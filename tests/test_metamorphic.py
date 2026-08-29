"""Metamorphic relations: properties of *related inputs*, needing no oracle.

Section 6.2 of docs/ARCHITECTURE_UPLIFT.md. Metamorphic testing checks that a
known transformation of the input produces a known transformation of the output
(Chen et al., ACM CSUR 2018). It fits this project exactly, because there is no
ground truth for "what should this candidate's score be" -- but there is a
certain answer to "what should happen to it if every amount is doubled".

Each relation below corresponds to a family in the bug catalogue:

  relabelling      hash / set-iteration-order dependence
  time translation epoch and window arithmetic (bug #7's family)
  amount scaling   units and rounding (bug #6's family)
  edge duplication multigraph vs simple-graph confusion
  prune            the docstring promises in prune.py, never asserted

The plan pre-registers that relabelling is expected to FIRE, because
`expand_traced` truncates by `sorted(nxt, key=degree)` with arbitrary
tie-breaking over a set. Where a relation is known not to hold exactly, the
test states precisely how far it does hold rather than being weakened until it
passes -- a test tuned until green measures nothing.
"""
from __future__ import annotations

import pytest

from sentinel.detect import features as F
from sentinel.detect.candidates import CandidateGenerator
from sentinel.detect.motifs import detect
from sentinel.detect.prune import LEAF2, NEAR_OR_LINKED, prune
from sentinel.graph.window import WindowedGraph
from tests.test_phase1 import batch

# A small structure with a genuine passthrough chain, a cycle, a fan and some
# background, so the transformations below have something to move.
EDGES = [
    # (t, src, dst, amount)
    (1, 100, 101, 5000.0), (3, 101, 102, 4800.0), (5, 102, 103, 4600.0),
    (7, 103, 100, 4400.0),                      # cycle back to the start
    (2, 200, 101, 900.0), (4, 101, 201, 850.0),  # passthrough across the ring
    (6, 300, 301, 12000.0), (8, 301, 302, 11500.0), (9, 301, 303, 400.0),
    (10, 301, 304, 300.0), (11, 301, 305, 250.0),   # a fan-out hub
    (12, 400, 301, 7000.0), (13, 305, 400, 120.0),
]


def build(edges, window=10_000):
    g = WindowedGraph(window_minutes=window)
    b = batch(0, 60, [(t, s, d, a, 0) for t, s, d, a in edges])
    g.add_batch(b)
    return g, b


def run(edges, window=10_000, **kw):
    g, b = build(edges, window)
    return g, CandidateGenerator(g, **kw).generate(b)


def summarise(cands):
    return [(c.key, round(c.score, 12), c.size) for c in cands]


# --------------------------------------------------------------------------
# relabelling
# --------------------------------------------------------------------------

class TestRelabelling:
    """Permuting node ids must permute the output, not change it."""

    def _relabelled(self, offset):
        mapping = {}

        def m(n):
            # A deliberately order-scrambling but injective relabelling: ids
            # keep no relationship to their originals, so anything that leaks
            # id ordering into a decision shows up here.
            return mapping.setdefault(n, (n * 7919 + offset) % 100_000)

        return [(t, m(s), m(d), a) for t, s, d, a in EDGES], mapping

    def test_candidate_member_sets_are_the_same_up_to_the_permutation(self):
        _, base = run(EDGES)
        base_sets = {frozenset(c.nodes) for c in base}

        for offset in (13, 977, 5001):
            edges, mapping = self._relabelled(offset)
            _, other = run(edges)
            inverse = {v: k for k, v in mapping.items()}
            other_sets = {frozenset(inverse[n] for n in c.nodes) for c in other}
            assert other_sets == base_sets, (
                f"relabelling with offset {offset} changed which candidates "
                f"exist. Only relabelled: {other_sets - base_sets}; only "
                f"original: {base_sets - other_sets}")

    def _cap_bound_graph(self):
        """A graph built so the node cap binds and every truncation candidate
        has identical degree -- the tie-break's worst case."""
        hub, spokes = 500, list(range(600, 640))
        edges = [(1, hub, s, 100.0) for s in spokes]
        edges += [(2, 999, hub, 100.0)]      # make the hub pass-through
        return edges, 12                      # cap far below the 41 reachable

    def test_node_cap_truncation_keeps_the_same_NUMBER_of_nodes(self):
        """The part of the relation that does hold, and is worth having.

        How many nodes survive truncation is a function of the cap and the
        graph's shape, so it is relabelling-invariant. *Which* ones survive is
        not -- see the xfail below.
        """
        edges, cap = self._cap_bound_graph()
        _, base = run(edges, max_nodes=cap, max_degree=1000)
        base_sizes = sorted(c.size for c in base)
        for offset in (13, 977, 5001):
            mapping: dict = {}

            def m(n, offset=offset, mapping=mapping):
                return mapping.setdefault(n, (n * 7919 + offset) % 100_000)

            _, other = run([(t, m(s), m(d), a) for t, s, d, a in edges],
                           max_nodes=cap, max_degree=1000)
            assert sorted(c.size for c in other) == base_sizes

    @pytest.mark.xfail(strict=True, reason=(
        "Known and now demonstrated: expand_traced truncates with "
        "sorted(nxt, key=degree)[:room] over a set, so when more nodes tie on "
        "degree than there is room for, WHICH survive depends on node ids. "
        "Recorded as xfail(strict) rather than deleted or weakened so that the "
        "day someone makes it pass, this line has to be revisited deliberately."))
    def test_node_cap_truncation_keeps_the_same_MEMBERS(self):
        """Pre-registered in docs/ARCHITECTURE_UPLIFT.md risk 4 as expected to
        fire. It does. Two findings that change what should be done about it:

        1. **The relation as the plan states it is unattainable, not merely
           unmet.** When the cap forces a choice among nodes that are identical
           in every intrinsic property (same degree, same amounts, same
           timestamps), any tie-break must use something extrinsic, and the
           only thing available is the node id. Adding `, n` to the sort key
           makes the result *deterministic* -- it cannot make it
           *relabelling-invariant*, because relabelling changes n. So this is
           not a bug to be fixed by a better tie-break; it is a property of
           truncating a tie.

        2. **It affects no reported number.** docs/HANDOFF.md 5c measured the
           expansion trace over 230 seeded rings and found `node_cap: 0
           occurrences` -- EXPAND_MAX_NODES is never the binding constraint on
           this dataset. This test has to construct a graph specifically to
           make the cap bind. So the defect is real, is untestable away, and is
           inert on the data every published figure comes from.
        """
        edges, cap = self._cap_bound_graph()
        _, base = run(edges, max_nodes=cap, max_degree=1000)
        base_sets = {frozenset(c.nodes) for c in base}
        for offset in (13, 977, 5001):
            mapping: dict = {}

            def m(n, offset=offset, mapping=mapping):
                return mapping.setdefault(n, (n * 7919 + offset) % 100_000)

            _, other = run([(t, m(s), m(d), a) for t, s, d, a in edges],
                           max_nodes=cap, max_degree=1000)
            inverse = {v: k for k, v in mapping.items()}
            other_sets = {frozenset(inverse[n] for n in c.nodes) for c in other}
            assert other_sets == base_sets

    def test_scores_are_unchanged_by_relabelling(self):
        _, base = run(EDGES)
        by_set = {frozenset(c.nodes): c.score for c in base}
        for offset in (13, 977, 5001):
            edges, mapping = self._relabelled(offset)
            _, other = run(edges)
            inverse = {v: k for k, v in mapping.items()}
            for c in other:
                key = frozenset(inverse[n] for n in c.nodes)
                assert c.score == pytest.approx(by_set[key], abs=1e-12)


# --------------------------------------------------------------------------
# time translation
# --------------------------------------------------------------------------

class TestTimeTranslation:
    """Shifting every timestamp by the same delta must change nothing.

    The window is a trailing interval, so a uniform shift moves the window with
    the data. Anything absolute in the epoch arithmetic breaks here -- bug #7's
    family.
    """

    @pytest.mark.parametrize("delta", [1, 60, 1440, 100_000])
    def test_outputs_are_invariant(self, delta):
        _, base = run(EDGES)
        shifted = [(t + delta, s, d, a) for t, s, d, a in EDGES]
        g = WindowedGraph(window_minutes=10_000)
        b = batch(delta, 60 + delta,
                  [(t, s, d, a, 0) for t, s, d, a in shifted])
        g.add_batch(b)
        other = CandidateGenerator(g).generate(b)

        assert [s[0] for s in summarise(base)] == [s[0] for s in summarise(other)]
        for a, c in zip(base, other):
            assert a.score == pytest.approx(c.score, abs=1e-12)
            assert a.features.span_minutes == c.features.span_minutes
            assert a.features.burstiness == pytest.approx(c.features.burstiness)


# --------------------------------------------------------------------------
# amount scaling
# --------------------------------------------------------------------------

class TestAmountScaling:
    """Multiplying every amount by c > 0 must leave every ratio alone.

    conservation, churn and passthrough_ratio are dimensionless; inflow,
    outflow, internal and total_amount must scale by exactly c. A feature that
    is neither invariant nor linear is carrying a hidden absolute threshold --
    bug #6's family.
    """

    @pytest.mark.parametrize("c", [0.5, 2.0, 1000.0])
    def test_ratios_invariant_and_totals_linear(self, c):
        g0, _ = build(EDGES)
        gc, _ = build([(t, s, d, a * c) for t, s, d, a in EDGES])
        nodes = {100, 101, 102, 103}

        f0 = F.build(nodes, g0, detect(g0.subgraph_edges(nodes)))
        fc = F.build(nodes, gc, detect(gc.subgraph_edges(nodes)))

        assert fc.conservation == pytest.approx(f0.conservation, rel=1e-9)
        assert fc.churn == pytest.approx(f0.churn, rel=1e-9)
        assert fc.passthrough_ratio == pytest.approx(f0.passthrough_ratio)
        assert fc.cycle_coverage == pytest.approx(f0.cycle_coverage)

        for field in ("inflow", "outflow", "internal", "total_amount"):
            assert getattr(fc, field) == pytest.approx(
                getattr(f0, field) * c, rel=1e-9), field

    def test_round_amount_ratio_is_not_scale_invariant_and_that_is_deliberate(self):
        """`is_round` is an absolute test (multiples of 100 / 1000), so it is
        the one amount feature that must NOT be scale-invariant. Asserted so a
        future 'fix' that normalises it is a visible, argued change rather than
        a silent one -- round-number structuring is a claim about the currency
        unit, not about the distribution's shape."""
        assert F.is_round(100.0) and not F.is_round(150.0)
        assert not F.is_round(100.0 * 1.5)


# --------------------------------------------------------------------------
# edge duplication
# --------------------------------------------------------------------------

class TestEdgeDuplication:
    """Adding another transaction on an existing pair must not change shape.

    The window aggregates per ordered pair, so a duplicate must move counts and
    amounts and nothing structural. A structural feature that moves here means
    something is treating the multigraph as a simple graph or vice versa.
    """

    def test_structure_unchanged_counts_and_amounts_move(self):
        nodes = {100, 101, 102, 103}
        g0, _ = build(EDGES)
        f0 = F.build(nodes, g0, detect(g0.subgraph_edges(nodes)))

        dup = EDGES + [(14, 101, 102, 4800.0)]
        g1, _ = build(dup)
        f1 = F.build(nodes, g1, detect(g1.subgraph_edges(nodes)))

        for field in ("n_nodes", "n_edges", "has_cycle", "shortest_cycle",
                      "cycle_coverage", "scatter_gather_width",
                      "gather_scatter_width", "fan_out_count", "fan_in_count",
                      "max_fan", "passthrough_ratio", "bipartite_score",
                      "stack_score", "layer_depth"):
            assert getattr(f1, field) == getattr(f0, field), field

        assert f1.n_txns == f0.n_txns + 1
        assert f1.internal == pytest.approx(f0.internal + 4800.0)


# --------------------------------------------------------------------------
# prune -- the promises prune.py's docstring makes and never asserted
# --------------------------------------------------------------------------

class TestPruneRelations:
    @pytest.mark.parametrize("strategy", [LEAF2, NEAR_OR_LINKED, "kcore2"])
    def test_result_is_a_subset_and_keeps_the_seed(self, strategy):
        g, _ = build(EDGES)
        nodes = set(g.out_adj) | set(g.in_adj)
        for seed in sorted(nodes):
            kept = prune(set(nodes), seed, g, strategy, min_nodes=3)
            assert kept <= nodes, f"{strategy} invented a node"
            assert seed in kept, f"{strategy} dropped the seed"
            assert len(kept) >= 3

    @pytest.mark.parametrize("strategy", [LEAF2, NEAR_OR_LINKED, "kcore2"])
    def test_containment_can_only_fall_or_hold_never_rise(self, strategy):
        """prune.py's docstring uses this to justify the BIPARTITE/STACK rescue
        argument in docs/HANDOFF.md 5e. Pruning only removes nodes, so the
        intersection with any fixed ring cannot grow. Stated there as a fact;
        made a test here."""
        g, _ = build(EDGES)
        nodes = set(g.out_adj) | set(g.in_adj)
        ring = {100, 101, 102, 103}
        before = len(nodes & ring) / len(ring)
        for seed in sorted(nodes):
            kept = prune(set(nodes), seed, g, strategy, min_nodes=3)
            after = len(kept & ring) / len(ring)
            assert after <= before + 1e-12, f"{strategy} raised containment"

    @pytest.mark.parametrize("strategy", [LEAF2, NEAR_OR_LINKED, "kcore2"])
    def test_pruning_is_idempotent_on_its_own_output(self, strategy):
        """Not promised anywhere, and worth knowing either way: a pruner that
        keeps shrinking under repetition is describing an unstable core."""
        g, _ = build(EDGES)
        nodes = set(g.out_adj) | set(g.in_adj)
        seed = 101
        once = prune(set(nodes), seed, g, strategy, min_nodes=3)
        twice = prune(set(once), seed, g, strategy, min_nodes=3)
        assert twice == once, (
            f"{strategy} is not idempotent: {len(once)} -> {len(twice)} nodes")

    def test_unknown_strategy_raises_rather_than_silently_passing_through(self):
        g, _ = build(EDGES)
        with pytest.raises(ValueError):
            prune({100, 101, 102, 103}, 100, g, "not_a_strategy", min_nodes=3)
