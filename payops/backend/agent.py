"""The autonomous payment-ops analyst: watch -> detect -> diagnose -> act.

This module owns the incident lifecycle and the one action the agent is allowed
to take on its own (routing). Everything it does is recorded as a timeline entry,
because an autonomous actor in a payments path has to be auditable.
"""
from __future__ import annotations

import asyncio
import itertools
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import config as C
import diagnose
from baseline import BaselineStore, Store
from sim import Outage, Simulator

# What a human rota realistically achieves for a slice-level degradation that
# does not trip a global threshold. Used only to frame the MTTD comparison.
MANUAL_MTTD_MINUTES = 30

SEV_ORDER = {"critical": 0, "serious": 1, "warning": 2}


@dataclass
class Incident:
    id: str
    bank: str
    method: str
    opened_at: datetime
    severity: str
    status: str = "detecting"        # detecting | diagnosing | mitigating | monitoring | resolved
    evidence: dict = field(default_factory=dict)
    narrative: dict = field(default_factory=dict)
    timeline: list = field(default_factory=list)
    resolved_at: datetime | None = None
    detection_latency_min: float | None = None
    mitigation: dict | None = None
    affected: list = field(default_factory=list)
    failures_avoided: int = 0
    peak_drop_pp: float = 0.0

    def log(self, ts: datetime, kind: str, text: str) -> None:
        self.timeline.append({"ts": ts.isoformat(), "kind": kind, "text": text})

    def to_dict(self) -> dict:
        return {
            "id": self.id, "bank": self.bank, "method": self.method,
            "opened_at": self.opened_at.isoformat(), "severity": self.severity,
            "status": self.status, "evidence": self.evidence,
            "narrative": self.narrative, "timeline": self.timeline,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "detection_latency_min": self.detection_latency_min,
            "mitigation": self.mitigation,
            "affected": self.affected,
            "failures_avoided": self.failures_avoided,
            "peak_drop_pp": round(self.peak_drop_pp, 2),
        }


class Agent:
    def __init__(self, start: datetime):
        self.baselines = BaselineStore()
        self.sim = Simulator(start)
        self.baselines.seed(self.sim, start)
        self.store = Store(self.baselines)
        self.incidents: dict[str, Incident] = {}
        self.order: list[str] = []
        self.activity = deque(maxlen=120)
        self.mitigations: dict[str, dict] = {}     # method -> mitigation record
        self.pending_outage_marks: list[dict] = []
        self.tick = 0
        self.session_started = start
        self.total_failures_avoided = 0
        self._counter = itertools.count(1)
        self._tasks: set = set()
        self._pending_actions: list[str] = []

    # -- helpers -------------------------------------------------------------

    @property
    def now(self) -> datetime:
        return self.store.last_ts or self.sim.now

    def note(self, kind: str, text: str) -> None:
        self.activity.appendleft({
            "ts": self.now.isoformat(), "kind": kind, "text": text,
        })

    def open_incident_for(self, bank: str, method: str) -> Incident | None:
        return self.incident_covering(bank, method)

    def incident_covering(self, bank: str, method: str) -> Incident | None:
        slice_id = f"{bank}/{method}"
        for i in self.incidents.values():
            if i.status == "resolved":
                continue
            if slice_id in i.affected or (i.bank == bank and i.method == method):
                return i
        return None

    def _all_clear(self, inc: Incident) -> bool:
        ts = self.now
        for slice_id in inc.affected or [f"{inc.bank}/{inc.method}"]:
            b, m = slice_id.split("/")
            cs = self.store.cell_state(b, m)
            if cs["n"] and cs["z"] <= C.Z_CLEAR:
                return False
        return True

    # -- main loop -----------------------------------------------------------

    async def step(self) -> None:
        self.tick += 1
        rows = self.sim.step()
        self.store.ingest(rows)
        ts = self.now

        opened, cleared = self.store.evaluate(ts)

        for bank, method in opened:
            if self.open_incident_for(bank, method):
                continue
            await self._open(bank, method, ts)

        for bank, method in cleared:
            inc = self.incident_covering(bank, method)
            if inc and self._all_clear(inc):
                self._resolve(inc, ts)

        while self._pending_actions:
            inc = self.incidents.get(self._pending_actions.pop(0))
            if inc and inc.status == "diagnosing":
                self._decide_action(inc, ts)

        # Keep open incidents' evidence fresh, and accrue the value of mitigation.
        for inc in self.incidents.values():
            if inc.status == "resolved":
                continue
            cs = self.store.cell_state(inc.bank, inc.method)
            inc.peak_drop_pp = max(inc.peak_drop_pp, cs.get("drop_pp") or 0.0)
            if self.tick % 5 == 0 and inc.mitigation is None and inc.status != "diagnosing":
                inc.evidence = diagnose.build_evidence(
                    self.store, inc.bank, inc.method, ts)
            if inc.mitigation:
                saved = int(inc.mitigation.get("failures_per_min_at_mitigation", 0))
                inc.failures_avoided += saved
                self.total_failures_avoided += saved

        self._check_canaries(ts)

        # Let narration tasks make progress before the next tick.
        await asyncio.sleep(0)

        if self.tick % 10 == 0:
            live = sum(1 for i in self.incidents.values() if i.status != "resolved")
            self.note("watch",
                      f"Swept {len(C.BANKS) * len(C.METHODS)} slices across "
                      f"{len(C.ALL_PSPS)} rails - "
                      + (f"{live} open incident{'s' if live != 1 else ''}."
                         if live else "all within baseline."))

    # -- incident lifecycle --------------------------------------------------

    async def _open(self, bank: str, method: str, ts: datetime) -> None:
        cs = self.store.cell_state(bank, method)
        ev = diagnose.build_evidence(self.store, bank, method, ts)

        # Alert fatigue is the failure mode of ops tooling. If this slice is
        # degrading for a cause we have already opened -- the same rail, on the
        # same method -- it joins that incident instead of paging again.
        existing = self._correlate(ev)
        if existing:
            slice_id = f"{bank}/{method}"
            if slice_id not in existing.affected:
                existing.affected.append(slice_id)
                existing.log(ts, "correlate",
                             f"{bank} {method} began degrading with the same "
                             f"signature ({ev['primary_rail']}, "
                             f"{ev['dominant_error_code']}). Folded into this "
                             f"incident rather than paging separately - "
                             f"{len(existing.affected)} slices now affected.")
                self.note("correlate",
                          f"{existing.id}: +{bank} {method} (same root cause).")
            return

        sev = self._severity(cs)
        inc = Incident(
            id=f"INC-{next(self._counter):03d}",
            bank=bank, method=method, opened_at=ts, severity=sev,
        )
        inc.affected = [f"{bank}/{method}"]
        inc.peak_drop_pp = cs.get("drop_pp") or 0.0
        inc.log(ts, "detect",
                f"{bank} {method} at {cs['p']*100:.1f}% vs {cs['p0']*100:.1f}% expected "
                f"for {ts:%A} {ts:%H:%M} (z={cs['z']}). Sustained across "
                f"{C.BREACH_WINDOWS} windows.")
        self.incidents[inc.id] = inc
        self.order.insert(0, inc.id)

        # Detection latency, measured against the injection that caused it.
        mark = self._match_outage(bank, method)
        if mark:
            inc.detection_latency_min = round(
                (ts - mark["started_at"]).total_seconds() / 60.0, 1)

        self.note("detect", f"{inc.id} opened - {bank} {method} "
                            f"{cs['drop_pp']:.1f}pp below baseline.")

        inc.status = "diagnosing"
        inc.evidence = ev
        inc.log(ts, "diagnose",
                f"Attribution: {int(inc.evidence['primary_rail_share_of_drop']*100)}% "
                f"of excess failures on {inc.evidence['primary_rail']}; dominant code "
                f"{inc.evidence['dominant_error_code']}. Scope: "
                f"{diagnose.SCOPE_LABEL.get(inc.evidence['scope'])}.")

        self._tasks.add(asyncio.create_task(self._narrate(inc)))

    def _correlate(self, ev: dict) -> Incident | None:
        if not ev.get("primary_rail") or not str(ev.get("scope", "")).startswith("rail"):
            return None
        for i in self.incidents.values():
            if i.status == "resolved":
                continue
            e = i.evidence or {}
            if (e.get("primary_rail") == ev["primary_rail"]
                    and i.method == ev["method"]
                    and str(e.get("scope", "")).startswith("rail")):
                return i
        return None

    async def _narrate(self, inc: Incident) -> None:
        try:
            inc.narrative = await diagnose.narrate(inc.evidence)
            self.note("diagnose", f"{inc.id}: {inc.narrative.get('headline', '')}")
        except Exception as exc:
            inc.narrative = {"headline": f"{inc.bank} {inc.method} degraded",
                             "summary": f"Narration failed: {exc}",
                             "source": "error"}
        finally:
            # Acting is deliberately downstream of writing the diagnosis: the
            # agent explains itself before it changes production routing.
            self._pending_actions.append(inc.id)

    def _severity(self, cs: dict) -> str:
        drop = cs.get("drop_pp") or 0
        if drop >= 12 or (cs.get("z") or 0) <= -12:
            return "critical"
        if drop >= 5:
            return "serious"
        return "warning"

    def _decide_action(self, inc: Incident, ts: datetime) -> None:
        ev = inc.evidence
        alts = ev.get("healthy_alternatives") or []
        if ev.get("reroutable") and alts and inc.severity in ("critical", "serious"):
            self._reroute(inc, ts, ev["primary_rail"], alts)
        elif ev.get("reroutable") and alts:
            inc.status = "monitoring"
            inc.log(ts, "hold",
                    f"Impact below the autonomous-action threshold. Holding traffic "
                    f"on {ev['primary_rail']} and continuing to watch; reroute to "
                    f"{alts[0]['psp']} is staged and one click away.")
        else:
            inc.status = "monitoring"
            inc.log(ts, "hold",
                    "No routing remedy available - the fault is issuer-side, so "
                    "moving traffic between rails would not change the outcome. "
                    "Recommending retry policy and merchant comms instead.")

    def _reroute(self, inc: Incident, ts: datetime, bad_psp: str, alts: list) -> None:
        method = inc.method
        weights = dict(self.sim.routing[method])
        prev = dict(weights)
        # Leave a 3% canary on the degraded rail: it is how we find out, without
        # a human, that the rail has come back.
        freed = weights.get(bad_psp, 0.0) - 0.03
        if freed <= 0:
            return
        weights[bad_psp] = 0.03
        healthy = [a["psp"] for a in alts if a["psp"] in weights]
        if not healthy:
            return
        base = sum(prev[p] for p in healthy) or 1.0
        for p in healthy:
            weights[p] = prev[p] + freed * (prev[p] / base)
        self.sim.set_routing(method, weights)

        cs = self.store.cell_state(inc.bank, inc.method)
        per_min = (cs.get("excess_failures") or 0) / C.WINDOW_MINUTES
        inc.mitigation = {
            "action": "reroute",
            "method": method,
            "moved_off": bad_psp,
            "moved_to": healthy,
            "before": {k: round(v, 3) for k, v in prev.items()},
            "after": {k: round(v, 3) for k, v in self.sim.routing[method].items()},
            "at": ts.isoformat(),
            "canary_pct": 3,
            "failures_per_min_at_mitigation": round(per_min, 1),
        }
        self.mitigations[method] = {
            "psp": bad_psp, "incident": inc.id, "since": ts,
            "prev": prev, "healthy_windows": 0,
        }
        inc.status = "mitigating"
        pct = int(round((prev.get(bad_psp, 0)) * 100))
        inc.log(ts, "act",
                f"Rerouted {method}: {bad_psp} cut from {pct}% to 3% of traffic "
                f"(3% held as a health canary), redistributed to "
                f"{', '.join(healthy)}. Change is reversible and logged.")
        self.note("act", f"{inc.id}: rerouted {method} away from {bad_psp} "
                         f"({pct}% -> 3%).")

    def _check_canaries(self, ts: datetime) -> None:
        """Restore default routing once the degraded rail proves healthy again."""
        for method, m in list(self.mitigations.items()):
            tot, suc, _ = self.store.psp_roll[(method, m["psp"])].agg(5)
            if tot < 40:
                continue
            p = suc / tot
            # Compare against the rail's own blended baseline across issuers.
            exp = []
            for bank in C.BANKS:
                e, _ = self.baselines.expected((bank, method, m["psp"]),
                                               ts.weekday(), ts.hour)
                if e:
                    exp.append(e * C.BANK_MIX[bank])
            p0 = sum(exp) / sum(C.BANK_MIX[b] for b in C.BANKS) if exp else 0
            if p0 and p >= p0 - 0.01:
                m["healthy_windows"] += 1
            else:
                m["healthy_windows"] = 0
            if m["healthy_windows"] >= 4:
                self.sim.set_routing(method, m["prev"])
                inc = self.incidents.get(m["incident"])
                if inc:
                    inc.log(ts, "restore",
                            f"Canary traffic shows {m['psp']} back at "
                            f"{p*100:.1f}% (baseline {p0*100:.1f}%). Original "
                            f"{method} routing restored.")
                self.note("restore", f"{m['psp']} recovered - default {method} "
                                     f"routing restored.")
                del self.mitigations[method]

    def _resolve(self, inc: Incident, ts: datetime) -> None:
        inc.status = "resolved"
        inc.resolved_at = ts
        dur = (ts - inc.opened_at).total_seconds() / 60.0
        inc.log(ts, "resolve",
                f"All {len(inc.affected)} affected slice"
                f"{'s' if len(inc.affected) != 1 else ''} back within baseline for "
                f"{C.CLEAR_WINDOWS} consecutive windows. Open for {dur:.0f} min"
                + (f"; approximately {inc.failures_avoided:,} transactions "
                   f"preserved by the reroute." if inc.failures_avoided else "."))
        self.note("resolve", f"{inc.id} resolved after {dur:.0f} min.")

    # -- outage injection (demo control) -------------------------------------

    def inject(self, scope: str, bank: str, method: str, psp: str | None,
               severity: float, label: str = "") -> dict:
        oid = uuid.uuid4().hex[:8]
        if scope == "psp" and not psp:
            psp = C.PSPS_BY_METHOD[method][0]
        o = Outage(id=oid, scope=scope, bank=bank, method=method,
                   psp=psp if scope == "psp" else None,
                   severity=severity, started_at=self.now, label=label)
        self.sim.inject(o)
        self.pending_outage_marks.append({
            "bank": bank, "method": method, "started_at": self.now, "id": oid,
        })
        self.note("inject",
                  f"[demo] Fault injected: {scope} degradation on {bank} {method}"
                  + (f" via {psp}" if psp else "")
                  + f", {int(severity*100)}% severity.")
        return {"id": oid}

    def _match_outage(self, bank: str, method: str) -> dict | None:
        for m in reversed(self.pending_outage_marks):
            if m["bank"] == bank and m["method"] == method:
                return m
        return None

    def clear_outages(self) -> None:
        self.sim.clear_outages()
        self.pending_outage_marks.clear()
        self.note("inject", "[demo] All injected faults cleared.")

    # -- snapshot for the UI -------------------------------------------------

    def snapshot(self) -> dict:
        ts = self.now
        grid = [self.store.cell_state(b, m) for b in C.BANKS for m in C.METHODS]
        tot, suc, errs = self.store.overall.agg(C.WINDOW_MINUTES)
        overall_p = suc / tot if tot else 0.0
        exp_parts, weight = 0.0, 0.0
        for b in C.BANKS:
            for m in C.METHODS:
                w = C.BANK_MIX[b] * C.METHOD_MIX[m]
                e, _ = self.baselines.expected((b, m), ts.weekday(), ts.hour)
                exp_parts += e * w
                weight += w
        overall_p0 = exp_parts / weight if weight else 0.0

        live = [self.incidents[i] for i in self.order
                if self.incidents[i].status != "resolved"]
        live.sort(key=lambda i: (SEV_ORDER.get(i.severity, 9), i.opened_at))
        incident_slices = {}
        for i in live:
            for sl in (i.affected or [f"{i.bank}/{i.method}"]):
                incident_slices[sl] = {"id": i.id, "severity": i.severity,
                                       "status": i.status}
        actions = sum(1 for i in self.incidents.values() if i.mitigation)

        detections = [i.detection_latency_min for i in self.incidents.values()
                      if i.detection_latency_min is not None]
        mttd = round(sum(detections) / len(detections), 1) if detections else None

        return {
            "sim_time": ts.isoformat(),
            "tick": self.tick,
            "kpis": {
                "success_rate": round(overall_p * 100, 2),
                "expected_rate": round(overall_p0 * 100, 2),
                "tpm": int(tot / C.WINDOW_MINUTES),
                "open_incidents": len(live),
                "mttd_minutes": mttd,
                "manual_mttd_minutes": MANUAL_MTTD_MINUTES,
                "failures_avoided": self.total_failures_avoided,
                "slices_watched": len(C.BANKS) * len(C.METHODS),
                "autonomous_actions": actions,
            },
            "incident_slices": incident_slices,
            "grid": grid,
            "banks": C.BANKS,
            "methods": C.METHODS,
            "incidents": [i.to_dict() for i in
                          [self.incidents[x] for x in self.order][:12]],
            "activity": list(self.activity)[:40],
            "routing": self.sim.routing,
            "default_routing": C.DEFAULT_ROUTING,
            "overall_spark": self.store.overall.series(C.SPARK_POINTS),
            "psps_by_method": C.PSPS_BY_METHOD,
        }
