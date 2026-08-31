# 18 of 34 training query groups were all-positive, and the fix costs 156 positives

**Recorded:** 2026-08-31. **Measured from:** `data/ranker_pool.npz`
(the pool written 2026-08-31 11:55), recomputed directly rather than read from
the summary in `data/eval_ranker.json` — the recomputation reproduces that
summary exactly, which is what makes the per-group table quotable.
**Full table:** `docs/inventory/query_groups.md`.

## What was measured

`ring_time_split` assigned positives by **ring identity** and negatives by
**timestamp**. For every generation cycle at or after `split_t = 7980`, train
therefore received that cycle's positives and none of its negatives.

| | groups | positives |
|---|---:|---:|
| informative (mixed labels) | 16 | 165 |
| **all-positive remnant** | **18** | **156** |
| all-negative | 0 | 0 |
| **total** | **34** | **321** |

**All 18 unusable groups share exactly one reason.** Not most of them — all of
them.

A lambdarank query group whose labels are all identical generates no discordant
pairs and contributes exactly zero gradient. So **48.6% of the training
positives were invisible to LambdaMART while remaining fully visible to the
pointwise classifier**, which has no notion of groups.

## Why this is a negative result and not just a bug

It invalidates the framing of a comparison that had already been written down
and reported. `docs/CENTREPIECE-INVALIDATED.md` states the listwise-vs-pointwise
head-to-head as the comparison "item 1.3 actually turns on", and reports that
the pre-registration holds at k=10 and k=20. That comparison was made between
two models trained on **different amounts of signal**, in the pointwise model's
favour — so the null result was weaker evidence than it looked, not stronger.
The confound was stated in the run's own output, which is to its credit, but
stating a confound is not the same as removing it.

A second defect is visible in the same table and is *not* the reason any group
was unusable: **6 of the 16 informative groups exceed LightGBM's hard
10,000-row lambdarank ceiling**, the largest being 24,545 rows. Those are
handled by negative subsampling in train only.

## The fix, and what it costs

`ring_time_split` now bounds train by the cutoff: a positive whose ring is a
train ring but whose timestamp is at or after `split_t` is **dropped from
train**. It is not moved to test — that would be the ring leak the split exists
to close.

Three consequences, and the second is a real cost:

1. Every remaining training group carries mixed labels. The two objectives
   receive the same signal and the head-to-head is no longer confounded.
   Asserted before any model is fitted, in `scripts/eval_ranker.py`.
2. **Train loses 156 of 321 positives**, which the pointwise model previously
   used. The headline number moves, and it moves down. See the measured
   before/after below.
3. The split's time-ordering claim becomes literally true for the first time.
   Every train record now has `t < split_t` and every test record `t >= split_t`.
   The qualification the docstring used to carry — "time-ordered on the
   NEGATIVE pool only" — is no longer needed, and the assertion is
   correspondingly strengthened.

**The test set is byte-identical across the fix.** Only training changed, so
before/after is a paired comparison on the same held-out cycles rather than two
different experiments. That was the reason for preferring this fix over the
alternative of moving the stranded positives into test.

## Known cost, deliberately not fixed in the same change

A train ring whose first appearance is **exactly** `split_t` now contributes no
training records at all, while still being excluded from test by
ring-disjointness. Such a ring is wasted. It was equally wasted before in every
practical sense — all its candidates sat in the dead groups — but it is worth
naming. Recovering those rings would mean moving them to test, which changes
the held-out denominator and would destroy the paired comparison above. Not
bundled.

## Measured effect

Whole chain re-run end to end, no cache: `eval_ranker` → `compile_corpus
--adopt` → `eval_oracle` → `eval_ring_unit`. All four exit 0. Log:
`data/rerun_deadgroupfix.log`.

Superseded artefacts retained as `data/*.DEADGROUPS.*.bak`. **The three JSON
results are committed; the two 62 MB `.npz` pool snapshots are kept on disk but
gitignored.** That is a deliberate departure from the convention that retained
`data/ranker_pool.PREFIX.npz.bak` in git, and the reason is that the two cases
differ: there, the stale pool's *contents* were the evidence for the
mixed-provenance finding and could not be reconstructed. Here the evidence is
the per-group table and the JSON, both committed, and the pools are exactly
regenerable by reverting the `ring_time_split` change and re-running
`scripts/eval_ranker.py`. Nothing is deleted.

### The fix did what it was built to do

| | before | after |
|---|---:|---:|
| training query groups | 34 | **16** |
| all-positive (zero-gradient) groups | **18** | **0** |
| training positives | 321 | **165** |
| positives LambdaMART can learn from | 165 of 321 | **165 of 165** |

### The test set really is byte-identical

Not asserted — demonstrated. Every baseline that reads nothing the change
touched reproduces to four decimal places, in both arms:

| baseline | p@10 before | p@10 after |
|---|---:|---:|
| blend | 0.1889 | 0.1889 |
| size | 0.0444 | 0.0444 |
| degree | 0.0222 | 0.0222 |
| random | 0.0000 | 0.0000 |

A baseline that ignores training cannot move unless the evaluation moved. None
moved.

### The cost, as predicted, and larger than predicted

Supervised p@10 **0.2500 → 0.2111**. The oracle/blend ratio the centrepiece was
killed on falls further, **1.32× → 1.12×** at k=10 and 1.42× → 1.28× at k=20.

And the supervised model's paired lead over the shipped blend **loses
CI-clearance at the depths that matter**:

| k | before | after |
|---:|---|---|
| 10 | +0.0611 [+0.0111, +0.1167] | **+0.0222 [−0.0333, +0.0889]** |
| 20 | +0.0417 [+0.0139, +0.0778] | **+0.0278 [−0.0083, +0.0667]** |
| 50 | +0.0144 [+0.0033, +0.0267] | +0.0156 [+0.0022, +0.0311] |

Three independent estimators agree on this, which is why it is stated as a
finding rather than a wobble:

- candidate-level p@k (above);
- distinct-ring p@10, 0.2167 → 0.1889;
- the ring-unit metric, P(surfaced | built) supervised − blend
  **+0.1379 [+0.0444, +0.2411] → +0.0625 [−0.0809, +0.1976]**.

The consequence for the write-up is in
[`lambdamart-reversal.md`](lambdamart-reversal.md): a sentence this repository
has been quoting — "the supervised re-ranker still beats the blend with
intervals excluding zero at every k" — is now false at k=10 and k=20.

### An effect in the opposite direction that is NOT explained

On the **seed-cheat** arm the same change moved the supervised model sharply
**up**, not down:

| k | before | after | ratio before → after |
|---:|---:|---:|---|
| 10 | 0.4833 | **0.5611** | 1.18× → 1.36× |
| 20 | 0.3278 | **0.4694** | 1.13× → 1.63× |
| 50 | 0.1644 | **0.3367** | 1.22× → **2.50×** |

1,443 of 2,776 training positives were dropped and the model got materially
better, more than doubling at k=50. The as-is arm lost a comparable *fraction*
(156 of 321) and got worse.

**No mechanism is asserted for this.** The plausible one — that
`class_weight="balanced"` was being computed over a positive set half of which
arrived with no negatives, distorting the decision threshold, and that the cheat
arm's 8× larger positive count made the distortion far worse — is a hypothesis
that has not been tested. It is recorded here as an open anomaly rather than
explained away, because an unexplained improvement is exactly as suspicious as
an unexplained regression and this repository's own history is mostly the
former turning out to be a defect.

**Do not quote the seed-cheat numbers until this is understood.** They are a
ceiling diagnostic and were never quotable as a result, which limits the damage,
but the anomaly also touches the as-is arm's class weighting and that arm *is*
quoted.

## What would reverse this

Any one of:

- A measurement showing that all-positive query groups do contribute gradient
  under this LightGBM version and objective — which would mean the 156
  positives were never lost and the fix costs signal for nothing. Testable
  directly: fit LambdaMART with and without the dead groups on the pre-fix
  pool and compare predictions for equality.
- A demonstration that the pointwise model's advantage over LambdaMART survives
  unchanged once both are trained on the 16 informative groups only. That would
  mean the confound was real but not load-bearing, and the head-to-head
  conclusion stands on its original evidence.
- A split rule that recovers the 156 positives without either leaking ring
  identity across the boundary or changing the held-out denominator. None is
  known; the three options considered are in `docs/inventory/query_groups.md`.
