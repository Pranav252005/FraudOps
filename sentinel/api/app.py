"""The console API: a ranked queue, a case file, and a disposition.

Deliberately small. The console exists to make one loop fast — read a case,
check the evidence, decide — and every endpoint here serves that loop.

Two decisions carried over from the design work:

  * The queue is **capacity-ranked, not threshold-gated**. A fixed score cut
    produces a flood or a drought as the world drifts; an ops team has a fixed
    number of reviews per day, so the queue is filled with the best available
    candidates and is stable by construction.
  * Disposition must cost seconds. If it costs a form, the label loop dies —
    and the label loop is the long-term product.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from sentinel.cases.case import REASONS, Lane, Verdict
from sentinel.cases.evidence import build_case_file
from sentinel.cases.recommendation_store import RecommendationStore
from sentinel.cases.store import CaseStore
from sentinel.compliance.purpose import ACCESS_SCOPES, Purpose, retention_until
from sentinel.config import WINDOW_MINUTES
from sentinel.escalation import ACTION_DESCRIPTIONS, Action, decide, execute, recommend
from sentinel.narrative.citation import NarrativeVerificationError
from sentinel.narrative.str_narrative import generate_and_verify

ROOT = Path(__file__).resolve().parent.parent.parent
FRONTEND = ROOT / "frontend"
# The console works the *pending* queue built by scripts/build_queue.py. The
# phase 4 corpus in data/cases is already disposed and is training data, not a
# work queue.
CASES = Path(os.environ.get("SENTINEL_CASES", ROOT / "data" / "queue"))
RECOMMENDATIONS = Path(os.environ.get("SENTINEL_RECOMMENDATIONS",
                                       ROOT / "data" / "recommendations"))

app = FastAPI(title="Sentinel — ring investigation console")
store = CaseStore(CASES).load()
rec_store = RecommendationStore(RECOMMENDATIONS).load()
_run_id = "console-session"


def _stream():
    """Lazy import: the case-file/STR endpoints are the only ones that need
    the full compiled stream, and importing it at module load would make the
    whole console fail to start without the licensed AMLworld data present."""
    from sentinel.stream.replay import Stream
    return Stream(ROOT / "data" / "stream")


def summarise(case) -> dict:
    """The row an analyst scans in the queue."""
    f = case.features
    return {
        "id": case.id,
        "opened_at": case.opened_at,
        "lane": case.lane.value,
        "score": case.score,
        "size": case.size,
        "n_banks": f.get("n_banks", 0),
        "n_countries": f.get("n_countries", 0),
        "amount": f.get("total_amount", 0.0),
        "typology": typology_of(f),
        "conservation": f.get("conservation", 0.0),
        "has_temporal_cycle": bool(f.get("has_temporal_cycle")),
        "absorbed": case.absorbed,
        "verdict": case.disposition.verdict.value,
        "headline": headline(case),
    }


def typology_of(f: dict) -> str:
    """Name the dominant shape, so the queue reads as structures not scores."""
    if f.get("has_temporal_cycle"):
        return "cycle"
    if (f.get("stack_score") or 0) >= 0.5:
        return "stack"
    if (f.get("bipartite_score") or 0) >= 0.5:
        return "bipartite"
    if (f.get("scatter_gather_width") or 0) >= 2:
        return "scatter-gather"
    if (f.get("gather_scatter_width") or 0) >= 2:
        return "gather-scatter"
    if (f.get("max_fan") or 0) >= 4:
        return "fan"
    return "cluster"


def headline(case) -> str:
    f = case.features
    bits = [f"{case.size} accounts"]
    if f.get("n_banks", 0) > 1:
        bits.append(f"{f['n_banks']} banks")
    if f.get("n_countries", 0) > 1:
        bits.append(f"{f['n_countries']} countries")
    return " · ".join(bits)


def evidence_rows(case) -> list[dict]:
    """Each claim, with the number behind it, ordered by how much it mattered.

    Every row is derived from a feature that is displayed — the narrative may
    not assert anything the evidence object does not contain.
    """
    f = case.features
    rows = []

    def add(name, value, detail="", weight=0.0):
        rows.append({"name": name, "value": value, "detail": detail,
                     "weight": round(weight, 4)})

    c = case.contrib or {}
    if f.get("has_temporal_cycle"):
        add("Temporal cycle",
            f"length {f.get('shortest_temporal_cycle')}",
            f"{f.get('temporal_cycle_coverage', 0):.0%} of members on the loop; "
            f"timestamps allow value to actually travel it",
            c.get("temporal_cycle", 0))
    elif f.get("has_cycle"):
        add("Structural cycle only",
            f"length {f.get('shortest_cycle')}",
            "the timestamps do NOT allow value to travel this loop",
            c.get("cycle", 0))
    if f.get("conservation", 0) > 0:
        add("Value conservation", f"{f['conservation']:.0%}",
            "money entering the cluster closely matches money leaving it",
            c.get("conservation", 0))
    if f.get("fast_passthrough_ratio", 0) > 0:
        add("Fast pass-through", f"{f['fast_passthrough_ratio']:.0%} of members",
            "forwarded 80%+ of what they received within 48 hours",
            c.get("fast_passthrough", 0))
    if f.get("gargaml", 0) > 0:
        add("Smurfing resemblance", f"{f['gargaml']:.2f}",
            f"sender/mule/receiver block density "
            f"({f.get('n_senders',0)}/{f.get('n_mules',0)}/{f.get('n_receivers',0)})",
            c.get("gargaml", 0))
    if f.get("stack_score", 0) > 0:
        add("Stack (3-layer)", f"{f['stack_score']:.2f}", "layered forwarding",
            c.get("stack", 0))
    if f.get("bipartite_score", 0) > 0:
        add("Bipartite (2-layer)", f"{f['bipartite_score']:.2f}",
            "sources feeding sinks directly", c.get("bipartite", 0))
    if f.get("scatter_gather_width", 0) >= 2:
        add("Scatter-gather", f"width {f['scatter_gather_width']}",
            "split across intermediaries then recombined",
            c.get("scatter_gather", 0))
    if f.get("gather_scatter_width", 0) >= 2:
        add("Gather-scatter", f"width {f['gather_scatter_width']}",
            "collected into one account then dispersed",
            c.get("gather_scatter", 0))
    if f.get("n_countries", 0) > 1:
        add("Cross-border", f"{f['n_countries']} countries",
            f"across {f.get('n_banks', 0)} banks", c.get("cross_border", 0))
    if f.get("entity_reuse", 0) > 1.0:
        add("Shared legal owner",
            f"{f['entity_reuse']:.1f} accounts per entity",
            "a fact about ownership, not an inference from behaviour", 0.0)
    if f.get("median_dormancy_h", 0) > 24:
        add("Dormancy before activity",
            f"{f['median_dormancy_h']/24:.1f} days median", "", 0.0)
    if f.get("round_amount_ratio", 0) > 0:
        add("Round amounts", f"{f['round_amount_ratio']:.0%} of transfers", "",
            c.get("round_amounts", 0))

    rows.sort(key=lambda r: -r["weight"])
    return rows


@app.get("/api/queue")
async def queue(lane: str | None = None, limit: int = 50):
    cases = store.pending(Lane(lane) if lane else None)
    return {
        "cases": [summarise(c) for c in cases[:limit]],
        "total_pending": len(cases),
        "lanes": {l.value: len(store.pending(l)) for l in Lane},
    }


@app.get("/api/case/{case_id}")
async def case_detail(case_id: str):
    c = store.get(case_id)
    if c is None:
        raise HTTPException(404, "no such case")

    members = []
    inbound: dict[str, int] = {}
    for s, d, _, _ in c.subgraph:
        inbound[d] = inbound.get(d, 0) + 1
        inbound.setdefault(s, inbound.get(s, 0))
    outbound: dict[str, int] = {}
    for s, d, _, _ in c.subgraph:
        outbound[s] = outbound.get(s, 0) + 1
        outbound.setdefault(d, outbound.get(d, 0))
    for m in c.members:
        i, o = inbound.get(m, 0), outbound.get(m, 0)
        role = "mule" if (i and o) else ("sender" if o else "receiver")
        # Members with no edges inside the case were pulled in by expansion and
        # are the ones an analyst is most likely to drop.
        confidence = 0.9 if (i and o) else (0.6 if (i or o) else 0.3)
        members.append({"key": m, "role": role, "in": i, "out": o,
                        "confidence": confidence})
    members.sort(key=lambda m: -m["confidence"])

    return {
        "case": c.to_dict(),
        "headline": headline(c),
        "typology": typology_of(c.features),
        "evidence": evidence_rows(c),
        "members": members,
        "reasons": {v.value: REASONS.get(v, []) for v in Verdict
                    if v is not Verdict.PENDING},
    }


class VerdictBody(BaseModel):
    verdict: str
    reason: str = ""
    note: str = ""
    dropped: list[str] = []
    seconds: float | None = None


@app.post("/api/case/{case_id}/verdict")
async def dispose(case_id: str, body: VerdictBody):
    c = store.get(case_id)
    if c is None:
        raise HTTPException(404, "no such case")
    try:
        v = Verdict(body.verdict)
    except ValueError:
        raise HTTPException(400, f"unknown verdict {body.verdict!r}")
    kept = [m for m in c.members if m not in set(body.dropped)]
    try:
        store.dispose(case_id, v, reason=body.reason, note=body.note,
                      analyst="console", at=c.opened_at,
                      confirmed_members=kept if v.is_positive else [],
                      dropped_members=body.dropped, seconds=body.seconds)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "verdict": v.value, "remaining": len(store.pending())}


@app.get("/api/stats")
async def stats():
    s = store.stats()
    done = store.labelled()
    times = [c.disposition.seconds_to_decide for c in done
             if c.disposition.seconds_to_decide]
    accounts = sum(c.size for c in done if c.disposition.verdict.is_positive)
    return {
        **s,
        "pending": len(store.pending()),
        # The leverage number: accounts covered per analyst decision.
        "accounts_per_decision": round(accounts / len(done), 2) if done else 0,
        "median_seconds": round(sorted(times)[len(times) // 2], 1) if times else None,
    }


@app.get("/api/case/{case_id}/file")
async def case_file(case_id: str, role: str = "compliance"):
    """The auditable case file: member roles, the transaction ledger, the
    typology and its evidence, and the provenance chain -- every element
    traceable to a transaction id or a named feature value.

    Access is scoped by the case's DPDP purpose tag (sentinel.compliance.
    purpose): a caller outside the scope for this case's purpose is refused,
    which is the access-scoping half of purpose limitation applied as an
    enforced property rather than left in prose.
    """
    c = store.get(case_id)
    if c is None:
        raise HTTPException(404, "no such case")
    try:
        purpose = Purpose(c.purpose)
    except ValueError:
        purpose = Purpose.FRAUD_INVESTIGATION
    if role not in ACCESS_SCOPES.get(purpose, frozenset()):
        raise HTTPException(403, f"role {role!r} is not in scope for purpose "
                                 f"{purpose.value!r}: allowed = "
                                 f"{sorted(ACCESS_SCOPES.get(purpose, []))}")
    try:
        stream = _stream()
    except FileNotFoundError:
        raise HTTPException(503, "compiled stream not built -- "
                                 "run scripts/build_stream.py")
    until = retention_until(purpose, datetime.fromisoformat(c.opened_at))
    cf = build_case_file(c, stream, WINDOW_MINUTES, _run_id,
                         purpose=purpose.value, retention_until=until.isoformat())
    return cf.to_dict()


@app.get("/api/case/{case_id}/str")
async def case_str_narrative(case_id: str, role: str = "compliance"):
    """Generate and verify the STR narrative. A failed citation verification
    is returned as a 422 with the specific failures, never as a narrative
    that looks filed-ready but silently skipped its own check."""
    c = store.get(case_id)
    if c is None:
        raise HTTPException(404, "no such case")
    try:
        purpose = Purpose(c.purpose)
    except ValueError:
        purpose = Purpose.FRAUD_INVESTIGATION
    if role not in ACCESS_SCOPES.get(purpose, frozenset()):
        raise HTTPException(403, f"role {role!r} is not in scope for purpose {purpose.value!r}")
    try:
        stream = _stream()
    except FileNotFoundError:
        raise HTTPException(503, "compiled stream not built -- "
                                 "run scripts/build_stream.py")
    cf = build_case_file(c, stream, WINDOW_MINUTES, _run_id,
                         purpose=Purpose.REGULATORY_REPORTING.value)
    try:
        narrative, result = generate_and_verify(cf)
    except NarrativeVerificationError as e:
        raise HTTPException(422, {"error": "narrative failed citation verification",
                                  **e.result.to_dict()})
    return {"narrative": narrative, "verification": result.to_dict()}


@app.get("/api/actions")
async def actions():
    """Every action this system may recommend. Bounded and enumerated --
    nothing outside this list is ever proposed, and nothing here executes
    without a human decision (see /api/case/{id}/recommend)."""
    return {"actions": [{"action": a.value, "description": ACTION_DESCRIPTIONS[a]}
                        for a in Action]}


class RecommendBody(BaseModel):
    action: str
    evidence_ids: list[str]
    rationale: str


@app.post("/api/case/{case_id}/recommend")
async def case_recommend(case_id: str, body: RecommendBody):
    c = store.get(case_id)
    if c is None:
        raise HTTPException(404, "no such case")
    try:
        action = Action(body.action)
    except ValueError:
        raise HTTPException(400, f"unknown action {body.action!r}")
    try:
        rec = recommend(case_id, action, body.evidence_ids, body.rationale)
    except ValueError as e:
        raise HTTPException(400, str(e))
    rec_id = rec_store.add(rec)
    return {"id": rec_id, **rec.to_dict()}


@app.get("/api/case/{case_id}/recommendations")
async def case_recommendations(case_id: str):
    return {"recommendations": [{"id": i, **r.to_dict()}
                                for i, r in rec_store.for_case(case_id)]}


class DecideBody(BaseModel):
    approved: bool
    by: str
    note: str = ""


@app.post("/api/recommendation/{rec_id}/decide")
async def recommendation_decide(rec_id: str, body: DecideBody):
    """The human gate. No recommendation reaches `executed=True` without a
    call here first, and this endpoint records who decided and when."""
    rec = rec_store.get(rec_id)
    if rec is None:
        raise HTTPException(404, "no such recommendation")
    try:
        decide(rec, approved=body.approved, by=body.by, note=body.note)
    except ValueError as e:
        raise HTTPException(400, str(e))
    rec_store.update(rec_id, "decide")
    return {"id": rec_id, **rec.to_dict()}


@app.post("/api/recommendation/{rec_id}/execute")
async def recommendation_execute(rec_id: str):
    rec = rec_store.get(rec_id)
    if rec is None:
        raise HTTPException(404, "no such recommendation")
    try:
        execute(rec)
    except ValueError as e:
        raise HTTPException(400, str(e))
    rec_store.update(rec_id, "execute")
    return {"id": rec_id, **rec.to_dict()}


@app.get("/app.js")
async def appjs():
    return FileResponse(FRONTEND / "app.js", media_type="application/javascript")


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")
