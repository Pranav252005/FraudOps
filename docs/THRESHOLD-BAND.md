# M1 — the `is_hit` threshold sensitivity band

**Pre-registered in [`prereg/threshold_band.md`](../prereg/threshold_band.md)
before the harness existed.** Run 2026-09-04, 34 cycles, 259 rings,
`scripts/eval_threshold_band.py` → `data/eval_threshold_band.json`.
Bootstrap clustering: **cycle-clustered**, paired within cell.

## Why this exists

`HIT_SHARE = 0.5` and `MIN_JACCARD = 0.3` decide what counts as finding a ring
and therefore decide every ring-level number in this repository. The
*existence* of a Jaccard floor is argued for and documented — containment alone
let a node-count baseline tie the score, which is bug #8. The *values* were
never defended by a curve. This is the curve.

Nine cells, one replay, one candidate pool: `is_hit` is an evaluation function
and takes no part in seeding, expansion, pruning, suppression or scoring, so
every cell scores the same candidates in the same order. That makes this the
one experiment in the queue that `suppress()`'s score-ordered NMS cannot
confound.

## The band

`score` p@10, the `size` baseline it must beat, and the paired delta.
`recall` is ring recall within the top 100.

| hit_share | min_jaccard | score p@10 | size p@10 | delta @10 | 95% CI | score p@20 | delta @20 | recall |
|---:|---:|---:|---:|---:|---|---:|---:|---:|
| 0.4 | 0.2 | 0.3382 | 0.1059 | +0.2324 | [+0.1500, +0.3088] | 0.1868 | +0.1059 | 0.2625 |
| 0.4 | 0.3 | 0.2941 | 0.0941 | +0.2000 | [+0.1265, +0.2706] | 0.1588 | +0.0853 | 0.2432 |
| 0.4 | 0.4 | 0.2176 | 0.0735 | +0.1441 | [+0.0882, +0.2029] | 0.1191 | +0.0588 | 0.2124 |
| 0.5 | 0.2 | 0.3324 | 0.1059 | +0.2265 | [+0.1471, +0.3029] | 0.1824 | +0.1015 | 0.2587 |
| **0.5** | **0.3** | **0.2912** | **0.0941** | **+0.1971** | **[+0.1235, +0.2676]** | **0.1574** | **+0.0838** | **0.2394** |
| 0.5 | 0.4 | 0.2176 | 0.0735 | +0.1441 | [+0.0882, +0.2029] | 0.1191 | +0.0588 | 0.2124 |
| 0.6 | 0.2 | 0.3206 | 0.1059 | +0.2147 | [+0.1353, +0.2912] | 0.1750 | +0.0941 | 0.2394 |
| 0.6 | 0.3 | 0.2824 | 0.0941 | +0.1882 | [+0.1176, +0.2559] | 0.1529 | +0.0794 | 0.2201 |
| 0.6 | 0.4 | 0.2118 | 0.0735 | +0.1382 | [+0.0794, +0.1971] | 0.1162 | +0.0559 | 0.2008 |

**Bold row is the shipped pair.** It reproduces `data/eval_phase2.json` exactly
— p@10 0.2911764…, delta +0.1970588… — which is the check that this band is a
band around the headline and not around something else.

## What it says

**The conclusion is stable across the entire grid.** `score − size` is positive
in **9 of 9** cells at k=10 and its 95% interval excludes zero in **9 of 9** —
and the same holds at k=20, so **18 of 18** intervals exclude zero. The
narrowest margin, at the tightest thresholds, is still +0.1382 [+0.0794,
+0.1971].

**The absolute number moves, and it is supposed to.** p@10 runs from 0.2118 at
the tightest cell to 0.3382 at the loosest — a factor of 1.60 across the whole
grid. A looser threshold asks an easier question and must return a bigger
number; a band that was flat would mean the thresholds were inert and not worth
having. What the headline actually asserts is that the score beats a ranker
which reads no features, and that survives everywhere.

**No headline is fragile to the choice.** Stated plainly because the
pre-registration required it to be stated either way.

## The one structural finding

**Above `min_jaccard = 0.4`, `hit_share` stops doing anything.** The rows
(0.4, 0.4) and (0.5, 0.4) are identical to the last digit at every k.

This is arithmetic, not coincidence. Jaccard is `|A∩R| / |A∪R|` and containment
is `|A∩R| / |R|`; since `|A∪R| ≥ |R|`, **Jaccard ≤ containment always**. So a
Jaccard floor at 0.4 already guarantees containment ≥ 0.4, and raising
`hit_share` from 0.4 to 0.5 can only matter for candidates whose containment
lands in [0.4, 0.5) *while* Jaccard clears 0.4 — a narrow band that this data
contains none of.

The practical consequence is worth knowing: **the two thresholds are not two
independent knobs.** `min_jaccard` is doing most of the work, `hit_share` is
partially shadowed by it, and the effective free parameter is closer to one
than to two. Reading the columns confirms it — moving `min_jaccard` 0.2 → 0.4
moves p@10 by 0.1206, while moving `hit_share` 0.4 → 0.6 moves it by 0.0176 at
most.

## Against the pre-registration

| # | predicted | observed | verdict |
|---:|---|---|---|
| 1 | p@10 at loosest = **1.2×–2.0×** shipped | **1.16×** | **MISSED** — just below the range |
| 2 | p@10 at tightest = 0.4×–0.8× shipped | 0.73× | hit |
| 3 | ring recall rises monotonically as either threshold loosens | it does, in both directions | hit |
| 4 | `score − size` sign positive in all 9 cells | 9/9 | hit |
| 5 | CI excludes zero in **at least 7 of 9** | **9 of 9** | hit, and better than predicted |
| 6 | shipped cell reproduces `eval_phase2.json` | to the last digit | hit |

**Prediction 1 missed and the miss is recorded rather than rounded.** I expected
loosening both thresholds to buy more than it did. The band is *narrower* than
predicted, which happens to be the more favourable outcome — and that is exactly
the direction in which a missed prediction is easiest to quietly not mention.

**The bad news I pre-registered did not arrive.** I wrote that I expected the
tightest cell to go underpowered rather than reversed, and that the honest claim
would then be "holds in seven or eight of nine cells". It did not: the tightest
cell is CI-clear. **My pessimistic prediction was wrong in the good direction,
and the stronger claim is the one the data supports.**

## Kill criteria

All three were checked. **None fired.**

1. **Monotonicity** — asserted in the harness before any result is read, for
   every ranking at every k, on both axes. Clean. This one fires on arithmetic,
   so a violation would have voided the run.
2. **Shipped cell excludes zero** — it does, and it reproduces the stored
   headline exactly.
3. **`score − size` negative in any cell** — never; positive in all nine.

## What this does not settle

- **The thresholds still stay where they are.** `MIN_JACCARD` remains 0.3. The
  0.2 column exists so a reader can see what a looser floor would have bought;
  publishing that number is the opposite of taking it.
- The grid is 3×3 around the shipped pair. It says nothing about thresholds
  outside [0.4, 0.6] × [0.2, 0.4], and a floor low enough to re-tie the size
  baseline presumably exists somewhere below 0.2 — bug #8 is the evidence that
  it does. Finding it was not the question asked.
- Ring recall here is recall within the top 100, not global built-recall. The
  funnel's built stage is measured by `scripts/eval_funnel.py` and is a
  different quantity.
- One dataset, one split. HI-Small only.
