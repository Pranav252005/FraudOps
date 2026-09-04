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

from collections import deque
from dataclasses import dataclass, field

from sentinel.config import (EXPAND_HOPS, EXPAND_MAX_DEGREE, EXPAND_MAX_NODES,
                             PRUNE_STRATEGY)
from sentinel.detect import features as F
from sentinel.detect.merge import (DEFAULT_THRESHOLD, SUPPRESS_SCORE,
                                   suppress)
from sentinel.detect.motifs import Motifs, detect
from sentinel.detect.layers import node_smurf_score
from sentinel.detect.prune import prune as prune_candidate

MIN_NODES = 3          # two accounts have no structure to detect
MIN_EDGES = 2

# -- seed strategies (experiments S1 / S2) -----------------------------------
#
# The shipped rule fires only on pass-through accounts, which BIPARTITE,
# FAN-OUT, RANDOM and STACK do not contain by construction -- so those four
# typologies are unreachable at any scoring quality
# (docs/graph-review/2026-09-04.md 2a). These add a bounded number of
# non-pass-through seeds on top of it.
#
# Every arm spends the SAME budget, which is the whole point. A rule that
# reaches more rings by firing more often has not found a better predicate, it
# has bought recall with candidates, and the funnel stops meaning anything.
# Holding the budget equal across arms is what makes any difference between
# them attributable to the criterion.
SEED_PASSTHROUGH = "passthrough"          # shipped
SEED_GARGAML = "passthrough+gargaml"      # S1
SEED_DEGREE_BURST = "passthrough+degree"  # S2, the control arm
SEED_RANDOM = "passthrough+random"        # the null: same budget, no criterion
SEED_STRATEGIES = (SEED_PASSTHROUGH, SEED_GARGAML, SEED_DEGREE_BURST,
                   SEED_RANDOM)

# Extra seeds as a fraction of the pass-through count. Pre-registered in
# prereg/seed_predicate.md before any arm was run.
SEED_BUDGET = 0.10

# -- seed lookback (experiment P0) -------------------------------------------
#
# `seeds()` draws from the accounts touched in ONE tick, while the generator
# expands into a WINDOW_MINUTES graph -- 1 hour against 72. Cycles fire every
# 6 ticks, so five of every six ticks are never sampled for seeds at all.
#
# Measured over data/stream with the evals' own active_rings semantics: of 259
# active rings, 237 are touched in a seed tick and 230 of those are also
# pass-through (which is what the funnel reports as "seeded"). 22 rings are
# reachable ONLY by widening this source, and none are unreachable from the
# whole window. See prereg/seed_lookback.md and docs/GRAPH-PRIOR-ART-PLAN.md 2.
#
# 1 is the shipped value and is byte-identical to the original implementation:
# with a lookback of 1 the deque is never populated and `seeds` reads the batch
# it was handed, exactly as before.
SEED_LOOKBACK_TICKS = 1


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


def _touched(batch) -> set[int]:
    """Accounts appearing on either side of one tick's edges."""
    out: set[int] = set()
    if len(batch):
        out.update(int(x) for x in batch.src)
        out.update(int(x) for x in batch.dst)
    return out


def canonical_key(nodes) -> str:
    """Stable identity for a member set, independent of discovery order."""
    return ",".join(str(n) for n in sorted(nodes))


class CandidateGenerator:
    def __init__(self, graph, registry=None, node_key=None,
                 hops: int = EXPAND_HOPS,
                 max_nodes: int = EXPAND_MAX_NODES,
                 max_degree: int = EXPAND_MAX_DEGREE,
                 min_nodes: int = MIN_NODES,
                 prune_strategy: str = PRUNE_STRATEGY,
                 seed_strategy: str = SEED_PASSTHROUGH,
                 seed_budget: float = SEED_BUDGET,
                 suppress_ordering: str = SUPPRESS_SCORE,
                 seed_lookback_ticks: int = SEED_LOOKBACK_TICKS):
        self.graph = graph
        self.registry = registry
        self.node_key = node_key
        self.hops = hops
        self.max_nodes = max_nodes
        self.max_degree = max_degree
        self.min_nodes = min_nodes
        self.prune_strategy = prune_strategy
        if seed_strategy not in SEED_STRATEGIES:
            raise ValueError(f"unknown seed strategy {seed_strategy!r}; "
                             f"expected one of {SEED_STRATEGIES}")
        self.seed_strategy = seed_strategy
        self.seed_budget = seed_budget
        # Which member of an overlapping group survives suppression. The
        # shipped `score` ordering makes the scorer part of the generator; see
        # sentinel/detect/merge.py and prereg/suppression_key.md.
        self.suppress_ordering = suppress_ordering
        if seed_lookback_ticks < 1:
            raise ValueError("seed_lookback_ticks must be >= 1, got "
                             f"{seed_lookback_ticks}")
        self.seed_lookback_ticks = seed_lookback_ticks
        # Populated only by `observe()`, and only when a lookback is asked for.
        # A generator whose caller never calls `observe` behaves exactly as it
        # did before this parameter existed.
        self._recent_touched: deque = deque(maxlen=seed_lookback_ticks)
        self._last_observed_end: int | None = None
        self.last_seeds: set[int] = set()
        self.stats = {
            "seeds": 0, "expanded": 0, "deduped": 0,
            "too_small": 0, "emitted": 0, "suppressed": 0,
            "pruned_nodes": 0,
            # Split out so a funnel gain can be attributed to the arm that
            # bought it rather than to "more seeds".
            "seeds_passthrough": 0, "seeds_extra": 0, "seed_budget": 0,
            # How many ticks the lookback actually saw. A harness can assert
            # this rather than trusting that observe() was wired up.
            "observed_ticks": 0,
        }

    def _expansion_signature(self) -> tuple:
        """The parameters an expansion result depends on. Deliberately excludes
        `prune_strategy`, which is applied after expansion, and `min_nodes`,
        which only filters."""
        return (self.hops, self.max_nodes, self.max_degree, id(self.graph))

    # -- seeding --------------------------------------------------------------

    def observe(self, batch) -> None:
        """Record one tick's touched accounts, for the seed lookback.

        Must be called on EVERY tick, not only on cycle ticks. This is
        ENFORCED rather than documented: a caller that observes only cycle
        ticks would get a lookback six times longer than the number says, and
        every metric would look plausible. `seed_lookback_ticks` is the one
        parameter in this class whose misuse produces no error and no visible
        symptom, so it is the one that gets guards.

        A no-op at the shipped lookback of 1, so a caller that never calls this
        gets exactly the pre-P0 behaviour -- which is what keeps the fixture
        fingerprint and the shipped path unchanged.
        """
        if self.seed_lookback_ticks <= 1:
            return
        t_start = getattr(batch, "t_start", None)
        t_end = getattr(batch, "t_end", None)
        if t_start is None or t_end is None:
            raise TypeError(
                "observe() needs a batch carrying t_start and t_end to check "
                "that ticks are contiguous; got "
                f"{type(batch).__name__} without them. A lookback that cannot "
                "verify its own tick spacing is a lookback of unknown length.")
        if (self._last_observed_end is not None
                and t_start != self._last_observed_end):
            raise ValueError(
                f"observe() got a non-contiguous tick: this batch starts at "
                f"{t_start} but the previous one ended at "
                f"{self._last_observed_end}. seed_lookback_ticks counts TICKS, "
                f"so observing every Nth tick makes the lookback N times "
                f"longer than it says while every metric still looks "
                f"plausible. Call observe() on every tick.")
        self._recent_touched.append(_touched(batch))
        self._last_observed_end = t_end
        self.stats["observed_ticks"] += 1

    def seeds(self, batch) -> set[int]:
        """Accounts touched this tick that are pass-through in the window.

        Pass-through -- money in and money out -- is the mule signature and was
        the best measured cheap trigger: 78.6% recall over ring accounts at 2.0x
        lift. It is not selective on its own; selectivity comes from the
        structure and scoring stages, not from the seed.
        """
        if self.seed_lookback_ticks > 1:
            if not self._recent_touched:
                raise RuntimeError(
                    f"seed_lookback_ticks={self.seed_lookback_ticks} but "
                    f"observe() was never called, so the lookback is empty and "
                    f"seeding would silently fall back to this single batch -- "
                    f"i.e. behave as lookback 1 while reporting "
                    f"{self.seed_lookback_ticks}. Call observe() on every tick.")
            end = getattr(batch, "t_end", None)
            if end is not None and end != self._last_observed_end:
                raise RuntimeError(
                    f"seeding a batch ending at {end} but the last observed "
                    f"tick ended at {self._last_observed_end}. observe() and "
                    f"generate() are out of step, so the lookback does not "
                    f"include the tick being seeded.")
        touched = (set().union(*self._recent_touched)
                   if self._recent_touched else _touched(batch))
        g = self.graph
        base = {n for n in touched
                if g.out_adj.get(n) and g.in_adj.get(n)}
        self.stats["seeds_passthrough"] += len(base)
        if self.seed_strategy == SEED_PASSTHROUGH:
            return base
        return base | self._extra_seeds(touched - base, len(base))

    def _extra_seeds(self, pool: set[int], n_base: int) -> set[int]:
        """The bounded second predicate: at most `seed_budget * n_base` more.

        `pool` is the accounts touched this tick that the pass-through rule
        refused -- receive-only sinks, send-only sources, the sides of a
        BIPARTITE and the ends of a FAN. Every arm ranks this same pool by a
        different criterion and takes the same number off the top, so the arms
        differ in what they believe, not in how much they spend.

        Ordering is fully deterministic in every arm, including the random one:
        ties break on node id, and the random arm keys a per-node RNG on the
        node id rather than drawing from a shared stream. A seed set that
        depended on iteration order would make the determinism gate fail for
        the experiment's own reasons.
        """
        budget = int(self.seed_budget * n_base)
        self.stats["seed_budget"] += budget
        if budget <= 0 or not pool:
            return set()
        g = self.graph

        if self.seed_strategy == SEED_RANDOM:
            import random as _random
            ranked = sorted(pool, key=lambda n: (_random.Random(n).random(), n))
        elif self.seed_strategy == SEED_DEGREE_BURST:
            # The control arm: width alone, with the same hub guard S1 uses so
            # the two arms see the same eligible pool.
            def width(n):
                w = len(g.neighbours(n))
                return w if w <= self.max_degree else 0
            ranked = sorted(pool, key=lambda n: (-width(n), n))
        else:  # SEED_GARGAML
            scored = [(node_smurf_score(g, n, max_width=self.max_degree), n)
                      for n in pool]
            ranked = [n for (score, w), n in
                      sorted(scored, key=lambda sn: (-sn[0][0], -sn[0][1], sn[1]))]

        extra = set(ranked[:budget])
        self.stats["seeds_extra"] += len(extra)
        return extra

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
        # Exposed so an evaluation harness can report the seed set this
        # cycle actually used without calling `seeds()` a second time --
        # which would double-count the budget counters and quietly break
        # the equal-spend property the S1/S2 attribution rests on.
        self.last_seeds = seeds
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
            out = suppress(out, threshold=merge_threshold,
                           ordering=self.suppress_ordering)
            self.stats["suppressed"] += before - len(out)
        out.sort(key=lambda c: -c.score)
        return out
