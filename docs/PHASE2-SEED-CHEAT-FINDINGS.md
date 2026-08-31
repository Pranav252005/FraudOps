# The §5b tension, resolved: the seed lands in one fragment of a broken ring

**Date:** 2026-09-01. **Measured by:** `scripts/eval_seed_cheat_diff.py`
(catalogue, 34 cycles, 1,192 s) and `scripts/eval_seeding_prize.py`
(interval, no replay). **Data:** `data/eval_seed_cheat_diff.json`,
`data/eval_seeding_prize.json`. **Log:** `data/eval_seed_cheat_diff.log`.

## The tension

`docs/HANDOFF.md` §5b measures seeding at **89% of active rings**.
`docs/CENTREPIECE-INVALIDATED.md` measures the seed cheat as worth **~2.2× at
k=10** to the shipped scorer. Both cannot be simple.

The standing hypothesis was that *"the ring was seeded at all"* is not *"the
ring was seeded with a member set the builder can grow into the ring"*. **That
hypothesis is confirmed, and the mechanism is now named: the ring's own
induced subgraph is disconnected inside the 72-hour window, and the honest seed
lands in one fragment of it.**

## The catalogue reconciles with §5b exactly

259 active rings, partitioned on
(`seeded_honest`, `seeded_cheat`, `built_honest`, `built_cheat`):

| cell | count | reading |
|---|---:|---|
| `1111` | **159** | seeded and recovered honestly — the working case |
| `1101` | **49** | **R** — seeded honestly, *not* recovered, rescued by the cheat |
| `1100` | 22 | seeded honestly, recovered by neither. The cheat does not rescue these either |
| `0101` | 25 | not seeded honestly; only the cheat recovers them |
| `0111` | 2 | not seeded honestly yet recovered honestly — a neighbouring seed's candidate happened to cover the ring |
| `0100` | 2 | the cheat seeded them and still failed to build them |
| **total** | **259** | |

**Reconciliation:** 230 / 259 = **88.8%** seeded under the honest rule. §5b
reports 230/259 = 89%. The two agree to the ring. That is the check that makes
everything below quotable — a partition that disagreed with the published
figure would be describing a different pool.

**|R| = 49.** Above the plan's threshold of 30, so this is a result rather than
an anecdote, and hypotheses may be fitted to it.

## The falsification check, run before interpreting

R differs from the matched comparison set **C** (seeded *and* recovered
honestly, n = 159) on **7 of 7** measurements. The pre-registered null — that
the cheat is not operating through seed growability and the §5b framing is
wrong as posed — **does not fire**.

## The three hypotheses, and which survives

| | R (n=49) | C (n=159) | |
|---|---:|---:|---|
| median ring size | 8 | 5 | |
| median seed fraction of ring | 0.250 | 0.333 | **H1: weak** |
| **share with the ring split across ≥2 components** | **0.510** | **0.057** | **H2: 9×** |
| share with the seed in only *some* components | 0.469 | 0.044 | **H2: 11×** |
| median components / median seeded | 2 / 1 | 1 / 1 | |

### H1 — the seed is too thin: WEAK

Rescued rings do carry proportionally fewer seeds (0.250 vs 0.333 of the ring),
but the gap is small and the absolute numbers overlap heavily. Seed *count* is
not what separates a rescued ring from a recovered one.

### H2 — the seed is in the wrong place: THIS IS THE ONE

**51% of rescued rings are split across two or more components of their own
induced subgraph, against 5.7% of recovered rings.** The honest seed sits in
one fragment; the rest of the ring is not reachable through ring edges at all,
only through unrelated intermediaries.

Rescued rings are also larger (median 8 members vs 5), which is the plausible
cause rather than a separate finding: a larger ring has more members whose
activity can fall outside a 72-hour window, so more of its edges are missing
from any one window and it fragments more readily.

This is why the cheat works. The cheat seeds **every** member, so every
fragment gets a seed, and one expansion per fragment is enough to produce a
covering candidate.

### H3 — the builder's budget is too tight: REFUTED, and it fails backwards

The budget sweep relaxes each knob against the shipped configuration
(`hops=2, max_nodes=200, max_degree=50`), taking the best single seed:

| budget | R containment | R covered | C containment | C covered |
|---|---:|---:|---:|---:|
| shipped | 0.571 | **24%** | 1.000 | **50%** |
| no hub guard | 0.500 | 16% | 1.000 | 46% |
| more nodes (2000) | 0.571 | 24% | 1.000 | 50% |
| three hops | 0.700 | 6% | 1.000 | 12% |
| all relaxed | 0.714 | **4%** | 1.000 | **8%** |

**Relaxing the budget raises containment and collapses coverage.** More budget
finds *more of the ring* (0.571 → 0.714) and covers *fewer rings* (24% → 4%),
because the extra reach drags in bystanders and the candidate fails `is_hit`'s
Jaccard floor. This is `docs/HANDOFF.md` §5c's "expansion recovers the ring and
then buries it", measured directly on the rings it matters for.

The effect is symmetric — C degrades the same way (50% → 8%) — so it is a
property of expansion against the Jaccard floor, not something specific to
rescued rings. Either way, **giving the builder more budget is not the fix, and
this closes the last of the three hypotheses.**

### Caveat on the sweep's absolute numbers, which matters

The sweep calls `graph.expand` directly: **no pruning and no suppression**.
Both materially change `is_hit` — `sentinel/config.py` records that `leaf2`
pruning raises rings BUILT from 115 to 159 and mean Jaccard from 0.369 to
0.485. So the sweep's "covered" column **understates** what the real builder
achieves and is **not** comparable to `built_honest`. Only the R-vs-C contrast
within the sweep is interpretable, since both sides omit the same stages.
Concretely: the 24% figure for R does not contradict R being 0% built by
definition; it is a different measurement of a different pipeline stage.

## The prize, with an interval for the first time

`scripts/eval_seeding_prize.py`, paired on the same 18 held-out cycles,
cycle-clustered bootstrap:

| ranking | as-is → cheat, p@10 | delta | ratio |
|---|---|---|---|
| **blend** (shipped) | 0.1889 → 0.4111 | **+0.2222 [+0.1222, +0.3333]** | **2.18× [1.62×, 3.50×]** |
| **size** (reads no features) | 0.0444 → 0.1000 | +0.0556 [+0.0111, +0.1111] | 2.25× [1.25×, 3.75×] |
| oracle (supervised) | 0.2111 → 0.5611 | +0.3500 [+0.2556, +0.4389] | 2.66× [2.09×, 4.00×] |

**The 2.2× survives its first interval.** The delta excludes zero at every k
and every ranking.

Two readings worth having:

- **The scorer prize is now outside the seeding prize's interval.** The
  oracle/blend ratio is 1.12× at k=10; the seeding interval's lower bound is
  1.62×. Before this, "seeding is worth more than the scorer" was two point
  estimates from two documents compared by eye. It is now a separation backed
  by an interval, at n=18.
- **`size` gains as much as `blend` does** (2.25× vs 2.18×). A baseline that
  reads no features at all collects the whole seeding prize. That is the
  strongest available evidence that the prize is about the pool *containing*
  the rings, not about ranking them — it is available to any scorer.

The scorer ratio (`oracle_over_blend`) still has **no interval**; it is a ratio
of point estimates in `scripts/eval_oracle.py`. Recorded rather than glossed.

## What this does and does not indicate

It does **not** resolve to "go widen seeding", which `docs/HANDOFF.md` §5b
rules out and §5c ruled out by experiment on all three expansion knobs. §5b and
§5c remain correct: firing the seed rule on more accounts does not address a
ring whose seed is already present but stranded in one fragment.

It also does not resolve to "give the builder more budget" — H3 is refuted
above, and relaxing the budget makes coverage worse.

**What it indicates is a different idea, which is what
`docs/CENTREPIECE-INVALIDATED.md` predicted would be needed:** the loss is at
*build*, and specifically at **candidate assembly across disconnected
fragments of the same ring**. The cheat's advantage is that it puts a seed in
every fragment. A real detector cannot do that — it does not know the rings —
but the two directions this opens are:

1. **Merge candidates that are weakly linked**, rather than only suppressing
   ones that overlap. `suppress()` currently removes near-duplicates; nothing
   joins two candidates that are different fragments of one structure.
2. **Widen the window for large structures specifically.** Fragmentation is a
   function of ring size against window length, and R's rings are larger.
   `WINDOW_MINUTES` is currently uniform.

**Both are untested.** They are named as the directions the measurement points
at, not as recommendations, and neither should be quoted as a plan until it has
its own pre-registration.

## Cost, and what it corrected

`docs/HANDOFF-NEXT.md` §2 and `docs/CENTREPIECE-INVALIDATED.md` both describe
this diff as "cheap to settle" and "a read of data that exists". **Both are
wrong**, and `docs/inventory/run2_pools.md` records why: run 2's pools are
never persisted, and three of the four fields the partition needs — both seed
sets and `recovered_cheat` — are computed and discarded. This took a
**1,192-second replay**, made cheaper than the naive 2×400 s by sharing one
graph and one expansion cache across both arms per tick.
