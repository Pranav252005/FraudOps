# The centrepiece does not clear its own pre-registered bar

**Date:** 2026-08-31. **Status:** plan-invalidating, by a rule written before
the measurement. **The verdict was written by the script, not by hand** — the
branch is pre-registered in `scripts/eval_oracle.py` and it selected the
"PLAN-INVALIDATING" arm on its own.

## The one-line version

`docs/ARCHITECTURE_UPLIFT.md` §8 item **0.1** pre-registered a kill rule:

> I expect oracle p@10 to fall somewhat (smaller, tighter pool) but the
> oracle/blend ratio to stay ≥ 2×. **If the ratio collapses below ~1.5×, §1 is
> wrong and should be re-scoped toward features before a week is spent on the
> ranker.**

Measured on a clean end-to-end re-run of `scripts/eval_oracle.py`, both arms
replayed post-fix, one provenance throughout:

| k | supervised | v1 blend | ratio |
|---:|---:|---:|---:|
| 10 | 0.2500 | 0.1889 | **1.32×** |
| 20 | 0.1417 | 0.1000 | **1.42×** |
| 50 | 0.0611 | 0.0467 | **1.31×** |

**Well below the 1.5× kill line, against a pre-registration that expected ≥ 2×.
"The scorer is the bottleneck" does not survive.**

## What changed, and why it is not the oracle getting worse

Commit `a0cbbec` retired two hand-set blend terms (`gargaml`, `stack`) that
were measured to be pointing the wrong way. **The gap closed because the floor
rose, not because the ceiling fell.** The blend went 0.0500 → 0.1889 at k=10;
the supervised re-ranker did not improve at all. The "5.33× headroom" the
centrepiece rested on was, to a large extent, a measurement of two backwards
weights.

The blend now also clears node count on the held-out cycles, which it did not
before — `blend − size` was previously reported as including zero at every k
(exactly +0.0000 at k=20). Post-fix:

| k | blend − size | 95% CI |
|---:|---:|---|
| 10 | +0.1444 | [+0.0667, +0.2389] |
| 20 | +0.0556 | [+0.0139, +0.1000] |
| 50 | +0.0222 | [+0.0078, +0.0389] |

All three exclude zero.

## The number that was nearly published was mixed-provenance

An earlier draft of this document quoted **1.47× / 1.50× / 1.48×**, taken from
`data/eval_ranker.json`. That file is **not one experiment**, and how it broke
is worth more than the number was.

`scripts/eval_ranker.py --use-cache` reads `data/ranker_pool.npz`. That pool's
**candidate set is pre-fix** — its row counts match the pre-fix oracle exactly
(169,947 train / 176,576 test / 164 positive), where a clean post-fix replay
gives 169,970 / 176,584 / 163. But its **`test_blend` column is post-fix**,
because `scripts/compile_corpus.py --rescore` regenerates the stored blend from
the stored features *and explicitly rescores the pool as well*.

So the file pairs a post-fix denominator with a pre-fix numerator and candidate
set. The tell is that `size` and `degree` differ between the two runs (0.0333 →
0.0444 and 0.0167 → 0.0222): **baselines that read no features at all can only
move if the candidate set moved.**

**`a0cbbec`'s own commit message predicted this exact failure**, in these words:

> `verify_scoring` cannot see it either, since rescoring makes the stored blend
> agree with today's code while leaving the candidate set stale.

The mechanism is `suppress()`: greedy non-maximum suppression **ordered by
score**, so the score decides which of several overlapping views of a
neighbourhood survives to be ranked at all. The score is not only a ranking
function — it participates in generation. Rescoring therefore *cannot* repair a
pool; it can only make a stale pool look internally consistent. The rescore
command is not wrong, but it is structurally incapable of detecting the
staleness class it is most likely to be reached for.

**Both provenances put the ratio below 1.5×** (1.32–1.42 clean, 1.47–1.50
mixed), so the verdict is robust to this. The headline is the clean one.

### One ULP, disclosed

On the mixed-provenance numbers the pre-registered branch turned on
`max(1.4706, 1.4999999999999998) >= 1.5` — `0.15 / 0.1` sits below `1.5` by one
unit in the last place in IEEE double. The clean numbers are nowhere near that
boundary (1.32 / 1.42 / 1.31), so this is a historical note rather than a live
fragility. Recorded because a verdict that *had* depended on the last bit of a
float has to say so.

## What survives

- The supervised re-ranker still beats the blend with intervals excluding zero
  at every k: **+0.0611 [+0.0111, +0.1167]**, **+0.0417 [+0.0139, +0.0778]**,
  **+0.0144 [+0.0033, +0.0267]**. **A real gain, and a small one** — not the 2×
  the plan was built on.
- These are **true-label** numbers. The label tax applies on top of all of it
  and is still an unmeasured hypothesis, not a coefficient.

## The perfect-seeding arm: the bottleneck is SEEDING, and always was

Run 2 cheats — candidates are generated with a seed rule that also fires on
every active ring's own members. Ceiling diagnostic, never a result. Post-fix:

| k | supervised | blend | ratio | oracle − blend |
|---:|---:|---:|---:|---|
| 10 | 0.4833 | 0.4111 | 1.18× | +0.0722 [+0.0167, +0.1278] |
| 20 | 0.3278 | 0.2889 | 1.13× | +0.0389 **[−0.0083, +0.0944] includes zero** |
| 50 | 0.1644 | 0.1344 | 1.22× | +0.0300 [+0.0067, +0.0578] |

**With seeding fixed, the supervised model barely beats the hand-set blend at
all, and at k=20 the interval includes zero.** Whatever headroom the ranker
rewrite was supposed to unlock is not there once the candidate pool actually
contains the rings.

Now compare the *blend against itself* across the two arms — same weights, same
scorer, same harness, only the seed rule differs:

| | blend p@10 | blend p@20 | blend p@50 |
|---|---:|---:|---:|
| as-is seeding | 0.1889 | 0.1000 | 0.0467 |
| perfect seeding | **0.4111** | **0.2889** | **0.1344** |

**Fixing seeding is worth ~2.2× at k=10 to the shipped scorer. Fixing the
scorer is worth 1.32×.** The larger prize is not in the component the plan
named, and the two arms converge on that from opposite directions:

- fix the weights → the as-is ratio collapses from 5.56× to 1.32×;
- fix the seeding instead → the ratio collapses to 1.18×.

Two independent repairs each erase the headroom. That is one fact seen twice:
**the scorer was never the binding constraint.**

## And the indicated fix is the one §5b forbids

The obvious reading — go widen seeding — is exactly what `docs/HANDOFF.md` §5b
rules out, and §5c ruled out all three expansion knobs by experiment. §5b also
measured seeding at **89%** of active rings, which is hard to reconcile with a
2.2× prize sitting behind the seed rule.

**Those two findings are in tension, and the tension is unresolved.** Most
likely the 89% measures something weaker than what run 2's cheat supplies —
"the ring was seeded at all" is not "the ring was seeded with a member set the
builder can grow into the ring" — in which case the loss is at *build*, not at
seed selection, and §5b/§5c are still right that widening the seed triggers is
the wrong knob. But that is a hypothesis. It is also cheap to settle: run 2
already generates both pools, so diffing which rings the cheat rescues is a read
of data that exists.

> **RESOLVED 2026-09-01, and both clauses of "cheap to settle / a read of data
> that exists" were wrong.** Run 2's pools are never persisted — `collect_pool`
> returns them in memory and only per-cycle aggregates reach
> `data/eval_oracle.json`, so three of the four fields the partition needs were
> computed and discarded. It took a **1,192-second replay**
> (`scripts/eval_seed_cheat_diff.py`), not a read.
>
> **The hypothesis stated above is confirmed and the mechanism is named: the
> ring's own induced subgraph is disconnected inside the 72-hour window, and
> the honest seed lands in one fragment of it.** Over 259 in-window rings,
> 0.510 of the rings the cheat rescues are split across two or more components
> against 0.057 of the rings recovered honestly. The builder-budget hypothesis
> is refuted and fails backwards: relaxing every knob raises containment and
> collapses coverage, symmetrically on both sets.
>
> The prize also has an interval now — blend 2.18x [1.62x, 3.50x] at k=10
> against a scorer ratio of 1.12x — so "seeding is worth more than the scorer"
> is no longer two point estimates compared by eye.
>
> Full account: [`PHASE2-SEED-CHEAT-FINDINGS.md`](PHASE2-SEED-CHEAT-FINDINGS.md).
> What it indicates is in [`NEXT_PHASE_PLAN.md`](NEXT_PHASE_PLAN.md) §2.1.

So this does **not** resolve to "go widen seeding". It resolves to:

1. the ranker rewrite is **off**, by item 0.1's own rule;
2. the loss is at seeding/build, but the knobs already tried do not move it —
   it needs a different idea, and the §5b/run-2 tension resolved first;
3. **item 0.5 — more independent evaluation cycles — is the live top item.**
   The plan's own line was *"the scorer is the bottleneck on performance;
   sample size is the bottleneck on knowing anything."* On this evidence the
   first clause is false and the second is the one that matters.

## LambdaMART, re-measured on the clean pool

`scripts/eval_ranker.py` was re-run end to end (pool regenerated post-fix, no
cache), so these supersede `data/eval_ranker.MIXEDPROVENANCE.json.bak`. The
pointwise arm reproduces the oracle exactly — **0.2500 / 0.1417 / 0.0611 in both
files, from two separate harnesses** — which is the cross-check that makes the
rest quotable.

| ranking | p@10 | p@20 | p@50 |
|---|---:|---:|---:|
| lambdamart | **0.2889** | **0.1667** | **0.0833** |
| pointwise | 0.2500 | 0.1417 | 0.0611 |
| blend | 0.1889 | 0.1000 | 0.0467 |
| size | 0.0444 | 0.0444 | 0.0244 |
| degree | 0.0222 | 0.0306 | 0.0222 |
| random | 0.0000 | 0.0000 | 0.0000 |
| best single feature | 0.0722 | 0.0417 | 0.0211 |

**Head-to-head, listwise vs the pointwise model it would replace** — the
comparison item 1.3 actually turns on:

| k | lambdamart − pointwise | 95% CI | excludes zero? |
|---:|---:|---|---|
| 10 | +0.0389 | [−0.0222, +0.1000] | **no** |
| 20 | +0.0250 | [−0.0056, +0.0583] | **no** |
| 50 | +0.0222 | [+0.0111, +0.0333] | yes |

**The pre-registration in §8 item 1.3 — "I expect the CI at n=17 cycles to still
include zero" — HOLDS at k=10 and k=20 and fails at k=50.** The point estimates
moved up on the clean pool (LambdaMART now leads at every k, where before it
trailed at k=10), but the intervals at the depths that matter still include
zero. **There is still no measured case for shipping the listwise model.** The
one CI-clear delta remains at k=50, the depth where an alert budget matters
least.

The confound is unchanged and is stated in the run's own output: only 16 of 34
training query groups carry pairwise signal, so LambdaMART learns from 165 of
321 positives while the pointwise classifier sees all 321. **The comparison is
confounded in the pointwise model's favour**, which makes a null result here
weaker evidence than it looks, not stronger.

**Re-tie check against node count** — `pointwise`, `lambdamart`,
`pointwise_intensive`, `lambdamart_intensive` and `blend` all come back
**SHIPPABLE**; `best1` (best single feature) does not, its CI including zero at
k=10 or k=20. Distinct-ring p@k is reported alongside and is lower for every
ranking, as it must be — the blend loses the most to duplicate candidates for
one ring (0.0500 at k=10 against 0.0278 for LambdaMART).

## Provenance of every number here

`data/eval_oracle.json`, written 2026-08-31 by an end-to-end re-run of
`scripts/eval_oracle.py` (no cache, both arms replayed). Log:
`data/eval_oracle_postblendfix.log`; a copy of the result is kept at
`data/eval_oracle_postblendfix.json`. The superseded pre-fix file is kept as
`data/eval_oracle.PREBLENDFIX.json.bak` and the mixed-provenance ranker file as
`data/eval_ranker.MIXEDPROVENANCE.json.bak` — in both cases the stale artefact
is the evidence for the finding, so it is retained rather than deleted.
