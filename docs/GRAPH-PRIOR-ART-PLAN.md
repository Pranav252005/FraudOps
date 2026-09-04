# Graph prior art, and a plan aimed at the measured failure

**Written 2026-09-04.** Research and planning only — nothing here is
implemented. Two small spikes were run to verify installability and to
quantify one claim; both are marked **[SPIKE]** and neither changed the
detector.

Read §1 and §2 before the survey. §2 is a correction to a claim this
repository made **today**, and it moves the highest-value item on the list
from "import a method from the literature" to "fix a sampling gap in our own
code".

---

## 1. B3 first, as instructed

`docs/SUPPRESSION-KEY-FINDINGS.md`, committed `63c3834`. Verified here against
`data/eval_suppression_key.json` rather than its own prose.

**The property held in both directions.** The shipped score-ordered pool moves
when blend weights move (4 of 525 fixture candidates, **0.76%**); `largest`,
`smallest` and `key` are each bit-identical under the same perturbation.

**The cost is near zero for the right key**, 34 cycles, cycle-clustered paired
bootstrap:

| ordering | built | ranked@50 | p@10 | size p@10 | delta vs score @10 |
|---|---:|---:|---:|---:|---|
| `score` (shipped) | 161 | 58 | 0.2912 | 0.0882 | — |
| `largest` *(the review's pick)* | 161 | 58 | 0.2765 | 0.0941 | **−0.0147 [−0.0265, −0.0029]** |
| **`smallest`** | **162** | 58 | 0.2882 | 0.0882 | −0.0029 [−0.0088, +0.0000] |
| `key` | 161 | 58 | 0.2824 | 0.0912 | −0.0088 [−0.0206, +0.0000] |

**What this changes for everything below.** Until the default is flipped, every
scorer A/B in this repo is confounded — but the confound is **~1%**, not
order-of-magnitude. So B3 unblocks scorer work *and* simultaneously says the
thing it unblocks was never badly broken. **Flip `SUPPRESS_SCORE` →
`SUPPRESS_SMALLEST` before any of the ranking-side work in §6, and not before
the generation-side work, which does not need it.**

Note `largest` lifts the size baseline (0.0882 → 0.0941) while `smallest`
leaves it flat. That mechanism recurs throughout this document.

---

## 2. [SPIKE] The claim in the brief that does not survive contact with the code

> *"22 of 29 unseeded rings were never touched in any active cycle —
> unreachable by any touch-based rule."*

**True as written, and its implication is wrong.** They were never touched **in
the one-hour tick that seeding samples**. Every one of them is touched inside
the 72-hour window the detector is already holding.

### The mechanism, read off the code

- `sentinel/config.py`: `TICK_MINUTES = 60`, `WINDOW_MINUTES = 72*60`
- every eval loop: `if i % EVERY or ...: continue` with `EVERY = 6`
- `CandidateGenerator.seeds(batch)` builds `touched` from **`batch.src` /
  `batch.dst` only** — that is one tick, one hour

So a cycle expands into a **72-hour** graph but draws its seeds from **one
hour**. Five of every six ticks are never sampled for seeds at all.

### Quantified, over the real stream

Computed directly from `data/stream` with the evals' own `active_rings`
semantics (≥3 in-window accounts). The reproduction is exact — 259 active
rings, matching every eval in the repo.

| | edges | rings |
|---|---:|---:|
| inside some cycle's 72h window | 4,447,201 (99.1%) | **259** |
| inside some cycle's 1h **seed tick** | 679,984 (15.2%) | **237** |
| **seeding sees this share of its own window** | **15.3%** | |
| touched in the seed tick **and** pass-through | | **230** ← what the funnel reports as "seeded" |
| **reachable only by widening the seed source** | | **22** |
| unreachable even from the whole window | | **0** |

The arithmetic reconciles exactly with today's S1 run: 259 active − 237
tick-touched = **22**; 237 − 230 = **7**, which is precisely the "addressable
set" S1 measured. **29 unseeded = 22 lost to time-sampling + 7 lost to the
pass-through predicate.**

### What this means

1. **The S1/S2 ceiling was a ceiling on the sampling, not on seed predicates.**
   S1 drew extra seeds from the same one-hour `touched` set, so it could never
   have reached the 22. Its refutation stands — `node_smurf_score` is still
   bit-identical to degree-burst and the cleanliness term is still inert for
   98.6% of the pool — but "S1's ceiling is 7 rings" is a fact about the hour,
   not about seeding.
2. **The single largest verified, untested opportunity in this repository is a
   config-shaped gap, not a literature import.** That is an uncomfortable
   finding for a prior-art survey and it goes first because it is the honest
   ranking.
3. It is **not free**: widening the seed source multiplies seeds and therefore
   generation cost roughly linearly. §6 P0 treats it as a sweep, not a switch.

**This is exactly the failure mode the brief warned about** — a claim
propagating from prose (my own, this morning) rather than from code. I made it;
it is corrected here.

---

## 3. What I verified vs what I inferred

| claim | status |
|---|---|
| B3 numbers above | **verified** — read from `data/eval_suppression_key.json` |
| funnel losses seeding 11.20 / build 26.64 / ranking 39.77, `largest_loss_stage = "ranking"` | **verified** — `data/funnel.json` |
| perfect scorer ≈ 1.12× | **verified** — `data/eval_oracle.json` interpretation string gives k=10 = 1.1176, k=20 = 1.2778 |
| seed source = 1 tick of 72h; 15.3% of window edges; 22 rings recoverable | **verified [SPIKE]** — code read + computed from `data/stream`, reproduces the 259/230 the evals report |
| library installability, wheel platform + size | **verified [SPIKE]** — `pip install --dry-run --only-binary=:all:` on this interpreter (3.11.9) |
| repo licence / last push / stars / size | **verified** — GitHub REST API, 2026-09-04 |
| what each paper's *method* does | **inferred from abstracts and secondary sources.** No paper's results were reproduced. Every performance number attributed to a paper below is **their claim, not a measurement on this machine** |
| that any method below will work on AMLworld | **not verified — this is the whole risk.** No head-to-head has been run |
| test count | **verified: 916**, not the 904 in the brief (B3 added 12). All pass; five gates green |

---

## 4. The survey, ranked by expected value against the measured funnel

Ranking is against **build (26.64 pts)** and **seeding (11.20 pts)**. Ranking
loss is nominally the largest (39.77) but `data/eval_oracle.json` says a
supervised model on the same features buys 1.12× at k=10 — **so the ranking
loss is a feature-information problem, not an ordering problem**, and anything
that only reorders is ranked low here.

### Tier 1 — replace the generator's core assumption

Everything this repo has ever generated is *seed → connected expansion → prune*.
That assumption is what makes a ring disconnected-in-window unrecoverable. The
dense-subgraph family does not make it.

**1. FRAUDAR-family density objectives (take the objective, not the code).**
[KDD'16 paper](https://bhooi.github.io/papers/fraudar_kdd16.pdf) ·
[TKDD version](https://dl.acm.org/doi/pdf/10.1145/3056563) ·
[code mirror](https://github.com/JunhaoWang/fraudar)

Greedy peeling on `g(S) = e(S)/|S|` (and log/sqrt column-weighted variants),
with a **provable bound on how much fraud can hide** and camouflage
resistance. No seed, no traversal — it peels the whole graph toward a density
optimum.

*Why it is ranked first among imports:* **the objective is size-normalised by
construction.** `e(S)/|S|` does not increase when you add a node that brings
fewer than the current average edges. That is the size-baseline defence the
hard constraints demand, obtained structurally rather than by a post-hoc check.

*Concretely borrowable:* the objective and the peeling loop are ~100 lines with
a priority queue. **Reimplement rather than vendor** — the original is
research code, and D-Cube/M-Zoom below are GPL-3.0.
*Risk:* FRAUDAR is bipartite (users × objects); AMLworld is account→account. The
bipartite framing (sources × destinations) is an adaptation, not a port.

**2. Dense-block detection in tensors — M-Zoom / D-Cube.**
[M-Zoom](https://github.com/kijungs/mzoom) · [D-Cube](https://github.com/kijungs/dcube)
Both **GPL-3.0**, last pushed 2024-10-30, 27/33 stars, 4.9/9.4 MB.

A 3-mode tensor `(src, dst, time-bucket)` **natively models "one ring = several
components observed at different times"** — a dense block spans time buckets by
construction rather than by a linking heuristic. This is the closest thing in
the literature to the actual data model of the failure.

*Concretely borrowable:* the density measures (arithmetic/geometric/suspiciousness)
and the block-peeling schedule. **GPL-3.0 is a real constraint** — reimplement
the measure from the papers rather than vendoring the code.

### Tier 2 — attack the window, not the graph

**3. Evidence accumulation / co-association across multiple windows.**
[EAC, Fred & Jain](https://www.researchgate.net/publication/3974043_Data_clustering_using_evidence_accumulation) ·
[probabilistic consensus](https://link.springer.com/article/10.1007/s10994-013-5339-6)

Run the **existing** generator at several window lengths (24h / 72h / 7d), and
accumulate, per account pair, the fraction of windows in which they co-occurred
in a candidate. Cluster that co-association matrix.

*Why it fits:* it is the "several disconnected components observed at different
times" model made native, and it requires **no new detection algorithm** — only
re-running what exists and combining.
*Size defence by construction:* co-association is a **rate in [0,1]** per pair,
not a count, so candidate score is intensive.
**Honest caveat: this is the same family as B1, which was refuted today.** B1
joined things that looked related *within* a window and found zero new rings.
The distinction is that this joins *across* windows, which is where §2 shows the
ring's missing mass actually is. That is an argument, not evidence.

**4. Multilayer / multislice community detection.**
[survey](https://link.springer.com/article/10.1007/s10618-020-00716-6) ·
[temporal multilayer](https://people.maths.ox.ac.uk/howison/papers/TemporalCommunityDetection2015.pdf)

Windows as layers with interlayer coupling. Theoretically the right model;
practically heavier than #3 for the same hypothesis. **Do #3 first; #4 only if
#3 shows signal.**

### Tier 3 — features, because the oracle says features are the cap

**5. δ-temporal motifs (Paranjape et al., WSDM'17).**
[SNAP page](https://snap.stanford.edu/temporal-motifs/) ·
[paper](https://cs.stanford.edu/people/jure/pubs/motifs-wsdm17.pdf) ·
[Raphtory](https://github.com/Pometry/Raphtory)

A *census* of 2–3-node, 3-edge motifs within a time bound δ. This repo has
cycles with a temporal-validity test but **no motif census** — a feature family
it genuinely lacks, and the oracle result says features are what cap ranking.

*Availability [SPIKE-verified]:* Raphtory `0.17.0`, **cp311 win_amd64 wheel,
82.1 MB, installs on this machine**. **GPL-3.0**, 641 stars, pushed 2026-09-04
— very much alive. SNAP is `NOASSERTION` and last pushed 2023-12-10.
*Recommendation:* compute the census ourselves from the existing window
(subgraphs are ~8 nodes; this is cheap) rather than adding a GPL dependency.

**6. TemporalRI — temporal subgraph isomorphism.**
[paper](https://appliednetsci.springeropen.com/articles/10.1007/s41109-021-00397-0)
Relevant if typology templates are ever matched explicitly. **Not now** —
sentinel does not have a template-matching stage and adding one is a larger
change than anything else on this list.

### Tier 4 — infrastructure

**7. NetworKit** — [MIT], 873 stars, pushed 2026-09-02, **cp311 wheel 30.0 MB,
[SPIKE] installs**. k-core, k-truss, densest-subgraph, connected components at
C++ speed with a Python front end. The cheapest way to get Tier-1/Tier-2
primitives without hand-rolling them. **Best licence-to-capability ratio on this
list.**

**8. kuzu** — embedded property-graph DB, cp311 wheel 4.7 MB, [SPIKE] installs.
Only worth it if a Cypher-shaped query layer is wanted for the investigation
side. Not for detection.

### Explicitly not worth doing

| | why |
|---|---|
| **FlowScope code** ([repo](https://github.com/csqjxiao/FlowScope)) | **NO LICENCE FILE**, last push **2019-11-27**, 7 stars. Legally unusable and abandoned. The paper's multipartite-flow idea is partly what sentinel already computes. **Do not vendor.** |
| **spartan2** ([repo](https://github.com/stair-team/spartan2)) | BSD-3-Clause and alive (pushed 2026-04-09) but **[SPIKE] `pip install spartan2` resolves to a 2019-era 0.0.2 under `--only-binary`; the current 0.1.3.post4 is sdist-only and its build fails here — `ModuleNotFoundError: No module named 'Cython'`.** Same shape as the snapml/GFP blocker. |
| **graph-tool** | **[SPIKE] not on PyPI at all** — `ERROR: No matching distribution`. conda/system only. |
| **GNNs (PyG / DGL / GraphStorm / Multi-GNN)** | The oracle says a supervised model on current features buys 1.12×; a GNN needs labels the deployed system does not have. Already ruled out in `ARCHITECTURE_UPLIFT.md`. [Multi-GNN](https://github.com/IBM/Multi-GNN) stays useful as a *published baseline reference*, not as a component. |
| **Entity resolution (Splink / dedupe / zingg)** | [Splink](https://github.com/moj-analytical-services/splink) is MIT, 2,381 stars, pushed **today** — excellent software. **But AMLworld's entity ids are synthetic and already exact**; `features.entity_reuse` reads them directly. There is nothing to resolve. **Real value on real data, zero on this benchmark.** Say so rather than adding it for the survey's sake. |
| **Neo4j GDS / Memgraph MAGE** | A database dependency for algorithms NetworKit provides in-process. |
| **AMLGentex** ([repo](https://github.com/aidotse/AMLGentex)) | Apache-2.0, **1,079.7 MB** — would let the window-vs-fragmentation hypothesis be tested at chosen rates, which is genuinely the right instrument for §6 P1. But it is a *generator*: results on it transfer to nothing claimed about HI-Small. **Report the size before pulling; medium value, and only after P0/P1 have a result.** |

### Does anything here do what FraudOps does better?

**On detection: almost certainly yes, and it is not close.** FRAUDAR and D-Cube
carry approximation guarantees and provable bounds on hidden fraud; sentinel has
a hand-set blend that a supervised model beats by 1.12×. Nothing here should be
read as sentinel having a detection edge.

**On the investigation layer: nothing in this survey competes.** None of these
projects emits a case file with per-sentence citations, a verdict taxonomy, a
control arm, or an append-only refutation ledger. That remains the honest
differentiator, and §7 of `graph-review/2026-09-04.md` was right about it.

**No parity claim against any of these has been made or may be made until a
head-to-head runs on this machine.** X1 (GFP) is still blocked.

---

## 5. How every proposal avoids the size re-tie *by construction*

The hard constraint, and today's evidence that it bites: `largest` lifted the
size baseline 0.0882 → 0.0941; B1's linking nearly tripled it at k=50 and
reversed the margin.

**A standing diagnostic, proposed for all of the below:** report **Spearman ρ
between the arm's score and candidate node count** over the emitted pool. If
|ρ| > 0.5 the arm is treated as size-confounded **regardless of its p@k**. This
is stronger than a re-tie check because it fails before the metric does.

| proposal | structural defence |
|---|---|
| P0 seed-source widening | changes *which candidates exist*, not how they are scored; the scorer is untouched, so any re-tie would be a pure generation artifact and is directly attributable |
| P1 density objective | `e(S)/|S|` is a **ratio**; adding a below-average node lowers it |
| P2 co-association | per-pair **rate in [0,1]**; candidate score is the mean, an intensive quantity |
| P3 temporal-motif features | motif **densities** (count ÷ node count), never raw counts |

**Every measurement below specifies the re-tie check at k=10, 20 AND 50**, in a
paired cycle-clustered bootstrap, because a k=10-only check failed to catch a
reversal today.

---

## 6. The phased plan

### P0 — widen the seed source. **Do this first.**

**Objective.** Seeding currently samples 15.3% of the edges its own window
holds. Make the seed source a swept parameter: `{1 tick (shipped), EVERY ticks
(=6h, time-lossless), 24h, full window}`.

**Work items.** A `seed_lookback_ticks` parameter on `CandidateGenerator`; the
generator retains the last *N* ticks' touched sets (a deque, no graph change);
a four-arm paired eval on one replay; cycle-cost recorded per arm.

**Pre-registered expected effect.**

| | prediction |
|---|---|
| rings newly seeded | **+15 to +22** of the 22 shown reachable |
| built | **+8 to +20** |
| **ranked@50** | **+0 to +6.** Low, and stated low on purpose — S1 added 10% more seeds for **+14 built and +0 ranked**. This is the same *shape* of intervention |
| p@10 paired CI | **includes zero** |
| size-baseline margin | unchanged; the scorer is untouched |
| cycle cost | **6× at 6h lookback**, ~20× at full window |

**Kill criterion.** If ranked@50 does not rise by **≥3 rings** at *any*
lookback, P0 is a build-stage-only gain and must be reported as "+N built, +0
ranked" with the S1 precedent named — **not** as a recall improvement. And if
`score − size` loses CI-clarity at k=10, 20 or 50 in any arm, that arm is
unshippable.

**Effort.** ~1 day incl. replay. **Dependencies.** None. Does not need B3.

**Why this is ranked above everything imported:** it is verified, it is local,
its ceiling is measured rather than hoped, and no paper is needed to justify it.

### P1 — a density objective as a *second* generator, run alongside

**Objective.** Add a seedless, size-normalised candidate source: greedy peeling
on `e(S)/|S|` over the window's bipartite (sources × destinations) projection,
emitting blocks as candidates **in addition to** seed-and-expand output.

**Work items.** Reimplement the objective + peeling (~100 lines, no vendored
GPL code); emit blocks as `Candidate`s through the existing feature/score path;
three arms — shipped, shipped+density, shipped+**random blocks of matched size
distribution** (the null that B1 taught us to include).

**Pre-registered expected effect.** built **+5 to +25**; ranked@50 **+0 to
+8**; p@k CI **includes zero**; Spearman ρ(score, size) **< 0.3** by
construction.

**Kill criterion.** If `shipped+density` does not beat the matched-size random
null on built, the objective earned nothing and it is reported as a refutation
— exactly B1's criterion, which is the one that fired today.

**Effort.** ~2–3 days. **Dependencies.** P0 (so the seed baseline is settled).

### P2 — cross-window evidence accumulation

**Objective.** Test whether a ring's fragments can be assembled across windows
rather than within one.

**Effort.** ~2 days. **Dependencies.** P0, and **contingent on P1's result** —
if P1's seedless generator already recovers the fragmented rings, P2 is
redundant.

**Pre-registered expected effect.** built **+0 to +12**; ranked@50 **+0 to +4**.
**Kill criterion:** must beat a null that accumulates evidence over *shuffled*
window assignments. **Flagged risk:** same family as B1, which was refuted.

### P3 — δ-temporal motif census as features

**Objective.** Add the motif family the oracle's ceiling implies is missing.
**Deliberately last**, because it targets the ranking loss and the oracle says
a perfect ranker on current features buys 1.12× — so this is only worth doing
if it adds *information*, which is precisely what must be measured.

**Pre-registered expected effect.** p@10 **+0.00 to +0.03**, CI likely
including zero; the **oracle re-run** is the real read — if the supervised
ceiling on features+motifs does not rise above 1.12×, the motifs added nothing
and P3 is refuted regardless of p@k.

**Effort.** ~2 days. **Dependencies.** B3 flipped to `smallest` first, since
this is scorer-side work.

### Not worth doing

Vendoring FlowScope (no licence), spartan2 (build-broken here), graph-tool
(unavailable), any GNN, entity resolution on this dataset, a graph database.
**And do not widen the Jaccard floor** — not proposed anywhere above.

---

## 7. Risk, and the base rate this plan must be read against

**Today's record: five experiments, and not one moved a headline metric.**

| | outcome |
|---|---|
| L1 | closed an unguarded surface; no metric movement (by design) |
| M1 | thresholds confirmed robust; no metric movement (a measurement) |
| S1/S2 | **refuted** |
| B1 | **refuted** |
| B3 | confirmed; no metric movement (by design) |

Two refutations, three methodology confirmations, **zero p@k or recall gains.**
That is the base rate. Anyone reading §6's ranges should assume **at most one
of P0–P3 moves a headline number, and none by more than a few points.**

**What would make these different from the two that were refuted.** S1 was a new
*seed predicate* over the same sampled hour; B1 was a *post-hoc merge* of the
same candidates. Both were variations on the existing generator that left its
core assumption intact. P0 changes what the generator can see; P1 removes the
seed-and-expand assumption entirely. That is a real structural difference — but
it is an argument, and B1's prereg contained an equally good-sounding argument
before it produced zero new rings.

**Specific things most likely to disappoint:**

1. **P0 will probably repeat S1's shape**: built up, ranked flat. 103 rings are
   already built and not ranked; adding more built rings to a queue that
   surfaces 58 of them may change nothing a user sees. **This is the single most
   likely outcome of the highest-ranked item.**
2. **P1's bipartite adaptation may simply not fit.** FRAUDAR's guarantees are
   for bipartite fraud blocks; a unipartite transaction graph projected to
   sources × destinations is a different object, and the bound may not transfer.
   No one has run it here.
3. **P2 is the same family as a thing refuted this morning.** Its prior should
   be low and its kill criterion is deliberately harsh.
4. **P3 is aimed at the largest funnel loss and the oracle says that loss is not
   addressable by better ranking.** It is on the list for completeness and to
   be measured, not because I expect it to work.
5. **Every performance number attributed to a paper here is that paper's own
   claim.** Nothing was reproduced. The gap between "FRAUDAR has a provable
   bound" and "FRAUDAR helps on AMLworld HI-Small" is the entire risk and it is
   unmeasured.
6. **This survey's most valuable finding came from reading our own code, not
   from the literature.** If P0 is the biggest win available, then the honest
   lesson is that the prior-art search was worth less than an afternoon spent
   checking what `seeds()` actually receives — and that should temper how much
   is invested in Tier 1–3 before P0 reports.

**Realistic ceiling.** If P0 and P1 both land at the optimistic end,
ranked@50 goes 58 → ~70 of 259 and ring recall follows. That is a real
improvement and it is nowhere near closing the 26.64-point build loss or the
39.77-point ranking loss. Nothing in this document is a path to solving the
funnel; it is a path to measuring four more things honestly.
