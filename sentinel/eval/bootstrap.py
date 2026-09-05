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

    **NEVER pass this to `bootstrap_ci` or `paired_bootstrap_delta`.** A union
    is not a ratio of sums, and a cluster bootstrap cannot bound it: the
    interval is biased low by construction and need not contain its own point
    estimate. That is not hypothetical -- it shipped, and on HI-Medium every
    `ring_recall@k` point landed above its own `hi`. Use
    `owner_attributed_counts` with `ratio_of_sums` instead, which gives the
    identical point estimate and a valid interval.

    This function remains correct, and is the right thing, for a **point
    estimate with no interval** -- which is how `eval_phase2.py` and
    `eval_threshold_band.py` use it. `tests/test_union_recall_ci.py` enforces
    the separation statically.
    """
    def stat(records: Sequence[dict]) -> float:
        found: set = set()
        seen: set = set()
        for r in records:
            found |= r[found_key]
            seen |= r[seen_key]
        return len(found) / len(seen) if seen else 0.0
    return stat


def owner_attributed_counts(records: Sequence[dict], found_key: str,
                            seen_key: str, *, fractional: bool = False,
                            num_key: str = "rings_found",
                            den_key: str = "rings_owned") -> list[dict]:
    """Turn per-cycle ring *sets* into per-cycle counts a bootstrap can use.

    **Why this exists.** `union_recall` below cannot be handed to
    `bootstrap_ci`. A resample of n cycles with replacement holds only ~63.2%
    distinct cycles, so both unions shrink -- but not at the same rate. A ring
    is *seen* in every cycle whose window it is active in, typically several
    consecutive ones, and *found* in a strict subset of those, often exactly
    one. The numerator therefore rests on fewer supporting cycles per ring than
    the denominator, dropping a cycle removes rings from `found` faster than
    from `seen`, and the ratio is biased **downward by construction**. Measured
    on HI-Medium, every `ring_recall@k` point estimate fell *above* its own
    interval (0.11947 against [0.09609, 0.11249]). See `prereg/ring_recall_ci.md`.

    The fix assigns every distinct ring to **one owning cycle** -- the first,
    by index, in which it is seen -- and records whether it was found *anywhere
    in the full data*. Ring recall is then `ratio_of_sums(num_key, den_key)`,
    the same shape as p@k, and resampling duplicates or drops a cycle's rings
    from numerator and denominator together. No asymmetry, no bias.

    The point estimate is unchanged, algebraically: each ring is owned exactly
    once and `found` is a subset of `seen`, so the sums are `|union(found)|`
    over `|union(seen)|`.

    **The found-status is deliberately a full-data property.** Whether the
    detector found a ring is a fact about the detector's behaviour on that
    ring, and it saw every cycle. Letting a resample revoke it conflates "this
    cycle was not sampled" with "the detector missed it" -- which is the bug.
    The resample varies which rings enter the estimate, not whether a given
    ring was found.

    `fractional=True` splits a ring seen in m cycles as 1/m to each instead.
    First-appearance ownership is unbalanced -- the first cycle owns every ring
    active at the start -- which inflates variance and is therefore
    conservative. Fractional balances the blocks. It is a **robustness check**;
    the pre-registered shipped estimator is first-appearance.

    Returns a new list, one dict per input record, carrying only the two count
    keys. Records are not mutated.
    """
    owner: dict = {}
    seen_in: dict = {}
    found: set = set()
    for i, r in enumerate(records):
        for ring in r[seen_key]:
            owner.setdefault(ring, i)
            seen_in.setdefault(ring, []).append(i)
        found |= r[found_key]

    unseen = found - owner.keys()
    if unseen:
        raise ValueError(
            f"{len(unseen)} ring(s) reported found but never seen, e.g. "
            f"{sorted(unseen)[:3]}. Ring recall would exceed 1; the caller's "
            f"found/seen sets disagree.")

    out = [{num_key: 0.0, den_key: 0.0} for _ in records]
    for ring, first in owner.items():
        hit = float(ring in found)
        if fractional:
            cycles = seen_in[ring]
            share = 1.0 / len(cycles)
            for i in cycles:
                out[i][den_key] += share
                out[i][num_key] += hit * share
        else:
            out[first][den_key] += 1.0
            out[first][num_key] += hit
    return out
