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

**450 tests passing, 1 xfail.** `python -m pytest -q`

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

### Where the loss lives — the funnel

**The funnel diagnoses, the supervised re-ranker treats, and the paired
bootstrap confirms.** This is the artefact to read first: every accuracy number
below it is uninterpretable without knowing which stage lost the ring.

Ring recall decomposed into stages, distinct rings across all cycles.
Source: `data/funnel.json` / `data/funnel.csv` — 34 generation runs, `rank_k`
50, 259 labelled rings active in the 10-day evaluation window
(`scripts/eval_funnel.py`). A rendered version for presentation is
[`docs/funnel.html`](docs/funnel.html).

| stage | rings | share | loss at this stage |
|---|---:|---:|---:|
| seed-reachable | 259 | 100.0% | — |
| seeded | 230 | 88.8% | **−11.2 pts** |
| built (candidate generated) | 162 | 62.5% | **−26.3 pts** |
| ranked into top 50 | 49 | 18.9% | **−43.6 pts** |

The losses are stated in percentage points because that is the only form in
which they can be compared, and `scripts/eval_funnel.py` computes them from the
measured recalls rather than from a hand-typed table (`stage_losses_pts` in
`data/funnel.json`).

**Structural ceiling is 73.3%** — 88 of 370 rings have two or fewer accounts and
no community structure to detect.

#### Ranking is the largest single loss, at 43.6 points

More rings are lost between *built* and *ranked* (162 → 49) than at seeding and
building combined. A candidate that structurally covers the ring exists; the
scorer does not put it in the top 50.

That is exactly the loss the supervised re-ranker addresses, and it moves it:
**p@10 0.2778 [0.1500, 0.4167] against the shipped v1 hand-set blend's 0.0500,
a paired delta of +0.2278 [+0.1167, +0.3500] on a ring-disjoint held-out split
— and it is trained on ground-truth ring labels, which a deployment does not
have.** (`scripts/eval_oracle.py` run 1, `data/eval_oracle.json`; independently
reproduced by the pointwise arm of `scripts/eval_ranker.py`.) Both halves of
that sentence are the result; [The label tax](#the-label-tax--why-the-caveat-is-the-argument)
below is why the caveat is the argument rather than a hedge. 0.2778 is not a
production number and is not quoted as one anywhere in this repository.

#### The build stage's 26 points are concentrated in exactly two typologies

Per typology, from `data/funnel.csv`. The `interpretation` column is derived in
code from each row's own build retention (built ÷ seeded), not from a
hand-written per-typology lookup — the thresholds and their boundary behaviour
are documented at the top of `scripts/eval_funnel.py`.

| typology | total | seeded | built | ranked (top-50) | interpretation |
|---|---:|---:|---:|---:|---|
| BIPARTITE | 31 | 28 (90.3%) | **5 (16.1%)** | 1 (3.2%) | **build-destroyed** |
| STACK | 30 | **30 (100.0%)** | **9 (30.0%)** | 2 (6.7%) | **build-destroyed** |
| SCATTER-GATHER | 31 | 28 (90.3%) | 27 (87.1%) | 10 (32.3%) | ranking-limited |
| GATHER-SCATTER | 38 | 35 (92.1%) | 31 (81.6%) | 9 (23.7%) | ranking-limited |
| CYCLE | 37 | 31 (83.8%) | 28 (75.7%) | 7 (18.9%) | ranking-limited |
| FAN-OUT | 36 | 30 (83.3%) | 24 (66.7%) | 9 (25.0%) | ordinary attrition |
| FAN-IN | 30 | 26 (86.7%) | 21 (70.0%) | 4 (13.3%) | ordinary attrition |
| RANDOM | 26 | 22 (84.6%) | 17 (65.4%) | 7 (26.9%) | ordinary attrition |
| **TOTAL** | **259** | **230 (88.8%)** | **162 (62.5%)** | **49 (18.9%)** | aggregate |

Six of the eight typologies keep 77–96% of their seeded rings through the build
stage. BIPARTITE keeps 17.9% and STACK 30.0%. **Those two rows are the build
stage's 26 points.** The three `ranking-limited` rows lose almost nothing at
build (3–11 pts) and 55–58 points at ranking; the three `ordinary attrition`
rows lose steadily at every stage.

#### The STACK finding, stated plainly

**Nothing is wrong with *finding* these rings.** STACK is seeded 30 of 30 —
perfectly, the only typology in the table that is. Every one of those rings was
located by the seed rule and then discarded by the expansion-or-pruning step
that runs after it. BIPARTITE is the same failure at 90.3% seeded.

That is a bounded, well-localised bug hunt with a known input (30 seeded STACK
rings, 21 of which never become a candidate) and a known output, and it is **the
highest-value remaining engineering task that is not the re-ranker**. Whether it
can be closed in the time remaining is genuinely uncertain — [both obvious knobs
have already been ruled out by experiment](#what-is-already-known-about-the-build-stage-bug),
so it is not a tuning pass. **Naming it precisely is itself the deliverable**:
three previous attempts at this question each blamed a stage that was not at
fault, and those corrections are recorded in place in `docs/HANDOFF.md` §5b–§5f.

#### What is already known about the build-stage bug

`scripts/diagnose_build.py` splits the build failure into two causes with
**opposite fixes**:

- **CONTAINMENT_FAIL** — expansion never reached ≥50% of the ring. *Fix by
  expanding harder.*
- **DILUTION_FAIL** — expansion *did* reach the ring, but dragged in so much
  neighbourhood that Jaccard fell below 0.3. The structure was found and then
  buried. *Fix by expanding less and pruning.*

At the shipped expansion config (`hops=2`, `max_degree=50`,
`data/build_diagnosis_h2_d50.json`), over the same 34 cycles and the same 230
seeded rings as the funnel:

| typology | seeded | containment_fail | → hop_limit | → hub_guard | dilution_fail |
|---|---:|---:|---:|---:|---:|
| BIPARTITE | 28 | 12 | 9 | 3 | 16 |
| STACK | 30 | 14 | 13 | 1 | 14 |

Roughly half "never reached" and half "reached then buried", for both. **That is
why a single knob cannot fix it** — the two halves want opposite changes.

> **Denominator caveat, stated up front rather than buried.** The
> `build_diagnosis_*.json` files report BIPARTITE **built = 0** and STACK
> **built = 2**; `data/funnel.csv` reports **5** and **9**. Both are correct and
> they are not the same measurement. `scripts/diagnose_build.py` calls
> `WindowedGraph.expand_traced` directly on each seed and scores the raw
> neighbourhood; it never calls `CandidateGenerator.generate`, so it applies
> **no pruning** (`PRUNE_STRATEGY = "leaf2"`, `sentinel/detect/prune.py`), no
> dedup, no `MIN_EDGES` filter and no overlap suppression. `eval_funnel.py` goes
> through `generate` and therefore gets all of them. The diagnosis counts are
> **raw two-hop expansion, pre-prune**; the funnel counts are the **shipped
> pipeline, post-prune**. The seeded denominator *is* shared — 230 rings in both
> — so the whole gap is the post-expansion pipeline, and it runs in the expected
> direction: pruning is precisely the treatment for DILUTION_FAIL, and it is
> what lifts BIPARTITE 0 → 5 and STACK 2 → 9. **Quote the diagnosis for its
> proportions and causes, never for its absolute built counts.**

**Both obvious knobs were ruled out by experiment, and the experiments are
stored.** Both rows below are pre-prune counts, per the caveat:

| knob | result | source |
|---|---|---|
| hops 2 → 3 | **worse.** BIPARTITE built 0 → 0, STACK 2 → 1. Mean best Jaccard collapsed (BIPARTITE 0.140 → 0.083, STACK 0.153 → 0.075) as mean candidate size ballooned (BIPARTITE 15.2 → 36.4, STACK 19.1 → 52.8). | `data/build_diagnosis_h3.json` |
| hub-degree guard 50 → 500 | **nothing at all.** The BIPARTITE and STACK rows are identical on every count — built, containment_fail, each sub-reason, dilution_fail. (Elsewhere it moves builds by at most one ring, and downward: FAN-OUT 20 → 19, GATHER-SCATTER 23 → 22, RANDOM 10 → 9.) | `data/build_diagnosis_h2_d500.json` |

More hops is not the fix and a looser hub guard is not the fix. The remaining
`hop_limit` containment failures mean those ring members are genuinely not
reachable from a *pass-through* seed within the window — a structural property
of seed-and-expand on those two shapes, not a parameter.

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

### The supervised re-ranker, and what perfect labels are worth

**A supervised re-ranker over ground-truth ring labels, ring-disjoint held-out
split, p@10 0.278 [0.150, 0.417] — trained on ground-truth ring labels, which a
deployment does not have on day one.** Both halves of that sentence are the
result. `scripts/eval_oracle.py`, run 1 (`oracle_as_is` in
`data/eval_oracle.json`); the same LightGBM model on the same candidate
features the shipped scorer already computes, with no cheat anywhere in the
pipeline.

The split is what makes it a result rather than a demo, and it is worth being
exact about what it guarantees, because the two guarantees are not equally
strong.

**Ring-disjointness is the strong one, and it is asserted.** A ring's
candidates are wholly in train or wholly in test, never split across the
boundary; `ring_time_split` in `scripts/eval_oracle.py` asserts it and the run
dies if it is violated.

**Time-ordering is the weaker one, and the weakness is deliberate.** The
negative pool is a pure temporal split, and that half *is* asserted: no
training negative post-dates any test negative. Positives are not. A positive
candidate follows its ring, so a ring assigned to train keeps every one of its
candidates — including the ones that fall after the cutoff. That is a trade
taken on purpose, and the function says so in its own comment: two
near-duplicate candidates for the same ring landing on opposite sides of the
boundary is the worse leak of the two, so ring identity wins and a little
temporal overlap on an already-positive ring is accepted. "Train strictly
precedes test" is therefore true of the negative pool and **not** true of the
positives. This README used to state it flat out; that was an overclaim and it
is corrected here rather than quietly dropped.

Pool 346,523 candidates; train 169,947 (321 positive); test 176,576 (164
positive); 18 held-out cycles; `leaf2` pruning.

Every ranking scored on the **same** 18 held-out cycles:

| ranking | p@10 | 95% CI | p@20 | p@50 |
|---|---:|---|---:|---:|
| **supervised (TRUE LABELS — not deployable; see [the label tax](#the-label-tax--why-the-caveat-is-the-argument))** | **0.2778** | [0.1500, 0.4167] | 0.1500 | 0.0689 |
| v1 hand-set blend (shipped) | 0.0500 | [0.0222, 0.0778] | 0.0389 | 0.0244 |
| size | 0.0333 | [0.0111, 0.0556] | 0.0389 | 0.0233 |
| degree | 0.0167 | [0.0000, 0.0389] | 0.0278 | 0.0211 |
| random | 0.0000 | [0.0000, 0.0000] | 0.0000 | 0.0000 |

Average precision 0.2285. The size baseline is quoted beside the headline
because [the standing rule](#standing-rule) requires it, and here it is finally
not flattering to the baseline: at p@10 the supervised model clears size by an
interval that never touches zero.

**The denominator inflates that 0.2778, and by roughly a tenth.** p@k here is
counted over *candidates*, so a cycle in which the generator emits three
surviving candidates covering one true ring pays three times for one detection.
That is not a hypothetical: `scripts/eval_ranker.py` measures both denominators
on this same split, and for its pointwise fit the same model scores **0.2778
candidate-level against 0.2500 distinct-ring** at k=10
(`data/eval_ranker.json`, `precision_at["10"]["pointwise"]` versus
`distinct_ring_precision_at["10"]["pointwise"]`). `scripts/eval_oracle.py`
computes only the candidate-level figure, so **its 0.2778 — the identical
number, not merely a comparable one — carries the identical inflation, and
there is no distinct-ring counterpart for it in any JSON.** The honest
distinct-ring reading of the headline is therefore 0.2500. Read
it as a candidate-level number, and read every baseline in the table beside it
the same way — they are all inflated by the same mechanism, which is why the
*deltas* below are the load-bearing part.

Paired bootstrap over those same 18 cycles, supervised minus the shipped v1
blend (`data/eval_oracle.json`, `oracle_as_is.paired`):

| k | delta | 95% CI | excludes zero? |
|---:|---:|---|---|
| 10 | **+0.2278** | [+0.1167, +0.3500] | **yes** |
| 20 | +0.1111 | [+0.0528, +0.1778] | **yes** |
| 50 | +0.0444 | [+0.0222, +0.0678] | **yes** |

The stored F1 of 0.0045 is **not** interpreted and should not be quoted without
this clause: a fixed 0.5 threshold on a pool with roughly 0.1% positives
measures the threshold, not the model.

### It was fitted twice, by two scripts, and landed in the same place

This is the reason the result is quoted at all rather than filed as a curiosity.
`scripts/eval_ranker.py` exists to test LambdaMART, and it carries a pointwise
LightGBM classifier as its reference arm — a second fit, from a separately
collected candidate pool, on the identical ring-disjoint split (same `split_t`
7980, same 169,947 train / 176,576 test rows, same 18 held-out cycles). It
reaches **p@10 0.2778 [0.1500, 0.4167]**, with a paired delta over the v1 blend
of **+0.2278 [+0.1167, +0.3500]** (`data/eval_ranker.json`,
`paired["pointwise-blend@10"]`).

**The two agree exactly, to every digit.** Both report p@10 0.2778 [0.1500,
0.4167]; both report a paired delta over the v1 blend of +0.2278 [+0.1167,
+0.3500] at k=10 and +0.0444 at k=50. Two scripts, with separate
pool-collection paths and separate evaluation harnesses, produce the identical
number. State the limit of that too — the two fits share a model family, a
feature block and a seed, so this is a check that the pool-collection and
evaluation path reproduces, not two statistically independent estimates. An
earlier version of this section reported the two as 0.2667 and 0.2778 and read
the 0.011 between them as fit-to-fit wobble. That reading was wrong: the 0.2667
was a stored number from a run that predated commit `b1ef656`'s fix to a
numerically unstable feature (see `docs/HANDOFF.md` §3). Re-run after the fix,
the gap is zero.

**The largest CI-clear separation from a baseline anywhere in this repository is
this one — supervised versus baseline at k=10, at either fit.** Against the
shipped v1 blend that is +0.2278 [+0.1167, +0.3500] in both
`data/eval_oracle.json` and `data/eval_ranker.json`; against random, +0.2778
[+0.1500, +0.4167] in both. Nothing else
measured on real seeding is in the same range — the pruning A/B tops out at
+0.088 [+0.056, +0.126] (`data/prune_impact.json`) and every Phase 4 re-ranker
delta includes zero. The only larger separations stored anywhere are inside run
2 of `scripts/eval_oracle.py`, which cheats at seeding and is a ceiling
diagnostic, not a result. This paragraph replaces an earlier claim that the
supervised-minus-blend delta at k=10 was "the widest CI-clear result in this
project": it was not, because the same two files hold a wider one — the
supervised-minus-random delta at k=10, +0.2778 [+0.1500, +0.4167], on the very
same split. The correction is that the widest result is *a* supervised-versus-
baseline gap at k=10, not that particular one.

### The label tax — why the caveat is the argument

0.278 is what these features support **when the labels are perfect**. A
deployment does not get ground truth; it gets analyst verdicts. Phase 4's
learned re-ranker, trained on *simulated analyst verdicts* instead of truth,
reached **p@10 = 0.124 against 0.106 for the v1 hand-set** over 17 held-out
cycles, with [a paired delta CI that includes zero at every
k](docs/HANDOFF.md#with-the-learned-re-ranker-held-out) (`data/eval_phase4.json`,
`lift_ci`).

**Those two numbers are not two arms of one experiment, and this README used to
claim they were.** The retracted sentence read "same features, same candidates,
same model family — only the labels changed". Every clause of it is false, and
here is the list, because a correction that does not enumerate what was wrong is
just a softer version of the same claim:

| | verdict-trained (Phase 4) | truth-trained (run 1) |
|---|---|---|
| model | `HistGradientBoostingClassifier` (`sentinel/learn/reranker.py`) | `LGBMClassifier` (`scripts/eval_oracle.py`) |
| features | 44 (`data/eval_phase4.json` → `importances`) | 54 (`data/eval_ranker.json` → `n_features`) |
| training corpus | 680 **cases** (`n_train`) | 169,947 **candidates**, 321 positive — roughly 250× |
| split rule | plain time split on cases (`time_split`, `scripts/eval_phase4.py`) | ring-disjoint `ring_time_split` |
| split point | `split_t` 8340 | `split_t` 7980 |
| evaluation window | 17 held-out cycles | 18 held-out cycles |

**What can honestly be said.** A verdict-trained re-ranker on 680 labelled cases
reached p@10 0.124 over 17 held-out cycles; a truth-trained model on ~170k
candidates reached 0.278 over a different 18. The gap is *consistent with* a
label-quality tax, and it is not a measurement of one — training-set size,
feature block, model family, split rule and evaluation window all differ, and
any one of them could carry the whole 2.25×.

**The clean experiment is the same model, on the same pool, on the same split,
fitted twice: once on true ring labels, once on simulated verdicts. It has not
been run.** Naming it is the honest position; calling the 2.25× the tax is not.
And it is cheap — `collect_pool` in `scripts/eval_oracle.py` already returns
exactly what it needs (the candidate records plus `ring_first_t`), so the second
arm is a relabelling of an existing pool and a second `fit`, not a new
evaluation harness. **That is the next task on this measurement**, and until it
runs, "the label tax" is a hypothesis with a plausible mechanism, not a number.

The strategic claim does not depend on the arithmetic, which is why it survives
the correction: **the label corpus, not the detector, is the actual product.**
The detector reaches 0.278 when someone hands it clean ring labels, and nobody
will hand it those. What would close whatever gap is real is the verdict
pipeline — the case store, the control lane, the calibration loop — not a better
model. That was the argument before the 2.25× was quoted and it is the argument
after it is withdrawn.

**0.278 is never a production number, and it is not quoted as one anywhere in
this repository.** It is what these features support under a label advantage no
deployment has — and it is not a ceiling on the features either, only the best
these features have been made to do so far.

### Three measurements came back negative, and that is recorded here

Three follow-up experiments were run to close gaps this project already knew
it had open. All three came back negative or null, the decisions they imply
have not changed, and a negative result gets deleted from documentation more
often than a positive one — so it goes here rather than in a script's own
output.

**1. A ranking-native loss does not beat the pointwise model where it matters.**
`scripts/eval_ranker.py` exists to test whether LambdaMART beats the pointwise
LightGBM classifier already quoted above. It beats the v1 hand-set blend —
both fits do, at every k (`data/eval_ranker.json`, `ship`, true for
`pointwise`/`lambdamart` at k=10/20/50). It does not clearly beat the
pointwise model itself. Paired bootstrap, lambdamart minus pointwise, same
ring-disjoint split, same 18 held-out cycles
(`data/eval_ranker.json`, `head_to_head_vs_pointwise`):

| k | delta | 95% CI | excludes zero? |
|---:|---:|---|---|
| 10 | -0.0167 | [-0.0611, +0.0222] | no |
| 20 | +0.0111 | [-0.0139, +0.0361] | no |
| 50 | +0.0122 | [+0.0022, +0.0244] | yes |

The pre-registered prediction was that a ranking-native loss would beat a
pointwise classifier; it was wrong in both directions, not merely optimistic —
LambdaMART neither loses to the pointwise model nor clearly beats it. The two
are statistically indistinguishable at k=10 and k=20, and the one interval
that clears zero is at k=50, the depth where the analyst's alert budget
matters least. There is no measured case here for shipping the listwise loss
over the pointwise model.

**2. Closing a real GFP coverage gap made ranking worse, not better — and the
seed-stability re-run that would have qualified that claim has already run.**
IBM's Graph Feature Preprocessor computes per-account/edge median transaction
amounts; sentinel's 54-feature block did not. Five such features
(`mean_median_out_amount`, `mean_median_in_amount`, `max_median_out_amount`,
`max_median_in_amount`, `internal_edge_median`) were added and the model
refit on the identical pool and split (`data/eval_median_gap.json`).

*Chapter A — the single shipped-config fit.* Paired bootstrap, with-median
minus sentinel, candidate-level, same 18 cycles (`data/eval_median_gap.json`,
`candidate.paired`):

| k | delta | 95% CI | excludes zero? |
|---:|---:|---|---|
| 10 | -0.0444 | [-0.0833, -0.0056] | yes |
| 20 | -0.0167 | [-0.0417, +0.0083] | no |
| 50 | -0.0078 | [-0.0144, -0.0011] | yes |

Of the 59 total features in that fit, three of the five new ones rank in the
top 10 by importance — `internal_edge_median` 5th, `max_median_out_amount`
8th, `mean_median_out_amount` 9th (`median_ranks`) — while degrading
precision. Heavily used and net-negative on a 321-positive training set is the
signature of overfitting, not of a feature the model correctly ignored.

*Chapter B — the corrected 5-seed re-run, which supersedes Chapter A's number
as a stability claim.* A first seed sweep reported "5 of 5 seeds degrade at
k=10" with bit-identical predictions across seeds — `random_state` does
nothing in this LightGBM config once bagging and feature-sampling sit at their
default 1.0, so it was one fit reported five times (commit `8c17994`, message
in full via `git show 8c17994`). The sweep was corrected to perturb
`subsample=0.8`/`subsample_freq=1`/`colsample_bytree=0.8`, which the RNG does
reach, with an assertion added so identical seeds can never again pass as five
agreeing fits. The corrected sweep (`data/eval_median_gap.json`, `per_seed`,
`seeds_harming_at_10`, `seeds_helping_at_10`): at k=10, 2 of 5 seeds show a
CI-clear degradation and 0 of 5 show a gain — point estimates run from -0.0556
to +0.0056, so 3 of 5 are statistically null, not degradations. At k=20 all
five point estimates are negative and 3 of 5 exclude zero.

**The honest characterization is not "confirmed degradation, -0.0444,
provisional pending a seed re-run" — that re-run is done.** It is: these
features never helped in any fit at either depth; the degradation is real in
the single shipped-config fit and in 2 of 5 genuinely-varied fits, and
indistinguishable from zero in the other 3. The file's own verdict
(`data/eval_median_gap.json`, `verdict`) states it plainly: *"NOT WORTH THE
DESIGN COST: no measured improvement at k=10 or k=20, and the degradation is
not stable across model-fit seeds. The absence recorded in
tests/test_gfp_gaps.py stands, and now stands on a measurement rather than on
the argument that Welford cannot do medians. Do not add a streaming quantile
estimator."* The decision — do not add these features, do not build a
streaming quantile estimator — is unchanged; it now rests on the corrected
evidence rather than the single, stronger-sounding number, which is a better
place for a decision to rest. The broader point survives at full strength:
a feature GFP computes and sentinel lacked is not automatically worth adding —
heavily-used-but-net-negative on a small labelled set is overfitting, and
"GFP computes it" is not by itself a reason.

**3. GFP feature parity remains unmeasured, and stays unclaimed here.**
`scripts/gfp_control.py` already establishes why: `snapml` 1.15.6 imports
cleanly on this Windows Python 3.11 venv, but constructing
`GraphFeaturePreprocessor()` raises `AttributeError: module
'snapml.libsnapmllocal3_avx2' has no attribute 'gf_allocate'` — none of the
Windows `.pyd` binaries export any `gf_*` symbol, while the manylinux wheel of
the identical version exports all eight. The blocker is the operating system,
not the Python version; a newer venv cannot fix a symbol the Windows build
never exported at any snapml release. No parity control has run, no parity
number exists in this repository, and no sentence here claims otherwise.

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
| top 10 | 66,342 at risk |
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

There is no graph neural network here. There *is* a trained model, in fact two
of them, and the distance between what they score is the argument: a supervised
re-ranker trained on ground-truth ring labels reaches [p@10 0.278 on a
ring-disjoint held-out split](#the-supervised-re-ranker-and-what-perfect-labels-are-worth),
while a re-ranker trained on simulated analyst verdicts — the only labels a
deployment actually has — reaches 0.124. Those are **two different experiments**,
not one experiment run twice: different model, different feature block, a
250×-smaller training corpus, a different split rule and a different evaluation
window, all enumerated [in the label-tax
section](#the-label-tax--why-the-caveat-is-the-argument). The gap is consistent
with **you cannot train a supervised ring detector to its potential before you
have confirmed rings**; it does not by itself measure the size of that effect.
Which is still why the label pipeline is the product. Every component below
earns its place on a measurement, not on the fact that this is an AI
buildathon.

### 1. Learned re-ranker — `sentinel/learn/reranker.py`

Trains on the analyst verdict corpus and reorders the queue.

**STRUCK — the held-out average precision figure this paragraph used to quote.**
It read "held-out average precision 0.2704 against a 0.0412 base rate". It is
gone rather than softened, because it is not traceable to anything runnable:
`data/eval_phase4.json` has no `ap` key, and `scripts/eval_phase4.py` never
computes average precision at all. The number survives only in
`docs/PHASE4-FINDINGS.md`, the session record of the run that produced it, and
that file is left alone as the historical record it is. It is not reproducible
from this repository today, so it is not quoted from this repository today.

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
python scripts/eval_oracle.py        # run 1: supervised re-ranker on TRUE ring
                                     #   labels, ring-disjoint held-out split
                                     # run 2: seed-cheat ceiling diagnostic
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
| **This project's shipped v1 blend, unsupervised, threshold-free, whole population** | **AP 0.011 (1.7x base rate)** |

The fair like-for-like row is the threshold-free one, and it is weak. An earlier
top-10 slice figure (F1 0.068, "11x lift") is a fixed-cardinality-selection
artifact — five different uncalibrated operating points, with the best quoted —
and it should not be placed beside a calibrated whole-test-set decision.

**The "unsupervised" qualifier belongs to that row, not to the repository.** The
last row is the *shipped v1 hand-set blend*, which trains on nothing. This repo
also contains a supervised result — [p@10 0.2778 on a ring-disjoint
held-out split](#the-supervised-re-ranker-and-what-perfect-labels-are-worth) —
so "this uses none" is true of what ships and false of what has been measured.
The supervised numbers are deliberately **not** dropped into the table above,
because they would not mean anything there: the published baselines and the last
row are *transaction-level minority-class F1 over the whole population*, and the
supervised result is *ring-level precision at k over held-out cycles* — a
different unit, a different denominator, and a different decision. Putting them
in one column would be exactly the fixed-cardinality mistake the paragraph above
retracts. Those baselines do train on the labels, the shipped blend uses none,
and the size of that gap should be read off the threshold-free row.

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

### The wedge: a mandate is manufacturing this bottleneck on a published schedule

*The figures in this subsection are external public claims, not measurements
from this repo. Nothing here rests on access to bank data, which this project
does not have.*

India's Ministry of Home Affairs has directed financial institutions to
integrate with the RBI's **MuleHunter.AI** by **December 2026**. It runs on 19
behavioural patterns and is implemented in **23 banks** (a December 2025 RTI
response, via MediaNama). On that same RTI the RBI **declined to disclose how
many mule accounts have been identified or acted on**, citing fiduciary
grounds — so the "~20,000 mule accounts per month" and "~450,000 frozen"
figures that circulate in secondary coverage are capability claims, not
RBI-confirmed outcomes, and are not repeated here as measurements. The mandate
argument below does not need them: it rests on the account count MuleHunter
touches being nonzero and growing, not on its exact monthly rate.

MuleHunter answers *"is this account a mule?"* **Nothing in that stack answers
"which of these mules are the same ring?"** A mandate that obliges every
institution in the country to stand up account-level mule detection by a fixed
date is, by construction, manufacturing a flood of account-level alerts — and
the bottleneck that flood creates is the one this project is built for.

That makes Sentinel **complementary to MuleHunter, not competitive with it**:
consume the alert stream, resolve it into rings, assemble the evidence, and
hand an analyst one decision covering forty accounts instead of forty decisions
covering one each.

### Who this does not compete with, said plainly

- **RBI MuleHunter.AI** — government-built, free to banks, and mandated. There
  is no version of this project that out-detects it, and it should not try.
- **Razorpay Vulcan** (launched 18 Aug 2026) — trained on roughly 4 billion
  payments and 3 trillion data points, free to merchants, already doing
  network-level cross-merchant detection. No public dataset and no laptop
  closes that gap.
- **The agentic alert-triage category** (Unit21, Sardine, Alessa, Binderr,
  Kriv) is genuinely crowded, and its marketing language is close to this
  README's older framing. But every one of them triages alerts **one at a
  time**. None of them change the unit of investigation. The crowding is an
  argument for sharpening ring-level case assembly, not for abandoning it.

Naming non-competitors accurately is a judgment claim, not a modesty one. The
layer this occupies is the investigation, not the score.

**DPIP** (RBI and NPCI) shares fraud signal between institutions. MuleHunter
sits inside banks; DPIP sits between them. **Neither sits at the
payment-aggregator merchant layer**, and that gap is the sharpest case for this
work. Reporting explicitly names payment-aggregator merchant accounts as the
weaponised vector — *"fraudulent accounts can look identical to legitimate
businesses."* **524,121** suspected mule accounts were flagged in March 2026
alone, and **2.47 million** Layer-1 mule accounts by I4C.

Nothing public suggests any of these systems hands an analyst *"here are the
nine accounts that form this structure, here is the shape, and here is the
evidence for each claim."* Nor point-in-time labelling, a five-way verdict
taxonomy, or control-arm sampling.

Compliance timing matters too: an STR must be filed within seven working days
of forming suspicion, and protracted internal review is the most-cited cause of
late filing. This compresses both clocks.

### Elliptic2: take the dataset, leave the market

`scripts/eval_elliptic2.py` already reads Elliptic2, and its thesis — that
money laundering is a subgraph-level problem — is this project's thesis. Its
**2,763 labelled suspicious subgraphs against HI-Small's 370** is the honest
fix for the sample-size ceiling that weakens every confidence interval in this
README.

It is used here as a **second dataset for cross-dataset generalisation**, and
explicitly **not** as a change of market. Repositioning onto crypto would walk
into Chainalysis, Elliptic and TRM, and away from Indian payments. The dataset
is worth taking; the market is not.

### If this were a company rather than a submission

*External public figures again, not measured here.* Between FY2021-22 and
September FY2025-26 India recorded **₹3,588 crore** in digital-payment fraud
losses and recovered **₹238.83 crore** — a **6.7% recovery rate**. Cyber fraud
overall ran to roughly ₹22,495 crore in 2025, with case volume up 24%.

That recovery rate is the whole argument. Money is recoverable only *before* it
disperses through the layering chain. Freezing one mule account per alert loses
that race by construction — it chases a network with a scalar. Ring-level
action is the only structure that moves at the speed the money moves, because
one decision covers the whole layer instead of one node in it.

Three things would make that defensible: the labelled ring corpus accumulated
in operation is a compounding asset no incumbent has; ring-level evaluation is
something nobody in the category currently reports; and the regulatory calendar
creates the alert flood without anyone having to sell it.

### The counterweight, in the same breath

The cost model says the queue's viability is **conditional**, and the condition
is measurable rather than assumed. At top 10 it pays only if the average
confirmed ring carries more than **66,342** at risk
(`scripts/eval_cost.py`; the unit is deliberately unnamed — ratios are what
the model claims, not rupees).

*A note on which p@k this is.* The precisions in this subsection — 0.097,
0.079, 0.043 — are the **shipped v1 queue's** score ranking from HANDOFF §5d,
which is what an ops team would actually work today. They are not the
supervised re-ranker's p@10 of 0.2778 quoted earlier: that model trains on
ground-truth ring labels and is not deployable on day one. Costing the queue
against the re-ranker's number would assume away exactly the label dependency
this README spends a section establishing.

**All six cost inputs are still placeholders**, and the model says so on every
run (`unsourced()`). Under a joint stress — all six *inputs* moved adverse at
once, each by a factor of two — the break-even precision rises from **0.0056
to 0.0864**. Note that this is harsher than doubling: review cost, benefit and
false-positive harm are each a *product of two* of those inputs, so review cost
and residual harm rise fourfold while the benefit falls to a quarter. At that
corner
**only top 10 still pays** (p@10 = 0.097); top 20 (0.079) and top 50 (0.043)
do not.

**But the severity factor is doing all the work, and that is the real
finding.** Two is a convention, not a measurement, and top 10 clears 0.0864 by
about one point of precision. Sweeping the factor: at x1.5 the break-even is
0.0282 and top 10 pays; at x2 it is 0.0864 and top 10 still pays; at **x2.06 it
stops paying**; at x2.5 it is 0.1979 and no depth pays at any k.

**At the x10 corner the repo actually gates on, nothing pays at all.**
`scripts/ci_gates.py`'s cost gate runs the same joint construction across the
0.1x-10x band its one-at-a-time sweep uses, and reports a break-even of
**1.8382** — a precision above 1.0, i.e. unreachable by any detector. So the
honest statement is not "the shallow queue survives the pessimistic corner." It
is that **the queue's survival under joint stress is decided entirely by a
severity parameter nobody has grounded**: it flips about three percent past x2,
and by x10 the queue cannot pay however good the ranking gets.

That gate PASSES, and the reason it passes is worth stating: its criterion is
that no *single* unsourced input can flip the pay/no-pay verdict across an
order of magnitude, which is true. The joint corner does flip it, and the gate
prints that rather than gating on it — one-at-a-time robustness does not extend
to the joint case, and the gate says so in its own output.

Grounding those six inputs is the difference between a thesis and a business.
The answer to the obvious challenge, though, is that **the break-even
inverts**: `required_value_at_risk` solves for the exposure instead of assuming
it, so nobody has to accept these rupee figures to check the claim. They only
have to decide whether the threshold is plausible — a question an ops lead can
actually answer.

### Pivots considered and rejected

Five directions were considered and rejected, on purpose: becoming a general
AML case-management platform (a different, crowded product with different
buyers); moving the target market to crypto/on-chain (the Elliptic2 dataset
gets used above precisely *without* this move, because it walks into
Chainalysis, Elliptic and TRM and away from the Indian-payments track this is
built for); selling the measurement and evaluation harness itself as the
product (it is the thing that makes every other claim here checkable, not a
product in its own right); chasing GFP feature-parity as a goal
(`scripts/gfp_control.py` and the corrections above it establish that parity is
unmeasured and unmeasurable on this OS — treating it as a target would mean
optimizing against a number nobody can compute); and competing head-on with
MuleHunter or Vulcan on raw detection accuracy (covered above under "who this
does not compete with" — restated here because a reader scanning for pivots
rather than positioning should be able to find it without re-deriving it).

---

## Not built, and stated as such

Kafka ingest from a live transaction topic, deep links into an internal admin
panel, case-management push, and real execution of payout holds or step-up
authentication. Batch actions are simulated and labelled as such.

There is no graph neural network. There is no *deployed* ring detector trained
on ground truth either — only on analyst verdicts, which is all a deployment
ever has; the ground-truth-label run is a held-out measurement of what the
features can support, never a shipped model. See
[Where the AI actually is](#where-the-ai-actually-is) and [the label
tax](#the-label-tax--why-the-caveat-is-the-argument) for why that is a decision
rather than an omission, and what is trained instead.

---

*Commits are co-authored with Claude Opus 5, deliberately and visibly. It is an
AI buildathon; using the tools and saying so is the honest position.*
