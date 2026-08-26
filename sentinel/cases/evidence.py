"""Auditable case-file evidence: every claim traced to a transaction id or a
computed feature.

The detector's `WindowedGraph` deliberately aggregates edges per ordered pair
(count, amount, first/last seen -- see `sentinel/graph/window.py`) rather than
storing individual transactions, to keep memory bounded across a 4.5M-edge
stream. That means the case record's own `subgraph` field is pair-aggregated,
not a transaction ledger. So the case *file* -- the auditable artifact built
on top of a case, on demand -- re-reads the compiled stream once, at
report-generation time, to recover the individual transactions behind the
aggregate. This runs only when a case file or narrative is actually
requested, never on the detection hot path.

A transaction id is the row's position in the compiled, immutable, sorted
`data/stream/edges.parquet`: `TXN-{row_index:08d}`. It is stable for a given
build of the compiled stream and is exactly what an FIU-IND request for
additional supporting documents (the `AdditionalDocuments` flow in the
FINnet/FINGate reporting format) would need to locate the underlying record.
"""
from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field

from sentinel.cases.case import Case, DETECTOR_VERSION

# -- provenance --------------------------------------------------------------

STAGE_CANDIDATE_GENERATION = "candidate_generation"
STAGE_SCORING = "scoring"
STAGE_CASE_OPEN = "case_open"
STAGE_EVIDENCE_ASSEMBLY = "evidence_assembly"


@dataclass
class Provenance:
    stage: str
    detector_version: str
    run_id: str
    generated_at: str

    def to_dict(self) -> dict:
        return {"stage": self.stage, "detector_version": self.detector_version,
                "run_id": self.run_id, "generated_at": self.generated_at}


# -- evidence objects ---------------------------------------------------------

ROLE_SOURCE = "SOURCE"
ROLE_SINK = "SINK"
ROLE_PASS_THROUGH = "PASS_THROUGH"
ROLE_ISOLATED = "ISOLATED"


@dataclass
class Transaction:
    txn_id: str
    ts: str                 # ISO timestamp
    src: str                 # account key
    dst: str                 # account key
    amount: float
    currency: str
    channel: str

    def to_dict(self) -> dict:
        return {"txn_id": self.txn_id, "ts": self.ts, "src": self.src,
                "dst": self.dst, "amount": self.amount,
                "currency": self.currency, "channel": self.channel}


@dataclass
class MemberRole:
    account: str
    role: str
    in_degree: int
    out_degree: int
    evidence: list[str] = field(default_factory=list)   # txn ids touching this account

    def to_dict(self) -> dict:
        return {"account": self.account, "role": self.role,
                "in_degree": self.in_degree, "out_degree": self.out_degree,
                "evidence": self.evidence}


@dataclass
class CaseFile:
    case_id: str
    members: list[MemberRole]
    transactions: list[Transaction]
    typology: str
    typology_evidence: list[str]
    feature_snapshot: dict
    provenance: list[Provenance]
    purpose: str = "fraud_investigation"
    retention_until: str | None = None

    def valid_citation_ids(self) -> set[str]:
        """Every id a narrative may cite: the case id, every transaction id,
        and every member account key. Anything else is unverifiable."""
        ids = {self.case_id}
        ids.update(t.txn_id for t in self.transactions)
        ids.update(m.account for m in self.members)
        return ids

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "members": [m.to_dict() for m in self.members],
            "transactions": [t.to_dict() for t in self.transactions],
            "typology": self.typology,
            "typology_evidence": self.typology_evidence,
            "feature_snapshot": self.feature_snapshot,
            "provenance": [p.to_dict() for p in self.provenance],
            "purpose": self.purpose,
            "retention_until": self.retention_until,
        }


# -- role classification -------------------------------------------------

def classify_role(in_degree: int, out_degree: int) -> str:
    """Pass-through (money in *and* out) is the mule signature this whole
    project is built around -- see sentinel/detect/candidates.py. Source and
    sink are the two halves a pass-through account sits between."""
    if in_degree and out_degree:
        return ROLE_PASS_THROUGH
    if out_degree and not in_degree:
        return ROLE_SOURCE
    if in_degree and not out_degree:
        return ROLE_SINK
    return ROLE_ISOLATED


def build_member_roles(members: list[str], transactions: list[Transaction]) -> list[MemberRole]:
    in_deg: dict[str, int] = {m: 0 for m in members}
    out_deg: dict[str, int] = {m: 0 for m in members}
    touching: dict[str, list[str]] = {m: [] for m in members}
    for t in transactions:
        if t.src in out_deg:
            out_deg[t.src] += 1
            touching[t.src].append(t.txn_id)
        if t.dst in in_deg:
            in_deg[t.dst] += 1
            touching[t.dst].append(t.txn_id)
    out = [MemberRole(account=m, role=classify_role(in_deg[m], out_deg[m]),
                       in_degree=in_deg[m], out_degree=out_deg[m],
                       evidence=touching[m])
           for m in members]
    # Pass-through accounts are the load-bearing evidence for a mule-ring
    # verdict, so surface them first.
    out.sort(key=lambda m: (m.role != ROLE_PASS_THROUGH, -m.in_degree - m.out_degree))
    return out


# -- typology evidence ---------------------------------------------------

def typology_evidence_for(features: dict) -> tuple[str, list[str]]:
    """Which typology, and the exact feature values that support it.

    Mirrors `sentinel.api.app.typology_of` so the queue and the case file
    never disagree about what a candidate "is" -- a case file whose typology
    contradicts the console it was opened from is not auditable.
    """
    if features.get("has_temporal_cycle"):
        return "CYCLE", [f"has_temporal_cycle=True",
                         f"shortest_temporal_cycle={features.get('shortest_temporal_cycle')}",
                         f"temporal_cycle_coverage={features.get('temporal_cycle_coverage', 0):.3f}"]
    if (features.get("stack_score") or 0) >= 0.5:
        return "STACK", [f"stack_score={features['stack_score']:.3f}"]
    if (features.get("bipartite_score") or 0) >= 0.5:
        return "BIPARTITE", [f"bipartite_score={features['bipartite_score']:.3f}"]
    if (features.get("scatter_gather_width") or 0) >= 2:
        return "SCATTER-GATHER", [f"scatter_gather_width={features['scatter_gather_width']}"]
    if (features.get("gather_scatter_width") or 0) >= 2:
        return "GATHER-SCATTER", [f"gather_scatter_width={features['gather_scatter_width']}"]
    if (features.get("max_fan") or 0) >= 4:
        return "FAN", [f"max_fan={features['max_fan']}"]
    return "CLUSTER", [f"n_nodes={features.get('n_nodes')}"]


# -- transaction ledger ---------------------------------------------------

def build_transactions(members: list[str], opened_t: int, window_minutes: int,
                        stream) -> list[Transaction]:
    """Recover the individual transactions behind a case's aggregated subgraph.

    `stream` is a `sentinel.stream.replay.Stream`. Bounded to `[opened_t -
    window_minutes, opened_t]` via binary search on the (sorted) timestamp
    column -- the same technique `Stream.ticks` uses -- so this stays fast
    even though the compiled stream holds millions of rows.
    """
    member_set = set(members)
    lo = opened_t - window_minutes
    hi = opened_t
    left = int(np.searchsorted(stream.ts, lo, side="left"))
    right = int(np.searchsorted(stream.ts, hi, side="right"))

    out: list[Transaction] = []
    for i in range(left, right):
        s_key = stream.key(int(stream.src[i]))
        d_key = stream.key(int(stream.dst[i]))
        if s_key in member_set and d_key in member_set:
            out.append(Transaction(
                txn_id=f"TXN-{i:08d}",
                ts=stream.when(int(stream.ts[i])).isoformat(),
                src=s_key, dst=d_key,
                amount=float(stream.amount[i]),
                currency=str(stream.currency[i]),
                channel=str(stream.channel[i]),
            ))
    return out


# -- assembly --------------------------------------------------------------

def build_case_file(case: Case, stream, window_minutes: int, run_id: str,
                     purpose: str = "fraud_investigation",
                     retention_until: str | None = None,
                     now_iso: str | None = None) -> CaseFile:
    """Assemble the full auditable case file for one case.

    Every field traces to either a transaction id (the ledger) or a named,
    valued feature (`feature_snapshot`, taken verbatim from the case's
    point-in-time snapshot -- never recomputed, per `sentinel/cases/case.py`).
    """
    from datetime import datetime, timezone
    generated_at = now_iso or datetime.now(timezone.utc).isoformat()

    transactions = build_transactions(case.members, case.opened_t, window_minutes, stream)
    members = build_member_roles(case.members, transactions)
    typology, typ_evidence = typology_evidence_for(case.features)

    provenance = [
        Provenance(STAGE_CANDIDATE_GENERATION, case.detector_version, run_id, case.opened_at),
        Provenance(STAGE_SCORING, case.detector_version, run_id, case.opened_at),
        Provenance(STAGE_CASE_OPEN, case.detector_version, run_id, case.opened_at),
        Provenance(STAGE_EVIDENCE_ASSEMBLY, DETECTOR_VERSION, run_id, generated_at),
    ]

    return CaseFile(
        case_id=case.id, members=members, transactions=transactions,
        typology=typology, typology_evidence=typ_evidence,
        feature_snapshot=dict(case.features), provenance=provenance,
        purpose=purpose, retention_until=retention_until,
    )
