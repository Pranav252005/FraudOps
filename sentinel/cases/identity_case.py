"""The identity case file: what a reviewer works, and what it may not claim.

The AMLworld case file traces every sentence to a transaction id. There are no
transactions in onboarding data, so the citable unit is different -- an
application, or the shared attribute value that linked two of them -- but the
contract is the same one and is enforced by the same verifier
(`sentinel.narrative.citation`): a sentence that asserts a fact and cites
nothing, or cites an id the case file does not contain, is a hard failure.

**Two things this file deliberately will not produce.**

*No confidence number.* The obvious merchant-facing sentence is "this cluster is
synthetic identity, confidence 0.85". Nothing in this project has calibrated
such a probability for this domain, so the number would be invented at exactly
the point where it does the most damage -- in front of somebody deciding whether
to decline a real applicant. Standing rule 1 forbids it, and the case file has
no field for it. What is offered instead is the observable structure and a coded
recommendation.

*No claim about detection timing.* The identity path is a static full-graph pass
(`prereg/synthetic_identity_generator.md`), so every link shown here may involve
applications that arrived after the one under review. The case file says so, in
the artefact rather than in a design document nobody rereads.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sentinel.cases.evidence import Provenance, STAGE_EVIDENCE_ASSEMBLY
from sentinel.generators.synthetic_identity import ATTRS

DETECTOR_VERSION = "identity-v1.0.0-phaseE"

# What a reviewer is being asked to do. A closed vocabulary, for the reason
# `sentinel/cases/case.py` keeps one: a coded action aggregates and a free-text
# one does not. Ordered from lightest to heaviest.
ACTION_MONITOR = "MONITOR"
ACTION_MANUAL_REVIEW = "MANUAL_REVIEW"
ACTION_REQUEST_STEP_UP_KYC = "REQUEST_STEP_UP_KYC"
ACTIONS = (ACTION_MONITOR, ACTION_MANUAL_REVIEW, ACTION_REQUEST_STEP_UP_KYC)

# Attribute values held by more than this many applications are reported as
# SHARED-INFRASTRUCTURE rather than as a link between the applications. An
# office IP subnet or a landlord's address joins hundreds of unrelated people,
# and presenting that to a reviewer as evidence of a ring is how a queue loses
# its audience. The threshold is the one Phase A's `rare_multiplicity` baseline
# used, so the case file and that measurement mean the same thing by "rare".
RARE_MULTIPLICITY = 5


def application_id(app_id: int) -> str:
    return f"APP-{app_id:08d}"


@dataclass
class ApplicationRecord:
    """One application in the cluster, as the reviewer sees it."""

    app_ref: str
    ts_day: int
    shared_with: int                 # other members it shares any value with
    shared_attributes: list          # which attribute types link it to members

    def to_dict(self) -> dict:
        return {"app_ref": self.app_ref, "ts_day": self.ts_day,
                "shared_with": self.shared_with,
                "shared_attributes": list(self.shared_attributes)}


@dataclass
class SharedValue:
    """One attribute value held by two or more members: the citable link.

    `population_count` is how many applications in the whole queue hold this
    value, and it is what separates "these three share a handset" from "these
    three are among two hundred people in an office".
    """

    link_ref: str
    attribute: str
    members: list
    population_count: int

    @property
    def is_shared_infrastructure(self) -> bool:
        return self.population_count > RARE_MULTIPLICITY

    def to_dict(self) -> dict:
        return {"link_ref": self.link_ref, "attribute": self.attribute,
                "members": list(self.members),
                "population_count": self.population_count,
                "shared_infrastructure": self.is_shared_infrastructure}


@dataclass
class IdentityCaseFile:
    case_id: str
    applications: list
    links: list
    seed_ref: str
    recommendation: str
    feature_snapshot: dict
    provenance: list
    reach_note: str
    purpose: str = "onboarding_fraud_review"

    def valid_citation_ids(self) -> set:
        """Every id a narrative may cite: the case, its applications, its links.

        No regulatory ids. The AMLworld case file cites statutes because an STR
        makes claims about the law; an onboarding review recommends a KYC step
        and makes none, so admitting statute ids here would only create a way
        to prop up an unsupported sentence.
        """
        ids = {self.case_id, self.seed_ref}
        ids.update(a.app_ref for a in self.applications)
        ids.update(l.link_ref for l in self.links)
        return ids

    def to_dict(self) -> dict:
        return {"case_id": self.case_id,
                "applications": [a.to_dict() for a in self.applications],
                "links": [l.to_dict() for l in self.links],
                "seed_ref": self.seed_ref,
                "recommendation": self.recommendation,
                "feature_snapshot": self.feature_snapshot,
                "provenance": [p.to_dict() for p in self.provenance],
                "reach_note": self.reach_note,
                "purpose": self.purpose}


def recommend(links: list, applications: list) -> str:
    """The coded action, from observable structure alone.

    Deliberately a rule over counts rather than a threshold on a score. A score
    threshold would imply a calibration this domain does not have, and would
    put an uncalibrated number in front of a decision about a real applicant.

    The escalation is driven by RARE links only. Sharing an office IP with two
    hundred people is not evidence about an applicant, and a rule that counted
    it would escalate every employee of a large company.
    """
    rare = [l for l in links if not l.is_shared_infrastructure]
    attrs = {l.attribute for l in rare}
    if len(rare) >= 3 and len(attrs) >= 2:
        return ACTION_REQUEST_STEP_UP_KYC
    if rare:
        return ACTION_MANUAL_REVIEW
    return ACTION_MONITOR


def build_identity_case_file(case_id: str, nodes, seed: int, apps: dict,
                              population_counts: dict, features: dict,
                              run_id: str, generated_at: str | None = None
                              ) -> IdentityCaseFile:
    """Assemble the case file for one candidate.

    `apps` is app_id -> Application (the observable record, label-free) and
    `population_counts` is attribute -> Counter over the whole queue. Neither
    carries ground truth, so the case file cannot state one.
    """
    nodes = sorted(nodes)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()

    by_value = defaultdict(list)
    for i in nodes:
        for a in ATTRS:
            by_value[(a, getattr(apps[i], a))].append(i)

    links, shares_of = [], defaultdict(set)
    attrs_of = defaultdict(set)
    n = 0
    for (attribute, value), ids in sorted(by_value.items()):
        if len(ids) < 2:
            continue
        n += 1
        link = SharedValue(link_ref=f"LNK-{attribute.upper()}-{n:04d}",
                            attribute=attribute,
                            members=[application_id(i) for i in ids],
                            population_count=population_counts[attribute][value])
        links.append(link)
        for i in ids:
            shares_of[i] |= set(ids) - {i}
            attrs_of[i].add(attribute)

    applications = [
        ApplicationRecord(app_ref=application_id(i),
                           ts_day=apps[i].ts // 1440,
                           shared_with=len(shares_of[i]),
                           shared_attributes=sorted(attrs_of[i]))
        for i in nodes]

    return IdentityCaseFile(
        case_id=case_id,
        applications=applications,
        links=links,
        seed_ref=application_id(seed),
        recommendation=recommend(links, applications),
        feature_snapshot=dict(features),
        provenance=[Provenance(stage=STAGE_EVIDENCE_ASSEMBLY,
                                detector_version=DETECTOR_VERSION,
                                run_id=run_id, generated_at=generated_at)],
        reach_note=(
            "This case file was assembled from a static pass over the whole "
            "application graph. Links shown may involve applications received "
            "after the one under review, so nothing here is a claim about what "
            "was detectable at the time that application arrived."),
    )
