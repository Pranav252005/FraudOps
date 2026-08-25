"""Phase 3 tests: the case record, the store, and queue selection.

The property these tests exist to protect is point-in-time correctness. A case
must record what was true when it was scored, and nothing later may edit it --
otherwise the label corpus is contaminated by hindsight and every model trained
on it is measuring the future.
"""
from __future__ import annotations

import json

import pytest

from sentinel.cases.case import (DETECTOR_VERSION, REASONS, Case, Disposition,
                                 Lane, Verdict, validate_reason)
from sentinel.cases.manager import CaseManager, LOW_CONFIDENCE_SCORE
from sentinel.cases.store import CaseStore
from sentinel.detect.candidates import Candidate, canonical_key
from sentinel.detect.features import Features
from sentinel.detect.motifs import Motifs
from tests.test_phase2 import graph_from


def cand(nodes, score, seed=None, **feat):
    return Candidate(
        key=canonical_key(nodes), nodes=frozenset(nodes),
        seed=seed if seed is not None else min(nodes), t=1440,
        score=score, contrib={"cycle": score},
        features=Features(n_nodes=len(nodes), **feat), motifs=Motifs(),
    )


@pytest.fixture
def store(tmp_path):
    return CaseStore(tmp_path / "cases")


@pytest.fixture
def graph():
    return graph_from([(0, 1, 100.0), (1, 2, 100.0), (2, 0, 100.0)])


# --------------------------------------------------------------------------
# Verdicts
# --------------------------------------------------------------------------

class TestVerdict:
    def test_positive_verdicts(self):
        assert Verdict.CONFIRMED_RING.is_positive
        assert Verdict.CONFIRMED_PARTIAL.is_positive
        assert not Verdict.NOT_A_RING.is_positive
        assert not Verdict.BENIGN_EXPLAINED.is_positive

    def test_pending_is_unresolved(self):
        assert not Verdict.PENDING.is_resolved
        assert Verdict.NOT_A_RING.is_resolved

    def test_every_verdict_has_reasons(self):
        for v in Verdict:
            if v is Verdict.PENDING:
                continue
            assert REASONS.get(v), f"{v} has no reason vocabulary"

    def test_reason_validation_is_per_verdict(self):
        assert validate_reason(Verdict.CONFIRMED_RING, "layering")
        assert not validate_reason(Verdict.CONFIRMED_RING, "payroll_hub")
        assert validate_reason(Verdict.BENIGN_EXPLAINED, "payroll_hub")


# --------------------------------------------------------------------------
# Case record
# --------------------------------------------------------------------------

class TestCase:
    def make(self):
        return Case(id="CASE-1", opened_at="2022-09-05T12:00:00", opened_t=5760,
                    lane=Lane.PRIMARY, members=["1:A", "2:B"], seed="1:A",
                    score=0.5, contrib={"cycle": 0.5},
                    features={"n_nodes": 2, "conservation": 0.9},
                    motifs={"n_cycles": 1}, subgraph=[["1:A", "2:B", 3, 100.0]])

    def test_roundtrip_through_json(self):
        c = self.make()
        c.disposition = Disposition(verdict=Verdict.CONFIRMED_RING,
                                    reason="layering", at="x")
        back = Case.from_dict(json.loads(c.to_json()))
        assert back.id == c.id
        assert back.lane is Lane.PRIMARY
        assert back.disposition.verdict is Verdict.CONFIRMED_RING
        assert back.features == c.features

    def test_detector_version_is_stamped(self):
        assert self.make().detector_version == DETECTOR_VERSION

    def test_timeline_is_append_only(self):
        c = self.make()
        c.log("t1", "detect", "opened")
        c.log("t2", "evidence", "cycle")
        assert [e["kind"] for e in c.timeline] == ["detect", "evidence"]


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------

class TestCaseStore:
    def open_one(self, store, score=0.5):
        c = Case(id=store.next_id(), opened_at="2022-09-05T12:00:00",
                 opened_t=5760, lane=Lane.PRIMARY, members=["1:A", "2:B"],
                 seed="1:A", score=score, contrib={}, features={"conservation": 0.9},
                 motifs={}, subgraph=[])
        return store.open(c)

    def test_ids_are_sequential_and_unique(self, store):
        a, b = self.open_one(store), self.open_one(store)
        assert a.id != b.id
        assert store.get(a.id) is a

    def test_duplicate_id_is_rejected(self, store):
        c = self.open_one(store)
        with pytest.raises(ValueError):
            store.open(c)

    def test_disposition_requires_a_valid_reason(self, store):
        c = self.open_one(store)
        with pytest.raises(ValueError):
            store.dispose(c.id, Verdict.CONFIRMED_RING, reason="payroll_hub")

    def test_disposition_is_recorded(self, store):
        c = self.open_one(store)
        store.dispose(c.id, Verdict.CONFIRMED_RING, reason="layering",
                      at="2022-09-05T12:11:00", seconds=41.0)
        assert c.disposition.verdict is Verdict.CONFIRMED_RING
        assert c.disposition.seconds_to_decide == 41.0
        assert c not in store.pending()
        assert c in store.labelled()

    def test_partial_confirmation_keeps_both_sides(self, store):
        """The most informative label: positives and negatives in one subgraph."""
        c = self.open_one(store)
        store.dispose(c.id, Verdict.CONFIRMED_PARTIAL, reason="subset_confirmed",
                      confirmed_members=["1:A"], dropped_members=["2:B"], at="x")
        assert c.disposition.confirmed_members == ["1:A"]
        assert c.disposition.dropped_members == ["2:B"]
        assert c.disposition.verdict.is_positive

    def test_the_case_row_is_never_rewritten(self, store):
        """Dispositions append as events; the alert-time record is immutable."""
        c = self.open_one(store)
        first = store.cases_file.read_text(encoding="utf-8")
        store.dispose(c.id, Verdict.NOT_A_RING, reason="single_actor", at="x")
        assert store.cases_file.read_text(encoding="utf-8") == first
        assert store.events_file.exists()

    def test_reload_replays_dispositions(self, store):
        c = self.open_one(store)
        store.dispose(c.id, Verdict.CONFIRMED_RING, reason="layering", at="x")
        fresh = CaseStore(store.path).load()
        got = fresh.get(c.id)
        assert got is not None
        assert got.disposition.verdict is Verdict.CONFIRMED_RING
        assert fresh.next_id() != c.id, "id counter must not restart"

    def test_unknown_case_raises(self, store):
        with pytest.raises(KeyError):
            store.dispose("CASE-99999", Verdict.NOT_A_RING)

    def test_pending_is_score_ordered(self, store):
        self.open_one(store, score=0.1)
        self.open_one(store, score=0.9)
        self.open_one(store, score=0.5)
        assert [c.score for c in store.pending()] == [0.9, 0.5, 0.1]

    def test_confirm_rate_is_instrumented(self, store):
        a, b = self.open_one(store), self.open_one(store)
        store.dispose(a.id, Verdict.CONFIRMED_RING, reason="layering", at="x")
        store.dispose(b.id, Verdict.NOT_A_RING, reason="single_actor", at="x")
        assert store.stats()["confirm_rate"] == pytest.approx(0.5)

    def test_training_rows_only_include_labelled_cases(self, store):
        a, b = self.open_one(store), self.open_one(store)
        store.dispose(a.id, Verdict.CONFIRMED_RING, reason="layering", at="x")
        rows = store.training_rows()
        assert len(rows) == 1
        assert rows[0]["label"] == 1
        assert rows[0]["f_conservation"] == 0.9
        assert rows[0]["detector_version"] == DETECTOR_VERSION


# --------------------------------------------------------------------------
# Queue selection
# --------------------------------------------------------------------------

class TestCaseManager:
    def test_capacity_is_respected(self, store, graph):
        m = CaseManager(store, capacity=5, control_fraction=0.0)
        cands = [cand([0, 1, 2], 0.1 * i, seed=0) for i in range(1, 20)]
        assert len(m.select(cands)) == 5

    def test_primary_lane_is_score_ordered(self, store, graph):
        m = CaseManager(store, capacity=3, control_fraction=0.0)
        cands = [cand([0, 1, 2], s) for s in (0.1, 0.9, 0.5)]
        picked = [c.score for c, _ in m.select(cands)]
        assert picked == [0.9, 0.5, 0.1]

    def test_low_scores_go_to_their_own_lane(self, store):
        m = CaseManager(store, capacity=2, control_fraction=0.0)
        cands = [cand([0, 1, 2], 0.9), cand([3, 4, 5], LOW_CONFIDENCE_SCORE - 0.01)]
        lanes = {c.score: lane for c, lane in m.select(cands)}
        assert lanes[0.9] is Lane.PRIMARY
        assert lanes[LOW_CONFIDENCE_SCORE - 0.01] is Lane.LOW_CONFIDENCE

    def test_control_arm_samples_from_below_the_cut(self, store):
        """Without this the corpus only ever describes what the detector finds."""
        m = CaseManager(store, capacity=10, control_fraction=0.2)
        cands = [cand([i, i + 100, i + 200], 1.0 - i / 100) for i in range(60)]
        picked = m.select(cands)
        controls = [c for c, lane in picked if lane is Lane.CONTROL]
        assert controls, "control arm must be populated"
        primary_scores = [c.score for c, lane in picked if lane is not Lane.CONTROL]
        assert all(c.score < min(primary_scores) for c in controls)

    def test_control_arm_can_be_disabled(self, store):
        m = CaseManager(store, capacity=10, control_fraction=0.0)
        cands = [cand([i, i + 100, i + 200], 1.0 - i / 100) for i in range(60)]
        assert not [c for c, lane in m.select(cands) if lane is Lane.CONTROL]

    def test_empty_input(self, store):
        assert CaseManager(store).select([]) == []

    def test_open_case_snapshots_the_subgraph(self, store, graph):
        m = CaseManager(store, capacity=5, control_fraction=0.0)
        c = m.open_case(cand([0, 1, 2], 0.8, seed=0), Lane.PRIMARY, graph)
        assert c.size == 3
        assert len(c.subgraph) == 3
        assert c.timeline and c.timeline[0]["kind"] == "detect"
        assert store.get(c.id) is c

    def test_features_are_snapshotted_not_referenced(self, store, graph):
        """Mutating the source afterwards must not change the stored case."""
        cd = cand([0, 1, 2], 0.8, seed=0, conservation=0.91)
        m = CaseManager(store, capacity=5, control_fraction=0.0)
        case = m.open_case(cd, Lane.PRIMARY, graph)
        cd.features.conservation = 0.0
        assert case.features["conservation"] == 0.91

    def test_evidence_lines_reflect_the_features(self, store, graph):
        cd = cand([0, 1, 2], 0.8, seed=0, has_cycle=True, shortest_cycle=3,
                  cycle_coverage=1.0, conservation=0.95)
        m = CaseManager(store, capacity=5, control_fraction=0.0)
        case = m.open_case(cd, Lane.PRIMARY, graph)
        kinds = [e["kind"] for e in case.timeline]
        assert kinds.count("evidence") == 2
