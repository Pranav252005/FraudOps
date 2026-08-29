"""Candidate generation: the seed-and-expand funnel.

Measured against this dataset, expanding two hops from a *single* ring member
recovers a median 100% of that ring, and the resulting neighbourhood is median
14 nodes with 99% under 60 -- small enough to be a case an analyst can work.
Leiden on the same window put 98% of covered rings inside 4,000+ node
communities, which is why clustering is not the primary path here.

The funnel is:

    tick -> pass-through seeds -> 2-hop bounded expansion -> dedup -> score

Dedup matters more than it looks. Neighbours of neighbours overlap heavily, so
without a canonical key on the member set the same candidate is rebuilt and
re-scored dozens of times per tick.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sentinel.config import (EXPAND_HOPS, EXPAND_MAX_DEGREE, EXPAND_MAX_NODES,
                             PRUNE_STRATEGY)
from sentinel.detect import features as F
from sentinel.detect.merge import DEFAULT_THRESHOLD, suppress
from sentinel.detect.motifs import Motifs, detect
from sentinel.detect.prune import prune as prune_candidate

MIN_NODES = 3          # two accounts have no structure to detect
MIN_EDGES = 2


@dataclass
class Candidate:
    """One scored neighbourhood, before it becomes a case."""

    key: str
    nodes: frozenset[int]
    seed: int
    t: int                              # tick end, minutes since epoch
    score: float = 0.0
    contrib: dict = field(default_factory=dict)
    features: F.Features = field(default_factory=F.Features)
    motifs: Motifs = field(default_factory=Motifs)
    # How many near-duplicate views of this neighbourhood were suppressed into
    # it. Shown in the case file as corroboration rather than discarded.
    absorbed: int = 0
    absorbed_seeds: list = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.nodes)


def canonical_key(nodes) -> str:
    """Stable identity for a member set, independent of discovery order."""
    return ",".join(str(n) for n in sorted(nodes))


class CandidateGenerator:
    def __init__(self, graph, registry=None, node_key=None,
                 hops: int = EXPAND_HOPS,
                 max_nodes: int = EXPAND_MAX_NODES,
                 max_degree: int = EXPAND_MAX_DEGREE,
                 min_nodes: int = MIN_NODES,
                 prune_strategy: str = PRUNE_STRATEGY):
        self.graph = graph
        self.registry = registry
        self.node_key = node_key
        self.hops = hops
        self.max_nodes = max_nodes
        self.max_degree = max_degree
        self.min_nodes = min_nodes
        self.prune_strategy = prune_strategy
        self.stats = {
            "seeds": 0, "expanded": 0, "deduped": 0,
            "too_small": 0, "emitted": 0, "suppressed": 0,
            "pruned_nodes": 0,
        }

    def _expansion_signature(self) -> tuple:
        """The parameters an expansion result depends on. Deliberately excludes
        `prune_strategy`, which is applied after expansion, and `min_nodes`,
        which only filters."""
        return (self.hops, self.max_nodes, self.max_degree, id(self.graph))

    # -- seeding --------------------------------------------------------------

    def seeds(self, batch) -> set[int]:
        """Accounts touched this tick that are pass-through in the window.

        Pass-through -- money in and money out -- is the mule signature and was
        the best measured cheap trigger: 78.6% recall over ring accounts at 2.0x
        lift. It is not selective on its own; selectivity comes from the
        structure and scoring stages, not from the seed.
        """
        touched: set[int] = set()
        if len(batch):
            touched.update(int(x) for x in batch.src)
            touched.update(int(x) for x in batch.dst)
        g = self.graph
        return {n for n in touched
                if g.out_adj.get(n) and g.in_adj.get(n)}

    # -- generation -----------------------------------------------------------

    def generate(self, batch, seen: set[str] | None = None,
                 merge_threshold: float | None = DEFAULT_THRESHOLD,
                 seed_override: set[int] | None = None,
                 expansion_cache: dict | None = None) -> list[Candidate]:
        """Produce scored candidates for one tick, overlap-suppressed.

        `seed_override` replaces the pass-through seed rule entirely when
        given. It exists for the oracle diagnostic in
        `scripts/eval_oracle.py`, which measures the ceiling if seeding were
        perfect by seeding on every active ring's own members -- never used
        by the real detection path, which always calls `self.seeds(batch)`.

        `expansion_cache` is a caller-owned {seed: frozenset(nodes)} map for
        one tick. Expansion depends only on (seed, graph, hops, max_nodes,
        max_degree) -- never on the prune strategy -- so an A/B harness running
        two strategies over the same tick can expand once and hand both runs
        the same neighbourhood. It is the caller's job to use one cache per
        tick and only across generators with identical expansion bounds;
        `_expansion_signature` is asserted against the cache to make a misuse
        raise instead of silently returning another configuration's answer.
        """
        g = self.graph
        seen = set() if seen is None else seen
        out: list[Candidate] = []

        seeds = self.seeds(batch) if seed_override is None else set(seed_override)
        self.stats["seeds"] += len(seeds)

        if expansion_cache is not None:
            sig = self._expansion_signature()
            cached_sig = expansion_cache.setdefault("__signature__", sig)
            assert cached_sig == sig, (
                f"expansion_cache was built with bounds {cached_sig} but this "
                f"generator uses {sig}; sharing it would return another "
                f"configuration's neighbourhoods")

        for seed in seeds:
            if expansion_cache is None:
                nodes = g.expand([seed], hops=self.hops,
                                 max_nodes=self.max_nodes,
                                 max_degree=self.max_degree)
                self.stats["expanded"] += 1
            else:
                hit = expansion_cache.get(seed)
                if hit is None:
                    hit = expansion_cache[seed] = g.expand(
                        [seed], hops=self.hops, max_nodes=self.max_nodes,
                        max_degree=self.max_degree)
                    self.stats["expanded"] += 1
                # Copy: prune and the caller downstream must not be able to
                # mutate a set another strategy will still read.
                nodes = set(hit)

            # Prune the expansion by-products before anything downstream sees
            # the candidate. Deliberately ahead of the dedup key: two seeds
            # whose raw neighbourhoods differed only by passengers collapse to
            # the same member set once pruned, which is a real dedup win
            # rather than a coincidence.
            if self.prune_strategy and self.prune_strategy != "none":
                before = len(nodes)
                nodes = prune_candidate(nodes, seed, g, self.prune_strategy,
                                         min_nodes=self.min_nodes)
                self.stats["pruned_nodes"] += before - len(nodes)

            if len(nodes) < self.min_nodes:
                self.stats["too_small"] += 1
                continue

            key = canonical_key(nodes)
            if key in seen:
                self.stats["deduped"] += 1
                continue
            seen.add(key)

            edges = g.subgraph_edges(nodes)
            if len(edges) < MIN_EDGES:
                self.stats["too_small"] += 1
                continue

            motifs = detect(edges)
            # `edges` is threaded into build rather than recomputed there.
            # Profiling counted 171,479 `subgraph_edges` calls for 57,233
            # candidates -- three per candidate, from prune, from here, and
            # from features.build. Two of those three are the same call on the
            # same node set, so one of them is pure waste. (The third, inside
            # prune, runs on the *pre*-prune node set and genuinely cannot be
            # shared.)
            feats = F.build(nodes, g, motifs, registry=self.registry,
                            node_key=self.node_key, internal_edges=edges)
            s, contrib = F.score(feats)

            out.append(Candidate(
                key=key, nodes=frozenset(nodes), seed=seed, t=batch.t_end,
                score=s, contrib=contrib, features=feats, motifs=motifs,
            ))
            self.stats["emitted"] += 1

        if merge_threshold is not None:
            before = len(out)
            out = suppress(out, threshold=merge_threshold)
            self.stats["suppressed"] += before - len(out)
        out.sort(key=lambda c: -c.score)
        return out
