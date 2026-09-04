# Pre-registration — the second seed predicate (S1), its control (S2), and a correction to the premise both rested on

**Written 2026-09-04, before `scripts/eval_seed_arms.py` existed and before any
arm was run.** Items **S1** and **S2** in
[`docs/EXPERIMENT-QUEUE.md`](../docs/EXPERIMENT-QUEUE.md).

## The premise was wrong, and that is recorded before the run rather than after

`docs/graph-review/2026-09-04.md` §2a ranked this experiment first among
generation work on the grounds that:

> the pass-through rule cannot reach BIPARTITE / FAN-OUT / RANDOM / STACK by
> construction. This is the single largest structural recall loss in the
> funnel.

It cited `sentinel/eval/funnel.py`'s docstring, which said those four
typologies "generate 0%".

**The docstring was stale and the claim is false.** `docs/HANDOFF.md` §5b
corrected it on 2026-08-26: the seed rule tests pass-through against an
account's whole position in the window graph, not its role inside one ring, and
AMLworld's background traffic gives nearly every active account both inbound and
outbound edges. The docstring was never updated, so the review read it instead
of the data and repeated a superseded claim. The docstring is corrected in the
same commit as this file.

The measured funnel (`data/funnel.json`, 34 cycles, 259 rings) says:

| typology | seeded | built | ranked |
|---|---:|---:|---:|
| BIPARTITE | **90%** | 16% | 3% |
| FAN-OUT | **83%** | 67% | 31% |
| RANDOM | **85%** | 65% | 27% |
| STACK | **100%** | 30% | 7% |
| **TOTAL** | **89%** | 62% | 22% |

Stage losses: **seeding 11.2 points, build 26.6 points, ranking 39.8 points.**
`largest_loss_stage` in that file reads `"ranking"`.

**So seeding is the smallest of the three losses, not the largest, and S1's
ceiling is bounded at 29 rings** — the 259 seed-reachable minus the 230 seeded.

## Why it is still worth running

Three reasons, and none of them is "the queue said so".

1. **The ceiling is now quantified rather than assumed.** A bounded experiment
   against a known ceiling is cheap evidence; the arms cost ~26 minutes total.
2. **The four-arm design answers a question the funnel cannot**: whether *any*
   criterion for spending extra seeds beats spending them at random. That
   generalises beyond this predicate.
3. **A negative result here is worth publishing**, because "we added the
   obvious second predicate and it bought nothing measurable" is exactly the
   kind of finding this repository exists to record and most projects quietly
   drop.

## The design

Four arms, **one replay**, identical graph state at every cycle, so every
comparison is paired:

| arm | seeds |
|---|---|
| `passthrough` | shipped. Pass-through accounts touched this tick. |
| `passthrough+gargaml` (**S1**) | + top-B non-pass-through by a GARG-AML-style per-node score |
| `passthrough+degree` (**S2**) | + top-B non-pass-through by width alone — the control |
| `passthrough+random` | + B non-pass-through at random — the null |

### The budget, fixed in advance

**B = 0.10 x (number of pass-through seeds), per cycle.** Measured on cycle 36
of the real stream: 15,854 pass-through seeds, 12,711 non-pass-through touched
accounts in the pool, so **B ≈ 1,585** and total seeds rise 15,854 → 17,439.

**Every arm spends exactly B.** This is the review's own kill rule and it is
enforced by a test (`tests/test_seed_predicate.py::test_every_arm_spends_
exactly_the_same_budget`), not by discipline. A rule that reaches more rings by
firing more often has not found a better predicate; it has bought recall with
candidates and destroyed the funnel's meaning. Holding B equal is what makes any
difference between arms attributable to the criterion.

### What the score is, and what it is not

`sentinel/detect/layers.py::node_smurf_score`. Taken from GARG-AML
([arXiv:2506.04292](https://arxiv.org/abs/2506.04292)): the idea of scoring a
node by how closely its own neighbourhood's structure resembles a pure smurfing
pattern, read as blocks, as one interpretable number — and crucially defined for
**every** node, including ones with no pass-through.

**Not taken and not claimed**: the paper's second-order construction, its
normalisation, or its results. Two deliberate deviations are recorded in the
code: participation rates replace pairwise densities (pairwise density decays
quadratically with width and is inert at exactly the widths that matter — a
visibly contaminated hub scored 0.95 against a pure one at 1.00 during design),
and a saturating width term is multiplied in (cleanliness alone is 1.0 for most
nodes in a sparse window and would collapse selection to degree, which is what
S2 already is). Aggregation over the contamination terms is `mean`; `max` was
not tried, and is recorded here so nobody later claims the form was chosen by
measurement.

**No result from this may be quoted as a GARG-AML comparison.** Standing
constraint: no parity claim against a surveyed project enters the repo without a
head-to-head on this machine.

## The measurement that comes first

Before any arm's p@k is read, the run decomposes the **29 unseeded rings** into:

- **untouched** — no member appeared in any tick's batch during a cycle in which
  the ring was active. **No seed rule that draws from `touched` can ever reach
  these, S1 included.**
- **touched but never pass-through** — S1's actual addressable set.

**This bounds S1's ceiling exactly, and it may bound it at zero.** If the 29 are
mostly untouched, then S1 cannot help by construction, and that is the finding —
reported instead of the p@k table, not alongside it as a consolation.

## Pre-registered expectations

Given the corrected premise, these are deliberately low.

| quantity | prediction |
|---|---|
| unseeded rings that are **touched but not pass-through** | **5 – 20** of 29 |
| S1 seeded-recall gain over shipped | **+0 to +8 rings** (0 to +3.1 points) |
| S1 **built** gain | **+0 to +4 rings** |
| S1 **ranked@50** gain | **+0 to +2 rings** |
| S1 p@10 vs shipped, paired CI | **includes zero** |
| S1 vs S2 (the attribution question) | **indistinguishable** — CI includes zero |
| S1 vs random null | S1 ≥ random on seeded-recall; **may still include zero at p@10** |
| size / degree / random re-tie under every arm | score still CI-clear over size at k=10 |

**I expect S1 to fail to separate from S2.** The cleanliness term has low
dynamic range on real sparse neighbourhoods, so selection will be dominated by
the width term — and width alone *is* S2. If that is what comes back, the honest
statement is "the GARG-AML-style term earned nothing over degree at equal
budget", and it goes in the ledger as a refutation.

**I also expect p@10 to move very little in any arm**, because adding 10% more
seeds adds candidates that must then survive suppression and outrank 15,000
others.

## Kill criteria

1. **If the unseeded-ring decomposition shows fewer than 5 rings are
   "touched but not pass-through"**, S1's ceiling is below the noise floor.
   **Stop. Report the ceiling and do not run the arms** — a p@k table computed
   against a ceiling of three rings would be noise dressed as a result.

2. **If any arm's `seeds_extra` differs from another's**, the attribution is
   void. Stop and fix the harness; a test already asserts this, so a failure
   here means the test is wrong too.

3. **If S1 raises seeded-recall but LOWERS ranked-recall**, report that as the
   headline. It would mean the extra candidates displace better ones under
   suppression — a real cost that a seeded-recall-only report would hide. This
   is the outcome I would least like and the one most worth publishing.

4. **If score loses its CI-clear margin over `size` under any arm**, the arm is
   not shippable regardless of what it does to recall. Bug #8's rule, applied to
   a generation change.

## What would reverse the conclusion

A budget large enough to change the answer. B = 10% is a choice; at B = 100% S1
might reach rings it cannot at 10%, at a cost the funnel would have to be
re-read to interpret. **Not testing that here, and not claiming anything about
it** — one budget, pre-registered, measured once.
