# A five-seed stability sweep was one fit reported five times

**Recorded:** 2026-08-29, commit `8c17994`. **Source:**
`scripts/eval_median_gap.py`, `scripts/gfp_compare.py`.

## What happened

A five-seed sweep was added to check whether a measured degradation was a
single-fit artefact. It reported **"5 of 5 seeds show a CI-clear DEGRADATION at
k=10"** — while every seed had produced **bit-identical p@k to four decimal
places**.

That is one fit reported five times, presented as five agreeing fits.

## Cause

`LGBMClassifier`'s `random_state` is never consulted when bagging and feature
sampling are both at their default 1.0. LightGBM's histogram tree construction
is deterministic, so the RNG has nothing to seed. Verified directly: two seeds
give `np.array_equal` predictions under the shipped parameters, and differ once
`subsample`/`colsample_bytree` are added.

**This is load-bearing for anything that tries to raise `n` by re-seeding.**
There is no run-to-run variation to average over — see
`docs/inventory/cycles.md`, which establishes that the whole measured pipeline
is deterministic and that "run more cycles" has no seed knob.

## It changed the conclusion

Under genuine fit variation at k=10: 2 of 5 fits show a CI-clear degradation,
0 of 5 show a gain, and point estimates span −0.0556 to +0.0056. At k=20 all
five are negative and 3 of 5 exclude zero.

So the honest verdict is **not** "actively harmful". It is "never helped in any
fit at either depth, with a degradation that is real in some fits and not
others". The claim already written down was weakened.

An assertion now fails the run if two seeds ever produce identical predictions
again, so the defect cannot come back quietly.

## What would reverse this

A LightGBM version or configuration in which `random_state` does reach tree
construction at default bagging. The assertion added in `8c17994` would then
start passing for the original reason rather than the added one, and the sweep
would be measuring what it always claimed to.
