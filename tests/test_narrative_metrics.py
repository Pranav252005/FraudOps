"""Phase 5 items 2 and 3: the narrative layer's numbers, and the contract
that stops them being quoted as something they are not.

Three things are pinned here.

1. `unit="case"` is admitted by `Metric` AND requires its conditioning banner.
   Both arms are asserted. A gate that can only pass is not a gate, and this
   repository has shipped one of those already (`docs/HANDOFF.md` section 11b).

2. The draft ledger's rejection rate is `None` over an empty denominator and
   never `0.0`. The difference is the difference between "unmeasured" and "the
   model never erred", and only one of those is true here.

3. The ledger's buckets are reachable. A rejection counter that is structurally
   pinned at zero measures nothing, which is the same defect as the verifier
   that could not fail.
"""
from __future__ import annotations

import pytest

from sentinel.narrative import metrics as draft_metrics
from sentinel.report.metric import Metric, MetricContractError

CONDITIONING = (
    "Measured on the deterministic template path; the drafted path has "
    "attempted zero drafts, so this is a property of the template.")


def _case_metric(**over):
    kw = dict(id="citation_evidence_recall", value=0.88, n_units=1360,
              unit="case", ci_lower=0.86, ci_upper=0.90,
              ci_method="case_clustered_bootstrap", conditioning=CONDITIONING)
    kw.update(over)
    return Metric(**kw)


class TestTheCaseUnitIsAdmittedAndConstrained:

    def test_a_case_unit_metric_with_its_conditioning_constructs(self):
        m = _case_metric()
        assert m.unit == "case"
        assert m.ci_method == "case_clustered_bootstrap"

    def test_a_case_unit_metric_without_conditioning_is_refused(self):
        """The other arm, and the reason the unit was added to
        CONDITIONING_REQUIRED_UNITS at all.

        A citation-recall figure with no banner reads as 'the drafted
        narratives cite 88% of their evidence' -- a claim about a model that
        has never run. This makes that sentence unconstructable.
        """
        with pytest.raises(MetricContractError):
            _case_metric(conditioning=None)
        with pytest.raises(MetricContractError):
            _case_metric(conditioning="   ")

    def test_an_unknown_clustering_is_still_refused_on_the_case_unit(self):
        """Admitting a unit must not admit a bare 'bootstrap' with it."""
        with pytest.raises(MetricContractError):
            _case_metric(ci_method="bootstrap")


class TestTheRejectionRateHasNoDenominator:

    def test_an_empty_ledger_reports_none_not_zero(self):
        ledger = draft_metrics.DraftLedger()
        assert ledger.attempted == 0
        assert ledger.rejection_rate is None, (
            "a rejection rate of 0.0 over zero attempts reads as 'the model "
            "never erred'; it must be undefined")

    def test_an_unavailable_draft_does_not_enter_the_denominator(self):
        """`llm_unavailable` is a call that never happened, not a draft the
        verifier passed. Counting it would flatter the rejection rate."""
        ledger = draft_metrics.DraftLedger()
        ledger.record(draft_metrics.LLM_UNAVAILABLE)
        ledger.record(draft_metrics.TEMPLATE_FILED)
        assert ledger.attempted == 0
        assert ledger.rejection_rate is None

    def test_the_counter_can_actually_move(self):
        """The arm that proves the metric is not pinned at zero."""
        ledger = draft_metrics.DraftLedger()
        ledger.record(draft_metrics.LLM_FILED)
        ledger.record(draft_metrics.LLM_REJECTED_UNCITED)
        ledger.record(draft_metrics.LLM_REJECTED_UNVERIFIABLE)
        assert ledger.attempted == 3
        assert ledger.rejected == 2
        assert ledger.rejection_rate == pytest.approx(2 / 3)

    def test_an_unknown_outcome_raises_rather_than_being_absorbed(self):
        ledger = draft_metrics.DraftLedger()
        with pytest.raises(ValueError):
            ledger.record("llm_probably_fine")
