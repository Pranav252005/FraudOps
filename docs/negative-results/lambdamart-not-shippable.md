# LambdaMART does not beat the model it would replace

> **SUPERSEDED THE SAME DAY, AND REVERSED.** Removing the confound named at the
> bottom of this entry flipped the result: on the unconfounded pool the
> interval excludes zero at **every** k, and the pre-registration this entry
> reports as holding now **fails**. See
> [`lambdamart-reversal.md`](lambdamart-reversal.md).
>
> This entry is left standing, unedited below this line. It is the record of
> what was believed on the evidence available, and the confound that overturned
> it was stated here before it was measured — which is the only reason the
> reversal was findable. Rule 7: negative results are not deleted when a later
> measurement is kinder, and they are not quietly reworded either.

**Recorded:** 2026-08-31. **Source:** `data/eval_ranker.json` as it stood at
2026-08-31 11:55, retained as `data/eval_ranker.DEADGROUPS.json.bak`.
**Earlier superseded artefact also retained:**
`data/eval_ranker.MIXEDPROVENANCE.json.bak`.

## The pre-registration

`docs/ARCHITECTURE_UPLIFT.md` §8 item 1.3: *"I expect the CI at n=17 cycles to
still include zero."*

(The measurement is actually at **n=18** — `eval_ranker` and `eval_oracle` both
run 18 held-out cycles; the 17 belongs to `eval_phase4`, which splits at a
different tick. The discrepancy is recorded in `docs/inventory/cycles.md` and
does not affect the conclusion.)

## What was measured

Head-to-head, listwise against the pointwise model it would replace:

| k | lambdamart − pointwise | 95% CI | excludes zero? |
|---:|---:|---|---|
| 10 | +0.0389 | [−0.0222, +0.1000] | **no** |
| 20 | +0.0250 | [−0.0056, +0.0583] | **no** |
| 50 | +0.0222 | [+0.0111, +0.0333] | yes |

**The pre-registration holds at k=10 and k=20 and fails at k=50.** The one
CI-clear delta is at the depth where an alert budget matters least. There is no
measured case for shipping the listwise model.

## The confound, since removed

This comparison was made between two models trained on different amounts of
signal: only 16 of 34 training query groups carried pairwise signal, so
LambdaMART learned from 165 of 321 positives while the pointwise classifier saw
all 321. **The comparison was confounded in the pointwise model's favour**,
which makes this null result weaker evidence than it looks, not stronger.

That confound has since been removed — see
[`dead-query-groups.md`](dead-query-groups.md). This entry records the state
before the fix, and is retained rather than rewritten.

## What would reverse this

- The same head-to-head on the unconfounded pool, with the k=10 or k=20
  interval excluding zero. This is now measurable and is the direct successor
  to this entry.
- A shipping argument that turns on k=50 specifically, with a stated alert
  budget that makes depth-50 precision the operative quantity. None has been
  made.
