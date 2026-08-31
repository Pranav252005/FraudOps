"""The retired blend terms, and the properties that keep the retirement honest.

`gargaml` and `stack` were measured as anti-signal and zeroed. That is a change
to the shipped ranking, so what gets tested is not "the weights are these
numbers" -- which would just restate the source -- but the invariants that would
silently break if somebody edited them later:

  * the retirement is DERIVED from the v1 literal, not hand-retyped, so the two
    cannot drift apart;
  * a retired term is still computed and still shown, because the case file is
    the product and an analyst losing sight of a GARG-AML reading is a
    regression even when the ranking improves;
  * the surviving terms keep their relative ordering, so renormalising did not
    quietly re-weight anything;
  * the score still saturates at exactly 1.0.

The measured claim itself -- that this is what moved p@10 past the size
baseline -- is tested against `data/eval_blend_v2.json` at the bottom, in the
same spirit as the funnel's numbers: a figure quoted in the README should fail
a test when it stops being true.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentinel.detect import features as F

ARTEFACT = Path(__file__).resolve().parent.parent / "data" / "eval_blend_v2.json"


class TestRetiredTerms:
    def test_retired_terms_carry_zero_weight(self):
        for term in F.RETIRED_TERMS:
            assert F.WEIGHTS[term] == 0.0

    def test_retired_terms_are_still_keys(self):
        """Zeroed, not deleted. `score()` iterates the terms dict and indexes
        WEIGHTS by name, so a missing key is a KeyError -- and more to the
        point, the case file should still show the reading."""
        for term in F.RETIRED_TERMS:
            assert term in F.WEIGHTS
            assert term in F._V1_WEIGHTS

    def test_retired_terms_still_appear_in_the_contribution_breakdown(self):
        """The analyst still sees them; they just do not drive the rank."""
        f = F.Features(gargaml=1.0, stack_score=1.0)
        _, contrib = F.score(f)
        for term in F.RETIRED_TERMS:
            assert term in contrib
            assert contrib[term] == 0.0

    def test_the_score_no_longer_responds_to_a_retired_term(self):
        """The property that actually changed the queue."""
        base = F.Features(conservation=0.5)
        loud = F.Features(conservation=0.5, gargaml=1.0, stack_score=1.0)
        assert F.score(base)[0] == pytest.approx(F.score(loud)[0])

    def test_weights_are_derived_from_the_v1_literal_not_retyped(self):
        """If someone hand-edits WEIGHTS, this fails. The renormalisation must
        stay a function of `_V1_WEIGHTS` so the audit trail cannot rot."""
        kept = sum(v for k, v in F._V1_WEIGHTS.items()
                   if k not in F.RETIRED_TERMS)
        for name, w in F.WEIGHTS.items():
            want = 0.0 if name in F.RETIRED_TERMS else F._V1_WEIGHTS[name] / kept
            assert w == pytest.approx(want)

    def test_surviving_terms_keep_their_relative_order(self):
        """Renormalising is a rescale, not a re-weighting. Any change to the
        ORDER of the surviving terms would be a second, unstated decision."""
        surv = [k for k in F._V1_WEIGHTS if k not in F.RETIRED_TERMS]
        by_v1 = sorted(surv, key=lambda k: (-F._V1_WEIGHTS[k], k))
        by_now = sorted(surv, key=lambda k: (-F.WEIGHTS[k], k))
        assert by_v1 == by_now

    def test_weights_still_sum_to_one(self):
        assert sum(F.WEIGHTS.values()) == pytest.approx(1.0)

    def test_v1_weights_summed_to_one_too(self):
        """So the renormalisation is a fair comparison and not a rescale of a
        blend that never summed correctly in the first place."""
        assert sum(F._V1_WEIGHTS.values()) == pytest.approx(1.0)


@pytest.fixture(scope="module")
def report():
    """Skipped rather than failed when the artefact is absent: `data/` is not
    in the repository, and a fresh clone should not fail its suite for that."""
    if not ARTEFACT.exists():
        pytest.skip("needs data/eval_blend_v2.json "
                    "(python scripts/eval_blend_v2.py)")
    return json.loads(ARTEFACT.read_text(encoding="utf-8"))


class TestMeasuredClaim:
    """The numbers the README states, checked against the artefact."""

    def test_the_artefact_retired_the_same_terms_the_code_did(self, report):
        assert tuple(report["retired_terms"]) == tuple(F.RETIRED_TERMS)

    def test_both_retired_terms_measured_below_half_with_size_held_constant(
            self, report):
        """The whole justification. An AUC at or above 0.5 would mean the term
        was not anti-signal and the retirement was unearned."""
        for term in F.RETIRED_TERMS:
            assert report["per_term"][term]["stratified_auc"] < 0.5
            assert report["per_term"][term]["verdict"] == "INVERTED"

    def test_the_score_was_not_merely_a_size_proxy(self, report):
        """The hypothesis that had to be ruled out before the real one mattered."""
        assert report["size_proxy_check"]["spearman_blend_size"] < 0.0

    def test_shipped_beats_size_at_both_k_10_and_k_20(self, report):
        """The repo's ship criterion, restated as a test."""
        paired = report["paired_vs_size"]["shipped (terms retired)"]
        for k in ("10", "20"):
            assert paired[k]["excludes_zero"], f"k={k} no longer excludes zero"
            assert paired[k]["point"] > 0
        assert report["ship"]["shipped (terms retired)"] is True

    def test_the_v1_blend_did_not_meet_that_criterion(self, report):
        """The problem being fixed, kept as a test so it cannot quietly become
        untrue and take the justification with it."""
        paired = report["paired_vs_size"]["v1 (retired terms restored)"]
        assert not paired["10"]["excludes_zero"]
        assert not paired["20"]["excludes_zero"]

    def test_the_fitted_model_does_not_beat_the_removal(self, report):
        """Why the shipped fix is a removal and not a learned model: the NNLS
        fit's point estimate sits inside the removal's interval, so it buys
        nothing measurable for the label cost it charges."""
        removal = report["paired_vs_size"]["shipped (terms retired)"]["10"]
        fit = report["paired_vs_size"]["nnls fit on train"]["10"]
        assert removal["lo"] <= fit["point"] <= removal["hi"]

    def test_the_split_is_ring_disjoint(self, report):
        assert report["design"]["ring_overlap"] == 0

    def test_the_time_split_caveat_is_recorded(self, report):
        """This measurement inherits README open problem 2 and must say so."""
        assert report["design"]["time_disjoint"] is False
