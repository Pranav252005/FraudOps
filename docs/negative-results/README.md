# Negative results

Results that did not go the way the plan expected, recorded where a reader
will hit them.

**Standing rule 7: this directory is append-only.** Nothing here is deleted,
truncated, or quietly reworded when a later measurement is kinder.
`tests/test_standing_rules.py::TestRule7NegativeResultsAreAppendOnly` reads the
git history of this directory and fails the build if a file has ever been
removed.

The rule exists because the cheapest way to make a project look successful is
to stop recording the things that did not work — and because several of the
strongest findings in this repository are negative ones. The centrepiece of the
uplift plan was killed by its own pre-registered rule; that is the single most
defensible thing here, and it is only defensible because it was written down.

## What belongs here

- A measurement that came back null, or came back against the hypothesis.
- A pre-registered rule that fired.
- A claim withdrawn because it could not be supported.
- A defect in a measurement that invalidated numbers already written down.

## What each entry must contain

Every entry states, in a section headed exactly **"What would reverse this"**,
the measurement that would overturn it. This is checked by
`tests/test_standing_rules.py::...::test_every_recorded_negative_names_what_would_reverse_it`.

A negative result without a reversal condition is an opinion. With one, it is a
measurement someone can argue with.

## Index

| entry | what it records |
|---|---|
| [`centrepiece-invalidated.md`](centrepiece-invalidated.md) | The oracle/blend ratio missed its pre-registered ≥2× bar and fell below the 1.5× kill line. The ranker rewrite is off. |
| [`lambdamart-not-shippable.md`](lambdamart-not-shippable.md) | LambdaMART does not beat the pointwise model it would replace at the depths that matter. **Superseded and reversed the same day — kept, not deleted.** |
| [`lambdamart-reversal.md`](lambdamart-reversal.md) | Removing the training confound flipped that verdict at every k — and cost the supervised model its CI-clear lead over the hand-set blend at k=10 and k=20. |
| [`dead-query-groups.md`](dead-query-groups.md) | 18 of 34 training query groups were all-positive; the listwise-vs-pointwise comparison was confounded, and the fix costs 156 positives. |
| [`analyst-pool-mismatch.md`](analyst-pool-mismatch.md) | The label-tax experiment four files call "cheap and unrun" is **ill-posed**: applying per-case analyst rates to a 170k-candidate pool makes 85% of the positive labels synthetic. |
| [`label-noise-non-monotone.md`](label-noise-non-monotone.md) | p@10 rises before it falls in the noise arm. Recorded, bounded, and explicitly not presented as "a little noise helps". |
| [`builder-budget-refuted.md`](builder-budget-refuted.md) | Relaxing every expansion knob makes ring coverage worse, not better — on exactly the rings where a budget increase would have had to work. |
| [`gfp-parity-unmeasured.md`](gfp-parity-unmeasured.md) | Every "feature parity with IBM's GFP" claim was struck. It was never measured and cannot be measured on this machine. |
| [`inert-seed-sweep.md`](inert-seed-sweep.md) | A five-seed stability sweep was one fit reported five times. |
| [`median-amount-features.md`](median-amount-features.md) | Closing a GFP coverage gap did not help and sometimes hurt. |
| [`elliptic2-cancelled.md`](elliptic2-cancelled.md) | The second-dataset expansion was cancelled on a schema fact; the only Elliptic2 numbers in the repo come from a 10-node fixture. |

## Entries still held only in prose

These are recorded, but in long documents rather than here, and should be
migrated as they are next touched. Listed so the gap is visible rather than
implied:

- `docs/HANDOFF.md` §5e — the p@50 "size beats score" claim did not survive its
  own confidence interval.
- `docs/HANDOFF.md` §5c — all three candidate-expansion knobs ruled out by
  experiment.
- `docs/HANDOFF.md` §5g — three follow-up measurements, all negative.
- `docs/SCORE-VS-SIZE-FINDINGS.md` — the blend did not clear node count at any
  k before the inverted weights were retired.
- `docs/HANDOFF.md` §7 — the distributed-computing idea, verdict: don't build it.
