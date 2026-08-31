# The centrepiece did not clear its own pre-registered bar

**Recorded:** 2026-08-31. **Full write-up:** `docs/CENTREPIECE-INVALIDATED.md`.
**The verdict was written by the script, not by hand** — the branch is
pre-registered in `scripts/eval_oracle.py` and it selected the
"PLAN-INVALIDATING" arm on its own.

## The pre-registration

`docs/ARCHITECTURE_UPLIFT.md` §8 item 0.1, written before the measurement:

> I expect oracle p@10 to fall somewhat (smaller, tighter pool) but the
> oracle/blend ratio to stay ≥ 2×. **If the ratio collapses below ~1.5×, §1 is
> wrong and should be re-scoped toward features before a week is spent on the
> ranker.**

## What was measured

Clean end-to-end re-run, both arms replayed post-fix, one provenance
throughout (`data/eval_oracle.json`, 2026-08-31 11:47):

| k | supervised | v1 blend | ratio |
|---:|---:|---:|---:|
| 10 | 0.2500 | 0.1889 | **1.32×** |
| 20 | 0.1417 | 0.1000 | **1.42×** |
| 50 | 0.0611 | 0.0467 | **1.31×** |

**Below the 1.5× kill line, against a pre-registration that expected ≥ 2×.**

## Why the gap closed

Not because the oracle got worse — it is unchanged. Commit `a0cbbec` retired
two hand-set blend terms that were measured to be pointing the wrong way, and
**the floor rose**: blend p@10 went 0.0500 → 0.1889. The "5.33× headroom" the
centrepiece rested on was largely a measurement of two backwards weights.

The perfect-seeding arm says the same thing from the other side. With seeding
cheated, the ratio is 1.18× / 1.13× / 1.22× and the k=20 interval includes
zero. The same blend gains ~2.2× at k=10 from the seed cheat alone
(0.1889 → 0.4111) versus 1.32× from replacing the scorer with a true-label
model.

**Two independent repairs each erase the headroom. That is one fact seen twice:
the scorer was never the binding constraint.**

## What survives

The supervised re-ranker still beats the blend with intervals excluding zero at
every k — but by +0.0611 [+0.0111, +0.1167] at k=10, not by the 2× the plan was
built on. A real gain, and a small one.

## What would reverse this

- A pool on which the oracle/blend ratio returns to ≥ 2× **without**
  reintroducing the two inverted blend weights. The ratio is a fraction whose
  denominator was wrong; a change that only moves the denominator back is not
  a reversal.
- Evidence that the post-prune candidate set the ratio was measured on is
  itself defective, such that both arms are mismeasured in the same direction.
  The candidate-set staleness class that `data/eval_ranker.MIXEDPROVENANCE.json.bak`
  exposed is exactly this shape, so it is a live possibility rather than a
  hypothetical.
- Note that re-running the ratio at higher `n` is **not** a reversal condition.
  The kill rule was stated on the point estimate and the point estimate is far
  from the boundary (1.31–1.42 against 1.5).
