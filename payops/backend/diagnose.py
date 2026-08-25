"""Diagnosis: attribute a drop to a dimension, then say it in English.

Two stages, deliberately separated:

  1. `build_evidence` -- deterministic contribution analysis. No model involved.
     It answers "which slice explains the drop, and is it the rail or the issuer".
  2. `narrate` -- Claude turns that evidence into the paragraph a human on shift
     would want, plus merchant-facing copy. If no API key is configured it falls
     back to a template, so the demo never depends on the network.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import httpx

import config as C

MODEL = os.environ.get("PAYOPS_MODEL", "claude-sonnet-4-5")
API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()


# --------------------------------------------------------------------------
# Stage 1 -- contribution analysis
# --------------------------------------------------------------------------

def build_evidence(store, bank: str, method: str, ts: datetime) -> dict:
    W = C.WINDOW_MINUTES
    cell = store.cell_state(bank, method)
    p0 = cell["p0"] or 0.0

    rails = []
    total_excess = 0.0
    for psp in C.PSPS_BY_METHOD[method]:
        win = store.rails[(bank, method, psp)]
        tot, suc, errs = win.agg(W)
        if tot == 0:
            continue
        p = suc / tot
        rp0, _ = store.baselines.expected((bank, method, psp), ts.weekday(), ts.hour)
        z = store.zscore((bank, method, psp), p, tot, ts)
        excess = max(0.0, rp0 - p) * tot
        total_excess += excess
        rails.append({
            "psp": psp, "n": tot, "p": round(p, 4), "p0": round(rp0, 4),
            "z": round(z, 2) if z is not None else None,
            "excess_failures": round(excess, 1),
            "top_error": max(errs, key=errs.get) if errs else None,
            "error_mix": _top_mix(errs),
        })
    for r in rails:
        r["share_of_drop"] = round(r["excess_failures"] / total_excess, 3) if total_excess > 0 else 0.0
    rails.sort(key=lambda r: -r["share_of_drop"])

    worst = rails[0] if rails else None

    # Is the same rail sick for other issuers too?
    blast_banks = []
    if worst:
        for other in C.BANKS:
            if other == bank:
                continue
            tot, suc, _ = store.rails[(other, method, worst["psp"])].agg(W)
            if tot < 30:
                continue
            z = store.zscore((other, method, worst["psp"]), suc / tot, tot, ts)
            if z is not None and z <= -3.0:
                blast_banks.append(other)

    # Is this issuer sick on other methods too?
    bank_other_methods = []
    for m in C.METHODS:
        if m == method:
            continue
        cs = store.cell_state(bank, m)
        if cs["n"] and cs["z"] <= -3.0:
            bank_other_methods.append({"method": m, "z": cs["z"]})

    # Healthy alternatives on this method.
    alternatives = []
    for psp in C.PSPS_BY_METHOD[method]:
        if worst and psp == worst["psp"]:
            continue
        tot, suc, _ = store.psp_roll[(method, psp)].agg(W)
        if tot < 30:
            continue
        r = next((x for x in rails if x["psp"] == psp), None)
        alternatives.append({
            "psp": psp,
            "success_rate": round(suc / tot, 4),
            "z": r["z"] if r else None,
            "headroom_tpm": int(tot / W),
        })
    alternatives = [a for a in alternatives if (a["z"] is None or a["z"] > -2.5)]

    scope, reroutable = _classify(method, worst, blast_banks, bank_other_methods, alternatives)

    return {
        "detected_at": ts.isoformat(),
        "bank": bank,
        "method": method,
        "success_rate": cell["p"],
        "expected_rate": cell["p0"],
        "drop_pp": cell["drop_pp"],
        "z": cell["z"],
        "window_minutes": W,
        "volume_in_window": cell["n"],
        "failed_txns_above_normal_per_min": round(cell["excess_failures"] / W, 1),
        "rails": rails,
        "primary_rail": worst["psp"] if worst else None,
        "primary_rail_share_of_drop": worst["share_of_drop"] if worst else 0.0,
        "dominant_error_code": worst["top_error"] if worst else cell["top_error"],
        "same_rail_also_degraded_for": blast_banks,
        "same_issuer_also_degraded_on": bank_other_methods,
        "healthy_alternatives": alternatives,
        "scope": scope,
        "reroutable": reroutable,
    }


def _top_mix(errs: dict[str, int], k: int = 3) -> dict[str, float]:
    tot = sum(errs.values())
    if not tot:
        return {}
    top = sorted(errs.items(), key=lambda x: -x[1])[:k]
    return {c: round(v / tot, 3) for c, v in top}


def _classify(method, worst, blast_banks, other_methods, alternatives):
    """Decide what kind of fault this is -- which decides whether routing helps."""
    if not worst:
        return "unknown", False
    # A method with a single rail has no routing degree of freedom, so a drop
    # there is by definition the issuer or the rail itself, not a routing choice.
    if len(C.PSPS_BY_METHOD[method]) == 1:
        return ("issuer_wide" if other_methods else "issuer_side"), False
    concentrated = worst["share_of_drop"] >= 0.6
    if other_methods and not concentrated:
        return "issuer_wide", False
    if not concentrated:
        return "issuer_side", False
    if blast_banks:
        return "rail_wide", bool(alternatives)
    # One rail, one issuer -- typically that acquirer's handling of that BIN range.
    return "rail_issuer_pair", bool(alternatives)


SCOPE_LABEL = {
    "rail_wide": "PSP/acquirer-side, affecting multiple issuers",
    "rail_issuer_pair": "PSP/acquirer-side, isolated to one issuer's traffic",
    "issuer_wide": "Issuer-side, across multiple payment methods",
    "issuer_side": "Issuer-side on this method",
    "unknown": "Undetermined",
}


# --------------------------------------------------------------------------
# Stage 2 -- narration
# --------------------------------------------------------------------------

SYSTEM = """You are the on-shift payment operations analyst for a large Indian \
payment gateway. You are handed a completed statistical diagnosis of a live \
degradation and you write the incident note the humans will read.

Rules:
- Lead with what is broken and how much it costs, not with methodology.
- Use only the numbers you are given. Never invent a figure, a timestamp, or a \
cause you cannot support from the evidence.
- Distinguish clearly between a rail (PSP/acquirer) problem, which routing can \
work around, and an issuer problem, which it cannot.
- Indian payments vocabulary: issuer, acquirer, PSP, UPI, VPA, 3DS, decline code.
- No hedging filler, no bullet-point padding, no emoji.

Return STRICT JSON with exactly these keys:
  "headline"      : under 90 characters, states the fault and the affected slice.
  "summary"       : 2-4 sentences for the ops channel. Include the size of the \
drop, the share attributable to the primary rail, the dominant decline code, and \
whether routing can mitigate.
  "recommendation": one sentence naming the concrete next action.
  "merchant_note" : 2 sentences a merchant support lead could send unedited. \
Calm, specific, no internal jargon, no blame on a named bank unless the evidence \
is issuer-side.
  "confidence"    : "high" | "medium" | "low"
"""


async def narrate(evidence: dict) -> dict:
    if not API_KEY:
        return _fallback(evidence)
    payload = {
        "model": MODEL,
        "max_tokens": 700,
        "system": SYSTEM,
        "messages": [{
            "role": "user",
            "content": (
                "Diagnosis evidence (JSON):\n"
                + json.dumps(evidence, indent=2)
                + f"\n\nScope classification: {SCOPE_LABEL.get(evidence['scope'])}."
                + "\nWrite the incident note now. JSON only."
            ),
        }],
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
            )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
        out = json.loads(_extract_json(text))
        out["source"] = "claude"
        for k in ("headline", "summary", "recommendation", "merchant_note"):
            out.setdefault(k, _fallback(evidence)[k])
        return out
    except Exception as e:  # network, quota, malformed -- the demo must not stop
        out = _fallback(evidence)
        out["source"] = f"fallback ({type(e).__name__})"
        return out


def _extract_json(text: str) -> str:
    s, e = text.find("{"), text.rfind("}")
    return text[s:e + 1] if s >= 0 and e > s else "{}"


def _fallback(ev: dict) -> dict:
    bank, method = ev["bank"], ev["method"]
    rail = ev.get("primary_rail")
    rail_side = str(ev.get("scope", "")).startswith("rail")
    share = int(round(ev.get("primary_rail_share_of_drop", 0) * 100))
    drop = ev.get("drop_pp", 0)
    code = ev.get("dominant_error_code")
    rate = (ev.get("success_rate") or 0) * 100
    exp = (ev.get("expected_rate") or 0) * 100
    per_min = ev.get("failed_txns_above_normal_per_min", 0)
    alts = ev.get("healthy_alternatives") or []
    also = ev.get("same_rail_also_degraded_for") or []

    if ev.get("reroutable") and alts:
        rec = f"Shift {method} traffic for {bank} off {rail} onto {alts[0]['psp']}."
        mitig = f"Routing can mitigate: {alts[0]['psp']} is healthy."
        attribution = (f"{share}% of the excess failures sit on {rail}"
                       + (f" (also degraded for {', '.join(also)})" if also else "")
                       + f", concentrated in {code} declines. ")
        headline = f"{bank} {method} down {drop:.1f}pp - {rail} degraded"
    else:
        rec = (f"No routing remedy - the fault is issuer-side. Enable smart retries "
               f"for {bank} {method} and notify affected merchants.")
        mitig = ("Rerouting cannot mitigate this: the failures follow the issuer, "
                 "not the rail.")
        attribution = (f"Excess failures are spread across every rail carrying this "
                       f"traffic rather than concentrated on one, and are dominated by "
                       f"{code}. ")
        headline = f"{bank} {method} down {drop:.1f}pp - issuer-side"

    surface = {"UPI": "UPI payments", "CARD": "card payments",
               "NETBANKING": "netbanking payments",
               "WALLET": "wallet payments"}.get(method, method.lower())
    return {
        "headline": headline,
        "summary": (
            f"{bank} {method} is running at {rate:.1f}% against an expected "
            f"{exp:.1f}% for this hour ({drop:.1f}pp below baseline, z={ev.get('z')}), "
            f"about {per_min:.0f} extra failed transactions a minute. "
            + attribution + mitig
        ),
        "recommendation": rec,
        "merchant_note": (
            f"We are currently seeing elevated failures on {surface} routed through "
            f"{bank}, and our systems have already begun mitigating. Other banks and "
            f"payment methods are unaffected, and we will confirm as soon as success "
            f"rates are back to normal."
        ),
        "confidence": "high" if (rail_side and ev.get("primary_rail_share_of_drop", 0) > 0.6)
                      or (not rail_side and ev.get("same_issuer_also_degraded_on"))
                      else "medium",
        "source": "fallback (no ANTHROPIC_API_KEY set)",
    }
