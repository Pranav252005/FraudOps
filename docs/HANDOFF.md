# Session handoff — FraudOps / Sentinel

Everything built, measured, and learned in this session. Written so a fresh
session can pick up without re-deriving anything.

**Repo:** https://github.com/Pranav252005/FraudOps
**Target:** Razorpay AI Buildathon, AI Risk Manager track. One class of loss:
money-movement / mule rings. Defence only.
**Tests:** 436 passing + 1 skipped + 1 xfail. `python -m pytest -q` is the only authority for this figure.
(The skip is the snapml constructor check in `tests/test_gfp_control.py`, which runs only where snapml is installed.)

> **Read §5b–§5e and §12 before acting on §5 or §10.** Several sections of this
> document were written before measurements that overturned them. Where that
> happened the original text is kept and a correction follows it, because the
> reversal is usually the most useful thing on the page — but it means the
> earliest statement of a question is often the wrong one. §10 in particular
> still lists a next step that §5b explicitly rules out; it is annotated inline
> now rather than left to trap a reader going top-down.

---

## 1. What this is

A fraud-ring **investigation console**, not a transaction classifier. It changes
the unit of investigation from the transaction to the ring, and delivers each
ring pre-investigated.

The thesis: the bottleneck in fraud ops is not detection — every risk team
already has detectors producing more alerts than it can work — it is
**investigation throughput**. Two multipliers: one analyst decision covers ~40
accounts instead of one, and the case arrives with evidence assembled.

---

## 2. Phases completed

| Phase | What | State |
|---|---|---|
| 0 | Ground-truth parsing, account/jurisdiction registry | done, verified |
| 1 | Time-ordered stream compilation, sliding-window graph | done, verified |
| 2 | Seed-and-expand, motifs, scoring, overlap suppression | done, measured |
| v2 | Temporal cycles, behavioural axis, GARG-AML layers, registry context | done |
| 3 | Immutable case records, verdict taxonomy, label corpus | done |
| 4 | Learned re-ranker + simulated analyst | done, measured |
| 5 | Console (queue, case file, disposition) | done, verified live |

### Data

IBM AMLworld `HI-Small` (NeurIPS 2023, CDLA-Sharing-1.0). 5,078,344
transactions, 515,088 accounts, 30,528 banks, 34 countries, **370 labelled
rings** across 8 typologies. The only public dataset found that labels **rings**
rather than only transactions, which is what makes ring-level precision and
recall reportable at all.

Compiled to a 48.9 MB parquet: 4,487,133 edges after dropping 591,211
self-loops, monotonic, 3,209/3,209 ring edges joined (100%). Replay runs at
233k edges/s.

### Architecture

```
stream → windowed graph (72h) → pass-through seeds → 2-hop expand
       → motifs + 3 feature families → score → overlap suppression
       → ranked queue → case record → analyst verdict → label corpus → re-ranker
```

Three feature families: **structural** (cycles, temporal cycles, fan, scatter-
gather, gather-scatter, GARG-AML block density, bipartite, stack),
**behavioural** (pass-through ratio/latency, dormancy, velocity, amount moments
with skew and kurtosis), **contextual** (banks, countries, entity reuse, entity
type purity).

---

## 3. Where the numbers actually stand

### Ring-level (the honest headline)

Hit = candidate contains ≥50% of a ring **and** Jaccard ≥ 0.3.

| ranking | p@10 | p@20 | p@50 | ring recall |
|---|---:|---:|---:|---:|
| **score** | **0.085** | 0.049 | 0.024 | **15.4%** |
| degree | 0.000 | 0.001 | 0.008 | 3.9% |
| size | 0.000 | 0.000 | 0.001 | 2.3% |
| random | 0.000 | 0.000 | 0.002 | 1.5% |

### With the learned re-ranker (held-out)

| ranking | p@5 | p@10 | p@20 | p@50 |
|---|---:|---:|---:|---:|
| v1 hand-set | 0.176 | 0.106 | 0.065 | 0.035 |
| learned | 0.176 | 0.124 | 0.088 | 0.053 |
| lift | 1.00× | 1.17× | 1.36× | 1.50× |

Held-out average precision **0.2704 vs 0.0412 base = 6.57×**.

**CORRECTION (later session) — the lift above does not survive its own
confidence interval.** `scripts/eval_phase4.py` now reports a paired
bootstrap 95% CI on the v1-vs-reranker delta at each k, resampled over the 17
held-out cycles (`sentinel/eval/bootstrap.py`):

| k | delta (reranker − v1) | 95% CI | excludes zero? |
|---:|---:|---|---|
| 5 | 0.000 | [-0.094, 0.094] | no |
| 10 | 0.018 | [-0.035, 0.071] | no |
| 20 | 0.024 | [-0.018, 0.068] | no |
| 50 | 0.018 | [-0.002, 0.039] | no |

**At every k, the interval includes zero.** With only 17 held-out cycles, the
lift reported above is not distinguishable from noise — this is the direct
answer to "does the reported improvement survive its own CI": **no.** The
held-out average precision figure (0.2704 vs 0.0412 = 6.57×) is a single
aggregate number over the same 17 cycles and carries the same fragility,
though it was not itself bootstrapped. This does not mean the re-ranker is
useless — the permutation-importance ranking (below) is still informative
about which features carry signal — but the precision-at-k lift specifically
should not be quoted as a settled result at this sample size. More held-out
cycles (a longer eval window, or a shorter tick spacing) would narrow this
before it is worth trusting either way.

### Per typology

| Typology | Recall | | Typology | Recall |
|---|---:|---|---|---:|
| SCATTER-GATHER | 29% | | FAN-OUT | 14% |
| GATHER-SCATTER | 21% | | RANDOM | 12% |
| FAN-IN | 20% | | STACK | 7% |
| CYCLE | 16% | | BIPARTITE | 3% |

**Structural ceiling is 73.3%** — 88 of 370 rings have ≤2 accounts and have no
community structure to detect.

### Transaction-level (for comparability only)

| top-k | precision | recall | F1 | lift |
|---:|---:|---:|---:|---:|
| 10 | 7.3% | 6.4% | **0.068** | 11× |
| 20 | 4.3% | 7.2% | 0.054 | 6× |
| 50 | 2.0% | 8.5% | 0.032 | 3× |
| 100 | 1.3% | 10.7% | 0.023 | 2× |
| 500 | 0.7% | 24.1% | 0.015 | 1× |

**CORRECTION (later session) — this F1 is not comparable to the published
baselines below, and the honest whole-population number is much weaker.**
Two independent problems, found while checking whether the "0.069, roughly 6×
worse" framing in the old §4 below was fair:

1. **The F1 above is a fixed-cardinality-selection artifact**, the same
   family of problem as the oracle's fixed-0.5-threshold pathology (§ above),
   just via a different mechanism. "Flagged" is the union of edges inside the
   top-*k* *candidates* that cycle — an arbitrary, uncalibrated operating
   point, not a per-transaction decision boundary a classifier chose to
   maximise F1. The published GNN baselines get to pick their own threshold
   over the *entire* test set; this system's k=10/20/50/... numbers are five
   different, all-uncalibrated slices, and the best of them (k=10) is the one
   quoted.
2. **The threshold-free number is far less flattering.** Scoring every one
   of the 647,316 pairs in the evaluation window by the highest score any
   candidate ever containing it received (0.0 if never flagged by anything)
   and computing average precision against the true labels
   (`scripts/eval_vs_published.py`, `average_precision_score`) gives
   **AP = 0.0113 against a base rate of 0.0067 -- a 1.7× lift**, not the 10-11×
   the top-10 table suggests. The gap between "11× at k=10" and "1.7× over
   the whole population" is the funnel's built-stage recall ceiling made
   visible at the transaction level: a large share of true positives are
   never flagged by *any* candidate at *any* score, so they sit tied at 0.0
   with most of the negative population, and AP correctly punishes that.

**The right statement is not "roughly 6× worse than supervised baselines."**
It is: this system's transaction-level ranking, honestly measured over the
whole population, is barely above base rate (1.7×), and the top-k table above
should not be quoted alongside the published F1 numbers as if they were the
same measurement.

---

## 4. How this compares

### Published on the same HI-Small dataset — all **supervised**

| System | Minority-class F1 |
|---|---:|
| Standard GNN, no adaptations | 26.9% |
| GNN + reverse MP + port numbering + ego IDs | 42.9% |
| GIN, adapted | 57.2% |
| **This project (unsupervised), top-10 slice, uncalibrated** | 0.068 |
| **This project (unsupervised), threshold-free, whole population** | **AP 0.011 (1.7× base rate)** |

**Not a clean "6× worse."** The top-10 row and the published rows are
different measurements (a small uncalibrated slice vs. a calibrated
whole-test-set decision); the threshold-free row is the fairer like-for-like
view of ranking quality and it is considerably weaker than the top-10 number
implies. Theirs train on the labels; this uses none -- that gap is real -- but
the size of the gap should be read off the threshold-free row, not the top-10
one.

### Razorpay Vulcan (launched 18 Aug 2026)

Non-LLM transformer foundation model for payments, built with NVIDIA and AWS.
**~3 trillion data points across 4 billion payments**, ~3,000 behavioural
signals per transaction in real time. Reported: 8× more international card
fraud stopped, 5× more fraudulent/disputed transactions without more alerts.

Critically, it already does cross-merchant network detection — *"can identify a
compromised card the moment it appears at multiple unrelated merchants"* — which
was the differentiator originally written into this project's design doc.

**This will not reach Vulcan.** No public dataset and no laptop closes a
3-trillion-datapoint gap.

**What is still distinct:** Vulcan scores *transactions* and flags *entities*.
Nothing public suggests it hands an analyst *"here are the 9 accounts that form
this structure and here is the shape."* Nor point-in-time labelling, a verdict
taxonomy, or control-arm sampling.

### RBI MuleHunter.AI

Built by the Reserve Bank Innovation Hub on **19 distinct mule behaviour
patterns**. Runs **inside banks on bank-account data**.

**Corrected — the earlier version of this paragraph ("operational in 26 banks,
~20,000 mule accounts flagged monthly") presented a capability claim as a
verified outcome, which is the standard this repo applies to its own numbers
and must apply symmetrically.** What is actually sourced: an RTI response
reported Dec 2025 gives **23 banks** implemented
([MediaNama](https://www.medianama.com/2025/12/223-rti-23-banks-mulehunter-mule-accounts/)).
On the same RTI the **RBI declined to disclose how many mule accounts have been
identified or acted on**, citing fiduciary grounds. So "~20,000 flagged
monthly" is **not an independently verified outcome** and must not be quoted as
one — it is a capability figure circulating in secondary coverage. The 19
patterns remain unpublished.

The 19 patterns are unpublished; the industry typology they draw on is
implemented here — pass-through velocity, the 80%-within-48h rule, dormancy,
fan-in from unrelated senders.

### IBM Graph Feature Preprocessor (ICAIF 2024) — the most important comparison

GFP reports **higher minority-class F1 than standard GNNs** using hand-
engineered subgraph features plus gradient boosting, on CPU. **This is the
architecture class this project is already in**, which means the ceiling here is
far above current numbers.

**CORRECTION (later session) — the parity claim that stood here is withdrawn,
and the reason it could not be checked was misdiagnosed twice.**

The original text read: *"Coverage vs GFP: fan-in/out ✅, degree ✅,
scatter-gather ✅, gather-scatter ✅, simple cycle ✅, temporal cycle ✅, vertex
statistics with skew/kurtosis ✅. Essentially at parity."* Two things are wrong
with it.

**It was never a measurement.** It is a checklist made by reading two feature
lists and comparing names. `docs/ARCHITECTURE_UPLIFT.md` §2.2 already found
three of those ticks to be false — un-windowed scatter-gather, absent timestamp
moments, amount moments computed but never propagated — and commit `cc8a68a`
closed them. Closing a coverage gap still does not measure anything: two
implementations of "scatter-gather" can agree on the name and disagree on every
value.

**The blocker was not the Python version.** This document said "`snapml` has no
Python 3.14 build"; commit `d7dba2f` refined that to "snapml is obtainable,
just not on 3.14"; `ARCHITECTURE_UPLIFT.md` §2.1 costed the fix at "~30
minutes, lowest risk". All three are wrong. Measured directly:

- Python 3.11 was provisioned and `snapml==1.15.6` installed cleanly.
- `from snapml import GraphFeaturePreprocessor` succeeds — the wrapper module
  is in the Windows wheel.
- Constructing it raises `module 'snapml.libsnapmllocal3_avx2' has no
  attribute 'gf_allocate'`.
- **None of the six `.pyd` binaries in the Windows wheel export any `gf_*`
  symbol.** The manylinux wheel of the *identical version* exports all eight.
- snapml 1.17.x, the current release, ships **no Windows wheels at all**.
  1.15.6 is the last Windows release, and it is one without GFP.

**IBM's Graph Feature Preprocessor is not built for Windows, at any snapml
version or any Python version.** A 3.11 venv cannot fix that. The real
requirement is a Linux or macOS host, which is why `scripts/gfp_control.py` is
split at a file boundary: `export` and `compare` run here, `gfp-features` does
not run here at all.

Until that middle stage has been run, **there is no measured comparison against
GFP and no parity claim of any kind belongs in this repo.**
`scripts/gfp_compare.py` refuses to emit a verdict without it, and
`tests/test_gfp_control.py` pins that refusal.

### Industry reality — the comparison that flatters most, and is fair

Production rule-based AML runs at **95–99% false-positive rates**; alert→SAR
conversion is **under 5%, one bank survey found 2.8%**. Investigation burden
reaches 22 hours per alert.

p@20 = 0.049 means **5% of the top-20 are real rings — at or slightly above
industry alert-to-SAR conversion.** Not because this is good, but because the
industry standard is genuinely that bad.

---

## 5. THE OPEN BOTTLENECK — start here

A generation-vs-ranking diagnostic:

| typology | active | **generated** | in top-50 |
|---|---:|---:|---:|
| BIPARTITE | 10 | **0 (0%)** | 0 |
| FAN-OUT | 17 | **0 (0%)** | 0 |
| RANDOM | 8 | **0 (0%)** | 0 |
| STACK | 15 | **0 (0%)** | 0 |
| FAN-IN | 15 | 8 (53%) | 0 |
| GATHER-SCATTER | 18 | 11 (61%) | 1 |
| SCATTER-GATHER | 15 | 10 (67%) | 0 |
| **Total** | **114** | **30 (26%)** | **1 (1%)** |

**Only 26% of active rings become candidates at all. Four typologies are never
generated.**

This **contradicts the Phase 2 conclusion** ("the loss is in ranking, not
generation") that justified Phase 4.

**Cause:** the seed rule requires an account to be **pass-through** (money in
*and* out). A FAN-OUT is one sender plus receive-only sinks; a BIPARTITE is
senders feeding sinks with no intermediary. **Neither contains a single
pass-through account**, so neither can ever be seeded, built, scored, or ranked.
The GARG-AML/bipartite/stack detectors never saw a candidate to score — which is
why those typologies did not move.

**Missed because** Phase 2 measured seed recall at 78.6% aggregated over ring
*accounts*, averaging over whole typologies sitting at zero.

### The fix (next task)

Seed on a **union of triggers**, not one rule:

- pass-through (current) — the layering typologies
- **fan-out degree** — FAN-OUT, and the source side of BIPARTITE
- **fan-in degree** — FAN-IN, and the sink side
- velocity / dormancy break — behaviourally odd accounts of any shape

All four are already computed. Cost is more candidates per tick, which the
ranking layer exists to absorb. **74% of rings are currently unreachable at any
ranking quality**, so this is the highest-value work available.

Then, in order: rebalance weights by measured prevalence (`gather_scatter` fires
on 50% of candidates and `cross_border` on 61% — near-constants that cannot
discriminate); re-run Phase 2 and Phase 4; consider raising
`find_gather_scatter` min_width from 2 to 3.

### 5b. CORRECTION (later session) — the 26%/0% diagnosis above does not hold

**This is wrong, and loudly:** `scripts/eval_funnel.py`, run over the full
10-day eval window with an explicit *seeded* stage between seed-reachable and
built, measures something materially different from §5 above:

| typology | seed-reachable | seeded | built | ranked (top-50) |
|---|---:|---:|---:|---:|
| BIPARTITE | 31 (100%) | 28 (90%) | **1 (3%)** | 0 (0%) |
| CYCLE | 37 (100%) | 31 (84%) | 21 (57%) | 3 (8%) |
| FAN-IN | 30 (100%) | 26 (87%) | 23 (77%) | 5 (17%) |
| FAN-OUT | 36 (100%) | 30 (83%) | 23 (64%) | 5 (14%) |
| GATHER-SCATTER | 38 (100%) | 35 (92%) | 29 (76%) | 8 (21%) |
| RANDOM | 26 (100%) | 22 (85%) | 13 (50%) | 3 (12%) |
| SCATTER-GATHER | 31 (100%) | 28 (90%) | 26 (84%) | 8 (26%) |
| STACK | 30 (100%) | **30 (100%)** | **4 (13%)** | 2 (7%) |
| **TOTAL** | **259 (100%)** | **230 (89%)** | **140 (54%)** | **34 (13%)** |

Not 26% built, not four typologies at 0%. **Seeding reaches 89% of active
rings overall, and BIPARTITE/FAN-OUT/RANDOM/STACK are seeded at 83-100%, not
0%.** The reason §5's diagnosis was wrong: the seed rule (`gen.seeds`) checks
whether an account is pass-through **against its whole position in the
window's graph**, not against its role inside one specific ring. An account
that is a receive-only sink *within* a FAN-OUT ring can easily be
pass-through *overall*, because AMLworld's background traffic gives almost
every active account both inbound and outbound edges from unrelated,
non-ring activity. §5 apparently measured seed recall in a way that didn't
capture this — restated here rather than silently corrected, per this
project's own rule about reporting when a result overturns a prior belief.

**Where the loss actually is**, per this measurement:

1. **Candidate-build for BIPARTITE and STACK specifically.** Both are
   seeded almost perfectly (90-100%) but collapse to 3% and 13% built. The
   seed fires, but two-hop expansion from that seed apparently does not
   assemble a candidate whose node set clears the hit floor (50% containment,
   0.3 Jaccard) against the ring — plausibly the hub guard (`EXPAND_MAX_DEGREE
   = 50`) or `EXPAND_MAX_NODES = 200` truncating before the far side of a
   2-layer/3-layer structure is reached. This is a candidate-generation
   problem, not a seeding problem, and needs its own instrumentation before
   the widened-seed-rule plan in §5 is worth building.
2. **A severe built→ranked drop, in every typology.** 54% built → 13% ranked
   overall is worse than the built→ranked drop for any single typology in
   isolation, meaning candidates that structurally cover a ring are
   routinely present but not scored into the top 50. This re-supports the
   **original Phase 2 conclusion that §5 says it overturned** ("the loss is
   in ranking, not generation") — which the Phase 4 re-ranker was built to
   address, and did measurably improve (§3), so that work was not wasted;
   it just was not the whole story either time.

Bootstrap 95% CIs (resampled over the 34 generation cycles;
`sentinel/eval/bootstrap.py`) on the headline numbers: p@10 = 0.085 [0.059,
0.115], p@20 = 0.049 [0.032, 0.065], p@50 = 0.024 [0.016, 0.032]. The re-ranker
lift CI is in `data/eval_phase4.json` under `lift_ci`, computed the same way
(paired, so it answers "does the lift survive resampling" directly rather than
via two separately-wide intervals).

**Practical implication for the next task:** do not implement the
union-of-seed-triggers fix in §5 as scoped — it targets a stage (seeding)
that is not actually where BIPARTITE/STACK are lost. Instrument the
candidate-build stage specifically (log why a seeded ring's expansion
produces no covering candidate: hub-guard truncation, node-cap truncation, or
genuine Jaccard failure) before changing the seed rule.

### 5c. Build-stage diagnosis — and a third correction

`scripts/diagnose_build.py` does exactly what 5b asked for: for every seeded
ring it expands from each seed member, records the best containment and
Jaccard achieved, and classifies the failure using a trace produced by the
*real* expansion path (`WindowedGraph.expand_traced`, which `expand` now
delegates to, so the trace cannot drift from the code it describes).

Over the same 34 cycles, 230 seeded rings, at the shipped settings
(hops=2, max_nodes=200, max_degree=50):

| outcome | rings | share |
|---|---:|---:|
| **BUILT** (clears containment ≥50% *and* Jaccard ≥0.3) | 115 | 50% |
| **DILUTION_FAIL** (≥50% of the ring found, then Jaccard <0.3) | 88 | **38%** |
| **CONTAINMENT_FAIL** (never reached ≥50% of the ring) | 27 | 12% |
| **FOUND at containment alone** | **203** | **88%** |

| typology | seeded | built | contain-fail | dilute-fail | mean cont. | mean Jacc. | ring | cand |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BIPARTITE | 28 | **0** | 12 | 16 | 0.43 | 0.14 | 6.4 | 15.2 |
| CYCLE | 31 | 17 | 0 | 14 | 0.90 | 0.32 | 4.4 | 14.5 |
| FAN-IN | 26 | 19 | 0 | 7 | 1.00 | 0.49 | 7.3 | 16.1 |
| FAN-OUT | 30 | 20 | 0 | 10 | 1.00 | 0.38 | 6.9 | 19.6 |
| GATHER-SCATTER | 35 | 23 | 0 | 12 | 1.00 | 0.51 | 7.4 | 17.7 |
| RANDOM | 22 | 10 | 1 | 11 | 0.91 | 0.31 | 4.4 | 17.3 |
| SCATTER-GATHER | 28 | 24 | 0 | 4 | 1.00 | 0.63 | 10.0 | 16.3 |
| STACK | 30 | **2** | 14 | 14 | 0.52 | 0.15 | 5.7 | 19.1 |

**Correction to 5b, which is the third reversal on this question.** 5b said
"the real loss is candidate-build for BIPARTITE/STACK". That is only
one-third right:

- **Expansion is not broken for six of the eight typologies.** CYCLE,
  FAN-IN, FAN-OUT, GATHER-SCATTER, SCATTER-GATHER and RANDOM all reach
  **mean containment 0.90–1.00** — expansion routinely recovers the *entire*
  ring. They "fail to build" only because the neighbourhood dragged in
  alongside (mean candidate ~15–20 nodes around a ~4–10 node ring) pushes
  Jaccard under the 0.3 floor.
- **38% of all seeded rings are found and then rejected by the metric**, vs
  12% genuinely not reached. The dominant term in the built-stage loss is
  **dilution, not discovery.**
- BIPARTITE and STACK *do* have a real containment problem (mean 0.43 and
  0.52), and they are the only two that do.

**All three expansion knobs are ruled out as the fix, by experiment:**

| config | BUILT | BIPARTITE found | STACK found | mean cand size |
|---|---:|---:|---:|---:|
| hops=2, deg=50 (shipped) | **115** | 16 | 16 | ~17 |
| hops=3, deg=50 | 48 | 16 | 16 | ~44 |
| hops=2, deg=500 | 112 | 16 | 16 | ~17 |

- **node_cap: 0 occurrences.** `EXPAND_MAX_NODES` is never the binding
  constraint. The 5b guess that it might be was wrong.
- **hub_guard: 4 occurrences**, and relaxing it 10× (deg 50→500) moves
  nothing — BIPARTITE and STACK stay at 16 found, total BUILT drops slightly.
  The 5b guess that the hub guard was "plausibly" the cause was also wrong.
- **hops=3 does not improve containment for BIPARTITE or STACK at all**
  (both still 16 found) while **more than halving total BUILT (115→48)**,
  because candidate size jumps ~17→~44 and Jaccard collapses everywhere.

So the 23 `hop_limit` containment failures are not "needs one more hop" —
given another hop, expansion still does not reach those members. BIPARTITE
and STACK members are genuinely not reachable from a *pass-through* seed
within the window. That is a structural property of seed-and-expand on those
two shapes, not a tuning parameter.

### 5d. Pruning shipped — it worked, and it broke something else

`sentinel/detect/prune.py` (`leaf2`, chosen by sweep, see §5c implications)
is now wired into `CandidateGenerator`. End-to-end re-runs of
`scripts/eval_funnel.py` and `scripts/eval_phase2.py`:

| funnel stage | before | after |
|---|---:|---:|
| seeded | 230 (89%) | 230 (89%) |
| **built** | 140 (54%) | **162 (63%)** |
| **ranked (top-50)** | 34 (13%) | **49 (19%)** |
| BIPARTITE built | 1 (3%) | 5 (16%) |
| STACK built | 4 (13%) | 9 (30%) |
| CYCLE built | 21 (57%) | 28 (76%) |

| metric | before (95% CI) | after (95% CI) | CIs overlap? |
|---|---|---|---|
| p@10 | 0.085 [0.059, 0.115] | 0.097 [0.068, 0.126] | yes — not distinguishable |
| p@20 | 0.049 [0.032, 0.065] | 0.079 [0.059, 0.100] | barely |
| **p@50** | 0.024 [0.016, 0.032] | **0.043 [0.033, 0.054]** | **no — real** |
| ring recall | 15.4% | **20.1%** | — |

**But the baselines re-tied, which is bug #8's exact pattern returning.**
`scripts/eval_phase2.py` runs `size` / `degree` / `random` alongside the
score. Before pruning the score dominated them completely. After:

| ranking | p@10 | p@20 | p@50 | ring recall |
|---|---:|---:|---:|---:|
| **score** | **0.097** | **0.079** | 0.043 | **20.1%** |
| size | 0.088 | 0.074 | **0.049** | 18.5% |
| degree | 0.062 | 0.071 | 0.047 | 16.6% |
| random | 0.000 | 0.001 | 0.002 | 5.0% |

The score's margin over a baseline that just counts nodes has collapsed from
roughly **7×** (ring recall 15.4% vs 2.3%) to **1.09×** (20.1% vs 18.5%) —
and **at p@50 the size baseline now beats the score outright** (0.049 vs
0.043).

Read honestly: **pruning is a real improvement to candidate generation and a
real problem for the scoring function.** More rings are reachable (recall
15.4% → 20.1%, and that part is genuine), but almost all of that gain is
available to a trivial ranker. The v1 hand-set score is no longer doing
meaningful discriminative work on the pruned candidate set.

Two readings, not yet separated:
1. Pruning normalised candidate size (mean 17 → 8.2 nodes), so node count
   went from an anti-signal (huge candidates trivially failed Jaccard) to a
   real one, and the score simply is not exploiting the tighter candidates.
2. The v1 score was always partly a size proxy, and pruning removed the
   noise that was hiding it.

Either way the conclusion is the same and it is not optional: **any headline
that quotes the pruned p@k must quote the size baseline next to it.**
"p@20 improved 61%" is true and misleading on its own; the size baseline
improved more, from 0.000 to 0.074.

**Next task is the scorer, not the generator.** The re-ranker CI result (§3)
already said the learned ranker's lift was noise at n=17; this says the
hand-set score is now barely above node-count. Those are the same finding
from two directions: ranking is where the remaining loss lives, and neither
current ranker is earning its place.

### 5e. Correction to 5d — the p@50 "size beats score" claim does not survive its own CI

5d's before/after CIs were computed from two **separate** runs (old stored
`funnel.json` vs a fresh one), which is the same weakness §3 already called
out for the re-ranker lift. `scripts/eval_prune_impact.py` redoes it properly:
both `prune_strategy=none` and `leaf2` are run over the **identical** 34
cycles, so the delta is a paired bootstrap (`sentinel/eval/bootstrap.py`,
resampled on matched pairs) rather than two independently-noisy intervals.

**Headline, paired (leaf2 − none), 2000 resamples:**

| k | none | leaf2 | delta | 95% CI | excludes 0? |
|---:|---:|---:|---:|---|---|
| 10 | 0.085 | 0.097 | +0.012 | [-0.021, +0.044] | no — 5d was right to hedge this one |
| 20 | 0.049 | 0.079 | +0.031 | [+0.010, +0.053] | **yes — real** |
| 50 | 0.024 | 0.043 | +0.019 | [+0.009, +0.029] | **yes — real** |
| 100 | 0.015 | 0.026 | +0.011 | [+0.006, +0.016] | **yes — real** |

So the generation-side gain is confirmed at k=20/50/100, not just claimed.

**Re-tie check, paired (score − size), same cycles:**

| k | under `none` (pre-prune) | under `leaf2` (post-prune) |
|---:|---|---|
| 10 | +0.085 [+0.059,+0.115] real | +0.009 [-0.027,+0.041] **gone — not proven either way** |
| 20 | +0.049 [+0.032,+0.065] real | +0.006 [-0.021,+0.031] **gone** |
| 50 | +0.023 [+0.015,+0.031] real | -0.007 [-0.019,+0.005] **gone** (point favours size, CI includes 0 — 5d's "size beats score at p@50" is *not* statistically established) |
| 100 | +0.012 [+0.007,+0.017] real | -0.009 [-0.016,-0.002] **size significantly beats score, confirmed** |

**Correction to 5d:** the p@50 reversal it reported as a fact is a point
estimate whose own CI includes zero — by this project's own rule (§3, "a
gain whose interval includes zero is not a gain"), that rule cuts both ways
and the same discipline applies to a claimed *loss*. What paired resampling
actually confirms is narrower and arguably worse: **score's entire margin
over a trivial node-count ranker has collapsed to statistical noise at
k=10/20/50**, and at k=100 the reversal is real. 5d's practical conclusion
stands regardless of this correction — the scorer is the next task — but the
evidence for it is "the score no longer clearly beats size," not "size now
clearly beats score."

**Per-typology built, corrected to the distinct-ring funnel (`eval_funnel.py`
semantics — a ring counts once if built in *any* cycle it was active, not
once per cycle; an earlier per-cycle-instance version of this table produced
misleading swings and was discarded):**

| typology | seeded | built before | built after | delta |
|---|---:|---:|---:|---:|
| BIPARTITE | 28 | 1 | 5 | +4 |
| CYCLE | 31 | 21 | 28 | +7 |
| **FAN-IN** | 26 | 23 | **21** | **-2** |
| FAN-OUT | 30 | 23 | 24 | +1 |
| GATHER-SCATTER | 35 | 29 | 31 | +2 |
| RANDOM | 22 | 13 | 17 | +4 |
| SCATTER-GATHER | 28 | 26 | 27 | +1 |
| STACK | 30 | 4 | 9 | +5 |
| **TOTAL** | 230 | 140 | 162 | +22 |

**FAN-IN got slightly worse, and this was not caught before shipping.**
`scripts/sweep_prune.py`'s own diagnostic (the one the ship decision was made
from) measures best-containment/best-jaccard per ring across every seed
attempt in isolation, ignoring the generator's real dedup and
overlap-suppression pipeline (`sentinel/detect/merge.py`). The full pipeline
disagrees with it for FAN-IN: 23→21 distinct rings built, and ranked drops
5→4 with it. Plausible mechanism, not yet confirmed: FAN-IN's ring members
are receive-only sinks around a hub, and `leaf2`'s far-leaf rule keeps
1-hop-from-seed nodes unconditionally but can still drop a legitimate
far-side sink whose only path back into the candidate is a single edge —
the same shape the shipped commit message worried about for FAN-OUT (which
did *not* regress) but did not check for FAN-IN specifically. **Flagged, not
fixed.** Every other typology matches sweep_prune's directional claim
(BIPARTITE, CYCLE, GATHER-SCATTER, RANDOM, SCATTER-GATHER, STACK all
improved in the full pipeline too), so this is a one-typology exception, not
a reason to distrust the strategy overall — but "improves BUILT for *every*
typology" (0b3157f's commit message) is not quite true and is corrected here.

**Why BIPARTITE and STACK improved — checked, not assumed.** Pruning only
removes nodes, so it cannot raise containment; it can only be *found and then
rescued* on rings that already reached ≥50% containment pre-prune and were
purely Jaccard-rejected. `data/build_diagnosis_h2_d50.json` shows exactly
that pool: 16 of 28 seeded BIPARTITE rings and 14 of 30 seeded STACK rings
were `dilution_fail` (containment cleared, Jaccard didn't) before pruning
shipped. BIPARTITE's 1→5 and STACK's 4→9 built counts are drawn from those
pools and are smaller than the pools' ceiling, consistent with a partial,
legitimate rescue rather than a scoring artifact.

Reproduce: `python scripts/eval_prune_impact.py` (writes
`data/prune_impact.json`; ~40 min, runs both strategies over the same 34
cycles).

### What this actually implies

1. **The single highest-value change is candidate pruning, not wider
   expansion.** 88 rings are already inside a candidate and are being thrown
   away for carrying passengers. Pruning a candidate to its structurally
   connected core before scoring raises Jaccard *legitimately* — it makes the
   candidate genuinely tighter rather than moving the goalposts.
2. **Do not simply lower the Jaccard floor.** That would convert 88 rings to
   "built" overnight and inflate every headline number without improving the
   detector at all. The floor exists because a containment-only metric let a
   node-count baseline tie the score (bug #8). Any change to it must re-run
   the `size`/`degree`/`random` baselines to show they do not re-tie —
   otherwise it is the same mistake a second time.
3. **BIPARTITE and STACK need a different generator, not a tuned one.**
   Seed-and-expand from a pass-through account cannot reach them. A
   bipartite/stack-specific construction (e.g. seeding on a *pair* of layers,
   or building from the GARG-AML layer decomposition directly) is the honest
   path; more hops is not.

---

## 6. Bugs found and fixed — the portfolio

Every one produced a **plausible wrong answer** rather than an error. That is
the failure mode this project is built to resist.

| # | Bug | Impact |
|---|---|---|
| 1 | Bank IDs zero-padded in transactions, not in accounts | Every registry lookup silently missed; reported 0% of rings cross a border. Truth is 89%. |
| 2 | Nested `BEGIN` swallowed the enclosing pattern block | 3 blocks → 1 ring, no diagnostic |
| 3 | `parse_row` truncated over-long rows | Values mapped to wrong columns while "succeeding" |
| 4 | `account_key("")` collided with genuine bank `0` | Silent entity merge |
| 5 | `parse_country` invented countries from bank names | "Savings Bank #12" → country "Savings" |
| 6 | `amount_key` rounded to 2dp | 0.005 and 0.01 collided in the label join |
| 7 | **Source CSV not time-ordered** (47.6% of pairs reversed) | Would have fed the detector scrambled time |
| 8 | **Metric rewarded candidate size** | A size-only baseline *tied* the score at p@10 = 0.138; the honest number was ~half |
| 9 | `rank()` took a dict, live candidates carry a dataclass | Train/score representation mismatch |
| 10 | Simulated analyst's 3% false-confirm rate | Equalled genuine positives; corpus half noise, model learned nothing |
| 11 | Permutation importance on **accuracy**, then on **training data** | Reported 0.0000 for every feature while the model re-ranked 4× better |
| 12 | **Length-2 "cycles" are mutual pairs** | 91% of cases flagged CYCLE; highest-weighted feature was a constant |
| 13 | **Seed rule structurally excludes typologies** | See §5 — open |

### Two leaks found in the benchmark, deliberately unused

1. **`Payment Format` is a 7.3× giveaway** — 86.6% of laundering is ACH against
   an 11.8% base rate. Generator artifact. Excluded from every feature; a test
   asserts it can never re-enter.
2. **The tail is 91% laundering** — days 0–9 hold 99.98% of edges; days 10–17
   hold 715 edges of which 652 are laundering. Evaluation ends at day 10.

---

## 7. The distributed-computing idea — verdict: don't build it

The proposal: SETI@home-style, use idle company laptops for fraud detection
compute.

**The instinct is sound; it is wrong for this problem.**

1. **The data cannot leave.** SETI@home worked because telescope data is not
   sensitive. This needs transaction records — PII and financial data. Under
   RBI's PA Directions, PMLA, and the DPDP Act 2023 you cannot distribute
   customer financial data to employee laptops. A legal wall, not a preference.
2. **Compute is not the bottleneck** — and this project's own numbers prove it.
   Leiden on 280k pairs: 6s. Full 4.5M-edge replay: 19s. GFP beats GNNs on CPU.
   The bottleneck is analyst throughput.
3. **Economics invert.** Razorpay runs on AWS with idle nightly capacity; spot
   instances cost cents. Orchestrating laptops that sleep and disconnect costs
   more engineering than the compute is worth — BOINC handled unreliability by
   sending each task to 3+ machines, burning 3× the work.
4. **New attack surface** on employee endpoints, which security will refuse.

**The good version of the same instinct: federated / privacy-preserving
collaborative detection.** Data stays inside each institution, only model
updates travel. This maps directly onto India's live problem — **RBI's DPIP
exists precisely because banks and PAs cannot share raw data but need shared
fraud signal**, and mule rings span institutions so no single player sees the
whole ring. Strong "future work" section; needs multiple parties, so not
buildable solo now.

---

## 8. India context — the strongest positioning available

- **524,121** suspected mule accounts flagged in March 2026 alone
- **2.47 million** Layer-1 mule accounts flagged by I4C
- RBI **MuleHunter.AI** in **23 banks** (Dec 2025 RTI response; see §4 — the
  "26 banks / ~20,000 accounts monthly" figures used here previously were not
  independently verified, and the RBI declined under RTI to disclose accounts
  identified); **DPIP** (RBI + NPCI) for cross-institution signal sharing
- Reporting explicitly names **payment-aggregator merchant accounts** as the
  weaponised vector — *"fraudulent accounts can look identical to legitimate
  businesses"*

MuleHunter runs inside banks. DPIP shares between institutions. **Neither sits
at the payment-aggregator merchant layer** the reporting names. That gap is
genuine and is the sharpest pitch.

Also: STR must be filed within **7 working days of forming suspicion**, and
protracted internal review is the most-cited cause of late filing. This product
compresses both clocks.

---

## 9. Repo and environment state

```
sentinel/
  schema.py            normalised Edge / LabeledRing, account_key, amount_key
  config.py            EVAL_END, windows, expansion bounds, excluded features
  data/                patterns parser (ParseReport), account registry
  stream/replay.py     time-ordered tick replay
  graph/window.py      sliding-window graph, incremental expiry
  graph/stats.py       per-account Welford moments, behavioural measures
  detect/              motifs, layers (GARG-AML), features, candidates, merge
  cases/               case record, store (append-only), manager (capacity+control)
  learn/               reranker, simulated analyst
  api/app.py           console API
frontend/              console UI
scripts/               verify_patterns, build_stream, eval_phase2/4,
                       eval_vs_published, build_queue, run_replay
docs/                  PHASE0-FINDINGS, PHASE2-FINDINGS, PHASE4-FINDINGS,
                       ARCHITECTURE-V2, sentinel-design.html, this file
```

- Python 3.14. `leidenalg`, `igraph`, `networkx`, `sklearn`, `pandas`, `pyarrow`
  installed. `snapml` unavailable for 3.14.
- Data is gitignored. Rebuild: download the three `HI-Small_*` files into
  `data/amlworld/`, then `python scripts/build_stream.py`.
- Console: `python scripts/build_queue.py` then `run.bat` / `run.sh`,
  open http://127.0.0.1:8000
- Commits are authored `Pranav <pranav2024vv@gmail.com>`, co-authored Claude
  Opus 5 (deliberate — it is an AI buildathon).

### Not built, and stated as such

Kafka ingest, admin-panel deep links, case-management push, real execution of
payout holds or step-up auth. Batch actions are simulated and labelled.
**There is no trained model in v1 and no GNN** — you cannot train a supervised
ring detector before you have confirmed rings, which is why the label pipeline
is the actual product.

---

## 10. Remaining before submission

**This list was written before §5b–§5e and is stale in two ways. Corrected in
place rather than rewritten, because the correction is the useful part.**

1. ~~**Widen seeding** (§5) — the only change that can move recall off 15%~~
   **DO NOT DO THIS.** §5b measured the funnel with an explicit *seeded* stage
   and found seeding already reaches **89%** of active rings, not the 26% §5
   reported. §5b's own words: *"do not implement the union-of-seed-triggers fix
   in §5 as scoped — it targets a stage that is not actually where
   BIPARTITE/STACK are lost."* §5c then ruled out all three expansion knobs by
   experiment. The item survived four rounds of corrections above it purely
   because nobody edited this list, and a fresh session reading top-down would
   have spent a day on it.
   Also stale: **ring recall is 20.1%, not 15%** (§5d, post-prune).
   The live version of this item is §12: the scorer, not the generator.
2. Rebalance weights by measured prevalence, re-run Phase 2 + Phase 4
3. Update README with current numbers and the Vulcan positioning (name it
   explicitly; complementary, not competitive)
4. Foreground the mule-network / payment-aggregator angle
5. Five-minute pitch video — lead with the workflow, not the graph
6. Final benchmark comparison **after** the architecture is complete (deferred
   deliberately; measuring a half-built system against a finished one is
   meaningless)

---

## 11. Economics, drafting, and calibration (added this session)

Three components built after the §10 list was written, each aimed at a clause
of the track's bar that nothing in the repo previously answered.

### 11a. Cost model — `sentinel/economics/`

The bar names false-positive cost explicitly and there was no cost model
anywhere in the codebase. There is now.

**The headline is a break-even precision, not a rupee figure**, and the design
reason matters: an absolute expected-loss number needs the value at risk behind
an average ring, which nobody building on a public benchmark knows. Quoting one
would be bug #8's category — a confident number resting on an unchecked
assumption.

Better, the model **inverts**. `CostModel.required_value_at_risk(p)` solves for
the ring value at which a queue of precision `p` breaks even:

| depth | measured p@k | pays if the average ring has more than |
|---|---:|---:|
| top 10 | 0.097 | 66,384 at risk |
| top 20 | 0.079 | 82,324 at risk |
| top 50 | 0.043 | 154,236 at risk |

Nobody has to accept the cost inputs to check that claim. Every default is a
labelled placeholder; `unsourced()` names the ones still resting on nothing and
`scripts/eval_cost.py` prints that warning above the results. `sensitivity()`
sweeps each input so a conclusion that survives an order of magnitude can be
identified as not depending on that input.

One genuine architectural finding fell out of building it: **because actions are
human-gated, the false-positive cost is mostly labour, not merchant harm.** The
gate converts customer harm into analyst time. The residual is modelled
explicitly with an analyst-false-approval rate rather than assumed to zero.

**Still to do:** ground the six placeholder inputs. Until then the absolute
rupee figures must not be quoted — only the break-even and the inversion.

### 11b. LLM drafting under the existing citation contract — `sentinel/llm/`, `sentinel/narrative/`

`str_narrative.py`'s docstring had pre-committed to this contract while the
module was still template-only: *"If narrative drafting is ever routed through
an LLM instead, the contract does not change."* It now is, and it doesn't.

`draft_and_verify` tries a model draft, runs the **identical** `verify()` over
it, and on failure discards the draft whole and falls back to the template. A
rejected draft is never partially salvaged and never filed. Provenance —
source, model, failure reason, the rejected text and its specific failures —
goes into the response so a filed narrative always says who wrote it.

**Why this was worth building at all:** the template's sentences carry citations
by construction, so the verifier could never reject anything. A check that
cannot fail is not evidence. LLM output can fail it, which makes the rejection
rate a real metric — tracked in `sentinel/narrative/metrics.py`, exposed at
`/api/llm/status`, persisted to `data/draft_ledger.jsonl`.

Two properties are locked by tests: with no key the behaviour is byte-identical
to before, and nothing in `sentinel/detect` or `sentinel/eval` may import
`sentinel.llm` — a non-deterministic component inside a measured path would
contaminate every reported interval.

**CORRECTION — the second of those two tests did not exist when this paragraph
was written.** Only the first was real (`test_client_returns_not_configured_
without_a_key`, `test_unavailable_model_falls_back_silently`). The import
boundary was a docstring promise with nothing behind it, asserted here in the
past tense for several sessions. It exists now:
`tests/test_import_boundaries.py` checks it in a subprocess against the
*transitive* module set for every module in `sentinel.detect` and
`sentinel.eval`, and is a CI gate. It also includes a test that the probe
itself can fail, pointed at a module that genuinely does import `sentinel.llm`
— this file already records one check that could never fail (the template
narrative's citations were correct by construction), and an unfailable check is
not evidence.

OpenRouter was chosen over a vendor SDK because the endpoint is
OpenAI-compatible, so `OPENROUTER_BASE_URL` repoints the whole path at a
self-hosted vLLM or Ollama instance with no code change. That is the answer to
"does data leave the box" — demonstrated, not promised.

### 11c. Calibration loop — `sentinel/learn/calibrate.py`

Online reweighting from analyst verdicts, reading **aggregate counts only**. The
transaction graph is never an input, and a test verifies that against the
transitive import set in a subprocess (a direct-import check would pass while a
dependency dragged pyarrow in behind it).

The design turns on three things:

1. **The control arm makes the estimate valid.** A loop fed only by verdicts on
   surfaced cases learns only about the top of its own queue and converges onto
   its own blind spots. `CONTROL_FRACTION = 0.10` random draws from below the
   cut are the unbiased sample; both lanes combine by inverse-propensity
   weighting. **Caveat:** the control propensity is approximated as
   `1/CONTROL_FRACTION`. The true value is `n_control/len(rest)` per cycle and
   is not recorded on the case. Recording it at `CaseManager.select` time would
   make this exact — a small change, flagged not done.
2. **The evidence gate.** No weight moves until a bootstrap CI on that term's
   lift excludes 1.0, plus a minimum-observations floor per arm. Given how wide
   the intervals already are at n = 17 to 34, an ungated update rule would chase
   noise confidently — bug #14 waiting to happen.
3. **Shrinkage and renormalisation**, preserving the sum-to-1.0 invariant
   `features.py` asserts.

Every term is written to the audit record including the ones that did **not**
move and the reason — a log listing only changes cannot be audited.

`insufficient_evidence` is excluded from both arms rather than counted negative;
treating "the analyst could not tell" as "not a ring" would bias every term
toward zero lift.

**Still to do:** the replay demo — run the loop across the 10-day stream and
show weights moving with the cost curve alongside. Needs the compiled stream.

### 11d. Corrections to §10's premises

- **Tests: 363**, not 192 and no longer 308.
  **Superseded: 416 passing + 1 xfail** as of §12. Note that this document
  carried *two different* test counts simultaneously for several sessions — the
  header said 308 while this line said 363 — which is the same failure the
  claims ledger in the uplift plan (§6.6) is designed to prevent: a number
  quoted in prose with nothing checking it against the artifact that produced
  it. The header is now a single figure and `python -m pytest -q` is the only
  authority for it.
- **The working tree was clean**, not carrying CRLF churn — but 15 commits were
  unpushed, so the public repo was missing the entire pruning workstream and
  every correction in §5b to §5e. `.gitattributes` added regardless.
- **Elliptic2 is publicly available on Kaggle**, not licence-gated. The §10
  framing that it required a manual licensed request is wrong about
  availability; `sentinel/data/elliptic2.py`'s docstring should be corrected
  when the real files are loaded.
- **Do not shorten `every_ticks` to widen the cycle count.** The window is 72h;
  cycles 6h apart already overlap heavily, and at 2h they are near-duplicates.
  Resampling near-duplicates narrows the interval spuriously. The honest route
  to a narrower interval is more independent data.
