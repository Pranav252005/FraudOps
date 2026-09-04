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
