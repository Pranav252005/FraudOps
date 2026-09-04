---
name: payops-experiment
description: The pre-register → run → adjudicate → record loop for any change to sentinel that is meant to move a number. Picks the next experiment off a ranked queue, writes a falsifiable pre-registration with a kill rule before running anything, and appends what was learned to an append-only ledger so the next run starts from a shorter list. Use whenever asked to "improve the model", "make it better", "run the next experiment", or when proposing a change to seeding, expansion, pruning, suppression, scoring, or the split.
---

# The experiment loop

This is how the project gets better across runs. Not by the model changing —
by the **queue getting shorter, the ledger getting longer, and the invariants
getting tighter**. Each pass through this loop must leave at least one of those
three in a better state, or the pass produced nothing.

State lives in two files, both append-only:

- `docs/EXPERIMENT-QUEUE.md` — candidate experiments, ranked, with the funnel
  stage each one attacks and the expected size of the prize.
- `docs/EXPERIMENT-LEDGER.md` — one entry per completed pass: what was
  predicted, what happened, and the rule that came out of it.

## Step 0 — Read the state before proposing anything

```bash
cat docs/EXPERIMENT-QUEUE.md
tail -80 docs/EXPERIMENT-LEDGER.md
ls docs/negative-results/
```

**A proposal that repeats a refuted experiment is the main failure this loop
exists to prevent.** `docs/negative-results/` and the ledger are the memory.
Check both by name before writing a pre-registration. If the idea is already in
there, say so and take the next queue item instead.

## Step 1 — Pick from the queue, by funnel stage

`sentinel/eval/funnel.py` reports recall at four stages:
`seed_reachable → seeded → built → ranked`. **Always attack the stage that is
losing the most rings**, not the stage that is most interesting.

The measured picture as of the last funnel run: seeding loses four typologies
entirely (BIPARTITE / FAN-OUT / RANDOM / STACK generate 0% because the seed rule
requires a pass-through account), and *build* loses ~38% of seeded rings to
dilution rather than to discovery. Ranking is not the binding constraint — the
seed cheat is worth ~2.2× at k=10 against the scorer's 1.3×.

If a queue item attacks `ranked` while `seeded` is still losing four typologies,
it is mis-ranked. Say so and re-rank the queue.

## Step 2 — Pre-register, with a kill rule, before running

Write `prereg/<name>.md` following the shape of the existing ones
(`prereg/label_tax_noise.md` is a good model). It must contain, in this order:

1. **The question**, as one sentence with a subject that can be false.
2. **The metric and its clustering** — which bootstrap unit, and why that unit
   (rule 5). Name it as one of the three permitted `ci_method` values.
3. **The prediction**, as an interval or a direction, written *before* the run.
4. **The kill rule** — the observation that would make you abandon the idea.
   A pre-registration without a kill rule is a plan, not an experiment.
   `docs/CENTREPIECE-INVALIDATED.md` exists because a kill rule fired; that is
   the standard.
5. **The null / falsification check** — what you would expect to see if the
   effect is not real, run *before* interpreting the result.
6. **Cost**, in wall-clock. If it needs a replay, say how many seconds. This
   project has twice called a 20-minute replay "cheap to settle".

Then commit the pre-registration **before** running the experiment. The commit
timestamp is the evidence that the prediction preceded the result.

## Step 3 — Run it, under the invariants

Load the `payops-invariants` skill. In particular:

- If the change touches a score weight, the candidate pool is invalid. Do not
  reuse a cached pool. Regenerate.
- If the change touches `is_hit`, `prune`, or `suppress`, report **containment
  and Jaccard together**. A pruner that raises one by lowering the other has
  not helped.
- Every headline number carries an interval that names its clustering.

## Step 4 — Adjudicate against the kill rule, not against hope

State plainly which of the three happened:

- **Confirmed** — the prediction held, interval excludes the null. Ship it, and
  add the new number to `results/metrics.json` so the literals check can see it.
- **Refuted** — the kill rule fired. Write `docs/negative-results/<name>.md`.
  This is a *result*, not a failure; rule 7 makes it permanent.
- **Underpowered** — the interval spans the decision boundary. Say so. Do not
  report the point estimate as if it decided anything. Record what n would have
  been needed.

## Step 5 — Write the ledger entry, and shorten the queue

Append to `docs/EXPERIMENT-LEDGER.md`:

```markdown
## <date> — <experiment name>

**Predicted:** <the interval or direction from the prereg>
**Observed:** <the measurement, with its interval and clustering>
**Verdict:** confirmed | refuted | underpowered
**Cost:** <wall-clock>
**Rule that came out of it:** <one sentence, or "none">
**Queue changes:** <items removed, items added, items re-ranked>
```

The **rule** line is the part that compounds. If a pass produces a rule, it goes
into `payops-invariants` (as a checklist row) or into
`docs/STANDING-RULES.md` (if it needs mechanising). A rule that lives only in
the ledger will be forgotten; that is what the promotion step is for.

Then edit `docs/EXPERIMENT-QUEUE.md`: strike what was settled, add what the
result opened, and re-rank by funnel stage.

## What "improves every run" actually means here

It does not mean the model's weights change. It means:

1. The **queue** is re-ranked by measured funnel loss, so each pass attacks the
   largest remaining loss rather than the most recently discussed one.
2. The **ledger** and `docs/negative-results/` make a refuted idea permanently
   unrepeatable, so the search space strictly shrinks.
3. Rules promoted out of the ledger into `payops-invariants` mean the next pass
   starts with a stricter definition of "correct", so a class of error is
   retired rather than re-caught.

If a pass ends with the queue unchanged, the ledger unchanged, and no new rule,
report that plainly. A loop that reports progress it did not make is the
failure mode this whole repository is built against.
