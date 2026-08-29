# FraudOps v2 — architectural refinement

Derived from four systems that solve this problem better than v1 does, with the
specific mechanism taken from each and mapped onto existing code.

> **"GFP parity" in this document is a DESIGN TARGET, never a measured result.**
> It appears below as "extend to GFP parity" and "cheap GFP parity" — phrasings
> written while planning which feature families to build. None of them assert
> that parity was reached, and none should be quoted as if they did.
>
> The only honest status: **there is no measured comparison against IBM's Graph
> Feature Preprocessor.** The coverage checklist that once claimed "essentially
> at parity" is struck from `HANDOFF.md` §4, the control harness is
> `scripts/gfp_control.py`, and its middle stage cannot run on Windows at all —
> GFP is a Linux/macOS-only component at every snapml version. See
> `ARCHITECTURE_UPLIFT.md` §2.1 for the measurement that overturned the
> previously recorded blocker.

## What the reference architectures actually do

### IBM Graph Feature Preprocessor (ICAIF 2024) — the most important one

GFP is the closest production-proven relative to FraudOps, and it reports
**higher minority-class F1 than standard GNNs** on the AML datasets while
running on CPU rather than a V100. That matters enormously: it means the
architecture class v1 already sits in is not a compromise. Hand-engineered
subgraph features plus gradient boosting is a winning design, not a poor man's
GNN.

What it computes, and what v1 has:

| GFP feature | v1 status |
|---|---|
| fan-in / fan-out | partial — only max degree, not the pattern count |
| degree-in / degree-out | partial |
| scatter-gather | **have** |
| gather-scatter | **missing** — only one direction implemented |
| simple cycle | **have** |
| **temporal cycle** | **missing** |
| vertex statistics: sum, mean, min, max, median, var, **skewness, kurtosis**, in and out separately | **missing entirely** |

Its graph is adjacency lists over hash maps with per-pair edge lists kept as
deques sorted by timestamp, giving O(1) expiry — structurally what
`WindowedGraph` already does.

### RBI MuleHunter.AI — the behavioural axis

Built by the Reserve Bank Innovation Hub on **19 distinct patterns of mule
account behaviour**, operational in 26 banks, flagging ~20,000 mule accounts a
month. The 19 patterns are not published, but the industry typology they are
drawn from is well documented and directly implementable:

- **Pass-through velocity** — the core signal. ≥80% of inflow forwarded within
  48 hours.
- **Fan-in from multiple unrelated senders**, then rapid dispersal.
- **Dormant account reactivation** — a threshold rule on "large inflow soon
  after opening" misses accounts deliberately aged before use.
- **Structuring** just below reporting thresholds.
- **Cross-institution forwarding** — funds leave to a different bank fast.

v1 has **none** of these as features. `passthrough_ratio` is a binary
structural count, not a velocity measurement.

### Vulcan-class sequence models — the axis v1 does not have at all

Transaction foundation models learn per-account **behavioural sequences**: the
ordered history of what an account did, encoded by a transformer. Recent work
(GTCT, Temporal Contrastive Transformer) combines a graph encoder for structure
with a temporal encoder for sequence, and shows the contrastive/temporal
component carries real weight — removing it drops recall from 0.867 to 0.805.

v1 models **structure only**. It has no notion of how an account's behaviour
*evolved*. This is the single largest conceptual gap.

Reproducing a 3-trillion-datapoint foundation model is not on the table. But the
*signal* it extracts — behaviour over time per entity — is available cheaply
through summary statistics, which is exactly what GFP's vertex-statistics
features are.

### GARG-AML (2025) — the interpretability argument, plus one feature

Scores each node from the **block densities of its second-order neighbourhood
adjacency matrix**, then boosts with a decision tree. Explicitly argues that
interpretability and scalability matter more than raw F1 for AML because
investigators and regulators must know *why*. Its block-density measure targets
smurfing structure directly — the BIPARTITE and STACK shapes where v1 scores 3%
and 7%.

---

## The diagnosis

v1 measures **one axis of three**, and measures it incompletely.

```
                    STRUCTURE          BEHAVIOUR          IDENTITY
                    (graph shape)      (time series)      (shared attrs)

  v1                ~60% of GFP        none               stub, thin here
  GFP               100%               vertex stats       —
  MuleHunter        some               19 patterns        consortium data
  Vulcan-class      graph encoder      sequence encoder   3k signals/txn
```

This also explains the measured failure mode precisely. Recall analysis showed
the seed trigger reaches 78.6% of ring accounts and expansion recovers a median
100% of a ring — yet only 18.1% surface. **The rings are being generated and
then ranked away.** A scorer with one axis and seven hand-set weights cannot
separate them. The fix is more signal and learned weights, not better candidate
generation.

---

## v2 architecture

```
L0  ingest ─────────────────────────────────────────────  unchanged

L1  graph state
      money graph (pairs, adjacency)                      have
    + per-account incremental statistics                  NEW
    + per-pair timestamp-ordered edge lists               NEW

L2  candidate generation
      pass-through seeds + 2-hop expansion                have
    + behavioural seeds (dormancy break, velocity spike)  NEW

L3  feature extraction  ── three families ──
      structural   GFP parity + temporal cycles           EXTEND
      behavioural  velocity, dormancy, moments            NEW
      contextual   jurisdiction, entity type, age         partial

L4  scoring
      transparent linear blend                            have (v1)
    + gradient-boosted fusion over all three families     NEW (phase 4)

L5  cases + label corpus ────────────────────────────────  have
```

### L1 — two additions

**Per-account incremental statistics.** Maintain, separately for inflow and
outflow: count, sum, min, max, mean, and the second/third/fourth central
moments so variance, skewness and kurtosis are O(1) updates. GFP's design.
Amount *skewness* is a structuring signal that a mean cannot express — a mule
account's outflows cluster tightly just under a threshold.

**Timestamp-ordered edge lists per pair.** Required for temporal cycles and for
pass-through latency. `PairAgg` already keeps `first_t`/`last_t`; this extends it
to the ordered set.

### L2 — behavioural seeds

Pass-through alone gives 78.6% recall at 2.0× lift. Add two MuleHunter-derived
triggers as a union, not a replacement:

- **dormancy break** — account inactive for ≥N days then transacting
- **velocity spike** — inflow in the last 24h far above that account's own
  trailing mean, using the moments from L1

### L3 — the three families

**Structural (extend to GFP parity)**

- `temporal_cycle` — a cycle whose edges are chronologically ordered. **This is
  the highest-value single addition.** v1's cycle detection is purely
  structural: A→B→C→A counts whether or not the money could actually have
  flowed that way. In a 244k-node graph, structural cycles occur by chance
  constantly; temporally *valid* cycles do not. This should cut false positives
  sharply and directly targets the CYCLE typology now at 11%.
- `gather_scatter` — the reverse direction of the pattern already implemented.
- `fan_in_count` / `fan_out_count` as pattern counts, not just max degree.
- `block_density` — GARG-AML's second-order adjacency block measure, aimed at
  BIPARTITE (3%) and STACK (7%).

**Behavioural (new)**

- `passthrough_latency` — median hours between inflow and matching outflow
- `passthrough_ratio_value` — share of inflow value forwarded within 48h
- `dormancy_days` — max quiet gap before the burst
- `amount_skew`, `amount_kurtosis` — structuring signature
- `counterparty_novelty` — share of counterparties never seen before in window
- `cross_bank_latency` — how fast value leaves the institution

**Contextual (extend)**

- `n_countries`, `n_banks` — have
- `entity_type_mix` — Corporation / Partnership / Sole Proprietorship from the
  registry, currently loaded but unused
- `account_age` — first-seen time

### L4 — learned fusion

Gradient boosting over all three families, trained on the label corpus. The v1
linear blend is retained and displayed: **the score shown to the analyst stays
decomposable**, because GARG-AML's argument is correct and a case an analyst
cannot interrogate does not produce a usable verdict.

---

## Expected impact, and honest uncertainty

Ordered by expected value per unit of work:

| Change | Why | Confidence |
|---|---|---|
| Temporal cycles | Removes chance cycles; targets CYCLE (11%) | high |
| Learned fusion (phase 4) | Loss is in ranking, not generation | high |
| Behavioural features | An entire missing axis | high |
| Vertex-statistic moments | GFP core; structuring signal | medium |
| Gather-scatter + fan counts | Cheap GFP parity | medium |
| Block density | Targets the two worst typologies | medium |
| Sequence encoder | Real but needs scale v1 does not have | low |

**What this will not do:** reach Vulcan. Vulcan trained on ~3 trillion data
points across 4 billion real payments with NVIDIA and AWS infrastructure. No
public dataset and no laptop closes that gap, and any claim otherwise is not
credible.

**What it plausibly does:** move FraudOps into the architecture class that GFP
demonstrates can *beat standard GNNs* — hand-engineered subgraph features plus
boosting, fully interpretable, CPU-only, streaming. That is a defensible place
to be, and it is the honest ceiling of this project.

Benchmarking against published numbers is deferred until the architecture is
complete. Measuring a half-built system against a finished one produces a number
that means nothing.
