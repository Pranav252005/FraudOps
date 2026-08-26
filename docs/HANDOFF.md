# Session handoff — FraudOps / Sentinel

Everything built, measured, and learned in this session. Written so a fresh
session can pick up without re-deriving anything.

**Repo:** https://github.com/Pranav252005/FraudOps
**Target:** Razorpay AI Buildathon, AI Risk Manager track. One class of loss:
money-movement / mule rings. Defence only.
**Tests:** 192, all passing.

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
| 10 | 6.4% | 7.5% | **0.069** | 10× |
| 100 | 1.7% | 15.9% | 0.031 | 3× |

---

## 4. How this compares

### Published on the same HI-Small dataset — all **supervised**

| System | Minority-class F1 |
|---|---:|
| Standard GNN, no adaptations | 26.9% |
| GNN + reverse MP + port numbering + ego IDs | 42.9% |
| GIN, adapted | 57.2% |
| **This project (unsupervised)** | **0.069** |

**Roughly 6× worse.** Theirs train on the labels; this uses none. Different
task, but the gap is real and should not be explained away.

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
patterns**, operational in 26 banks, ~20,000 mule accounts flagged monthly.
Runs **inside banks on bank-account data**.

The 19 patterns are unpublished; the industry typology they draw on is
implemented here — pass-through velocity, the 80%-within-48h rule, dormancy,
fan-in from unrelated senders.

### IBM Graph Feature Preprocessor (ICAIF 2024) — the most important comparison

GFP reports **higher minority-class F1 than standard GNNs** using hand-
engineered subgraph features plus gradient boosting, on CPU. **This is the
architecture class this project is already in**, which means the ceiling here is
far above current numbers. `snapml` has no Python 3.14 build, so its feature set
was implemented directly.

Coverage vs GFP: fan-in/out ✅, degree ✅, scatter-gather ✅, gather-scatter ✅,
simple cycle ✅, temporal cycle ✅, vertex statistics with skew/kurtosis ✅.
Essentially at parity.

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
- RBI **MuleHunter.AI** in 26 banks; **DPIP** (RBI + NPCI) for cross-institution
  signal sharing
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

1. **Widen seeding** (§5) — the only change that can move recall off 15%
2. Rebalance weights by measured prevalence, re-run Phase 2 + Phase 4
3. Update README with current numbers and the Vulcan positioning (name it
   explicitly; complementary, not competitive)
4. Foreground the mule-network / payment-aggregator angle
5. Five-minute pitch video — lead with the workflow, not the graph
6. Final benchmark comparison **after** the architecture is complete (deferred
   deliberately; measuring a half-built system against a finished one is
   meaningless)
