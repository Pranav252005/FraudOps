"""Tests for the stage-wise funnel tracker and bootstrap CI helpers."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from sentinel.eval.bootstrap import (bootstrap_ci, paired_bootstrap_delta,
                                     ratio_of_sums, union_recall)
from sentinel.eval.funnel import STAGES, FunnelTracker, is_hit


@dataclass
class _Cand:
    nodes: frozenset


class TestIsHit:
    def test_full_overlap_is_a_hit(self):
        assert is_hit({1, 2, 3}, {1, 2, 3})

    def test_below_containment_floor_is_not_a_hit(self):
        assert not is_hit({1, 100, 101}, {1, 2, 3, 4, 5})  # 1/5 < 0.5

    def test_bulk_candidate_fails_the_jaccard_floor(self):
        """A huge candidate trivially contains half a small ring."""
        big = set(range(100)) | {1, 2}
        assert not is_hit(big, {1, 2, 3, 4})

    def test_empty_intersection_is_not_a_hit(self):
        assert not is_hit({9, 10}, {1, 2, 3})


class TestFunnelTracker:
    def test_ring_never_seeded_stalls_at_seed_reachable(self):
        """A FAN-OUT-shaped ring with no pass-through account: reachable only."""
        tracker = FunnelTracker(rank_k=10)
        rings = {0: {1, 2, 3}}
        tracker.observe_cycle(rings, lambda r: "FAN-OUT",
                               seed_nodes=set(), candidates=[])
        row = tracker.rings()[0]
        assert row["seed_reachable"] is True
        assert row["seeded"] is False
        assert row["built"] is False
        assert row["ranked"] is False

    def test_seeded_but_no_candidate_built(self):
        tracker = FunnelTracker(rank_k=10)
        rings = {0: {1, 2, 3}}
        tracker.observe_cycle(rings, lambda r: "CYCLE",
                               seed_nodes={1}, candidates=[])
        row = tracker.rings()[0]
        assert row["seeded"] is True
        assert row["built"] is False

    def test_built_but_ranked_out(self):
        tracker = FunnelTracker(rank_k=1)
        rings = {0: {1, 2, 3}}
        cands = [_Cand(frozenset({9, 9, 9} | {1, 2, 3})),  # rank 0, not a hit
                 _Cand(frozenset({1, 2, 3}))]               # rank 1, a hit
        # make rank 0 genuinely not a hit
        cands[0] = _Cand(frozenset({100, 101, 102}))
        cands = [cands[0], _Cand(frozenset({1, 2, 3}))]
        tracker.observe_cycle(rings, lambda r: "CYCLE",
                               seed_nodes={1}, candidates=cands)
        row = tracker.rings()[0]
        assert row["built"] is True
        assert row["ranked"] is False, "hit landed at rank 1, k=1 means top-1 only"

    def test_fully_ranked(self):
        tracker = FunnelTracker(rank_k=10)
        rings = {0: {1, 2, 3}}
        cands = [_Cand(frozenset({1, 2, 3}))]
        tracker.observe_cycle(rings, lambda r: "CYCLE",
                               seed_nodes={1}, candidates=cands)
        row = tracker.rings()[0]
        assert all(row[s] for s in STAGES)

    def test_stage_is_sticky_across_cycles(self):
        """A ring only needs to clear a stage once across the whole run."""
        tracker = FunnelTracker(rank_k=10)
        rings = {0: {1, 2, 3}}
        tracker.observe_cycle(rings, lambda r: "CYCLE",
                               seed_nodes={1}, candidates=[_Cand(frozenset({1, 2, 3}))])
        tracker.observe_cycle(rings, lambda r: "CYCLE", seed_nodes=set(), candidates=[])
        row = tracker.rings()[0]
        assert row["built"] is True and row["ranked"] is True

    def test_table_groups_by_typology_and_counts_recall(self):
        tracker = FunnelTracker(rank_k=10)
        tracker.observe_cycle({0: {1, 2, 3}, 1: {4, 5, 6}},
                               lambda r: "FAN-OUT" if r == 0 else "CYCLE",
                               seed_nodes={4},
                               candidates=[_Cand(frozenset({4, 5, 6}))])
        table = tracker.table()
        assert table["FAN-OUT"]["total"] == 1
        assert table["FAN-OUT"]["seeded"] == 0
        assert table["CYCLE"]["seeded"] == 1
        assert table["CYCLE"]["ranked"] == 1

    def test_to_rows_includes_total_row(self):
        tracker = FunnelTracker(rank_k=10)
        tracker.observe_cycle({0: {1, 2, 3}}, lambda r: "CYCLE",
                               seed_nodes=set(), candidates=[])
        rows = tracker.to_rows()
        assert any(r["typology"] == "TOTAL" for r in rows)
        total_row = next(r for r in rows if r["typology"] == "TOTAL")
        assert total_row["total"] == 1

    def test_empty_tracker_has_no_division_by_zero(self):
        tracker = FunnelTracker()
        rows = tracker.to_rows()
        assert rows[-1]["typology"] == "TOTAL"
        assert rows[-1]["total"] == 0
        assert rows[-1]["seed_reachable_recall"] == 0.0


class TestBootstrap:
    def test_point_estimate_matches_direct_computation(self):
        records = [{"hit": 1, "total": 10}, {"hit": 2, "total": 10}]
        stat = ratio_of_sums("hit", "total")
        result = bootstrap_ci(records, stat, n_resamples=200)
        assert result["point"] == pytest.approx(3 / 20)

    def test_ci_brackets_the_point_estimate(self):
        records = [{"hit": h % 3, "total": 10} for h in range(30)]
        stat = ratio_of_sums("hit", "total")
        result = bootstrap_ci(records, stat, n_resamples=500)
        assert result["lo"] <= result["point"] <= result["hi"]

    def test_empty_records_do_not_crash(self):
        result = bootstrap_ci([], ratio_of_sums("hit", "total"))
        assert result["point"] == 0.0
        assert result["lo"] == result["hi"] == 0.0
        assert result["n_units"] == 0

    def test_no_variance_collapses_interval(self):
        records = [{"hit": 5, "total": 10}] * 20
        result = bootstrap_ci(records, ratio_of_sums("hit", "total"), n_resamples=200)
        assert result["lo"] == pytest.approx(result["hi"])

    def test_paired_delta_is_zero_for_identical_statistics(self):
        records = [{"a": i, "b": i} for i in range(20)]
        stat_a = ratio_of_sums("a", "a")
        stat_b = ratio_of_sums("b", "b")
        result = paired_bootstrap_delta(records, stat_a, stat_b, n_resamples=200)
        assert result["point"] == pytest.approx(0.0)

    def test_paired_delta_excludes_zero_for_a_real_lift(self):
        # b is always double a's hit rate on a large, low-noise sample.
        records = [{"hit_a": 1, "hit_b": 2, "total": 100} for _ in range(50)]
        stat_a = ratio_of_sums("hit_a", "total")
        stat_b = ratio_of_sums("hit_b", "total")
        result = paired_bootstrap_delta(records, stat_a, stat_b, n_resamples=500)
        assert result["excludes_zero"] is True
        assert result["point"] == pytest.approx(0.01)

    def test_union_recall_dedups_across_cycles(self):
        records = [{"found": {1, 2}, "seen": {1, 2, 3}},
                   {"found": {2, 3}, "seen": {1, 2, 3, 4}}]
        stat = union_recall("found", "seen")
        assert stat(records) == pytest.approx(3 / 4)
