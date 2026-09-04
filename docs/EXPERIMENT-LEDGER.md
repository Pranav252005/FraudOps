# Experiment ledger

Append-only. One entry per completed pass through the loop in
`.claude/skills/payops-experiment/SKILL.md`. Never edit an entry in place —
a correction is a new entry that names the one it corrects.

The **rule** line is the part that compounds: a rule that comes out of a pass
gets promoted into `.claude/skills/payops-invariants/SKILL.md` or, if it needs
mechanising, into `docs/STANDING-RULES.md`. A rule that stays only here will be
forgotten, which is the whole reason for the promotion step.

Entry template:

```markdown
## <YYYY-MM-DD> — <experiment name>

**Predicted:** <interval or direction, copied from the prereg, before the run>
**Observed:** <measurement, with interval and named clustering>
**Verdict:** confirmed | refuted | underpowered
**Cost:** <wall-clock>
**Rule that came out of it:** <one sentence, or "none">
**Promoted to:** <invariants | standing-rules | not promoted>
**Queue changes:** <struck | added | re-ranked>
```

---

## 2026-09-04 — loop established (no experiment run)

**Predicted:** n/a — this pass created the loop rather than running through it.
**Observed:** Review of candidate construction, leakage control and evaluation
methodology recorded in [`graph-review/2026-09-04.md`](graph-review/2026-09-04.md).
Twelve experiments seeded into [`EXPERIMENT-QUEUE.md`](EXPERIMENT-QUEUE.md),
ranked by funnel stage.
**Verdict:** n/a
**Cost:** one session, no replay.
**Rule that came out of it:** the ground-truth label is reachable from the
detect path (`PairAgg.laundering` rides on every edge handed to
`motifs.detect` and `features.build`); nothing reads it and nothing enforces
that.
**Promoted to:** invariants, as proposed rule 8 — **not yet mechanised**, and
recorded as proposed rather than counted among the seven enforced rules.
**Queue changes:** queue created; L1 ranked first because a leakage question
blocks the credibility of every number above it.

## 2026-09-04 — L1: the ground-truth label is made unreachable from the detect path

**Predicted:** the review recorded this as an *unguarded surface*, not an
active leak — it grepped and found nothing under `sentinel/detect`,
`sentinel/learn` or `sentinel/report` reading `PairAgg.laundering`. So the
pre-registered expectation was that both halves would pass on first run, and
that a passing guard would therefore prove nothing unless each half carried a
negative control demonstrating it can fail.

**Observed:** both halves pass, and both controls fire.

- Static: no `.laundering` reference on any measured entry point's import
  closure outside `sentinel/graph/window.py`; no `laundering` **or**
  `is_laundering` anywhere in `sentinel/detect` or `sentinel/learn`. The
  detector was run against `tests/test_phase1.py`, which does read the
  counter, and flagged it — so the walk is not passing vacuously.
- Runtime: the fixture's labels randomised under two seeds, and the pipeline
  fingerprint (candidate keys, member sets, every feature, scores, rank order,
  generator statistics) is unchanged at `4ea7ba5e…`. Planting a feature
  computed from `agg.laundering` moves it, so the poison test can fail.

**Verdict:** confirmed — the surface is closed, and it was closed rather than
merely observed to be quiet.

**Cost:** one session, no replay. The poison gate itself is a few seconds.

**Rule that came out of it:** two guards are needed, not one, and they fail
differently on purpose. A static walk answers "did anyone write the name" and
is defeated by a computed `getattr`, a runtime alias, or a read through
`asdict()`. A poison test answers "does the answer depend on the truth", which
is the property actually wanted, and no rename defeats it. Keep both: the
static half fails on a diff with a line number; the runtime half cannot be
argued around.

**Promoted to:** standing-rules (rule 8, with its own section explaining that
it is the one rule added by review rather than by a failure) **and** invariants
(rule 8 restated from *proposed* to enforced). Also wired as the
`label_poison` CI gate so it runs outside pytest.

**Known limit, recorded not discovered later:** the poison test only covers
what the committed fixture reaches. A label read inside the re-ranker, the case
layer or the narrative path would not move its fingerprint; those are covered
by the static half alone. The cleaner shape — `subgraph_edges` yielding a
label-free view so the counter cannot travel at all — was **not** done, because
it allocates per edge on a hot path. Left open rather than dropped.

**Queue changes:** L1 struck.

## 2026-09-04 — M1: the `is_hit` threshold sensitivity band

**Predicted:** (1) p@10 at the loosest cell 1.2x-2.0x the shipped cell;
(2) at the tightest, 0.4x-0.8x; (3) ring recall monotone in both thresholds;
(4) `score - size` positive in all nine cells; (5) its interval excluding zero
in **at least seven of nine**; (6) the shipped cell reproducing
`data/eval_phase2.json`. I also pre-registered the bad news I expected — the
tightest cell going underpowered, making the honest claim "holds in seven or
eight of nine".

**Observed:** 34 cycles, 259 rings, cycle-clustered paired bootstrap.
`score - size` positive in **9/9** cells and CI-clear in **9/9** at k=10, and
the same at k=20 — **18/18 intervals exclude zero**. Narrowest margin, at the
tightest thresholds, +0.1382 [+0.0794, +0.1971]. p@10 spans 0.2118 to 0.3382
across the grid, a factor of 1.60. Shipped cell reproduces the stored headline
to the last digit.

Prediction 1 **missed**: the loosest cell came in at 1.16x, just under the
predicted range. The band is narrower than I expected, which is the more
favourable direction and therefore the one a missed prediction is easiest to
quietly not mention. It is recorded.

The pre-registered bad news **did not arrive**. The tightest cell is CI-clear,
not underpowered. The pessimistic prediction was wrong in the good direction.

**Verdict:** confirmed — and stronger than pre-registered.

**Cost:** 376s of replay, one pass, nine cells.

**Rule that came out of it:** **the two thresholds are not independent knobs.**
Jaccard is bounded above by containment (`|A∪R| ≥ |R|`), so a Jaccard floor at
0.4 already implies containment ≥ 0.4 and `hit_share` is shadowed above that
point — the (0.4, 0.4) and (0.5, 0.4) rows are identical to the last digit.
Moving `min_jaccard` across the grid moves p@10 by 0.1206; moving `hit_share`
moves it by at most 0.0176. Anyone reasoning about these as two dials is
reasoning about roughly one.

**Promoted to:** not promoted as a rule. It is a property of the metric rather
than a practice, and it is recorded in `docs/THRESHOLD-BAND.md` where the metric
is defined.

**Queue changes:** M1 struck. Thresholds unchanged — `MIN_JACCARD` stays 0.3,
and the 0.2 column is published rather than taken.

## 2026-09-04 — S1/S2: the second seed predicate, and the premise it rested on

**Predicted:** the prereg first *corrected the premise* — the queue had ranked
this on a stale `funnel.py` docstring claiming four typologies "generate 0%",
which `HANDOFF.md` §5b had already refuted on 2026-08-26. Seeding is the
smallest of the three funnel losses. Then: addressable rings 5-20; S1 seeded
gain +0 to +8; built +0 to +4; ranked +0 to +2; p@10 CI including zero; **S1
indistinguishable from S2**; score staying CI-clear over size in every arm.

**Observed:** ceiling first, per kill criterion 1 — of 29 unseeded rings, **22
were never touched in any active cycle** and are unreachable by any
touched-based rule, leaving S1 an addressable set of **7 rings**. All four arms
spent an identical 35,543 extra seeds.

**S1 and S2 were bit-identical at every k** (delta +0.0000, CI [+0.000,+0.000]).
Measured mechanism: the cleanliness factor is exactly 1.0 for **98.6%** of the
real non-pass-through pool, so `cleanliness x width` collapses to width, and the
tiebreak makes the top-B selection exactly degree ordering. Only 83 accounts
saturate against a budget of 1,585.

Built rose 161 to 175 (+14, against the random null's +4, so ~+10 is
attributable to the criterion) — but **ranked@50 was 58 in all four arms**.
BIPARTITE and STACK, the two build-destroyed typologies, gained nothing; the
gain is FAN-IN and FAN-OUT, which is what degree burst should find.

**Verdict:** S1 **refuted** as a distinct predicate. S2 confirmed but not worth
shipping.

**Cost:** 1,568 s, four arms, one replay.

**Rule that came out of it:** **a middle-of-funnel gain that does not reach the
output is not a product improvement.** Built +14 with ranked +0 is a true
statement whose misleading half is the one worth quoting. Any future generation
change must report `ranked` beside `built` or it is reporting the flattering
half.

Second rule, from the miss: I under-predicted built (+14 against a predicted
+0 to +4) because I reasoned only about newly-seeded rings and forgot that extra
seeds also produce extra candidates around rings that were **already** seeded.
Most of the built gain was not from newly-reachable rings at all.

**Promoted to:** not promoted as an invariant. Recorded in
`docs/SEED-PREDICATE-FINDINGS.md`, and the stale-docstring correction is now
inline in `sentinel/eval/funnel.py` so the next reader cannot repeat it.

**Queue changes:** S1 and S2 struck. Neither shipped. The evidence points back
at B1, where `PHASE2-SEED-CHEAT-FINDINGS.md` §H2 already said it pointed.

## 2026-09-04 — B1: shape-directed fragment linking

**Predicted:** built-recall +2 to +8 rings, BIPARTITE and STACK the
beneficiaries, p@k **not** moving (a merge makes a candidate bigger, not
better), `link` beating `link_random` on built, score staying CI-clear over
size, pool growth under 10%.

**Observed:** 34 cycles, 1,788 merges, 0.52% pool growth, 0.13 s/cycle.

- **Built is 161 in all three arms.** Zero rings newly reached. Kill criterion 1
  fired — though with the null also at 161 the comparison was on a saturated
  metric and could not have distinguished much.
- A large, **unpredicted** ranking gain: p@20 0.1574 → 0.2279, p@50 0.0759 →
  0.1288, CI-clear against both shipped and the null.
- **The size baseline nearly tripled with it** (p@50 0.0488 → 0.1341), and
  `score − size` under `link` collapses to CI-clear at k=10 only, includes zero
  at k=20, and goes **negative** at k=50. Bug #8's pattern.
- **Distinct rings ranked fell 58 → 55.** More top-50 slots hold a hit,
  covering fewer distinct rings.
- Containment of merged candidates **doubles** (0.785 vs 0.385 for the best
  unmerged), so the mechanism does assemble — kill criterion 4 fired on Jaccard
  (0.2099 vs 0.2235) but its stated interpretation, "dilutes rather than
  assembles", is refuted by the containment column.

**Verdict:** refuted as scoped. Four of seven predictions missed, and the two
central ones missed in **opposite** directions — no generation gain, and a large
ranking gain that then failed its own baseline check. Not shipped; `link.py`
stays unused by `CandidateGenerator`.

**Cost:** 480 s, three arms, one generation per cycle.

**Rule that came out of it, and it is the important one:** **a kill criterion
that references the size baseline must quantify over every reported k.** Mine
was written as a k=10 check, so the harness printed "not fired" while the margin
had collapsed at k=20 and gone negative at k=50. A criterion narrower than the
rule it encodes will keep returning comfortable answers. Fixed in
`scripts/eval_fragment_link.py`, which now evaluates it at every k.

Second rule, carried over and now confirmed twice in one day: report the
product-relevant counterpart beside the flattering one. S1 gave "+14 built, +0
ranked"; B1 gives "p@50 up 70%, distinct rings down 58→55". Both are true
statements whose first half is the misleading one.

**Promoted to:** not an invariant yet. The size-baseline-at-every-k rule belongs
in `docs/STANDING-RULES.md` rule 2 when someone mechanises it; recorded here as
proposed.

**Queue changes:** B1 struck. A **new** hypothesis is generated and explicitly
**not** claimed: linking may be a *ranking* intervention rather than a
generation one. That is post-hoc, needs its own pre-registration and a
size-stratified baseline the size effect cannot win, and B3 (score-free
suppression) should precede it.

## 2026-09-04 — B3: a score-free suppression key

**Predicted:** the shipped pool moves under a weight perturbation and all three
score-free pools do not; candidates/cycle within ±5%; p@10 **falls** under
`largest` and holds under `smallest`; `ranked@50` falls 0-15%; and — the risk
named in advance — **`score − size` under `largest` at risk of losing CI-clarity
at k=20 and k=50**, because `largest` is a size-ordered key and that is exactly
what refuted B1 the same morning.

**Observed:** the property holds in **both** directions. The shipped pool shifts
by 4 of 525 fixture candidates (**0.76%**); `largest`, `smallest` and `key` are
each bit-identical under the same perturbation, and differ from one another, so
they are genuinely three arms.

Cost, 34 cycles: `ranked@50` is **58 in every arm**. `smallest` is
−0.0029 [−0.009, +0.000] at k=10 and includes zero at every k, with built
161 → **162**. `largest` is the only arm with a CI-clear loss
(−0.0147 [−0.026, −0.003] at k=10, −0.0059 [−0.012, −0.001] at k=20).

**Verdict:** confirmed. The confound is real, the fix works, and the price is
approximately nothing for the right key.

**Cost:** 618 s for four arms — one generation per cycle, four suppressions of
the same unsuppressed pool, so the arms are paired exactly rather than by
arrangement.

**Rule that came out of it:** **when a review proposes one member of a family,
test the family.** The review named `largest` ("largest member set, tie-broken
on canonical_key"). It is the worst of the three tested and the only one that
costs anything measurable. Adopting it on recommendation would have taken the
only avoidable loss available. The mechanism is the one this project keeps
meeting: `largest` skews the surviving pool bigger, which lifts the size
baseline (0.0882 → 0.0941 at k=10); `smallest` keeps the tightest
representative, which is what the Jaccard floor rewards, and leaves the baseline
flat.

**Miss:** the risk I pre-registered did not materialise. `largest` moved the
size baseline in the predicted direction but nowhere near far enough to break
`score − size`, which stays CI-clear at every k in every arm. A miss in the
favourable direction, recorded because that is the kind easiest not to mention.

Kill criterion 2 was evaluated **at every reported k** — the defect in B1's
pre-registration, applied rather than merely noted.

**Promoted to:** not an invariant. `SUPPRESS_SCORE` remains the shipped default;
flipping it would move every ring-level number in the repository and is a
deliberate decision to be taken and re-rendered behind, not a side effect of an
experiment.

**Queue changes:** B3 struck. **If adopted, adopt `smallest`, not `largest`.**
B3 was the blocker named at the end of the B1 and S1/S2 entries; with it
measured, a scorer A/B can now be run on a pool the scorer did not help choose.

## 2026-09-05 — P0: widening the seed source

**Predicted:** newly seeded +15 to +22; built +8 to +20; **ranked@50 +0 to +6**;
p@10 paired CI **including zero**; `score − size` CI-clear at k=10/20/50; ρ(score,
size) unchanged; cost ≈4.3×; dedup rising materially so cost is sublinear in
seeds.

**Observed**, 34 cycles, `lb1` reproducing the shipped baseline exactly
(230/161/58, p@10 0.2912) so the deviation policy is satisfied:

- seeded **230 → 258** of 259; built **161 → 218** (+35%); **every typology
  gained**, including BIPARTITE 5 → 16 and STACK 9 → 14 — the two that S1 and
  B1 both targeted and neither moved;
- p@10 **0.2912 → 0.5500**, +0.2588 [+0.182, +0.335]; p@20 +0.2426
  [+0.199, +0.290]; p@50 +0.1076 [+0.084, +0.132]. All CI-clear;
- `score − size` clear at every k and **widening** (+0.2029 → +0.5324 at k=10);
  ρ(score, size) **falls** 0.2714 → 0.1987. Not a size artifact;
- **`ranked@50` 58 → 61**, and build→rank retention **falls** 0.360 → 0.280;
- cost **4.85×**; dedup did **not** absorb the seeds (65,283 candidates from
  68,235), so cost is linear.

**Verdict:** confirmed, and the first change in two days to move a headline
number — but the output moved by three rings.

**Cost:** 2,547 s for two arms.

**Rule that came out of it:** **p@k and distinct-rings-surfaced can move by
very different amounts, and the ratio is the tell.** Hit slots per distinct ring
in the top 50 went 2.2 → 5.1: the queue became twice as redundant, so most of
the precision gain is the same rings occupying more slots. Any future p@k claim
must be quoted beside distinct rings ranked, exactly as rule 2 requires the size
baseline.

Second rule: **an argument named in a pre-registration and then dismissed as
"not evidence" is still a prediction, and should be forecast from.** The prereg
distinguished S1's extra seeds (same hour) from P0's (hours never sampled), then
predicted the S1 outcome anyway. The distinction was the whole result.

**Miss:** four of eight predictions missed, nearly all in the favourable
direction. Only `ranked@50` — the number the prereg said mattered — landed
inside its range.

**Promoted to:** not an invariant. `SEED_LOOKBACK_TICKS` stays 1; shipping needs
the `observe()` guard (queued as P0b) because the parameter is inert without it
and fails silently.

**Queue changes:** P0 struck. P0b (observe guard) and P0c (lb24 full sweep)
added. **P0 moves the bottleneck: build loss falls from 26.64 to roughly 12
points, so essentially all remaining loss is ranking — where the oracle says a
supervised model on current features buys 1.12×. The feature problem is now the
whole problem.**
