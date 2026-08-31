# The centrepiece does not clear its own pre-registered bar

**Date:** 2026-08-31. **Status:** plan-invalidating, by a rule written before
the measurement.

## The one-line version

`docs/ARCHITECTURE_UPLIFT.md` §8 item **0.1** pre-registered a kill rule:

> I expect oracle p@10 to fall somewhat (smaller, tighter pool) but the
> oracle/blend ratio to stay ≥ 2×. **If the ratio collapses below ~1.5×, §1 is
> wrong and should be re-scoped toward features before a week is spent on the
> ranker.**

Measured, post-blend-fix, on one file and one split:

| k | supervised | v1 blend | ratio |
|---:|---:|---:|---:|
| 10 | 0.2778 | 0.1889 | **1.47×** |
| 20 | 0.1500 | 0.1000 | **1.50×** |
| 50 | 0.0689 | 0.0467 | **1.48×** |

**The ratio is at the kill line, not above it. "The scorer is the bottleneck"
does not survive.** Re-scope toward features and toward sample size (item 0.5),
not toward a ranker rewrite.

## What changed, and why it was not the oracle

Nothing about the oracle moved. Commit `a0cbbec` retired two hand-set blend
terms (`gargaml`, `stack`) that were measured to be pointing the wrong way.
That commit touched **weights only** — `_V1_WEIGHTS` and the renormalisation —
and changed no feature computation. So:

- the supervised row is **unchanged to every digit**: 0.2778 / 0.1500 / 0.0689
  before and after;
- `size`, `degree` and `random` are unchanged, as they must be — they do not
  read features;
- **only the blend row moved**, 0.0500 → 0.1889 at k=10.

The gap did not close because the ceiling fell. It closed because **the floor
was raised by deleting two terms.** The "5.33× headroom" that the centrepiece
rested on was, to a first approximation, a measurement of two inverted weights.

## The two stored files now hard-contradict, and §3 asserts they agree

`docs/HANDOFF.md` §3 states the two independent fits agree "**exact, to every
digit**". That is now false, and not by a rounding hair:

| | `eval_oracle.json` (29 Aug, pre-fix) | `eval_ranker.json` (31 Aug, post-fix) |
|---|---|---|
| blend p@10 | 0.0500 | 0.1889 |
| blend p@10 95% CI | [0.0222, 0.0778] | [0.0833, 0.3000] |
| supervised − blend @10 | +0.2278 [+0.1167, +0.3500] | +0.0889 [+0.0333, +0.1500] |

**The two blend intervals are disjoint.** They cannot both describe the same
quantity on the same 18 cycles, and they do not: one predates `a0cbbec`.

This is the **exact failure mode HANDOFF §3 had just finished diagnosing**, one
section earlier, about a different commit:

> a stored result is only as current as the last commit that touched the code
> producing it. A commit that changes a feature, a threshold or a split
> invalidates every stored metric downstream of it, whether or not the commit
> author re-ran the thing.

`a0cbbec` changed the blend. It did not re-run `scripts/eval_oracle.py`. The
lesson was written down and then immediately re-incurred — which is worth more
as evidence about process than the number is as evidence about the scorer.

## The verdict flips on one ULP, and that must be said out loud

`scripts/eval_oracle.py` decides its own branch on `max(ratio@10, ratio@20)`
against the literal `1.5`. In IEEE double, `0.15 / 0.1 == 1.4999999999999998` —
**below 1.5 by one unit in the last place.** The stored interpretation
therefore reads "PLAN-INVALIDATING" rather than "RESULT, but a modest one" on a
floating-point artefact.

The branch is knife-edge; **the decision is not.** k=10 (1.4706) and k=50
(1.4762) are below 1.5 by margins no rounding rule touches, and even the
generous reading — call k=20 exactly 1.50 — puts the ratio *at* the bar rather
than above it, against a pre-registration that expected ≥ 2×. The conclusion is
the same under either rounding. Recorded because a result that depends on the
last bit of a float is a result that has to disclose it.

## What survives

- The supervised re-ranker still beats the blend with intervals excluding zero
  at every k (+0.0889 / +0.0500 / +0.0222). **It is a real gain and a small
  one**, not the 2× the plan was built on.
- The blend now beats node count with CI-clear margins at k=10/20/50
  (`docs/SCORE-VS-SIZE-FINDINGS.md`).
- Nothing here touches the label tax, which applies on top of all of it: these
  are true-label numbers and no deployment has them.

## What this does not license

It does not license "the features are fine". The ceiling arm below says
otherwise, and points somewhere else entirely.

## The perfect-seeding arm says the bottleneck is SEEDING

Run 2 of `scripts/eval_oracle.py` cheats: candidates are generated with a seed
rule that also fires on every active ring's own members. It is a ceiling
diagnostic, never a result. Its pre-blend-fix numbers:

| k | supervised | blend | ratio |
|---:|---:|---:|---:|
| 10 | 0.3833 | 0.2500 | 1.53× |
| 20 | 0.2639 | 0.1667 | 1.58× |
| 50 | 0.1389 | 0.0889 | 1.56× |

Read the two arms together, because the comparison is the finding:

- **as-is seeding:** supervised 0.2778, blend 0.0500 (pre-fix) → ratio 5.56×
- **perfect seeding:** supervised 0.3833, blend 0.2500 (pre-fix) → ratio 1.53×

**The scorer gap was ~5.6× when seeding was real and ~1.5× when seeding was
perfect — on the same features, the same model, the same harness.** A gap that
mostly evaporates when you fix a *different* stage was never a measurement of
that stage. Most of what looked like "the hand-set scorer is leaving signal on
the table" was the hand-set scorer being handed a candidate pool that does not
contain the rings.

Both arms now converge on the same verdict from opposite directions:

- fix the blend's inverted weights → as-is ratio falls 5.56× → 1.47×;
- fix the seeding instead → ratio falls 5.56× → 1.53×.

Either repair alone collapses the headroom. That is not two coincidences; it is
the same fact seen twice — **the scorer was never the binding constraint.**

## And that is awkward, because §5b forbids the indicated fix

The obvious reading — go widen seeding — is the change `docs/HANDOFF.md` §5b
explicitly rules out, and §5c ruled out all three expansion knobs by experiment.
So this does **not** resolve to "go do seeding". It resolves to:

1. the ranker rewrite is off (item 0.1's own rule);
2. seeding is where the loss is, but the three knobs already tried do not move
   it, so it needs a *different* idea rather than more of the same one;
3. **item 0.5 — more independent evaluation cycles — is the real blocker**, and
   the plan already said so: *"The scorer is the bottleneck on performance;
   sample size is the bottleneck on knowing anything."* On this evidence the
   first clause is wrong and the second is the one that matters.
