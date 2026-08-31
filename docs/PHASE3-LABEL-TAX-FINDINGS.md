# The label tax is a coefficient now, and it is not prevalence drift

**Date:** 2026-09-01. **Pre-registered:** `prereg/label_tax_noise.md` and
`prereg/label_tax_budget.md`, both committed at `a4eee6e` **before**
`scripts/eval_label_tax.py` existed. The runner refuses to start without a
committed prereg for the arm and records the sha it ran against.
**Data:** `data/eval_label_tax_noise.json`, `data/eval_label_tax_budget.json`.

**Two arms, never averaged.** Worse labels and fewer labels are different
interventions with different mechanisms. There is no combined "label tax"
number here and there must not be one downstream.

## The gate that had to pass first

The p=0 / f=1.0 arm reproduces the stored headline **exactly, to every digit,
at all three k** — p@10 0.2111111111111111, p@20 0.12777777777777777, p@50
0.06222222222222222, identical to `data/eval_oracle.json`. That is a regression
test on the entire harness: pool loading, the fit, the per-cycle grouping and
the metric. Had it failed, nothing else in this document would be trustworthy.

## Arm A — noise: what wrong labels cost

`p` = fraction of the 165 training positives relabelled negative. Positives
only, one direction (the analyst **miss**). Evaluation always against true
labels.

| p | raw p@10 | seed range | control p@10 | seed range | train prevalence |
|---:|---:|---|---:|---|---:|
| 0.00 | 0.2111 | [0.2111, 0.2111] | 0.2111 | [0.2111, 0.2111] | 0.000972 |
| 0.05 | 0.2289 | [0.2111, 0.2444] | 0.2356 | [0.2111, 0.2611] | 0.000925 |
| 0.10 | 0.2244 | [0.1944, 0.2500] | 0.2233 | [0.2111, 0.2389] | 0.000877 |
| 0.20 | 0.2100 | [0.1833, 0.2333] | 0.2200 | [0.1889, 0.2444] | 0.000777 |
| 0.40 | 0.1844 | [0.1611, 0.2056] | 0.2111 | [0.1944, 0.2278] | 0.000583 |

**raw** = the flipped positives stay in training, labelled wrong.
**control** = the same positives are removed entirely, so the correct-label
count matches raw exactly and only prevalence differs (by at most a factor of
1.0004).

### The fit

| | slope per unit p | per 0.1 | 95% CI (per unit p) | |
|---|---:|---:|---|---|
| raw | −0.0917 | −0.0092 | [−0.1622, −0.0289] | **excludes zero** |
| prevalence-matched control | −0.0261 | −0.0026 | [−0.0650, +0.0139] | includes zero |
| **label tax (raw − control)** | **−0.0656** | **−0.0066** | **[−0.1194, −0.0156]** | **excludes zero** |

### The citable result

> **Δ p@10 = −0.0066 per 0.1 increase in the positive-label flip rate**
> (95% CI [−0.0119, −0.0016]), n = 18 held-out cycles, cycle-clustered
> bootstrap, true-label evaluation, as-is pool with 165 training positives.

**And it is not prevalence drift.** This is the outcome the prereg named as the
discriminating one. The prevalence-matched control — same number of correct
positives, the flipped rows simply absent — shows **no resolvable effect**
(CI includes zero). The degradation appears only when the wrong labels are
*present*. So the cost is being paid for label **quality**, not for having
fewer positives.

The interval on the difference is computed on the **same** cycle resample as
both slopes, not by comparing two separate intervals for overlap. The arms are
strongly correlated — same cycles, same features, same model — so the
difference is far better determined than either slope, and overlap of the two
marginal intervals would say nothing either way.

### Non-monotone, recorded rather than smoothed

p@10 **rises** from 0.2111 to 0.2289 at p=0.05 before falling. The
pre-registration committed to recording this rather than fitting around it.

Two things bound how much to read into it. The rise (+0.0178) sits inside the
between-seed spread at that point (0.2111 to 0.2444), so it is consistent with
draw noise. And it appears in the control arm too (0.2111 → 0.2356), which is
the arm with no wrong labels in it at all — so whatever it is, it is not an
effect of mislabelling. It is recorded in `docs/negative-results/` and is
**not** presented as evidence that a little label noise helps.

## Arm B — budget: what fewer labels cost

`f` = fraction of training rows retained, uniformly at random, labels correct.

| f | p@10 | seed range | train rows | positives | prevalence |
|---:|---:|---|---:|---:|---:|
| 1.00 | 0.2111 | [0.2111, 0.2111] | 169,814 | 165 | 0.000972 |
| 0.50 | 0.2011 | [0.1833, 0.2333] | 84,907 | 85 | 0.001001 |
| 0.25 | 0.1778 | [0.1389, 0.2222] | 42,454 | 34 | 0.000801 |
| 0.10 | 0.1133 | [0.0778, 0.1444] | 16,981 | 13 | 0.000766 |

> **Δ p@10 = −0.0295 per halving of the label budget**
> (95% CI [−0.0470, −0.0144]), n = 18 held-out cycles, monotone in `f`.

Monotone, and the slope excludes zero.

## Reading the two arms together — without averaging them

The arms are not commensurable and no combined figure is given. But one
comparison **is** legitimate, because it is internal to the measured points
rather than a construct across the two slopes:

- **Dropping 40% of the positives costs nothing measurable.** The noise arm's
  control at p=0.4 retains 99 correct positives and scores **0.2111** — exactly
  the baseline.
- **Dropping to 34 positives costs a lot.** The budget arm at f=0.25 scores
  **0.1778**, and at 13 positives (f=0.10) it collapses to **0.1133**.

Both are "fewer correct positives, no wrong labels", so they are the same kind
of intervention at different depths. Together they suggest the positive set is
**redundant down to roughly 100 examples and not below** — a threshold, not a
gradient.

That is an observation from four measured points, not a fitted result. The
grid was pre-registered and is not extended to chase it; locating the threshold
would need its own pre-registration with points between 34 and 99.

## What these numbers are not

**They are not the experiment four places in this repository call cheap and
unrun.** That one is *"same model, same pool, same split, fitted once on truth
and once on simulated verdicts"*. The Phase 3 plumbing established that it is
**ill-posed as stated**: `SimulatedAnalyst.label_rate_caveat(169814, 165)`
returns a noise share of **0.851** — applying the shipped per-case analyst
rates to every candidate manufactures ~848 false positives against ~149
surviving true ones. A model trained on that measures the mismatch between a
per-case error rate and a per-candidate pool, not analyst error. An analyst
labels a **queue**, not a pool. Recorded in
`docs/negative-results/analyst-pool-mismatch.md`.

**They do not locate a deployment on the curve.** These arms say what precision
costs at a given flip rate or label budget. They do not say what flip rate a
real analyst queue has. Naming the coefficient is not the same as knowing where
on it you sit, and nothing here licenses multiplying the slope by a guessed
noise rate to produce a deployment number.

**The false-confirm direction is unmeasured**, deliberately and for the reason
above. Only misses were corrupted.

**Both arms are true-label evaluations on the as-is pool at n = 18.** The
intervals are wide in absolute terms and every caveat that travels with the
headline p@10 travels with these.

## Successor experiment, named and not run

Label only the **top-k of each training cycle** with the simulated analyst and
presume the rest negative — which is what a deployment actually has. Different
estimand, different design, needs its own pre-registration. It is the faithful
version of the experiment the repo has been claiming is cheap, and it is now
the most valuable unrun thing here.
