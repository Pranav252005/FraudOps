# Pre-registration — label tax, NOISE arm (uplift plan item 3A)

**Written:** 2026-09-01, at commit `82e2997`, **before any arm was run.**
Committed before `scripts/eval_label_tax.py` will start; the runner refuses to
begin without this file.

## The estimand

> **Δ p@10 per 0.1 increase in the positive-label flip rate `p`**, measured on
> the 18 held-out cycles of the as-is pool, where the model is trained on
> corrupted labels and **evaluated against true labels**.

Units: precision points per 0.1 of flip rate. "Label tax" is not an estimand
and is not used as one anywhere in this file.

**Evaluation is always against truth.** Corrupting the test labels too would
measure the corruption twice — once in what the model learned and once in what
it is scored against — and would produce a number that falls for a reason that
has nothing to do with the model. The tax is a cost paid in *training*.

## What is corrupted, and what "flip" means

`p` is the fraction of **true positives in the training set** relabelled as
negative. Positives only, in one direction.

This is the analyst **miss**: a real ring dismissed. It is chosen over
symmetric corruption because the reverse error — a clean cluster confirmed —
behaves completely differently on a pool with ~0.1% positives, and averaging
the two into one "noise rate" would hide that. The false-confirm direction is
**deliberately not measured here**; see "What this arm cannot see" below.

## The design, and the prevalence control

At each `p`, two arms are fitted on the same rows:

| arm | the `p·165` selected positives are… | positives | rows |
|---|---|---|---|
| **raw** | relabelled negative, kept in train | (1−p)·165 | 169,814 |
| **prevalence-matched control** | removed from train entirely | (1−p)·165 | 169,814 − p·165 |

Both arms carry the same number of *correct* positive labels. The control
differs only in that the flipped rows are absent rather than present-and-wrong.

**The label tax is `raw − control`, not the raw slope.** The raw slope confounds
two things: fewer positives (a prevalence effect) and wrong positives (a noise
effect). The control holds the first fixed.

Prevalence differs between the arms by at most a factor of
169,814 / (169,814 − 66) ≈ **1.0004** at p=0.4, so the control is a genuine
match rather than a nominal one. Both prevalences are reported at every point
(rule 4 applies to Elliptic2; reporting them here is the same discipline).

## `p` grid and repetitions

`p ∈ {0, 0.05, 0.10, 0.20, 0.40}` — the plan's grid, unchanged.

**5 corruption seeds at every `p`.** This is not optional at this `n`. With 165
training positives, p=0.05 flips 8 specific rows, and *which* 8 plausibly
matters more than the rate. A single draw would produce a number with no way to
tell a dose response from a lucky sample. Reported as mean and full range
across seeds.

LightGBM itself is deterministic here — `random_state` is inert at default
bagging (`docs/negative-results/inert-seed-sweep.md`) — so **all** variation
across seeds is corruption-draw variation, which is exactly what is wanted.

## The functional form, and the null

Fitted: **ordinary least squares of p@10 on `p`**, through the five grid points,
on the seed-averaged values.

- **Null:** slope = 0, i.e. corrupting positive labels does not degrade held-out
  precision.
- Linearity is an assumption and is **not** asserted. Residuals are reported.
  If the response is not monotone in `p`, that is recorded as a finding and not
  smoothed — see the stopping condition.

Interval on the slope: cycle-clustered bootstrap over the 18 held-out cycles
(`docs/STANDING-RULES.md` rule 5 — p@k trials are not nested within rings, so
the cycle is the correct cluster).

## Stopping condition

Run all 5 `p` values × 5 seeds × 2 arms = 50 fits. No early stopping, no
extension. In particular the grid is **not** extended if the slope is
uninteresting, and seeds are **not** added if the spread is wide.

"No effect detected" looks like: **the slope's CI includes zero.** That is
reported as `"label tax not resolvable at n=18, slope CI = [a, b]"`, with the
`n` that would resolve it computed from the observed between-seed variance
rather than guessed.

## What would falsify the label-tax hypothesis entirely

The hypothesis is that training on degraded labels costs held-out precision.
It is falsified by **either**:

- the slope's CI including zero across the full grid up to p=0.40 — at which
  point 40% of positives are mislabelled and the model is still as good, which
  would mean the positives are largely redundant with each other; **or**
- `raw − control` being indistinguishable from zero while the raw slope is
  clearly negative — which would mean the whole effect is prevalence drift and
  nothing is being paid for label *quality*. This is a real possibility and the
  more interesting outcome of the two.

## What this arm cannot see, stated before it is run

**1. The false-confirm direction is excluded, and the reason is a measurement.**
`SimulatedAnalyst.label_rate_caveat(169814, 165)` returns
`noise_share_of_positive_labels = 0.851`: applying the shipped analyst rates to
every candidate in this pool manufactures ~848 false positives against ~149
surviving true ones. A model trained on that measures the mismatch between a
per-case error rate and a per-candidate pool, not analyst error. Recorded in
`docs/negative-results/`.

**2. This is therefore NOT the experiment four places in the repo call cheap
and unrun.** That one is "same model, same pool, same split, fitted once on
truth and once on simulated verdicts". Given point 1, **that experiment is
ill-posed as stated**: an analyst does not label a pool, they label a queue.
The faithful version — label only the top-k of each training cycle and presume
the rest negative — is a different design with a different estimand. It is
named here as the successor and is **not** run under this pre-registration.

**3. A dose-response curve does not locate a deployment on itself.** This arm
says what precision costs at a given flip rate. It does not say what flip rate
a real analyst queue has. Those are separate measurements and this file claims
only the first.
