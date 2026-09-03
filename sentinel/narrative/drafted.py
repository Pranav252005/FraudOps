"""The drafted narrative path, kept in its own module for standing rule 6.

WHY THIS IS NOT IN `str_narrative.py`. Rule 6 says `sentinel.llm` must not be
reachable from any measured path, and `tests/test_measured_path_closure.py`
enforces it by walking the import graph STATICALLY from every `scripts/eval_*.py`
entry point -- function-local imports included, deliberately, because a
conditional import is still a reachable one.

While `draft_and_verify` lived in `str_narrative.py`, every script that merely
wanted to render a template narrative dragged `sentinel.llm` into its closure.
Three measured entry points tripped rule 6 that way at once
(`eval_citation_recall.py`, `eval_verifier_catch_rate.py`, and a third since
removed), and none of them ever called a model. The fix is not to exempt them.
The fix is that a template-only measurement should not be able to reach the
drafting code at all, which is now true by construction: `str_narrative.py`
imports nothing from here, and the dependency runs one way.

The contract is unchanged and is restated because it is the point of the
module: whatever wrote the text, `verify` runs over it, and a failure is a hard
stop. A rejected draft is discarded whole, never partially salvaged, and the
template runs instead so the queue keeps moving.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sentinel.cases.evidence import CaseFile
from sentinel.narrative.citation import VerificationResult, verify
from sentinel.narrative.str_narrative import generate_and_verify

SOURCE_TEMPLATE = "template"
SOURCE_LLM = "llm"


@dataclass
class NarrativeOutcome:
    """A narrative plus the full provenance of how it came to be.

    `source` records which generator produced the filed text, and
    `rejected_draft` preserves the verification failure of a model draft that
    was stopped. Both go into the case record: a filed narrative that does not
    say whether a model wrote it is not auditable, and a rejected draft that
    leaves no trace makes the guardrail unfalsifiable.
    """
    narrative: str
    verification: VerificationResult
    source: str
    outcome: str
    model: str = ""
    llm_failure: str | None = None
    llm_detail: str = ""
    rejected_draft: str | None = None
    rejected_reasons: list[str] = field(default_factory=list)


def draft_and_verify(case_file: CaseFile, *, source: str = "auto",
                     ledger=None, draft_fn=None) -> NarrativeOutcome:
    """Produce a verified narrative, preferring a model draft when available.

    The contract is the one this module's docstring pre-committed to and it is
    unchanged: whatever wrote the text, `verify` runs over it, and a failure
    is a hard stop. The only thing the model path adds is what happens *after*
    the stop -- the draft is discarded and the template runs instead, so the
    queue keeps moving. A rejected draft is never filed and never partially
    salvaged.

    `source="template"` forces the deterministic path. `source="auto"` tries
    the model first and falls back on any failure, including no key being
    configured, which is why an install with no `.env` behaves exactly as it
    did before this function existed.
    """
    from sentinel.narrative import metrics as _metrics

    if source not in ("auto", SOURCE_TEMPLATE, SOURCE_LLM):
        raise ValueError(f"unknown narrative source: {source!r}")

    valid_ids = case_file.valid_citation_ids()

    def _record(outcome: str, detail: str = "", model: str = "") -> None:
        if ledger is not None:
            ledger.record(outcome, case_id=case_file.case_id, detail=detail,
                          model=model)

    llm_failure = llm_detail = None
    rejected_draft = None
    rejected_reasons: list[str] = []
    model = ""

    if source in ("auto", SOURCE_LLM):
        if draft_fn is None:
            from sentinel.narrative.llm_draft import draft as draft_fn
        attempt = draft_fn(case_file)
        model = attempt.model
        if not attempt.ok:
            llm_failure, llm_detail = attempt.failure, attempt.detail
            _record(_metrics.LLM_UNAVAILABLE, detail=attempt.detail or "",
                    model=model)
        else:
            result = verify(attempt.text, valid_ids)
            if result.ok:
                _record(_metrics.LLM_FILED, model=model)
                return NarrativeOutcome(narrative=attempt.text,
                                        verification=result,
                                        source=SOURCE_LLM,
                                        outcome=_metrics.LLM_FILED,
                                        model=model)
            # Rejected. Keep the draft and the reasons for the audit trail,
            # then fall through to the template.
            rejected_draft = attempt.text
            rejected_reasons = result.failures
            outcome = (_metrics.LLM_REJECTED_UNVERIFIABLE
                       if result.unverifiable_citations
                       else _metrics.LLM_REJECTED_UNCITED)
            _record(outcome, detail="; ".join(rejected_reasons)[:500],
                    model=model)

    narrative, result = generate_and_verify(case_file)
    _record(_metrics.TEMPLATE_FILED, model="")
    return NarrativeOutcome(narrative=narrative, verification=result,
                            source=SOURCE_TEMPLATE,
                            outcome=_metrics.TEMPLATE_FILED, model=model,
                            llm_failure=llm_failure, llm_detail=llm_detail or "",
                            rejected_draft=rejected_draft,
                            rejected_reasons=rejected_reasons)
