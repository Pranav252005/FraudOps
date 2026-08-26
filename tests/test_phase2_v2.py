"""v2 additions: temporal cycles, gather-scatter, and the behavioural axis.

Temporal validity is the most important thing tested here. v1 counted any
structural cycle, and in a 244k-node graph triangles arise by chance constantly.
A cycle only means something if the timestamps allow value to actually travel
the loop, so these tests pin that distinction precisely.
"""
from __future__ import annotations

import networkx as nx
import pytest

from sentinel.detect import features as F
from sentinel.detect.motifs import (build_digraph, detect, find_gather_scatter,
                                    is_temporally_valid)
from sentinel.graph.stats import AccountStats, Moments
from sentinel.graph.window import WindowedGraph
from tests.test_phase1 import batch
from tests.test_phase2 import graph_from


def timed_graph(edges, window=10_000):
    """edges = [(ts, src, dst, amount)]"""
    g = WindowedGraph(window_minutes=window)
    g.add_batch(batch(0, 60, [(t, s, d, a, 0) for t, s, d, a in edges]))
    return g


def digraph(edges):
    G = nx.DiGraph()
    for a, b, t in edges:
        G.add_edge(a, b, first_t=t, last_t=t, count=1, amount=1.0)
    return G


class TestTemporalCycles:
    def test_chronological_cycle_is_valid(self):
        assert is_temporally_valid(digraph([(0, 1, 10), (1, 2, 20), (2, 0, 30)]),
                                   [0, 1, 2])

    def test_reverse_time_cycle_is_invalid(self):
        """Value cannot travel backwards. This is the false positive v1 counted."""
        assert not is_temporally_valid(
            digraph([(0, 1, 30), (1, 2, 20), (2, 0, 10)]), [0, 1, 2])

    def test_rotation_is_handled(self):
        """Any hop may be first, so a valid loop must be found from any start."""
        assert is_temporally_valid(digraph([(0, 1, 20), (1, 2, 30), (2, 0, 10)]),
                                   [0, 1, 2])

    def test_simultaneous_edges_are_valid(self):
        assert is_temporally_valid(digraph([(0, 1, 5), (1, 2, 5), (2, 0, 5)]),
                                   [0, 1, 2])

    def test_repeat_pair_widens_the_window(self):
        """A pair transacting repeatedly can satisfy ordering on a later hop."""
        G = nx.DiGraph()
        G.add_edge(0, 1, first_t=10, last_t=10, count=1, amount=1.0)
        G.add_edge(1, 2, first_t=5, last_t=50, count=2, amount=1.0)
        G.add_edge(2, 0, first_t=60, last_t=60, count=1, amount=1.0)
        assert is_temporally_valid(G, [0, 1, 2])

    def test_detect_separates_temporal_from_structural(self):
        good = timed_graph([(10, 0, 1, 5.0), (20, 1, 2, 5.0), (30, 2, 0, 5.0)])
        bad = timed_graph([(30, 0, 1, 5.0), (20, 1, 2, 5.0), (10, 2, 0, 5.0)])
        mg = detect(good.subgraph_edges({0, 1, 2}))
        mb = detect(bad.subgraph_edges({0, 1, 2}))
        assert mg.n_cycles == 1 and mg.n_temporal_cycles == 1
        assert mb.n_cycles == 1 and mb.n_temporal_cycles == 0

    def test_temporal_cycle_scores_strictly_higher(self):
        good = timed_graph([(10, 0, 1, 5.0), (20, 1, 2, 5.0), (30, 2, 0, 5.0)])
        bad = timed_graph([(30, 0, 1, 5.0), (20, 1, 2, 5.0), (10, 2, 0, 5.0)])
        n = {0, 1, 2}
        sg = F.score(F.build(n, good, detect(good.subgraph_edges(n))))[0]
        sb = F.score(F.build(n, bad, detect(bad.subgraph_edges(n))))[0]
        assert sg > sb


class TestGatherScatter:
    def test_detects_collect_then_disperse(self):
        g = graph_from([(1, 0, 10.0), (2, 0, 10.0), (3, 0, 10.0),
                        (0, 7, 10.0), (0, 8, 10.0)])
        assert find_gather_scatter(
            build_digraph(g.subgraph_edges({0, 1, 2, 3, 7, 8}))) == 2

    def test_needs_both_sides(self):
        g = graph_from([(1, 0, 10.0), (2, 0, 10.0), (3, 0, 10.0)])
        assert find_gather_scatter(
            build_digraph(g.subgraph_edges({0, 1, 2, 3}))) == 0

    def test_is_distinct_from_scatter_gather(self):
        g = graph_from([(1, 0, 10.0), (2, 0, 10.0), (0, 7, 10.0), (0, 8, 10.0)])
        m = detect(g.subgraph_edges({0, 1, 2, 7, 8}))
        assert m.gather_scatter == 2
        assert m.scatter_gather == 0


class TestMoments:
    def test_matches_numpy(self):
        import numpy as np
        xs = [3.0, 1.0, 4.0, 1.0, 5.0, 9.0, 2.0, 6.0]
        m = Moments()
        for i, x in enumerate(xs):
            m.add(x, i)
        a = np.array(xs)
        assert m.mean == pytest.approx(a.mean())
        g1 = ((a - a.mean()) ** 3).mean() / a.std() ** 3
        g2 = ((a - a.mean()) ** 4).mean() / a.std() ** 4 - 3
        assert m.skewness == pytest.approx(g1, rel=1e-6)
        assert m.kurtosis == pytest.approx(g2, rel=1e-6)

    def test_min_max_total(self):
        m = Moments()
        for i, x in enumerate([5.0, 2.0, 9.0]):
            m.add(x, i)
        assert (m.lo, m.hi, m.total) == (2.0, 9.0, 16.0)

    def test_degenerate_cases_are_zero_not_nan(self):
        m = Moments()
        assert m.skewness == 0.0 and m.kurtosis == 0.0
        m.add(1.0, 0)
        assert m.variance == 0.0 and m.skewness == 0.0

    def test_identical_amounts_have_zero_variance(self):
        """The structuring signature: many transfers of the same size."""
        m = Moments()
        for i in range(10):
            m.add(500.0, i)
        assert m.variance == pytest.approx(0.0, abs=1e-9)
        assert m.skewness == 0.0


class TestAccountStats:
    def test_fast_passthrough_matches_the_industry_rule(self):
        """>=80% of inflow forwarded within 48 hours."""
        a = AccountStats()
        a.add_in(1000.0, 0)
        a.add_out(900.0, 60 * 24)
        assert a.passthrough_value_ratio == pytest.approx(0.9)
        assert a.is_fast_passthrough

    def test_slow_forwarding_is_not_flagged(self):
        a = AccountStats()
        a.add_in(1000.0, 0)
        a.add_out(900.0, 60 * 24 * 5)
        assert not a.is_fast_passthrough

    def test_accumulating_account_is_not_a_conduit(self):
        a = AccountStats()
        a.add_in(1000.0, 0)
        a.add_out(50.0, 60)
        assert a.passthrough_value_ratio == pytest.approx(0.05)
        assert not a.is_fast_passthrough

    def test_ratio_is_capped_at_one(self):
        a = AccountStats()
        a.add_in(100.0, 0)
        a.add_out(5000.0, 60)
        assert a.passthrough_value_ratio == 1.0

    def test_receive_only_account_is_not_passthrough(self):
        a = AccountStats()
        a.add_in(1000.0, 0)
        assert not a.is_passthrough
        assert not a.is_fast_passthrough


class TestGraphIntegration:
    def test_graph_maintains_account_stats(self):
        g = timed_graph([(0, 0, 1, 100.0), (60, 1, 2, 90.0)])
        assert g.account_stats[1].is_fast_passthrough
        assert not g.account_stats[0].is_passthrough

    def test_stats_survive_window_expiry(self):
        """Dormancy and lifetime velocity need history the window has dropped."""
        g = WindowedGraph(window_minutes=60)
        g.add_batch(batch(0, 60, [(0, 0, 1, 100.0, 0)]))
        g.add_batch(batch(60, 120, []))
        g.add_batch(batch(120, 180, []))
        assert len(g) == 0, "the edge should have aged out of the graph"
        assert g.account_stats[0].outflow.n == 1, "but the behaviour is remembered"

    def test_behavioural_features_reach_the_candidate(self):
        g = timed_graph([(0, 9, 0, 1000.0), (30, 0, 1, 950.0),
                         (60, 1, 2, 900.0), (90, 2, 8, 880.0)])
        n = {0, 1, 2}
        f = F.build(n, g, detect(g.subgraph_edges(n)))
        assert f.fast_passthrough_ratio > 0.0
        assert f.median_passthrough_value > 0.8
