"""Candidate pruning: drop the passengers expansion drags in.

`scripts/diagnose_build.py` established the problem precisely. Two-hop
expansion already recovers the *entire* ring for six of eight typologies
(mean containment 0.90-1.00), but the neighbourhood it collects alongside --
roughly 15-20 nodes around a 4-10 node ring -- pushes Jaccard under the 0.3
hit floor. 88 of 230 seeded rings (38%) are found and then rejected for
carrying passengers, against only 27 (12%) never reached at all. Dilution,
not discovery, is the dominant loss at the build stage.

The tempting "fix" is to lower the Jaccard floor. That is bug #8 a second
time: a containment-only metric already let a node-count baseline tie the
real score once, and relaxing the floor would reclassify 88 rings as found
without the detector improving at all. Pruning is the honest version of the
same move -- it makes the candidate genuinely tighter, so Jaccard rises
because the candidate got better, not because the bar dropped.

Every strategy here must therefore be judged on **both** halves at once:
Jaccard must go up *without* containment falling. A pruner that raises
Jaccard by deleting ring members has made things worse while looking better,
which is exactly the failure mode this project keeps a bug catalogue for.

Strategies are deliberately plural and cheap so the choice is made by
measurement (`python scripts/diagnose_build.py --sweep`) rather than by
argument.
"""
from __future__ import annotations

from collections import defaultdict, deque

# Strategy names, exported so the sweep and the config agree on spelling.
NONE = "none"
LEAF2 = "leaf2"
KCORE2 = "kcore2"
NEAR_OR_LINKED = "near_or_linked"
STRATEGIES = (NONE, LEAF2, KCORE2, NEAR_OR_LINKED)


def _induced_adjacency(nodes: set[int], graph) -> dict[int, set[int]]:
    """Undirected adjacency restricted to `nodes`.

    Direction is dropped deliberately, matching `WindowedGraph.neighbours`:
    a mule receiving from one account and paying another is one structure,
    and treating those as unrelated would cut it in half.
    """
    adj: dict[int, set[int]] = defaultdict(set)
    for s, d, _ in graph.subgraph_edges(nodes):
        if s == d:
            continue
        adj[s].add(d)
        adj[d].add(s)
    return adj


def _hops_from(seed: int, adj: dict[int, set[int]], nodes: set[int]) -> dict[int, int]:
    """BFS hop distance from `seed` inside the induced subgraph."""
    dist = {seed: 0}
    q = deque([seed])
    while q:
        n = q.popleft()
        for m in adj.get(n, ()):
            if m not in dist and m in nodes:
                dist[m] = dist[n] + 1
                q.append(m)
    return dist


def prune(nodes: set[int], seed: int, graph, strategy: str = NONE,
          min_nodes: int = 3) -> set[int]:
    """Return a tightened member set for one candidate.

    Never returns fewer than `min_nodes` (the candidate would stop being a
    structure at all), and never drops the seed -- the seed is the reason
    this neighbourhood was built, so a pruner that discards it has changed
    the subject rather than tightened the answer.
    """
    if strategy == NONE or len(nodes) <= min_nodes:
        return set(nodes)

    nodes = set(nodes)
    adj = _induced_adjacency(nodes, graph)
    deg = {n: len(adj.get(n, ())) for n in nodes}

    if strategy == KCORE2:
        # Iteratively shed degree-<2 nodes: the classic 2-core. Aggressive,
        # and expected to damage FAN shapes, whose sinks legitimately have
        # induced degree 1. Included so that damage is measured rather than
        # assumed.
        keep = set(nodes)
        changed = True
        while changed and len(keep) > min_nodes:
            changed = False
            for n in list(keep):
                if n == seed:
                    continue
                d = sum(1 for m in adj.get(n, ()) if m in keep)
                if d < 2:
                    keep.discard(n)
                    changed = True
                    if len(keep) <= min_nodes:
                        break
        return keep if len(keep) >= min_nodes else set(nodes)

    dist = _hops_from(seed, adj, nodes)

    if strategy == LEAF2:
        # Drop only far leaves: a node two or more hops from the seed whose
        # sole tie to the candidate is the single edge that pulled it in.
        # These are pure expansion by-products. Nodes adjacent to the seed
        # are kept regardless of degree, which preserves FAN shapes.
        keep = {n for n in nodes
                if n == seed
                or dist.get(n, 99) <= 1
                or deg.get(n, 0) >= 2}
        return keep if len(keep) >= min_nodes else set(nodes)

    if strategy == NEAR_OR_LINKED:
        # Same intent as LEAF2 but stricter on the far ring: beyond one hop,
        # require two ties *and* that the node is not a dead end back toward
        # the seed. Keeps the well-attached far side of a scatter-gather
        # while dropping single-thread stragglers.
        keep = set()
        for n in nodes:
            if n == seed or dist.get(n, 99) <= 1:
                keep.add(n)
                continue
            if deg.get(n, 0) >= 2:
                keep.add(n)
        # Second pass: a kept far node whose neighbours were all dropped is
        # now itself a straggler.
        changed = True
        while changed and len(keep) > min_nodes:
            changed = False
            for n in list(keep):
                if n == seed or dist.get(n, 99) <= 1:
                    continue
                if sum(1 for m in adj.get(n, ()) if m in keep) < 2:
                    keep.discard(n)
                    changed = True
        return keep if len(keep) >= min_nodes else set(nodes)

    raise ValueError(f"unknown prune strategy {strategy!r}; "
                     f"expected one of {STRATEGIES}")
