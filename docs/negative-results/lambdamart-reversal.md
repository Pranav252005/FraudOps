# Removing the training confound reversed the LambdaMART verdict — and cost the pointwise model its lead over the blend

**Recorded:** 2026-08-31. **Source:** `data/eval_ranker.json`, re-run end to
end with no cache after the dead-query-group fix. Log:
`data/rerun_deadgroupfix.log`. The superseded file is retained as
`data/eval_ranker.DEADGROUPS.json.bak`.

**This entry records a reversal, not a success.** Two things moved, one in the
direction the plan wanted and one against it, and the second is the more
important of the two.

## Why this is filed under negative results

A pre-registration failed. `docs/ARCHITECTURE_UPLIFT.md` §8 item 1.3 predicted
the listwise-vs-pointwise interval would still include zero; it no longer does
at any k. And separately, a claim this repository has been quoting — that the
supervised re-ranker beats the shipped hand-set blend with intervals excluding
zero at every k — **is no longer true at k=10 or k=20**.

Filing a reversal that includes a gain here rather than in the headline is
deliberate. The gain is real; so is the retraction that came with it, and the
two were produced by the same measurement.

## What changed in the setup

Nothing about the models, the features, the split point, or the held-out
cycles. **Only what train contained.** See
[`dead-query-groups.md`](dead-query-groups.md).

| | before | after |
|---|---:|---:|
| training query groups | 34 | **16** |
| all-positive (zero-gradient) groups | 18 | **0** |
| training positives | 321 | **165** |
| positives LambdaMART could learn from | 165 of 321 | **165 of 165** |
| training rows | 169,970 | 169,814 |
| **test rows / positives** | **176,584 / 163** | **176,584 / 163** |
| held-out cycles | 18 | 18 |

**The test set is byte-identical.** The check that this is true rather than
merely intended: `blend`, `size`, `degree` and `best1` read nothing the change
touched, and all four reproduce to four decimal places (0.1889 / 0.0444 /
0.0222 / 0.0722 at k=10). A baseline that ignores training cannot move unless
the evaluation moved.

## Result 1 — the pre-registration fails

LambdaMART − pointwise, the comparison item 1.3 turns on:

| k | before | after | |
|---:|---|---|---|
| 10 | +0.0389 [−0.0222, +0.1000] | **+0.0667 [+0.0278, +0.1111]** | includes zero → **excludes** |
| 20 | +0.0250 [−0.0056, +0.0583] | **+0.0389 [+0.0167, +0.0667]** | includes zero → **excludes** |
| 50 | +0.0222 [+0.0111, +0.0333] | +0.0167 [+0.0078, +0.0256] | excludes → excludes |

**The pre-registered expectation now fails at every k, where before it held at
k=10 and k=20.**

The mechanism is the one that was written down before it was measured: the
confound ran in the *pointwise* model's favour, so removing it moved the
pointwise model and not LambdaMART. Point estimates confirm exactly that —
pointwise p@10 falls 0.2500 → 0.2111 while LambdaMART barely moves,
0.2889 → 0.2778.

## Result 2 — and the supervised model loses its lead over the blend

Pointwise − blend, on the same cycles:

| k | before | after | |
|---:|---|---|---|
| 10 | +0.0611 [+0.0111, +0.1167] | **+0.0222 [−0.0333, +0.0889]** | **now includes zero** |
| 20 | +0.0417 [+0.0139, +0.0778] | **+0.0278 [−0.0083, +0.0667]** | **now includes zero** |
| 50 | +0.0144 [+0.0033, +0.0267] | +0.0156 [+0.0022, +0.0311] | still excludes |

`docs/CENTREPIECE-INVALIDATED.md` states under "What survives": *"The supervised
re-ranker still beats the blend with intervals excluding zero at every k."*
**On the unconfounded pool that is false at k=10 and k=20.** It survives only at
k=50, the depth where an alert budget matters least — the same depth that
document already dismisses when the result ran the other way.

Two ship verdicts also flipped: `pointwise_intensive@20` and
`pointwise_intensive@50`, both True → False.

## What this does and does not license

It does **not** license shipping LambdaMART. Three reasons, and the first is
sufficient on its own:

1. **The gain was bought by deleting 156 training positives.** The honest
   description is "LambdaMART degrades less than the pointwise model when both
   are trained on 165 positives", not "LambdaMART is better". Both absolute
   numbers fell.
2. These are **true-label** numbers throughout. The label tax applies on top and
   is still an unmeasured hypothesis.
3. `n` is 18 cycles. The intervals are narrow relative to the deltas but the
   deltas are small in absolute terms.

What it does establish is that the confound was **load-bearing**, not cosmetic.
A confound that was stated honestly in the output for weeks was still changing
the conclusion the whole time.

## What would reverse this

- A demonstration that the 156 dropped positives are legitimately usable by
  both objectives — i.e. that all-positive groups do contribute gradient under
  this LightGBM version. That would make the pre-fix numbers the correct ones
  and this reversal an artefact.
- The same head-to-head at materially larger `n`, with the k=10 or k=20
  interval returning to include zero.
- A split rule that recovers the 156 positives without leaking ring identity or
  changing the held-out denominator, on which the pointwise model regains its
  CI-clear lead over the blend. None is known.
