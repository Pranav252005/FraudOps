"""Phase E: the identity case file, and the two things it must refuse to say.

The citation contract is inherited from the STR narrative and tested the same
way -- including the negative control, because a verifier that cannot reject
anything is not a verifier.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import fields

import pytest

from sentinel.cases import identity_case as IC
from sentinel.cases.identity_case import (ACTION_MANUAL_REVIEW, ACTION_MONITOR,
                                          ACTION_REQUEST_STEP_UP_KYC,
                                          SharedValue,
                                          build_identity_case_file)
from sentinel.detect import identity_features as IF
from sentinel.eval import identity as ident
from sentinel.generators import synthetic_identity as gen
from sentinel.narrative import identity_brief as brief
from sentinel.narrative.citation import NarrativeVerificationError, verify

SMALL = {"n_apps": 600, **gen.PRIMARY}


@pytest.fixture(scope="module")
def case_files():
    world = gen.generate(seed=0, **SMALL)
    _, candidates, _ = ident.run_identity_funnel(world)
    apps = {a.app_id: a for a in world.applications}
    counts = IF.population_counts(world.applications)
    graph, _ = ident.build_graph(world)
    out = []
    for i, c in enumerate(candidates[:6]):
        f = IF.build(set(c.nodes), graph, apps, counts)
        out.append(build_identity_case_file(
            case_id=f"IDC-{i:04d}", nodes=set(c.nodes), seed=c.seed, apps=apps,
            population_counts=counts, features=f.vector(), run_id="test",
            generated_at="2026-09-01T00:00:00+00:00"))
    return out


class TestTheCitationContract:
    def test_every_narrative_sentence_is_sourced(self, case_files):
        for cf in case_files:
            text, result = brief.case_narrative_verified(cf)
            assert result["ok"], result["failures"]

    def test_the_merchant_brief_is_sourced(self, case_files):
        _, result = brief.merchant_brief_verified(case_files)
        assert result["ok"], result["failures"]

    def test_the_verifier_can_actually_reject(self, case_files):
        """The negative control. A verifier that cannot fail measures nothing.

        `sentinel/narrative/str_narrative.py` holds the same contract for the
        STR path; this asserts the identity path inherits the teeth and not
        just the shape.
        """
        cf = case_files[0]
        bad = "Application APP-99999999 shares 4 attributes [APP-99999999]."
        result = verify(bad, cf.valid_citation_ids())
        assert not result.ok
        assert result.unverifiable_citations

    def test_an_uncited_fact_is_rejected(self, case_files):
        result = verify("7 applications share a device.",
                        case_files[0].valid_citation_ids())
        assert not result.ok
        assert result.uncited_sentences

    def test_statutes_are_not_citable_here(self, case_files):
        """The STR narrative cites the law because it makes claims about it.

        An onboarding review recommends a KYC step and makes no statutory
        claim, so admitting regulatory ids would only create a way to prop up
        an unsupported sentence with an authority that does not support it.
        """
        from sentinel.cases.evidence import REGULATORY_CITATIONS
        assert not (case_files[0].valid_citation_ids() & REGULATORY_CITATIONS)


class TestWhatItRefusesToSay:
    def test_there_is_no_confidence_field_to_fill_in(self):
        """Not omitted by convention -- absent from the type.

        The natural merchant sentence is "confidence 0.85". Nothing here has
        calibrated such a probability, so the number would be invented exactly
        where it does most damage: in front of a decline decision.
        """
        names = {f.name for f in fields(IC.IdentityCaseFile)}
        assert not any(n in names for n in
                       ("confidence", "probability", "score", "risk_score"))

    def test_the_narrative_says_it_is_not_estimating_a_likelihood(self, case_files):
        text, _ = brief.case_narrative_verified(case_files[0])
        assert "does not estimate how likely" in text

    def test_the_merchant_brief_declines_to_quote_one(self, case_files):
        text, _ = brief.merchant_brief_verified(case_files)
        assert "No likelihood is quoted" in text

    def test_no_applicant_is_called_fraudulent(self, case_files):
        """The brief's subject is shared structure, which is what was observed.

        Whether the structure is a ring or a family is what the recommended
        review establishes, and the brief has to survive being read by the
        applicant it is about.
        """
        text, _ = brief.merchant_brief_verified(case_files)
        for claim in ("is fraudulent", "are fraudulent", "is a fraudster",
                      "confirmed fraud"):
            assert claim not in text.lower()

    def test_the_case_file_states_its_own_non_causality(self, case_files):
        text, _ = brief.case_narrative_verified(case_files[0])
        assert "after the one under review" in text


class TestSharedInfrastructure:
    def test_a_hub_value_is_not_evidence_about_an_applicant(self):
        """An office IP joins hundreds of unrelated people."""
        hub = SharedValue("LNK-IP-0001", "ip", ["APP-1", "APP-2"], 200)
        rare = SharedValue("LNK-DEVICE-0002", "device", ["APP-1", "APP-2"], 2)
        assert hub.is_shared_infrastructure
        assert not rare.is_shared_infrastructure

    def test_the_threshold_is_the_one_phase_a_measured_with(self):
        """So "rare" means the same thing in the case file and in the kill
        rule's `rare_multiplicity` baseline."""
        from scripts.eval_identity_background import RARE_MAX_MULTIPLICITY
        assert IC.RARE_MULTIPLICITY == RARE_MAX_MULTIPLICITY

    def test_a_group_linked_only_by_infrastructure_is_not_escalated(self):
        links = [SharedValue("LNK-IP-0001", "ip", ["APP-1", "APP-2"], 200),
                 SharedValue("LNK-ADDRESS-0002", "address",
                             ["APP-1", "APP-2"], 60)]
        assert IC.recommend(links, []) == ACTION_MONITOR

    def test_escalation_needs_several_rare_links_across_attributes(self):
        one = [SharedValue("LNK-DEVICE-0001", "device", ["APP-1", "APP-2"], 2)]
        assert IC.recommend(one, []) == ACTION_MANUAL_REVIEW

        many = [SharedValue(f"LNK-DEVICE-{i}", "device", ["APP-1", "APP-2"], 2)
                for i in range(3)]
        assert IC.recommend(many, []) == ACTION_MANUAL_REVIEW, (
            "three links on ONE attribute is a household, not a rotation")

        mixed = many[:2] + [SharedValue("LNK-PAN-9", "pan",
                                         ["APP-1", "APP-3"], 2)]
        assert IC.recommend(mixed, []) == ACTION_REQUEST_STEP_UP_KYC


class TestTheNumbersAreCounted:
    def test_the_brief_moves_when_the_queue_does(self, case_files):
        """Nothing in the brief is a literal, and there is no field to inject
        one through."""
        one, _ = brief.merchant_brief_verified(case_files[:1])
        many, _ = brief.merchant_brief_verified(case_files)
        assert one != many
        assert f"{len(case_files)} group(s)" in many

    def test_an_empty_queue_says_so_rather_than_inventing(self):
        assert "no application groups" in brief.merchant_brief([])


class TestNoTruthInTheCaseFile:
    def test_building_one_needs_only_observables(self, case_files):
        import inspect
        params = list(inspect.signature(build_identity_case_file).parameters)
        assert "world" not in params and "clusters" not in params
        assert "apps" in params and "population_counts" in params

    def test_the_recommendation_is_derived_from_links_only(self):
        import inspect
        assert list(inspect.signature(IC.recommend).parameters) == [
            "links", "applications"]
