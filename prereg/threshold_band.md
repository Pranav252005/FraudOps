# Pre-registration — the `is_hit` threshold sensitivity band

**Written 2026-09-04, before `scripts/eval_threshold_band.py` existed.**
Committed before the run, per this project's standing practice: a threshold
chosen after seeing the number is not a threshold, and neither is a band
whose edges were picked once the middle was known.

This is item **M1** in [`docs/EXPERIMENT-QUEUE.md`](../docs/EXPERIMENT-QUEUE.md),
raised by [`docs/graph-review/2026-09-04.md`](../docs/graph-review/2026-09-04.md)
§4a as "the single cheapest credibility win available".

## The problem

`HIT_SHARE = 0.5` and `MIN_JACCARD = 0.3` decide what counts as finding a ring,
and therefore decide **every ring-level number this repository reports**. The
*existence* of a Jaccard floor is well argued and documented: containment alone
let a node-count baseline tie the real score, which is bug #8. The *values* have
never been defended by a curve.

That is an open invitation to the question "did you tune the floor", and this
project will get asked it precisely because it is careful everywhere else.

## What is being measured

A 3x3 grid, evaluated on **one replay and one candidate pool**:

    hit_share   in {0.4, 0.5, 0.6}
    min_jaccard in {0.2, 0.3, 0.4}

with the shipped pair (0.5, 0.3) as the centre cell.

Per cell: p@10 / p@20 / p@50 for `score`, `size`, `degree` and `random`; ring
recall for each; and the **paired** bootstrap CI on `score - size` at k=10 and
k=20, clustered on the cycle.

### Why one replay is enough, and why this experiment is unusually clean

`is_hit` is an **evaluation** function. It does not participate in seeding,
expansion, pruning, suppression or scoring. So all nine cells score the *same*
candidates, produced by the *same* pipeline, in the *same* rank order.

That matters here more than usual. `suppress()` is greedy NMS ordered by score,
so the score decides which candidates exist and every *scorer* A/B is
structurally confounded (review §2b, queued as B3). **M1 is immune to that
confound**, because it changes nothing upstream of the metric. The nine cells
are paired by construction, not by arrangement.

### This is not a re-tune

The shipped thresholds do not move as a result of this. `MIN_JACCARD` stays at
0.3. The 0.2 column exists so a reader can see what a looser floor would have
bought and judge for themselves — publishing that number is the opposite of
lowering the floor to collect it.

## The invariant this run must satisfy, checked before any result is read

Tightening either threshold can only ever remove hits, never add them. So for
both metrics, **p@k and ring recall must be non-increasing in `hit_share` and
non-increasing in `min_jaccard`**, for every ranking, at every k.

This is arithmetic, not a hypothesis. **If it is violated, the harness has a
defect and no number from the run may be reported until it is found.**

## Pre-registered expectations

Stated as directions and ranges before the run, so a comfortable result cannot
be retrofitted into a prediction.

| quantity | prediction |
|---|---|
| p@10 at the loosest cell (0.4, 0.2) | **1.2x - 2.0x** the shipped cell |
| p@10 at the tightest cell (0.6, 0.4) | **0.4x - 0.8x** the shipped cell |
| ring recall | rises monotonically as either threshold loosens |
| `score - size` at k=10, **sign** | **positive in all 9 cells** |
| `score - size` at k=10, **CI excluding zero** | in **at least 7 of 9** cells |
| the shipped cell reproduces `data/eval_phase2.json` | to within floating-point noise; it is the same code path on the same data |

**The absolute p@k is supposed to move across the grid.** A looser threshold
asks an easier question and must yield a bigger number; a band that was flat
would mean the thresholds were inert and therefore not worth having. So
stability of the *number* is not the claim being tested.

**What must be stable is the conclusion**: that the score beats a ranker which
reads no features. That is the only thing the headline actually asserts, and it
is what this grid is built to stress.

## Kill criteria

Three, and each says what happens rather than leaving it to judgement on the
day.

1. **Monotonicity violated** in any ranking at any k. → Harness defect. Stop,
   report nothing from the run, find the bug. This fires on arithmetic, so it
   cannot be argued with.

2. **`score - size` at k=10 does not exclude zero in the shipped cell (0.5,
   0.3).** → The run has failed to reproduce `data/eval_phase2.json`'s stored
   `shipped_score_over_size_delta_at_10`. Stop and reconcile the two before
   reporting a band around a centre that does not match the headline it is
   supposed to be a band around.

3. **`score - size` point estimate is negative in one or more cells.** → Do not
   report the band as reassurance. **The headline is fragile to the threshold
   choice, that is the finding, and it goes at the top of the report rather
   than in a footnote.** Name the cells. This is the outcome I would least like
   and it is the one most worth publishing.

## What I expect the honest bad news to be

The tightest cell. At `hit_share = 0.6, min_jaccard = 0.4` the candidate must be
both a substantial share of the ring and mostly ring, and `leaf2`-pruned
candidates run around 8 nodes against rings of 4-10. I expect p@10 there to be
low enough that the interval on `score - size` widens past zero — which would
make **kill criterion 3 not fire but expectation 5 fail**, and the honest
statement becomes "the conclusion holds across seven or eight of nine cells, and
is underpowered rather than reversed at the tightest".

That is a materially weaker claim than "the result is robust to the threshold",
and if it is what comes back, that weaker sentence is the one that gets written.
