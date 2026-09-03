"""The verifier's blind spot, demonstrated rather than described.

PRE-REGISTERED at prereg/citation_recall.md, which predicted this before the
suite existed: *"a narrative that cites a real transaction id for a claim that
transaction does not support will PASS verification."*

WHY THIS FILE EXISTS. `tests/test_narrative.py` already proves the verifier
catches the two things it implements -- a citation to an id the case file does
not hold, and a fact-shaped sentence with no citation at all. Those tests pass,
and passing tests about what a check *does* catch say nothing about what it
does not. This project has twice shipped a check that could not fail; the
remaining risk is not a check that cannot fail but a check whose scope is
narrower than the sentence it appears to license.

The verifier answers "is there a citation, and is the id real?" It does NOT
answer "does that id support this claim?" Every ATTRIBUTION test below is
therefore an EXPECTED PASS of the verifier and a demonstrated hole, and each
one asserts `result.ok is True` with a comment naming what a reader would
wrongly conclude from that green tick.

The positive controls at the bottom are not decoration. Without them this file
would be a set of tests that pass because the verifier is broken in some
*other* way, and could not distinguish "the hole is exactly attribution" from
"the verifier does nothing at all".
"""
from __future__ import annotations

from sentinel.cases.evidence import (CaseFile, MemberRole, Provenance,
                                     ROLE_PASS_THROUGH, ROLE_SINK, ROLE_SOURCE,
                                     Transaction)
from sentinel.narrative.citation import verify


def make_case_file():
    """Three accounts, two transactions, deliberately distinguishable.

    The amounts (500 and 480), the directions and the channels all differ, so
    a sentence that swaps them is unambiguously wrong about the world while
    citing an id that genuinely exists.
    """
    txns = [
        Transaction("TXN-00000001", "2024-01-01T00:01:00+00:00", "1:A", "1:B",
                    500.0, "USD", "wire"),
        Transaction("TXN-00000002", "2024-01-01T00:05:00+00:00", "1:B", "1:C",
                    480.0, "USD", "ACH"),
    ]
    members = [
        MemberRole("1:A", ROLE_SOURCE, 0, 1, ["TXN-00000001"]),
        MemberRole("1:B", ROLE_PASS_THROUGH, 1, 1,
                   ["TXN-00000001", "TXN-00000002"]),
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


VALID = make_case_file().valid_citation_ids()


class TestAttributionIsNotChecked:
    """Every test here asserts the verifier PASSES text that is false.

    That is the finding. The pre-registration predicted it; if any of these
    starts failing, the verifier has gained claim-tuple checking and the
    prediction was wrong -- which would be a better outcome and must be
    reported as a reversal, not quietly absorbed.
    """

    def test_a_wrong_amount_cited_to_a_real_transaction_passes(self):
        # TXN-00000001 carries 500.00. The sentence says 5,000,000.00.
        text = ("On 2024-01-01, USD 5000000.00 moved from account 1:A to "
                "account 1:B via wire [TXN-00000001].")
        result = verify(text, VALID)
        # A reader seeing this green would conclude the amount was checked
        # against the ledger. It was not. Only the id's existence was.
        assert result.ok is True
        assert not result.failures

    def test_a_reversed_direction_cited_to_a_real_transaction_passes(self):
        # TXN-00000001 runs 1:A -> 1:B. This asserts the opposite.
        text = ("On 2024-01-01, USD 500.00 moved from account 1:B to "
                "account 1:A via wire [TXN-00000001].")
        assert verify(text, VALID).ok is True

    def test_a_claim_about_one_transaction_cited_to_another_passes(self):
        # The ACH hop is TXN-00000002. This attributes it to TXN-00000001,
        # which is a wire. Both ids are real, so both survive the id check.
        text = ("A transfer of USD 480.00 moved via ACH between the accounts "
                "[TXN-00000001].")
        assert verify(text, VALID).ok is True

    def test_a_fabricated_date_cited_to_a_real_transaction_passes(self):
        # Nothing in this case file happened in 2019.
        text = ("On 2019-06-15, USD 500.00 moved from account 1:A to account "
                "1:B [TXN-00000001].")
        assert verify(text, VALID).ok is True

    def test_a_statutory_claim_propped_up_by_a_transaction_id_passes(self):
        # The case file admits regulatory ids precisely so a claim about the
        # law cites the instrument rather than being propped up by a
        # transaction. Nothing enforces that direction: a transaction id
        # satisfies the check for a sentence about the filing clock.
        text = ("The filing obligation arises within 7 working days of "
                "forming suspicion [TXN-00000001].")
        assert verify(text, VALID).ok is True

    def test_a_role_claim_contradicting_the_case_file_passes(self):
        # 1:C is a SINK with 0 outbound transfers. This calls it a source.
        text = ("Account 1:C acted as source, with 0 inbound and 9 outbound "
                "transfer(s) inside the flagged window [1:C].")
        assert verify(text, VALID).ok is True

    def test_an_invented_typology_passes_when_cited_to_the_case_id(self):
        # The case file's typology is CYCLE.
        text = ("The structure is a bipartite layering pattern spanning 40 "
                "accounts [CASE-00042].")
        assert verify(text, VALID).ok is True


class TestTheHoleIsAttributionAndNotSomethingWiderPositiveControls:
    """Negative controls for the section above.

    Without these, every assertion above would be consistent with "verify()
    returns ok for everything", which is a different and much worse defect.
    These pin that the two implemented checks really do fire on this exact
    fixture and this exact valid-id set.
    """

    def test_an_invented_transaction_id_is_still_caught(self):
        text = ("On 2024-01-01, USD 500.00 moved from account 1:A to account "
                "1:B [TXN-99999999].")
        result = verify(text, VALID)
        assert result.ok is False
        assert "TXN-99999999" in result.unverifiable_citations

    def test_an_invented_account_id_is_still_caught(self):
        text = "Account 9:ZZZZ received USD 500.00 in the window [9:ZZZZ]."
        result = verify(text, VALID)
        assert result.ok is False
        assert "9:ZZZZ" in result.unverifiable_citations

    def test_the_same_false_sentence_with_its_citation_removed_is_caught(self):
        """The sharpest control in the file.

        This is byte-for-byte the wrong-amount sentence from the first test
        above, minus the `[TXN-00000001]`. It is caught. So the citation is
        doing all of the work of making a false claim acceptable, and the
        content of the claim is doing none.
        """
        text = ("On 2024-01-01, USD 5000000.00 moved from account 1:A to "
                "account 1:B via wire.")
        result = verify(text, VALID)
        assert result.ok is False
        assert result.uncited_sentences

    def test_a_real_id_on_a_true_sentence_still_passes(self):
        """And the verifier is not simply rejecting everything either."""
        text = ("On 2024-01-01T00:01:00+00:00, USD 500.00 moved from account "
                "1:A to account 1:B via wire [TXN-00000001].")
        assert verify(text, VALID).ok is True


class TestTheScopeIsRecordedWhereAReaderWillHitIt:
    """The hole must be documented, not only tested.

    A demonstrated limitation that lives only in a test file is a limitation
    nobody reads. This asserts the claim is stated in the verifier's own
    docstring, so the next person to extend it is told the scope before they
    rely on it.
    """

    # The exact sentence, not a loose keyword. An earlier version of this test
    # searched for "does not", which the docstring already contained in an
    # unrelated clause ("...an id that does not exist in the case file..."), so
    # the test passed while the limitation was undocumented. It was a check
    # that could not fail, written INTO the file whose subject is checks that
    # cannot fail, and it is recorded here rather than silently tightened.
    REQUIRED = "does not check that the cited id supports the claim"

    def test_the_verifier_docstring_states_what_it_does_not_check(self):
        from sentinel.narrative import citation
        doc = " ".join((citation.__doc__ or "").split()).lower()
        assert self.REQUIRED in doc, (
            "sentinel/narrative/citation.py's docstring must contain the "
            f"exact phrase {self.REQUIRED!r}. This file demonstrates that the "
            "verifier does not, and a demonstrated hole that is not written "
            "down where a reader will hit it is a hole that gets relied on.")

    def test_the_docstring_check_can_fail(self):
        """Negative control on the control.

        Proves the assertion above discriminates, rather than matching
        something every docstring happens to contain.
        """
        innocuous = ("Check every sentence against an id that does not exist "
                     "in the case file.")
        assert self.REQUIRED not in " ".join(innocuous.split()).lower()
