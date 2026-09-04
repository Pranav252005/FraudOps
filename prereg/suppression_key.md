# Pre-registration — B3, a score-free suppression key

**Written 2026-09-04, before `suppress()` gained a key parameter and before
anything was measured.** Item **B3** in
[`docs/EXPERIMENT-QUEUE.md`](../docs/EXPERIMENT-QUEUE.md).

## The problem, which is already documented in three places

`sentinel/detect/merge.py::suppress` is greedy non-maximum suppression
**ordered by score**, run inside `generate()`. So when several overlapping views
of one neighbourhood compete, **the score decides which one exists as a
candidate at all** — not merely where it ranks.

- `docs/HANDOFF-NEXT.md` §"The methodological finding": *"any change to the
  weights invalidates the candidate set, not just the ranking. A scorer
  experiment that reuses a cached pool is measuring a fixed-candidate-set
  counterfactual, not the deployed system."*
- `sentinel/corpus/__init__.py`: *"A known hole … the score decides which one
  survives to be a candidate at all. Changing the blend weights therefore
  changes the candidate SET, not only its order — measurably."*
- `docs/graph-review/2026-09-04.md` §2b: *"this makes every scorer A/B
  structurally confounded."*

Two experiments hit it today. S1/S2 could only be attributed by holding the
seed budget equal; B1's apparent p@k win turned out to be mostly a size effect
that a score-ordered pool could not separate from a scoring effect.

## What is actually being tested, and it is not p@k

**The point of B3 is a property, not a metric.** The claim to falsify:

> Under a score-free suppression key, the candidate **set** is invariant to the
> blend weights. Under the shipped score-ordered key, it is not.

That is mechanically checkable and it is checked **first**, on the committed
fixture, in seconds — no replay needed. Perturb `features.WEIGHTS`, regenerate,
and compare the emitted member sets.

**Both halves must fire or the experiment is void.** If the shipped key's pool
does *not* move under perturbation, the confound does not exist in practice and
B3 is unnecessary; that is a legitimate and reportable outcome. If a score-free
key's pool *does* move, the key is not score-free and the implementation is
wrong.

## Arms

The review proposes one key — "largest member set, tie-broken on
`canonical_key`". Three are tested, because **"score-free" is a family and
picking one member of it without measuring is exactly the unjustified-constant
problem this repository keeps a catalogue for.**

| arm | NMS ordering | |
|---|---|---|
| `score` | `-score` | shipped; must reproduce the headline exactly |
| `largest` | `(-size, canonical_key)` | the review's proposal |
| `smallest` | `(size, canonical_key)` | keeps the tightest representative |
| `key` | `canonical_key` | no structural preference at all |

**A risk worth naming in advance: `largest` is a size-ordered key.** It keeps
the biggest representative of every overlapping group, which is a size-directed
choice made *inside* generation. B1 was refuted this morning because merged
candidates were bigger and better and the size baseline nearly tripled with
them. `largest` could do the same thing by a different route, and `smallest` and
`key` exist so that outcome is separable from "score-free" as such.

All four arms run over **one replay**, from the same graph state each cycle, so
every comparison is paired.

## Pre-registered expectations

| quantity | prediction |
|---|---|
| **invariance: shipped pool moves under weight perturbation** | **yes** — it is documented as measurable, and this is the negative control |
| **invariance: all three score-free pools are bit-identical under perturbation** | **yes**, exactly. Not "nearly" |
| candidates per cycle, `largest` vs shipped | within ±5% |
| p@10 under `largest` | **falls** — bigger representatives mean lower Jaccard against a ring |
| p@10 under `smallest` | **rises or holds** |
| ranked@50 under any score-free key | **falls** from 58, by 0–15% |
| `score − size` under `largest`, at k=20 and k=50 | **at risk of losing CI-clarity** — this is the B1 pattern and it is predicted, not discovered |
| `score − size` under `smallest` / `key` | stays CI-clear at all three k |

**I expect the headline to move down, and that is the point rather than a
problem.** The current numbers are produced by a pool the scorer helped choose;
a lower number on a pool the scorer did not touch is a *more interpretable*
number, and the two are not comparable as "better" and "worse".

## Kill criteria

1. **The invariance property fails in either direction.** Either the shipped
   pool does not move under perturbation (no confound to fix — report that and
   stop), or a score-free pool does move (the key is not score-free — fix the
   implementation before reading any metric). **In both cases the p@k table is
   not reported.**

2. **`score − size` loses CI-clarity at ANY reported k under a candidate key.**
   Applied at k=10, k=20 **and** k=50. This is the criterion I wrote too
   narrowly for B1 — as a k=10 check — so the harness printed "not fired" while
   the margin had collapsed at k=20 and reversed at k=50. Bug #8's rule is not a
   k=10 rule. Any arm that fails this is diagnostic-only and unshippable
   regardless of what it does for interpretability.

3. **ranked@50 falls below 47** (a 20% loss from 58) under every score-free arm.
   Then interpretability is being bought at a price the product cannot pay, and
   B3 is reported as a *diagnostic only* — the confound is real, quantified, and
   the fix is too expensive. That is still a useful result and it is stated in
   advance so it cannot be re-framed as a win later.

4. **Candidate count more than doubles** under any arm. Suppression is not
   suppressing and the arm is broken, not different.

## What this experiment cannot settle

- **Whether to ship it.** The review is explicit that B3 "should be run as a
  diagnostic before it is considered as a change", and nothing here changes the
  shipped default. A shipping decision needs the cost in §Kill-criterion-3 to be
  weighed against work this unblocks, which is a judgement, not a measurement.
- **The size of the confound on any *specific* past result.** Measuring that a
  pool moves does not say by how much any given historical number was wrong. It
  says future scorer A/Bs can be run without the question.
- **One dataset, one split, one perturbation.** The magnitude of the pool shift
  depends on which weights are perturbed and by how much; the perturbation used
  is recorded in the harness so it is reproducible, not so it is general.
