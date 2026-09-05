# HI-Medium — the detector generalises, and the reason I ran it was wrong

**Run 2026-09-05**, 58 cycles over 16 days, 9,838 s (2h44m).
`SENTINEL_DATASET=HI-Medium python scripts/eval_phase2.py` →
`data/eval_phase2-HI-Medium.json`. Cycle-clustered paired bootstrap.

First evaluation this project has ever run on a split other than HI-Small.
HI-Small's `data/eval_phase2.json` is untouched — verified, still 34 runs,
dated 08-31.

## The result

**1,900 ground-truth rings seen**, against HI-Small's 259.

| ranking | p@10 | p@20 | p@50 | p@100 | rings found | ring recall |
|---|---:|---:|---:|---:|---:|---:|
| **score** | **0.688** | **0.602** | **0.354** | **0.185** | 322 | **16.9%** |
| size | 0.110 | 0.108 | 0.088 | 0.069 | 138 | 7.3% |
| degree | 0.033 | 0.046 | 0.051 | 0.046 | 111 | 5.8% |
| random | 0.003 | 0.004 | 0.003 | 0.002 | 15 | 0.8% |

`score − size`, paired over the same 58 cycles:

| k=10 | k=20 | k=50 | k=100 |
|---|---|---|---|
| **+0.5776 [+0.5086, +0.6414]** | **+0.4940 [+0.4328, +0.5526]** | **+0.2669 [+0.2272, +0.3072]** | **+0.1162 [+0.0969, +0.1362]** |

**CI-clear at every depth, including k=100** — which on HI-Small is the depth
where the size baseline historically *beat* the score (`HANDOFF.md` §5e:
"at k=100 the reversal is real"). On an independent split with 7.3× the rings,
that reversal does not appear.

## The finding worth keeping: the typology ordering replicates

| typology | HI-Small | HI-Medium |
|---|---:|---:|
| SCATTER-GATHER | 17/31 **54.8%** | 65/244 **26.6%** |
| GATHER-SCATTER | 10/38 26.3% | 47/235 20.0% |
| CYCLE | 8/37 21.6% | 49/247 19.8% |
| RANDOM | 8/26 30.8% | 41/218 18.8% |
| FAN-OUT | 11/36 30.6% | 37/227 16.3% |
| STACK | 2/30 6.7% | 35/243 14.4% |
| FAN-IN | 5/30 16.7% | 32/255 12.5% |
| BIPARTITE | 1/31 **3.2%** | 16/231 **6.9%** |

**Spearman ρ = +0.786** between the two splits' difficulty orderings.
SCATTER-GATHER is easiest and BIPARTITE hardest on both, on data the detector
had never seen, with constants derived independently.

This is the first evidence in this project that its per-typology structure is a
property of the *problem* rather than of HI-Small's particular generator run —
and it is the strongest reason to keep BIPARTITE and STACK as the targets they
have been all along.

## Two things that look better than they are

### p@k is not comparable across splits, and most of the jump is prevalence

p@10 goes 0.2912 → 0.688. That is **not** a 2.4× better detector.

HI-Medium has **~790 active rings per cycle against HI-Small's ~140**. With 5.6×
more targets in the window, a candidate is far more likely to cover *some* ring
— the random baseline moves 0.000 → 0.003 for exactly that reason. Standing
rule 4 requires prevalence beside any p@k, and across splits it is not optional.

The conditioned statement is the **ratio to the size baseline**:

| | score/size @10 |
|---|---:|
| HI-Small | 3.30× |
| HI-Medium | 6.25× |

Still a real improvement, and 1.9× rather than 2.4×. **Quote the ratio, not the
level.**

### Ring recall went DOWN

**23.9% → 16.9%.** The detector surfaces a *smaller fraction* of the rings that
exist. Precision up, recall down, and the recall number is the one closer to
what the product claims.

## The prediction I got wrong, and it was my reason for running this

`docs/GRAPH-PRIOR-ART-PLAN.md` and the queue entry both said HI-Medium was
"**the only split that could materially narrow the intervals** this project
keeps hitting". That was the stated justification for the whole exercise.

**It barely narrowed them.**

| | `score − size` @10 interval | width |
|---|---|---:|
| HI-Small (34 cycles) | [+0.1235, +0.2676] | 0.1441 |
| HI-Medium (58 cycles) | [+0.5086, +0.6414] | **0.1328** |
| expected from cycle count alone | — | 0.1103 |

An 8% narrowing, against 23% expected from √(34/58) — so per-cycle variance is
*higher* here, and the extra rings bought nothing in precision of the estimate.

**The mechanism is one I should have seen before running a 2h44m job: the
bootstrap resamples CYCLES, not rings.** Cycles went 34 → 58 (1.7×) while rings
went 259 → 1,900 (7.3×). Ring count does not enter the resampling unit at all,
so it cannot narrow a cycle-clustered interval.

The conclusions are far more robust here — but because the **effect is larger**,
not because the estimate is more precise. Those are different things and the
plan conflated them.

**What would actually narrow these intervals** is more cycles, not more rings:
a shorter tick spacing (rejected in `HANDOFF.md` §11d as producing near-duplicate
cycles), a longer evaluable span, or a resampling unit that isn't the cycle.
None of that is what running a bigger split buys.

## Cost, and my estimate of it

**9,838 s — 2h44m**, against the 8–12 hours I projected. Candidate counts
stabilised around 55–59k rather than continuing to climb, so later cycles were
not much worse than the two I benchmarked. **My estimate was 3–4× pessimistic**,
and it was built from two cycles at the cheapest point in the run.

For the record, the earlier per-cycle measurement stands: HI-Medium is ~4× the
candidates for ~20× the time of HI-Small, which is superlinear and remains a
real scaling problem for `suppress()`.

## What this does and does not settle

- **No cross-split parity claim is made.** The two splits have different
  prevalence, different day counts, different derived boundaries (10 vs 16) and
  different ring counts. The typology ordering replicates; the levels do not
  transfer.
- **This is one run of one script.** `eval_funnel.py` and `eval_oracle.py` were
  unrunnable until today's repair and had never been run on HI-Medium, so at
  the time of writing there was no funnel decomposition and no supervised
  ceiling for this split. **Superseded by Part 2 below**, which reports the
  funnel; the oracle followed after D3b.
- **The lb6 seed-lookback finding was not re-tested here.** P0 ran on HI-Small
  only.

---

# Part 2 — the funnel, and what D3b proved on the way

Added 2026-09-05 after `eval_funnel.py` and `eval_oracle.py` were repaired
(both had been unrunnable) and `collect_pool` was made memory-viable (D3b).

## The funnel replicates HI-Small's structure

58 cycles, 1,900 rings. `data/funnel-HI-Medium.json`; HI-Small's `funnel.json`
untouched.

| typology | seen | seeded | built | ranked | verdict |
|---|---:|---:|---:|---:|---|
| **BIPARTITE** | 231 | 220 (95%) | **51 (22%)** | 16 (7%) | **build-destroyed** |
| **STACK** | 243 | 235 (97%) | **74 (30%)** | 35 (14%) | **build-destroyed** |
| FAN-IN | 255 | 226 (89%) | 175 (69%) | 30 (12%) | ordinary attrition |
| FAN-OUT | 227 | 211 (93%) | 158 (70%) | 36 (16%) | ordinary attrition |
| GATHER-SCATTER | 235 | 225 (96%) | 189 (80%) | 45 (19%) | ordinary attrition |
| RANDOM | 218 | 200 (92%) | 174 (80%) | 36 (17%) | ranking-limited |
| CYCLE | 247 | 234 (95%) | 201 (81%) | 44 (18%) | ranking-limited |
| SCATTER-GATHER | 244 | 234 (96%) | 217 (89%) | 62 (25%) | ranking-limited |
| **TOTAL** | **1,900** | 1,785 (94%) | 1,239 (65%) | 304 (16%) | |

**The stage ordering is identical on both splits:**

| stage loss | HI-Medium | HI-Small |
|---|---:|---:|
| seeding | −6.1 pts | −11.2 |
| build | −28.7 | −26.6 |
| **ranking** | **−49.2** | **−39.8** |

Ranking largest, build second, seeding smallest — on both. And **the same two
typologies are classified "build-destroyed" on both splits, and only those
two**: BIPARTITE and STACK.

That is stronger evidence than the p@k replication in Part 1, because it is a
*structural classification* rather than a level, and levels do not transfer
across splits with different prevalence.

## D3b was verified end-to-end, and it validated five other claims

The oracle was re-run on HI-Small after D3b and diffed against the preserved
pre-change baseline (`data/eval_oracle.PRE-D3B.json`, measured 2026-08-31).

**Four differences, all prose strings, zero numeric differences.**

| | pre | post |
|---|---|---|
| `oracle_as_is` p@10 / p@20 / p@50 | 0.211111 / 0.127778 / 0.062222 | **identical** |
| `oracle_on_all_rings` p@10 / p@20 / p@50 | 0.561111 / 0.469444 / 0.336667 | **identical** |
| `cycle_rows` (the bootstrap unit) | | **identical** |
| ap, f1, n_test, n_train, split_t, cycles, mean_candidate_size | | **identical** |

The four diffs are `gfp_control`, `interpretation`, `label_dependency` and
`framing` — narrative strings edited by later commits, not by D3b.

**This validated more than D3b.** That baseline predates six commits (S1/S2,
B3, the fragment linker, P0, P0b), each of which claimed the shipped path was
byte-identical. Those claims were checked individually against a 3-cycle
fixture; this is the first end-to-end confirmation across a full 34-cycle
replay including model training. **All of them hold.**

The run also took ~14 minutes, so the memory fix made it faster as well as
smaller.

## Two defects found while reporting, both pre-existing

### `ring_recall@k` point estimates fall outside their own intervals

HI-Medium at all three k; HI-Small at k=20 and k=50:

```
ring_recall@50   point = 0.1600   CI [0.1429, 0.1550]
```

This is the cluster bootstrap applied to a **union** statistic. A resample with
replacement covers only ~63% of distinct cycles, so the union of distinct rings
found over a resample is systematically smaller than the union over the full
set. **The interval is biased low by construction and cannot contain the
point.**

`ring_recall` is quoted in this project's headline tables, and the interval
attached to it is not a valid interval for it. p@k is unaffected — it is a
ratio of sums, not a union, and its intervals bracket their points correctly.

### `eval_funnel.py` misreports where it wrote

It prints `written to data/funnel.json and data/funnel.csv` while writing
`funnel-HI-Medium.*`. The same defect fixed in `eval_phase2.py` when HI-Medium
was first run, and not swept at the time.
