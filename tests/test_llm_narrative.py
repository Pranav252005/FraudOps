"""The drafted narrative path, and the guarantee it exists to demonstrate.

The load-bearing test here is `test_invented_citation_is_stopped_before_filing`.
The citation verifier was written for a hallucination that the template path
cannot produce; this is the first text in the project that can actually fail
it, so this file is where the guardrail stops being an assertion.
"""
from __future__ import annotations

import httpx
import pytest

from sentinel.cases.evidence import (CaseFile, MemberRole, Provenance,
                                     REG_PMLA_MOR_2005, ROLE_PASS_THROUGH,
                                     STAGE_EVIDENCE_ASSEMBLY, Transaction)
from sentinel.llm import client as llm_client
from sentinel.narrative import metrics
from sentinel.narrative.llm_draft import Draft, build_prompt
from sentinel.narrative.str_narrative import (SOURCE_LLM, SOURCE_TEMPLATE,
                                              draft_and_verify, generate)


# --- fixtures ---------------------------------------------------------------

@pytest.fixture
def case_file() -> CaseFile:
    txns = [
        Transaction("TXN-00000001", "2022-09-01T10:00:00+00:00", "0011:AAA",
                    "0011:BBB", 250000.0, "USD", "ACH"),
        Transaction("TXN-00000002", "2022-09-01T11:30:00+00:00", "0011:BBB",
                    "0022:CCC", 249000.0, "USD", "ACH"),
    ]
    members = [
        MemberRole("0011:AAA", "SOURCE", 0, 1, ["TXN-00000001"]),
        MemberRole("0011:BBB", ROLE_PASS_THROUGH, 1, 1,
                   ["TXN-00000001", "TXN-00000002"]),
        MemberRole("0022:CCC", "SINK", 1, 0, ["TXN-00000002"]),
    ]
    return CaseFile(
        case_id="CASE-0001", members=members, transactions=txns,
        typology="SCATTER-GATHER",
        typology_evidence=["pass-through ratio 0.99", "fast forward < 2h"],
        feature_snapshot={"passthrough_ratio": 0.996, "n_countries": 2},
        provenance=[Provenance(STAGE_EVIDENCE_ASSEMBLY, "v1", "run-1",
                               "2022-09-01T12:00:00+00:00")],
    )


def _fixed_draft(text, *, failure=None, detail="", model="test/model"):
    def _draft(case_file):
        return Draft(text=text, failure=failure, detail=detail, model=model)
    return _draft


# --- the guarantee ----------------------------------------------------------

def test_invented_citation_is_stopped_before_filing(case_file):
    """A draft citing a transaction id that does not exist in the case file
    must never reach the returned narrative."""
    hallucinated = (
        "WHO: Three accounts are involved in this pattern [CASE-0001].\n\n"
        "WHAT: Account 0011:BBB forwarded USD 249,000.00 to a fourth account "
        "in Singapore [TXN-99999999].")
    ledger = metrics.DraftLedger()

    outcome = draft_and_verify(case_file, ledger=ledger,
                               draft_fn=_fixed_draft(hallucinated))

    assert outcome.source == SOURCE_TEMPLATE
    assert "TXN-99999999" not in outcome.narrative
    assert "Singapore" not in outcome.narrative
    assert outcome.rejected_draft == hallucinated
    assert "TXN-99999999" in " ".join(outcome.rejected_reasons)
    assert ledger.counts[metrics.LLM_REJECTED_UNVERIFIABLE] == 1
    assert ledger.counts[metrics.TEMPLATE_FILED] == 1
    assert ledger.counts[metrics.LLM_FILED] == 0


def test_uncited_fact_is_stopped_before_filing(case_file):
    """A fact-bearing sentence with no citation at all is the other rejection
    mode, and it is counted separately because it has a different fix."""
    uncited = ("WHO: Three accounts are involved [CASE-0001].\n\n"
               "WHAT: A total of USD 499,000.00 moved between them.")
    ledger = metrics.DraftLedger()

    outcome = draft_and_verify(case_file, ledger=ledger,
                               draft_fn=_fixed_draft(uncited))

    assert outcome.source == SOURCE_TEMPLATE
    assert ledger.counts[metrics.LLM_REJECTED_UNCITED] == 1
    assert ledger.counts[metrics.LLM_REJECTED_UNVERIFIABLE] == 0


def test_a_clean_draft_is_filed_and_attributed(case_file):
    """A draft that passes the verifier is used, and says a model wrote it."""
    clean = (
        "WHO: Three accounts are involved in this suspected pattern "
        "[CASE-0001].\n\n"
        "WHAT: Account 0011:AAA sent USD 250,000.00 to account 0011:BBB "
        "[TXN-00000001], which forwarded USD 249,000.00 onward "
        "[TXN-00000002].\n\n"
        "CONCLUSION: The filing obligation is noted "
        f"[{REG_PMLA_MOR_2005}].")
    ledger = metrics.DraftLedger()

    outcome = draft_and_verify(case_file, ledger=ledger,
                               draft_fn=_fixed_draft(clean))

    assert outcome.source == SOURCE_LLM
    assert outcome.narrative == clean
    assert outcome.model == "test/model"
    assert outcome.verification.ok
    assert ledger.counts[metrics.LLM_FILED] == 1
    assert ledger.counts[metrics.TEMPLATE_FILED] == 0


# --- fallback behaviour -----------------------------------------------------

def test_unavailable_model_falls_back_silently(case_file):
    """No key, a timeout, or a 4xx must all keep the queue moving."""
    ledger = metrics.DraftLedger()
    outcome = draft_and_verify(
        case_file, ledger=ledger,
        draft_fn=_fixed_draft(None, failure=llm_client.NOT_CONFIGURED,
                              detail="no key", model=""))

    assert outcome.source == SOURCE_TEMPLATE
    assert outcome.llm_failure == llm_client.NOT_CONFIGURED
    assert outcome.narrative == generate(case_file)
    assert ledger.counts[metrics.LLM_UNAVAILABLE] == 1


def test_template_source_never_calls_the_model(case_file):
    def _explode(case_file):
        raise AssertionError("the model must not be called for source=template")

    outcome = draft_and_verify(case_file, source=SOURCE_TEMPLATE,
                               draft_fn=_explode)
    assert outcome.source == SOURCE_TEMPLATE


def test_unknown_source_is_rejected(case_file):
    with pytest.raises(ValueError):
        draft_and_verify(case_file, source="magic")


# --- the prompt -------------------------------------------------------------

def test_prompt_enumerates_the_allowed_citation_ids(case_file):
    """A rejection must mean the model ignored an enumerated constraint, not
    that it was never told what the valid ids were."""
    _system, user = build_prompt(case_file)
    for valid in case_file.valid_citation_ids():
        assert valid in user


def test_prompt_contains_no_fact_absent_from_the_case_file(case_file):
    """The prompt is rendered from the case file alone -- if a fact is not
    citable it must not be suggestible either."""
    _system, user = build_prompt(case_file)
    assert "TXN-99999999" not in user
    assert user.count("0011:AAA") >= 1


# --- the client's failure surface -------------------------------------------

class _Response:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _ok_payload(text="hello"):
    return {"choices": [{"message": {"content": text}}],
            "model": "test/model", "usage": {"total_tokens": 7}}


@pytest.fixture
def keyed(monkeypatch):
    monkeypatch.setattr(llm_client.config, "API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(llm_client.config, "MAX_RETRIES", 2, raising=False)
    return llm_client


def test_client_returns_not_configured_without_a_key(monkeypatch):
    monkeypatch.setattr(llm_client.config, "API_KEY", "", raising=False)
    result = llm_client.complete("s", "u", post=lambda *a: _Response(200))
    assert result.failure == llm_client.NOT_CONFIGURED
    assert result.ok is False


def test_client_does_not_retry_a_4xx(keyed):
    calls = []

    def _post(url, headers, payload, timeout):
        calls.append(1)
        return _Response(404, text="model not found")

    result = keyed.complete("s", "u", post=_post)
    assert result.failure == keyed.HTTP_CLIENT_ERROR
    assert len(calls) == 1, "a 4xx is a config error and must not be retried"


def test_client_retries_a_5xx_then_gives_up(keyed):
    calls = []

    def _post(url, headers, payload, timeout):
        calls.append(1)
        return _Response(503, text="upstream unavailable")

    result = keyed.complete("s", "u", post=_post)
    assert result.failure == keyed.HTTP_SERVER_ERROR
    assert len(calls) == keyed.config.MAX_RETRIES + 1


def test_client_retries_a_transport_error_then_succeeds(keyed):
    calls = []

    def _post(url, headers, payload, timeout):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectTimeout("slow")
        return _Response(200, _ok_payload("drafted"))

    result = keyed.complete("s", "u", post=_post)
    assert result.ok
    assert result.text == "drafted"
    assert result.attempts == 2


def test_client_treats_a_malformed_200_as_failure_not_an_exception(keyed):
    result = keyed.complete("s", "u",
                            post=lambda *a: _Response(200, {"unexpected": 1}))
    assert result.failure == keyed.MALFORMED


def test_client_treats_empty_content_as_failure(keyed):
    result = keyed.complete("s", "u",
                            post=lambda *a: _Response(200, _ok_payload("   ")))
    assert result.failure == keyed.MALFORMED


# --- the ledger -------------------------------------------------------------

def test_rejection_rate_is_none_not_zero_when_nothing_was_drafted():
    """0.0 would read as 'the model never erred'."""
    ledger = metrics.DraftLedger()
    ledger.record(metrics.LLM_UNAVAILABLE)
    ledger.record(metrics.TEMPLATE_FILED)
    assert ledger.attempted == 0
    assert ledger.rejection_rate is None


def test_rejection_rate_excludes_calls_that_never_happened():
    ledger = metrics.DraftLedger()
    ledger.record(metrics.LLM_FILED)
    ledger.record(metrics.LLM_REJECTED_UNCITED)
    ledger.record(metrics.LLM_UNAVAILABLE)
    assert ledger.attempted == 2
    assert ledger.rejection_rate == 0.5


def test_ledger_rejects_an_unknown_outcome():
    with pytest.raises(ValueError):
        metrics.DraftLedger().record("something_else")


def test_ledger_writes_append_only_jsonl(tmp_path):
    import json
    path = tmp_path / "nested" / "drafts.jsonl"
    ledger = metrics.DraftLedger(path=path)
    ledger.record(metrics.LLM_FILED, case_id="CASE-1", model="m")
    ledger.record(metrics.LLM_REJECTED_UNCITED, case_id="CASE-2")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["outcome"] for r in rows] == [metrics.LLM_FILED,
                                            metrics.LLM_REJECTED_UNCITED]
    assert rows[0]["case_id"] == "CASE-1"
