# Architecture uplift plan

**Status:** plan only. Nothing here is implemented. Written 29 Aug 2026 against
commit `ee0607d`.

**Scope.** How to raise FraudOps/Sentinel's efficiency, reliability and quality
toward the level of the three systems it is measured against in conversation —
IBM's Graph Feature Preprocessor (GFP), Razorpay Vulcan, and HDFC Bank's
in-house fraud platform. Two of those three are not reachable and this document
says so plainly. The one that is reachable — GFP — is reachable because it is
the same architecture class this project already occupies.

**Reading rules.** Every external claim carries a link. Anything I could not
verify is marked **[unverified]**. Every proposed change carries a
**pre-registered expected direction**, so that when the measurement comes back
we can tell the difference between a result and a rationalisation. Where I
measured something myself in this session, it is marked **[measured today]**
with the method.

---

## 0. The state this plans from

All post-correction, all from `docs/HANDOFF.md` §3–§5e and `data/*.json`.

| quantity | value |
|---|---|
| rings seeded / built / ranked-top-50 (of 230 seeded) | 230 / 162 (63%) / 49 (19%) |
| ring recall | 20.1% |
| p@10 / p@20 / p@50 (score, post-prune) | 0.097 / 0.079 / 0.043 |
| p@10 / p@20 / p@50 (size baseline, post-prune) | 0.088 / 0.074 / 0.049 |
| paired (score − size), post-prune | k=10 +0.009 [−0.027,+0.041]; k=20 +0.006 [−0.021,+0.031]; k=50 −0.007 [−0.019,+0.005]; k=100 −0.009 [−0.016,−0.002] |
| paired prune gain (leaf2 − none) | k=10 not a gain; k=20/50/100 real |
| oracle (LightGBM, true labels, same features), real seeding | AP 0.1875, p@10 0.239, p@20 0.153 |
| oracle, perfect seeding | AP 0.2678, p@10 0.467, p@20 0.475 |
| re-ranker lift over v1 | every paired CI at k=5/10/20/50 includes zero (n=17 cycles) |
| threshold-free transaction level | AP 0.0113 vs 0.0067 base = 1.7× |
| structural recall ceiling | 73.3% |

The two findings that drive everything below:

1. **The scorer is the bottleneck.** The oracle gets p@10 0.239 on the *same*
   features the hand-set blend gets 0.085 on. After pruning, the blend's margin
   over a node-count baseline collapsed to noise at k=10/20/50 and reversed
   significantly at k=100.
2. **Neither current ranker earns its place.** The hand blend no longer beats
   size; the learned re-ranker's lift does not survive its own paired CI.

**A caveat on finding 1 that nobody has recorded yet, and it is load-bearing.**
`data/eval_oracle.json` was written 26 Aug 21:03. `sentinel/detect/prune.py`
shipped 27 Aug 10:55 (`0b3157f`). **The oracle ceiling was measured on the
pre-prune candidate distribution.** Pruning changed mean candidate size from 17
to 8.2 nodes and changed which rings are reachable. The 2.8× gap is a claim
about a candidate pool that no longer exists. It is probably still directionally
right — but "probably" is exactly the word this project does not accept
elsewhere, and re-running the oracle is ~30 minutes of compute. That is item
**0.1** below and it gates the entire centrepiece.

Two smaller corrections to the record while we are here:

- `data/eval_oracle.json` still carries
  `"interpretation": "F1 < 0.20: the feature-parity claim does not hold up.
  Feature engineering should be prioritised ahead of weak-supervision work."`
  That conclusion is reasoned from the fixed-0.5-threshold F1 that HANDOFF §3
  has since established is a pathology, not a measurement. The stored
  interpretation contradicts the corrected reading of its own file and should
  be deleted or rewritten.
- The oracle's p@10 = 0.239 is computed over **held-out test cycles only**
  (`ring_time_split`, ~17 cycles). The blend's 0.097 is over **all 34 cycles**.
  These are not the same denominator. The "2.8×" is quotable only after the
  blend is evaluated on the oracle's own test cycles. Item **0.2**.

---

## 1. The scorer rewrite — the centrepiece

### 1.1 What is actually wrong

The v1 score (`sentinel/detect/features.py:253`) is a fixed linear blend of 13
terms with hand-set weights summing to 1.0. Three structural problems, in
descending order of how much I think they cost:

**(a) It is pointwise and the metric is listwise.** p@k is computed per cycle:
candidates within one generation cycle compete for 10/20/50 slots. The blend
produces an absolute score with no reference to the cycle it sits in, so a
cycle with 15k candidates and a cycle with 2k candidates are ranked against the
same implicit thresholds. The learned re-ranker
(`sentinel/learn/reranker.py:131`) does not fix this — it is a
`HistGradientBoostingClassifier`, i.e. still pointwise, optimising log-loss over
the whole pool. With ~1–3 positives per cycle against ~15k negatives, almost all
of that gradient is spent separating negatives from each other far below the
cut. **This is the clearest mismatch in the system and it is also the cheapest
to fix.**

**(b) It is a partial size proxy and nothing prevents that.** Several terms are
extensive (grow with candidate size): `scatter_gather_width`,
`gather_scatter_width`, `fan_out_count`, `fan_in_count`, `n_banks`,
`n_entities`, `n_txns`, `burstiness`, `max_fan`. Others are intensive
(scale-free): `conservation`, `passthrough_ratio`, `cycle_coverage`,
`fast_passthrough_ratio`, the GARG-AML block densities. HANDOFF §5d offers two
readings of the post-prune re-tie and does not separate them. They are
separable, cheaply, and §1.4 below says how.

**(c) It throws away information the pipeline already computes.** Three items
sit on the `Candidate` dataclass but never reach the feature vector, because
`reranker.feature_names` reads `c.features` (the `Features` dataclass) and not
the candidate:

- `absorbed` / `absorbed_seeds` — how many *independent* seeds discovered this
  same neighbourhood. That is a corroboration signal and it is close to
  orthogonal to both structure and size. `merge.py`'s own docstring calls it
  "corroboration rather than discarded" and then the ranker discards it.
- the `expand_traced` trace (`hub_blocked`, `truncated`, `hops_completed`,
  `exhausted`) — "this candidate was cut short by the hub guard" is a strong
  prior that the candidate is incomplete.
- the seed's own degree and role.

That is three free features, zero new computation.

### 1.2 Options, weighed

**Option A — learning-to-rank with a listwise objective (LambdaMART).**

Replace `HistGradientBoostingClassifier` with `lightgbm.LGBMRanker`,
`objective="lambdarank"`, query group = generation cycle,
`eval_at=[10,20,50]`. LambdaMART weights each pairwise swap by the change it
causes in the ranking metric ([Burges 2010, *From RankNet to LambdaRank to
LambdaMART*](https://www.microsoft.com/en-us/research/publication/from-ranknet-to-lambdarank-to-lambdamart-an-overview/)),
which concentrates the gradient exactly where p@k is decided — the top of each
cycle's list — instead of spreading it over 15k negatives.

lightgbm 4.7.0 **is installed and works on this machine's Python 3.14**
[measured today: `import lightgbm` succeeds]. `scripts/eval_oracle.py` already
imports `LGBMClassifier`. So this is a same-day change: same features, same
corpus, same eval harness, different objective plus a `group` array.

**Verdict: do this first.** It is the only option that changes the training
objective to match the reported metric, and it is nearly free.

**Option B — programmatic weak supervision (Snorkel-style label model).**

Write labelling functions over the heuristics (temporal cycle present;
`fast_passthrough_ratio` above threshold; `conservation` near 1; `gargaml`
positive; `entity_reuse > 1`; bipartite/stack density high), let a generative
label model estimate their accuracies from their agreement structure without
ground truth, emit probabilistic labels, train a discriminative ranker on them
([Ratner et al., *Snorkel*, VLDB 2017](https://arxiv.org/abs/1711.10160);
[*Data Programming*, NeurIPS 2016](https://arxiv.org/abs/1605.07723)).

**Verdict: rank this last in the scorer tier, and be willing to kill it.** The
reason is specific, not a general dislike. Snorkel's label model recovers LF
accuracies from *disagreement* between sources that are conditionally
independent given the true label, unless the dependency structure is specified
explicitly. Here every candidate LF is a function of the *same* induced
subgraph — `gargaml`, `bipartite`, `stack`, `passthrough_ratio` and
`cycle_coverage` are all read off one adjacency matrix. They are massively
dependent by construction, which is the regime where the label model degrades
toward majority vote. And HANDOFF §5 already measured two of them as
near-constants (`gather_scatter` fires on 50% of candidates, `cross_border` on
61%): an LF that almost never abstains and almost always votes the same way
contributes no information to the label model at all.

More fundamentally: the LFs *are* the blend's own terms. A label model over them
can reweight; it cannot add information. The oracle says the information is
already in the features. The question is whether a no-label method can recover
the oracle's weighting — and a listwise ranker trained on real analyst verdicts
is a more direct attempt at that than a label model over correlated heuristics.
Budget Option B one day, gate it on beating v1's point estimate, drop it
otherwise.

**Option C — positive-unlabeled framing.** The verdict corpus is one-sided:
`confirmed_ring` is a reliable positive; `not_a_ring` is a *reviewed* negative
but the unreviewed ~15k are unlabeled, not negative. Training as though they are
negative biases the model. PU learning with a class-prior estimate
([Elkan & Noto, KDD 2008](https://dl.acm.org/doi/10.1145/1401890.1401920)) is
the principled correction. **Verdict: worth doing, but as a refinement of Option
A's loss weighting rather than a separate model.** The existing control arm
(`CONTROL_FRACTION = 0.10`, `sentinel/cases/manager.py:28`) is exactly the
unbiased sample a PU prior estimate needs — a real asset this project has and
most do not. Note the defect already flagged in HANDOFF §11c: the control
propensity is approximated as `1/CONTROL_FRACTION` rather than recorded per
cycle. Fix that at `CaseManager.select` time before relying on it for a prior.

**Option D — a GNN.** **Verdict: no.** Both direct comparators argue against it.
GFP beats a PNA GNN on this dataset with hand features plus boosting on CPU
([arXiv:2402.08593](https://arxiv.org/html/2402.08593v2), Table 4: GFP+XGBoost
63.23 vs PNA 56.77 minority-class F1), and GARG-AML's entire argument is that an
interpretable block-density score is preferable for AML because the case has to
be explainable ([arXiv:2506.04292](https://arxiv.org/abs/2506.04292)). This
project's product is a case file an analyst can interrogate. A GNN is the wrong
tool for the stated thesis and there is no measured evidence it would help.

### 1.3 Calibration

p@k does not need calibrated scores. Two things downstream do:

- `CostModel.required_value_at_risk(p)` takes a precision. If the precision fed
  to it is a point estimate over 34 overlapping cycles, the break-even figure
  inherits that uncertainty and should be reported as an interval, not a number.
- Queue capacity and the escalation threshold are decisions about an absolute
  probability, not a rank.

Plan: fit isotonic regression on held-out cycles
(`sklearn.calibration.CalibratedClassifierCV`, `method="isotonic"`), report a
reliability diagram, Brier score and ECE, **and state the sample-size caveat in
the same breath**: with ~1–3 positives per cycle over 17 held-out cycles,
isotonic calibration will overfit. Report the bootstrap CI on ECE. If the
interval is uninformative, say the model is uncalibrated and use rank-based
operating points instead. Do not ship a calibration curve you cannot defend.

### 1.4 Avoiding the size re-tie by construction

This is the part that has to be designed rather than tested-after. Three
constructions, in the order I would apply them:

**(i) Intensive-only ablation — the diagnostic, do this first.** Partition the
feature set into intensive (scale-free) and extensive (size-growing) and train
the oracle twice. The delta is a *measurement* of how much of the 0.1875 AP
ceiling is size exploitation. HANDOFF §5d's two competing readings ("pruning
made size a real signal" vs "the score was always partly a size proxy") are
exactly this quantity, and it has never been measured.

**This is the single most important diagnostic in the plan** because it can
invalidate the plan. If the intensive-only oracle collapses toward the size
baseline, then the features do *not* contain much size-independent signal, and
the correct response is new features (§2), not a new ranker (§1.2).

**(ii) Size-stratified evaluation — the reporting discipline, permanent.**
Bucket candidates by node count (3–5, 6–9, 10–15, 16+), and report p@k *within
each stratum against the size baseline within that stratum*. A global size
baseline can win simply by concentrating on the most productive stratum; a
within-stratum comparison cannot be won that way. This should replace the
current global baseline table as the headline, not supplement it.

Optionally also *rank* stratified with a slot quota per bucket, which makes the
top-k un-tie-able with size by construction. Note honestly that this is a
constraint, not an improvement: it can only lower unconstrained p@k. Its value
is that whatever it achieves is provably not size.

**(iii) Size residualisation — only if (i) says size carries real signal worth
keeping.** Fit `ŝ(n) = E[hit | n_nodes = n]` by isotonic regression on train,
rank by `score − ŝ(n_nodes)`. By construction the residual score has no marginal
AP from size alone. The cost is that genuine size information is thrown away,
which is why this is third and conditional.

**(iv) Within-cycle normalisation.** Rank-transform or z-score scores within
each generation cycle before any cross-cycle aggregation. Free, addresses
§1.1(a) partially even without a listwise objective, and a listwise objective
gets it natively.

### 1.5 Validation protocol — non-negotiable, applies to every variant

Every scorer variant is evaluated by `scripts/eval_prune_impact.py`-style
**paired** bootstrap on the **same** cycles (`sentinel/eval/bootstrap.py`
already implements this correctly) against, at minimum:

1. `size` — node count
2. `degree` — `max_fan`
3. `random`
4. **the v1 hand blend** — currently not run as a baseline against the learned
   ranker in the same paired frame
5. **best-single-feature** — the strongest individual feature chosen on train,
   applied unchanged on test. **This baseline does not exist today and it is the
   one that matters most.** A learned ranker that cannot beat `conservation`
   alone is not a ranker; it is an expensive way to compute `conservation`.

Ship criterion, stated in advance: **the paired delta (variant − size) must
exclude zero at k=10 and at k=20.** Not k=50 alone, not the point estimate, not
"the CIs overlap but the point is higher". This project has already been burned
twice by the weaker version of this rule (HANDOFF §3, §5e) and the rule cuts
both ways — a claimed loss whose CI includes zero is also not a loss.

---

## 2. Closing on IBM GFP

GFP is the direct architectural comparator: hand-engineered subgraph features
plus gradient boosting, on CPU, beating a PNA GNN on the same dataset
([ICAIF'24, arXiv:2402.08593](https://arxiv.org/html/2402.08593v2);
[ACM DL](https://dl.acm.org/doi/10.1145/3677052.3698674);
[snapml-examples notebook](https://github.com/IBM/snapml-examples/blob/main/examples/graph_feature_preprocessor/graph_feature_preprocessor.ipynb)).

### 2.1 The blocker, and how to clear it

**THIS SECTION WAS WRONG AND THE CORRECTION IS THE USEFUL PART.** It read:
*"`snapml` ships cp310 and cp311 win_amd64 wheels for 1.15.6; there is no build
for 3.12+; this machine has only 3.14. So the control run is blocked on
provisioning an interpreter, not on the package existing"* — and ranked
option 1 below as "~30 minutes, lowest risk, **do this one**".

Option 1 was done. It does not work, and the reason invalidates the whole
ranking:

- `py -3.11 -m venv .venv311` and `pip install snapml==1.15.6` both succeed.
- `from snapml import GraphFeaturePreprocessor` succeeds.
- `GraphFeaturePreprocessor()` raises `module
  'snapml.libsnapmllocal3_avx2' has no attribute 'gf_allocate'`.
- **No `.pyd` in the Windows wheel exports any `gf_*` symbol** (checked against
  all six). The manylinux wheel of the same version exports all eight.
- snapml **1.17.x ships no Windows wheels at all**; 1.15.6 is the last Windows
  release.

**GFP is Linux/macOS-only.** The interpreter was never the obstacle.

### How to actually run it (the repo owner has a Fedora dual boot)

```bash
git pull
./scripts/gfp_setup_linux.sh --limit 2     # smoke test, ~minutes
./scripts/gfp_setup_linux.sh               # the real run
```

The script provisions a venv on the newest Python snapml has a wheel for
(3.9-3.12; **Fedora 41+ defaults to 3.13, which has no build**), pins
`numpy<2` because snapml 1.15.6 is compiled against numpy 1.x and dies with
`_ARRAY_API not found` otherwise, verifies `GraphFeaturePreprocessor()`
actually constructs, then runs stages 2 and 3.

The **export is ~700 MB and gitignored**, so it is not in the clone. Point at
the Windows partition's copy rather than regenerating:

```bash
EXPORT_DIR=/run/media/$USER/<windows>/Users/Pranav/Documents/PayopsAnalyst/data/gfp_export   ./scripts/gfp_setup_linux.sh
```

That guarantees byte-identical candidates instead of a replay that ought to be
identical. `data/eval_gfp.json` is small — commit it back, and treat its
`verdict` string as the only thing that licenses any GFP statement anywhere in
the repo.

Options, re-ranked against the real obstacle:

1. ~~**`py -3.11 -m venv .venv311 && pip install snapml lightgbm pandas`.**~~
   **RULED OUT BY EXPERIMENT.** No Python version helps on Windows.
2. **A Linux environment — WSL, a container, or a CI runner.** This is now the
   *only* local route. WSL needs Administrator to install, which is why this
   is a decision for the repo owner rather than something a session can just
   do. The AMLworld CSVs are already on disk and WSL reads them through
   `/mnt/c`, so no data has to move.
3. **Reimplement GFP's families natively.** **Not worth doing as a control.** A
   reimplementation of GFP compared against `sentinel/` measures your
   reimplementation, not GFP. Reimplementing the *missing* families into
   `sentinel/` (§2.3) is a different, worthwhile task — keep the two strictly
   separate and never let one be reported as the other.

### 2.2 The actual feature diff — and where the parity claim is false

GFP's published families ([arXiv:2402.08593](https://arxiv.org/html/2402.08593v2)):
fan-in, fan-out, gather-scatter (single-hop); scatter-gather, simple cycles,
temporal cycles (multi-hop); vertex statistics (sum, mean, min, max, median,
variance, skew, kurtosis) over **transaction amounts and timestamps**. No
cliques or bicliques. Parameters for AML: scatter-gather window 6 h, simple
cycle window 1 day, cycle length bound 10 hops.

| GFP family | `sentinel/` | verdict |
|---|---|---|
| fan-in / fan-out | `motifs.fan_in_count`, `fan_out_count`, `max_fan` | ✅ |
| gather-scatter | `find_gather_scatter` | ✅ |
| scatter-gather | `find_scatter_gather` | ⚠️ **no time window.** GFP bounds the shape at 6 h; sentinel bounds it not at all. A scatter-gather spread over 72 h is a different object. |
| simple cycles | `find_cycles`, `MAX_CYCLE_LEN = 8`, cap 200 | ⚠️ GFP uses 10 hops and a 1-day window; sentinel uses 8 hops and the full 72 h window. |
| temporal cycles | `is_temporally_valid` | ✅ |
| vertex stats on **amount** | `AccountStats` computes Welford moments, but only `max_amount_skew` and `mean_velocity` reach the candidate vector | ⚠️ **partial.** sum/mean/min/max/median/variance are computed per account and never aggregated into `Features`. |
| vertex stats on **timestamps** | — | ❌ **absent.** `span_minutes`, `burstiness`, `median_dormancy_h` are related but are not the moment set. |
| cliques / bicliques | — | ✅ (GFP does not compute them either) |

So HANDOFF §4's *"Essentially at parity"* is **wrong in three specific,
correctable places**: the un-windowed scatter-gather, the missing timestamp
moments, and the amount moments computed but not propagated. That is a more
useful finding than a checklist of ticks, and each is a small change.

### 2.3 What would make "feature parity" a *measured* claim

Today it is a coverage checklist: someone read both feature lists and compared
names. To convert it into a measurement:

1. Provision 3.11, install snapml, run `GraphFeaturePreprocessor` over HI-Small
   in the paper's own configuration.
2. **Reproduce the paper's own number first** (GFP+LightGBM 62.86 minority-class
   F1). If you cannot reproduce it, you cannot compare against it, and the
   honest report is "control did not reproduce", not a partial quote.
3. **The granularity problem, stated rather than papered over.** GFP emits
   features per *transaction*. Sentinel emits them per *candidate*. Two ways to
   make them comparable:
   - **(a)** project sentinel's candidate features down onto edges (each edge
     inherits, max-pooled, the features of candidates containing it) — this is
     what `scripts/eval_vs_published.py` already does for the score alone;
   - **(b)** aggregate GFP's transaction features up to sentinel's candidate
     node-sets (mean/max/sum over member edges) and compare the two feature
     blocks under **sentinel's own ring-level p@k**, in the paired-bootstrap
     harness of §1.5.

   **(b) is the better experiment** and should be the headline. It answers a
   question the paper does not: do GFP's features rank *rings* better than
   sentinel's? (a) is worth running only as a secondary check.
4. The measured claim then reads: *"substituting GFP's feature block for
   sentinel's changes ring-level p@10 by X [CI]"*. Anything short of that stays
   labelled UNMEASURED, as `scripts/eval_oracle.py`'s `gfp_note` already
   correctly does.

**Do not chase GFP's 62.86 F1 as a target.** It is a supervised, per-transaction,
thresholded F1. Quoting this system's numbers against it is the comparison
HANDOFF §3 already established is invalid.

---

## 3. Vulcan-class engineering

### 3.1 What is actually public, separated from what is asserted

From the joint AWS/Razorpay press release, 18 Aug 2026
([press.aboutamazon.com](https://press.aboutamazon.com/aws-international/2026/8/razorpay-launches-vulcan-indias-first-ai-payments-foundation-model-fueled-by-nvidia-and-aws-re-architecting-payments-for-a-350-bn-e-comm-future-by-2030);
coverage: [Business Standard](https://www.business-standard.com/industry/news/razorpay-builds-proprietary-ai-model-vulcan-to-boost-payment-success-rates-126081801078_1.html),
[DQ India](https://www.dqindia.com/news/razorpay-vulcan-8x-fraud-detection-baseline-12398348)):

- transformer-based payments foundation model, explicitly **not an LLM**
- trained on **~3 trillion data points across ~4 billion payments**
- **~3,000 signals per transaction**
- NVIDIA GPUs for training and serving; AWS including SageMaker
- **8× more international card fraud** detected and stopped
- **5× more fraudulent or disputed transactions identified, without increasing
  the number of alerts**
- **Network-Level Fraud Detection**: "spots fraud visible only across merchants,
  flagging a stolen card the moment it's used across unrelated sellers"
- up to 10% lift in payment success rates (routing, not fraud)

**What is marketing.** All of the above are first-party claims in a launch press
release. No specific GPU models, **no latency figure, no throughput figure**,
and — the part that matters by this project's own standards — the 8× and 5× have
**no stated baseline, no evaluation window, no population definition and no
interval**. A multiplier without a denominator is not a result. That is not a
dig at Razorpay; it is the standard this repo applies to its own numbers and it
should be applied symmetrically, in writing, wherever Vulcan is cited.

**What is genuinely worth stealing** is the *framing* of the second claim:
"without increasing the number of alerts." That is the correct way to report a
fraud improvement, and precision@k *is* that frame — a fixed alert budget. Adopt
the wording: report every improvement as **Δ at constant alert budget**.

### 3.2 What "Vulcan-class" means for this project, component by component

| dimension | what Vulcan-class implies | verdict for this project |
|---|---|---|
| **Streaming vs batch** | continuous scoring on a live topic | **Already the right shape.** `Stream.ticks` + `WindowedGraph` is a replayable stream abstraction. Do not add Kafka. The abstraction is the valuable part; the broker is not. |
| **Incremental graph maintenance** | O(Δ) work per event | **Half done, and this is the real gap.** Edge insert/expire is genuinely incremental (`add_batch`/`_expire`, 10.6 s total across 49 ticks [measured today]). **Candidate generation is not** — every cycle re-expands every seed from scratch. This is also the largest efficiency win (§5), so the two motivations coincide. |
| **Latency budget** | <100 ms for an authorisation decision | **Do not try to match, and say why.** This system sits *behind* the authorisation path, not in it: its output is a case for a human, and the human is the slow step by design. But it should still declare and measure a budget of the right kind — e.g. *"a ring surfaces within one tick (60 min) of the edge that completes it"* — and report the distribution, not the mean. Nothing measures this today. |
| **Throughput** | end-to-end sustained TPS | **Stop quoting 233k edges/s.** That is ingest-only. End-to-end throughput is bounded by candidate generation at ~50–75 s/cycle. Report the end-to-end figure or none. |
| **Model serving** | SageMaker endpoints, versioned models | Out of scope and unnecessary. |
| **Feature store** | offline/online parity, point-in-time correctness | **Already have the valuable 10%.** `Case` snapshots features at alert time and `reranker.fit` reads them rather than recomputing — that is train/serve consistency and point-in-time correctness, which is the entire reason feature stores exist. Name it as such in the README; do not build the infrastructure. |
| **GPU graph analytics (RAPIDS cuGraph)** | GPU PageRank/Louvain/BFS at billion-edge scale ([docs](https://docs.rapids.ai/api/cugraph/stable/)) | **Not worth doing. Skip it.** The hot path operates on **7.7-node subgraphs** [measured today] — kernel-launch overhead alone would dominate. cuGraph's plausible use is a *global* pre-pass over the ~500k-pair window, but community detection on this window was already measured and rejected on quality grounds (Leiden: 6 s, 98% of covered rings inside 4,000+ node communities). The exact CPU changes in §5 give ~2.5× for a fraction of the effort. |
| **~3,000 signals/transaction** | massive feature breadth | **Do not chase feature count.** The oracle says the existing ~50 features hold ~2.8× more signal than the blend extracts. Adding 2,950 features to a system not using the 50 it has is cargo cult. |

### 3.3 Plainly out of reach

Cross-merchant network effects (requires Razorpay's book), 4 billion payments,
transformer pretraining at that scale, production serving infrastructure, and
any claim about fraud actually stopped in production. **This project will not
reach Vulcan and no part of this plan should be read as claiming otherwise.**

What remains genuinely distinct — worth keeping in the pitch — is the *unit of
output*. Vulcan scores transactions and flags entities. Nothing public suggests
it hands an analyst "here are the 9 accounts that form this structure, here is
the shape, here is the filing-shaped narrative with every sentence cited." Nor
point-in-time labelling, a verdict taxonomy, or a control arm.

---

## 4. HDFC Bank's architecture

### 4.1 What is verifiable

The single technically specific public source is a **QuestDB engineering case
study naming and quoting HDFC Bank**
([questdb.com](https://questdb.com/blog/hdfc-bank-uses-questdb-for-mule-account-detection/)):

- **Kafka** ingest → **Apache Flink** stream processing (global filtering,
  enrichment, aggregation, decisioning) → **QuestDB** as the core data layer,
  alongside **Redis, PostgreSQL, a GraphDB and Aerospike**
- **5,000–7,000 transactions/second** on a single instance
- **96-core machine, 700 GiB RAM**
- **sub-second** analytical query latency
- **up to 300 rules per transaction** on the card channel alone
- **25+ banking channels** unified on one platform for the first time (UPI,
  credit cards, online banking)
- **6× volume growth** since deployment launch
- QuestDB serves a dual role: real-time rule evaluation against historical
  account patterns arriving via Kafka/Flink, and precomputed historical
  aggregates available to the rules engine and ML models
- quoted: Rana Sinha Ray, Head Enterprise Competencies, HDFC Bank

**Read it for what it is: vendor collateral.** It is technically specific and
quotes a named executive, which is why it is usable — but QuestDB published it
and the numbers are not independently audited.

### 4.2 What is reported but not confirmed **[unverified]**

News coverage from July 2026 describes an in-house generative-AI platform
**"Neev"** plus an in-house real-time fraud engine, built by ~150–200 engineers
at HDFC's Gurgaon technology centre over ~18 months, with tightened KYC linked
to I4C and Ministry of Home Affairs databases
([Whalesbook](https://www.whalesbook.com/news/English/technology/HDFC-Bank-Deploys-Proprietary-AI-Platform-Neev-and-Fraud-Tools/6a46bad8003e8c7640ef4417),
[Telugu Times](https://www.telugutimes.net/en/bnews/hdfc-bank-develops-in-house-generative-ai-platform-neev-and-real-time-fraud-monitoring-351749.html)).
I could not find an HDFC primary press release or investor communication for
these details, and the outlets carrying them are aggregators of varying
editorial quality. **Treat as unconfirmed.**

**Stated plainly: HDFC Bank has not published an architecture paper.** Indian
banks publish materially less engineering detail than US/EU ones. Inventing
detail here would be exactly the failure mode this repo keeps a bug catalogue
for, so this section stops where the sources do.

### 4.3 What *is* verifiable about the Indian regulatory stack

- **MuleHunter.AI** (Reserve Bank Innovation Hub), announced Dec 2024. An RTI
  response reported in Dec 2025 shows **23 banks** have implemented it
  ([MediaNama](https://www.medianama.com/2025/12/223-rti-23-banks-mulehunter-mule-accounts/)).
  Rollout coverage: [Business Standard](https://www.business-standard.com/industry/banking/15-more-banks-to-adopt-rbi-s-mulehunter-fraud-detection-tool-by-october-125080101845_1.html),
  [FinTech Futures](https://www.fintechfutures.com/ai-in-fintech/reserve-bank-of-india-pilots-new-mulehunter-ai-solution-to-help-identify-mule-accounts).
  **Important qualifier:** the RBI declined under the RTI Act to disclose how
  many mule accounts have actually been identified or acted on, citing fiduciary
  grounds. So the frequently repeated "~20,000 mule accounts flagged monthly" is
  a *capability* claim, **not an independently verified outcome**, and the README
  should stop presenting it as the latter. The 19 behavioural patterns remain
  unpublished.
- **DPIP** (Digital Payments Intelligence Platform): RBIH prototype with 5–10
  banks; phase 1 is a **negative registry** integrating telecom-operator and I4C
  data; a Section 8 company (IDPIC) was approved in Dec 2025 with SBI and other
  PSBs; the Finance Ministry has publicly pressed the RBI over rollout delays
  ([Business Standard, Jun 2025](https://www.business-standard.com/industry/banking/rbi-banks-to-launch-dpip-platform-to-combat-rising-digital-payment-frauds-125062200370_1.html);
  [Business Standard, Sep 2025](https://www.business-standard.com/finance/news/fin-min-pushes-rbi-to-expedite-launch-of-platform-to-curb-digital-frauds-125093000979_1.html)).
- **RBI (Regulation of Payment Aggregators) Directions, 2025** — already verified
  against primary text in `sentinel/compliance/fiu_ind.py` (RBI/DPSS/2025-26/141,
  15 Sep 2025, Ch. IV para 13(i)/(a)/(j)). Continuous monitoring of merchant
  transactions against the business profile is an explicit, *ongoing* obligation,
  not an onboarding one
  ([overview](https://indiacorplaw.in/2025/10/09/decoding-rbis-overhaul-of-the-payment-aggregator-directions/)).
- **Still unverified in this repo, and it is a compliance-facing number:** the
  seven-working-day STR filing clock in `str_narrative.FILING_CLOCK_NOTE` derives
  from the PML (Maintenance of Records) Rules 2005, whose primary text has never
  been pulled. `fiu_ind.py` flags this honestly. **Plan item: read Rule 8
  directly and either confirm or correct.** Cheap, and it closes a known unknown
  sitting inside a filing artifact.

### 4.4 What transfers to this project

1. **Cross-channel unification is the win, not the model.** 25+ channels on one
   platform is what makes patterns visible that were invisible per channel.
   Sentinel's analogue — the *ring* spanning banks and countries as the unit of
   analysis — is the same idea at a different layer, and is already right.
2. **Precomputed historical aggregates served alongside streaming decisioning.**
   `WindowedGraph.account_stats` (Welford moments, deliberately never expired
   with the window) is exactly this pattern. Name the correspondence in the
   README; it is a stronger architectural claim than anything currently there.
3. **Rules are the substrate; ML sits on top.** 300 rules per transaction at
   5–7k TPS in 2026 is worth internalising against the temptation to replace the
   transparent blend with an opaque model. It also explains the industry's 95–99%
   false-positive rate — rules scale, precision does not.
4. **What NOT to copy:** the five-datastore layer. QuestDB + Redis + Postgres +
   GraphDB + Aerospike is an operational answer to an operational problem this
   project does not have.

---

## 5. Efficiency — profile-informed

### 5.1 Measurement method **[measured today]**

`cProfile` around `CandidateGenerator.generate` for three cycles (ticks 36, 42,
48) on the real compiled stream, plus a targeted micro-benchmark over 2,996 real
pruned candidate node-sets from tick 36. Absolute times below are inflated by
profiler overhead (~2–3×); **read the shares, not the seconds.** The
micro-benchmark numbers are unprofiled and directly comparable to each other.

Cycle-level facts:

- 15,854 seeds → 15,496 candidates at tick 36; 24,533 at tick 48 as the window
  fills. Cost grows with window occupancy.
- `add_batch` cumulative: **10.6 s across 49 ticks.** Ingest is *not* the
  bottleneck. Any plan to vectorise `add_batch` is wasted effort.
- **`deduped: 9` out of 57,288 candidates.** Exact-key dedup does essentially
  nothing post-prune. `suppressed: 1,651` (2.9%). **This kills the obvious
  idea** — "adjacent seeds are redundant, expand once per group" — the candidates
  are genuinely distinct. Doing fewer of them is a *quality* decision, not a free
  speedup. Recorded because it was my own first hypothesis and the profile
  refuted it.
- Mean pruned candidate size: **7.7 nodes**. Mean *full-graph* degree of a
  candidate member: **478**, max **13,012**.

Share of `generate` (cumulative time):

| stage | share |
|---|---:|
| `features.build` | **57.7%** (50.4% self) |
| `merge.suppress` | 15.4% (21.5M `jaccard` calls) |
| `prune` | 11.4% (mostly `subgraph_edges`) |
| `motifs.detect` | 8.2% |
| `expand_traced` | 1.3% |

`subgraph_edges` is called **171,479 times for 57,233 candidates — three times
each** (prune's `_induced_adjacency`, `generate`, and `features.build`).

Inside `features.build` (per candidate, unprofiled):

| block | ms/cand | share of build |
|---|---:|---:|
| **boundary-flow loop** | **2.820** | **76%** |
| everything else in build | 0.815 | 22% |
| registry block | 0.015 | 0.4% |
| account-stats block | 0.031 | 0.8% |
| (`subgraph_edges`, for reference) | 0.294 | — |
| (`motifs.detect`, for reference) | 0.174 | — |

**One nested loop is ~44% of total cycle time.** `features.build` lines 160–166
walk *every member's entire window adjacency* to sum external inflow/outflow.
With 7.7 members at mean degree 478, that is ~3,700 dict lookups per candidate to
compute two scalars.

Two of my code-reading priors were wrong and are corrected here: networkx cycle
enumeration is only 8% (not the bottleneck), and seed redundancy is negligible
(not a 3–10× win).

### 5.2 Ranked by speedup per unit of effort

| # | change | expected speedup | effort | exactness |
|---|---|---|---|---|
| **1** | **Maintain per-node total in/out amount incrementally** in `add_batch`/`_expire` (O(1) per edge), then compute boundary flow as `Σ_members total_in(n) − Σ_internal_edges amount`. | **~1.5× overall** (removes ~44% of cycle) | **S** | **Exact.** inflow = Σ_{n∈C} Σ_{s∉C} amt(s→n) = Σ_{n∈C} total_in(n) − Σ internal. Internal edges are already enumerated. Self-loops were dropped at compile time, so no edge case. |
| **2** | **Compute `subgraph_edges` once per candidate** and thread it through prune, motifs and features. | ~1.2× overall | **S** | Exact; pure plumbing. |
| **3** | **Size-bound pre-rejection in `merge.suppress`.** Jaccard ≥ t implies min(\|A\|,\|B\|)/max(\|A\|,\|B\|) ≥ t. Compare sizes before intersecting. Also cap or bucket `by_node` lists for very high-degree nodes. | ~1.1–1.15× overall (2–4× on suppress) | **S** | Exact — the size bound is a necessary condition, so no true match is lost. |
| **4** | **Hub-membership guard**: exclude nodes above a degree threshold from candidate *membership*, not just from traversal. | ~1.05×, and possibly a **quality** gain | **S** | **NOT exact — a detector change; must go through §1.5's full paired evaluation.** Motivation is quality: a degree-13,012 node inside a 7.7-node candidate is a correspondent/exchange account, i.e. a passenger, and dropping it raises Jaccard legitimately the way `leaf2` did. |
| **5** | **Run both prune strategies from one expansion** in `eval_prune_impact.py`. | 2× **on the A/B specifically** | **S** | Exact. Directly attacks the 40-minute paired run. |
| 6 | Drop networkx from the motif path for hand-rolled dict adjacency. | ~1.05× | M | Exact. **Only 8% of the budget — do this last if at all.** |
| 7 | Two-stage scoring: cheap pre-score on all, exact motifs on top-N. | 1.3–1.5× | M | **Not exact.** Gate on measuring "recall of the expensive stage's top-50 by the cheap stage's top-N ≥ 0.99" before adopting. Risk of cascade bias. |
| 8 | Parallelism across seeds. | up to n_cores | M–L | `sys._is_gil_enabled()` returns **True** on this interpreter [measured today], so threads will not help; processes require pickling a ~500k-pair graph per worker on Windows (no `fork`). **Poor ratio. Deprioritise.** |
| 9 | Vectorise `add_batch`. | ~0 | M | **Do not do.** Ingest is 10.6 s total. |
| 10 | cuGraph / GPU. | ~0 | L | **Do not do.** See §3.2. |

**Do 1 → 2 → 3 → 5 first.** All four are exact — they cannot change a single
metric — and together they should take the cycle to roughly **40% of current
time (~2.5×)**, turning the 40-minute paired A/B into ~8 minutes with change 5
included. Iteration speed is the precondition for every experiment in §1, so this
tier is genuinely blocking, not housekeeping.

Then evaluate **4** as a detector change on quality grounds.

---

## 6. Reliability

The characteristic failure of this codebase is **a plausible wrong answer rather
than an error** — 16 found. Three of those (§5, §5b, §5c) were *diagnoses* that
were themselves wrong and survived multiple sessions.

**The first gap is that there is no CI at all.** No `.github/`, no `pytest.ini`,
no `pyproject.toml` [verified today]. 363 tests run when someone remembers.

### 6.1 Invariants — assertions in production code, not only in tests

Several of these are currently docstring *promises*:

- `prune(nodes) ⊆ nodes` and `seed ∈ prune(nodes)` — promised in `prune.py`'s
  docstring, never asserted.
- **Pruning can only lower or hold containment, never raise it** — stated as a
  fact in `prune.py`'s docstring and used to justify the BIPARTITE/STACK rescue
  argument in HANDOFF §5e. Make it a test.
- Window conservation: `Σ agg.count == n_added − n_expired`.
- Weight sum = 1.0 (exists — keep).
- `account_key` injective on (bank, account) — bug #4's shape.
- `parse_row` never truncates silently — bug #3's shape: assert field-count
  equality or raise.
- Post-prune candidate size ≥ `MIN_NODES`.

### 6.2 Metamorphic tests — the highest-value addition

Metamorphic testing checks relations between *outputs of related inputs*, so it
needs no oracle — which is precisely this project's situation
([Chen et al., *Metamorphic Testing: A Review*, ACM CSUR 2018](https://dl.acm.org/doi/10.1145/3143561)).

| relation | input transform | required output relation | catches |
|---|---|---|---|
| **relabelling** | permute all node ids | every candidate set, score and p@k identical up to the permutation | hash/set-iteration order dependence — a live risk given `set`s throughout expansion and the degree-sorted truncation tie-break in `expand_traced` |
| **time translation** | shift all timestamps by +Δ | outputs identical | epoch/window arithmetic (bug #7's family) |
| **amount scaling** | multiply all amounts by c>0 | `conservation`, `churn`, all ratios invariant; `total_amount` scales by c | units/rounding (bug #6's family) |
| **edge duplication** | add a duplicate txn on an existing pair | all *structural* features unchanged; only counts/amounts move | multigraph/simple-graph confusion |
| **ring injection** | plant a synthetic ring of each of the 8 typologies in clean background | it is built | **bug #13's family — a typology structurally excluded. This is the class that was missed three separate times.** |
| **prune monotonicity** | apply any strategy | containment non-increasing, node set a subset | the §6.1 promise |

### 6.3 Property-based testing

[Hypothesis](https://hypothesis.readthedocs.io/) over the pure functions:
`is_hit`, `jaccard`, `prune`, `canonical_key`, `amount_key`, `account_key`,
`parse_row`, `_norm`, `is_temporally_valid`. Properties: `jaccard` symmetric and
in [0,1]; `is_hit(A,R) ⟹ |A∩R| ≥ 0.5|R|`; `canonical_key` invariant to input
order; `_norm` monotone and bounded; `is_temporally_valid` invariant to cyclic
rotation of the cycle.

### 6.4 Golden fixtures at real scale

Current fixtures are one small `elliptic2_sample`. Add a **frozen 3-cycle slice
of the real stream** (deterministically derived, a few MB) with a checked-in JSON
of the exact candidate keys, scores and stage counts. Any change that moves them
must move them *deliberately*, in a reviewed diff. **This is what would have
caught the FAN-IN 23→21 regression before it shipped.**

### 6.5 What should fail the build

1. Any test failure.
2. **Baseline re-tie gate.** On the frozen fixture, the paired `score − size`
   point estimate at k=10 and k=20 must be > 0. Not the CI — a 3-cycle fixture
   cannot support one — the *point estimate*, as a smoke gate. The CI version
   runs on demand over 34 cycles.
3. **Metric regression gate.** p@10, p@20 and ring recall on the fixture must not
   fall more than a **stated, explicit** tolerance against a checked-in baseline
   JSON.
4. **Determinism gate.** Run the fixture pipeline twice in-process and twice in
   fresh processes with different `PYTHONHASHSEED`; assert byte-identical output.
   **I expect this one to fire.**
5. **Excluded-feature gate** — `channel` may never appear in a feature vector
   (test exists; gate it).
6. **Import-boundary gate** — `sentinel.detect` / `sentinel.eval` may not
   transitively import `sentinel.llm` (test exists; gate it).
7. **Unsourced-cost gate** — CI fails if a value `economics.unsourced()` flags
   reaches a reported headline path.

### 6.6 The claims ledger — the structural fix

The recurring failure is not in the code; it is in the **prose about the code**.
HANDOFF has been wrong and corrected four times on one question. Proposal: every
numeric claim in `README.md` and `docs/` carries a machine-checkable provenance
tag naming the artifact that produced it
(`<!-- src: data/prune_impact.json#paired.k20.lo -->`), and CI fails if the
quoted number is not present at that path. That directly attacks this project's
actual failure mode. **I rank this above half the test work above**, because a
correct system described by a wrong document is what this project keeps shipping.

---

## 7. The investigation layer

### 7.1 The verifier's real limitation

`sentinel/narrative/citation.py` checks that a fact-shaped sentence carries a
citation and that the cited id **exists** in the case file. It does **not** check
that the citation **supports the claim**. `"Account X moved USD 4,000,000
[TXN-00001234]"` passes as long as `TXN-00001234` is any transaction in the case
file — regardless of its amount, its direction, or whether X is party to it.

**The strongest single upgrade in this section:** make the LLM emit a
machine-readable **claim tuple** `(subject, predicate, value, citation)` alongside
each sentence, and verify the tuple against the case data — amount matches the
cited transaction, direction matches, party matches, timestamp inside the window.
Then render prose *from verified tuples*. That converts the verifier from a
syntax check into a semantic one, and it is the difference between "the model
cited something" and "the model said something true."

Second limitation: `FACT_SIGNAL` is a keyword regex, so a fabricated sentence
with no digits and no keyword — *"The controller directed the movement."* —
passes uncited. Either widen the signal, or **invert the default**: every
sentence must cite unless explicitly tagged connective.

Third: `DraftLedger.rejection_rate` measures the **model's** error rate, not the
**verifier's** detection rate. Those are different quantities and only the second
is a property of this system.

### 7.2 How to actually measure narrative quality

1. **Adversarial verifier suite — the number that matters.** Hand-write drafts
   containing each known-bad class: invented txn id; valid id / wrong amount;
   valid amount / wrong account; invented statute outside the closed regulatory
   set; a fabricated claim phrased without digits or keywords; a true claim with
   no citation. Report **verifier recall on injected errors** and
   **false-rejection rate on known-good drafts**, both with CIs. This is the
   guardrail's own performance and it does not exist today.
2. **Completeness against a rubric.** FinCEN's five-W + how structure is already
   the template's skeleton. Machine-check each of the six elements for presence
   *and* citation. Report % of narratives complete on all six.
3. **Groundedness ceiling.** Fraction of sentences whose claim tuple is
   verifiable against case data. Target 100%; report the actual.
4. **Case-file evidence precision/recall — cheap, high value, and nobody has
   measured it.** For each confirmed ring, what fraction of the ring's true
   members appear in the case file (recall), and what fraction of case-file
   members are not in the ring (precision)? Directly measurable against AMLworld
   ground truth, and it is what the product claim ("delivered pre-investigated")
   actually rests on. **Do this one first in this section.**
5. **Human eval, honestly powered.** A blind pairwise study (template vs LLM
   draft, n≈30, 2–3 raters) is *underpowered* and must be reported as
   directional. A better proxy for the same claim: **time-to-disposition with and
   without an assembled narrative**, which is the product's actual thesis. Even
   n=20 with an interval beats a confident score.
6. **Do not use an LLM judge as the headline metric.** It correlates with
   fluency, and this project's characteristic failure is fluent wrongness. If
   used at all, use it as a screen and report its agreement rate with human
   raters.

---

## 8. Sequenced roadmap, with pre-registered expectations

### Tier 0 — unblocks everything (do this week)

| # | item | expected effect — pre-registered |
|---|---|---|
| **0.1** | **Re-run the oracle post-prune.** | The whole centrepiece rests on a number measured on a candidate pool that no longer exists. **I expect oracle p@10 to fall somewhat (smaller, tighter pool) but the oracle/blend ratio to stay ≥ 2×. If the ratio collapses below ~1.5×, §1 is wrong and should be re-scoped toward features before a week is spent on the ranker.** |
| **0.2** | Evaluate the v1 blend restricted to the oracle's held-out cycles. | Small change to 0.097; makes the "2.8×" apples-to-apples. Also delete the stale `interpretation` field in `eval_oracle.json`. |
| **0.3** | Efficiency items **1, 2, 3, 5** (§5.2 — all exact). | **Cycle time to ~40% of current; every metric byte-identical.** Assert identical candidate sets on a fixture — if any metric moves, one of the four is not exact and must be reverted. |
| **0.4** | Stand up CI: GitHub Actions, 363 tests + the determinism gate (§6.5.4). | **I expect the determinism gate to fire.** |
| **0.5** | **More independent evaluation cycles.** Add `LI-Small` / `HI-Medium` from the same generator, or Elliptic2 once downloaded. **Do not** shorten `every_ticks` (HANDOFF §11d is right — near-duplicate cycles narrow intervals spuriously). | **This is the real bottleneck on learning anything.** With 34 overlapping 72 h cycles on a 10-day stream the effective sample is far below 34, and every Tier-1 experiment will return an inconclusive CI without it. Intervals should narrow ~√(n_new/n_old). |

**0.5 is arguably the highest-value item in the entire plan.** The scorer is the
bottleneck on *performance*; sample size is the bottleneck on *knowing anything*.
They are different bottlenecks and the second gates the first.

### Tier 1 — the scorer

| # | item | expected effect — pre-registered |
|---|---|---|
| **1.1** | Add the free features: `absorbed`, expansion-trace flags, seed degree. | p@10 **+0.00 to +0.02**. Low confidence, near-zero cost. `absorbed` is orthogonal to both size and structure. |
| **1.2** | **Intensive-only feature ablation of the oracle** (§1.4(i)). | **The most important diagnostic here.** If the intensive-only oracle stays ≥2× the blend, the ranker plan is sound. **If it collapses toward the size baseline, the features carry little size-independent signal and §1 must be re-scoped to §2.3-style new features.** |
| **1.3** | **LambdaMART** (`LGBMRanker`, group = cycle) replacing the pointwise classifier; evaluated against size/degree/random/v1/**best-single-feature** in the paired frame. | **Point estimate +0.02 to +0.05 at p@20 over v1. I expect the CI at n=17 cycles to still include zero.** Recording that in advance: if it improves and I then claim it works on a CI that includes zero, that is rationalisation, and this line is the check on it. Conclusive only after 0.5. |
| **1.4** | Size-stratified reporting + within-cycle rank normalisation. | **No change to p@k**; changes what can honestly be claimed. Expect the stratified size baseline to be *harder* to beat than the global one. |
| **1.5** | Isotonic calibration + reliability diagram + ECE with CI. | ECE interval probably uninformative at this sample size. Report it anyway; use rank-based operating points if so. |
| **1.6** | Weak supervision / label model (§1.2 Option B). | **Between v1 and the oracle, closer to v1.** One day, gated on beating v1's point estimate. Kill it otherwise. Do not start before 1.2. |

### Tier 2 — measurement gaps

| # | item | expected effect |
|---|---|---|
| **2.1** | Python 3.11 venv + snapml; **reproduce the paper's own number first**, then the GFP-vs-sentinel feature-block comparison at candidate granularity (§2.3(b)). | Roughly comparable ring-level p@k. The interesting outcome would be a gap, which should localise to the timestamp moments. |
| **2.2** | Close the three real GFP gaps: timestamp moments, windowed scatter-gather (6 h), full vertex-stat propagation. | Small p@k gain; larger effect on the oracle ceiling. Replaces "essentially at parity" with a measured statement. |
| **2.3** | Hub-membership guard (§5.2 item 4), full paired evaluation. | **Ring recall +2 to +5 points, similar in shape to `leaf2`.** Must be checked against the size baseline — it changes the size distribution, so a re-tie check is mandatory. |
| **2.4** | Declare and measure a detection-latency SLO (§3.2). | New number; nothing measures it today. |
| **2.5** | Verify PML (Maintenance of Records) Rules 2005, Rule 8, primary text. | Closes a live known-unknown inside a compliance artifact. |

### Tier 3 — reliability and investigation

3.1 Metamorphic suite (§6.2) · 3.2 Golden fixture + re-tie + regression gates
(§6.4–6.5) · 3.3 Claim-tuple verification + adversarial verifier suite (§7) ·
3.4 Case-file evidence precision/recall (§7.2.4) · 3.5 Claims ledger (§6.6) ·
3.6 Ground the six placeholder cost inputs, or delete the absolute rupee figures.

### Tier 4 — explicitly do not do

cuGraph / GPU anything · Kafka/Flink/multi-datastore · a GNN · chasing 3,000
features · lowering the Jaccard floor · the union-of-seed-triggers widening as
scoped in HANDOFF §5 (already ruled out by §5b) · reimplementing GFP as a
"control" · vectorising `add_batch` · seed-group deduplication (refuted by the
profile: `deduped: 9`).

---

## 9. Risks — what is most likely to disappoint

1. **The scorer rewrite is the most likely disappointment, and it is the
   centrepiece.** Its entire justification is the oracle, and the oracle (a) was
   measured pre-prune, (b) had access to `n_nodes` and `n_edges`, (c) trains on
   *true labels* that the deployed system will never have. It is entirely
   possible that most of the 2.8× gap is size exploitation plus label access, and
   that a no-label listwise ranker recovers little of it. Items 0.1 and 1.2 exist
   to find that out in the first week rather than the fourth.

2. **The confidence intervals may never close.** 34 cycles from a 72 h window
   stepped 6 h apart on a 10-day stream are heavily overlapping; the effective
   independent sample is much smaller. A genuine +0.03 at p@20 may remain
   inconclusive no matter how good the change is. The honest fallback is what
   this project already does well: report the point estimate with its interval
   and refuse to headline it.

3. **The size baseline may simply be right.** The plan has to hold this open:
   after pruning, node count may genuinely be the best available signal at this
   granularity, and "rank by size, then invest everything in the case file" may
   be the better *product*. If the evidence lands there, say it. That would not
   be a failure — the stated thesis is that investigation throughput, not
   detection, is the bottleneck.

4. **Metamorphic tests will invalidate current numbers.** Budget for it. I
   specifically expect the relabelling and determinism tests to fire, because
   `expand_traced` truncates by `sorted(nxt, key=degree)` with arbitrary
   tie-breaking over a `set`.

5. **The "exact" efficiency changes must be proven exact, not assumed.** Every
   bug in this project's catalogue is a plausible speedup or simplification that
   altered an answer. Item 0.3 is gated on exact candidate-set equality against a
   fixture — not on "p@k looks the same".

6. **The GFP control may not reproduce.** snapml 1.15.6 on 3.11 against a 2024
   paper's configuration is a version-drift risk. If the paper's own number
   cannot be reproduced, the control is uninformative and must be reported as
   such rather than partially quoted.

### 12. Measured this session — and what it does and does not move

Written after the runs, against the pre-registrations above rather than
instead of them.

#### 12.1 LambdaMART (item 1.3): does not beat what it would replace

`scripts/eval_ranker.py`, 18 held-out cycles, 164 positive candidates, paired
bootstrap over cycles. Candidate-level p@k:

| ranking | p@10 | p@20 | p@50 |
|---|---:|---:|---:|
| pointwise (LGBMClassifier, all features) | **0.2778** | 0.1500 | 0.0689 |
| lambdamart (LGBMRanker, group = cycle) | 0.2611 | **0.1611** | **0.0811** |
| pointwise_intensive (size-blind) | 0.1556 | 0.0944 | 0.0456 |
| lambdamart_intensive (size-blind) | 0.1500 | 0.0861 | 0.0478 |
| blend (shipped v1) | 0.0500 | 0.0389 | 0.0244 |
| size | 0.0333 | 0.0389 | 0.0233 |
| best single feature (`scatter_gather_width`) | 0.0667 | 0.0417 | 0.0211 |

The comparison that decides item 1.3 — listwise against the **pointwise model
it is proposed to replace**, not against the baselines it easily beats:

| k | lambdamart − pointwise | 95% CI | verdict |
|---:|---:|---|---|
| 10 | −0.0167 | [−0.0611, +0.0222] | includes zero |
| 20 | +0.0111 | [−0.0139, +0.0361] | includes zero |
| 50 | +0.0122 | [+0.0022, +0.0244] | REAL |

**LambdaMART buys a real gain only at k=50, where the alert budget matters
least.** Item 1.3 does not deliver. Two defects had to be fixed before this
could be measured at all, both recorded in commit `1af9516`: LightGBM's
lambdarank refuses query groups above 10,000 rows (cycles here reach 24,533),
and `ring_time_split` hands the listwise objective 18 all-positive remnant
groups that generate zero gradient, so LambdaMART trains on 164 of 321
positives while the pointwise model sees all 321 — a confound in the pointwise
model's favour that is now printed on every run.

**Contradicts the pre-registration in item 1.3, in both directions.** It
predicted "+0.02 to +0.05 at p@20 over v1, CI expected to include zero at
n=17". Against v1 the delta is +0.1222 [+0.0694, +0.1778] — larger than
predicted *and* excluding zero. The prediction was made in the Phase 4
re-ranker's frame; this pool has more positives and gradient-boosted models on
the full feature block are simply far stronger than the hand-set blend. It does
not rescue LambdaMART, because beating v1 was never the question.

#### 12.2 The headroom is real, and the constraint is NOT sample size

The framing this work started from was: *the oracle reaches p@10 0.2667 where
the blend reaches 0.0500, LambdaMART is step one, and if its CI includes zero
at n=17 then the constraint is sample size.* **The measurement says otherwise.**
The CI against the shipped blend does not include zero — it excludes it
decisively at every k. A plain supervised pointwise model already extracts the
headroom: 0.2778 vs 0.0500, and `pointwise − blend` is +0.2278 [+0.1167,
+0.3500] at k=10.

So the gap is not waiting on more held-out cycles and not waiting on a better
ranking objective. **It is the hand-set blend that is leaving 5× on the table,
and a supervised model on the same features closes it.** That is a more
actionable finding than "we need a bigger sample", and it reverses the
diagnosis this phase was scoped around.

The result also survives the analyst's own denominator. Candidate-level p@k
pays twice when the generator emits several surviving candidates for one ring;
counting each ring at most once per cut gives pointwise 0.2500 / 0.1306 /
0.0600 against candidate-level 0.2778 / 0.1500 / 0.0689. The duplication is
real but small, and it does not carry the result.

#### 12.3 What would actually give more held-out cycles — and the ceiling on that

Recorded because the question will be asked again. HANDOFF §11d already ruled
out shortening `every_ticks`: at a 72 h window, cycles 6 h apart overlap
heavily and 2 h apart are near-duplicates, so resampling them narrows the
interval spuriously. The remaining routes, measured:

1. **Use more of the stream.** `EVAL_END` is day 10 of a **17.7-day** stream —
   **56.6% of it**, with 7.7 days unused. Extending to the full span would add
   roughly 26 generation cycles to the current 34, so ~30 held-out instead of
   18. That narrows a CI by about √1.7 ≈ 1.3×. Real, cheap, and independent.
2. **Rolling-origin cross-validated CIs.** Several train/test cut points
   instead of one. Narrows the *nominal* interval, but every fold reuses the
   same rings, so it does not add information about unseen rings — it should be
   reported as what it is.
3. **A larger dataset.** This is the binding constraint, and it is worth being
   blunt about: **HI-Small labels 370 rings, and 363 of them are already inside
   the current eval window.** Extending to day 17.7 buys ~26 more cycles and
   **seven more rings.** More cycles of the same rings are not independent
   observations for a ring-level metric. The honest ceiling on route 1 is
   therefore much lower than the cycle count suggests, and the only route that
   adds genuinely new rings is a different dataset — the larger AMLworld
   variants, or Elliptic2.

So: route 1 is worth doing and is nearly free. Nobody should expect it to
settle a question that route 3 is the real answer to.

#### 12.4 The defended ceiling stands, and here is why 0.25 does not raise it

The estimate below (p@10 ≈ 0.13–0.16, ring recall ≈ 25–30%) is explicitly for
a **no-label system**. The 0.2778 / 0.2500 measured in §12.1 is a **true-label
oracle**: it trains on the actual ring identities, which a production system
does not have. Phase 4's re-ranker, trained on *simulated analyst verdicts*
rather than truth, reached p@10 0.124 with a CI including zero.

**The two numbers are different quantities and the higher one must not be
quoted as a forecast.** The ceiling estimate is NOT revised upward.

What the measurement does change is *where the remaining loss sits*. It is not
in the feature set — the features support 0.25 given good labels — and not in
the ranking objective. It is in **label quality**: the distance between 0.2500
(true labels) and 0.124 (simulated verdicts) is the label pipeline's tax. That
makes the label corpus the highest-value target, which is consistent with
HANDOFF §9's claim that the label pipeline is the actual product, and it is now
supported by a measurement rather than asserted.

Downward revision, stated explicitly: **nothing measured this session supports
GFP parity, and the control that would test it has not run** (§2.1 — GFP is
Linux/macOS-only and this machine cannot run it). If the control does run and
GFP's block beats sentinel's, this estimate comes down, not up.

---

### The realistic ceiling

The highest number anywhere in this project's measurements is the
perfect-seeding oracle at p@10 = 0.467 — and it assumes both true labels *and*
cheating seeds. The structural recall ceiling is 73.3%.

**My honest estimate of where a no-label system on this dataset lands after all
of the above: p@10 ≈ 0.13–0.16, p@20 ≈ 0.10–0.12, ring recall ≈ 25–30%, with a
size-baseline margin that is positive and CI-clear at k=10 and k=20 only if item
0.5 lands.**

**STILL STANDS after the §12 measurements, and §12.4 explains why.** The
true-label oracle reaching p@10 0.2500 does not raise this estimate: it is a
different quantity, measured with labels a deployed system does not have. Do
not let the oracle number migrate into this sentence.

That is roughly 2–3× industry alert-to-SAR conversion, which is a defensible
claim honestly stated. It is **not** parity with GFP's supervised numbers, not
parity with any published supervised baseline on this dataset, and **not
Vulcan-class by any definition**. Nothing in this plan should be presented as
approaching Vulcan. What the plan can credibly deliver is a system that is
*measured* — which, given that MuleHunter's outcome numbers are withheld under
RTI and Vulcan's multipliers ship without denominators, is a scarcer property
than it sounds.

---

## Sources

**Comparators**

- IBM Graph Feature Preprocessor — [arXiv:2402.08593](https://arxiv.org/html/2402.08593v2) · [ACM ICAIF'24](https://dl.acm.org/doi/10.1145/3677052.3698674) · [snapml-examples](https://github.com/IBM/snapml-examples/blob/main/examples/graph_feature_preprocessor/graph_feature_preprocessor.ipynb)
- GARG-AML — [arXiv:2506.04292](https://arxiv.org/abs/2506.04292)
- AMLworld / HI-Small — [Altman et al., NeurIPS 2023, arXiv:2306.16424](https://arxiv.org/abs/2306.16424)
- Razorpay Vulcan — [AWS/Razorpay press release, 18 Aug 2026](https://press.aboutamazon.com/aws-international/2026/8/razorpay-launches-vulcan-indias-first-ai-payments-foundation-model-fueled-by-nvidia-and-aws-re-architecting-payments-for-a-350-bn-e-comm-future-by-2030) · [Business Standard](https://www.business-standard.com/industry/news/razorpay-builds-proprietary-ai-model-vulcan-to-boost-payment-success-rates-126081801078_1.html) · [DQ India](https://www.dqindia.com/news/razorpay-vulcan-8x-fraud-detection-baseline-12398348)
- HDFC Bank fraud platform — [QuestDB case study](https://questdb.com/blog/hdfc-bank-uses-questdb-for-mule-account-detection/) (vendor collateral; named HDFC quote)
- HDFC "Neev" **[unverified]** — [Whalesbook](https://www.whalesbook.com/news/English/technology/HDFC-Bank-Deploys-Proprietary-AI-Platform-Neev-and-Fraud-Tools/6a46bad8003e8c7640ef4417) · [Telugu Times](https://www.telugutimes.net/en/bnews/hdfc-bank-develops-in-house-generative-ai-platform-neev-and-real-time-fraud-monitoring-351749.html)

**Indian regulatory context**

- MuleHunter.AI — [MediaNama RTI report, Dec 2025](https://www.medianama.com/2025/12/223-rti-23-banks-mulehunter-mule-accounts/) · [Business Standard rollout](https://www.business-standard.com/industry/banking/15-more-banks-to-adopt-rbi-s-mulehunter-fraud-detection-tool-by-october-125080101845_1.html) · [FinTech Futures](https://www.fintechfutures.com/ai-in-fintech/reserve-bank-of-india-pilots-new-mulehunter-ai-solution-to-help-identify-mule-accounts)
- DPIP — [Business Standard, Jun 2025](https://www.business-standard.com/industry/banking/rbi-banks-to-launch-dpip-platform-to-combat-rising-digital-payment-frauds-125062200370_1.html) · [Business Standard, Sep 2025](https://www.business-standard.com/finance/news/fin-min-pushes-rbi-to-expedite-launch-of-platform-to-curb-digital-frauds-125093000979_1.html)
- RBI PA Directions 2025 — primary text already transcribed in `sentinel/compliance/fiu_ind.py`; [overview](https://indiacorplaw.in/2025/10/09/decoding-rbis-overhaul-of-the-payment-aggregator-directions/)

**Method**

- Snorkel — [VLDB 2017, arXiv:1711.10160](https://arxiv.org/abs/1711.10160) · Data programming — [NeurIPS 2016, arXiv:1605.07723](https://arxiv.org/abs/1605.07723)
- LambdaMART — [Burges, MSR-TR-2010-82](https://www.microsoft.com/en-us/research/publication/from-ranknet-to-lambdarank-to-lambdamart-an-overview/) · [LGBMRanker](https://lightgbm.readthedocs.io/en/latest/pythonapi/lightgbm.LGBMRanker.html)
- PU learning — [Elkan & Noto, KDD 2008](https://dl.acm.org/doi/10.1145/1401890.1401920)
- Metamorphic testing — [Chen et al., ACM CSUR 2018](https://dl.acm.org/doi/10.1145/3143561) · [Hypothesis](https://hypothesis.readthedocs.io/)
- RAPIDS cuGraph — [docs](https://docs.rapids.ai/api/cugraph/stable/)
