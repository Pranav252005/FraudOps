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
loss: **merchant-account abuse rings / money movement**. Strictly defence-only.

**363 tests, all passing.** `python -m pytest -q`

---

## Contents

- [What this is](#what-this-is)
- [Honest results](#honest-results)
- [False-positive cost](#false-positive-cost--the-part-most-detectors-skip)
- [Where the AI actually is](#where-the-ai-actually-is)
- [Data residency](#data-residency--nothing-sensitive-has-to-move)
- [Open problems](#open-problems-stated-not-buried)
- [The bug portfolio](#the-bug-portfolio)
- [Architecture](#architecture)
- [Running it](#running-it)
- [Positioning](#positioning)

---

## What this is

A ring arrives on an analyst's screen as a **case file**, not a score: the
accounts, their roles, the transactions behind every claim, the structural
features that caused the alert with their individual contributions to the rank,
and a drafted suspicious-activity narrative in which every factual sentence
carries a citation to a specific transaction id.

Two multipliers: one analyst decision covers roughly eight accounts instead of
one, and the case arrives with the evidence already assembled.

| Phase | What it does | State |
|---|---|---|
| 0 — Data | Ground-truth parsing, account/jurisdiction registry | verified |
| 1 — Replay | Time-ordered stream compilation, sliding-window graph | verified |
| 2 — Detection | Seed-and-expand, motifs, scoring, overlap suppression | measured |
| 2v2 — Structure | Temporal cycles, behavioural axis, GARG-AML layers | measured |
| 3 — Cases | Immutable case records, verdict taxonomy, label corpus | built |
| 4 — Re-ranker | Learned queue ordering from analyst verdicts | measured |
| 5 — Console | Case queue, subgraph view, disposition UI | verified live |
| 6 — Pruning | Candidate core extraction before scoring | measured |
| 7 — Economics | Cost model, break-even precision, cost-optimal depth | built |
| 8 — Drafting | LLM narrative under the citation contract | built |
| 9 — Calibration | Online reweighting from aggregate verdict counts | built |

### The track's bar, answered literally

> *"Build a working detector, verifier or auto-responder for one class of loss,
> with measured precision and recall on a held-out test set."*
> *"Honest metrics including false-positive cost."*
> *"Strictly defence-only: anything offence-capable is disqualified."*

- **Measured precision and recall** — below, with baselines and bootstrap
  confidence intervals on every headline. See the caveat on held-out splitting
  in [Open problems](#open-problems-stated-not-buried); it is stated rather
  than glossed.
- **False-positive cost** — [`sentinel/economics/`](sentinel/economics/), with
  the break-even inverted so the conclusion does not rest on an assumed number.
- **Defence-only** — every action is enumerated in
  [`sentinel/escalation.py`](sentinel/escalation.py), and nothing executes
  without a recorded human disposition. Batch actions are simulated and
  labelled as such. There is no capability here that acts on an account
  without a person deciding first.

---

## Honest results

Measured over 10 days of the AMLworld `HI-Small` benchmark, 34 generation
cycles, 259 ground-truth rings with at least three accounts visible in-window.

A candidate counts as a hit when it contains at least 50% of a ring **and**
reaches Jaccard 0.3 or better against it.

| ranking | p@10 | p@20 | p@50 | ring recall |
|---|---:|---:|---:|---:|
| **score** | **0.097** | **0.079** | 0.043 | **20.1%** |
| size | 0.088 | 0.074 | **0.049** | 18.5% |
| degree | 0.062 | 0.071 | 0.047 | 16.6% |
| random | 0.000 | 0.001 | 0.002 | 5.0% |

**The `size` baseline is quoted beside every number on purpose, and it is not
flattering.** A baseline that ranks candidates by node count and nothing else is
currently within noise of the scoring function. Paired bootstrap over the same
cycles, score minus size:

| k | delta | 95% CI | verdict |
|---:|---:|---|---|
| 10 | +0.009 | [-0.027, +0.041] | not distinguishable |
| 20 | +0.006 | [-0.021, +0.031] | not distinguishable |
| 50 | -0.007 | [-0.019, +0.005] | not distinguishable |
| 100 | -0.009 | [-0.016, -0.002] | **size beats score** |

This is the most important honest statement in the repository, and it is
[an open problem](#open-problems-stated-not-buried), not a footnote.

### Where the loss lives

Ring recall decomposed into stages, distinct rings across all cycles:

| stage | rings | share |
|---|---:|---:|
| seed-reachable | 259 | 100% |
| seeded | 230 | 89% |
| built (candidate generated) | 162 | 63% |
| ranked into top 50 | 49 | 19% |

**Structural ceiling is 73.3%** — 88 of 370 rings have two or fewer accounts and
no community structure to detect. The dominant remaining loss is built to
ranked, which is ranking, not generation.

### What pruning bought, measured properly

Candidate pruning (`leaf2`) shipped after a paired A/B over the *identical* 34
cycles, not two separate runs:

| k | no pruning | leaf2 | delta | 95% CI | real? |
|---:|---:|---:|---:|---|---|
| 10 | 0.085 | 0.097 | +0.012 | [-0.021, +0.044] | no |
| 20 | 0.049 | 0.079 | +0.031 | [+0.010, +0.053] | **yes** |
| 50 | 0.024 | 0.043 | +0.019 | [+0.009, +0.029] | **yes** |
| 100 | 0.015 | 0.026 | +0.011 | [+0.006, +0.016] | **yes** |

Generation improved and it is confirmed. Scoring did not, and the size baseline
caught up. Both halves are reported.

### Standing rule

**Any headline that quotes p@k must quote the size baseline next to it.**
"p@20 improved 61%" is true and misleading alone — the size baseline improved
more, from 0.000 to 0.074. This rule exists because ignoring it once already
produced [bug #8](#the-bug-portfolio).

---

## False-positive cost — the part most detectors skip

A precision figure alone is not actionable. p@20 = 0.079 is either excellent or
unusable depending entirely on what a review costs and what a missed ring costs,
and neither appears in a confusion matrix.

```bash
python scripts/eval_cost.py
```

**The headline is a break-even precision, not a rupee figure.** Absolute
expected-loss numbers require knowing the value at risk behind an average ring,
which nobody building on a public benchmark actually knows. Quoting one would be
the same class of error as bug #8: a confident number resting on an assumption
nobody checked.

### The model inverts, and that is the point

Rather than assuming a ring value and deriving a threshold, the model **solves
for the ring value** at which each queue depth breaks even:

| depth | pays if the average confirmed ring has more than |
|---|---:|
| top 10 | 66,384 at risk |
| top 20 | 82,324 at risk |
| top 50 | 154,236 at risk |

Nobody has to accept the cost inputs to check that. They only have to decide
whether that much exposure behind a confirmed mule ring is plausible — a
question an ops lead can actually answer.

Every default input is a **labelled placeholder**. `CostModel.unsourced()` names
each one still resting on nothing, and the script prints that warning above the
results, because a cost model whose provenance is invisible is worse than none:
it launders a guess into a decision. `sensitivity()` reports how far the
break-even moves when each input is scaled, so a conclusion that survives an
order of magnitude does not depend on that input's exact value.

### Why the false-positive cost here is mostly labour

In a system that auto-actions, a false positive freezes a legitimate merchant's
payouts and the cost is customer harm. Sentinel's actions are human-gated and
enumerated, so a false positive is normally absorbed by an analyst dismissing
it — **the gate converts merchant harm into labour cost.** That is a real
architectural property, and it is not total: analysts approve some share of bad
recommendations, so the residual harm term stays in the model with an explicit
error rate rather than being assumed to zero.

---

## Where the AI actually is

There is no graph neural network here and no trained ring detector, and that is
a decision with a reason rather than a gap: **you cannot train a supervised ring
detector before you have confirmed rings.** Which is exactly why the label
pipeline is the product. Every component below earns its place on a measurement,
not on the fact that this is an AI buildathon.

### 1. Learned re-ranker — `sentinel/learn/reranker.py`

Trains on the analyst verdict corpus and reorders the queue. Held-out average
precision 0.2704 against a 0.0412 base rate.

**And its lift does not survive its own confidence interval.** Paired bootstrap
over the 17 held-out cycles gives deltas whose 95% intervals include zero at
every k. At this sample size the precision-at-k lift is not distinguishable from
noise, and it is not quoted as a settled result. The permutation-importance
ranking remains informative about which features carry signal.

### 2. LLM narrative drafting, under a pre-existing contract — `sentinel/narrative/`

The template generator produces text whose every sentence carries its citation
*by construction*, which means the citation verifier has nothing to reject
there. Good for a filed artifact, useless as evidence the verifier works: **a
check that cannot fail proves nothing.**

So drafting can route through a model, and the contract does not change. The
same `verify()` runs over the model's output. A fact-bearing sentence with no
citation, or a citation to an id absent from the case file, is a hard stop — the
draft is discarded whole, never partially salvaged, and the template runs
instead so the queue keeps moving.

**The rejection rate is the reportable metric**, tracked in
`sentinel/narrative/metrics.py` and exposed at `/api/llm/status`: N drafts
attempted, M stopped before filing, and how many rejected drafts reached a
filing — which must be zero, and a test asserts it.

The guardrail was written before the thing that needed guarding. The docstring
in `str_narrative.py` pre-committed to this contract while the module was still
template-only.

**Off by default.** With no key configured the system is byte-identical to a
build without it, and that is tested. Nothing in `sentinel/detect` or
`sentinel/eval` may import `sentinel.llm` — a non-deterministic component inside
a measured path would contaminate every reported interval, and a test enforces
it.

### 3. Online calibration from aggregate counts — `sentinel/learn/calibrate.py`

The loop that lets the scorer improve as analysts work the queue, **without the
raw transaction graph ever being an input.** It reads dispositions off the
append-only case store, reduces them to one 2x2 table per score term, and moves
the weights.

Three things make it defensible rather than a feedback loop that congratulates
itself:

**The control arm is what makes the estimate valid at all.** A loop trained only
on cases the detector surfaced learns only about the top of its own queue: a
term that would have caught rings nobody was ever shown accumulates no evidence
either way, and the system converges onto its own blind spots with rising
confidence. `CaseManager` already draws 10% of capacity at random from *below*
the cut, which is the unbiased sample of the unflagged population. Both lanes
are combined by inverse-propensity weighting.

**A weight does not move until its evidence excludes chance.** Every proposed
move carries a bootstrap CI on the term's lift, and a term whose interval
contains 1.0 does not move. The record says it did not move, and why — a
calibration log listing only changes cannot be audited, because the interesting
question after a quiet pass is which terms were considered and rejected.

**Updates shrink toward the current weight**, and renormalise to sum 1.0,
preserving the invariant the scorer already asserts.

Weights change, but every change is gated, logged, and reversible. A system that
"evolves on its own" is an audit problem, not a feature; this one evolves with a
paper trail.

### Where an LLM is deliberately *not* used

- **Not in the detector.** Non-deterministic and unmeasurable; it would
  contaminate the numbers that are the whole point.
- **Not in the calibration loop.** A closed-form update is auditable and an LLM
  reading statistics to adjust config is not — and it adds nothing the update
  rule does not already do.
- **Not as an agent that takes actions.** An LLM that can trigger a payout hold
  is unbounded and edges toward the offence-capable disqualifier. The human gate
  stays.

---

## Data residency — nothing sensitive has to move

Three independent properties, each verified rather than asserted:

**The benchmark carries no personal data.** AMLworld is synthetic and publicly
licensed. There is nothing in this repository that could leak.

**The calibration loop never reads records.** It consumes aggregate verdict
counts only. `sentinel/graph`, `sentinel/stream` and the parquet reader are
never imported, and a test verifies that against the *transitive* import set in
a subprocess — a direct-import check would pass while a dependency quietly
dragged the parquet reader in behind it. This is the property that makes the
same loop viable across institutions that cannot share records, which is the
shape RBI's DPIP exists to enable.

**Drafting runs wherever you point it.** The client speaks the OpenAI-compatible
`/chat/completions` contract, so a self-hosted vLLM or Ollama endpoint is one
environment variable:

```bash
OPENROUTER_BASE_URL=http://localhost:8000/v1
```

Nothing leaves the box. Or leave the key unset and the whole path is off. The
citation contract is identical in all three cases.

---

## Open problems, stated not buried

**1. The scorer no longer clearly beats a node-count baseline.** Post-pruning,
the score's margin over `size` has collapsed to statistical noise at k = 10, 20
and 50, and at k = 100 size wins significantly. Pruning normalised candidate
size (mean 17 to 8.2 nodes), so node count went from an anti-signal to a real
one and the hand-set weights are not exploiting the tighter candidates. This is
the next task, and the honest framing is "the score no longer clearly beats
size", not "size now clearly beats score" — a claimed *loss* has to clear its
own confidence interval too.

**2. The primary p@k is not measured on a clean held-out split.** The 34 cycles
that produced the headline numbers are the same cycles used to choose the prune
strategy and the Jaccard floor. Only the Phase 4 re-ranker figures use a
held-out split, and their CI includes zero. A time-split — tune on days 0 to 6,
report on days 7 to 9 — is the fix and is not yet done.

**3. BIPARTITE and STACK need a different generator, not a tuned one.** All
three expansion knobs were ruled out by experiment: raising hops from 2 to 3
more than halves total built candidates while moving neither typology, and
relaxing the hub guard tenfold moves nothing. Seed-and-expand from a
pass-through account structurally cannot reach those two shapes.

**4. FAN-IN regressed slightly under pruning** (23 to 21 distinct rings built)
and this was not caught before shipping, because the sweep diagnostic ignores
the real dedup and overlap-suppression pipeline. Flagged, not fixed.

**5. The control propensity is approximated.** Inverse-propensity weighting uses
`1 / CONTROL_FRACTION` as a stand-in; the true value is `n_control / len(rest)`
per cycle and is not currently recorded on the case. Recording it at selection
time would make this exact.

---

## The bug portfolio

Every one produced a **plausible wrong answer** rather than a crash. That is the
failure mode this project is built to resist, and it is the strongest evidence
in the repository.

| # | Bug | Impact |
|---|---|---|
| 1 | Bank IDs zero-padded in transactions, not in accounts | Every registry lookup silently missed; reported 0% of rings cross a border. Truth is 89%. |
| 2 | Nested `BEGIN` swallowed the enclosing pattern block | 3 blocks became 1 ring, with no diagnostic |
| 3 | `parse_row` truncated over-long rows | Values mapped to wrong columns while "succeeding" |
| 4 | `account_key("")` collided with genuine bank `0` | Silent entity merge |
| 5 | `parse_country` invented countries from bank names | "Savings Bank #12" became country "Savings" |
| 6 | `amount_key` rounded to 2dp | 0.005 and 0.01 collided in the label join |
| 7 | **Source CSV not time-ordered** (47.6% of pairs reversed) | Would have fed the detector scrambled time |
| 8 | **Metric rewarded candidate size** | A size-only baseline *tied* the score at p@10 = 0.138; the honest number was about half |
| 9 | `rank()` took a dict, live candidates carry a dataclass | Train/score representation mismatch |
| 10 | Simulated analyst's 3% false-confirm rate | Equalled genuine positives; corpus half noise, model learned nothing |
| 11 | Permutation importance on **accuracy**, then on **training data** | Reported 0.0000 for every feature while the model re-ranked 4x better |
| 12 | **Length-2 "cycles" are mutual pairs** | 91% of cases flagged CYCLE; the highest-weighted feature was a constant |
| 13 | **Seed rule believed to exclude typologies** | Investigated across three reversals; the real loss is dilution, not seeding |

Bug #8 is the one worth pausing on: the uncorrected headline would have been
roughly **double** its honest value and largely an artifact. It was found,
published, and turned into a standing rule that every p@k is quoted beside its
size baseline.

### Two leaks found in the benchmark, deliberately unused

**1. `Payment Format` is a 7.3x giveaway.** 86.6% of laundering rows are ACH
against an 11.8% base rate — a generator artifact, the same class of defect as
PaySim's `amount == oldbalanceOrig` shortcut. Excluded from every scoring
feature, and a test asserts it can never re-enter.

**2. The tail is 91% laundering.** Days 0 to 9 carry 99.98% of edges; days 10 to
17 carry 715 edges of which 652 are laundering. Evaluating across the full span
would make "timestamp after day 10" a near-perfect classifier. Evaluation ends
at day 10, costing 7 rings and tightening the recall ceiling from 76.2% to
73.3%.

Both documented in [`docs/PHASE0-FINDINGS.md`](docs/PHASE0-FINDINGS.md).

---

## Design decisions that measurement overturned

**Hour-of-week baselines are dead.** Hourly volume is flat — 178k edges every
hour. No seasonality to learn, so the predecessor system's core component was
not ported.

**Value conservation is a ring property, not a node trigger.** As a seed it
gives 4.0x lift at only 3.9% recall, because laundering accounts do not
individually conserve — the ring conserves as a whole. Moved to boundary-level
scoring.

**Community detection is the wrong primary tool here.** Leiden achieves 78 to
82% ring coverage but only 1 to 2% workable: nearly every covered ring lands
inside a 4,000 to 8,000 node community. Two-hop seed-and-expand recovers a
median 100% of the ring with neighbourhoods of median 14 nodes. Leiden is
retained as the documented platform-scale path and is not used on this data.

Full reasoning in [`docs/PHASE2-FINDINGS.md`](docs/PHASE2-FINDINGS.md).

---

## Architecture

```
stream ─► windowed graph ─► seed & expand ─► prune ─► motifs + features
                                                             │
                                  ranked queue ◄──── score ───┘
                                        │
                                  case record ─► analyst verdict
                                        │                 │
                          drafted narrative               ├─► label corpus ─► re-ranker
                                        │                 │
                              citation verifier           └─► calibration (counts only)
                                        │
                                hard stop or file
```

Cost scales with **anomaly volume**, not transaction volume: the global graph is
never clustered, only bounded neighbourhoods around anomalous seeds. Leiden on
280k pairs takes 6s; the full 4.5M-edge replay takes 19s. Compute is not the
bottleneck — analyst throughput is.

| Module | Role |
|---|---|
| `sentinel/schema.py` | Normalised `Edge` / `LabeledRing`; the adapter boundary |
| `sentinel/config.py` | Tuning constants, each with its measured justification |
| `sentinel/data/` | Ground-truth parser, account and jurisdiction registry, Elliptic2 loader |
| `sentinel/stream/` | Time-ordered replay in fixed ticks |
| `sentinel/graph/` | Sliding-window graph, incremental add and expiry, per-account moments |
| `sentinel/detect/` | Seeds, expansion, pruning, motifs, layers, features, scoring, suppression |
| `sentinel/cases/` | Immutable case records, evidence assembly, verdict taxonomy, label store |
| `sentinel/eval/` | Funnel instrumentation, bootstrap CIs, dataset-agnostic harness |
| `sentinel/learn/` | Re-ranker, simulated analyst, calibration loop |
| `sentinel/economics/` | Cost matrix, break-even precision, cost-optimal depth |
| `sentinel/narrative/` | STR narrative template, LLM drafting, citation verifier, ledger |
| `sentinel/compliance/` | FIU-IND references, DPDP purpose limitation and retention |
| `sentinel/llm/` | OpenRouter config and client — the only sanctioned LLM surface |
| `sentinel/escalation.py` | The enumerated, human-gated action set |
| `sentinel/api/` | Console API |

### The label pipeline is the point

Every case is written once at alert time and never recomputed. Features are
snapshotted as scored — recompute them later and an account's degree includes
edges that did not exist when it was flagged, which is the fatal leakage in
fraud ML.

Verdicts are not a thumbs-up: `confirmed_ring`, `confirmed_partial`,
`not_a_ring`, `benign_explained`, `insufficient_evidence`. **Partial
confirmation is the highest-value label** — it yields node-level positives and
negatives inside one subgraph. `insufficient_evidence` is excluded from both
arms of every calculation rather than counted as a negative; treating "the
analyst could not tell" as "not a ring" would bias every term toward zero lift.

A **control arm** samples unflagged candidates into the same queue. Without it
the corpus only describes what the detector already finds, the next model
inherits this one's blind spots, production recall cannot be estimated at all,
and the calibration loop has no unbiased sample to learn from.

---

## Running it

```bash
pip install -r requirements.txt
```

```bash
python -m pytest -q
```

The test suite runs with no dataset and no API key. So does the cost model:

```bash
python scripts/eval_cost.py
```

### The console

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
python scripts/build_queue.py
```

Then `run.bat` on Windows or `./run.sh`, and open http://127.0.0.1:8000

### Optional: LLM narrative drafting

Entirely optional. With no key set, drafting uses the deterministic template and
the system behaves exactly as it does without this feature.

```bash
cp .env.example .env
```

Add `OPENROUTER_API_KEY`, then verify the configuration resolves:

```bash
python scripts/check_llm.py
```

It distinguishes the three failure modes that matter: no key set, key valid but
model slug stale (a 404 that reads like an outage but is a typo — OpenRouter
slugs are versioned and they move), and a real completion. Every other knob —
endpoint, model, temperature, timeout, retries — is documented in
[`.env.example`](.env.example) and read by
[`sentinel/llm/config.py`](sentinel/llm/config.py).

To run against a self-hosted model instead, point `OPENROUTER_BASE_URL` at any
OpenAI-compatible endpoint. Nothing else changes.

### Evaluation

```bash
python scripts/eval_phase2.py        # p@k with size/degree/random baselines
python scripts/eval_funnel.py        # per-typology stage recall + bootstrap CIs
python scripts/eval_phase4.py        # re-ranker vs hand-set, paired CI on the lift
python scripts/eval_prune_impact.py  # paired same-cycle A/B on pruning (~40 min)
python scripts/eval_oracle.py        # supervised LightGBM ceiling on the features
python scripts/eval_vs_published.py  # threshold-free AP vs published GNN baselines
python scripts/eval_elliptic2.py     # second dataset: real labels, real data
python scripts/eval_cost.py          # break-even precision and cost-optimal depth
```

`eval_funnel.py` breaks ring recall into four stages — seed-reachable, seeded,
built, ranked — by typology, because a single ring-recall number cannot tell you
whether the loss is in seeding, generation, or ranking. Every headline it
reports carries a bootstrap 95% CI resampled over generation cycles, never a
bare point estimate.

`eval_prune_impact.py` runs both prune strategies over the **identical** cycles
so the delta is a paired bootstrap rather than two independently noisy
intervals — the same discipline the re-ranker CI demanded.

`eval_elliptic2.py` adds [Elliptic2](https://arxiv.org/abs/2404.19109) as a
second, real-labelled dataset: 122K labelled Bitcoin laundering subgraphs with a
published SOTA baseline (GLASS). Without the files present it validates the
loader and the dataset-agnostic evaluation path against a synthetic sample in
`tests/fixtures/elliptic2_sample/`, so the plumbing is provably correct before
the real data is in hand.

---

## Data

[IBM AMLworld](https://github.com/IBM/AML-Data) `HI-Small` — 5,078,344
transactions, 515,088 accounts, 30,528 banks, 34 countries, 370 labelled rings
across 8 typologies (NeurIPS 2023 Datasets and Benchmarks, CDLA-Sharing-1.0).

Compiled to a 48.9 MB parquet: 4,487,133 edges after dropping 591,211
self-loops, monotonic, 3,209 of 3,209 ring edges joined (100%). Replay runs at
233k edges per second.

It is the only public dataset found that labels **rings** rather than only
transactions, which is what makes ring-level precision and recall reportable at
all. It is synthetic and bank-transfer shaped rather than card-gateway shaped;
the normalised edge schema exists so a second adapter can point the same engine
at real card data.

Datasets are gitignored and separately licensed. Download instructions above.

---

## How this compares

### Published on the same dataset — all supervised

| System | Minority-class F1 |
|---|---:|
| Standard GNN, no adaptations | 26.9% |
| GNN + reverse MP + port numbering + ego IDs | 42.9% |
| GIN, adapted | 57.2% |
| **This project, unsupervised, threshold-free, whole population** | **AP 0.011 (1.7x base rate)** |

The fair like-for-like row is the threshold-free one, and it is weak. An earlier
top-10 slice figure (F1 0.068, "11x lift") is a fixed-cardinality-selection
artifact — five different uncalibrated operating points, with the best quoted —
and it should not be placed beside a calibrated whole-test-set decision. Those
baselines train on the labels; this uses none. That gap is real, and its size
should be read off the threshold-free row.

### Industry reality — the comparison that is fair

Production rule-based AML runs at **95 to 99% false-positive rates**; alert to
SAR conversion is **under 5%, with one bank survey finding 2.8%**. Investigation
burden reaches 22 hours per alert.

p@20 = 0.079 means roughly 8% of the top twenty are real rings — at or above
industry alert-to-report conversion. Not because this is good, but because the
industry standard is genuinely that bad, and because the cost model shows the
queue clears break-even by a wide margin at that precision.

---

## Positioning

**RBI MuleHunter.AI** runs inside banks, on bank-account data, across 26 banks
and around 20,000 mule accounts flagged monthly. **DPIP** (RBI and NPCI) shares
fraud signal between institutions. **Razorpay Vulcan** scores transactions and
flags entities at enormous scale — around 3 trillion data points across 4
billion payments — including cross-merchant detection.

Nothing public suggests any of them hands an analyst *"here are the nine
accounts that form this structure, here is the shape, and here is the evidence
for each claim."* Nor point-in-time labelling, a five-way verdict taxonomy, or
control-arm sampling.

This is complementary to Vulcan, not competitive with it. No public dataset and
no laptop closes a 3-trillion-datapoint gap, and this README does not pretend
otherwise. What it adds sits at a different layer: the investigation, not the
score.

**524,121** suspected mule accounts were flagged in March 2026 alone, and
**2.47 million** Layer-1 mule accounts by I4C. Reporting explicitly names
payment-aggregator merchant accounts as the weaponised vector — *"fraudulent
accounts can look identical to legitimate businesses."* MuleHunter sits inside
banks. DPIP sits between institutions. **Neither sits at the payment-aggregator
merchant layer**, and that gap is the sharpest case for this work.

Compliance timing matters too: an STR must be filed within seven working days of
forming suspicion, and protracted internal review is the most-cited cause of
late filing. This compresses both clocks.

---

## Not built, and stated as such

Kafka ingest from a live transaction topic, deep links into an internal admin
panel, case-management push, and real execution of payout holds or step-up
authentication. Batch actions are simulated and labelled as such.

There is no graph neural network and no trained ring detector — see
[Where the AI actually is](#where-the-ai-actually-is) for why that is a decision
rather than an omission, and what is trained instead.

---

*Commits are co-authored with Claude Opus 5, deliberately and visibly. It is an
AI buildathon; using the tools and saying so is the honest position.*
