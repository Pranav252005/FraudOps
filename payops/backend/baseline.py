"""Baseline learning and deviation detection.

The core claim of the product lives in this file: we do not alert on a fixed
threshold, we alert when a slice departs from *its own* expected behaviour for
this hour of this weekday, by more than its own natural variation.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from datetime import datetime, timedelta

import numpy as np

import config as C


class BaselineStore:
    """EWMA of success rate per slice, keyed by (weekday, hour).

    Also tracks the EWMA of squared residuals, so each slice carries its own
    idea of "how much does this normally wobble". A slice that is naturally
    noisy earns a wider tolerance instead of paging someone every evening.
    """

    def __init__(self, alpha: float = 0.15):
        self.alpha = alpha
        self.mean: dict[tuple, float] = {}
        self.var: dict[tuple, float] = {}
        self.count: dict[tuple, int] = defaultdict(int)

    def update(self, key: tuple, weekday: int, hour: int, p: float) -> None:
        k = (key, weekday, hour)
        if k not in self.mean:
            self.mean[k] = p
            self.var[k] = 0.0004
        else:
            a = self.alpha
            resid = p - self.mean[k]
            self.mean[k] += a * resid
            self.var[k] = (1 - a) * self.var[k] + a * resid * resid
        self.count[k] += 1

    def _neighbours(self, key: tuple, weekday: int, hour: int):
        for wd, hr in ((weekday, hour), (weekday, (hour - 1) % 24),
                       (weekday, (hour + 1) % 24)):
            k = (key, wd, hr)
            if k in self.mean:
                yield self.mean[k], self.var[k]

    def expected(self, key: tuple, weekday: int, hour: int) -> tuple[float, float]:
        """Return (expected success rate, baseline standard deviation)."""
        vals = list(self._neighbours(key, weekday, hour))
        if not vals:
            return 0.0, 0.0
        m = vals[0][0]
        sd = math.sqrt(max(1e-8, np.mean([v for _, v in vals])))
        return m, sd

    def is_warm(self, key: tuple, weekday: int, hour: int) -> bool:
        return self.count[(key, weekday, hour)] >= 3

    def seed(self, sim, start: datetime, days: int = C.HISTORY_DAYS) -> None:
        """Backfill history so the agent boots with a learned baseline.

        Done at hour granularity -- statistically equivalent for the EWMA and
        fast enough to run at startup without a visible pause.
        """
        rng = np.random.default_rng(11)
        t = start - timedelta(days=days)
        while t < start:
            for method in C.METHODS:
                for bank in C.BANKS:
                    base_p = (C.BASE_SUCCESS[method][bank]
                              * C.hour_health(method, t.hour))
                    cell_ps = []
                    for psp in C.PSPS_BY_METHOD[method]:
                        p = base_p * C.PSP_HEALTH.get(psp, 1.0)
                        p = float(np.clip(rng.normal(p, 0.006), 0.05, 0.999))
                        self.update((bank, method, psp), t.weekday(), t.hour, p)
                        cell_ps.append(p * C.DEFAULT_ROUTING[method][psp])
                    self.update((bank, method), t.weekday(), t.hour, sum(cell_ps))
            t += timedelta(hours=1)


class Window:
    """Rolling per-minute aggregates for one slice."""

    def __init__(self, maxlen: int = 240):
        self.rows = deque(maxlen=maxlen)

    def add(self, ts, total, success, errors):
        self.rows.append((ts, total, success, errors))

    def tail(self, minutes: int):
        return list(self.rows)[-minutes:]

    def agg(self, minutes: int):
        tot = suc = 0
        errs: dict[str, int] = defaultdict(int)
        for _, t, s, e in self.tail(minutes):
            tot += t
            suc += s
            for k, v in e.items():
                errs[k] += v
        return tot, suc, dict(errs)

    def series(self, points: int) -> list[float]:
        out = []
        for _, t, s, _ in self.tail(points):
            out.append(round(s / t, 4) if t else None)
        return out


class Store:
    """All rolling state, plus the detector."""

    def __init__(self, baselines: BaselineStore):
        self.baselines = baselines
        self.cells: dict[tuple, Window] = defaultdict(Window)      # (bank, method)
        self.rails: dict[tuple, Window] = defaultdict(Window)      # (bank, method, psp)
        self.psp_roll: dict[tuple, Window] = defaultdict(Window)   # (method, psp)
        self.overall = Window()
        self.breach: dict[tuple, int] = defaultdict(int)
        self.clear: dict[tuple, int] = defaultdict(int)
        self.last_ts: datetime | None = None

    def ingest(self, rows) -> None:
        if not rows:
            return
        self.last_ts = rows[0].ts
        cell_acc: dict[tuple, list] = defaultdict(lambda: [0, 0, defaultdict(int)])
        psp_acc: dict[tuple, list] = defaultdict(lambda: [0, 0, defaultdict(int)])
        g_tot = g_suc = 0
        g_err: dict[str, int] = defaultdict(int)
        for r in rows:
            self.rails[(r.bank, r.method, r.psp)].add(r.ts, r.total, r.success, r.errors)
            c = cell_acc[(r.bank, r.method)]
            c[0] += r.total; c[1] += r.success
            p = psp_acc[(r.method, r.psp)]
            p[0] += r.total; p[1] += r.success
            for k, v in r.errors.items():
                c[2][k] += v; p[2][k] += v; g_err[k] += v
            g_tot += r.total; g_suc += r.success
        for key, (t, s, e) in cell_acc.items():
            self.cells[key].add(self.last_ts, t, s, dict(e))
        for key, (t, s, e) in psp_acc.items():
            self.psp_roll[key].add(self.last_ts, t, s, dict(e))
        self.overall.add(self.last_ts, g_tot, g_suc, dict(g_err))
        # Learn continuously -- but only from windows we did not flag, so an
        # outage never gets absorbed into "normal".
        self._learn()

    def _learn(self) -> None:
        ts = self.last_ts
        if ts is None or ts.minute % 10 != 0:
            return
        for key, win in list(self.cells.items()) + list(self.rails.items()):
            tot, suc, _ = win.agg(10)
            if tot < C.MIN_WINDOW_VOLUME:
                continue
            z = self.zscore(key, suc / tot, tot, ts)
            if z is not None and z < -2.5:
                continue
            self.baselines.update(key, ts.weekday(), ts.hour, suc / tot)

    # -- detection -----------------------------------------------------------

    def zscore(self, key: tuple, p_obs: float, n: int, ts: datetime) -> float | None:
        p0, sd_base = self.baselines.expected(key, ts.weekday(), ts.hour)
        if p0 <= 0 or n < 5:
            return None
        sampling = math.sqrt(max(1e-9, p0 * (1 - p0) / n))
        sigma = math.sqrt(sampling ** 2 + sd_base ** 2)
        return (p_obs - p0) / max(sigma, 1e-6)

    def cell_state(self, bank: str, method: str) -> dict:
        key = (bank, method)
        win = self.cells[key]
        ts = self.last_ts
        tot, suc, errs = win.agg(C.WINDOW_MINUTES)
        if ts is None or tot == 0:
            return {"bank": bank, "method": method, "z": 0.0, "p": None,
                    "p0": None, "n": 0, "spark": [], "status": "idle"}
        p = suc / tot
        p0, _ = self.baselines.expected(key, ts.weekday(), ts.hour)
        z = self.zscore(key, p, tot, ts) or 0.0
        if tot < C.MIN_WINDOW_VOLUME:
            z = 0.0
        return {
            "bank": bank, "method": method,
            "p": round(p, 4), "p0": round(p0, 4),
            "z": round(z, 2), "n": tot,
            "drop_pp": round((p0 - p) * 100, 2),
            "excess_failures": int(max(0.0, (p0 - p)) * tot),
            "spark": win.series(C.SPARK_POINTS),
            "top_error": max(errs, key=errs.get) if errs else None,
        }

    def evaluate(self, ts: datetime) -> tuple[list[tuple], list[tuple]]:
        """Return (cells whose breach just became sustained, cells that cleared)."""
        opened, cleared = [], []
        for bank in C.BANKS:
            for method in C.METHODS:
                key = (bank, method)
                tot, suc, _ = self.cells[key].agg(C.WINDOW_MINUTES)
                if tot < C.MIN_WINDOW_VOLUME:
                    continue
                p = suc / tot
                p0, _ = self.baselines.expected(key, ts.weekday(), ts.hour)
                z = self.zscore(key, p, tot, ts)
                if z is None:
                    continue
                breaching = z <= C.Z_ALERT and (p0 - p) >= C.MIN_ABS_DROP
                if breaching:
                    self.clear[key] = 0
                    self.breach[key] += 1
                    if self.breach[key] == C.BREACH_WINDOWS:
                        opened.append(key)
                else:
                    self.breach[key] = 0
                    if z >= C.Z_CLEAR:
                        self.clear[key] += 1
                        if self.clear[key] == C.CLEAR_WINDOWS:
                            cleared.append(key)
                    else:
                        self.clear[key] = 0
        return opened, cleared
