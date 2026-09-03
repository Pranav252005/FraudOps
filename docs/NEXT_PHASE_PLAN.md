# Next-phase plan

**Written:** 2026-09-03. **Branch at time of writing:** `upgrades/dead-query-groups-standing-rules`, HEAD `143bd38`.
**Status of the previous plan:** `docs/ARCHITECTURE_UPLIFT.md` is complete and its
centrepiece is dead by its own pre-registered rule. This document replaces its
§8 roadmap. It does not replace its §2–§7, which are still the reference for
GFP, efficiency, reliability and the investigation layer.

**This document is written to be handed verbatim to a fresh session.** §1 is the
context bootstrap; read it before acting on anything below it. Nothing here has
been implemented — this is a plan and one commit.

---

## 0. Read this first: the brief you were probably given is stale

If you arrived here from `docs/HANDOFF.md`, `docs/HANDOFF-NEXT.md`, or a
human's summary, six things have moved since those were written. Each is
sourced.

| what you were probably told | what is actually true now | source |
|---|---|---|
| the supervised oracle p@10 and oracle/blend ratio quoted below the table | **0.2111**, ratio **1.12x**, and the paired delta **includes zero at k=10 and k=20** (+0.0222 [-0.0333, +0.0889]) | `results/metrics.json` -> `supervised_p_at_10`, `supervised_over_blend_delta_at_10`; commit `63066d1` |
| LambdaMART not shippable, CIs include zero at k=10/20 | on the unconfounded pool it **excludes zero at every k** (+0.0667 [+0.0278, +0.1111] at k=10). It is still not shippable, for a different reason — see NOT-4 | `results/metrics.json` -> `lambdamart_over_pointwise_delta_at_10`; `docs/negative-results/lambdamart-reversal.md` |
| the §5b-vs-seeding-prize tension is **UNRESOLVED** and is the cheap decisive next experiment | **RESOLVED on 2026-09-01**, over the full 34 cycles, 1,192 s of replay. The mechanism is named and the three competing hypotheses are separated | `docs/PHASE2-SEED-CHEAT-FINDINGS.md`, `data/eval_seed_cheat_diff.json`, commit `82e2997` |
| the seeding prize is a ratio of point estimates | it now carries an interval: blend **2.18x [1.62x, 3.50x]** at k=10, paired on the same 18 cycles | `results/metrics.json` -> `seeding_prize_blend_ratio_at_10`; `scripts/eval_seeding_prize.py` |
| 514 tests passing | **789 collected, all passing, 1 xfailed, 0 skipped** (`python -m pytest --collect-only -q` sums to 789; the suite exits 0) | measured 2026-09-03 on this tree |
| one domain | **two**. A synthetic-identity domain (Phases A–E) ships alongside AMLworld, with its own generator, harness, features, fragmentation dose-response and case file | `docs/PHASEA-IDENTITY-BACKGROUND.md` through `docs/PHASEE-CASE-FILES.md`, commits `49f9f08`…`a7ee53e` |

The first row's superseded figures, quoted out of the table so they can carry
the marker rule 1 requires:
<!-- historical: measured at commit 0b4debd, 2026-08-31 -->
the supervised oracle read p@10 0.2500 with an oracle/blend ratio of 1.32x.
Both were superseded by commit `63066d1`.

**Do not re-run `scripts/eval_seed_cheat_diff.py`.** It has run. The 20-minute
replay is spent. Read `docs/PHASE2-SEED-CHEAT-FINDINGS.md` instead.

`data/*.json` is gitignored (`.gitignore:13`), so the measurement files named
throughout this document exist on the author's machine and not in a fresh
clone. `results/metrics.json` **is** tracked and is the authority for any number
that appears in prose.

---

## 1. Context bootstrap — everything a fresh session needs

### What the system is

A **fraud-ring investigation console**, not a transaction classifier. The unit
of investigation is the ring, not the transaction. It surfaces "here are the 9
accounts forming this structure, here is the evidence, here is a filing-ready
STR draft."

Pipeline, as actually implemented:

```
stream (time-ordered ticks)
  -> WindowedGraph (72h sliding, sentinel/graph/window.py)
  -> seeds: accounts touched this tick that are pass-through in the window
            (CandidateGenerator.seeds, sentinel/detect/candidates.py)
  -> 2-hop bounded expansion (hops=2, max_nodes=200, max_degree=50)
  -> prune (`leaf2`, sentinel/detect/prune.py)
  -> dedup on canonical_key
  -> features (structural / behavioural / contextual) + hand-set weighted blend
            (sentinel/detect/features.py, _V1_WEIGHTS and score)
  -> suppress(): greedy non-maximum suppression ORDERED BY SCORE
            (sentinel/detect/merge.py)
  -> ranked queue -> case record (immutable, provenance)
  -> STR narrative, LLM-drafted under a deterministic citation verifier that
     hard-fails uncited claims (sentinel/narrative/, sentinel/llm/)
  -> bounded escalation behind a human gate (sentinel/escalation.py)
  -> DPDP purpose limitation on the case store (sentinel/compliance/purpose.py)
  -> analyst console (sentinel/api/, frontend/)
```

Data: IBM AMLworld `HI-Small` (NeurIPS 2023, CDLA-Sharing-1.0). Roughly 5.08M
transactions and 515k accounts, with **370 labelled rings** across 8 typologies
(CYCLE, FAN-IN, FAN-OUT, BIPARTITE, STACK, RANDOM, GATHER-SCATTER,
SCATTER-GATHER). It is the only public dataset found that labels **rings**
rather than only transactions, which is the only reason ring-level precision and
recall are reportable at all.

Evaluation ends at day 10 of a 17.7-day stream, deliberately: the tail holds a
few hundred edges of which the overwhelming majority are laundering, so
"timestamp after day 10" would be a near-perfect classifier
(`sentinel/config.py`, `EVAL_END_DAY`).

### The current measured state

All from `results/metrics.json` @ commit `aa205eb`. Every p@k here is
ring-level; a hit requires a candidate to contain at least half a ring **and**
clear the Jaccard floor (`sentinel/eval/funnel.py::is_hit`).

**Held-out split, 18 cycles** (`data/eval_oracle.json`, run 1):

| ranking | p@10 | 95% CI | p@20 | p@50 |
|---|---:|---|---:|---:|
| lambdamart | 0.2778 | [0.1667, 0.3889] | 0.1667 | 0.0789 |
| supervised pointwise (**true labels — never a production number**) | 0.2111 | [0.1111, 0.3167] | 0.1278 | 0.0622 |
| **blend (shipped)** | **0.1889** | [0.0833, 0.3000] | 0.1000 | 0.0467 |
| size (node count) | 0.0444 | [0.0167, 0.0722] | 0.0444 | 0.0244 |
| random | 0.0000 | — | 0.0000 | 0.0000 |

**Shipped scorer over all 34 generation cycles** — a *different* experiment, not
comparable to the row above: p@10 **0.2912** [0.2235, 0.3618] against a size
baseline of 0.0941, score minus size +0.1971 [+0.1235, +0.2676]. Ring recall
23.9%.

**Funnel** (`data/funnel.json`, 34 cycles, 259 in-window rings):

| stage | rings | recall | loss |
|---|---:|---:|---:|
| seed-reachable | 259 | 100.0% | — |
| seeded | 230 | 88.8% | -11.2 pts |
| built | 162 | 62.5% | -26.6 pts |
| ranked (top-50) | 49 | 18.9% | **-39.8 pts, largest** |

**Threshold-free transaction level:** average precision 0.0113 against a base
rate of 0.0067, a 1.7x lift (`scripts/eval_vs_published.py`).

**Cost model:** six inputs, each robust one-at-a-time, but the **joint worst
case break-even is 1.8382 — the queue does not pay** under simultaneous adverse
inputs (`sentinel/economics/`, `scripts/eval_cost.py`, `ci_gates.py cost`).

**Structural ceiling:** 73.3%. Rings with two or fewer accounts have no
community structure to detect.

**Verification:** `python -m pytest -q` (789 tests, 1 xfail) and
`python scripts/ci_gates.py all` (determinism, re-tie, regression, cost).

### The seven standing rules

`docs/STANDING-RULES.md`. Four are constructor preconditions in
`sentinel/report/metric.py` — a p@k without its size baseline, or an interval
that does not name its clustering, **cannot be constructed**, so it cannot be
printed or stored. Every phase below inherits them. In particular:

- **Rule 1:** never state a number that has not been measured. Enforced as a
  property for numbers leaving through `sentinel/report/`, as an assertion
  against stale values in `*.template.md`, and as a **ratcheted ledger** for
  metric-shaped literals in `docs/` narrative. Adding a document like this one
  raises the ratchet; the increase must be dated and justified.
- **Rule 2:** always quote p@k beside its size baseline.
- **Rule 5:** cluster the bootstrap on the unit the trials nest in; where they
  nest in rings, report the wider of cycle- and ring-clustered.
- **Rule 6:** `sentinel.llm` must not be importable from any measured path.
- **Rule 7:** `docs/negative-results/` is append-only, and every entry must
  contain a section headed exactly **"What would reverse this"**.

### The five findings that constrain everything below

1. **"The scorer is the bottleneck" is dead**, killed by its own pre-registered
   kill rule, and the kill has since got *stronger*: the oracle-over-blend ratio
   is 1.12x and the delta CI includes zero at k=10 and k=20
   (`docs/CENTREPIECE-INVALIDATED.md`, commit `63066d1`).
2. **The loss is at candidate assembly, and the mechanism is window
   fragmentation.** See §2.1.
3. **The score participates in generation, not just ranking.** `suppress()` is
   greedy non-maximum suppression ordered by score, so any weight change
   invalidates the candidate set. Any experiment reusing a cached pool measures
   a fixed-candidate-set counterfactual, not the deployed system. The tell:
   `size` and `degree` read no features, so if they move, the candidate set
   moved.
4. **GFP parity is blocked at OS level.** No `gf_*` symbols in any of the six
   Windows `.pyd` binaries in snapml 1.15.6; the manylinux wheel of the
   identical version exports all of them; snapml 1.17.x ships no Windows wheels
   at all. Needs WSL2 or Docker — **a user action requiring admin and a
   reboot**.
5. **Seventeen bugs found, every one returning a plausible wrong answer rather
   than an error**, including two written during this work and caught by it.

---

## 2. Part A — the hard questions, answered

### 2.1 Is the bottleneck identified now?

**Yes — the *location* is, for the first time on evidence designed to
discriminate rather than on a funnel table. The *fix* is not.** Those are
different claims and the project has previously conflated them.

This question has been answered wrongly three times (`HANDOFF.md` §5 blamed the
seed rule; §5b blamed candidate-build for two typologies; §5c corrected §5b and
blamed dilution). The fourth answer is different in kind: it comes from a
measurement built to separate three named hypotheses, with a pre-registered null
and a reconciliation check against the published figure.

`scripts/eval_seed_cheat_diff.py` partitioned all 259 in-window rings on
(seeded_honest, seeded_cheat, built_honest, built_cheat) over 34 cycles. The
partition reproduces §5b's seeding figure **to the ring** (230 of 259), which is
what makes the rest quotable — a partition that disagreed would be describing a
different pool. The rescued set **R** (seeded honestly, built only under the
cheat) has n = 49, above the plan's pre-set threshold of 30.

R differs from the matched control C (seeded *and* built honestly, n = 159) on
**7 of 7** measurements, so the pre-registered null does not fire. The
discriminating measurement:

| | R (n=49) | C (n=159) |
|---|---:|---:|
| median ring size | 8 | 5 |
| median seed fraction of ring | 0.250 | 0.333 |
| **share with the ring split across two or more components** | **0.510** | **0.057** |
| share with the seed in only *some* components | 0.469 | 0.044 |

**The mechanism: the ring's own induced subgraph is disconnected inside the
72-hour window, and the honest seed lands in one fragment of it.** The rest of
the ring is not reachable through ring edges at any budget. The cheat works
because it seeds every member, so every fragment gets a seed.

The builder-budget hypothesis is refuted, and it fails backwards: relaxing every
knob raises R's mean containment while collapsing the share of rings covered,
because the extra reach drags in bystanders and the candidate fails the Jaccard
floor. C degrades the same way, so this is a property of expansion against the
floor, not something specific to rescued rings
(`docs/negative-results/builder-budget-refuted.md`).

And the prize now has an interval that separates it from the scorer prize:

| ranking | as-is -> cheat p@10 | ratio |
|---|---|---|
| blend | 0.1889 -> 0.4111 | **2.18x [1.62x, 3.50x]** |
| size (reads no features) | 0.0444 -> 0.1000 | 2.25x [1.25x, 3.75x] |
| oracle | 0.2111 -> 0.5611 | 2.66x [2.09x, 4.00x] |

against a scorer ratio of **1.12x**. The seeding interval's lower bound sits
above the scorer's point estimate. That is a separation backed by an interval
rather than two point estimates compared by eye.

**Note what `size` does there.** A baseline that reads no features at all
collects essentially the whole prize. The prize is about the candidate pool
*containing* the rings, not about ranking them. It is available to any scorer,
which is the strongest available evidence that this is a generation problem and
not a disguised ranking problem.

**Three reasons to keep this held loosely.**

- The catalogue is **descriptive at n = 49**, and it says so in its own output.
  It is not an inferential claim about the size of the prize.
- **The cheat is not an intervention.** It uses ring identity. Knowing that
  "put a seed in every fragment" is worth roughly a doubling is not knowing that
  any label-free rule can put a seed in every fragment, or that a
  fragment-joining rule can find the other fragment without also joining a
  thousand unrelated neighbourhoods. §5 treats this as the plan's largest single
  exposure.
- The project has converted an identified loss into a CI-clear p@k gain
  **once** — pruning, +0.031 [+0.010, +0.053] at k=20
  (`data/prune_impact.json`). Identification has a much better track record here
  than repair.

So the honest statement is: **the loss is at candidate assembly across
disconnected fragments of one ring, this is measured rather than argued, and
whether it is collectable is open.**

### 2.2 Is this a good architecture for the problem?

**Where it is structurally right.**

1. **The ring is the unit, and the funnel is instrumented per stage.** This is
   the load-bearing decision and it is correct. Every diagnosis in this
   repository — including all three wrong ones — was only possible because
   seed, build and rank losses are separable and separately measured. Most
   projects in this space cannot tell you where they lose.
2. **The reporting layer cannot print an unmeasured number.** Four standing
   rules are constructor preconditions rather than review conventions. This is
   rare, it is what the judging bar actually rewards, and it is not a detector
   feature so no measurement can take it away.
3. **The citation verifier hard-fails and the LLM is outside every measured
   path**, enforced in a subprocess against the transitive import set with a
   negative control (`tests/test_import_boundaries.py`,
   `tests/test_measured_path_closure.py`). A verifier that cannot fail measures
   nothing; this one can, and the rejection rate is a real metric.
4. **The human gate converts false-positive cost into analyst labour** rather
   than merchant harm, and the cost model *inverts* to a break-even precision
   rather than asserting a rupee figure nobody can source.

**Where it is fighting itself.**

1. **Seed-and-expand is the wrong primitive for the failure that was
   measured.** Seed-and-expand assumes the target is connected and within
   radius *r* of the seed. The measurement says that for the rings that matter,
   it is neither. This is why *every* knob has been ruled out by experiment
   (hops, node cap, hub guard, seed width): the knobs parameterise a family of
   procedures that cannot express the answer. Tuning a family that excludes the
   solution returns null forever, which is exactly the history here.
2. **The Jaccard floor makes reach and precision structurally opposed.** More
   reach finds more of the ring and buries it — measured symmetrically on both
   R and C. The floor is right to exist (bug #8: a containment-only metric let a
   node-count baseline tie the score), but it is doing two jobs at once: it is
   an anti-size guard *and* a candidate-boundary-quality requirement. A builder
   that must over-collect in order to reach can never satisfy the second.
3. **`suppress()` couples the score to the candidate set** — finding 3. See
   §2.3.
4. **The window is a global constant doing per-ring work.** `WINDOW_MINUTES` is
   72h for every candidate. Fragmentation is a function of structure size
   against window length, which is now confirmed twice: R's rings are larger
   (median 8 against 5), and the identity domain's dose-response shows coverage
   falling as rotation stretches clusters, with mean cluster diameter rising and
   the effect vanishing at cluster size 3 (`docs/PHASED-FRAGMENTATION.md`). Same
   mechanism, two domains, measured with the same primitives.
5. **Two domains is scope risk at submission**, not an architecture problem.
   The cross-domain claim that motivated the second domain was refuted
   (`docs/negative-results/identity-fragments-worse-refuted.md`). It is built,
   tested and honest; it should not be led with.

### 2.3 The score-participates-in-generation coupling: flaw or property?

**It is a design flaw, it should be removed, and removing it is cheap — but it
is not free, and the cost is measured.**

The argument for removal: `suppress()` needs to choose a *representative* from a
set of overlapping views of one neighbourhood. That is a selection problem. It
does not need the *ranking* score to do it; it needs any deterministic,
feature-independent key. Using the ranking score for it buys a small selection
benefit and pays for it by making every scorer experiment in the project
structurally invalid on a cached pool — which has already produced one
mixed-provenance near-publication (`data/eval_ranker.MIXEDPROVENANCE.json.bak`)
and one file whose staleness the project's own `--rescore` command was
incapable of detecting.

The argument against removal: it is not free. On the blend-weight fix, the total
score-minus-size delta at k=10 was +0.197 [+0.124, +0.268]; on a **fixed**
candidate set the ranking effect alone was +0.144 [+0.056, +0.244]
(`docs/SCORE-VS-SIZE-FINDINGS.md`). Roughly a quarter of that change was
survivor selection. Decoupling gives that up.

**The recommendation, which is neither "remove" nor "evaluate around":** make
the suppression ordering key a **config-level choice**, default it to a
score-independent key (candidate size descending, then `canonical_key` — total,
deterministic, feature-blind), and run every scorer experiment under the
decoupled setting regardless of which one ships. Then:

- weight changes stop invalidating the candidate set, so cached-pool
  experiments become valid and a full regeneration disappears from every scorer
  A/B;
- `size` and `degree` become genuine invariants across scorer arms, which
  upgrades the project's best staleness tell from a heuristic to a property;
- the cost of decoupling is itself measurable in one run, so it becomes a
  number rather than an argument.

This is Phase 1. It is the evaluation-design fix that finding 3 implies, and it
is a precondition for trusting anything Phases 2 and 3 produce.

### 2.4 What a better architecture would look like, from what is now known

Keep the case store, verifier, report layer, cost model, escalation gate and
console **untouched**. They are the product, they answer the judging bar, and no
measurement threatens them.

Replace the detector's middle third. Three changes, ordered by how directly they
attack the measured mechanism:

**(a) Assembly, not just suppression.** Today the pipeline only ever *removes*
overlapping candidates. Nothing joins two candidates that are disjoint fragments
of one structure — which is precisely the shape half the rescued rings have. The
missing stage is a **fragment-linking** pass: given two surviving candidates
with no shared members, join them when a small number of transaction paths
connects them and the union's structural quality exceeds both parts'. This is
the only proposed change that addresses the mechanism head-on.

**(b) A conductance-guided boundary instead of a hop budget.** The measured
failure "more hops finds more of the target and buries it" is the textbook
motivation for local community detection by **personalised-PageRank sweep**
(Andersen–Chung–Lang): push a localised PPR vector from the seed, sort by
degree-normalised mass, and cut at the best-conductance prefix. The *cut* chooses
the boundary; the budget does not. Two secondary benefits: the sweep profile is
a natural size-normalised quality signal, so it yields a candidate score that is
not a size proxy by construction; and the same machinery is what the
local-motif-clustering line of work builds on, which is a cleaner path to "score
the candidate by the motif density it actually has" than the current hand-set
blend.

**(c) A per-candidate adaptive window.** Grow a candidate's window until its own
induced subgraph stops gaining connected components, instead of imposing 72h
globally. This attacks fragmentation at its source rather than repairing it
downstream, and it is the change the identity-domain dose-response independently
points at. It is also the most expensive and the most likely to reintroduce the
day-10 leak, so it is ranked last and is not in the plan below.

**What would be structurally different about the result:** the detector would
stop being "one procedure with four knobs, all measured inert" and become
"generate fragments cheaply, then *assemble* and *bound* them by an objective."
That is the shape the evidence has been pointing at since §5c, and the project
has never had it.

---

## 3. Part B — prior art survey

Searched across: anti-money laundering graph, AML detection, mule account
detection, money mule, transaction graph fraud, subgraph anomaly detection,
graph anomaly detection, financial crime graph, suspicious activity detection,
AMLSim, AMLworld, IBM AML, Elliptic and Elliptic2, GARG-AML, smurfing detection,
structuring detection, layering detection, typology detection, SAR/STR
automation, case management fraud, network fraud detection, community detection
fraud, temporal graph anomaly, GNN fraud detection, graph feature preprocessor,
local community detection / seed set expansion, collusion detection, fraud gang
(团伙) detection, abuse ring, payment-aggregator fraud, and the Razorpay
buildathon itself.

**Everything below was verified by fetching the repository or paper page.**
Where a field could not be established from the page it is marked *unverified*.
Star and commit counts are as read on 2026-09-03 and drift.

### Tier 1 — borrow or integrate

**1. AMLGentex — `aidotse/AMLGentex`** · Apache-2.0 · 25 stars, 12 forks, 678
commits, active · [repo](https://github.com/aidotse/AMLGentex) ·
[arXiv:2506.13989](https://arxiv.org/abs/2506.13989)

Open-source configurable AML data generator and benchmark suite from AI Sweden
with Handelsbanken and Swedbank. Generates transaction networks with injected
SAR patterns (cycle, bipartite, stack, and others), supports seeded
regeneration, two-level Bayesian optimisation over generation and model
hyperparameters, and ships eight baselines (decision tree, random forest, GBM,
logistic regression, MLP, GCN, GAT, GraphSAGE) plus AML-shaped metrics including
average precision at high recall.

**Why this is the most useful thing on the list.** This project's binding
constraint is not the scorer and not compute — it is **independent sample**.
`docs/ARCHITECTURE_UPLIFT.md` §12.3 states it plainly: HI-Small labels 370 rings
and almost all of them are already inside the eval window, so extending the
stream buys more cycles and only a handful of new rings. A configurable
generator is the only route that adds genuinely new rings without a licence
negotiation or a 196M-edge download. Every interval in this repository could
narrow.

**The blocker, and it must be checked in the first hour of any phase that
depends on it:** the repo page describes SAR labels as **per-account binary**,
with pattern membership tracked during generation but not obviously exported as
group ids. **Ring-level p@k is not computable from account-level binary labels.**
If group ids cannot be recovered from the generator's intermediate state, this
integration is dead on arrival and the phase must be killed rather than
retargeted at an account-level metric — that would silently change the unit and
is exactly the class of error `sentinel/corpus/` exists to refuse.

**2. FlowScope — `csqjxiao/FlowScope`** · licence not stated *(unverified)* ·
7 stars, 31 commits, Python 2 · [repo](https://github.com/csqjxiao/FlowScope)

Models transfers as a **multipartite** graph and detects the *complete flow of
money from source to destination through chains of accounts*, rather than
detecting dense subgraphs. Two variants: one middle layer and two.

**Why it matters here specifically:** STACK is this project's worst typology —
seeded 30 of 30, the only typology seeded perfectly, and 9 of 30 built
(`data/funnel.csv`). STACK is a layered chain. FlowScope is a method built for
exactly that shape and it does not use seed-and-expand. **Borrow the objective,
not the code** — Python 2, 7 stars, no licence stated, no packaging. The
transferable idea is scoring a candidate by *flow conservation along a layered
path* rather than by neighbourhood density, and `sentinel/detect/features.py`
already computes a `conservation` term that is a single-candidate version of it.

**3. Local community detection by PPR sweep** — the literature, not one repo.
[LocalCommunities (`LJeub/LocalCommunities`)](https://github.com/LJeub/LocalCommunities)
implements ACLcut, MOVcut and EGOcut; [`kkloste/lemon-sqz`](https://github.com/kkloste/lemon-sqz)
outputs a PPR diffusion and its best-conductance set;
[HeidelbergMotifClustering](https://github.com/LocalClustering/HeidelbergMotifClustering)
does local *motif* clustering via hypergraph partitioning
([arXiv:2205.06176](https://arxiv.org/pdf/2205.06176)).

This is the field that has already solved "expanding by hop count either
under-reaches or drags in bystanders." The answer is: do not choose a radius,
choose a **cut**. Sweep the degree-normalised PPR ordering and take the
best-conductance prefix. Directly applicable to §2.4(b) and to Phase 3. Nothing
needs to be vendored — the ACL push algorithm is a few dozen lines over the
existing `WindowedGraph` adjacency.

**4. IBM Graph Feature Preprocessor (snapml)** ·
[arXiv:2402.08593](https://arxiv.org/html/2402.08593v2) ·
[ICAIF'24](https://dl.acm.org/doi/10.1145/3677052.3698674) ·
[snapml-examples](https://github.com/IBM/snapml-examples)

Already the reference comparator (`docs/ARCHITECTURE_UPLIFT.md` §2). It is the
same architecture class — hand-engineered subgraph features plus gradient
boosting, on CPU — and it reports higher minority-class F1 than standard GNNs.
Blocked at OS level here; see Phase 4. `snapml-examples` ships a conda
environment and a notebook, which is the reproduction path once a Linux
userspace exists.

### Tier 2 — read, do not integrate

**5. GARG-AML — `B-Deprez/GARG-AML`** · MIT · Python · 130 commits ·
[repo](https://github.com/B-Deprez/GARG-AML) ·
[arXiv:2506.04292](https://arxiv.org/abs/2506.04292)

Second-order-neighbourhood block-density score for smurfing, extended with a
decision tree and gradient boosting; benchmarked against FlowScope and AutoAudit;
uses the same IBM AML Kaggle data. **Already implemented here** as the `gargaml`
feature — and **measured as an anti-signal on this pipeline after pruning**
(near-universal, near-saturated, and below chance against the label with node
count held exactly constant; retired in commit `a0cbbec`). That is a statement
about GARG-AML *on pruned seed-and-expand candidates in HI-Small*, not about the
method. Worth re-reading their evaluation protocol — their unit is the account,
this project's is the candidate, and the disagreement is probably the unit.

**6. Multi-GNN — `IBM/Multi-GNN`** · Apache-2.0 · 121 stars, 55 forks, 15
commits · [repo](https://github.com/IBM/Multi-GNN) ·
[arXiv:2306.11586](https://arxiv.org/abs/2306.11586) (AAAI 2024)

The source of the published HI-Small F1 numbers (reverse message passing, port
numbering, ego IDs). Runs on the same Kaggle files (`--data Small_HI`). Useful
as a **provenance reference for the published baselines**, and as the concrete
reason not to build a GNN: it exists, it is Apache-2.0, and it is
transaction-level, so it neither competes with nor substitutes for a ring-level
investigation layer. **Do not quote this project's transaction-level F1 against
theirs** — that comparison is a fixed-cardinality-selection artifact and is
already retracted in `docs/HANDOFF.md` §3 and §4.

**7. Elliptic2 — `MITIBMxGraph/Elliptic2`** · Apache-2.0 · 28 stars, 4 commits,
inactive · [repo](https://github.com/MITIBMxGraph/Elliptic2) ·
[arXiv:2404.19109](https://arxiv.org/abs/2404.19109)

122K labelled subgraphs in a 49M-node, 196M-edge background graph; baselines
GLASS, GNNSeg, Sub2Vec. **Read `docs/negative-results/elliptic2-cancelled.md`
before touching this.** Elliptic2 *ships* its subgraphs; this project
*constructs* them. Under `POOLING_VALIDITY` a **recall** comparison across the
two is invalid no matter how much compute is spent; only a **scorer** question
is admissible — and the scorer is the one component measured not to be the
bottleneck. See NOT-1.

**8. AutoAudit — `mengchillee/AutoAudit`** · BSD-2-Clause · 19 stars, 34 commits
· [repo](https://github.com/mengchillee/AutoAudit)

AA-SMURF (unsupervised smurfing detection) plus AA-AR (attention routing over
suspicious time periods). The **time-period attention** idea is the interesting
transfer: this project's fragmentation problem is temporal, and "which window is
anomalous" is a question it never asks. Datasets are small (a few hundred to
~17k nodes) and none is AMLworld.

**9. Spade** · [VLDB 2023, arXiv:2211.06977](https://arxiv.org/abs/2211.06977) ·
code availability *unverified*

Incremental real-time fraud detection maintaining dense subgraphs on evolving
graphs, deployed at Grab; sub-millisecond on million-scale graphs. Directly
relevant to `WindowedGraph`'s incremental expiry. **But compute is not this
project's bottleneck** — a 3.02x speedup already shipped, Leiden on the window
takes seconds, and a full replay takes under a minute. Read for the
incremental-maintenance design; do not adopt.

**10. Dense-subgraph and Benford-based detectors:**
[`wenchieh/specgreedy`](https://github.com/wenchieh/specgreedy) (unified dense
subgraph detection, ECML-PKDD'20 best student paper) and
[AntiBenford subgraphs](https://arxiv.org/abs/2205.13426) (KDD 2022, anomalous
subgraphs in crypto networks that dense-subgraph methods miss). Both are
**candidate-generation alternatives that do not need a seed** — which is the
property this project's failure mode wants. AntiBenford in particular scores a
subgraph by digit-distribution deviation, a signal orthogonal to everything in
`features.py`. Worth one afternoon of reading before Phase 2 is designed; not
worth integrating.

**11. Toolboxes and indices:** [`pygod-team/pygod`](https://github.com/pygod-team/pygod)
(graph outlier detection on PyG), [`safe-graph/DGFraud`](https://github.com/safe-graph/DGFraud)
and `DGFraud-TF2`, [`safe-graph/UGFraud`](https://github.com/safe-graph/UGFraud)
(unsupervised), [GADBench](https://arxiv.org/abs/2306.12251),
[`safe-graph/graph-fraud-detection-papers`](https://github.com/safe-graph/graph-fraud-detection-papers),
[`AI4Risk/awesome-fraud-detection`](https://github.com/AI4Risk/awesome-fraud-detection),
[`benedekrozemberczki/awesome-fraud-detection-papers`](https://github.com/benedekrozemberczki/awesome-fraud-detection-papers).
All node-level or edge-level. **None of them does ring-level candidate
generation with a ring-level metric.** Useful as literature indices; nothing to
integrate.

**12. AMLSim — `IBM/AMLSim`** · [repo](https://github.com/IBM/AMLSim/) · the
generator lineage behind AMLworld. Its typology classes are named identically to
this project's eight (`FanOutTypology`, `CycleTypology`, `StackTypology`,
`ScatterGatherTypology`, and so on), which confirms the typology taxonomy is
inherited from the generator rather than from FATF. Worth stating in the
submission: the eight typologies are the *generator's* categories. Superseded by
AMLGentex for generation purposes.

### Tier 3 — checked, not useful

- **`jube-home/aml-fraud-transaction-monitoring`** · AGPLv3 · C#/.NET · 103
  stars, 164 commits ·
  [repo](https://github.com/jube-home/aml-fraud-transaction-monitoring).
  A genuine, maintained, production-shaped AML platform with rules, adaptive
  ML, velocity and aggregation checks, and real case management (workflows,
  document versioning, escalation rules, audit trails). **This is the one
  project on the list that does the case-management half better** — it has been
  built as software rather than as a demo. It is transaction and entity level
  with behavioural aggregation; it does not do ring-level structure surfacing.
  If asked "who does the console better", the honest answer is Jube, and the
  honest distinction is that Jube manages alerts while this manages
  *structures*.
- **`RamprasanthRamachandran/ai-sar-narrative-automation`,
  `vyayasan/kyc-analyst`** and the wider cluster of LLM SAR-drafting repos. All
  generate narratives; **none of them has a deterministic verifier that
  hard-fails an uncited claim and discards the whole draft.** That is this
  project's genuine differentiator in the narrative layer and the survey did not
  find it anywhere else. State it as "not found", not as "does not exist".
- **`SS072/Rezorpay`** · MIT · 1 star, 12 commits ·
  [repo](https://github.com/SS072/Rezorpay). A **direct competitor in the same
  buildathon and the same track** — dual-tier gating plus an in-memory bipartite
  graph for mule rings, plus a "forensic copilot". React, FastAPI, NetworkX. Its
  own README labels its 50,000-transaction benchmark as **synthetic
  demonstration data** with "DEMO DATA" badges. Read: the competition in this
  track is building on self-generated data with unvalidated metrics. This
  project's public benchmark, funnel, intervals and fired kill rules are the
  differentiator against that field — not its p@10.
- **`Hunter764/GraphMule`**, `Swarnimm22/AML_Transaction_Monitoring`,
  `Alokjha16/Financial-Crime-Investigation-Agent`,
  `Yajunesh/AML-Agentic-Detection`, `Zahoor-ishfaq/aml-investigation-agent`, and
  the rest of the LLM-AML-agent cluster. Polished READMEs, low commit counts, no
  licences in several cases, and **no measured evaluation** — headline claims
  appear without a stated denominator, split, or interval. README-ware for
  present purposes.
- **Neo4j, GraphAware Hume, Quantexa** and the GraphRAG-for-KYC line
  ([Neo4j's KYC agent walkthrough](https://neo4j.com/blog/developer/graphrag-in-action-know-your-customer/)).
  Commercial or tutorial; the pattern (entity-resolved graph plus agent) is the
  industry direction and is worth one sentence in the submission's positioning,
  nothing more.

### Does anything do what FraudOps does, better?

Honestly assessed, component by component:

| component | anything better? |
|---|---|
| transaction-level detection quality | **Yes, decisively.** Multi-GNN and the Graph Feature Preprocessor, both supervised, both published, both on this exact dataset. Not close. |
| candidate generation for layered and bipartite shapes | **Yes, in principle.** FlowScope's multipartite flow objective is built for STACK; SpecGreedy and AntiBenford generate without seeds. None is packaged for production. |
| case management as software | **Yes.** Jube. |
| ring-level detection with a ring-level metric, a per-stage funnel, and published intervals | **Not found.** |
| narrative generation under a hard-failing deterministic citation verifier | **Not found.** |
| published pre-registered kill rules that fired and cancelled the author's own plan | **Not found**, in this domain or adjacent ones. |

The position is unchanged and it is not a moat: this is the investigation layer,
and its defensible property is that it is *measured*.

---

## 4. Part C — the phased plan

**Sequencing assumption, and it needs checking on day one.** The Razorpay AI
Buildathon 2026 application deadline is reported as **5 September 2026**, with
build, pitch and panel rounds after, dates announced to shortlisted candidates
([Velonx](https://velonx.in/blog/razorpay-ai-buildathon-2026-tracks-eligibility-stipend-selection-process)).
This plan was written on 3 September 2026. **If the build deadline is days
rather than weeks, run Phase 0 and Phase 5 only and skip everything else** —
Phases 1 to 3 are detector work whose expected effect on the judging criteria is
small, and Phase 5 is the work that is directly scored.

> **VERIFIED 2026-09-03, and the branch fired. Phases 1, 2, 3, 6 and 7 are
> OFF.** The assumption above was wrong in the direction that matters: the
> public repo and the five-minute pitch video are due **at application time**,
> not after shortlisting. Razorpay's own page lists the submission as "public
> repo, 5-minute pitch video, architecture" but prints no date; two independent
> secondary sources give the date and say what the application must contain —
> [DEV Community](https://dev.to/devengers/dev-opportunity-radar-14-mlh-global-hack-week-40k-agents-for-humans-hackathon-razorpay-ai-2b9g)
> ("Resume, project details, public GitHub repository, five-minute pitch video,
> and application questions", deadline 5 September 2026) and
> [@ajay_2512x on X](https://x.com/ajay_2512x/status/2090393869473165453)
> ("Applications close: 5 September"). That leaves roughly two days, so this
> document's own instruction applies as written: **Phase 0 and Phase 5 only.**
> Phase 4 was already gated on a user action needing admin and a reboot.

**Corrected, from the primary source.** Two claims in the paragraph that used to
stand here were mis-sourced, and the correction runs in both directions.

**Upgraded to verified.** The AI Risk Manager bar is on
[razorpay.com/buildathon](https://razorpay.com/buildathon/) verbatim: *"Honest
metrics including false-positive cost. Strictly defense-only: anything
offense-capable is disqualified."* The same page asks for detectors, verifiers
or auto-responders with *"measured precision and recall on a held-out test
set."* This document previously called that wording unverified. It is not.

**Downgraded to secondary.** The crisp four-word list — Problem Taste, Build
Quality, AI Judgment, Failure Recovery — is **not** on Razorpay's page and must
not be quoted as official. What is sourced is DEV Community's paraphrase:
Razorpay evaluates *"how you think, what you build, how well it works, and even
how you deal with things when they break."* The substance is the same and the
implication survives: **detector p@10 is not among the things named.** "How you
deal with things when they break" is, and it is the axis where this repository
is strongest and least packaged.

Every phase below inherits the standing rules. In particular each result must be
reported with its size baseline (rule 2) and its clustering method (rule 5), and
any phase that comes back negative must land an entry in
`docs/negative-results/` with a "What would reverse this" section (rule 7).

---

### Phase 0 — reconcile the record (2–3 hours, no dependencies) · DO THIS FIRST

**Objective.** Stop the next reader spending a day re-running a settled
experiment. §0 of this document lists six stale claims; three of them sit in
documents a fresh session reads top-down.

**Work items.**
1. `docs/HANDOFF-NEXT.md`, "Still open / not done" item 2, says the §5b tension
   is unresolved and "cheap to settle — a read of data that exists". Both
   clauses are false. Annotate in place (this repo corrects in place rather than
   rewriting) with a pointer to `docs/PHASE2-SEED-CHEAT-FINDINGS.md`, and record
   that it cost a 1,192-second replay, not a read.
2. The same correction in `docs/CENTREPIECE-INVALIDATED.md`, section "And the
   indicated fix is the one §5b forbids".
3. `docs/HANDOFF.md` §5f, "The remaining task, named precisely", is superseded —
   it names BIPARTITE and STACK build as the remaining task; the fragmentation
   finding is the live version. Annotate.
4. Re-run `python scripts/collect_metrics.py` and `python scripts/render_docs.py`
   so README and `docs/SUBMISSION.md` render from the current
   `results/metrics.json`. The template-literal leak
   (`docs/negative-results/template-literal-leak.md`) is the reason this cannot
   be assumed to have happened.
5. Add this document to the README's document index, and record its effect on
   the rule-1 prose-literal ledger with a date and a reason.

**Pre-registered effect.** No metric moves. If any metric moves, a render was
stale and that is itself a finding to record.

**Kill criterion.** None. This is bookkeeping.

**Effort.** 2–3 hours. **Dependencies.** None.

---

### Phase 1 — decouple suppression ordering from the score (1–2 days)

**Objective.** Make every downstream scorer experiment valid on a cached
candidate pool, and put a number on what the coupling was worth. This is the
evaluation-design fix that finding 3 implies, and it is a precondition for
trusting Phases 2 and 3.

**Work items.**
1. Add `SUPPRESS_ORDER` to `sentinel/config.py` with values `"score"` (current)
   and `"size_key"` (candidate size descending, then `canonical_key` ascending —
   a total order, deterministic, feature-blind). Thread it through `suppress()`
   in `sentinel/detect/merge.py` and `CandidateGenerator.generate`.
2. The size-bound pre-rejection optimisation inside `suppress()` is documented
   as output-identical under the score ordering; **verify it is still
   output-identical under the new ordering** on a fixture before believing any
   number. This is exactly the "exact speedup that altered an answer" class the
   bug catalogue is full of.
3. Run `scripts/eval_phase2.py` and `scripts/eval_oracle.py` end-to-end under
   both orderings over the same 34 and 18 cycles, paired.
4. Add a CI gate: under `SUPPRESS_ORDER="size_key"`, changing `_V1_WEIGHTS` must
   leave the `size` and `degree` rows byte-identical; under `"score"` it must
   not. **Both arms of that gate must be asserted** — a gate that can only pass
   is not a gate, and this repo has shipped one of those already
   (`docs/HANDOFF.md` §11b).
5. Whichever ordering ships, **run every scorer experiment in Phases 2 and 3
   under `"size_key"`**, and say so in each result.

**Pre-registered expectations** (write these into
`prereg/suppress_decoupling.md` and commit *before* running):
- **p@10 in the 34-cycle shipped frame: -0.05 to +0.01.** Direction genuinely
  uncertain. Roughly a quarter of the blend-fix effect was survivor selection,
  so the coupling is doing *something*; whether it is doing it in the right
  direction on the current weights is untested.
- **Ring recall: -2 to +2 points.**
- **The size-baseline margin at k=10 stays CI-clear.**
- The point of the phase is not the p@k. It is the gate in item 4.

**Kill criterion.** If `size_key` costs more than **0.05 p@10, CI-clear**, do
not ship it. Fall back to the expensive-but-correct rule — every scorer
experiment regenerates candidates, no cached pool, ever — record the cost in
`docs/negative-results/`, and note that the tell (`size` and `degree` moving)
remains the only defence.

**Effort.** 1–2 days including two end-to-end replays.
**Dependencies.** Phase 0.

---

### Phase 2 — fragment linking (3–5 days) · the highest-value detector work

**Objective.** Attack the measured mechanism directly. Half the rings the seed
cheat rescues are split across two or more components of their own induced
subgraph inside the window, and nothing in the pipeline ever joins two
candidates.

**Work items.**
1. New stage `sentinel/detect/link.py`, running **after** `suppress()` and
   **before** ranking. For each pair of surviving candidates A and B with no
   shared members, propose a merge when all of:
   - there exist at least **two edge-disjoint paths of length at most 2** from A
     to B through nodes in neither (the bridging intermediaries), and
   - the union's structural quality — use the existing `conservation` and
     `temporal_cycle` terms recomputed on the union — **strictly exceeds** both
     parts', and
   - the union respects a hard size cap that is not the scorer's judgment.
     Merging is the bug-#8 direction and needs a ceiling stated in `config.py`.
   Use the inverted node index `suppress()` already builds; do not write an
   O(n²) pass.
2. Record the merge on the candidate (`linked_from`, the bridging node ids) so
   the case file can show "assembled from two fragments via account X" — this is
   an *investigation* win independent of any p@k, and it is the kind of thing
   the Problem Taste axis rewards.
3. Evaluate with `scripts/eval_funnel.py` and `scripts/eval_phase2.py` over the
   same 34 cycles, paired, under `SUPPRESS_ORDER="size_key"`.
4. **Mandatory re-tie check** at k=10, 20, 50 and 100 against `size`, `degree`
   and `random`. Merging grows candidates. That is the exact direction that
   produced bug #8 and the post-pruning re-tie scare.

**Pre-registered expectations** (`prereg/fragment_linking.md`, committed before
the run):
- **Built recall 62.5% -> 66–74%.** The rescuable pool is bounded: R is 49 rings
  of 259, and only those whose fragments are actually bridged within two hops
  are reachable by this rule.
- **Ring recall 23.9% -> 26–31%.**
- **p@10 in the 34-cycle frame: -0.03 to +0.05.** I expect the interval to
  include zero. Merging adds candidates that cover rings *and* candidates that
  incorrectly join unrelated neighbourhoods, and at 34 cycles a net effect under
  0.05 will not separate.
- **The size-baseline margin at k=10 stays CI-clear** — this is the phase's real
  bar, not the p@10.
- **BIPARTITE and STACK built counts rise** (currently 5 of 28 and 9 of 30). If
  total built rises and these two do not, the merges are happening somewhere
  other than where the mechanism says they should, and the result is suspect
  even if the number is good.

**Kill criterion — three, any of which ends the phase:**
1. The score-minus-size margin at k=10 or k=20 stops excluding zero. The merge
   is then buying recall with size, which is bug #8 returning, and it reverts.
2. Built recall rises by **fewer than 3 points**. The mechanism predicted a
   larger pool than the rule can reach, and the rule is not worth its
   complexity.
3. Mean candidate size rises above roughly **14 nodes** (currently about 8
   post-prune). The pruning workstream's whole gain was normalising candidate
   size; giving it back is not a trade.

**Effort.** 3–5 days: a day for the linking rule, a day for the paired harness,
a couple of hours per end-to-end replay, and a full day budgeted for the re-tie
investigation because it will probably be needed.
**Dependencies.** Phase 1, so the candidate set is stable across scorer arms.

---

### Phase 3 — conductance-guided expansion, A/B against the shipped builder (3–4 days)

**Objective.** Replace "expand to a fixed radius, then prune" with "diffuse from
the seed, cut at the best conductance." The measured pathology — more budget
finds more of the ring and buries it, symmetrically on rescued and recovered
rings — is the textbook motivation for a sweep cut.

**Work items.**
1. Implement Andersen–Chung–Lang approximate personalised PageRank push over
   `WindowedGraph`'s undirected adjacency, then a degree-normalised sweep,
   taking the best-conductance prefix as the candidate. Two parameters
   (teleport and tolerance) — set them once from the literature's defaults and
   **do not sweep them**, or this becomes the fourth inert knob-tuning exercise.
2. A/B against the shipped builder over the same 34 cycles, sharing one graph
   per tick. Report containment and Jaccard *separately* as well as `is_hit`,
   because the whole point is whether the cut fixes the reach-versus-precision
   opposition.
3. Report the sweep's conductance value as a candidate feature and check whether
   it discriminates independently of node count — stratify on node count and
   compute AUC, exactly as `scripts/eval_blend_v2.py` did for `gargaml`.

**Pre-registered expectations** (`prereg/ppr_sweep.md`):
- **Containment at or above shipped and Jaccard at or above shipped,
  simultaneously.** That is the claim the method makes; anything less is a null.
- **Built recall +2 to +8 points** over the leaf2-pruned two-hop builder.
- **p@10: -0.03 to +0.06.** Interval expected to include zero.
- **Conductance as a feature: AUC 0.55–0.65** with node count held constant. If
  it lands at 0.50 give or take 0.03 it is a size proxy and must not enter the
  blend.

**Kill criterion.** If the sweep does not beat the leaf2-pruned two-hop builder
on **containment and Jaccard at the same time**, drop it. Pruning already solved
the dilution half, so a method that only improves Jaccard is buying something
already bought.

**Effort.** 3–4 days. **Dependencies.** Phase 1. Independent of Phase 2 — they
attack different halves (assembly versus boundary) and can be measured
separately, but **do not ship both in one arm**; the interaction is unmeasurable
at 34 cycles.

**Ranked below Phase 2** because Phase 2 attacks the mechanism the measurement
actually named, and Phase 3 attacks a problem `leaf2` already partly solved.

---

### Phase 4 — GFP parity (1 day of work, gated on a user action)

**Objective.** Replace "no parity claim of any kind belongs in this repo"
(`docs/negative-results/gfp-parity-unmeasured.md`) with a measured head-to-head
against the reference implementation of this project's own architecture class.

**USER ACTION REQUIRED, AND IT IS A PREREQUISITE, NOT A WORK ITEM.** IBM's Graph
Feature Preprocessor is not built for Windows at any snapml version or any
Python version — no `gf_*` symbols across the six `.pyd` binaries in 1.15.6, and
1.17.x ships no Windows wheels at all. The repo owner must install **WSL2 or
Docker Desktop** (administrator privileges and a reboot) or provide a Linux
host. No venv, interpreter change, or subprocess boundary can substitute.
`scripts/gfp_setup_linux.sh` and `scripts/gfp_control.py` are already split at
that file boundary: `export` and `compare` run on Windows, `gfp-features` does
not run here at all.

**Work items** (after the prerequisite is met):
1. **Reproduce the paper's own number first**, on their data, before comparing
   anything. A control that cannot reproduce its reference is uninformative.
2. `scripts/gfp_control.py gfp-features` on the exported candidate pool, then
   `gfp_compare` at candidate granularity on the identical ring-disjoint split.
3. Publish the result whichever way it falls.

**Pre-registered expectation.** Roughly comparable ring-level p@k. **The
interesting outcome is a gap**, and it should localise to the timestamp moments
(`docs/ARCHITECTURE_UPLIFT.md` §2.2 identifies these as a genuine coverage gap).
I expect GFP's block to be **modestly better**, because it is a tuned reference
implementation and this project's own median-amount experiment already showed
that closing one GFP gap can hurt
(`docs/negative-results/median-amount-features.md`).

**Kill criterion.** If the paper's own configuration cannot be reproduced under
snapml 1.15.6 on Python 3.11 — a 2024 paper against a pinned old version is a
real version-drift risk — report the control as uninformative and stop. Do not
partially quote it.

**Effort.** 1 day after the prerequisite; indefinite before it.
**Dependencies.** The user action. Nothing else in this plan depends on Phase 4,
so it must not block anything.

---

### Phase 5 — the investigation layer, against the actual judging criteria (3–4 days)

**This is the highest-expected-value phase on the list**, and if the deadline is
short it is the only one besides Phase 0 worth running. The judged parameters
are Problem Taste, Build Quality, AI Judgment and Failure Recovery. Detector
p@10 is not among them.

**Objective.** Package what the repository already has, and close the two
measurement gaps in the investigation layer that `docs/ARCHITECTURE_UPLIFT.md`
§7 named and never built.

**Work items.**
1. **A single Failure Recovery artefact** — `docs/WHAT-BROKE.md`, rendered, not
   typed. The raw material is exceptional and is currently scattered across
   1,500 lines of handoff prose: seventeen bugs each of which returned a
   *plausible wrong answer* rather than an error; two pre-registered kill rules
   that fired and cancelled the author's own centrepiece; one question answered
   wrongly three times and then settled by an experiment designed to
   discriminate; a five-seed stability sweep that was one fit reported five
   times; a render system that shipped the exact defect it was built to prevent.
   **No other entrant will have this.** It should be one page, with the
   mechanism of each catch stated, and it should be linked from the README's
   first screen.
2. **Narrative quality, measured** (§7.2, still unbuilt). Compute **citation
   precision and recall** on the STR drafts: of the ids cited, what fraction
   resolve to facts the case file contains (precision — currently guaranteed by
   the verifier, so the number is 1.0 *by construction* and must be labelled as
   such); of the case file's material facts, what fraction the narrative
   actually cites (recall — **not** guaranteed, never measured, and the honest
   number). Add an adversarial suite: drafts that cite real ids for claims those
   ids do not support. A verifier that catches fabricated ids but not
   mis-attributed ones has a named hole, and naming it is worth more than a
   clean pass.
3. **Publish the LLM draft rejection rate** from `data/draft_ledger.jsonl` and
   `/api/llm/status` as a first-class metric in `results/metrics.json`. It is
   the only metric in the repo that measures the AI component's judgment
   directly, which is a named judging axis.
4. **State the cost model's negative result on the first screen.** Six inputs
   robust one-at-a-time; **joint worst case break-even 1.8382 — the queue does
   not pay**. A submission that leads with its own adverse economics under the
   track's "honest metrics including false-positive cost" bar is doing exactly
   what the bar asks. Do *not* ground the six placeholder inputs to produce a
   rupee figure — see NOT-5.
5. **A five-minute pitch narrative** built around the workflow and the reversal,
   not the graph. Suggested spine: here is one ring, pre-investigated, with its
   STR draft and every sentence traceable; here is the funnel showing where we
   lose; here is the plan we killed with our own rule; here is the number that
   says our queue may not pay.

**Pre-registered expectations.** No detector metric moves. Citation **recall**
lands somewhere in **0.4 to 0.8** — that is a guess, recorded so it can be
wrong, and it is the first honest number for narrative quality in the project.

**Kill criterion.** If citation recall comes back near 1.0, check the measure
before believing it: a template that emits one sentence per fact would make
recall trivially 1.0, which measures the template and not the narrative — the
same pathology as the fixed-threshold F1 and the verifier that could not fail.

**Effort.** 3–4 days. **Dependencies.** Phase 0. Nothing else.

---

### Phase 6 — independent sample via AMLGentex (2–4 days) · conditional

**Objective.** Attack the constraint that gates every other conclusion: 18
held-out cycles, 370 rings, almost all of them already inside the eval window.

**Work items.**
1. **First hour, and it decides the phase:** determine whether AMLGentex can
   emit **group ids** for injected SAR patterns, not only per-account binary
   labels. Check the generator's intermediate state, not the exported CSV.
2. If yes: generate five to ten independent worlds with different seeds, ingest
   through `sentinel/data/`, and register them in `sentinel/corpus/` with a
   distinct `dataset` key so `require_same_dataset` refuses to pool them with
   AMLworld. The guard already exists and already caught this class in the
   identity domain.
3. Re-measure the shipped blend, the size baseline, and the fragmentation
   coverage on the new worlds. **Report per-dataset, never pooled.**

**Pre-registered expectations.**
- **Absolute p@k will differ**, possibly a lot, and that is not a failure — a
  different generator makes different rings.
- **The size-baseline margin's sign should replicate.** That is the transferable
  claim, and it is the one worth testing.
- Intervals across pooled *independent worlds* narrow roughly as the square root
  of the sample ratio.

**Kill criterion.** No group ids means the phase is dead on arrival. **Do not
retarget it at an account-level metric.** That silently changes the unit of the
whole project's headline and is exactly what `POOLING_VALIDITY` and
`require_same_dataset` exist to refuse.

**Effort.** 2–4 days if labels cooperate; one hour if they do not.
**Dependencies.** None technically. **Ranked below Phase 5** on deadline risk:
it is the most valuable thing for the *project* and among the least valuable for
the *submission*.

---

### Phase 7 — re-derive the ceiling (half a day) · run LAST

**Objective.** The defended no-label ceiling in `docs/ARCHITECTURE_UPLIFT.md`
has been exceeded and has not been re-derived, which is currently deliberate.
The shipped blend reads 0.2912 over 34 cycles and 0.1889 over 18 held-out
cycles; ring recall is 23.9%.

**Work items.** After Phases 2 and 3 land (or are killed), restate the ceiling
with its conditioning made explicit: for which frame (34-cycle shipped versus
18-cycle held-out — they differ by more than 0.10 and are routinely confused),
under which candidate-set convention (Phase 1's ordering), and with the size
baseline alongside. Keep the old estimate visible with the date it was written;
this project corrects in place.

**Pre-registered expectation.** The revised no-label ceiling lands at **p@10
0.20 to 0.30 in the 34-cycle shipped frame** and **0.15 to 0.22 in the 18-cycle
held-out frame**, with ring recall **26 to 33%**.

**Kill criterion.** None — this is a restatement, not an experiment. But it must
**not** be run before Phases 2 and 3, or it will be re-derived twice and the
first version will leak into prose. That is the template-literal-leak failure
mode.

**Effort.** Half a day. **Dependencies.** Phases 2 and 3 resolved either way.

---

### What is explicitly NOT worth doing

**NOT-1. The Elliptic2 real-data run.** The brief that prompted this plan lists
it; I recommend **cancelling it outright**, not deferring it.
`docs/negative-results/elliptic2-cancelled.md` establishes that Elliptic2
*ships* its subgraphs while this project *constructs* them, so under
`POOLING_VALIDITY` a **recall** comparison is invalid at any compute budget. The
only admissible question is a **scorer** question — and the scorer is the one
component measured *not* to be the bottleneck. So the cost is: a Kaggle token
the user has not created, a 49M-node, 196M-edge download onto a disk that
already could not hold the extracted archive (commit `3e6a4ba`), and an ingest
path, in exchange for a measurement on the component that does not matter.
**AMLGentex (Phase 6) is the strictly better answer to the same underlying
need** — it produces seed-and-expand-compatible constructed candidates, so a
*recall* comparison is legal there.

**NOT-2. Widening the seed rule.** Ruled out three times: §5b (seeding already
reaches nearly nine tenths of active rings), §5c (all three expansion knobs
inert by experiment), and now the fragment catalogue (the seed is *present*, it
is stranded). Firing the seed rule on more accounts does not reach a fragment
that has no ring edges to the seed.

**NOT-3. More expansion budget.** Refuted, and it fails backwards:
`docs/negative-results/builder-budget-refuted.md`. More budget means more
containment and less coverage, symmetrically on rescued and recovered rings.

**NOT-4. Shipping LambdaMART.** It now beats the pointwise model CI-clear at
every k — but the gain was bought by deleting nearly half the training
positives, and **both absolute numbers fell**. The honest description is
"degrades less", not "better". Commit `63066d1`'s own message says so. Beyond
that: the scorer is not the bottleneck, so a better scorer is a small win on the
wrong axis.

**NOT-5. Grounding the six cost-model inputs to produce absolute rupee
figures.** The inversion (`required_value_at_risk(p)`) is strictly better — it
lets a reader who rejects every input still check the claim — and the joint
worst-case break-even of 1.8382 is already the honest headline. Sourcing six
placeholders to emit a rupee number would add a confident figure resting on
assumptions nobody can check, which is bug #8's category.

**NOT-6. A GNN, cuGraph or GPU anything, Kafka or Flink, or chasing thousands of
features.** Compute is not the bottleneck: a 3.02x speedup already shipped,
Leiden on the window takes seconds, and a full replay takes under a minute.
Vulcan cannot be reached — roughly three trillion data points across four
billion payments, built with NVIDIA and AWS — and nothing in this plan should be
presented as approaching it.

**NOT-7. Lowering the Jaccard floor.** It would convert the dilution-failed
rings to "built" overnight without the detector improving. Bug #8 a second time.

**NOT-8. Shortening `every_ticks` to widen the cycle count.** At a 72h window,
cycles 6h apart already overlap heavily and 2h apart are near-duplicates.
Resampling near-duplicates narrows the interval spuriously.

**NOT-9. A third domain.** Two is already scope risk at submission, and the
cross-domain claim that justified the second was refuted.

---

## 5. Part D — risks: what in this plan is most likely to disappoint

Ordered by expected disappointment, most likely first.

**1. The seeding prize may be structurally uncollectable, and Phase 2 is where
that becomes visible.** The cheat seeds every ring member — it uses ring
identity. There may be no label-free signal that distinguishes "the other
fragment of this ring" from "an unrelated neighbourhood two hops away." If so,
the entire detector arm of this plan is capped at a couple of points and the
honest ceiling sits much closer to today's number than the cheat implies.
**This is the single largest exposure in the plan**, it applies to Phases 2 and
3 together, and it should be stated in the submission *before* anyone asks.

**2. Phase 2's most likely outcome is a recall gain with a null precision
delta.** Fragment linking grows candidates, and every size-growing change in
this project's history has moved the size baseline with it. The realistic good
outcome is "built recall up five points, p@10 interval includes zero, size
margin holds" — a legitimate, unexciting result that belongs in
`docs/negative-results/` and not in a headline.

**3. Eighteen held-out cycles will not resolve anything below about +0.05.**
`docs/ARCHITECTURE_UPLIFT.md` §9.2 said this and it has been right every time
since. Phases 2 and 3 are both pre-registered to expect intervals that include
zero. **If the plan is judged by whether it produced a CI-clear p@k gain, it
will look like a failure.** The fallback is what this project already does well:
report the point estimate with its interval and refuse to headline it. Phase 6
is the only structural fix and it is conditional on a label format.

**4. Decoupling suppression (Phase 1) may cost more than the pre-registration
allows.** About a quarter of the blend-fix effect was survivor selection. If the
cost exceeds the kill threshold, every subsequent scorer experiment gets
substantially more expensive, which compresses Phases 2 and 3 against the
deadline.

**5. GFP parity may come back showing GFP's feature block is better.** That
lowers the defended ceiling rather than raising it —
`docs/ARCHITECTURE_UPLIFT.md` §12.4 already says so. It should be run and
published anyway; a comparison you only publish when it flatters you is not a
comparison. But do not schedule it expecting good news.

**6. The likeliest submission failure is not a number — it is an unnavigable
repository.** Build Quality is an explicit judging axis. There are twenty-odd
documents in `docs/`, several of which contain corrections to corrections, and
`HANDOFF.md` alone is 1,497 lines that must be read non-linearly to avoid acting
on superseded conclusions — its own §10 carried a stale next step through four
rounds of corrections above it. A judge with twenty minutes will not find the
good parts. Phase 5 item 1 is the mitigation and it should not be cut.

**7. The deadline may be days, not weeks.** The 5 September 2026 date is an
*application* deadline from a secondary source, with build rounds after, and it
is **unverified against Razorpay's own materials**. If the build window is
short, Phases 1 to 3 and 6 are all wasted motion. **Verify the actual build
deadline before starting Phase 1.**

**8. Two of this plan's own claims could be wrong in the way this project keeps
catching.** The fragment-linking rule in Phase 2 will be new code on the
measured path, written against a mechanism inferred from a descriptive catalogue
at n = 49. Two of the seventeen catalogued bugs were written *during* this work
and caught by its own instrumentation. Assume Phase 2 ships at least one
plausible-wrong-answer defect, and budget the re-tie investigation for it rather
than treating a good first number as a result.

---

## 6. Sources

**Internal** (this repository; `data/*.json` is gitignored and exists only on
the author's machine — `results/metrics.json` is tracked and authoritative):
`docs/HANDOFF.md` · `docs/HANDOFF-NEXT.md` · `docs/CENTREPIECE-INVALIDATED.md` ·
`docs/ARCHITECTURE_UPLIFT.md` · `docs/STANDING-RULES.md` ·
`docs/PHASE2-SEED-CHEAT-FINDINGS.md` · `docs/PHASED-FRAGMENTATION.md` ·
`docs/PHASEE-CASE-FILES.md` · `docs/SCORE-VS-SIZE-FINDINGS.md` ·
`docs/negative-results/` (thirteen entries) · `results/metrics.json` ·
`sentinel/config.py` · `sentinel/detect/candidates.py` ·
`sentinel/detect/merge.py` · `sentinel/detect/prune.py` ·
`sentinel/detect/features.py` · commits `a0cbbec`, `b1ef656`, `63066d1`,
`82e2997`, `8453492`, `a7ee53e`, `143bd38`.

**External** — comparators and methods:
- IBM Graph Feature Preprocessor — [arXiv:2402.08593](https://arxiv.org/html/2402.08593v2) · [ACM ICAIF'24](https://dl.acm.org/doi/10.1145/3677052.3698674) · [IBM/snapml-examples](https://github.com/IBM/snapml-examples)
- AMLworld / HI-Small — [Altman et al., NeurIPS 2023, arXiv:2306.16424](https://arxiv.org/abs/2306.16424) · [IBM/AML-Data](https://github.com/IBM/AML-Data)
- Multi-GNN — [IBM/Multi-GNN](https://github.com/IBM/Multi-GNN) · [arXiv:2306.11586](https://arxiv.org/abs/2306.11586) (AAAI 2024)
- AMLSim — [IBM/AMLSim](https://github.com/IBM/AMLSim/) · [typology wiki](https://github.com/IBM/AMLSim/wiki/Transaction-Model:-Alert-Model)
- AMLGentex — [aidotse/AMLGentex](https://github.com/aidotse/AMLGentex) · [arXiv:2506.13989](https://arxiv.org/abs/2506.13989)
- Tide, a customisable AML dataset generator (2026) — [arXiv:2603.01863](https://arxiv.org/pdf/2603.01863) *(code availability unverified)*
- Elliptic2 — [MITIBMxGraph/Elliptic2](https://github.com/MITIBMxGraph/Elliptic2) · [arXiv:2404.19109](https://arxiv.org/abs/2404.19109)
- GARG-AML — [B-Deprez/GARG-AML](https://github.com/B-Deprez/GARG-AML) · [arXiv:2506.04292](https://arxiv.org/abs/2506.04292)
- FlowScope — [csqjxiao/FlowScope](https://github.com/csqjxiao/FlowScope)
- AutoAudit — [mengchillee/AutoAudit](https://github.com/mengchillee/AutoAudit)
- Spade — [arXiv:2211.06977](https://arxiv.org/abs/2211.06977) (VLDB 2023)
- SpecGreedy — [wenchieh/specgreedy](https://github.com/wenchieh/specgreedy)
- AntiBenford subgraphs — [arXiv:2205.13426](https://arxiv.org/abs/2205.13426) (KDD 2022)
- Local community detection — [LJeub/LocalCommunities](https://github.com/LJeub/LocalCommunities) · [kkloste/lemon-sqz](https://github.com/kkloste/lemon-sqz) · [HeidelbergMotifClustering](https://github.com/LocalClustering/HeidelbergMotifClustering) · [arXiv:2205.06176](https://arxiv.org/pdf/2205.06176)
- Toolboxes and indices — [pygod](https://github.com/pygod-team/pygod) · [DGFraud](https://github.com/safe-graph/DGFraud) · [UGFraud](https://github.com/safe-graph/UGFraud) · [GADBench](https://arxiv.org/abs/2306.12251) · [graph-fraud-detection-papers](https://github.com/safe-graph/graph-fraud-detection-papers) · [AI4Risk/awesome-fraud-detection](https://github.com/AI4Risk/awesome-fraud-detection)
- Jube — [jube-home/aml-fraud-transaction-monitoring](https://github.com/jube-home/aml-fraud-transaction-monitoring)
- Same-track competitor — [SS072/Rezorpay](https://github.com/SS072/Rezorpay) · [Hunter764/GraphMule](https://github.com/Hunter764/GraphMule)
- Neo4j GraphRAG for KYC — [neo4j.com](https://neo4j.com/blog/developer/graphrag-in-action-know-your-customer/)

**External** — context (all previously cited in
`docs/ARCHITECTURE_UPLIFT.md`; repeated here so this document stands alone):
- Razorpay Vulcan — [AWS/Razorpay press release, 18 Aug 2026](https://press.aboutamazon.com/aws-international/2026/8/razorpay-launches-vulcan-indias-first-ai-payments-foundation-model-fueled-by-nvidia-and-aws-re-architecting-payments-for-a-350-bn-e-comm-future-by-2030)
- Razorpay AI Buildathon 2026 tracks, criteria and application deadline — [Velonx](https://velonx.in/blog/razorpay-ai-buildathon-2026-tracks-eligibility-stipend-selection-process) · [DEV Community](https://dev.to/devengers/dev-opportunity-radar-14-mlh-global-hack-week-40k-agents-for-humans-hackathon-razorpay-ai-2b9g) — **secondary sources; the exact "abuse-ring sentinel" wording and the four judged parameters are UNVERIFIED against Razorpay's own materials and must be re-checked.**
- RBI MuleHunter.AI, twenty-three banks — [MediaNama RTI report, Dec 2025](https://www.medianama.com/2025/12/223-rti-23-banks-mulehunter-mule-accounts/). The RBI declined under RTI to disclose accounts identified, so circulating monthly-account figures are capability claims, not verified outcomes.
- RBI DPIP — [Business Standard, Jun 2025](https://www.business-standard.com/industry/banking/rbi-banks-to-launch-dpip-platform-to-combat-rising-digital-payment-frauds-125062200370_1.html)
