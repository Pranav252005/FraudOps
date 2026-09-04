# B3 — the score-free suppression key costs almost nothing, and the review picked the wrong one

**Pre-registered in [`prereg/suppression_key.md`](../prereg/suppression_key.md)**
before `suppress()` gained a key parameter and before anything was measured.
Property tested in [`tests/test_suppression_key.py`](../tests/test_suppression_key.py);
cost measured 2026-09-04, 34 cycles, 618 s, `scripts/eval_suppression_key.py`
→ `data/eval_suppression_key.json`. Cycle-clustered paired bootstrap.

## Headline

**The property holds in both directions.** The shipped score-ordered pool moves
when the blend weights move; all three score-free pools are bit-identical under
the same perturbation. The confound is real and the fix works.

**The cost is close to zero — and for one key it is statistically
indistinguishable from zero at every k**, with `ranked@50` unchanged and
built-recall up by one ring.

**The key the review proposed (`largest`) is the worst of the three tested**,
and the only one whose loss is CI-clear. `smallest` is strictly better on every
number. Had one key been adopted on the review's recommendation without
measuring the family, this project would have taken the only avoidable loss on
the table.

**No kill criterion fired.**

## 1. The property, which is the actual experiment

`suppress()` is greedy NMS ordered by score, so which member of an overlapping
group survives — and therefore which candidates exist at all — is decided by the
score. Recorded in three places (`HANDOFF-NEXT.md`, `sentinel/corpus/`, review
§2b) and hit twice today: S1/S2 needed an equal-budget constraint to be
attributable at all, and B1's apparent p@k win could not be separated from a
size effect on a score-ordered pool.

Perturbation: the same weight values reassigned to the same keys in reverse
rank order — sum-preserving, so the perturbed blend is a legal blend.

| | result |
|---|---|
| shipped pool changes under perturbation | **yes** — 4 of 525 fixture candidates, **0.76%** |
| `largest` / `smallest` / `key` pools change | **no** — bit-identical, all three |
| the three score-free pools differ from each other | yes (so they are three arms, not one) |
| overlap of each score-free pool with the shipped pool | 98.3–98.5% |

Both halves of kill criterion 1 were required to fire and both did. Had the
shipped pool *not* moved there would have been no confound to fix; had a
score-free pool moved, the key would not have been score-free.

**The confound is real, and it is about 1%.** That is worth stating plainly,
because "the score participates in generation" reads as though it might be
large. On this fixture it is not. It is large enough to matter for a careful
A/B and small enough that no historical number is likely to be badly wrong
because of it.

*Scope: the 0.76% is measured on the committed 3-cycle fixture, which is the
only place the perturbation was run. The full-replay arms below bound the
practical magnitude independently — the four pools differ in size by at most
0.04%.*

## 2. The cost

| ordering | mean pool | built | ranked@50 | p@10 | p@20 | p@50 |
|---|---:|---:|---:|---:|---:|---:|
| `score` (shipped) | 10,193 | 161 | **58** | 0.2912 | 0.1574 | 0.0759 |
| `largest` (review's proposal) | 10,194 | 161 | **58** | 0.2765 | 0.1515 | 0.0741 |
| **`smallest`** | 10,190 | **162** | **58** | **0.2882** | **0.1544** | **0.0753** |
| `key` | 10,193 | 161 | **58** | 0.2824 | 0.1529 | 0.0747 |

Paired deltas against the shipped ordering:

| | k=10 | k=20 | k=50 |
|---|---|---|---|
| `largest` − score | **−0.0147 [−0.026, −0.003]** | **−0.0059 [−0.012, −0.001]** | −0.0018 [−0.004, +0.000] |
| **`smallest`** − score | −0.0029 [−0.009, +0.000] | −0.0029 [−0.007, +0.000] | −0.0006 [−0.002, +0.000] |
| `key` − score | −0.0088 [−0.021, +0.000] | −0.0044 [−0.010, +0.000] | −0.0012 [−0.003, +0.000] |

**`largest` is the only arm with a loss whose interval excludes zero** — at both
k=10 and k=20. `smallest` and `key` include zero everywhere; by this project's
own rule, **a loss whose interval includes zero is not a loss**, and `smallest`
therefore has no measurable cost at any depth.

`ranked@50` is **58 in every arm**. Kill criterion 3 set a floor of 47 and
nothing came near it: score-freeness costs zero distinct rings surfaced.

## 3. Why `largest` is worse, and it is the mechanism this project keeps meeting

The size baseline, per arm:

| ordering | size p@10 | size p@20 | size p@50 |
|---|---:|---:|---:|
| `score` | 0.0882 | 0.0676 | 0.0488 |
| `largest` | **0.0941** | **0.0721** | **0.0512** |
| `smallest` | 0.0882 | 0.0662 | 0.0494 |
| `key` | 0.0912 | 0.0706 | 0.0506 |

`largest` keeps the biggest representative of every overlapping group, so the
surviving pool skews larger, node count becomes a slightly better predictor, and
the score's own p@k falls. `smallest` keeps the tightest representative, which
is exactly what the Jaccard floor in `is_hit` rewards, and leaves the size
baseline flat.

**This is the same size confound that refuted B1 this morning, arriving by a
third route.** It did not go far enough here to break anything — see §4 — but
the direction is the same one every time.

Per-typology built counts show the same story from the other side. Every
score-free arm gains a **BIPARTITE** ring (5 → 6) that score-ordered
suppression was throwing away, and loses a **RANDOM** ring (17 → 16).
`smallest` alone also gains a GATHER-SCATTER ring, which is where its +1 total
comes from.

## 4. Against the pre-registration

| predicted | observed | |
|---|---|---|
| shipped pool moves under perturbation | yes, 0.76% | hit |
| all three score-free pools bit-identical | yes, exactly | hit |
| candidates/cycle, `largest` vs shipped, within ±5% | +0.01% | hit |
| p@10 under `largest` **falls** | −0.0147, CI excludes zero | hit |
| p@10 under `smallest` rises or holds | holds (−0.0029, CI includes zero) | hit |
| ranked@50 falls 0–15% under score-free keys | falls **0%** | hit, bottom of range |
| **`score − size` under `largest` at risk of losing CI-clarity at k=20/k=50** | **stayed clear at every k** | **MISSED** |
| `score − size` under `smallest`/`key` clear at all k | yes | hit |

Seven of eight hit. **The miss is that a risk I predicted did not materialise** —
I expected `largest`'s size skew to threaten the score's margin over the size
baseline at k=20 and k=50, because that is exactly what happened to B1. It moved
the baseline in the predicted direction (0.0882 → 0.0941 at k=10) but nowhere
near far enough to matter:

| ordering | score − size @10 | @20 | @50 | |
|---|---:|---:|---:|---|
| `score` | +0.2029 | +0.0897 | +0.0271 | clear |
| `largest` | +0.1824 | +0.0794 | +0.0229 | clear |
| `smallest` | +0.2000 | +0.0882 | +0.0259 | clear |
| `key` | +0.1912 | +0.0824 | +0.0241 | clear |

Recorded as a miss in the favourable direction, which is the kind easiest not to
mention. **Kill criterion 2 was evaluated at every reported k**, which is the
defect B1's pre-registration had — there it was written as a k=10 check and the
harness printed "not fired" while the margin had collapsed at k=20 and reversed
at k=50. Applied properly here, it is clear everywhere.

## 5. Recommendation, and what is deliberately not done

**On this evidence `smallest` is shippable**: it removes a documented confound
that has obstructed two experiments in one day, at no measurable cost at any k,
with `ranked@50` unchanged and one more ring built.

**The shipped default has not been changed.** The review is explicit that B3
"should be run as a diagnostic before it is considered as a change", and the
pre-registration states that whether to ship "needs the cost weighed against
work this unblocks, which is a judgement, not a measurement". Flipping the
default would move every ring-level number in the repository, so it is a
decision to take deliberately and re-render behind, not a side effect of an
experiment. `SUPPRESS_SCORE` remains the default in `merge.py` and in
`CandidateGenerator`.

**If it is adopted, adopt `smallest`, not the review's `largest`.** That is the
single most actionable line on this page.

## 6. What this does and does not settle

- It does **not** say by how much any specific past result was wrong. It says
  future scorer A/Bs can be run without the question, and bounds the confound
  at roughly 1% of the pool on the fixture.
- One dataset, one split, one perturbation. The magnitude of the pool shift
  depends on which weights move and by how much; the perturbation is in
  `tests/test_suppression_key.py` so it is reproducible, not because it is
  general.
- The three orderings tested are not the whole family. `smallest` won among
  three; nothing says it is optimal.
