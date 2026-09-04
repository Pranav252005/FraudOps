# Pre-registration — M2, the bootstrap's own Monte Carlo error

**Written 2026-09-05, before `scripts/eval_bootstrap_mc.py` existed.** Item
**M2** in [`docs/EXPERIMENT-QUEUE.md`](../docs/EXPERIMENT-QUEUE.md), raised by
[`docs/graph-review/2026-09-04.md`](../docs/graph-review/2026-09-04.md) §4c.

## The question

Every interval this project reports comes from `sentinel/eval/bootstrap.py`
with **`seed=7, n_resamples=2000`**. A percentile bootstrap is itself a Monte
Carlo estimate, so its endpoints carry sampling error of their own. Every
"excludes zero" verdict in this repository — which is how *every* result here
is adjudicated — is a comparison of one of those noisy endpoints against zero.

The review's phrasing was: *"at n=18 cycles that is almost certainly fine, but
'almost certainly' is not the standard here."*

**This needs no replay.** Seven committed runs persist their per-cycle rows, so
the bootstrap can simply be re-run over the stored records at other seeds.

## What is re-checked

Every comparison that carries a verdict, from every file with `cycle_rows`:

| file | n | what it decided |
|---|---:|---|
| `eval_phase2.json` | 34 | the shipped headline, `score − size` |
| `eval_ranker.json` | **18** | ranker comparisons — the smallest n, so the most exposed |
| `eval_threshold_band.json` | 34 | M1's claim of **18/18** intervals excluding zero |
| `eval_seed_arms.json` | 34 | S1/S2 |
| `eval_fragment_link.json` | 34 | B1 |
| `eval_suppression_key.json` | 34 | B3 |
| `eval_seed_lookback.json` | 34 | P0 |

Two families per file: **within-arm** `score − size` (rule 2's re-tie check) and
**between-arm** paired deltas against the reference arm.

**Protocol.** Each comparison is re-run at **40 seeds** × `n_resamples ∈
{2000, 10000}`. Recorded per comparison: the committed verdict, the fraction of
seeds agreeing with it, and the spread of both interval endpoints.

## A verdict flip is the unit of interest, not endpoint wobble

Endpoints *will* move — that is what Monte Carlo error is. **The only thing
that matters is whether a conclusion changes**, i.e. whether `excludes_zero`
differs from the committed value at any seed.

## Pre-registered expectations

Several committed intervals already sit within a whisker of zero. Reading them
off the stored files **before** running anything:

| comparison | committed interval | nearer endpoint |
|---|---|---:|
| B3 `largest − score` @k=10 | [−0.0265, −0.0029] | **0.0029** |
| B1 `link − shipped` @k=10 | [−0.0029, +0.0882] | **0.0029** |
| B3 `smallest − score` @k=10 | [−0.0088, +0.0000] | **0.0000** |
| S1 `gargaml − shipped` @k=20 | [+0.0010, +0.0120] | **0.0010** |

| quantity | prediction |
|---|---|
| **verdict flips overall** | **1 to 6.** Not zero — four comparisons have an endpoint within 0.003 of zero, and 2,000 resamples cannot resolve that |
| flips among comparisons whose nearer endpoint is **> 0.01** from zero | **zero** |
| flips at `n_resamples = 10000` vs 2000 | **fewer**, roughly halving |
| **P0's `lb6 − lb1`** (+0.2588, +0.2426, +0.1076) | **no flip at any seed** — these are nowhere near zero |
| **M1's 18/18** | **at most 1 flip**; its narrowest margin was +0.0294 |
| shipped `score − size` @k=10/20/50 | **no flip** |
| `eval_ranker.json` at n=18 | **most flips per comparison of any file** |

## Kill criteria

1. **A verdict flips on a comparison that a findings document reports as its
   conclusion.** Then that document is wrong as written and **must be
   corrected**, and the affected claim re-reported at a resample count where it
   is stable. This is the outcome that costs something and it is the reason the
   experiment is worth running.

2. **P0's `lb6 − lb1` flips at any seed.** The largest claim made in two days
   would be seed-dependent. That would be severe and I do not expect it.

3. **More than 25% of all comparisons flip.** Then `n_resamples = 2000` is
   inadequate project-wide, not just at the margins, and the default in
   `sentinel/eval/bootstrap.py` must be raised — a change affecting every number
   this repo has ever reported.

## What this cannot settle

- **Whether the bootstrap is the right estimator.** It checks the Monte Carlo
  error of the procedure as configured, not the procedure's validity. Cluster
  bootstrap at n=18–34 has its own coverage properties and this says nothing
  about them.
- **Anything about the underlying data.** No replay, no new candidates. Only
  the resampling RNG changes.
- **A flip is not evidence the committed verdict was wrong** — only that it was
  not resolved at 2,000 resamples. The higher-resample answer is the better
  estimate, not automatically the true one.
