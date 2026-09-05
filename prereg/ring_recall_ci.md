# D5 — a valid interval for ring recall

**Pre-registered 2026-09-05, before any estimator was written or run.**

## The defect

`ring_recall@k` point estimates fall OUTSIDE their own 95% intervals:

```
HI-Medium ring_recall@10   point 0.11947   CI [0.09609, 0.11249]
HI-Small  ring_recall@50   point 0.16000   CI [0.14290, 0.15500]
```

HI-Medium fails at all three k; HI-Small at k=20 and k=50. Read from
`data/funnel-HI-Medium.json` and `data/funnel.json`, not from prose.

## Mechanism (stated before the fix, so the fix can be wrong)

`union_recall` computes `|∪ found| / |∪ seen|` over the resampled cycles.
A bootstrap resample of n cycles drawn with replacement contains only
~63.2% distinct cycles, so both unions shrink. They do **not** shrink at
the same rate:

* a ring is *seen* in every cycle whose window it is active in — typically
  several consecutive cycles;
* a ring is *found* in a strict subset of those, often exactly one.

So the numerator rests on fewer supporting cycles per ring than the
denominator, and dropping cycles removes rings from `found` faster than
from `seen`. The ratio is therefore biased **downward by construction**,
and no percentile of the resample distribution need contain the point.

**`p@k` is unaffected** — it is a ratio of sums, where duplicating a cycle
duplicates numerator and denominator together.

## The fix being tested (exactly one; no method shopping)

**Owner attribution.** Assign each distinct ring to a single owning cycle
— the first cycle, by index, in which it is seen. A ring's found-status is
`ring ∈ ∪found` computed over the **full** data, not over the resample.
Each cycle then carries two integers, `rings_found` and `rings_owned`,
and ring recall becomes `ratio_of_sums` — the same shape as p@k.

**Why the found-status is a full-data property.** Whether the detector
found a ring is a fact about the detector's behaviour on that ring; it
saw every cycle. Letting the resample revoke it conflates "this cycle was
not sampled" with "the detector missed it", which is the bug itself. The
resample varies *which rings enter the estimate*, not *whether a given
ring was found*.

**Secondary, reported but not shipped:** fractional attribution (a ring
seen in m cycles contributes 1/m to each). First-appearance ownership is
unbalanced — the first cycle owns every ring active at the start — which
inflates variance and so is conservative. Fractional would balance the
blocks better.

**The decision rule is fixed now: the shipped number is first-appearance
ownership regardless of which of the two produces the nicer interval.**
Fractional is a robustness check only.

## Kill criteria

1. **The point estimate must not move.** Owner-attributed ratio-of-sums
   must equal `union_recall` EXACTLY (to float equality) on both splits
   and every k. Algebraically it must: each ring is owned once, and
   `found ⊆ seen`, so numerator = `|∪found|` and denominator = `|∪seen|`.
   If it moves, the fix silently changes a reported metric and is
   **rejected** — that would be a different claim needing its own writeup.
2. **The interval must contain the point** on both splits, every k, both
   attribution schemes. Any exception kills the fix.
3. **The negative control must fire.** On synthetic records built so the
   true recall is known, the OLD estimator must exclude the true value
   and the NEW one must contain it. A fix with no demonstrated failure of
   the thing it replaces is not evidence.
4. **No prediction is made about interval width.** The old interval was
   both shifted and possibly narrow; I am not claiming to know which.
   Width is reported, not adjudicated.

## Declared in advance

* This requires **re-running the funnel on both splits** — `eval_funnel.py`
  does not persist per-cycle records, which is why this cannot be
  recomputed offline and why M2's Monte-Carlo sweep could never include
  it. Persisting `cycle_rows` is part of this change.
* The HI-Medium oracle is running on the same 16.5 GB machine. The
  re-runs wait for it. **The estimator and its tests land first and are
  validated against synthetic data with known answers; the real-data
  numbers follow.** If the re-run then fails criterion 2, that is
  reported as a failure, not patched over.
* `union_recall` is not deleted — `eval_threshold_band.py` and
  `eval_phase2.py` compute ring recall as a point estimate with no
  interval, which is valid. It gains a guard against being passed to a
  bootstrap.
