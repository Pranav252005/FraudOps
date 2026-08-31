# Phase 0.5 — Inventory of the query groups

**Produced:** 2026-08-31. **Method:** recomputed directly from
`data/ranker_pool.npz` (`train_t`, `train_y`, `train_ring`, `split_t`) —
i.e. from the stored pool, not from the summary in `data/eval_ranker.json`.
The recomputation reproduces that summary exactly (34 groups, 16 informative,
18 single-label, 165 / 156 positives), which is the cross-check that makes the
per-group table below quotable.

## The answer, in one line

**All 18 unusable groups share exactly one reason.** Every one of them is an
**all-positive remnant group**: a generation cycle at or after `split_t = 7980`
whose negatives were assigned to *test* by timestamp while its positives stayed
in *train* by ring identity.

## Why that happens

`ring_time_split` (`scripts/eval_oracle.py:262`) uses two different assignment
rules on purpose:

- **positives** follow their **ring** — a ring whose first appearance precedes
  the cut keeps *all* its candidates in train, including those occurring after
  the cut;
- **negatives** follow their **timestamp** — every negative after `split_t`
  goes to test, with no exception.

So for every cycle at or after `split_t`, train receives the positives and none
of the negatives. A lambdarank query group whose labels are all identical
generates no discordant pairs and therefore contributes exactly **zero
gradient**. The 156 positives in those groups are invisible to LambdaMART while
remaining fully visible to the pointwise classifier, which has no notion of
groups.

This is already documented at `scripts/eval_ranker.group_diagnostics.__doc__`
and stated as a confound in `docs/CENTREPIECE-INVALIDATED.md`. What is new here
is that it accounts for **18 of 18** unusable groups, not most of them.

## Per-group table

| tick | rows | pos | neg | distinct rings | usable? | reason |
|---:|---:|---:|---:|---:|---|---|
| 2220 | 15,494 | 10 | 15,484 | 9 | yes | mixed labels **exceeds the 10,000-row lambdarank ceiling** |
| 2580 | 15,560 | 8 | 15,552 | 6 | yes | mixed labels **exceeds the 10,000-row lambdarank ceiling** |
| 2940 | 24,545 | 6 | 24,539 | 6 | yes | mixed labels **exceeds the 10,000-row lambdarank ceiling** |
| 3300 | 4,724 | 4 | 4,720 | 4 | yes | mixed labels |
| 3660 | 4,811 | 6 | 4,805 | 4 | yes | mixed labels |
| 4020 | 4,915 | 3 | 4,912 | 3 | yes | mixed labels |
| 4380 | 18,899 | 11 | 18,888 | 7 | yes | mixed labels **exceeds the 10,000-row lambdarank ceiling** |
| 4740 | 4,614 | 4 | 4,610 | 4 | yes | mixed labels |
| 5100 | 4,412 | 11 | 4,401 | 10 | yes | mixed labels |
| 5460 | 4,490 | 12 | 4,478 | 10 | yes | mixed labels |
| 5820 | 16,880 | 13 | 16,867 | 11 | yes | mixed labels **exceeds the 10,000-row lambdarank ceiling** |
| 6180 | 9,584 | 17 | 9,567 | 15 | yes | mixed labels |
| 6540 | 9,077 | 18 | 9,059 | 15 | yes | mixed labels |
| 6900 | 8,624 | 13 | 8,611 | 12 | yes | mixed labels |
| 7260 | 14,152 | 15 | 14,137 | 14 | yes | mixed labels **exceeds the 10,000-row lambdarank ceiling** |
| 7620 | 9,033 | 14 | 9,019 | 11 | yes | mixed labels |
| 7980 | 21 | 21 | 0 | 20 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 8340 | 12 | 12 | 0 | 10 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 8700 | 12 | 12 | 0 | 11 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 9060 | 13 | 13 | 0 | 12 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 9420 | 11 | 11 | 0 | 10 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 9780 | 11 | 11 | 0 | 9 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 10140 | 13 | 13 | 0 | 10 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 10500 | 7 | 7 | 0 | 5 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 10860 | 13 | 13 | 0 | 11 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 11220 | 4 | 4 | 0 | 4 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 11580 | 5 | 5 | 0 | 5 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 11940 | 11 | 11 | 0 | 9 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 12300 | 7 | 7 | 0 | 7 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 12660 | 5 | 5 | 0 | 5 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 13020 | 4 | 4 | 0 | 4 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 13380 | 2 | 2 | 0 | 2 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 13740 | 1 | 1 | 0 | 1 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |
| 14100 | 4 | 4 | 0 | 4 | **no** | single-label: all-positive remnant (tick >= split_t; its negatives went to test by timestamp) |

## Totals

| | groups | positives |
|---|---:|---:|
| informative (mixed labels) | **16** | **165** |
| single-label: all-positive remnant | **18** | **156** |
| single-label: all-negative | 0 | 0 |
| **total** | **34** | **321** |

**48.6% of the training positives (156 / 321) sit in groups that contribute no
gradient to the listwise objective.**

A second, independent defect is visible in the same table and is *not* the
reason any group is unusable: **6 of the 16 informative groups exceed
LightGBM's hard 10,000-row lambdarank ceiling** (the largest is 24,545 rows at
tick 2940). Those are handled by `_cap_query_rows`, which subsamples negatives
in train only. Recorded here because it is the second way this pool is not what
the listwise objective is nominally being given.

## Flag — the plan's pre-interpreted outcome fires

> **If more than half the unusable query groups share one reason** → flag it.
> Fixing that one reason may buy more interval-narrowing per hour than running
> more cycles, and Phase 1's target should be reconsidered.

**18 of 18 share one reason. The condition is met at 100%, not "more than
half".** Combined with `docs/inventory/cycles.md` — which establishes that
"more cycles" has no seed knob and that the cheapest cycle-count increase
(halving `EVERY`) buys correlated observations rather than information — this
should be read as: **fixing the split's negative-assignment rule is very likely
a better use of the next hour than any cycle-count increase.**

The fix is not free and is not obvious, which is why this is a flag and not a
recommendation to act:

- **Option A — drop post-`split_t` train records entirely.** Removes the dead
  groups. Also removes 156 positives from the *pointwise* model, which
  currently uses them. This would change the headline number.
- **Option B — keep post-`split_t` negatives for train-assigned cycles.**
  Restores mixed labels. Directly weakens the negative-pool time-ordering
  invariant that `ring_time_split` asserts, which is one of the two leakage
  guards the whole result rests on.
- **Option C — leave it and stop comparing listwise to pointwise on this pool.**
  Costs nothing and is honest; buys no `n`.

**No option is taken here.** Phase 0 changes nothing.
