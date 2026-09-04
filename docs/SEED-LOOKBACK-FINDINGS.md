# P0 — the seed source was the binding constraint, and the output still barely moved

**Pre-registered in [`prereg/seed_lookback.md`](../prereg/seed_lookback.md)**
before `seed_lookback_ticks` existed. Run 2026-09-05, 34 cycles, 2,547 s,
`scripts/eval_seed_lookback.py` → `data/eval_seed_lookback.json`.
Cycle-clustered paired bootstrap.

**Baseline reproduction, per the prereg's deviation policy:** `lb1` returns
seeded 230 / built 161 / ranked 58 and p@10 0.2912, p@20 0.1574, p@50 0.0759 —
identical to `data/funnel.json` and the stored headline. The run is valid.

**No kill criterion fired.** All five clear, though #2 cleared by exactly one
ring.

## The result

| arm | seeds/cycle | cands/cycle | cost | seeded | built | ranked@50 | p@10 | p@20 | p@50 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `lb1` (shipped, 1h) | 10,458 | 10,193 | 1.00× | 230 | 161 | **58** | 0.2912 | 0.1574 | 0.0759 |
| `lb6` (6h) | 42,414 | 40,691 | **4.85×** | **258** | **218** | **61** | **0.5500** | **0.4000** | **0.1835** |

Paired deltas, `lb6 − lb1`:

| k=10 | k=20 | k=50 |
|---|---|---|
| **+0.2588 [+0.182, +0.335]** | **+0.2426 [+0.199, +0.290]** | **+0.1076 [+0.084, +0.132]** |

All three exclude zero. Seeding is now essentially complete: **258 of 259**
active rings seeded, against 230.

## This is the first change in two days to move a headline number. Read the rest anyway.

### What genuinely improved

**Seeding is solved.** 230 → 258 of 259. The 22 rings I showed were reachable
only by widening, plus 6 more — see §"Against the pre-registration".

**Build recall rose 35%**: 161 → 218 of 259 (62.2% → 84.2%). **Every typology
gained**, including the two that nothing else has moved:

| typology | lb1 built | lb6 built | Δ |
|---|---:|---:|---:|
| **BIPARTITE** | 5 | **16** | **+11** |
| CYCLE | 28 | 35 | +7 |
| FAN-OUT | 24 | 33 | +9 |
| FAN-IN | 21 | 29 | +8 |
| RANDOM | 17 | 25 | +8 |
| GATHER-SCATTER | 30 | 36 | +6 |
| **STACK** | 9 | **14** | **+5** |
| SCATTER-GATHER | 27 | 30 | +3 |

BIPARTITE goes from 16% built to 52%. S1 and B1 both targeted exactly these two
typologies and moved neither. A one-line change to the seed source moved both.

**The size baseline did not follow.** `score − size` is CI-clear at every k in
both arms and the margin **widens** under `lb6` (+0.2029 → +0.5324 at k=10).
Spearman ρ(score, size) *falls*, 0.2714 → 0.1987. Neither the re-tie check nor
the ρ diagnostic fires. This is not B1's size artifact.

### What did not improve, and it is the number that matters

**`ranked@50` went 58 → 61.** Three rings. Kill criterion 2 required ≥3, so it
cleared by exactly one ring.

**Build→rank retention got worse: 0.360 → 0.280.** The funnel now builds far
more and converts less.

Per typology, `ranked@50` is not a story of gains:

| | lb1 | lb6 | Δ |
|---|---:|---:|---:|
| CYCLE | 7 | 11 | +4 |
| SCATTER-GATHER | 16 | 19 | +3 |
| BIPARTITE | 1 | 1 | 0 |
| RANDOM | 7 | 7 | 0 |
| STACK | 2 | 2 | 0 |
| GATHER-SCATTER | 9 | 8 | **−1** |
| FAN-IN | 5 | 4 | **−1** |
| FAN-OUT | 11 | 9 | **−2** |
| **TOTAL** | 58 | 61 | **+3** |

**Eleven of the sixteen BIPARTITE rings that are now built still do not reach
the top 50.** The build stage was fixed; the ranking stage swallowed it.

### Why p@k doubled while distinct rings rose by three

Both are true and they measure different things. p@k counts **slots that are
hits**; `ranked@50` counts **distinct rings**. Dividing one by the other:

| | hit slots in top-50 (34 cycles) | distinct rings | slots per ring |
|---|---:|---:|---:|
| `lb1` | ≈129 | 58 | **2.2** |
| `lb6` | ≈312 | 61 | **5.1** |

**The top 50 became more than twice as redundant.** Much of the precision gain
is the same rings occupying more slots, not more rings surfacing. That is the
B1 pattern returning, and it is stated here rather than left for a reader to
divide.

For an analyst working a queue, a doubled p@10 is still a real gain — far fewer
wasted slots — but the claim "the system finds more rings for the analyst" is
worth **+3**, not +0.26 of precision.

### The control this run does not have

`lb6` produces 4× the candidates. Some p@k gain may come from pool size alone —
a best-of-40,691 top-10 beats a best-of-10,193 top-10 even with no better
detector.

**A matched-pool null is impossible by construction here**, and that is worth
saying: you cannot draw 68,235 seeds from a single hour, because that hour
contains only 28,565 touched accounts of which 15,854 are pass-through. The
extra candidates *necessarily* come from other hours.

What is available instead: the size baseline widened in the score's favour and
ρ(score, size) fell, both of which argue against a pure pool-size artifact.
**Neither is a matched null, and the p@k figure should carry that caveat
wherever it is quoted.** The nearest evidence is S1's random arm — 10% more
seeds from the same hour moved p@10 by 0.0000 — but at 330% the scale is not
comparable.

## Against the pre-registration

| predicted | observed | |
|---|---|---|
| newly seeded +15 to +22 | **+28** | **MISSED (above)** |
| built +8 to +20 | **+57** | **MISSED badly (above)** |
| **ranked@50 +0 to +6** | **+3** | **hit** |
| p@10 paired CI **includes zero** | **excludes zero, +0.2588** | **MISSED** |
| `score − size` clear at k=10/20/50 | clear, and widened | hit |
| ρ(score, size) ≈ unchanged | 0.2714 → 0.1987 | hit |
| cost ≈ 4.3× | 4.85× | near |
| dedup rises materially, cost sublinear | **it did not** — 65,283 candidates from 68,235 seeds | **MISSED** |

**Four misses, and nearly all in the favourable direction.** I under-predicted
the generation side badly.

**Why I was wrong, precisely.** I anchored on S1, which added 10% more seeds and
returned "+14 built, +0 ranked", and predicted P0 would be the same shape. The
pre-registration itself named the distinction — S1's extra seeds came from the
same sampled hour, P0's come from hours never looked at — and then called it
"an argument, not evidence". **The argument was right and I forecast as though
it would not be.**

The +28 seeded exceeded my own ceiling of +22 because that ceiling assumed the
7 rings that were touched-but-not-pass-through stayed unreachable. With a wider
`touched` set a *different member* of those rings can be both touched and
pass-through, so 6 of the 7 were recovered too. The ceiling analysis was right
about the mechanism and wrong about the arithmetic.

**The one prediction that held is the one I said mattered**: ranked@50 landed at
+3, inside the pre-registered +0 to +6, at the low end.

## `lb24`: measured, not swept

Dropped after a one-cycle cost run — a declared post-hoc deviation, recorded in
`scripts/eval_seed_lookback.py` next to `LOOKBACKS`:

| arm | seeds | cands | secs | × shipped | rings seeded (1 cycle) |
|---|---:|---:|---:|---:|---:|
| lb1 | 15,854 | 15,494 | 17 | 1.00 | 24 |
| lb6 | 68,235 | 65,283 | 150 | 8.93 | 32 |
| lb24 | 117,159 | 109,300 | 296 | 17.62 | 33 |

lb24 cost 2× lb6 and reached one more ring in that cycle. Nothing here says
lb24 is not better over 34 cycles — **it was not run, and no claim is made
about it.**

## Recommendation

**The evidence supports shipping `lb6`, and the decision is not mine.**

For it: seeding goes from 89% to 99.6% complete; built recall +35% with every
typology gaining, including the two nothing else could move; p@k roughly
doubles at every depth with CI-clear margins; the size baseline moves the right
way; no kill criterion fires.

Against it: **4.85× generation cost**, `ranked@50` +3, build→rank retention
*falls* from 0.360 to 0.280, and the p@k gain carries an unresolved
pool-size caveat.

Shipping means changing `SEED_LOOKBACK_TICKS` to 6 **and** having every caller
invoke `observe()` on every tick — the parameter is inert without it, which is a
foot-gun worth a guard before it ships.

**What P0 actually did is move the bottleneck.** Ranking loss was 39.77 points
against a build loss of 26.64. After P0 the build loss is roughly 12 points and
essentially all of the remaining loss is ranking — and
`data/eval_oracle.json` says a supervised model on the current features buys
1.12× there. **P0 makes the feature problem the whole problem.**
