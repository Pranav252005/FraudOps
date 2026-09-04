# S1/S2 — the second seed predicate is degree burst wearing a costume

**Pre-registered in [`prereg/seed_predicate.md`](../prereg/seed_predicate.md)**
before the harness existed, including the correction to the premise the queue
had ranked the experiment on. Run 2026-09-04, 34 cycles, 259 rings, 1,568 s,
`scripts/eval_seed_arms.py` → `data/eval_seed_arms.json`. Cycle-clustered
paired bootstrap.

## Headline

**S1 and S2 produced bit-identical output at every k.** The GARG-AML-style
cleanliness term earned exactly nothing over ranking by degree — not
"indistinguishable within noise", *identical*. The mechanism is measured, not
guessed, and it is in §4.

**S1 raised built-recall by 14 rings and ranked-recall by zero.** It moves a
middle-of-funnel number and delivers nothing at the output.

**Recommendation: do not ship any arm.** §6.

## 1. The premise was wrong, and it was corrected before the run

The queue ranked this first among generation work because
`docs/graph-review/2026-09-04.md` §2a called it "the single largest structural
recall loss in the funnel", citing `sentinel/eval/funnel.py`'s docstring:
BIPARTITE / FAN-OUT / RANDOM / STACK "generate 0%".

**That docstring was stale.** `docs/HANDOFF.md` §5b corrected it on 2026-08-26;
the docstring was never updated, and the review read the docstring instead of
the data. Seeding is the *smallest* of the three funnel losses — 11.2 points
against 26.6 at build and 39.8 at ranking. The docstring now carries the
correction inline.

## 2. The ceiling, measured before any arm was read

Kill criterion 1 required this first, because a p@k table computed against a
ceiling of three rings is noise dressed as a result.

| | rings |
|---|---:|
| seed-reachable | 259 |
| seeded by the pass-through rule | 230 |
| **unseeded** | **29** |
| — never touched in any cycle while active | **22** |
| — touched but never pass-through | **7** |

**22 of the 29 are unreachable by any seed rule that draws from the accounts
touched in a tick — S1 included.** They are not a pass-through problem at all;
no member of those rings appears in a batch during a cycle in which the ring is
active.

**S1's entire addressable set was 7 rings** (CYCLE 1, FAN-IN 1, FAN-OUT 3,
SCATTER-GATHER 2) — 2.7% of the population. Predicted 5–20; observed 7, at the
bottom of the range. Kill criterion 1 (fire below 5) **did not fire, barely.**

## 3. The arms

Budget B = 0.10 x pass-through seeds. **Every arm spent exactly 35,543 extra
seeds** — kill criterion 2 did not fire.

| arm | seeds | extra | seeded | built | ranked@50 | p@10 | p@20 | p@50 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `passthrough` (shipped) | 355,577 | 0 | 230 | 161 | **58** | 0.2912 | 0.1574 | 0.0759 |
| `passthrough+gargaml` (S1) | 391,120 | 35,543 | 234 | **175** | **58** | 0.2882 | 0.1632 | 0.0776 |
| `passthrough+degree` (S2) | 391,120 | 35,543 | 234 | **175** | **58** | 0.2882 | 0.1632 | 0.0776 |
| `passthrough+random` (null) | 391,120 | 35,543 | 231 | 165 | **58** | 0.2912 | 0.1574 | 0.0759 |

Paired deltas against shipped, cycle-clustered:

| | k=10 | k=20 | k=50 |
|---|---|---|---|
| S1 − shipped | −0.0029 [−0.015, +0.006] | **+0.0059 [+0.001, +0.012]** | +0.0018 [+0.000, +0.004] |
| S1 − S2 | **+0.0000 [+0.000, +0.000]** | **+0.0000** | **+0.0000** |
| random − shipped | +0.0000 | +0.0000 | +0.0000 |

Re-tie check — `score − size` at k=10, under every arm:

| arm | delta | 95% CI | |
|---|---:|---|---|
| shipped | +0.2029 | [+0.1353, +0.2676] | clear |
| S1 / S2 | +0.2735 | [+0.2088, +0.3412] | clear |
| random | +0.2382 | [+0.1706, +0.3059] | clear |

**The score keeps a CI-clear margin over the size baseline in all four arms**,
and the margin widens rather than narrows. Kill criterion 4 did not fire.

## 4. Why S1 and S2 are identical — the mechanism, measured

`node_smurf_score` is `cleanliness x width`, where cleanliness is one minus the
mean participation across the block relations a pure pattern leaves empty.

Measured over the real non-pass-through pool at cycle 36 (12,711 accounts):

- **the cleanliness factor is exactly 1.0 for 98.6% of the pool**, mean 0.9984;
- only **83 accounts** score a saturated 1.0 overall, against a budget of
  **1,585**;
- the score distribution is the width ladder and nothing else — 51.8% at 0.1,
  35.2% at 0.2, 7.5% at 0.3.

So on a sparse window graph almost every neighbourhood *is* clean: the senders
do not pay each other, the receivers do not pay each other, nobody bypasses the
hub. The cleanliness term is not weak, it is **inert**, and `score` collapses to
a function of degree — after which the `-width_raw` tiebreak makes the top-B
selection *exactly* degree ordering.

**This was pre-registered.** The prereg says: "I expect S1 to fail to separate
from S2. The cleanliness term has low dynamic range on real sparse
neighbourhoods, so selection will be dominated by the width term — and width
alone *is* S2." The prediction was right and the outcome is stronger than
predicted, because the two arms did not merely fail to separate, they coincided
exactly.

**This is a refutation of the S1 idea as a distinct predicate, not of the
implementation.** A different functional form might discriminate. Nothing here
says GARG-AML does not work — the published method uses a second-order
construction this does not implement, and **no result here may be read as a
GARG-AML comparison**; the head-to-head remains unrun (queue item X1).

## 5. Built rose, ranked did not

Built-recall by typology:

| typology | shipped | S1 / S2 | random |
|---|---:|---:|---:|
| BIPARTITE | 5 | **5** | 6 |
| CYCLE | 28 | 28 | 28 |
| **FAN-IN** | 21 | **26** | 21 |
| **FAN-OUT** | 24 | **29** | 26 |
| GATHER-SCATTER | 30 | 32 | 30 |
| RANDOM | 17 | 17 | 17 |
| SCATTER-GATHER | 27 | 29 | 28 |
| STACK | 9 | **9** | 9 |
| **TOTAL** | **161** | **175** | **165** |

Three things worth reading off this.

**The gain is attributable.** S1/S2 buys +14 built against the null's +4 at the
same spend, so roughly **+10 rings are down to the criterion rather than to
pool growth**. The criterion, per §4, is degree.

**The gain is not where the build problem is.** BIPARTITE (16% built) and STACK
(30% built) are the two typologies the funnel calls "build-destroyed", and they
gained **nothing** — 5→5 and 9→9. What gained is FAN-IN and FAN-OUT, which is
exactly what a degree-burst predicate should find. The experiment improved the
typologies that were already fine.

**+4 seeded produced +14 built**, which is not a contradiction: extra seeds also
produce extra candidates *around already-seeded rings*, and some of those cover
rings the pass-through candidates missed. So most of the built gain is not from
newly-reachable rings at all.

**And ranked@50 is 58 in all four arms.** Every one of the 14 extra built rings
failed to reach the top 50. The output of the system did not change.

Kill criterion 3 was written for "raises seeded-recall but LOWERS
ranked-recall". Ranked did not fall, so it did not fire — but the spirit of it
is the finding: **a middle-of-funnel gain that does not reach the output is not
a product improvement**, and reporting the +14 without the +0 would be the
misleading half of a true statement.

## 6. Against the pre-registration, and the recommendation

| predicted | observed | |
|---|---|---|
| addressable rings 5–20 | 7 | hit |
| S1 seeded gain +0 to +8 | +4 | hit |
| S1 built gain +0 to +4 | **+14** | **MISSED — 3.5x the top of the range** |
| S1 ranked@50 gain +0 to +2 | +0 | hit |
| S1 p@10 CI includes zero | it does | hit |
| S1 vs S2 indistinguishable | identical | hit, stronger |
| S1 ≥ random on seeded | 234 vs 231 | hit |
| score CI-clear over size in every arm | yes | hit |

One miss, and it is recorded: I under-predicted the built gain badly, because I
reasoned from newly-seeded rings and forgot that extra seeds also produce extra
candidates around rings that were already seeded.

**Recommendation: ship none of the arms.**

- S1 is not a distinct idea on this data; it is S2.
- S2 buys +14 built and +0 ranked, for a **10% increase in seeds and therefore
  in generation cost**, against a headline that does not move (p@10 −0.0029, CI
  includes zero; p@20 +0.0059, CI excludes zero but the point estimate is six
  thousandths).
- It does not touch the two typologies that are actually build-destroyed.

The measured evidence points where `PHASE2-SEED-CHEAT-FINDINGS.md` §H2 already
said it does — at **build**, and specifically at assembling fragments — not at
seeding. That is queue item B1.

## 7. A defect in this harness, found and fixed

The run's `addressable_by_typology` JSON field was built with
`{k: v for k, v in sorted((typ, 1) ...)}`, which silently collapses duplicates
to one each. It summed to 4 against a true 7 while the console printed the
correct table. A well-formed field that quietly understates is this project's
characteristic defect; it is a `Counter` now, and the stored JSON was repaired
from the run's own console output rather than by re-running 26 minutes of
replay.
