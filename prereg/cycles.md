# Pre-registration — evaluation cycles (uplift plan item 0.5)

**Written:** 2026-08-31, at commit `63066d1`.
**Status: the cycle-count increase is NOT being run, and this file records why
rather than leaving it undone silently.**

Scope note, because this file mixes two things and the distinction is the whole
point of a `prereg/` directory: **the decision about cycles is pre-registered —
nothing has been run and nothing will be without the restart rule below firing.
The dead-query-group fix discussed further down had already been measured when
this was written**, and the section covering it is explicitly marked as
retrospective.

## The ambiguity this resolves

Item 0.5 reads "more independent evaluation cycles", and
`docs/CENTREPIECE-INVALIDATED.md` promotes it to the live top item on the
strength of the plan's own line: *"the scorer is the bottleneck on performance;
sample size is the bottleneck on knowing anything."* The first clause is now
false. The second still stands, which is what made 0.5 look like the obvious
next spend.

**It cannot be run as written.** `docs/inventory/cycles.md` establishes that
there is no run-to-run randomness anywhere in the measured path:

- the stream is a fixed compiled artefact with no seed;
- the cycle schedule is a deterministic function of tick index;
- `LGBMClassifier(random_state=7)` is **inert** — with bagging and feature
  sampling at their defaults, LightGBM's tree construction never consults the
  RNG (commit `8c17994`, recorded in
  `docs/negative-results/inert-seed-sweep.md`);
- the bootstrap seeds are constants.

Two runs are byte-identical. **There is no "run more cycles" knob**, so the
plan's own Phase 1B test matrix cannot be satisfied: its *Independence* test
("two cycles with different seeds produce different output") fails by
construction, and *Resume* and *Manifest integrity* have nothing to test
because there is no runner and building one would not create data.

## The decision

`n` is raised by **fixing the dead query groups**, not by generating cycles.
Landed in `63066d1`; recorded in
`docs/negative-results/dead-query-groups.md`.

The reasoning, stated before the outcome was known: all 18 unusable training
query groups shared a single cause, and 156 of 321 training positives
(**48.6%**) sat in them contributing zero gradient. Recovering the *use* of
half the training signal was judged a better hour than adding correlated
observations to the evaluation.

### The options that were rejected, and why

| option | rejected because |
|---|---|
| Halve `EVERY` (6 → 3), doubling cycles | Adjacent cycles share a 72-hour window. The added observations are strongly correlated, so the interval narrows without the information to justify it — a **confidently narrower wrong answer**, the exact failure `scripts/eval_ring_unit.py` was written to avoid |
| Raise `EVAL_END` past day 10 | Forbidden by `sentinel/config.py`: days 10–17 are 91% laundering, so "timestamp after day 10" becomes a near-perfect classifier. A property of the generator, not of fraud |
| A second dataset | Elliptic2 cancelled on a schema fact — `docs/negative-results/elliptic2-cancelled.md` |
| Switch the reported unit to the ring | Already done, in `scripts/eval_ring_unit.py`. Costs no compute. Note it **widens** intervals rather than narrowing them (0.0396 → 0.0890 on the shipped blend); it buys correctness, not `n` |

## What was actually written down before the run, and what was not

**This section is scoped carefully, because the rest of this file is a genuine
pre-registration and this part is not.** The cycle decision above is
pre-registered: nothing has been run. The dead-query-group fix, by contrast,
had already been measured by the time this file was written, so anything said
about it here is post-hoc unless it can be pointed at in an earlier artefact.

Two claims can be pointed at, both committed before the re-run finished:

1. **"Train loses 156 of 321 positives … the headline number moves, and it
   moves DOWN."** Written in `ring_time_split.__doc__` and in
   `docs/negative-results/dead-query-groups.md`, both authored before the
   `eval_ranker` arm returned. **Outcome: correct** — supervised p@10
   0.2500 → 0.2111.
2. **"The comparison was confounded in the pointwise model's favour."**
   Inherited from `group_diagnostics.__doc__`, which has said so since before
   this session, and restated in the assertion message added to
   `scripts/eval_ranker.py` before the run. **Outcome: correct in direction** —
   removing the confound moved pointwise (−0.0389 at k=10) and barely moved
   LambdaMART (−0.0111).

**Not predicted, and not claimed as predicted:** that the listwise-vs-pointwise
interval would *cross zero* and thereby fail the item 1.3 pre-registration.
The mechanism was written down; the crossing was not. Reporting it as
anticipated would be exactly the retrofit this repository refuses elsewhere,
and it is the single most consequential result of the change.

Nothing else about the fix was pre-registered. The seed-cheat arm's large
improvement was neither predicted nor explained, and is filed as an open
anomaly in `docs/negative-results/dead-query-groups.md`.

## Stopping rule

There is nothing running, so the stopping rule is a **restart** rule instead.
Cycle generation is reconsidered only if one of these becomes true — and not on
the general feeling that `n` is small:

- a source of genuine independence appears (a second dataset with
  `constructed` provenance, or a stream generator with a real seed);
- someone demonstrates that observations at `EVERY=3` are not materially
  correlated with their neighbours, by measuring the correlation rather than
  assuming it is small;
- a decision turns on an interval whose width is the only thing between it and
  a conclusion, **and** the correlated-observation objection above is addressed
  first.

Absent those, adding cycles is measurement theatre: the interval gets narrower
and no more is known.

## What would count as this decision having been wrong

- The dead-query-group fix having **cost** `n` in effect rather than gained it.
  It did reduce training positives by 156; if the resulting intervals are
  **wider** than the pre-fix ones at the same `k`, then the trade went the wrong
  way. **Measured:** the k=10 supervised interval went [0.1278, 0.3722]
  (width 0.2444) → [0.1111, 0.3167] (width 0.2056). It narrowed. The trade
  holds on this criterion.
- Someone showing that correlated cycles at `EVERY=3` would still have produced
  a **correct** interval — i.e. that the cluster bootstrap over cycles already
  absorbs the correlation adjacent windows introduce. That would make option 1
  cheap and legitimate, and would make this decision an over-caution.

## What this file does NOT license

It does not license quoting any interval as though `n` were adequate. `n` is
**18 held-out cycles** for `eval_oracle` / `eval_ranker`, **17** for
`eval_phase4`, and **67 distinct rings / 144 ring-trials** for the ring-unit
metric. Those numbers are small and the intervals are correspondingly wide.
Fixing the query groups did not change that and was never expected to.
