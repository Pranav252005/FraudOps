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
| S1 | **Second seed predicate: GARG-AML-style second-order block-density score** | The pass-through rule cannot reach BIPARTITE / FAN-OUT / RANDOM / STACK by construction. This is the single largest structural recall loss in the funnel, and `detect/layers.py` already computes most of the ingredients. Kill rule must include a precision floor — a seed rule that fires on everything is not an improvement. | ~1 day + replay |
| S2 | **Degree-burst seed predicate (fan-in or fan-out ≥ k within one tick)** | Cheaper than S1 and attacks FAN-OUT specifically. Run as the control arm for S1 so the prize is attributable. | ~4h + replay |

## Stage: built (~38% of seeded rings lost to dilution)

| # | experiment | why now | cost |
|---:|---|---|---|
| B1 | **Fragment linking: join candidates connected through ≤1 external intermediary and temporally compatible** | Named as direction 1 by `PHASE2-SEED-CHEAT-FINDINGS.md` and untested. Must be judged on containment **and** Jaccard together — linking grows candidates, and size is a measured confound. | ~1 day + replay |
| B2 | **Size-adaptive window: extend `WINDOW_MINUTES` for large structures only** | Direction 2 of the same document. Fragmentation is ring-size against window length and `WINDOW_MINUTES` is uniform. Harder than B1 because the window is a global object. | ~2 days |
| B3 | **Score-free suppression key** | `suppress()` is NMS ordered by score, so the score decides which candidates exist. Ordering by a deterministic key instead would decouple pool from scorer and make every future scorer A/B valid on a fixed pool. Expect the headline to move; the point is that it becomes interpretable. | ~4h + replay |

## Stage: ranked (not the binding constraint — do not promote these)

| # | experiment | why now | cost |
|---:|---|---|---|
| R1 | **The clean label-tax experiment** | Still open from `HANDOFF-NEXT.md` §3: same model, same pool, same split, fitted once on truth and once on simulated verdicts. It is the only way to attribute the run-1 vs Phase-4 2×, which is confounded on five axes. | ~4h |

## Methodology (cheap, and closes standing objections)

| # | experiment | why now | cost |
|---:|---|---|---|
| ~~M1~~ | ~~`is_hit` threshold sensitivity band~~ | **DONE 2026-09-04.** 9/9 cells positive, 9/9 CI-clear at k=10 and at k=20. Shipped cell reproduces `eval_phase2.json` exactly. Thresholds unchanged. See [`THRESHOLD-BAND.md`](THRESHOLD-BAND.md). | done |
| M2 | **Bootstrap Monte Carlo check** | One headline at a second seed and 10,000 resamples. Minutes. | ~30m |

## Blocked

| # | experiment | blocker |
|---:|---|---|
| X1 | GFP head-to-head parity | No `gf_*` symbols in any Windows `.pyd`; needs WSL/Docker/Linux. **No parity claim may enter the repo until this runs.** See `HANDOFF-NEXT.md` §1. |
