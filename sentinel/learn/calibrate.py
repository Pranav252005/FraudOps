"""Online recalibration from analyst verdicts, using counts rather than records.

This is the loop that lets the scorer improve as analysts work the queue,
without the raw transaction graph ever being an input. It reads dispositions
off the append-only case store, reduces them to one 2x2 table per score term,
and moves the weights. `sentinel/graph`, `sentinel/stream` and the compiled
parquet are never imported here, and a test asserts that -- because "the loop
needs aggregate counts, not the database" has to be a verified property, not a
design intention. It is also the property that makes the same loop viable
across institutions that cannot share records, which is the shape RBI's DPIP
exists to enable.

Three things make this statistically defensible rather than a feedback loop
that congratulates itself.

**1. The control arm is what makes the estimate valid at all.**
A loop trained only on cases the detector surfaced learns only about the top
of its own queue: a term that would have caught rings the detector never
showed anyone accumulates no evidence either way, and the system converges
onto its own blind spots with rising confidence. `CaseManager` already draws
`CONTROL_FRACTION` of capacity at random from *below* the cut
(`sentinel/cases/manager.py`), which is the unbiased sample of the
unflagged population. Both lanes are combined by inverse-propensity weighting
-- see `LANE_WEIGHTS` for the approximation that involves and the one-line
change that would make it exact.

**2. A weight does not move until its evidence excludes chance.**
Point estimates on this data move a lot (see `sentinel/eval/bootstrap.py`).
An update rule that fires every cycle on a handful of noisy verdicts will
produce confident, plausible, wrong weights -- the exact failure mode this
project keeps a bug catalogue for. So every proposed move carries a bootstrap
CI on the term's lift, and a term whose interval contains 1.0 does not move.
The record says it did not move, and why.

**3. Updates shrink toward the current weight.**
Even a term that clears the gate jumps only part of the way to its estimate,
because the estimate is itself an interval and the gate is a threshold, not a
proof. Weights are renormalised to sum to 1.0 afterwards, preserving the
invariant `sentinel/detect/features.py` already asserts.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sentinel.cases.manager import CONTROL_FRACTION
from sentinel.detect.features import WEIGHTS
from sentinel.eval.bootstrap import bootstrap_ci

# Inverse-propensity weights per lane.
#
# PRIMARY cases are taken with certainty from above the cut, so their
# propensity is 1.0. CONTROL cases are a random draw from everything below it,
# so each stands for many unobserved candidates and is up-weighted.
#
# **This is an approximation and the exact fix is small.** The true control
# propensity in a cycle is `n_control / len(rest)`, which varies per cycle and
# is not currently recorded on the case. `1 / CONTROL_FRACTION` uses the
# capacity share as a stand-in. Recording the realised propensity at
# `CaseManager.select` time and reading it off the case would make this exact;
# until then the number below is a documented stand-in rather than a measured
# one, and the ratio between lanes -- not either weight alone -- is what the
# estimate depends on.
LANE_WEIGHTS = {
    "primary": 1.0,
    "low_confidence": 1.0,
    "control": 1.0 / CONTROL_FRACTION if CONTROL_FRACTION else 1.0,
}

# A term must be observed at least this many times, in both the fired and
# not-fired arms, before a CI on its lift is meaningful at all. The gate below
# would usually reject a term with less evidence anyway; this stops the
# bootstrap being run over a handful of records and reported as if it meant
# something.
MIN_OBSERVATIONS_PER_ARM = 20

# How far a term moves toward its estimated weight once it clears the gate.
# Deliberately well below 1.0: the estimate is the midpoint of an interval,
# and the gate is a threshold rather than a proof.
LEARNING_RATE = 0.25

# Reasons a term did not move. A closed set, because "why didn't this change"
# is the question the audit log exists to answer.
MOVED = "moved"
TOO_FEW_OBSERVATIONS = "too_few_observations"
CI_INCLUDES_ONE = "ci_includes_one"
NOT_A_SCORED_TERM = "not_a_scored_term"


@dataclass
class TermEvidence:
    """The 2x2 table for one score term, in propensity-weighted counts."""
    term: str
    fired_n: float = 0.0
    fired_positive: float = 0.0
    not_fired_n: float = 0.0
    not_fired_positive: float = 0.0
    raw_fired_n: int = 0
    raw_not_fired_n: int = 0

    @property
    def rate_fired(self) -> float:
        return self.fired_positive / self.fired_n if self.fired_n else 0.0

    @property
    def rate_not_fired(self) -> float:
        return (self.not_fired_positive / self.not_fired_n
                if self.not_fired_n else 0.0)

    @property
    def lift(self) -> float:
        """P(confirmed | fired) / P(confirmed | not fired).

        `inf` when the term fired on confirmations and never on anything else
        -- a real, if extreme, signal. 1.0 when neither arm confirmed
        anything, which is the honest "no information" value.
        """
        base = self.rate_not_fired
        if base <= 0:
            return float("inf") if self.rate_fired > 0 else 1.0
        return self.rate_fired / base

    @property
    def prevalence(self) -> float:
        """Share of cases where this term fired at all.

        A term near 0.0 or 1.0 cannot discriminate no matter what its lift
        says -- `cross_border` firing on 60% of candidates and
        `temporal_cycle` on 0.03% are both, in different directions, terms
        carrying almost no separating information.
        """
        total = self.raw_fired_n + self.raw_not_fired_n
        return self.raw_fired_n / total if total else 0.0

    def to_dict(self) -> dict:
        return {"term": self.term, "fired_n": self.fired_n,
                "fired_positive": self.fired_positive,
                "not_fired_n": self.not_fired_n,
                "not_fired_positive": self.not_fired_positive,
                "raw_fired_n": self.raw_fired_n,
                "raw_not_fired_n": self.raw_not_fired_n,
                "rate_fired": self.rate_fired,
                "rate_not_fired": self.rate_not_fired,
                "lift": self.lift, "prevalence": self.prevalence}


@dataclass
class TermUpdate:
    term: str
    old_weight: float
    new_weight: float
    status: str
    lift: float
    ci_lo: float
    ci_hi: float
    evidence: TermEvidence

    @property
    def moved(self) -> bool:
        return self.status == MOVED

    def to_dict(self) -> dict:
        return {"term": self.term, "old_weight": self.old_weight,
                "new_weight": self.new_weight, "status": self.status,
                "lift": self.lift, "ci_lo": self.ci_lo, "ci_hi": self.ci_hi,
                "evidence": self.evidence.to_dict()}


@dataclass
class Calibration:
    """One recalibration pass: the proposed weights and the reasoning."""
    weights: dict[str, float]
    updates: list[TermUpdate]
    n_cases: int
    n_positive: int
    base_rate: float
    optimal_k: int | None = None
    break_even_precision: float | None = None
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def moved_terms(self) -> list[str]:
        return [u.term for u in self.updates if u.moved]

    def to_dict(self) -> dict:
        return {"at": self.at, "n_cases": self.n_cases,
                "n_positive": self.n_positive, "base_rate": self.base_rate,
                "optimal_k": self.optimal_k,
                "break_even_precision": self.break_even_precision,
                "weights": dict(self.weights),
                "moved": self.moved_terms,
                "updates": [u.to_dict() for u in self.updates]}


# --- counting ----------------------------------------------------------------

def _fired(case, term: str) -> bool:
    """Did this term contribute to the case's score at alert time?

    Read off the stored per-term contribution rather than recomputed, so the
    evidence describes the score the analyst actually saw -- recomputing under
    today's weights would silently rewrite history every time the weights move.
    """
    return (getattr(case, "contrib", None) or {}).get(term, 0.0) > 0.0


def gather_evidence(cases, terms=None) -> dict[str, TermEvidence]:
    """Reduce disposed cases to one propensity-weighted 2x2 table per term.

    Only resolved cases count. `INSUFFICIENT_EVIDENCE` is a resolved verdict
    but not a judgement about the candidate, so it is excluded from both arms
    rather than counted as a negative -- treating "the analyst could not tell"
    as "not a ring" would bias every term toward zero lift.
    """
    terms = list(WEIGHTS) if terms is None else list(terms)
    evidence = {t: TermEvidence(term=t) for t in terms}

    for case in cases:
        verdict = case.disposition.verdict
        if not verdict.is_resolved or verdict.value == "insufficient_evidence":
            continue
        weight = LANE_WEIGHTS.get(case.lane.value, 1.0)
        positive = 1.0 if verdict.is_positive else 0.0
        for term in terms:
            ev = evidence[term]
            if _fired(case, term):
                ev.fired_n += weight
                ev.fired_positive += weight * positive
                ev.raw_fired_n += 1
            else:
                ev.not_fired_n += weight
                ev.not_fired_positive += weight * positive
                ev.raw_not_fired_n += 1
    return evidence


# --- the gate ----------------------------------------------------------------

def _lift_ci(cases, term: str, n_resamples: int = 500, seed: int = 7) -> dict:
    """Bootstrap CI on one term's lift, resampling whole cases.

    The resampling unit is the case, which is the unit an analyst disposes of
    and the unit that arrives independently here. That differs from
    `eval_funnel`'s cycle-level resampling on purpose: cases in the store span
    many cycles and are not clustered the way candidates within one generation
    run are.
    """
    records = []
    for case in cases:
        verdict = case.disposition.verdict
        if not verdict.is_resolved or verdict.value == "insufficient_evidence":
            continue
        records.append({
            "w": LANE_WEIGHTS.get(case.lane.value, 1.0),
            "fired": _fired(case, term),
            "pos": 1.0 if verdict.is_positive else 0.0,
        })

    def statistic(sample):
        fn = sum(r["w"] for r in sample if r["fired"])
        fp = sum(r["w"] * r["pos"] for r in sample if r["fired"])
        nn = sum(r["w"] for r in sample if not r["fired"])
        np_ = sum(r["w"] * r["pos"] for r in sample if not r["fired"])
        rate_fired = fp / fn if fn else 0.0
        rate_not = np_ / nn if nn else 0.0
        if rate_not <= 0:
            # Unbounded lift would dominate every percentile. Cap it at a
            # value that still reads as "strong" without making the interval
            # meaningless.
            return 10.0 if rate_fired > 0 else 1.0
        return rate_fired / rate_not

    return bootstrap_ci(records, statistic, n_resamples=n_resamples, seed=seed)


def calibrate(cases, weights=None, *, learning_rate: float = LEARNING_RATE,
              min_observations: int = MIN_OBSERVATIONS_PER_ARM,
              n_resamples: int = 500, seed: int = 7,
              precision_at_k: dict | None = None,
              cost_model=None) -> Calibration:
    """Propose updated weights from disposed cases. Pure: nothing is written.

    Returns the proposal *and* the reasoning for every term, including the
    terms that did not move. A calibration record that only lists changes
    cannot be audited, because the interesting question after a quiet pass is
    which terms were considered and rejected.
    """
    weights = dict(WEIGHTS if weights is None else weights)
    cases = list(cases)

    resolved = [c for c in cases
                if c.disposition.verdict.is_resolved
                and c.disposition.verdict.value != "insufficient_evidence"]
    n_positive = sum(1 for c in resolved if c.disposition.verdict.is_positive)
    base_rate = n_positive / len(resolved) if resolved else 0.0

    evidence = gather_evidence(resolved, terms=list(weights))
    updates: list[TermUpdate] = []
    proposed = dict(weights)

    for term, weight in weights.items():
        ev = evidence.get(term)
        if ev is None:
            updates.append(TermUpdate(term, weight, weight, NOT_A_SCORED_TERM,
                                      1.0, 1.0, 1.0, TermEvidence(term=term)))
            continue

        if (ev.raw_fired_n < min_observations
                or ev.raw_not_fired_n < min_observations):
            updates.append(TermUpdate(term, weight, weight,
                                      TOO_FEW_OBSERVATIONS, ev.lift,
                                      float("nan"), float("nan"), ev))
            continue

        ci = _lift_ci(resolved, term, n_resamples=n_resamples, seed=seed)
        lo, hi = ci["lo"], ci["hi"]
        if lo <= 1.0 <= hi:
            updates.append(TermUpdate(term, weight, weight, CI_INCLUDES_ONE,
                                      ci["point"], lo, hi, ev))
            continue

        # Target weight is proportional to the term's evidenced lift above
        # parity. A term with lift 1.0 contributes nothing and is pulled
        # toward zero; a term with lift 3.0 is pulled up.
        target = max(0.0, min(1.0, weight * min(ci["point"], 5.0)))
        new = weight + learning_rate * (target - weight)
        proposed[term] = new
        updates.append(TermUpdate(term, weight, new, MOVED, ci["point"], lo,
                                  hi, ev))

    proposed = _renormalise(proposed)
    for u in updates:
        u.new_weight = proposed[u.term]

    optimal, break_even = None, None
    if cost_model is not None:
        from sentinel.economics.cost import optimal_k as _optimal_k
        break_even = cost_model.break_even_precision()
        if precision_at_k:
            optimal = _optimal_k(precision_at_k, cost_model)

    return Calibration(weights=proposed, updates=updates,
                       n_cases=len(resolved), n_positive=n_positive,
                       base_rate=base_rate, optimal_k=optimal,
                       break_even_precision=break_even)


def _renormalise(weights: dict[str, float]) -> dict[str, float]:
    """Scale to sum 1.0, preserving the invariant features.py asserts.

    A degenerate all-zero proposal falls back to a uniform blend rather than
    dividing by zero: a scorer with no weights ranks nothing, which would be a
    silent outage rather than a visible failure.
    """
    total = sum(weights.values())
    if total <= 0:
        n = len(weights) or 1
        return {k: 1.0 / n for k in weights}
    return {k: v / total for k, v in weights.items()}


# --- the audit trail ---------------------------------------------------------

def append_record(calibration: Calibration, path: Path) -> None:
    """Append one calibration to the JSONL audit log.

    Append-only for the same reason the case store is. This file is the
    evidence that the gate refused the terms it says it refused, and a log you
    can rewrite proves nothing.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(calibration.to_dict()) + "\n")
