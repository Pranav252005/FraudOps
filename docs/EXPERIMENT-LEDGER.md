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
