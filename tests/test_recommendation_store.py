"""Tests for the append-only recommendation/decision/execution log."""
from __future__ import annotations

from sentinel.cases.recommendation_store import RecommendationStore
from sentinel.escalation import Action, DecisionStatus, decide, execute, recommend


class TestRecommendationStore:
    def test_add_assigns_a_stable_id(self, tmp_path):
        store = RecommendationStore(tmp_path)
        rec = recommend("CASE-1", Action.FREEZE_ACCOUNT, ["TXN-1"], "cycle")
        rec_id = store.add(rec)
        assert rec_id == "REC-00001"
        assert store.get(rec_id) is rec

    def test_survives_reload_across_the_full_lifecycle(self, tmp_path):
        store = RecommendationStore(tmp_path)
        rec = recommend("CASE-1", Action.FILE_STR, ["TXN-1", "1:A"], "confirmed ring")
        rec_id = store.add(rec)
        decide(rec, approved=True, by="analyst_1", note="looks right")
        store.update(rec_id, "decide")
        execute(rec)
        store.update(rec_id, "execute")

        reloaded = RecommendationStore(tmp_path).load()
        got = reloaded.get(rec_id)
        assert got is not None
        assert got.status is DecisionStatus.APPROVED
        assert got.executed is True
        assert got.decided_by == "analyst_1"
        assert got.evidence_ids == ["TXN-1", "1:A"]

    def test_for_case_filters_by_case_id(self, tmp_path):
        store = RecommendationStore(tmp_path)
        store.add(recommend("CASE-1", Action.HOLD_PAYOUT, ["TXN-1"], "r1"))
        store.add(recommend("CASE-2", Action.HOLD_PAYOUT, ["TXN-2"], "r2"))
        assert len(store.for_case("CASE-1")) == 1

    def test_load_on_empty_store_is_a_noop(self, tmp_path):
        store = RecommendationStore(tmp_path).load()
        assert store.all() == []

    def test_counter_resumes_after_reload(self, tmp_path):
        store = RecommendationStore(tmp_path)
        store.add(recommend("CASE-1", Action.HOLD_PAYOUT, ["TXN-1"], "r1"))
        reloaded = RecommendationStore(tmp_path).load()
        new_id = reloaded.add(recommend("CASE-1", Action.HOLD_PAYOUT, ["TXN-2"], "r2"))
        assert new_id == "REC-00002"
