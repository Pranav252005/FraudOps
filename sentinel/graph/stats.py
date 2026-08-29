"""Per-account incremental statistics — the behavioural axis v1 was missing.

Modelled on IBM's Graph Feature Preprocessor, which maintains per-vertex sum,
mean, min, max, variance, skewness and kurtosis for incoming and outgoing
transactions separately, updated in O(1) per edge.

Higher moments are not decoration here. A mule account forwarding value in
deliberately similar amounts just under a reporting threshold produces a
*tight, skewed* outflow distribution. A mean cannot express that; skewness and
kurtosis can. This is the structuring signature, and v1 had no feature capable
of representing it.

Updates use Welford-style central moments so nothing is stored per transaction
and nothing is recomputed on read.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(slots=True)
class Moments:
    """Streaming count/mean/M2/M3/M4 for one direction of one account."""

    n: int = 0
    mean: float = 0.0
    m2: float = 0.0
    m3: float = 0.0
    m4: float = 0.0
    total: float = 0.0
    lo: float = math.inf
    hi: float = -math.inf
    first_t: int = -1
    last_t: int = -1

    def add(self, x: float, t: int) -> None:
        n1 = self.n
        self.n += 1
        n = self.n
        delta = x - self.mean
        dn = delta / n
        dn2 = dn * dn
        term = delta * dn * n1
        self.mean += dn
        self.m4 += (term * dn2 * (n * n - 3 * n + 3)
                    + 6 * dn2 * self.m2 - 4 * dn * self.m3)
        self.m3 += term * dn * (n - 2) - 3 * dn * self.m2
        self.m2 += term
        self.total += x
        if x < self.lo:
            self.lo = x
        if x > self.hi:
            self.hi = x
        if self.first_t < 0 or t < self.first_t:
            self.first_t = t
        if t > self.last_t:
            self.last_t = t

    @property
    def variance(self) -> float:
        return self.m2 / self.n if self.n > 1 else 0.0

    @property
    def std(self) -> float:
        return math.sqrt(max(0.0, self.variance))

    @property
    def skewness(self) -> float:
        """Tight, one-sided amount distributions are a structuring signal."""
        if self.n < 3 or self.m2 <= 0:
            return 0.0
        return math.sqrt(self.n) * self.m3 / (self.m2 ** 1.5)

    @property
    def kurtosis(self) -> float:
        """Excess kurtosis. High values mean amounts cluster on a few sizes."""
        if self.n < 4 or self.m2 <= 0:
            return 0.0
        return self.n * self.m4 / (self.m2 * self.m2) - 3.0

    def to_dict(self) -> dict:
        return {
            "n": self.n, "total": round(self.total, 2),
            "mean": round(self.mean, 2),
            "min": round(self.lo, 2) if self.n else 0.0,
            "max": round(self.hi, 2) if self.n else 0.0,
            "std": round(self.std, 2),
            "skew": round(self.skewness, 4),
            "kurtosis": round(self.kurtosis, 4),
        }


@dataclass(slots=True)
class AccountStats:
    """Both directions for one account, plus derived behavioural measures."""

    inflow: Moments = field(default_factory=Moments)
    outflow: Moments = field(default_factory=Moments)
    # Moments over the transaction TIMESTAMPS themselves, both directions
    # pooled. IBM's Graph Feature Preprocessor computes its vertex-statistic
    # family over amounts *and* timestamps; docs/HANDOFF.md section 4 claimed
    # "essentially at parity" with GFP while this half was absent entirely.
    # `span_minutes` and `burstiness` are related but are not the moment set:
    # a span says how wide the activity is, and only the higher moments say
    # whether it is one burst, two, or a uniform trickle -- which is what
    # separates a mule cycling value from an ordinary business paying weekly.
    #
    # Timestamps are fed in minutes, the same unit the rest of the system uses.
    times: Moments = field(default_factory=Moments)
    # Counterparties are tracked as counts only; the sets live in the graph.
    quiet_before_first: int = 0

    def add_in(self, amount: float, t: int) -> None:
        self.inflow.add(amount, t)
        self.times.add(float(t), t)

    def add_out(self, amount: float, t: int) -> None:
        self.outflow.add(amount, t)
        self.times.add(float(t), t)

    # -- behavioural measures -------------------------------------------------

    @property
    def is_passthrough(self) -> bool:
        return self.inflow.n > 0 and self.outflow.n > 0

    @property
    def passthrough_value_ratio(self) -> float:
        """Share of received value that was forwarded on.

        The core mule signal: money arrives and leaves rather than accumulating.
        Capped at 1.0 so an account paying out more than it took in (its own
        prior balance) does not score above a pure conduit.
        """
        if self.inflow.total <= 0:
            return 0.0
        return min(1.0, self.outflow.total / self.inflow.total)

    @property
    def passthrough_latency(self) -> float:
        """Hours between first inflow and last outflow.

        Negative means value left before it arrived within this window, which is
        ordinary for an account with a prior balance and is not a conduit.
        """
        if not self.is_passthrough:
            return math.inf
        return (self.outflow.last_t - self.inflow.first_t) / 60.0

    @property
    def is_fast_passthrough(self) -> bool:
        """Industry mule rule: most of the inflow forwarded within 48 hours."""
        lat = self.passthrough_latency
        return (self.passthrough_value_ratio >= 0.8
                and 0 <= lat <= 48.0)

    @property
    def dormancy_hours(self) -> float:
        """Largest quiet gap this account had before becoming active.

        A rule keyed on "large inflow soon after opening" misses accounts that
        were deliberately aged before use, which is why dormancy is measured
        rather than account age.
        """
        return self.quiet_before_first / 60.0

    @property
    def active_hours(self) -> float:
        lo = min(t for t in (self.inflow.first_t, self.outflow.first_t) if t >= 0) \
            if (self.inflow.n or self.outflow.n) else 0
        hi = max(self.inflow.last_t, self.outflow.last_t)
        return max(0.0, (hi - lo) / 60.0)

    @property
    def velocity(self) -> float:
        """Transactions per hour across the active span."""
        n = self.inflow.n + self.outflow.n
        h = self.active_hours
        return n / h if h > 0 else float(n)

    @property
    def time_std_hours(self) -> float:
        """Spread of this account's activity in time, in hours."""
        return self.times.std / 60.0

    @property
    def time_skewness(self) -> float:
        """Positive means activity is back-loaded, negative front-loaded."""
        return self.times.skewness

    @property
    def time_kurtosis(self) -> float:
        """High excess kurtosis means activity concentrates in a few bursts."""
        return self.times.kurtosis

    def to_dict(self) -> dict:
        return {
            "in": self.inflow.to_dict(),
            "out": self.outflow.to_dict(),
            "times": self.times.to_dict(),
            "passthrough_ratio": round(self.passthrough_value_ratio, 4),
            "passthrough_latency_h": (
                round(self.passthrough_latency, 2)
                if math.isfinite(self.passthrough_latency) else None),
            "fast_passthrough": self.is_fast_passthrough,
            "dormancy_h": round(self.dormancy_hours, 2),
            "velocity": round(self.velocity, 4),
        }
