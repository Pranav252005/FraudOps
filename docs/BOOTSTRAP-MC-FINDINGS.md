# M2 — the bootstrap's Monte Carlo error changes no conclusion, and both my guesses about which ones were wrong

**Pre-registered in [`prereg/bootstrap_mc.md`](../prereg/bootstrap_mc.md)**
before `scripts/eval_bootstrap_mc.py` existed. Run 2026-09-05, 4,704 s, no
replay — only the resampling RNG changed.
`data/eval_bootstrap_mc.json`.

**320 comparisons × 40 seeds × `n_resamples ∈ {2000, 10000}`**, drawn from every
committed run that persists per-cycle rows: `eval_phase2`, `eval_ranker`,
`eval_threshold_band`, `eval_seed_arms`, `eval_fragment_link`,
`eval_suppression_key`, `eval_seed_lookback`.

## Headline

**No conclusion in this repository is seed-dependent.** Three comparisons of 320
flip at `n_resamples = 2000` (0.9%), two at 10,000 (0.6%) — and **none of them
is a claim any findings document makes.**

**No kill criterion fired.**

## The flips

| comparison | point | committed interval | flip rate @2k | @10k | is it a reported conclusion? |
|---|---:|---|---:|---:|---|
| `eval_seed_lookback` · `lb6` · degree−size @50 | −0.0106 | [−0.0218, +0.0000] | 22% | 3% | **no** — baseline against baseline |
| `eval_seed_arms` · `passthrough+random` · degree−size @20 | −0.0147 | [−0.0279, −0.0015] | 20% | 3% | **no** — baseline against baseline, in the null arm |
| `eval_threshold_band` · `hs0.6_mj0.4` · score−size @50 | +0.0147 | [+0.0012, +0.0282] | 3% | 0% | **no, and narrowly** — see below |

Two of the three are `degree − size`: one baseline against another, which no
document reports and nothing rests on.

### The third is a near-miss worth naming

`hs0.6_mj0.4 · score − size @ k=50` is in M1's tightest grid cell. M1's claim
was that `score − size` excludes zero in **9 of 9 cells at k=10 and 9 of 9 at
k=20 — 18 of 18**. Checked at every depth:

| depth | cells | flipping |
|---|---:|---:|
| k=10 | 9 | **0** |
| k=20 | 9 | **0** |
| k=50 | 9 | **1** |

**M1's claim survives intact because it was made at k=10 and k=20.** Had it been
stated as "27 of 27 across three depths", one of those 27 would have been
seed-dependent. That is luck rather than judgement, and it is recorded as luck.

## What did not move

| | flip rate |
|---|---:|
| **P0 `lb6 − lb1`** @10 / @20 / @50 (+0.2588 / +0.2426 / +0.1076) | **0% / 0% / 0%** |
| shipped `score − size` @10 / @20 / @50 / @100 | **0%** at every depth |
| all 191 comparisons whose nearer endpoint is > 0.01 from zero | **0%** |

P0's endpoints move by at most 0.0088 across 40 seeds against a point estimate
of +0.2588. The largest claim made in three days is not close to seed-dependent.

## Against the pre-registration

| predicted | observed | |
|---|---|---|
| **1 to 6 verdict flips** | **3** at B=2000 | hit |
| zero flips among nearest-endpoint > 0.01 | **0 of 191** | hit |
| fewer flips at 10,000, roughly halving | 3 → 2, and the *rates* fell 22%→3%, 20%→3%, 3%→0% | hit |
| P0's `lb6 − lb1` does not flip | it does not | hit |
| M1's 18/18: at most 1 flip | **0** at k=10/20 | hit |
| shipped `score − size` does not flip | it does not | hit |
| **`eval_ranker` (n=18) flips most per comparison** | **0 flips in 24 comparisons** | **MISSED** |
| *(implicitly, by tabulating them)* the four near-zero intervals are the ones at risk | **all four: 0% flip** | **MISSED** |

**Six hits and two misses, and the two misses are the interesting part: I was
wrong about *which* comparisons were fragile, while right about *how many*.**

The four intervals I tabulated in the pre-registration as most at risk — B3's
`largest − score` (nearest endpoint 0.0029), B1's `link − shipped` (0.0029),
B3's `smallest − score` (0.0000) and S1's `gargaml − shipped` (0.0010) — every
one of them held at **0% flip across 40 seeds at both resample counts**.

### Why the obvious predictors both failed

**Sample size does not predict flip risk.** `eval_ranker` has n=18 against
everything else's n=34, and I predicted it would be the most fragile. It
produced zero flips in 24 comparisons — despite one of them having a nearest
endpoint of exactly 0.0000.

**Endpoint proximity to zero does not predict it either.** `eval_ranker` has a
comparison with nearest endpoint 0.0000 and no flips; `lb6 · degree−size@50`
has nearest endpoint 0.0000 and flips 22% of the time.

What distinguishes them is not something the pre-registration reasoned about at
all: **how much of the bootstrap distribution's mass sits at the endpoint.**
Hit counts are small integers, so the resampled statistic is lumpy. An endpoint
that lands on a dense lump reproduces across seeds; one that lands on a sparse
shoulder does not. Neither n nor distance-to-zero captures that.

**Stated as a limitation rather than a theory:** this is a post-hoc explanation
of two failed predictions. It was not tested and it is not a result.

## Recommendation

**Do not raise the `n_resamples = 2000` default.** Going to 10,000 costs 5× on
every interval this project computes and moves the flip rate 0.9% → 0.6%, with
no conclusion affected either way. Kill criterion 3 (>25% flipping, which would
have forced the change) came nowhere near firing.

**What is worth doing instead** is targeted and cheap, and is queued rather than
done here because it changes a module every number in this repository flows
through: when an interval's nearer endpoint falls within ~0.005 of zero,
recompute that one interval at B ≥ 10,000 before quoting it as a verdict. All
three flips sit at nearest endpoint ≤ 0.0015; a 0.005 trigger catches them and
the four flagged intervals, and fires on roughly a tenth of comparisons.

## What this does not settle

- **Whether the cluster bootstrap is the right estimator at n=18–34.** This
  measures the Monte Carlo error of the procedure as configured, not its
  coverage. Those are different questions and only the first was asked.
- **A flip is not evidence the committed verdict was wrong**, only that 2,000
  resamples did not resolve it. The higher-resample answer is the better
  estimate, not automatically the true one.
- **Nothing about the data.** No replay; the records are the committed ones.
