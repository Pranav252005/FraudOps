# Pre-registration — label tax, BUDGET arm (uplift plan item 3B)

**Written:** 2026-09-01, at commit `82e2997`, **before any arm was run.**
Committed before `scripts/eval_label_tax.py` will start; the runner refuses to
begin without this file.

**This is a separate pre-registration from `label_tax_noise.md` on purpose.**
The two arms measure different quantities — the cost of *worse* labels and the
cost of *fewer* labels — and the plan is explicit that they must not be averaged
into one "label tax" number. They share a pool, a split, a model and a metric,
and nothing else.

## The estimand

> **Δ p@10 per halving of the labelled fraction `f`**, measured on the 18
> held-out cycles of the as-is pool, where the model is trained on a uniform
> random subsample of the training rows and **evaluated against true labels on
> the full held-out set**.

Units: precision points per halving. Reported per halving rather than per unit
of `f` because the grid is geometric and a linear coefficient over a geometric
grid is not interpretable.

## The design

`f ∈ {1.0, 0.5, 0.25, 0.1}` — the plan's grid, unchanged.

At each `f`, a uniform random subsample of **all training rows** is retained;
the rest are dropped from training entirely. Labels on retained rows are
**correct** — this arm has no corruption in it at all.

**Uniform, not stratified.** Stratifying to preserve the positive count would
make this arm measure something else: the cost of a smaller negative pool at
constant supervision. The question here is what a smaller *label budget* costs,
and a real budget cut loses positives in proportion. The consequence is that
`f=0.1` retains roughly 16 of 165 positives, and that is the point rather than
a defect.

Prevalence is approximately preserved by construction and is **reported at
every point** anyway, so that any drift is visible rather than assumed absent.

## Repetitions

**5 subsample seeds at every `f`**, for the same reason as the noise arm: at
`f=0.1` the draw retains ~16 positives, and which 16 plausibly matters more
than the fraction. Reported as mean and full range.

All variation across seeds is subsample variation — LightGBM's `random_state`
is inert at default bagging (`docs/negative-results/inert-seed-sweep.md`).

## The functional form, and the null

Fitted: **ordinary least squares of p@10 on log2(f)**, giving a slope in
precision points per halving.

- **Null:** slope = 0, i.e. discarding labels does not degrade held-out
  precision.
- Interval: cycle-clustered bootstrap over the 18 held-out cycles
  (`docs/STANDING-RULES.md` rule 5).
- Linearity in log2(f) is an assumption, not a claim. Residuals are reported.

## Stopping condition

Run all 4 `f` values × 5 seeds = 20 fits. No early stopping, no grid extension,
no added seeds.

"No effect detected" looks like: the slope's CI includes zero, reported as
`"budget effect not resolvable at n=18, slope CI = [a, b]"`, with the required
`n` computed from the observed between-seed variance rather than guessed.

## What would falsify the hypothesis

That fewer labels cost held-out precision is falsified by the slope's CI
including zero across the full grid down to `f=0.1` — at which point 90% of the
training set is gone and the model is still as good. On a pool with 165
positives that outcome is genuinely possible, and it would say the labels are
heavily redundant and the corpus is larger than the problem requires.

## What this arm cannot see, stated before it is run

**1. It is not comparable to the noise arm and must not be combined with it.**
Halving the labels and mislabelling half of them are different interventions
with different mechanisms. Any single number claiming to be "the label tax"
across both arms is a construct with no estimand behind it.

**2. It measures corpus size, not corpus quality.** A deployment's real
constraint is usually analyst hours, which buys both fewer *and* worse labels
at once. The interaction between the two arms is not measured here and is not
inferable from the two slopes.

**3. Dropping a row is not the same as never having collected it.** The
candidates still exist in the pool that generated the split; only their
supervision is withheld. A genuinely smaller label budget would also have
produced a different queue, and therefore different candidates to label. That
feedback loop is out of scope for this arm and is not approximated by it.
