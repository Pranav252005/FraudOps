"""Synthetic payment traffic with realistic seasonality and injectable outages.

The simulator emits one record per (bank, method, psp) per simulated minute.
It knows nothing about detection -- it just produces the stream an ops team
would actually be staring at, including the failure-code mix, which is what
makes diagnosis non-trivial.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np

import config as C


@dataclass
class Outage:
    """A degradation injected into the world.

    scope='psp'    -> one rail is sick. Rerouting away from it fixes the merchant.
    scope='issuer' -> the bank itself is sick on that method. Rerouting cannot
                      help, and the agent must say so instead of thrashing traffic.
    """
    id: str
    scope: str                 # "psp" | "issuer"
    bank: str
    method: str
    psp: str | None
    severity: float            # multiplicative hit to success probability, 0..1
    started_at: datetime
    ramp_minutes: int = 2
    label: str = ""

    def factor(self, now: datetime, bank: str, method: str, psp: str) -> float:
        if method != self.method:
            return 1.0
        if self.scope == "psp":
            if psp != self.psp:
                return 1.0
            # A PSP fault hits every issuer on that rail, but the bank named in
            # the injection takes the worst of it (its BIN range routes there).
            weight = 1.0 if bank == self.bank else 0.45
        else:
            if bank != self.bank:
                return 1.0
            weight = 1.0
        elapsed = (now - self.started_at).total_seconds() / 60.0
        if elapsed < 0:
            return 1.0
        ramp = min(1.0, elapsed / max(1, self.ramp_minutes))
        return 1.0 - (self.severity * weight * ramp)


@dataclass
class MinuteRow:
    ts: datetime
    bank: str
    method: str
    psp: str
    total: int
    success: int
    errors: dict[str, int] = field(default_factory=dict)


class Simulator:
    def __init__(self, start: datetime, seed: int = 7):
        self.rng = np.random.default_rng(seed)
        self.pyrng = random.Random(seed)
        self.now = start
        self.routing = {m: dict(w) for m, w in C.DEFAULT_ROUTING.items()}
        self.outages: list[Outage] = []
        self._drift = {
            (b, m): self.rng.normal(0, 0.004)
            for b in C.BANKS for m in C.METHODS
        }

    # -- routing -------------------------------------------------------------

    def set_routing(self, method: str, weights: dict[str, float]) -> None:
        total = sum(weights.values()) or 1.0
        self.routing[method] = {k: v / total for k, v in weights.items()}

    def reset_routing(self, method: str) -> None:
        self.routing[method] = dict(C.DEFAULT_ROUTING[method])

    # -- outages -------------------------------------------------------------

    def inject(self, outage: Outage) -> None:
        self.outages.append(outage)

    def clear_outages(self) -> None:
        self.outages.clear()

    def active_outage_ids(self) -> list[str]:
        return [o.id for o in self.outages]

    # -- the stream ----------------------------------------------------------

    def _volume(self, ts: datetime) -> float:
        h = ts.hour
        nxt = (h + 1) % 24
        frac = ts.minute / 60.0
        curve = C.HOUR_VOLUME[h] * (1 - frac) + C.HOUR_VOLUME[nxt] * frac
        return curve * C.WEEKDAY_VOLUME[ts.weekday()]

    def _error_mix(self, method: str, degraded: float, scope: str | None) -> dict[str, float]:
        base = dict(C.NORMAL_ERRORS[method])
        if scope is None or degraded <= 0.01:
            return base
        code = C.OUTAGE_ERROR[method][scope]
        # `degraded` is the share of this slice's failures caused by the fault.
        skew = min(0.92, degraded)
        mix = {k: v * (1 - skew) for k, v in base.items()}
        mix[code] = mix.get(code, 0.0) + skew
        return mix

    def step(self) -> list[MinuteRow]:
        ts = self.now
        rows: list[MinuteRow] = []
        load = self._volume(ts)
        tpm = C.BASE_TPM * load * float(self.rng.normal(1.0, 0.03))

        for method, mshare in C.METHOD_MIX.items():
            weights = self.routing[method]
            for bank, bshare in C.BANK_MIX.items():
                cell_n = tpm * mshare * bshare
                if cell_n < 1:
                    continue
                base_p = (
                    C.BASE_SUCCESS[method][bank]
                    * C.hour_health(method, ts.hour)
                    + self._drift[(bank, method)]
                )
                for psp, w in weights.items():
                    n = int(self.rng.poisson(max(0.0, cell_n * w)))
                    if n <= 0:
                        continue
                    p = base_p * C.PSP_HEALTH.get(psp, 1.0)
                    hit, scope = 1.0, None
                    for o in self.outages:
                        f = o.factor(ts, bank, method, psp)
                        if f < hit:
                            hit, scope = f, o.scope
                    p_final = max(0.02, min(0.999, p * hit))
                    succ = int(self.rng.binomial(n, p_final))
                    fails = n - succ
                    # Share of failures attributable to the fault, used to skew
                    # the error-code mix the way a real outage does.
                    excess = max(0.0, (p - p_final)) * n
                    degraded = (excess / fails) if fails > 0 else 0.0
                    mix = self._error_mix(method, degraded, scope)
                    rows.append(MinuteRow(ts, bank, method, psp, n, succ,
                                          self._split(fails, mix)))
        self.now = ts + timedelta(minutes=C.MINUTES_PER_TICK)
        return rows

    def _split(self, n: int, mix: dict[str, float]) -> dict[str, int]:
        if n <= 0:
            return {}
        codes = list(mix.keys())
        probs = np.array([max(0.0, mix[c]) for c in codes], dtype=float)
        s = probs.sum()
        if s <= 0:
            return {codes[0]: n}
        counts = self.rng.multinomial(n, probs / s)
        return {c: int(v) for c, v in zip(codes, counts) if v > 0}
