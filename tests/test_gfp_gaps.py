"""The three real gaps against IBM's Graph Feature Preprocessor, and their fix.

docs/HANDOFF.md section 4 says coverage vs GFP is "essentially at parity". That
was a checklist comparison -- someone read both feature lists and matched names
-- and docs/ARCHITECTURE_UPLIFT.md section 2.2 found it wrong in three specific,
correctable places:

  * scatter-gather had no time window. GFP's AML configuration bounds the shape
    at 6h; sentinel bounded it not at all.
  * timestamp vertex statistics were absent entirely. span_minutes and
    burstiness are related but are not the moment set.
  * amount vertex statistics were computed per account by AccountStats and then
    never propagated into Features -- paid for and thrown away.

These tests pin each fix to a graph whose answer is known by construction,
including the case each one is supposed to distinguish.
"""
from __future__ import annotations

import pytest

from sentinel.detect import features as F
from sentinel.detect.motifs import (SCATTER_GATHER_WINDOW_MINUTES,
                                    build_digraph, detect, find_scatter_gather)
from sentinel.graph.window import WindowedGraph
from tests.test_phase1 import batch


def graph_from(edges, window=100_000):
    """edges = [(t, src, dst, amount)]"""
    g = WindowedGraph(window_minutes=window)
    g.add_batch(batch(0, 60, [(t, s, d, a, 0) for t, s, d, a in edges]))
    return g


# --------------------------------------------------------------------------
# gap 1 -- the 6h scatter-gather window
# --------------------------------------------------------------------------

def _scatter_gather(t_offsets):
    """A -> {M1, M2} -> B, with each second leg offset from its first."""
    edges = [(0, 1, 10, 500.0), (0, 1, 11, 500.0)]
    edges += [(t_offsets[0], 10, 2, 480.0), (t_offsets[1], 11, 2, 480.0)]
    return build_digraph(graph_from(edges).subgraph_edges({1, 10, 11, 2}))


class TestWindowedScatterGather:
    def test_unbounded_detector_is_unchanged(self):
        """The original behaviour is preserved, not replaced -- otherwise the
        two cannot be measured against each other."""
        slow = _scatter_gather((60 * 48, 60 * 48))
        assert find_scatter_gather(slow) == [(1, 2, 2)]

    def test_a_pattern_inside_six_hours_is_kept(self):
        fast = _scatter_gather((60, 120))
        got = find_scatter_gather(
            fast, window_minutes=SCATTER_GATHER_WINDOW_MINUTES)
        assert got == [(1, 2, 2)]

    def test_a_pattern_spread_over_two_days_is_rejected(self):
        """The whole point: a scatter-gather over 48h is a different object."""
        slow = _scatter_gather((60 * 48, 60 * 48))
        assert find_scatter_gather(
            slow, window_minutes=SCATTER_GATHER_WINDOW_MINUTES) == []

    def test_a_second_leg_before_the_first_is_rejected(self):
        """Value cannot arrive at B before it left A."""
        edges = [(600, 1, 10, 500.0), (600, 1, 11, 500.0),
                 (1, 10, 2, 480.0), (2, 11, 2, 480.0)]
        G = build_digraph(graph_from(edges).subgraph_edges({1, 10, 11, 2}))
        assert find_scatter_gather(G) == [(1, 2, 2)]
        assert find_scatter_gather(
            G, window_minutes=SCATTER_GATHER_WINDOW_MINUTES) == []

    def test_width_drops_when_only_one_strand_is_fast(self):
        """One fast strand is width 1, below min_width, so no pattern."""
        mixed = _scatter_gather((60, 60 * 48))
        assert find_scatter_gather(mixed) == [(1, 2, 2)]
        assert find_scatter_gather(
            mixed, window_minutes=SCATTER_GATHER_WINDOW_MINUTES) == []

    def test_both_widths_reach_the_feature_vector(self):
        edges = [(0, 1, 10, 500.0), (0, 1, 11, 500.0),
                 (60, 10, 2, 480.0), (60 * 48, 11, 2, 480.0)]
        g = graph_from(edges)
        nodes = {1, 10, 11, 2}
        f = F.build(nodes, g, detect(g.subgraph_edges(nodes)))
        assert f.scatter_gather_width == 2
        assert f.scatter_gather_width_6h == 0


# --------------------------------------------------------------------------
# gap 2 -- timestamp moments
# --------------------------------------------------------------------------

class TestTimestampMoments:
    def test_a_steady_trickle_and_a_burst_are_distinguished(self):
        """span_minutes and burstiness cannot tell these apart; that is the gap.

        Both accounts transact 8 times over the same total span. One is evenly
        spaced, the other is two tight clusters at the ends. Excess kurtosis is
        the moment that separates them.
        """
        span = 700
        even = [(i * (span // 7), 100, 200 + i, 100.0) for i in range(8)]
        burst = [(t, 300, 400 + i, 100.0) for i, t in enumerate(
            [0, 1, 2, 3, span - 3, span - 2, span - 1, span])]

        g = graph_from(even + burst)
        a_even = g.account_stats[100]
        a_burst = g.account_stats[300]

        assert a_even.times.n == a_burst.times.n == 8
        # Same span, so span_minutes-style features agree...
        assert (a_even.times.last_t - a_even.times.first_t) == \
            (a_burst.times.last_t - a_burst.times.first_t)
        # ...and the moment set does not.
        assert a_burst.time_kurtosis < a_even.time_kurtosis, (
            "two tight clusters should be more platykurtic than a uniform "
            "trickle; if this flips, the moment is not measuring what the "
            "docstring claims")
        assert a_burst.time_std_hours > a_even.time_std_hours

    def test_moments_are_zero_not_fabricated_below_the_sample_floor(self):
        g = graph_from([(5, 1, 2, 100.0)])
        a = g.account_stats[1]
        assert a.times.n == 1
        assert a.time_skewness == 0.0 and a.time_kurtosis == 0.0

    def test_timestamp_moments_reach_the_feature_vector(self):
        edges = [(i * 100, 1, 2, 100.0) for i in range(6)]
        edges += [(i * 100 + 50, 2, 3, 90.0) for i in range(6)]
        g = graph_from(edges)
        nodes = {1, 2, 3}
        f = F.build(nodes, g, detect(g.subgraph_edges(nodes)))
        assert f.mean_time_std_h > 0.0
        assert f.max_time_kurtosis == pytest.approx(
            max(abs(g.account_stats[n].time_kurtosis) for n in nodes))


# --------------------------------------------------------------------------
# gap 3 -- amount moments, computed and previously discarded
# --------------------------------------------------------------------------

class TestAmountMomentPropagation:
    def test_amount_moments_reach_the_feature_vector(self):
        edges = [(1, 1, 2, 100.0), (2, 1, 2, 300.0), (3, 1, 2, 200.0),
                 (4, 2, 3, 50.0), (5, 2, 3, 150.0)]
        g = graph_from(edges)
        nodes = {1, 2, 3}
        f = F.build(nodes, g, detect(g.subgraph_edges(nodes)))

        # account 1 sends 100/300/200 (mean 200), account 2 sends 50/150 (100)
        assert f.mean_out_amount == pytest.approx((200.0 + 100.0) / 2)
        assert f.min_member_amount == pytest.approx(50.0)
        assert f.max_member_amount == pytest.approx(300.0)
        assert f.mean_amount_std > 0.0

    def test_receive_only_members_do_not_drag_the_outflow_mean_to_zero(self):
        """A candidate of pure receivers must report no outflow, not a small
        one. Counting an absent direction as 0.0 would be a plausible wrong
        answer -- it reads as 'these accounts send tiny amounts'."""
        edges = [(1, 9, 1, 1000.0), (2, 9, 2, 1000.0), (3, 9, 3, 1000.0)]
        g = graph_from(edges)
        nodes = {1, 2, 3}
        f = F.build(nodes, g, detect(g.subgraph_edges(nodes)))
        assert f.mean_out_amount == 0.0
        assert f.mean_in_amount == pytest.approx(1000.0)

    def test_the_median_gap_is_still_open_and_that_is_recorded(self):
        """GFP also reports a per-account MEDIAN amount. Welford moments cannot
        produce one without retaining samples. Asserted so that the absence is
        a known, tested fact rather than an oversight someone rediscovers."""
        names = set(F.Features().to_dict())
        assert "median_out_amount" not in names
        assert "median_passthrough_value" in names   # a different quantity
