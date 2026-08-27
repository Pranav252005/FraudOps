"""Tests for STR narrative generation and, especially, the citation verifier.

The verifier is the load-bearing check the task calls out explicitly: it must
reject a fabricated transaction/account id, and it must reject a fact-shaped
claim with no citation at all. Both are tested directly against hand-built
narratives, not just against the template generator, because a future
LLM-drafted narrative is exactly the case this exists to catch.
"""
from __future__ import annotations

from sentinel.cases.evidence import (REG_PMLA_MOR_2005, CaseFile, MemberRole,
                                     Provenance, ROLE_PASS_THROUGH, ROLE_SINK,
                                     ROLE_SOURCE, Transaction)
from sentinel.narrative.citation import NarrativeVerificationError, verify
from sentinel.narrative.str_narrative import generate, generate_and_verify


def make_case_file():
    txns = [
        Transaction("TXN-00000001", "2024-01-01T00:01:00+00:00", "1:A", "1:B",
                    500.0, "USD", "wire"),
        Transaction("TXN-00000002", "2024-01-01T00:05:00+00:00", "1:B", "1:C",
                    480.0, "USD", "wire"),
    ]
    members = [
        MemberRole("1:A", ROLE_SOURCE, 0, 1, ["TXN-00000001"]),
        MemberRole("1:B", ROLE_PASS_THROUGH, 1, 1, ["TXN-00000001", "TXN-00000002"]),
        MemberRole("1:C", ROLE_SINK, 1, 0, ["TXN-00000002"]),
    ]
    return CaseFile(
        case_id="CASE-00042", members=members, transactions=txns,
        typology="CYCLE", typology_evidence=["shortest_temporal_cycle=3"],
        feature_snapshot={"n_nodes": 3},
        provenance=[Provenance("case_open", "v1.0.0-phase2", "run-1",
                               "2024-01-01T00:10:00+00:00")],
        purpose="fraud_investigation",
    )


class TestCitationVerifier:
    def test_accepts_a_fully_cited_narrative(self):
        text = "WHAT: 1 transaction moved from account 1:A to 1:B [TXN-00000001]."
        result = verify(text, {"TXN-00000001", "1:A", "1:B"})
        assert result.ok
        assert not result.failures

    def test_rejects_a_fabricated_transaction_id(self):
        text = "WHAT: 1 transaction moved USD 500.00 [TXN-99999999]."
        result = verify(text, {"TXN-00000001"})
        assert not result.ok
        assert "TXN-99999999" in result.unverifiable_citations

    def test_rejects_a_fabricated_account_id(self):
        text = "WHO: account 9:ZZZZ sent funds [9:ZZZZ]."
        result = verify(text, {"1:A"})
        assert not result.ok
        assert "9:ZZZZ" in result.unverifiable_citations

    def test_rejects_a_fact_shaped_claim_with_no_citation(self):
        text = "On 2024-01-01, USD 500.00 moved from account 1:A to account 1:B."
        result = verify(text, {"1:A", "1:B"})
        assert not result.ok
        assert result.uncited_sentences

    def test_accepts_scene_setting_prose_with_no_citation(self):
        text = "This report is filed to summarise suspicious activity observed."
        result = verify(text, set())
        assert result.ok

    def test_multiple_sentences_each_checked_independently(self):
        text = ("This report summarises suspicious activity. "
                "Account 1:A sent funds to 1:B [TXN-00000001]. "
                "Account 1:A also sent funds to 1:Z [TXN-FAKE].")
        result = verify(text, {"1:A", "1:B", "TXN-00000001"})
        assert not result.ok
        assert "TXN-FAKE" in result.unverifiable_citations
        assert len(result.uncited_sentences) == 0  # both fact sentences had a citation token

    def test_empty_narrative_is_trivially_ok(self):
        result = verify("", {"1:A"})
        assert result.ok

    def test_rejects_an_invented_statute(self):
        """A claim about the law must cite a real instrument from the closed
        regulatory set, exactly as a claim about evidence must cite a real
        transaction. An invented Act is a hallucinated fact like any other."""
        cf = make_case_file()
        text = ("The filing clock is 30 days [FAKE-BANKING-ACT-1999].")
        result = verify(text, cf.valid_citation_ids())
        assert not result.ok
        assert "FAKE-BANKING-ACT-1999" in result.unverifiable_citations

    def test_accepts_a_known_regulatory_citation(self):
        cf = make_case_file()
        text = f"The filing clock is seven working days [{REG_PMLA_MOR_2005}]."
        result = verify(text, cf.valid_citation_ids())
        assert result.ok


class TestGenerate:
    def test_generated_narrative_passes_its_own_verifier(self):
        cf = make_case_file()
        narrative, result = generate_and_verify(cf)
        assert result.ok
        assert not result.failures

    def test_narrative_contains_the_five_ws_and_how(self):
        cf = make_case_file()
        narrative = generate(cf)
        for marker in ("WHO:", "WHAT:", "WHEN:", "WHERE:", "WHY:", "HOW:"):
            assert marker in narrative

    def test_narrative_cites_every_transaction_at_least_once(self):
        cf = make_case_file()
        narrative = generate(cf)
        for t in cf.transactions:
            assert f"[{t.txn_id}]" in narrative

    def test_narrative_names_the_typology_with_its_evidence(self):
        cf = make_case_file()
        narrative = generate(cf)
        assert "CYCLE" in narrative
        assert "shortest_temporal_cycle=3" in narrative

    def test_verification_error_carries_the_failing_result(self):
        cf = make_case_file()
        # Corrupt the case file's own citation universe so the (unmodified)
        # generated narrative now cites ids the file no longer recognises --
        # simulating what an LLM-drafted narrative with invented ids would do.
        cf.transactions = cf.transactions[:1]
        try:
            generate_and_verify(cf)
            assert False, "expected NarrativeVerificationError"
        except NarrativeVerificationError as e:
            assert e.result.unverifiable_citations

    def test_empty_case_file_still_produces_a_verifiable_narrative(self):
        cf = CaseFile(case_id="CASE-EMPTY", members=[], transactions=[],
                      typology="CLUSTER", typology_evidence=["n_nodes=0"],
                      feature_snapshot={}, provenance=[])
        narrative, result = generate_and_verify(cf)
        assert result.ok
