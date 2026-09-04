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
| M2 | **Bootstrap Monte Carlo check** | One headline at a second seed and 10,000 resamples. Minutes. | ~30m |

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
