# Phase 0.4 — Inventory of the evaluation-cycle machinery

**Produced:** 2026-08-31. **Method:** read of `sentinel/config.py`,
`scripts/eval_oracle.py`, `scripts/eval_ranker.py`, `scripts/eval_phase4.py`,
`sentinel/eval/bootstrap.py`, plus wall-clock read from
`data/eval_oracle_postblendfix.log` and `data/eval_ranker.json`.

## What a "cycle" is

A **generation cycle** is one invocation of `CandidateGenerator.generate()` on
one replay window. It is the unit of three different things, deliberately:
the p@k denominator, the LightGBM query group, and the bootstrap resampling
unit (`sentinel/eval/bootstrap.py` docstring; `scripts/eval_ranker._groups`).

## How a cycle is invoked

Not individually. Cycles are not addressable objects — they fall out of a
whole-window replay:

```python
# scripts/eval_oracle.py:215-234 (collect_pool)
for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
    graph.add_batch(b)
    if i % EVERY or graph.now < WINDOW_MINUTES // 2:
        continue          # <- only every 6th tick becomes a cycle
    ...
    cands = gen.generate(b, seed_override=seed_override)
```

The cycle schedule is fully determined by four constants in
`sentinel/config.py`, none of them a parameter:

| constant | value | effect |
|---|---|---|
| `TICK_MINUTES` | 60 | replay granularity |
| `EVERY` (in `eval_oracle.py`) | 6 | one cycle per 6 ticks = per 360 min |
| `WINDOW_MINUTES` | 4320 (72 h) | warm-up gate: no cycle before `graph.now >= 2160` |
| `EVAL_END` | 14400 (day 10) | hard stop |

**There is no cycle-level entry point and no cycle-level seed.**

## How the seed is set — and why "more cycles" cannot come from re-seeding

**There is no run-to-run randomness to seed.** Every stochastic-looking thing
in the measured path is pinned to a constant:

| site | seed | varies? |
|---|---|---|
| `Stream` | none — `data/stream/edges.parquet` is a fixed compiled artefact | no |
| cycle schedule | deterministic function of tick index | no |
| `LGBMClassifier(random_state=7)` | 7 | **no — the RNG is never consulted.** See commit `8c17994`: with `subsample` and `colsample_bytree` both at their default 1.0, LightGBM's histogram tree construction is deterministic and `random_state` does nothing. Two seeds give `np.array_equal` predictions |
| `bootstrap_ci` / `paired_bootstrap_delta` | `seed=7` | no |
| `random.Random(c.key).random()` (random baseline) | per-candidate key | no |
| `SimulatedAnalyst(seed=7)` | 7 | no — but this one *is* live (it is `random.Random`, not LightGBM) |

**This is the crux of the "0.5 more cycles" ambiguity and it must go to the
user before `prereg/cycles.md` is written.** Re-running the pipeline with a
different seed produces **byte-identical output**. There is no "run more
cycles" knob. The only ways to increase `n` are structural, and each buys a
different thing:

1. **Lower `EVERY`** (6 → 3 doubles the cycle count). Cheapest. But adjacent
   cycles share a 72 h window, so the added observations are strongly
   correlated — the interval would narrow without the information to justify
   it. This is the option most likely to produce a *confidently narrower wrong
   answer*, which is the exact failure `scripts/eval_ring_unit.py`'s docstring
   already names.
2. **Switch the resampling unit to the ring** (`scripts/eval_ring_unit.py`
   already does this): 145 ring-trials from 68 distinct rings against the
   cycle unit's 18. Costs no compute at all. Note it *widens* the interval
   (0.0890 ring-clustered vs 0.0396 cycle-clustered on the shipped blend) —
   it buys correctness, not narrowness.
3. **Fix the 18 dead query groups** (see `docs/inventory/query_groups.md`) —
   recovers 156 of 321 training positives.
4. **A second dataset.** Elliptic2 was cancelled on a schema fact (`375310a`).
5. **Raise `EVAL_END`** past day 10. Forbidden: `sentinel/config.py` documents
   that days 10–17 are 91% laundering, so "timestamp after day 10" becomes a
   near-perfect classifier. Not an option.

## Where output lands, and whether it is append-only

**Overwritten, not append-only.** Every eval script ends with a whole-file
`write_text` / `np.savez` to a fixed path:

| script | output | mode |
|---|---|---|
| `scripts/eval_oracle.py` | `data/eval_oracle.json` | **overwrite** |
| `scripts/eval_ranker.py` | `data/eval_ranker.json`, `data/ranker_pool.npz` | **overwrite** |
| `scripts/eval_phase4.py` | `data/eval_phase4.json` | **overwrite** |
| `scripts/eval_ring_unit.py` | `data/eval_ring_unit.json` | **overwrite** |

Prior results survive only by **manual** rename to `*.bak`
(`data/eval_oracle.PREBLENDFIX.json.bak`,
`data/eval_ranker.MIXEDPROVENANCE.json.bak`, `data/ranker_pool.PREFIX.npz.bak`).
That convention is honoured by hand and enforced by nothing.

**There is no checkpointing and no manifest.** An interrupted run loses
everything and restarts from tick 0.

## Measured wall-clock

From `data/eval_oracle_postblendfix.log` (the run that produced the current
`data/eval_oracle.json`, 2026-08-31 11:47), **not estimated**:

| stage | wall-clock | per cycle |
|---|---|---|
| `collect_pool(seed_perfect=False)` — 34 cycles, 346,554 candidates | **393 s** (log line 8) | **11.6 s** |
| `collect_pool(seed_perfect=True)` — 34 cycles, 365,011 candidates | **417 s** (log line 86) | **12.3 s** |
| whole `scripts/eval_oracle.py` | ~15 min (both arms + 2 fits + bootstraps) | — |
| whole `scripts/eval_ranker.py` | **445 s** (`data/eval_ranker.json`, `"seconds": 444.86`) | — |

## The cycle count — the 17 does not verify as a single number

**There are three different cycle counts in this repo and the plan's "17" is
only one of them.**

| count | what it is | source |
|---|---|---|
| **34** | total generation cycles in the replay window (ticks 2220 … 14100, step 360) | `data/eval_oracle_postblendfix.log:8,86`; `data/eval_phase4.json` `"runs": 34`; `data/eval_ranker.json` `train_group_diagnostics.n_groups = 34` |
| **18** | held-out evaluation cycles for `eval_oracle` and `eval_ranker` (`split_t = 7980`) | `data/eval_oracle.json` `cycles: 18`; `data/eval_ranker.json` `n_cycles: 18`; every `n_units: 18` in their bootstrap blocks |
| **17** | held-out evaluation cycles for `eval_phase4` (`split_t = 8340`) | `data/eval_phase4.json`, `n_units: 17` throughout |

The plan's `n = 17` therefore refers to the **Phase 4 simulated-verdict run**,
not to the centrepiece. The centrepiece (`eval_oracle` / `eval_ranker`) runs at
**n = 18**. The two differ because they split at different ticks.

`docs/CENTREPIECE-INVALIDATED.md` states the pre-registration as *"I expect the
CI at n=17 cycles to still include zero"* while the LambdaMART result it is
judging is measured at n=18. The pre-registration's `n` and the measurement's
`n` are not the same number. **This is a discrepancy, it is recorded here
rather than silently corrected, and the pre-registered conclusion is not
affected by it** (the intervals include zero at k=10 and k=20 either way).

Per the plan's pre-interpreted outcome for a non-17 count: the figure is
corrected in this document and flagged to the user rather than quietly adopted.
