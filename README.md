# Sentinel

**A fraud-ring investigation console for payment risk operations.**

Sentinel changes the unit of investigation from the transaction to the ring, and
delivers each ring pre-investigated.

The bottleneck in fraud operations is not detection — every risk team already
has detectors producing more alerts than it can work. The bottleneck is
investigation throughput: analysts spend most of their time assembling evidence
and a minority on the judgment that actually needs a human. Sentinel attacks
that, so the same team holds an order of magnitude more ground under continuous
review.

Built for the Razorpay AI Buildathon, **AI Risk Manager** track. One class of
loss: **money-movement / mule rings**. Strictly defence-only.

---

## Status

| Phase | What it does | State |
|---|---|---|
| 0 — Data | Ground-truth parsing, account/jurisdiction registry | ✅ verified |
| 1 — Replay | Time-ordered stream compilation, sliding-window graph | ✅ verified |
| 2 — Detection | Seed-and-expand, motif matching, scoring, ranking | ✅ measured |
| 3 — Cases | Immutable case records, verdict loop, label corpus | ✅ built |
| 4 — Re-ranker | Learned queue ordering from analyst verdicts | ⬜ next |
| 5 — Console | Case queue, subgraph view, disposition UI | ⬜ |

**118 tests, all passing.**

---

## What is real and what is not

**Real:** graph construction over a public benchmark, candidate generation,
motif detection, scoring and ranking, the case record, the disposition loop,
the point-in-time label store, and the evaluation harness with baselines.

**Described, not built:** Kafka ingest from a live transaction topic, deep links
into an internal admin panel, case-management push, and real execution of payout
holds or step-up authentication. Batch actions are simulated and labelled as
such.

**Not claimed:** there is no trained model in v1, and no graph neural network.
You cannot train a supervised ring detector before you have confirmed rings —
which is exactly why v1 is unsupervised and why the label pipeline is the actual
product.

---

## Honest results

Measured over 10 days of the AMLworld `HI-Small` benchmark, 34 generation runs,
259 ground-truth rings with ≥3 accounts visible in-window.

A candidate counts as a hit when it contains ≥50% of a ring **and** reaches
Jaccard ≥ 0.3 against it.

| ranking | p@10 | p@20 | p@50 | ring recall |
|---|---:|---:|---:|---:|
| **score** | **0.068** | **0.049** | **0.026** | **18.1%** |
| size | 0.000 | 0.000 | 0.001 | 2.3% |
| degree | 0.000 | 0.001 | 0.005 | 2.7% |
| random | 0.003 | 0.006 | 0.003 | 4.6% |

**This is not good enough to ship as a queue.** p@20 = 0.049 means an analyst
works twenty cases to find one ring, and 18.1% recall sits against a structural
ceiling of 73.3%. It is the unsupervised v1 floor with hand-set weights — the
number the learned re-ranker has to beat, not a finished product.

Per-typology recall, **including the blind spots**:

| Typology | Recall | | Typology | Recall |
|---|---:|---|---|---:|
| SCATTER-GATHER | 55% | | RANDOM | 23% |
| GATHER-SCATTER | 37% | | BIPARTITE | 13% |
| FAN-IN | 33% | | **STACK** | **7%** |
| FAN-OUT | 31% | | | |
| CYCLE | 30% | | | |

`STACK` and `BIPARTITE` are the multi-layer typologies and have no dedicated
motif detector. That is a known gap, published rather than hidden.

---

## Two leaks found in the benchmark, and deliberately not used

**1. `Payment Format` is a 7.3× giveaway.** 86.6% of laundering rows are ACH
against an 11.8% base rate. It is a generator artifact, the same class of defect
as PaySim's `amount == oldbalanceOrig` shortcut. **It is excluded from every
scoring feature**, and a test asserts it can never re-enter.

**2. The tail is 91% laundering.** Days 0–9 carry 99.98% of edges; days 10–17
carry 715 edges of which 652 are laundering. Evaluating across the full span
would make "timestamp after day 10" a near-perfect classifier. **Evaluation ends
at day 10**, which costs 7 rings and tightens the recall ceiling from 76.2% to
73.3%.

Both are documented in [`docs/PHASE0-FINDINGS.md`](docs/PHASE0-FINDINGS.md).

---

## A metric bug that would have doubled the headline number

The first results showed the score at p@10 = 0.138 — **tied exactly by a
baseline that just ranks candidates by node count.**

Containment-at-50% rewards bulk: a 158-node candidate trivially contains half of
a 4-account ring. The metric was measuring size as much as quality. Adding a
Jaccard floor collapsed the `size` baseline to 0.000 while the score held.

Reported because the uncorrected number would have been roughly double its
honest value and largely an artifact.

---

## Design decisions that measurement overturned

Three things in the original design document did not survive contact with data.

**Hour-of-week baselines are dead.** Hourly volume is flat — 178k edges every
hour. There is no seasonality to learn, so the predecessor system's core
component was not ported.

**Value conservation is a ring property, not a node trigger.** As a seed it
gives 4.0× lift at only 3.9% recall, because laundering accounts do not
individually conserve — the ring conserves as a whole. Moved to boundary-level
scoring.

**Community detection is the wrong primary tool here.** Leiden achieves 78–82%
ring coverage but only **1–2% workable**: nearly every covered ring lands inside
a 4,000–8,000 node community, and hub suppression at four thresholds barely
moves it. Two-hop seed-and-expand from a single member recovers a **median 100%**
of the ring with neighbourhoods **median 14 nodes, 99% under 60**. Leiden is
retained as the documented platform-scale path and is not used on this data.

Full reasoning in [`docs/PHASE2-FINDINGS.md`](docs/PHASE2-FINDINGS.md).

---

## Architecture

```
stream ──► windowed graph ──► seed & expand ──► motifs + features
                                                      │
                              ranked queue ◄── score ─┘
                                    │
                              case record ──► analyst verdict ──► label corpus
                                                                        │
                                                        re-ranker ◄─────┘
```

Cost scales with **anomaly volume**, not transaction volume: the global graph is
never clustered, only bounded neighbourhoods around anomalous seeds.

| Module | Role |
|---|---|
| `sentinel/schema.py` | Normalised `Edge` / `LabeledRing`; the adapter boundary |
| `sentinel/data/` | Ground-truth parser, account & jurisdiction registry |
| `sentinel/stream/` | Time-ordered replay in fixed ticks |
| `sentinel/graph/` | Sliding-window graph, incremental add and expiry |
| `sentinel/detect/` | Seeds, expansion, motifs, features, scoring, suppression |
| `sentinel/cases/` | Immutable case records, verdict taxonomy, label store |

### The label pipeline is the point

Every case is written once at alert time and never recomputed. Features are
snapshotted as scored — recompute them later and an account's degree includes
edges that did not exist when it was flagged, which is the fatal leakage in
fraud ML.

Verdicts are not a thumbs-up: `confirmed_ring`, `confirmed_partial`,
`not_a_ring`, `benign_explained`, `insufficient_evidence`. **Partial
confirmation is the highest-value label** — it yields node-level positives and
negatives inside one subgraph.

A **control arm** samples unflagged candidates into the same queue. Without it
the corpus only describes what the detector already finds, the next model
inherits this one's blind spots, and production recall cannot be estimated at
all.

---

## Running it

```bash
pip install -r requirements.txt
```

Download `HI-Small_Trans.csv`, `HI-Small_accounts.csv` and
`HI-Small_Patterns.txt` from the
[IBM AMLworld dataset](https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml)
into `data/amlworld/`, then:

```bash
python scripts/verify_patterns.py
```

```bash
python scripts/build_stream.py
```

```bash
python scripts/eval_phase2.py
```

```bash
python -m pytest tests/ -q
```

---

## Data

[IBM AMLworld](https://github.com/IBM/AML-Data) `HI-Small` — 5,078,344
transactions, 515,088 accounts, 34 countries, 370 labelled rings across 8
typologies (NeurIPS 2023 Datasets & Benchmarks, CDLA-Sharing-1.0).

It is the only public dataset found that labels **rings** rather than only
transactions, which is what makes ring-level precision and recall reportable at
all.

It is synthetic and bank-transfer shaped rather than card-gateway shaped. The
normalised edge schema exists so a second adapter can point the same engine at
real card data.
