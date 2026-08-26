"""Phase 4 tests: the re-ranker and the simulated analyst.

The properties worth protecting here are not accuracy — that is what the
evaluation measures — but the two rules that keep the measurement honest:
features must come from the alert-time snapshot, and the split must be by time.
A random split lets the model learn from cases that had not happened yet, which
is the most common way a fraud model looks strong offline and fails live.
"""
from __future__ import annotations

import pytest

from sentinel.cases.case import Case, Lane, Verdict
from sentinel.learn.analyst import SimulatedAnalyst
from sentinel.learn.reranker import (EXCLUDED, Reranker, feature_names,
                                     time_split, vectorise)


def make_case(cid, t, label, **feats):
    base = {"n_nodes": 3.0, "conservation": 0.5, "has_temporal_cycle": False,
            "fast_passthrough_ratio": 0.0, "cycle_coverage": 0.0}
    base.update(feats)
    c = Case(id=cid, opened_at=str(t), opened_t=t, lane=Lane.PRIMARY,
             members=["1:A", "1:B", "1:C"], seed="1:A", score=0.1,
             contrib={}, features=base, motifs={}, subgraph=[])
    if label is not None:
        c.disposition.verdict = (Verdict.CONFIRMED_RING if label
                                 else Verdict.NOT_A_RING)
    return c


def corpus(n=80):
    """Separable by construction, so a failure means the plumbing is broken."""
    out = []
    for i in range(n):
        pos = i % 3 == 0
        out.append(make_case(
            f"CASE-{i:05d}", t=i * 60, label=pos,
            conservation=0.95 if pos else 0.1,
            has_temporal_cycle=pos,
            fast_passthrough_ratio=0.9 if pos else 0.05,
            cycle_coverage=1.0 if pos else 0.0,
        ))
    return out


class TestVectorise:
    def test_stable_ordering(self):
        names = feature_names({"b": 1.0, "a": 2.0, "c": True})
        assert names == ["a", "b", "c"]

    def test_channel_can_never_become_a_feature(self):
        """The 7.3x ACH leak stays out of the model, by construction."""
        assert "channel" in EXCLUDED
        assert "channel" not in feature_names({"channel": 1.0, "a": 2.0})

    def test_booleans_become_numbers(self):
        assert vectorise({"a": True, "b": False}, ["a", "b"]) == [1.0, 0.0]

    def test_missing_features_default_to_zero(self):
        assert vectorise({"a": 3.0}, ["a", "zz"]) == [3.0, 0.0]

    def test_infinities_are_neutralised(self):
        """Latency is infinite when an account never forwards; that must not
        propagate into the model as a value."""
        assert vectorise({"a": float("inf")}, ["a"]) == [0.0]
        assert vectorise({"a": float("nan")}, ["a"]) == [0.0]

    def test_non_numeric_is_ignored(self):
        assert "note" not in feature_names({"note": "text", "a": 1.0})


class TestTimeSplit:
    def test_split_is_chronological(self):
        cases = [make_case(f"C{i}", t=i * 10, label=i % 2 == 0) for i in range(10)]
        train, test, t = time_split(cases, 0.5)
        assert all(c.opened_t < t for c in train)
        assert all(c.opened_t >= t for c in test)
        assert len(train) + len(test) == len(cases)

    def test_no_case_appears_in_both(self):
        cases = [make_case(f"C{i}", t=i * 10, label=True) for i in range(20)]
        train, test, _ = time_split(cases, 0.5)
        assert not ({c.id for c in train} & {c.id for c in test})

    def test_unsorted_input_is_handled(self):
        cases = [make_case(f"C{i}", t=t, label=True)
                 for i, t in enumerate([50, 10, 30, 20, 40])]
        train, test, _ = time_split(cases, 0.5)
        assert max(c.opened_t for c in train) < min(c.opened_t for c in test)

    def test_empty_input(self):
        assert time_split([], 0.5) == ([], [], 0)


class TestReranker:
    def test_requires_enough_labels(self):
        with pytest.raises(ValueError, match="at least 20"):
            Reranker().fit(corpus(5))

    def test_rejects_single_class_labels(self):
        cases = [make_case(f"C{i}", t=i, label=False) for i in range(30)]
        with pytest.raises(ValueError, match="single-class"):
            Reranker().fit(cases)

    def test_ignores_undisposed_cases(self):
        mixed = corpus(60) + [make_case(f"P{i}", t=i, label=None)
                              for i in range(40)]
        rep = Reranker().fit(mixed)
        assert rep.n_train == 60

    def test_learns_a_separable_signal(self):
        r = Reranker()
        r.fit(corpus(90))
        strong = r.score_one({"n_nodes": 3.0, "conservation": 0.95,
                              "has_temporal_cycle": True,
                              "fast_passthrough_ratio": 0.9,
                              "cycle_coverage": 1.0})
        weak = r.score_one({"n_nodes": 3.0, "conservation": 0.1,
                            "has_temporal_cycle": False,
                            "fast_passthrough_ratio": 0.05,
                            "cycle_coverage": 0.0})
        assert strong > weak

    def test_rank_orders_by_probability(self):
        r = Reranker()
        r.fit(corpus(90))
        items = corpus(30)
        ordered, probs = r.rank(items)
        assert list(probs) == sorted(probs, reverse=True)
        assert len(ordered) == len(items)

    def test_untrained_ranker_refuses_to_score(self):
        with pytest.raises(RuntimeError):
            Reranker().score_one({"a": 1.0})
        with pytest.raises(RuntimeError):
            Reranker().rank(corpus(3))

    def test_rank_handles_empty_input(self):
        """Must still return the (items, probabilities) pair, not a bare list.

        Returning a plain [] here crashed the evaluation on tuple unpacking.
        """
        r = Reranker()
        r.fit(corpus(90))
        items, probs = r.rank([])
        assert items == [] and len(probs) == 0

    def test_accepts_dataclass_features_as_well_as_dicts(self):
        """Cases store dicts; live candidates carry the Features dataclass.

        Training on one representation and scoring on the other was a real
        crash, and would have been a silent mismatch had it not raised.
        """
        from sentinel.detect.features import Features
        r = Reranker()
        r.fit(corpus(90))
        f = Features(n_nodes=3, conservation=0.95, has_temporal_cycle=True,
                     fast_passthrough_ratio=0.9, cycle_coverage=1.0)
        assert 0.0 <= r.score_one(f) <= 1.0

    def test_importance_needs_held_out_data(self):
        """Without validation the ranker reports no importance rather than zeros."""
        rep = Reranker().fit(corpus(90))
        assert rep.importances == {}


class TestSimulatedAnalyst:
    def case(self, members):
        c = make_case("C1", t=0, label=None)
        c.members = members
        return c

    def test_full_overlap_confirms(self):
        a = SimulatedAnalyst(seed=1, miss_rate=0.0, false_confirm=0.0)
        v, reason, keep, drop = a.dispose(
            self.case(["1:A", "1:B", "1:C"]), {"1:A", "1:B", "1:C"})
        assert v is Verdict.CONFIRMED_RING
        assert drop == []

    def test_partial_overlap_yields_partial_confirmation(self):
        """The most informative label: positives and negatives in one subgraph."""
        a = SimulatedAnalyst(seed=1, miss_rate=0.0, false_confirm=0.0)
        v, reason, keep, drop = a.dispose(
            self.case(["1:A", "1:B", "1:C", "1:D"]), {"1:A", "1:B"})
        assert v is Verdict.CONFIRMED_PARTIAL
        assert set(keep) == {"1:A", "1:B"}
        assert set(drop) == {"1:C", "1:D"}

    def test_no_overlap_rejects(self):
        a = SimulatedAnalyst(seed=1, miss_rate=0.0, false_confirm=0.0)
        v, _, keep, _ = a.dispose(self.case(["1:A"]), set())
        assert v is Verdict.NOT_A_RING
        assert keep == []

    def test_analyst_is_deliberately_imperfect(self):
        """A perfect oracle would make the flywheel experiment meaningless."""
        a = SimulatedAnalyst(seed=3, miss_rate=1.0, false_confirm=0.0)
        v, _, _, _ = a.dispose(self.case(["1:A"]), {"1:A"})
        assert v is Verdict.NOT_A_RING
        assert a.stats["missed"] == 1

    def test_false_confirmations_are_counted(self):
        a = SimulatedAnalyst(seed=3, miss_rate=0.0, false_confirm=1.0)
        v, _, _, _ = a.dispose(self.case(["1:A"]), set())
        assert v is Verdict.CONFIRMED_RING
        assert a.stats["false_confirmed"] == 1

    def test_is_deterministic_for_a_seed(self):
        runs = []
        for _ in range(2):
            a = SimulatedAnalyst(seed=11)
            runs.append([a.dispose(self.case(["1:A", "1:B"]), {"1:A"})[0]
                         for _ in range(50)])
        assert runs[0] == runs[1]


class TestImportanceIsHeldOut:
    """Importance on training data of a memorising model is all zeros.

    This was a real defect: every feature reported 0.0000 while the model was
    in fact re-ranking 4x better than the hand-set weights.
    """

    def test_no_validation_means_no_importance_claimed(self):
        rep = Reranker().fit(corpus(90))
        assert rep.importances == {}, "must not report importance it cannot measure"

    def test_validation_produces_real_importance(self):
        train, test = corpus(120), corpus(60)
        for i, c in enumerate(test):
            c.opened_t += 100000
            c.id = f"T{i}"
        rep = Reranker().fit(train, validation=test)
        assert rep.importances
        assert max(rep.importances.values()) > 0.0
        assert rep.n_test == len(test)

    def test_generalisation_gap_is_reported(self):
        train, test = corpus(120), corpus(60)
        rep = Reranker().fit(train, validation=test)
        assert rep.train_ap > 0 and rep.test_ap > 0
        assert rep.ap_lift > 1.0, "must beat the base rate to be worth ranking with"
