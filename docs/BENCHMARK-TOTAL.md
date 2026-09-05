# The benchmark, totalled

Everything this project has measured, on both splits it has ever evaluated,
as of 2026-09-05. Every number here is read from a committed JSON in `data/`,
not from prose. Intervals are cycle-clustered paired bootstraps,
`n_resamples=2000, seed=7, alpha=0.05`.

## 1. Headline: does the score earn its place?

Hit = containment ≥ 0.5 **and** Jaccard ≥ 0.3.

| | HI-Small | HI-Medium |
|---|---:|---:|
| cycles (bootstrap unit) | 34 | 58 |
| ground-truth rings seen | 259 | 1,900 |
| eval window | days 8–10 | days 12–16 |
| **p@10** score / size | **0.2912** / 0.0941 | **0.6879** / 0.1103 |
| p@20 | 0.1574 / 0.0735 | 0.6017 / 0.1078 |
| p@50 | 0.0759 / 0.0506 | 0.3545 / 0.0876 |
| p@100 | 0.0406 / 0.0350 | 0.1852 / 0.0690 |
| ring recall (score) | 23.9% | 16.9% |

`score − size`, paired over the same cycles:

| k | HI-Small | HI-Medium |
|---|---|---|
| 10 | +0.1971 [+0.1235, +0.2676] | +0.5776 [+0.5086, +0.6414] |
| 20 | +0.0838 [+0.0471, +0.1176] | +0.4940 [+0.4328, +0.5526] |
| 50 | +0.0253 [+0.0088, +0.0412] | +0.2669 [+0.2272, +0.3072] |
| **100** | **+0.0056 [−0.0032, +0.0135]** ← includes zero | +0.1162 [+0.0969, +0.1362] |

**The bottom line.** The score beats a node-count ranker at k=10, 20 and 50 on
both splits, with intervals clear of zero on all six. At **k=100 on HI-Small it
does not** — the interval contains zero, so by this project's own standing rule
that is not a gain. On HI-Medium it survives k=100.

## 2. The one number to quote across splits

**Not p@k.** HI-Medium has ~790 active rings per cycle against HI-Small's ~140,
so a candidate is 5.6× more likely to cover *something* — the random baseline
moves 0.000 → 0.003 for that reason alone. Levels are not comparable.

The conditioned quantity is the **ratio to the size baseline at k=10**:

| HI-Small | HI-Medium |
|---:|---:|
| **3.30×** | **6.25×** |

## 3. What replicates, and it is not the levels

**Per-typology difficulty ordering: Spearman ρ = +0.786** across splits.
SCATTER-GATHER easiest and BIPARTITE hardest on both, on data the detector had
never seen, with dataset constants derived independently per split.

**Funnel stage ordering: identical.**

| stage loss | HI-Medium | HI-Small |
|---|---:|---:|
| seeding | −6.1 pts | −11.2 |
| build | −28.7 | −26.6 |
| **ranking** | **−49.2** | **−39.8** |

**And the same two typologies are build-destroyed on both splits, and only
those two: BIPARTITE (22% built on HI-Medium) and STACK (30%).**

That is the strongest replication in the project, because it is a structural
classification rather than a level.

## 4. The supervised ceiling (HI-Small; HI-Medium pending)

| | p@10 | p@20 | p@50 |
|---|---:|---:|---:|
| oracle, real seeding | 0.2111 | 0.1278 | 0.0622 |
| oracle, perfect seeding | 0.5611 | 0.4694 | 0.3367 |

A learned reranker on the candidates the pipeline actually produces reaches
**0.2111 — below the shipped blend's 0.2912.** The headroom is not in ranking;
it is in **seeding**, worth 2.7× at k=10.

## 5. What the benchmark does NOT establish

- **No parity claim against any surveyed system.** No head-to-head has been run.
- **The rupee figures are unquotable.** The cost gate confirms no single
  unsourced input flips the conclusion across 10×, but with all six adverse at
  once, break-even is 1.8382 and the queue does not pay.
- **`ring_recall@k` intervals are invalid** (defect D5, found today, not fixed).
  A cluster bootstrap cannot bound a union statistic; the point estimate falls
  outside its own CI on both splits. `ring_recall` is quoted above with its
  point estimate only, deliberately. p@k is unaffected — it is a ratio of sums.
- **HI-Small's `structural_recall_ceiling` of 0.733 has never been reproduced.**
  Four definitions were tried; all land 278–282, none at 266.
- **One run of one script per split.** No repeated-run variance.

## 6. Scale

1,046 tests, 5 CI gates, 15 pre-registrations, 39 committed result sets,
2 splits of AMLworld (HI-Small 370 rings, HI-Medium 2,756).
