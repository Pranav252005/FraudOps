"""The recalibration loop, and the three properties that keep it honest.

Most of this file is about refusing to update. That is the point: an update
rule that always fires is the failure mode, not the feature. The tests that
matter are the evidence gate, the control-arm weighting, and the assertion
that this module cannot reach the transaction graph.
"""
from __future__ import annotations

import json

import pytest

from sentinel.cases.case import Case, Disposition, Lane, Verdict
from sentinel.learn import calibrate as C


def make_case(case_id: str, *, fired: dict, verdict: Verdict,
              lane: Lane = Lane.PRIMARY) -> Case:
    """A case carrying only what the calibration loop is allowed to read."""
    contrib = {term: (0.1 if on else 0.0) for term, on in fired.items()}
    return Case(id=case_id, opened_at="2022-09-01T00:00:00+00:00", opened_t=0,
                lane=lane, members=["0011:AAA", "0011:BBB"], seed="0011:AAA",
                score=sum(contrib.values()), contrib=contrib, features={},
                motifs={}, subgraph=[],
                disposition=Disposition(verdict=verdict, at="2022-09-02T00:00:00+00:00"))


def corpus(n_fired_pos, n_fired_neg, n_unfired_pos, n_unfired_neg,
           term="conservation", lane=Lane.PRIMARY):
    """A corpus where exactly one term separates confirmations from the rest."""
    cases, i = [], 0
    for count, on, verdict in (
            (n_fired_pos, True, Verdict.CONFIRMED_RING),
            (n_fired_neg, True, Verdict.NOT_A_RING),
            (n_unfired_pos, False, Verdict.CONFIRMED_RING),
            (n_unfired_neg, False, Verdict.NOT_A_RING)):
        for _ in range(count):
            i += 1
            cases.append(make_case(f"CASE-{i:04d}", fired={term: on},
                                   verdict=verdict, lane=lane))
    return cases


# --- the gate ----------------------------------------------------------------

def test_a_term_with_thin_evidence_does_not_move():
    """Five observations must not be allowed to move a weight, however
    dramatic the apparent lift."""
    cases = corpus(5, 0, 0, 5)
    result = C.calibrate(cases, weights={"conservation": 1.0})
    update = result.updates[0]
    assert update.status == C.TOO_FEW_OBSERVATIONS
    assert update.old_weight == update.new_weight


def test_a_term_whose_ci_includes_one_does_not_move():
    """A term that fires at the same rate on confirmations and rejections has
    a lift of 1.0 and must be left alone."""
    cases = corpus(30, 30, 30, 30)
    result = C.calibrate(cases, weights={"conservation": 1.0},
                         n_resamples=200)
    update = result.updates[0]
    assert update.status == C.CI_INCLUDES_ONE
    assert update.ci_lo <= 1.0 <= update.ci_hi
    assert update.new_weight == update.old_weight


def test_a_term_with_strong_separated_evidence_moves():
    cases = corpus(60, 5, 5, 60)
    result = C.calibrate(cases, weights={"conservation": 0.5, "cycle": 0.5},
                         n_resamples=200)
    moved = {u.term: u for u in result.updates}
    assert moved["conservation"].status == C.MOVED
    assert moved["conservation"].ci_lo > 1.0


def test_every_term_is_recorded_including_the_ones_that_did_not_move():
    """A calibration log that lists only changes cannot be audited."""
    cases = corpus(60, 5, 5, 60)
    result = C.calibrate(cases, weights={"conservation": 0.5, "cycle": 0.5},
                         n_resamples=200)
    assert {u.term for u in result.updates} == {"conservation", "cycle"}
    assert all(u.status in (C.MOVED, C.CI_INCLUDES_ONE,
                            C.TOO_FEW_OBSERVATIONS, C.NOT_A_SCORED_TERM)
               for u in result.updates)


# --- invariants ---------------------------------------------------------------

def test_weights_are_renormalised_to_one():
    cases = corpus(60, 5, 5, 60)
    result = C.calibrate(cases, weights={"conservation": 0.5, "cycle": 0.5},
                         n_resamples=200)
    assert sum(result.weights.values()) == pytest.approx(1.0)


def test_an_all_zero_proposal_falls_back_to_uniform():
    """A scorer with no weights ranks nothing -- a silent outage."""
    assert C._renormalise({"a": 0.0, "b": 0.0}) == {"a": 0.5, "b": 0.5}


def test_insufficient_evidence_is_excluded_from_both_arms():
    """Counting 'the analyst could not tell' as a negative would bias every
    term toward zero lift."""
    cases = corpus(30, 30, 30, 30)
    cases += [make_case(f"CASE-9{i:03d}", fired={"conservation": True},
                        verdict=Verdict.INSUFFICIENT_EVIDENCE)
              for i in range(50)]
    result = C.calibrate(cases, weights={"conservation": 1.0}, n_resamples=100)
    assert result.n_cases == 120
    evidence = result.updates[0].evidence
    assert evidence.raw_fired_n == 30 + 30


# --- the control arm ----------------------------------------------------------

def test_control_cases_are_up_weighted_relative_to_primary():
    """One control case stands for the many below-cut candidates it was
    randomly drawn from; without that the estimate only describes the top of
    the queue."""
    primary = corpus(10, 10, 10, 10, lane=Lane.PRIMARY)
    control = corpus(10, 10, 10, 10, lane=Lane.CONTROL)
    ev_p = C.gather_evidence(primary)["conservation"]
    ev_c = C.gather_evidence(control)["conservation"]
    assert ev_c.fired_n > ev_p.fired_n
    assert ev_c.fired_n == pytest.approx(ev_p.fired_n
                                         * C.LANE_WEIGHTS["control"])
    # Raw counts are untouched, so prevalence stays a real proportion.
    assert ev_c.raw_fired_n == ev_p.raw_fired_n


def test_prevalence_reads_raw_counts_not_weighted_ones():
    cases = corpus(25, 25, 25, 25)
    ev = C.gather_evidence(cases)["conservation"]
    assert ev.prevalence == pytest.approx(0.5)


def test_lift_is_one_when_neither_arm_confirmed_anything():
    """The honest 'no information' value, not a divide-by-zero."""
    cases = corpus(0, 40, 0, 40)
    assert C.gather_evidence(cases)["conservation"].lift == 1.0


# --- the property that makes the whole design claim true ----------------------

def test_calibration_never_reaches_the_transaction_graph():
    """'The loop needs aggregate counts, not the database' has to be verified,
    not intended -- it is also what makes the same loop viable across
    institutions that cannot share records.

    Checked in a subprocess against the *transitive* import set, not the
    module's own import lines -- a direct-import check would pass while a
    dependency quietly dragged the parquet reader in behind it.
    """
    import subprocess
    import sys

    probe = (
        "import sys; import sentinel.learn.calibrate; "
        "bad=[m for m in sys.modules if m.startswith(('sentinel.graph',"
        "'sentinel.stream','sentinel.data','pandas','pyarrow'))]; "
        "print(','.join(sorted(bad)))"
    )
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == "", (
        f"calibration pulled in transaction-data modules: {out.stdout.strip()}")


# --- the audit trail ----------------------------------------------------------

def test_append_record_is_append_only(tmp_path):
    cases = corpus(60, 5, 5, 60)
    path = tmp_path / "nested" / "calibration.jsonl"
    for _ in range(2):
        C.append_record(C.calibrate(cases, weights={"conservation": 1.0},
                                    n_resamples=100), path)
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 2
    assert "updates" in rows[0] and rows[0]["n_cases"] == 130


def test_record_carries_the_reason_a_term_did_not_move(tmp_path):
    cases = corpus(30, 30, 30, 30)
    result = C.calibrate(cases, weights={"conservation": 1.0}, n_resamples=100)
    row = result.to_dict()
    assert row["moved"] == []
    assert row["updates"][0]["status"] == C.CI_INCLUDES_ONE


# --- cost integration ---------------------------------------------------------

def test_cost_model_attaches_break_even_and_optimal_k():
    from sentinel.economics.cost import CostModel

    cases = corpus(60, 5, 5, 60)
    model = CostModel(analyst_minutes_per_case=60.0,
                      analyst_cost_per_hour=1000.0,
                      value_at_risk_per_ring=100_000.0, recovery_rate=0.5,
                      analyst_false_approval_rate=0.0,
                      harm_per_wrong_action=0.0)
    result = C.calibrate(cases, weights={"conservation": 1.0},
                         n_resamples=100, cost_model=model,
                         precision_at_k={10: 0.10, 50: 0.06})
    assert result.break_even_precision == pytest.approx(0.02)
    assert result.optimal_k == 50
