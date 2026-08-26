"""The case: what an analyst actually works, and what later trains a model.

A case is written once, at alert time, and never recomputed. That is the single
most important property in this file. If features were recomputed later, an
account's degree would include edges that did not exist when it was flagged, and
the eventual training set would be contaminated by hindsight -- the classic and
fatal leakage in fraud ML. It is cheap to get right now and impossible to
retrofit.

The verdict taxonomy is deliberately not a thumbs-up. `CONFIRMED_PARTIAL` is the
highest-value label in the system: it yields node-level positives *and*
negatives inside the same subgraph, which is exactly the supervision a node
classifier needs. `BENIGN_EXPLAINED` with a reason code is what eventually
teaches a model the legitimate structures that look like rings, which is where
all the false positives live.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Bumped whenever scoring, features or candidate generation change. Stamped on
# every case so labels stay interpretable after thresholds move -- without it a
# label collected today is uninterpretable against tomorrow's detector.
DETECTOR_VERSION = "v1.0.0-phase2"


class Verdict(str, Enum):
    PENDING = "pending"
    CONFIRMED_RING = "confirmed_ring"
    CONFIRMED_PARTIAL = "confirmed_partial"   # a subset is a ring
    NOT_A_RING = "not_a_ring"
    BENIGN_EXPLAINED = "benign_explained"     # real structure, legitimate cause
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

    @property
    def is_positive(self) -> bool:
        return self in (Verdict.CONFIRMED_RING, Verdict.CONFIRMED_PARTIAL)

    @property
    def is_resolved(self) -> bool:
        return self is not Verdict.PENDING


# Fixed vocabulary. Free text is kept alongside, but the coded reason is what
# makes dispositions aggregatable and is what the consistency check compares.
REASONS = {
    Verdict.CONFIRMED_RING: ["layering", "mule_network", "structuring",
                             "circular_flow", "bust_out"],
    Verdict.CONFIRMED_PARTIAL: ["subset_confirmed", "boundary_unclear"],
    Verdict.NOT_A_RING: ["coincidental_structure", "single_actor",
                         "insufficient_linkage"],
    Verdict.BENIGN_EXPLAINED: ["shared_corporate_owner", "payroll_hub",
                               "marketplace_settlement", "family_accounts",
                               "known_customer"],
    Verdict.INSUFFICIENT_EVIDENCE: ["needs_kyc", "needs_more_time",
                                    "escalated"],
}


class Lane(str, Enum):
    """Which queue a case lands in.

    A tool that presents everything with uniform confidence teaches analysts to
    distrust all of it, so low-confidence findings are separated rather than
    interleaved. CONTROL is the random sample of *unflagged* neighbourhoods:
    without it, labels only ever describe what the detector already finds, the
    next model inherits this one's blind spots, and production recall is not
    estimable at all.
    """

    PRIMARY = "primary"
    LOW_CONFIDENCE = "low_confidence"
    CONTROL = "control"


@dataclass
class Disposition:
    verdict: Verdict = Verdict.PENDING
    reason: str = ""
    note: str = ""
    at: str = ""                       # ISO timestamp of the human decision
    analyst: str = ""
    # Members the analyst kept. Empty means "all of them"; a shorter list is a
    # partial confirmation and is the most informative label available.
    confirmed_members: list[str] = field(default_factory=list)
    dropped_members: list[str] = field(default_factory=list)
    seconds_to_decide: float | None = None

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict.value, "reason": self.reason,
            "note": self.note, "at": self.at, "analyst": self.analyst,
            "confirmed_members": self.confirmed_members,
            "dropped_members": self.dropped_members,
            "seconds_to_decide": self.seconds_to_decide,
        }


@dataclass
class Case:
    """An immutable alert-time record, plus a mutable disposition."""

    id: str
    opened_at: str                     # ISO, simulated clock
    opened_t: int                      # minutes since epoch
    lane: Lane

    members: list[str]                 # account keys, stable and human-readable
    seed: str
    score: float
    contrib: dict
    features: dict                     # point-in-time snapshot, never recomputed
    motifs: dict
    subgraph: list                     # [[src, dst, count, amount], ...]
    detector_version: str = DETECTOR_VERSION

    absorbed: int = 0
    timeline: list = field(default_factory=list)
    narrative: dict = field(default_factory=dict)
    disposition: Disposition = field(default_factory=Disposition)
    # DPDP Act 2023 purpose limitation (sentinel.compliance.purpose): the
    # lawful purpose this case's personal data is being processed for, which
    # bounds both its retention and who may read it. Defaults to the
    # investigation purpose every case is opened for; a case only carries
    # "regulatory_reporting" once an STR is actually being prepared.
    purpose: str = "fraud_investigation"

    # Ground truth, populated only in evaluation. Never shown to a scorer -- it
    # exists so the simulated-analyst experiment can stand in for verdicts.
    truth_rings: list = field(default_factory=list)

    def log(self, at: str, kind: str, text: str) -> None:
        self.timeline.append({"at": at, "kind": kind, "text": text})

    @property
    def size(self) -> int:
        return len(self.members)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "opened_at": self.opened_at, "opened_t": self.opened_t,
            "lane": self.lane.value, "members": self.members, "seed": self.seed,
            "score": self.score, "contrib": self.contrib,
            "features": self.features, "motifs": self.motifs,
            "subgraph": self.subgraph, "detector_version": self.detector_version,
            "absorbed": self.absorbed, "timeline": self.timeline,
            "narrative": self.narrative,
            "disposition": self.disposition.to_dict(),
            "truth_rings": self.truth_rings,
            "purpose": self.purpose,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"))

    @classmethod
    def from_dict(cls, d: dict) -> "Case":
        disp = Disposition(**{**d.get("disposition", {}),
                              "verdict": Verdict(d.get("disposition", {})
                                                 .get("verdict", "pending"))})
        return cls(
            id=d["id"], opened_at=d["opened_at"], opened_t=d["opened_t"],
            lane=Lane(d["lane"]), members=d["members"], seed=d["seed"],
            score=d["score"], contrib=d["contrib"], features=d["features"],
            motifs=d["motifs"], subgraph=d["subgraph"],
            detector_version=d.get("detector_version", "unknown"),
            absorbed=d.get("absorbed", 0), timeline=d.get("timeline", []),
            narrative=d.get("narrative", {}), disposition=disp,
            truth_rings=d.get("truth_rings", []),
            purpose=d.get("purpose", "fraud_investigation"),
        )


def validate_reason(verdict: Verdict, reason: str) -> bool:
    """Reasons are per-verdict; a mismatched pair makes the label unusable."""
    return reason in REASONS.get(verdict, [])
