# Closing a GFP coverage gap did not help, and sometimes hurt

**Recorded:** 2026-08-29. **Source:** `scripts/eval_median_gap.py`,
`data/eval_median_gap.json`.

## What was measured

Per-account median-amount features were added to close a coverage gap against
IBM's Graph Feature Preprocessor. Measured under genuine fit variation (see
[`inert-seed-sweep.md`](inert-seed-sweep.md) — the first attempt at this
measurement was inert and reported one fit as five):

- **k=10:** 2 of 5 fits show a CI-clear degradation, 0 of 5 show a gain; point
  estimates span −0.0556 to +0.0056.
- **k=20:** all five negative, 3 of 5 exclude zero.

**Never helped in any fit at either depth.**

## The decision, and the broader finding

Do not build a streaming quantile estimator for this. The design cost is real
and the measured benefit is negative-to-zero.

The broader finding survives at lower strength than it was first written at:
**closing a GFP coverage gap is not automatically an improvement.**
Feature-family coverage and measured performance are different things — the
same distinction that makes the parity claim in
[`gfp-parity-unmeasured.md`](gfp-parity-unmeasured.md) unsupportable.

## What would reverse this

- The same experiment on a pool where per-account history is deeper. This
  dataset's evaluable window is 10 days, which may be too short for a per-account
  median to stabilise; that is a plausible mechanism for a null and it has not
  been tested.
- A measured gain at k=10 or k=20 with an interval excluding zero, under fit
  variation rather than a single fit.
