"""Phase 1 tests: replay ordering and windowed-graph correctness.

The window is the graph everything downstream reasons about, so its arithmetic
is worth pinning precisely. An expiry that leaks or double-counts would shift
every feature by a little and would never announce itself.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.graph.window import WindowedGraph, pair_key, unpair
from sentinel.stream.replay import Batch, Stream

STREAM = Path(__file__).resolve().parent.parent / "data" / "stream"

needs_stream = pytest.mark.skipif(
    not (STREAM / "edges.parquet").exists(),
    reason="compiled stream not built (run scripts/build_stream.py)",
)


def batch(t_start, t_end, edges):
    """edges = [(ts, src, dst, amount, label)]"""
    if edges:
        ts, src, dst, amt, lab = (np.array(x) for x in zip(*edges))
    else:
        ts = src = dst = np.array([], dtype="int32")
        amt = np.array([], dtype="float64")
        lab = np.array([], dtype="int8")
    z = np.zeros(len(edges), dtype="int8")
    return Batch(t_start=t_start, t_end=t_end,
                 ts=ts.astype("int32"), src=src.astype("int32"),
                 dst=dst.astype("int32"), amount=amt.astype("float64"),
                 currency=z, channel=z, is_laundering=lab.astype("int8"),
                 ring=np.full(len(edges), -1, dtype="int32"))


class TestPairKey:
    def test_roundtrip(self):
        for s, d in [(0, 0), (1, 2), (515087, 1), (123456, 654321)]:
            assert unpair(pair_key(s, d)) == (s, d)

    def test_direction_matters(self):
        assert pair_key(1, 2) != pair_key(2, 1)


class TestWindowedGraph:
    def test_adds_and_aggregates_repeat_pairs(self):
        g = WindowedGraph(window_minutes=1000)
        g.add_batch(batch(0, 60, [(1, 10, 20, 100.0, 0), (5, 10, 20, 50.0, 1)]))
        assert len(g) == 1
        agg = g.pairs[pair_key(10, 20)]
        assert agg.count == 2
        assert agg.amount == pytest.approx(150.0)
        assert agg.first_t == 1 and agg.last_t == 5
        assert agg.laundering == 1

    def test_adjacency_both_directions(self):
        g = WindowedGraph(window_minutes=1000)
        g.add_batch(batch(0, 60, [(1, 10, 20, 100.0, 0)]))
        assert g.out_adj[10] == {20}
        assert g.in_adj[20] == {10}
        assert g.neighbours(10) == {20}
        assert g.neighbours(20) == {10}
        assert g.degree(10) == (1, 0)
        assert g.degree(20) == (0, 1)

    def test_expiry_removes_the_pair(self):
        g = WindowedGraph(window_minutes=120)
        g.add_batch(batch(0, 60, [(10, 10, 20, 100.0, 0)]))
        assert len(g) == 1
        g.add_batch(batch(60, 120, []))
        assert len(g) == 1, "still inside the window"
        g.add_batch(batch(120, 180, []))
        assert len(g) == 0
        assert not g.out_adj and not g.in_adj, "adjacency must be cleaned up too"

    def test_expiry_is_batch_granular_not_edge_exact(self):
        """Documents the approximation rather than pretending it is not there.

        A batch is retired as a unit, so an edge survives for the window plus
        up to one tick. At the configured 72h window and 60min tick that is a
        1.4% overhang, which is cheaper than tracking per-edge expiry and is
        deliberately traded away.
        """
        g = WindowedGraph(window_minutes=60)
        g.add_batch(batch(0, 60, [(0, 10, 20, 100.0, 0)]))   # edge at t=0
        g.add_batch(batch(60, 120, []))                      # now=120
        # True age of the edge is 120 minutes against a 60 minute window, yet it
        # only leaves now, with its batch.
        assert len(g) == 0

    def test_expiry_is_partial_when_pair_recurs(self):
        """A pair seen in two ticks must survive the first expiry."""
        g = WindowedGraph(window_minutes=120)
        g.add_batch(batch(0, 60, [(10, 10, 20, 100.0, 0)]))
        g.add_batch(batch(60, 120, [(70, 10, 20, 40.0, 0)]))
        g.add_batch(batch(120, 180, []))
        assert len(g) == 1
        agg = g.pairs[pair_key(10, 20)]
        assert agg.count == 1
        assert agg.amount == pytest.approx(40.0)
        g.add_batch(batch(180, 240, []))
        assert len(g) == 0

    def test_counters_balance(self):
        g = WindowedGraph(window_minutes=60)
        for t in range(0, 600, 60):
            g.add_batch(batch(t, t + 60, [(t, 1, 2, 1.0, 0)]))
        st = g.stats()
        assert st["added"] - st["expired"] == sum(a.count for a in g.pairs.values())

    def test_volume(self):
        g = WindowedGraph(window_minutes=1000)
        g.add_batch(batch(0, 60, [(1, 10, 20, 100.0, 0), (1, 30, 10, 25.0, 0)]))
        out, inc = g.volume(10)
        assert out == pytest.approx(100.0)
        assert inc == pytest.approx(25.0)


class TestExpand:
    def line_graph(self, n=6):
        g = WindowedGraph(window_minutes=10_000)
        g.add_batch(batch(0, 60, [(1, i, i + 1, 10.0, 0) for i in range(n)]))
        return g

    def test_two_hops(self):
        g = self.line_graph()
        assert g.expand([0], hops=1) == {0, 1}
        assert g.expand([0], hops=2) == {0, 1, 2}

    def test_respects_max_nodes(self):
        g = WindowedGraph(window_minutes=10_000)
        g.add_batch(batch(0, 60, [(1, 0, i, 10.0, 0) for i in range(1, 50)]))
        assert len(g.expand([0], hops=2, max_nodes=10)) <= 10

    def test_hub_is_included_but_not_traversed_through(self):
        """The guard that stops one popular node merging the whole graph."""
        g = WindowedGraph(window_minutes=10_000)
        # node 0 -> hub 1 ; hub 1 -> 100 leaves
        edges = [(1, 0, 1, 10.0, 0)] + [(1, 1, 100 + i, 10.0, 0) for i in range(100)]
        g.add_batch(batch(0, 60, edges))
        got = g.expand([0], hops=2, max_degree=50)
        assert 1 in got, "the hub itself is context and should be present"
        assert not (got & set(range(100, 200))), "must not expand through the hub"

    def test_subgraph_edges_are_induced(self):
        g = self.line_graph()
        edges = g.subgraph_edges({0, 1, 2})
        assert {(s, d) for s, d, _ in edges} == {(0, 1), (1, 2)}


@needs_stream
class TestRealStream:
    @staticmethod
    def stream():
        return Stream(STREAM)

    def test_stream_is_time_ordered(self):
        s = self.stream()
        assert bool((np.diff(s.ts) >= 0).all())

    def test_ticks_cover_every_edge_exactly_once(self):
        s = self.stream()
        total = sum(len(b) for b in s.ticks(TICK_MINUTES))
        assert total == s.meta["n_edges"]

    def test_ticks_are_aligned_and_contiguous(self):
        s = self.stream()
        prev_end = None
        for b in s.ticks(TICK_MINUTES):
            assert b.t_start % TICK_MINUTES == 0
            if prev_end is not None:
                assert b.t_start == prev_end
            prev_end = b.t_end

    def test_quiet_ticks_are_still_yielded(self):
        """Time passing is information; skipping empty buckets desynchronises
        every baseline keyed on hour-of-week."""
        s = self.stream()
        n = sum(1 for _ in s.ticks(TICK_MINUTES))
        assert n == s.n_ticks(TICK_MINUTES)
        assert any(len(b) == 0 for b in s.ticks(TICK_MINUTES))

    def test_evaluation_window_holds_almost_all_traffic(self):
        s = self.stream()
        inside = int((s.ts < EVAL_END).sum())
        assert inside / s.meta["n_edges"] > 0.999

    def test_tail_is_almost_pure_laundering(self):
        """Documents the leak that EVAL_END exists to exclude."""
        s = self.stream()
        tail = s.ts >= EVAL_END
        assert tail.sum() > 0
        assert s.is_laundering[tail].mean() > 0.85

    def test_replay_over_eval_window(self):
        s = self.stream()
        g = WindowedGraph(window_minutes=WINDOW_MINUTES)
        seen = 0
        for b in s.ticks(TICK_MINUTES, end=EVAL_END):
            g.add_batch(b)
            seen += len(b)
        assert seen == int((s.ts < EVAL_END).sum())
        assert len(g) > 0
        st = g.stats()
        assert st["added"] - st["expired"] == sum(a.count for a in g.pairs.values())
