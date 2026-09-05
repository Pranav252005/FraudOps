# Experiment queue

Ranked by **measured funnel loss**, not by interest. Worked through the loop in
`.claude/skills/payops-experiment/SKILL.md`: pre-register with a kill rule,
run, adjudicate, then strike the item and re-rank.

Seeded 2026-09-04 from the review in
[`graph-review/2026-09-04.md`](graph-review/2026-09-04.md). Nothing below has
been run. Every prize column is an **expectation, not a measurement** — that is
what the pre-registration is for.

## Stage: leakage (blocks the credibility of everything else)

| # | experiment | why now | cost |
|---:|---|---|---|
| ~~L1~~ | ~~Label-poison test + static reachability scan for `PairAgg.laundering`~~ | **DONE 2026-09-04.** Both halves shipped with negative controls; now standing rule 8 and the `label_poison` CI gate. See the ledger entry. | done |
| L2 | **Purge-and-embargo variant of `ring_time_split`** | The current split is time-ordered on negatives only; train-assigned rings keep post-`split_t` candidates. An embargo buys time-ordering on positives at a known cost in rows. Report both splits, not a replacement. | ~2h + refit |

## Stage: seeded (four typologies at 0%)

| # | experiment | why now | cost |
|---:|---|---|---|
| ~~S1~~ | ~~Second seed predicate: GARG-AML-style second-order block-density score~~ | **DONE 2026-09-04 — REFUTED as a distinct idea.** Bit-identical to S2: the cleanliness term is 1.0 for 98.6% of the real pool, so the score collapses to degree. Ceiling was 7 rings, not "the largest loss in the funnel" — that premise came from a stale docstring. See [`SEED-PREDICATE-FINDINGS.md`](SEED-PREDICATE-FINDINGS.md). | done |
| ~~S2~~ | ~~Degree-burst seed predicate (fan-in or fan-out ≥ k within one tick)~~ | **DONE 2026-09-04 — not shipped.** +14 built over shipped (+10 over the random null, so attributable), **+0 ranked**, for 10% more seeds. Helps FAN-IN/FAN-OUT; does nothing for BIPARTITE/STACK, the two build-destroyed typologies. | done |

## Stage: built (~38% of seeded rings lost to dilution)

| # | experiment | why now | cost |
|---:|---|---|---|
| ~~B1~~ | ~~Fragment linking: join candidates connected through ≤1 external intermediary and temporally compatible~~ | **DONE 2026-09-04 — REFUTED as scoped.** Built 161 in all three arms: zero rings newly reached. A large p@20/p@50 gain appeared but the size baseline nearly tripled with it and `score − size` goes to zero at k=20 and negative at k=50 — bug #8's pattern. Distinct rings ranked fell 58→55. Containment doubles (0.79 vs 0.39), so the mechanism assembles; it just does not pay. Not shipped. See [`FRAGMENT-LINK-FINDINGS.md`](FRAGMENT-LINK-FINDINGS.md). | done |
| B2 | **Size-adaptive window: extend `WINDOW_MINUTES` for large structures only** | Direction 2 of the same document. Fragmentation is ring-size against window length and `WINDOW_MINUTES` is uniform. Harder than B1 because the window is a global object. | ~2 days |
| ~~B3~~ | ~~Score-free suppression key~~ | **DONE 2026-09-04 — confirmed, and the review's proposed key was the wrong one.** The property holds both ways: the shipped pool moves under a weight perturbation (0.76% of the fixture pool), all three score-free pools are bit-identical. Cost for `smallest`: CI includes zero at every k, `ranked@50` unchanged at 58, built +1. `largest` (the proposal) is the only arm with a CI-clear loss. **Default not flipped** — that is a judgement, not a measurement. See [`SUPPRESSION-KEY-FINDINGS.md`](SUPPRESSION-KEY-FINDINGS.md). | done |

## Stage: ranked (not the binding constraint — do not promote these)

| # | experiment | why now | cost |
|---:|---|---|---|
| R1 | **The clean label-tax experiment** | Still open from `HANDOFF-NEXT.md` §3: same model, same pool, same split, fitted once on truth and once on simulated verdicts. It is the only way to attribute the run-1 vs Phase-4 2×, which is confounded on five axes. | ~4h |

## Methodology (cheap, and closes standing objections)

| # | experiment | why now | cost |
|---:|---|---|---|
| ~~M1~~ | ~~`is_hit` threshold sensitivity band~~ | **DONE 2026-09-04.** 9/9 cells positive, 9/9 CI-clear at k=10 and at k=20. Shipped cell reproduces `eval_phase2.json` exactly. Thresholds unchanged. See [`THRESHOLD-BAND.md`](THRESHOLD-BAND.md). | done |
| ~~M2~~ | ~~Bootstrap Monte Carlo check~~ | **DONE 2026-09-05.** 320 comparisons x 40 seeds x {2000, 10000}. **3 flips of 320 at B=2000 (0.9%), 2 at 10000, and none is a reported conclusion.** P0's headline and the shipped `score − size` are immovable; all 191 comparisons with an endpoint beyond 0.01 from zero are stable. Default NOT raised. See [`BOOTSTRAP-MC-FINDINGS.md`](BOOTSTRAP-MC-FINDINGS.md). | done |
| M2b | **Flag Monte-Carlo-unstable intervals at source** | All three flips sit at a nearest endpoint <= 0.0015. When an interval's nearer endpoint falls within ~0.005 of zero, recompute that one at B >= 10000 before quoting it as a verdict. Targeted; touches `bootstrap.py`, which every number flows through, so it needs its own care. | ~2h |

## Blocked

| # | experiment | blocker |
|---:|---|---|
| X1 | GFP head-to-head parity | No `gf_*` symbols in any Windows `.pyd`; needs WSL/Docker/Linux. **No parity claim may enter the repo until this runs.** See `HANDOFF-NEXT.md` §1. |

## Stage: seeding (closed by P0)

| # | experiment | why now | cost |
|---:|---|---|---|
| ~~P0~~ | ~~Widen the seed source beyond one tick~~ | **DONE 2026-09-05.** seeds() drew from 1h of a 72h window. lb6: seeded 230→258 of 259, built 161→218, **every typology gained** incl. BIPARTITE +11 and STACK +5, p@10 0.2912→0.5500 CI-clear. But **ranked@50 only 58→61** and build→rank retention FELL 0.360→0.280, at 4.85x cost. Not shipped — decision pending. See [`SEED-LOOKBACK-FINDINGS.md`](SEED-LOOKBACK-FINDINGS.md). | done |
| ~~P0b~~ | ~~Guard: `observe()` must be called when lookback > 1~~ | **DONE 2026-09-05.** Three guards, each with a negative control: omission (`seeds()` refuses an empty lookback), non-contiguity (`observe()` refuses a skipped tick, which is what would make lookback 6 silently mean 36h), and out-of-step observe/generate. Shipped lookback 1 is untouched — no observe, no timestamps, no contiguity required. `stats["observed_ticks"]` added so a harness can assert its own wiring. | done |
| P0c | **lb24 over the full 34 cycles** | Measured at 17.62x cost for +1 ring in a single cycle and dropped as a declared deviation. No claim made about it over a full run. | ~3h |

## Stage: corpus (opened 2026-09-05)

| # | experiment | why now | cost |
|---:|---|---|---|
| ~~D2~~ | ~~Build the HI-Medium stream and evaluate on it~~ | **DONE 2026-09-05.** 29.3M edges, 2.08M nodes, 58 cycles, 1,900 rings, 2h44m. score-size CI-clear at **every** k including k=100, where HI-Small shows a reversal. Typology ordering replicates, Spearman +0.786. **But it did NOT narrow the intervals** -- the bootstrap resamples cycles (34->58), not rings (259->1900). See [`HI-MEDIUM-FINDINGS.md`](HI-MEDIUM-FINDINGS.md). | done |
| D1 | **Re-derive HI-Small's `structural_recall_ceiling`** | The committed 0.733 cannot be reproduced from its own provenance (four readings give 278-282 of 363, never 266). Until it is re-derived under the stated definition, cross-split ceiling comparison is invalid. Changes a number that appears in prose repo-wide. | ~2h |
| ~~D3~~ | ~~Run the funnel and oracle on HI-Medium~~ | **FUNNEL DONE 2026-09-05.** Stage ordering replicates exactly -- ranking 49.2 > build 28.7 > seeding 6.1 pts -- and the same two typologies are build-destroyed on both splits (BIPARTITE 22%, STACK 30%), and only those two. Oracle running; ~12h projected. | part |
| ~~D4~~ | ~~Dataset-aware result paths for the remaining eval scripts~~ | **DONE 2026-09-05.** 29 scripts migrated (reads as well as writes); `dataset_constants.json` exempt by design and asserted as such. An AST guard replaces the regex and immediately found one the regex missed. | done |
| ~~D3b~~ | ~~Make `eval_oracle.collect_pool` retain feature vectors~~ | **DONE 2026-09-05, verified end-to-end.** HI-Small oracle re-run and diffed against the pre-change baseline: **zero numeric differences**, all four diffs prose. Also retro-validated the "shipped path unchanged" claims of six intervening commits. | done |
| ~~D5~~ | ~~`ring_recall@k` intervals are invalid~~ | **ESTIMATOR LANDED 2026-09-05, re-run chained.** Cause: a cluster bootstrap cannot bound a UNION -- a ring is seen across several consecutive cycles but found in one, so dropping a cycle removes rings from `found` faster than from `seen` and the ratio is biased low by construction. Fixed by attributing each ring to one owning cycle, making recall a ratio of sums with an ALGEBRAICALLY IDENTICAL point estimate. Negative control reproduces the shipped failure exactly (old CI [0.140,0.235] entirely below its 0.295 point). Both funnels re-run once the oracle frees the machine. | part |
| ~~D6~~ | ~~`eval_funnel.py` misreports where it wrote~~ | **DONE 2026-09-05**, fixed alongside D5. | done |
| ~~D7~~ | ~~The oracle pool retained two fields nothing reads~~ | **DONE 2026-09-05.** `overlap` and `ring_members` were stored on every pooled record for a second labelling pass that never existed. `ring_members` is a SET OF NODE KEYS: 728 bytes for a ring of 5-10, 2,264 for one of 20-40, against 544 for the feature vector D3b was written to protect. It killed the HI-Medium oracle at cycle 40 of 58. Removed, with an AST guard that fails on any stored-but-unread field. | done |
| ~~D1~~ | ~~Re-derive HI-Small's ceiling so all three splits report one quantity~~ | **DONE 2026-09-05, and the earlier verdict was wrong.** 0.733 IS reproducible: 'accounts visible in-window' means accounts on edges BEFORE the boundary, not every account the ring touches. Read that way it gives 266/363 exactly, and does so with or without self-loops and with either account key. The derivation was wrong, not the constant. LI-Small 0.810 -> 0.802, HI-Medium 0.758 -> 0.720; `--check` now asserts the ceiling too. | done |
