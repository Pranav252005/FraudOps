"""Tests for bounded escalation actions and the human-gate contract.

The core invariant: nothing executes without a prior, explicitly-recorded
human decision, and a recommendation cannot be decided twice.
"""
from __future__ import annotations

import pytest

from sentinel.escalation import (Action, DecisionStatus, decide, execute,
                                 recommend)


class TestRecommend:
    def test_requires_evidence(self):
        with pytest.raises(ValueError, match="evidence"):
            recommend("CASE-1", Action.FREEZE_ACCOUNT, [], "suspicious pattern")

    def test_requires_a_rationale(self):
        with pytest.raises(ValueError, match="rationale"):
            recommend("CASE-1", Action.FREEZE_ACCOUNT, ["TXN-1"], "")

    def test_starts_pending_and_not_executed(self):
        rec = recommend("CASE-1", Action.HOLD_PAYOUT, ["TXN-1"], "cycle detected")
        assert rec.status is DecisionStatus.PENDING
        assert rec.executed is False


class TestDecide:
    def test_approve_sets_status_and_decider(self):
        rec = recommend("CASE-1", Action.FILE_STR, ["TXN-1"], "confirmed ring")
        decide(rec, approved=True, by="analyst_1", note="reviewed evidence")
        assert rec.status is DecisionStatus.APPROVED
        assert rec.decided_by == "analyst_1"
        assert rec.decided_at

    def test_reject_sets_status_without_allowing_execution(self):
        rec = recommend("CASE-1", Action.FREEZE_ACCOUNT, ["TXN-1"], "cycle")
        decide(rec, approved=False, by="analyst_1")
        assert rec.status is DecisionStatus.REJECTED
        with pytest.raises(ValueError, match="approved"):
            execute(rec)

    def test_cannot_decide_twice(self):
        rec = recommend("CASE-1", Action.ESCALATE_TO_COMPLIANCE, ["TXN-1"], "review")
        decide(rec, approved=True, by="analyst_1")
        with pytest.raises(ValueError, match="already decided"):
            decide(rec, approved=False, by="analyst_2")

    def test_decision_requires_a_named_decider(self):
        rec = recommend("CASE-1", Action.HOLD_PAYOUT, ["TXN-1"], "cycle")
        with pytest.raises(ValueError, match="who made it"):
            decide(rec, approved=True, by="")


class TestExecute:
    def test_cannot_execute_a_pending_recommendation(self):
        rec = recommend("CASE-1", Action.REQUEST_KYC_REVERIFICATION, ["TXN-1"], "cycle")
        with pytest.raises(ValueError, match="approved"):
            execute(rec)

    def test_execute_after_approval_logs_timestamp(self):
        rec = recommend("CASE-1", Action.FILE_STR, ["TXN-1"], "confirmed")
        decide(rec, approved=True, by="compliance_lead")
        execute(rec)
        assert rec.executed is True
        assert rec.executed_at

    def test_to_dict_round_trips_the_full_audit_trail(self):
        rec = recommend("CASE-1", Action.FREEZE_ACCOUNT, ["TXN-1", "1:A"],
                        "pass-through cycle with cross-border flow")
        decide(rec, approved=True, by="analyst_1", note="ok")
        execute(rec)
        d = rec.to_dict()
        assert d["status"] == "approved"
        assert d["executed"] is True
        assert d["evidence_ids"] == ["TXN-1", "1:A"]
        assert d["decided_by"] == "analyst_1"
