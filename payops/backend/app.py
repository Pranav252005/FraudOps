"""FastAPI surface: one SSE stream, a few control endpoints, and the console."""
from __future__ import annotations

import asyncio
import json
import os
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

import config as C
import diagnose
from agent import Agent

def _ist():
    """IST, without depending on a system tz database.

    Windows ships no zoneinfo database, so ZoneInfo("Asia/Kolkata") raises
    unless the `tzdata` package happens to be installed. India has no DST and
    has been a fixed UTC+05:30 since 1945, so a fixed offset is exact here.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Asia/Kolkata")
    except Exception:
        return timezone(timedelta(hours=5, minutes=30), "IST")


IST = _ist()
FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Payment Ops Analyst")
agent = Agent(datetime.now(IST).replace(second=0, microsecond=0))
_subscribers: set[asyncio.Queue] = set()


@app.on_event("startup")
async def _boot():
    # Prime a short live window so the console is populated the moment it opens.
    for _ in range(C.WINDOW_MINUTES + 2):
        await agent.step()
    asyncio.create_task(_loop())


async def _loop():
    while True:
        started = asyncio.get_event_loop().time()
        try:
            await agent.step()
            payload = json.dumps(agent.snapshot())
            for q in list(_subscribers):
                if q.qsize() < 3:
                    q.put_nowait(payload)
        except Exception as exc:  # a demo must survive its own bugs
            print("tick error:", exc)
        elapsed = asyncio.get_event_loop().time() - started
        await asyncio.sleep(max(0.05, C.SECONDS_PER_TICK - elapsed))


@app.get("/api/stream")
async def stream():
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)

    async def gen():
        try:
            yield f"data: {json.dumps(agent.snapshot())}\n\n"
            while True:
                data = await q.get()
                yield f"data: {data}\n\n"
        finally:
            _subscribers.discard(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "Connection": "keep-alive",
    })


@app.get("/api/state")
async def state():
    return agent.snapshot()


@app.get("/api/cell/{bank}/{method}")
async def cell(bank: str, method: str):
    if bank not in C.BANKS or method not in C.METHODS:
        raise HTTPException(404, "unknown slice")
    ev = diagnose.build_evidence(agent.store, bank, method, agent.now)
    inc = agent.open_incident_for(bank, method)
    hist = agent.store.cells[(bank, method)]
    return {
        "evidence": ev,
        "scope_label": diagnose.SCOPE_LABEL.get(ev["scope"]),
        "incident": inc.to_dict() if inc else None,
        "series": hist.series(90),
        "state": agent.store.cell_state(bank, method),
    }


class InjectBody(BaseModel):
    scope: str = "psp"
    bank: str = "HDFC"
    method: str = "CARD"
    psp: str | None = None
    severity: float = 0.35


@app.post("/api/inject")
async def inject(body: InjectBody):
    if body.method not in C.METHODS or body.bank not in C.BANKS:
        raise HTTPException(400, "unknown slice")
    if body.scope not in ("psp", "issuer"):
        raise HTTPException(400, "scope must be psp or issuer")
    return agent.inject(body.scope, body.bank, body.method, body.psp,
                        max(0.05, min(0.95, body.severity)))


@app.post("/api/inject/random")
async def inject_random():
    scope = random.choice(["psp", "psp", "issuer"])
    method = random.choice(["UPI", "CARD", "CARD", "NETBANKING"])
    bank = random.choice(C.BANKS)
    psp = random.choice(C.PSPS_BY_METHOD[method]) if scope == "psp" else None
    sev = round(random.uniform(0.25, 0.6), 2)
    return agent.inject(scope, bank, method, psp, sev)


@app.post("/api/clear")
async def clear():
    agent.clear_outages()
    for m in C.METHODS:
        agent.sim.reset_routing(m)
    agent.mitigations.clear()
    return {"ok": True}


class ApproveBody(BaseModel):
    incident_id: str


@app.post("/api/incident/approve")
async def approve(body: ApproveBody):
    inc = agent.incidents.get(body.incident_id)
    if not inc:
        raise HTTPException(404, "no such incident")
    if inc.mitigation:
        return {"ok": True, "already": True}
    alts = (inc.evidence or {}).get("healthy_alternatives") or []
    if not (inc.evidence or {}).get("reroutable") or not alts:
        raise HTTPException(400, "no routing remedy available for this fault")
    agent._reroute(inc, agent.now, inc.evidence["primary_rail"], alts)
    return {"ok": True}


@app.get("/api/config")
async def cfg():
    return {
        "banks": C.BANKS, "methods": C.METHODS,
        "psps_by_method": C.PSPS_BY_METHOD,
        "llm": bool(diagnose.API_KEY), "model": diagnose.MODEL,
    }


@app.get("/app.js")
async def appjs():
    return FileResponse(FRONTEND / "app.js", media_type="application/javascript")


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")
