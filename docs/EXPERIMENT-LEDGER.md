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
