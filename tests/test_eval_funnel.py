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


# --- the derived funnel metrics ------------------------------------------------
#
# `scripts/eval_funnel.py`'s stage-loss and interpretation helpers are pure
# arithmetic over counts the tracker already produced, but they are the numbers
# the write-up quotes directly, so a sign flip or a moved threshold would change
# a headline claim silently. These pin them.

from scripts.eval_funnel import (BUILD_DESTROYED_BELOW,  # noqa: E402
                                 BUILD_HEALTHY_AT_OR_ABOVE, LABEL_DESTROYED,
                                 LABEL_ORDINARY, LABEL_RANKING, annotate,
                                 build_retention, interpret, stage_losses_pts)


def _row(typology, total, seeded, built, ranked, seed_reachable=None):
    reach = total if seed_reachable is None else seed_reachable
    return {"typology": typology, "total": total,
            "seed_reachable": reach, "seed_reachable_recall": reach / total,
            "seeded": seeded, "seeded_recall": seeded / total,
            "built": built, "built_recall": built / total,
            "ranked": ranked, "ranked_recall": ranked / total}


# The measured TOTAL row: 259 rings -> 230 seeded -> 162 built -> 49 ranked.
TOTAL_ROW = _row("TOTAL", 259, 230, 162, 49)


def test_stage_losses_match_the_measured_total_row():
    losses = stage_losses_pts(TOTAL_ROW)
    assert losses["seeding"] == pytest.approx(11.1969, abs=1e-3)
    assert losses["build"] == pytest.approx(26.2548, abs=1e-3)
    assert losses["ranking"] == pytest.approx(43.6293, abs=1e-3)


def test_stage_losses_close_against_the_end_to_end_drop():
    """The three stages must account for the whole loss, or one is mis-defined."""
    losses = stage_losses_pts(TOTAL_ROW)
    end_to_end = 100.0 * (TOTAL_ROW["seed_reachable_recall"]
                          - TOTAL_ROW["ranked_recall"])
    assert sum(losses.values()) == pytest.approx(end_to_end)


def test_ranking_is_the_largest_loss_on_the_measured_row():
    """The claim the write-up leads with, pinned so it cannot silently invert."""
    losses = stage_losses_pts(TOTAL_ROW)
    assert max(losses, key=losses.get) == "ranking"


def test_build_retention_is_built_over_seeded_not_over_total():
    assert build_retention(_row("STACK", 30, 30, 9, 2)) == pytest.approx(0.30)
    assert build_retention(_row("BIPARTITE", 31, 28, 5, 1)) == pytest.approx(
        5 / 28)


def test_build_retention_is_undefined_when_nothing_was_seeded():
    assert build_retention(_row("X", 10, 0, 0, 0)) is None
    assert interpret(_row("X", 10, 0, 0, 0)) == "not seeded"


def test_the_two_destroyed_typologies_are_classified_as_destroyed():
    assert interpret(_row("STACK", 30, 30, 9, 2)) == LABEL_DESTROYED
    assert interpret(_row("BIPARTITE", 31, 28, 5, 1)) == LABEL_DESTROYED


def test_a_healthy_typology_is_classified_ranking_limited():
    # SCATTER-GATHER: 28 seeded, 27 built -> retention .96
    assert interpret(_row("SCATTER-GATHER", 31, 28, 27, 10)) == LABEL_RANKING


def test_a_middling_typology_is_ordinary_attrition():
    # FAN-IN: 26 seeded, 21 built -> retention .81, between the two cuts
    assert interpret(_row("FAN-IN", 30, 26, 21, 4)) == LABEL_ORDINARY


def test_the_total_row_is_never_given_a_diagnosis():
    """Reading one blended retention as a diagnosis is the averaging mistake
    the per-typology table exists to prevent."""
    assert interpret(TOTAL_ROW) == "aggregate"


def test_threshold_boundaries_behave_as_documented():
    """`<` at .50 and `>=` at .85, per the THRESHOLDS comment."""
    assert BUILD_DESTROYED_BELOW == 0.50
    assert BUILD_HEALTHY_AT_OR_ABOVE == 0.85
    exactly_half = _row("A", 100, 100, 50, 0)      # retention exactly .50
    assert interpret(exactly_half) == LABEL_ORDINARY
    exactly_85 = _row("B", 100, 100, 85, 0)        # retention exactly .85
    assert interpret(exactly_85) == LABEL_RANKING


def test_annotate_appends_and_never_reorders_existing_keys():
    """The CSV schema stays additive only if the original keys keep their
    positions -- `csv.DictWriter` takes field order from the first row."""
    row = dict(TOTAL_ROW)
    before = list(row)
    after = list(annotate([row])[0])
    assert after[:len(before)] == before
    assert "interpretation" in after and "build_retention" in after
