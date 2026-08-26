"""Bootstrap confidence intervals over resampled evaluation cycles.

Point estimates on this dataset move a lot: at p@10 = 0.085 a single ring is
worth roughly +/-0.05 of the metric, so a point estimate with no interval is
close to meaningless. Every top-level metric this project reports should carry
one from here on.

The resampling unit is the **cycle** (one generation run), not the individual
candidate. Candidates from the same cycle are not independent draws -- they
come from the same window of active ground-truth rings -- so resampling
candidates directly would understate the true variance. Resampling whole
cycles treats each generation run as one exchangeable observation, which is
the same logic as the standard cluster bootstrap.
"""
from __future__ import annotations

import random
from typing import Callable, Sequence, TypeVar

T = TypeVar("T")
Statistic = Callable[[Sequence[T]], float]


def _percentile_indices(n_resamples: int, alpha: float) -> tuple[int, int]:
    lo_i = int((alpha / 2) * n_resamples)
    hi_i = min(int((1 - alpha / 2) * n_resamples), n_resamples - 1)
    return lo_i, hi_i


def bootstrap_ci(records: Sequence[T], statistic: Statistic,
                  n_resamples: int = 2000, alpha: float = 0.05,
                  seed: int = 7) -> dict:
    """Percentile bootstrap CI for `statistic` computed over `records`.

    Returns {"point", "lo", "hi", "n_resamples", "n_units"}. With no records
    the interval collapses to the (degenerate) point estimate rather than
    raising, so callers can report "no data" honestly instead of crashing.
    """
    point = statistic(records)
    n = len(records)
    if n == 0:
        return {"point": point, "lo": point, "hi": point,
                "n_resamples": 0, "n_units": 0}
    rng = random.Random(seed)
    draws = []
    for _ in range(n_resamples):
        sample = [records[rng.randrange(n)] for _ in range(n)]
        draws.append(statistic(sample))
    draws.sort()
    lo_i, hi_i = _percentile_indices(n_resamples, alpha)
    return {"point": point, "lo": draws[lo_i], "hi": draws[hi_i],
            "n_resamples": n_resamples, "n_units": n}


def paired_bootstrap_delta(records: Sequence[T], statistic_a: Statistic,
                            statistic_b: Statistic, n_resamples: int = 2000,
                            alpha: float = 0.05, seed: int = 7) -> dict:
    """CI on statistic_b(records) - statistic_a(records).

    Both statistics are evaluated on the *same* resample each iteration
    (paired), which is what lets a narrow interval on the delta rule out "this
    lift is noise" even when each statistic's own interval is wide.
    """
    point_a, point_b = statistic_a(records), statistic_b(records)
    point = point_b - point_a
    n = len(records)
    if n == 0:
        return {"point": point, "lo": point, "hi": point,
                "a": point_a, "b": point_b, "n_resamples": 0, "n_units": 0,
                "excludes_zero": False}
    rng = random.Random(seed)
    draws = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        sample = [records[i] for i in idx]
        draws.append(statistic_b(sample) - statistic_a(sample))
    draws.sort()
    lo_i, hi_i = _percentile_indices(n_resamples, alpha)
    lo, hi = draws[lo_i], draws[hi_i]
    return {"point": point, "lo": lo, "hi": hi, "a": point_a, "b": point_b,
            "n_resamples": n_resamples, "n_units": n,
            "excludes_zero": lo > 0 or hi < 0}


def ratio_of_sums(num_key: str, den_key: str) -> Statistic:
    """Build a statistic: sum(record[num_key]) / sum(record[den_key])."""
    def stat(records: Sequence[dict]) -> float:
        num = sum(r[num_key] for r in records)
        den = sum(r[den_key] for r in records)
        return num / den if den else 0.0
    return stat


def union_recall(found_key: str, seen_key: str) -> Statistic:
    """Build a statistic: |union(found sets)| / |union(seen sets)|.

    For metrics defined as "distinct things found" over "distinct things
    possible" (e.g. ring recall), where a cycle contributes a *set* rather
    than a count.
    """
    def stat(records: Sequence[dict]) -> float:
        found: set = set()
        seen: set = set()
        for r in records:
            found |= r[found_key]
            seen |= r[seen_key]
        return len(found) / len(seen) if seen else 0.0
    return stat
