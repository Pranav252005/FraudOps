"""Shape-directed fragment linking: join two candidates that a bounded,
time-ordered set of intermediaries says are two ends of one structure.

Pre-registered in `prereg/fragment_linking.md`. The measured problem, from
`docs/PHASE2-SEED-CHEAT-FINDINGS.md` §H2: **51% of cheat-rescued rings are
split across two or more components of their own induced subgraph**, against
5.7% of recovered ones. The honest seed is present and stranded in one
fragment; the rest of the ring is not reachable through ring edges at all,
only through unrelated intermediaries.

`suppress()` removes near-duplicates. Nothing joins two candidates that are
different *fragments* of one structure. This does.

THE MECHANISM, AND WHERE IT COMES FROM. BlazingAML (arXiv:2604.12241) builds
patterns by set intersection and difference rather than by expanding a
neighbourhood and searching inside it -- a scatter-gather is the intersection
of A's out-neighbours with B's in-neighbours, constructed rather than hoped
for. **The mechanism only; no code and no comparison to their results.**

Lifted from nodes to candidates: `C1` and `C2` are two ends of one structure
when the bridge

    X = out_neighbours(C1) ∩ in_neighbours(C2)

is non-empty, small, and time-ordered. That is a *witness*, not a proximity
score: two candidates that merely sit near each other do not qualify.

TWO DESIGN DECISIONS THAT ARE EASY TO GET WRONG, both fixed in the
pre-registration before any of this was measured:

  * **The merge excludes the bridge.** `merged = C1 | C2`. The intermediaries
    are the evidence that the fragments belong together, not a claim that they
    are ring members -- §H2 calls them unrelated. This is also the
    Jaccard-friendly choice, which is stated openly rather than left looking
    reverse-engineered. The consequence is that a merged candidate is
    disconnected in the induced subgraph, which is *correct*: the ring itself
    is disconnected in this window, and that is the whole finding.

  * **Merges are emitted in addition to their parents, never instead.**
    Linking may only add. If a merge is spurious the originals are still
    there and the scorer can prefer them.
"""
from __future__ import annotations

from collections import defaultdict

# Bounds, fixed in prereg/fragment_linking.md before the first run.
MAX_CANDIDATES = 200      # pairwise witness search is quadratic in this
MAX_BRIDGE = 3            # a wide bridge is a hub, not a link
MAX_MERGED_NODES = 40     # above this it is a cluster, not a case
# An intermediary shared by this many candidates on one side is a
# thoroughfare, not a witness. Bounds the pair generation, which is otherwise
# quadratic in the busiest node.
MAX_WITNESS_FANOUT = 20


def _boundary(nodes: frozenset[int], graph, max_degree: int):
    """(out-neighbours, in-neighbours) of a candidate, excluding its members.

    High-degree neighbours are excluded, matching the expansion hub guard: an
    intermediary with hundreds of counterparties is a correspondent account,
    and a "link" through one says nothing about the two candidates. Excluding
    them here is also what keeps these sets small enough to intersect --
    measured mean full-graph degree of a candidate member in this window is in
    the hundreds.
    """
    outs: set[int] = set()
    ins: set[int] = set()
    for n in nodes:
        for d in graph.out_adj.get(n, ()):
            if d not in nodes and len(graph.neighbours(d)) <= max_degree:
                outs.add(d)
        for s in graph.in_adj.get(n, ()):
            if s not in nodes and len(graph.neighbours(s)) <= max_degree:
                ins.add(s)
    return outs, ins


def _earliest_out(nodes: frozenset[int], x: int, graph):
    """Earliest time any member of `nodes` paid `x`, or None."""
    best = None
    for n in nodes:
        if x in graph.out_adj.get(n, ()):
            agg = graph.pairs.get((n << 32) | x)
            if agg is not None and (best is None or agg.first_t < best):
                best = agg.first_t
    return best


def _latest_in(x: int, nodes: frozenset[int], graph):
    """Latest time `x` paid any member of `nodes`, or None."""
    best = None
    for n in nodes:
        if n in graph.out_adj.get(x, ()):
            agg = graph.pairs.get((x << 32) | n)
            if agg is not None and (best is None or agg.last_t > best):
                best = agg.last_t
    return best


def _temporally_ordered(c1: frozenset[int], x: int, c2: frozenset[int],
                        graph) -> bool:
    """Could value have travelled C1 -> x -> C2?

    Same logic as `motifs.is_temporally_valid`: a pair may transact several
    times, so the test asks whether *some* choice is consistent, using the
    earliest feasible arrival and the latest feasible departure.
    """
    t_in = _earliest_out(c1, x, graph)
    if t_in is None:
        return False
    t_out = _latest_in(x, c2, graph)
    return t_out is not None and t_out >= t_in


def find_links(candidates, graph, max_degree: int = 50,
               max_candidates: int = MAX_CANDIDATES,
               max_bridge: int = MAX_BRIDGE,
               max_merged: int = MAX_MERGED_NODES,
               min_nodes: int = 3):
    """Ordered pairs of candidate indices that a bridge witnesses, with it.

    Returns a list of `(i, j, bridge)` where `bridge` is the witnessing
    intermediary set, `i` and `j` index into `candidates[:max_candidates]`,
    and the merge `candidates[i].nodes | candidates[j].nodes` satisfies the
    size bounds.

    An inverted index over boundary nodes keeps this near-linear in the number
    of *witnesses* rather than quadratic in the number of candidates: only
    pairs sharing at least one eligible intermediary can be linked at all, so
    the 200x200 comparison never happens.
    """
    pool = list(candidates[:max_candidates])
    if len(pool) < 2:
        return []

    bounds = [_boundary(frozenset(c.nodes), graph, max_degree) for c in pool]
    by_out: dict[int, list[int]] = defaultdict(list)
    by_in: dict[int, list[int]] = defaultdict(list)
    for i, (outs, ins) in enumerate(bounds):
        for x in outs:
            by_out[x].append(i)
        for x in ins:
            by_in[x].append(i)

    witnesses: dict[tuple[int, int], set[int]] = defaultdict(set)
    for x, senders in by_out.items():
        receivers = by_in.get(x)
        if not receivers:
            continue
        # A thoroughfare, not a witness.
        if len(senders) > MAX_WITNESS_FANOUT or len(receivers) > MAX_WITNESS_FANOUT:
            continue
        for i in senders:
            for j in receivers:
                if i != j:
                    witnesses[(i, j)].add(x)

    out = []
    for (i, j), bridge in witnesses.items():
        if not 0 < len(bridge) <= max_bridge:
            continue
        ni, nj = frozenset(pool[i].nodes), frozenset(pool[j].nodes)
        if len(ni) < min_nodes or len(nj) < min_nodes:
            continue
        merged = ni | nj
        # Nothing to assemble if one already contains the other.
        if len(merged) == len(ni) or len(merged) == len(nj):
            continue
        if len(merged) > max_merged:
            continue
        if not any(_temporally_ordered(ni, x, nj, graph) for x in bridge):
            continue
        out.append((i, j, frozenset(bridge)))
    # Deterministic: witness discovery walks dict iteration order, which is
    # insertion order over a set-derived sequence. Sorting makes the emitted
    # merge set independent of that.
    out.sort(key=lambda t: (t[0], t[1], sorted(t[2])))
    return out
