"""S1/S2: the second seed predicate, its control arm, and the budget that
makes the comparison mean anything.

The shipped seed rule fires only on pass-through accounts. BIPARTITE, FAN-OUT,
RANDOM and STACK contain no such account by construction, so those four
typologies are unreachable at any scoring quality — the largest structural loss
in the funnel (`docs/graph-review/2026-09-04.md` §2a).

The properties asserted here are the ones the experiment's validity rests on,
not the ones its result rests on:

  * the shipped arm is unchanged, exactly;
  * every arm spends the same budget, so a difference between arms is a
    difference in criterion and not in spend;
  * the new score is non-zero for shapes the pass-through rule cannot see,
    which is the entire reason for adding it;
  * every arm is deterministic, including the random one.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.detect import candidates as C  # noqa: E402
from sentinel.detect.layers import (SMURF_WIDTH_SATURATION,  # noqa: E402
                                    node_smurf_score)


class FakeGraph:
    """Just the adjacency surface `node_smurf_score` and `seeds` read."""

    def __init__(self, edges):
        self.out_adj = defaultdict(set)
        self.in_adj = defaultdict(set)
        for a, b in edges:
            self.out_adj[a].add(b)
            self.in_adj[b].add(a)

    def neighbours(self, n):
        return self.out_adj.get(n, set()) | self.in_adj.get(n, set())


class FakeBatch:
    def __init__(self, edges):
        self.src = [a for a, _ in edges]
        self.dst = [b for _, b in edges]

    def __len__(self):
        return len(self.src)


W = SMURF_WIDTH_SATURATION


def passthrough(w=W):
    """w senders -> 0 -> w receivers, nothing else."""
    return ([(i, 0) for i in range(1, w + 1)]
            + [(0, 100 + i) for i in range(1, w + 1)])


def fan_out(w=8):
    """0 -> w sinks. No inbound at all, so the shipped rule cannot seed it."""
    return [(0, i) for i in range(1, w + 1)]


def fan_in(w=8):
    return [(i, 0) for i in range(1, w + 1)]


# -- the score itself -------------------------------------------------------

def test_a_pure_passthrough_hub_scores_at_the_top():
    score, width = node_smurf_score(FakeGraph(passthrough()), 0)
    assert score == pytest.approx(1.0)
    assert width == 2 * W


@pytest.mark.parametrize("edges", [fan_out(), fan_in()],
                         ids=["fan_out_source", "fan_in_sink"])
def test_the_score_is_positive_for_shapes_the_shipped_rule_cannot_seed(edges):
    """The whole point of the experiment, asserted directly.

    A fan-out source has no inbound edge and a fan-in sink has no outbound one,
    so neither is pass-through and neither can ever be seeded today. If the new
    score were also zero on them, S1 could not possibly reach the four
    typologies it exists to reach, and the experiment would be void before it
    ran.
    """
    g = FakeGraph(edges)
    assert not (g.out_adj.get(0) and g.in_adj.get(0)), "not a fan shape"
    score, _ = node_smurf_score(g, 0)
    assert score > 0.5


def test_contamination_lowers_the_score():
    clean = node_smurf_score(FakeGraph(passthrough()), 0)[0]
    # Senders paying each other, and a sender bypassing the hub to a receiver.
    dirty = node_smurf_score(
        FakeGraph(passthrough() + [(1, 2), (2, 3), (1, 101), (2, 102)]), 0)[0]
    assert dirty < clean


def test_a_narrow_shape_scores_below_a_wide_one_at_equal_cleanliness():
    narrow = node_smurf_score(FakeGraph([(1, 0), (0, 2)]), 0)[0]
    wide = node_smurf_score(FakeGraph(passthrough()), 0)[0]
    assert 0 < narrow < wide


def test_the_hub_guard_returns_zero_rather_than_paying_for_a_hub():
    huge = [(i, 0) for i in range(1, 400)]
    score, width = node_smurf_score(FakeGraph(huge), 0, max_width=50)
    assert score == 0.0
    assert width > 50


def test_an_isolated_node_scores_zero_without_raising():
    assert node_smurf_score(FakeGraph([(1, 2)]), 99) == (0.0, 0)


# -- the seeding arms -------------------------------------------------------

def _gen(edges, strategy, budget=0.10):
    g = FakeGraph(edges)
    return g, C.CandidateGenerator(g, seed_strategy=strategy,
                                   seed_budget=budget)


def _scenario():
    """Pass-through hubs (seedable today) plus fan shapes (not seedable)."""
    edges = []
    for h in (0, 10, 20, 30):                 # four pass-through hubs
        edges += [(h + 1000 + i, h) for i in range(1, 4)]
        edges += [(h, h + 2000 + i) for i in range(1, 4)]
    edges += [(500, 5000 + i) for i in range(1, 9)]     # fan-out source
    edges += [(6000 + i, 501) for i in range(1, 9)]     # fan-in sink
    return edges


def test_the_shipped_arm_is_exactly_the_pass_through_rule():
    edges = _scenario()
    g, gen = _gen(edges, C.SEED_PASSTHROUGH)
    batch = FakeBatch(edges)
    got = gen.seeds(batch)
    want = {n for n in set(batch.src) | set(batch.dst)
            if g.out_adj.get(n) and g.in_adj.get(n)}
    assert got == want
    assert gen.stats["seeds_extra"] == 0


@pytest.mark.parametrize("strategy", [C.SEED_GARGAML, C.SEED_DEGREE_BURST,
                                      C.SEED_RANDOM])
def test_every_arm_is_a_superset_of_the_shipped_arm(strategy):
    """The arms ADD seeds. None of them may remove one, or the comparison is
    against a different detector rather than an extended one."""
    edges = _scenario()
    batch = FakeBatch(edges)
    _, base_gen = _gen(edges, C.SEED_PASSTHROUGH)
    base = base_gen.seeds(batch)
    _, gen = _gen(edges, strategy, budget=0.5)
    assert gen.seeds(batch) >= base


@pytest.mark.parametrize("strategy", [C.SEED_GARGAML, C.SEED_DEGREE_BURST,
                                      C.SEED_RANDOM])
def test_every_arm_spends_exactly_the_same_budget(strategy):
    """The property the experiment's attribution depends on.

    If one arm could spend more seeds than another, a funnel gain would be
    unattributable — it could be the criterion or it could be the spend. The
    review's kill rule for S1 is precisely this.
    """
    edges = _scenario()
    batch = FakeBatch(edges)
    _, gen = _gen(edges, strategy, budget=0.5)
    seeds = gen.seeds(batch)
    n_base = gen.stats["seeds_passthrough"]
    assert gen.stats["seed_budget"] == int(0.5 * n_base)
    assert gen.stats["seeds_extra"] <= gen.stats["seed_budget"]
    assert len(seeds) == n_base + gen.stats["seeds_extra"]


def test_a_zero_budget_reduces_every_arm_to_the_shipped_one():
    edges = _scenario()
    batch = FakeBatch(edges)
    _, base_gen = _gen(edges, C.SEED_PASSTHROUGH)
    base = base_gen.seeds(batch)
    for strategy in (C.SEED_GARGAML, C.SEED_DEGREE_BURST, C.SEED_RANDOM):
        _, gen = _gen(edges, strategy, budget=0.0)
        assert gen.seeds(batch) == base, strategy


@pytest.mark.parametrize("strategy", [C.SEED_GARGAML, C.SEED_DEGREE_BURST,
                                      C.SEED_RANDOM])
def test_every_arm_is_deterministic_including_the_random_one(strategy):
    """The random arm keys a per-node RNG on the node id rather than drawing
    from a shared stream, so its seed set does not depend on set iteration
    order. Otherwise the determinism gate would fail for the experiment's own
    reasons."""
    edges = _scenario()
    batch = FakeBatch(edges)
    runs = []
    for _ in range(3):
        _, gen = _gen(edges, strategy, budget=0.5)
        runs.append(frozenset(gen.seeds(batch)))
    assert len(set(runs)) == 1


def test_the_gargaml_arm_prefers_the_fan_shapes_over_arbitrary_leaves():
    """S1's substantive claim, on a scenario built to expose it.

    The pool of non-pass-through accounts here is dominated by degree-1 leaves
    (the tails of the pass-through hubs). The two structures worth reaching are
    the fan-out source and the fan-in sink. A predicate that could not put them
    above the leaves would have nothing to offer.
    """
    edges = _scenario()
    batch = FakeBatch(edges)
    # Budget 1.0: the scenario has only four pass-through hubs, so a realistic
    # 0.10 budget rounds to zero extra seeds and the test would pass vacuously
    # on an empty set. One-for-one is the smallest budget that exercises the
    # ranking at this scale.
    _, gen = _gen(edges, C.SEED_GARGAML, budget=1.0)
    extra = gen.seeds(batch) - {n for n in set(batch.src) | set(batch.dst)
                                if gen.graph.out_adj.get(n)
                                and gen.graph.in_adj.get(n)}
    assert {500, 501} <= extra, sorted(extra)


def test_an_unknown_strategy_is_refused_at_construction():
    with pytest.raises(ValueError, match="unknown seed strategy"):
        C.CandidateGenerator(FakeGraph([]), seed_strategy="hopeful")
