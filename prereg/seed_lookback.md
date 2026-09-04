# Pre-registration — P0, widening the seed source

**Written 2026-09-04, before `seed_lookback_ticks` existed.** Phase **P0** of
[`docs/GRAPH-PRIOR-ART-PLAN.md`](../docs/GRAPH-PRIOR-ART-PLAN.md) §6, whose
ranges were committed in `c59440e` **before any of this was implemented**;
this file is the full protocol, and it does not soften them.

## The gap, already verified

`sentinel/detect/candidates.py::seeds` builds `touched` from `batch.src` /
`batch.dst` — **one tick, one hour**. `WINDOW_MINUTES` is 4320 and cycles fire
every 6 ticks. So the generator expands into a 72-hour graph while choosing
seeds from one hour of it, and five of every six ticks are never sampled.

Measured over `data/stream` with the evals' own `active_rings` semantics
(reproduces their 259 exactly):

| | rings |
|---|---:|
| active | 259 |
| touched in the 1h seed tick | 237 |
| touched **and** pass-through (what the funnel calls "seeded") | 230 |
| **reachable only by widening the seed source** | **22** |
| unreachable even from the whole window | **0** |

## The arms, and why 72 is not one of them

[SPIKE, cost only — no outcome measured] Seed counts at cycle 36 of the real
stream:

| lookback | hours | touched | pass-through seeds | × shipped |
|---:|---:|---:|---:|---:|
| 1 | 1 | 28,565 | 15,854 | 1.00 |
| 6 | 6 | 139,502 | 68,235 | **4.30** |
| 24 | 24 | 290,262 | 117,159 | **7.39** |
| 72 | 72 | 340,478 | 120,502 | 7.60 |

**Lookback 72 is dropped: it buys 2.9% more seeds than 24 for another 48 hours
of history.** Saturation is measured, not assumed — by 24 ticks `touched` is
already 85% of every node in the window.

Three arms, **one replay**, four generators over one shared graph, `observe()`
called on every tick so each arm sees the same history:

| arm | seed source |
|---|---|
| `lb1` | the current tick — **shipped, must reproduce the headline exactly** |
| `lb6` | last 6 ticks — time-lossless: no tick is ever unsampled, since cycles are 6 apart |
| `lb24` | last 24 ticks |

## Pre-registered expectations

Copied from `c59440e` and made specific.

| quantity | prediction |
|---|---|
| rings newly seeded at `lb6` | **+15 to +22** of the 22 shown reachable |
| built at `lb6` | **+8 to +20** |
| **ranked@50** at any lookback | **+0 to +6** |
| p@10, `lb6` − `lb1`, paired CI | **includes zero** |
| `score − size` at k=10, 20, 50 | **stays CI-clear in every arm** |
| Spearman ρ(score, node count) | **essentially unchanged** — the scorer is untouched; only which candidates exist changes |
| cycle cost | ~4.3× at `lb6`, ~7.4× at `lb24`, unless dedup absorbs it |
| candidate dedup rate | **rises materially above the 9-in-57,288 measured at lookback 1** — adjacent hours cover overlapping neighbourhoods. If it does, cost is sublinear in seeds |

**The ranked@50 range is deliberately low and it is the number that matters.**
S1 added 10% more seeds this morning and returned **+14 built and +0 ranked**.
P0 is the same *shape* of intervention — more seeds — and the base rate says it
produces build-stage gains that never reach the output. The difference is that
S1's extra seeds came from the same sampled hour, while these come from hours
that are currently never looked at, covering 22 rings that cannot be reached at
all today. **That is an argument, not evidence.**

## Kill criteria

1. **Newly-seeded rings < 10 at `lb6`.** The mechanism did not do what the
   spike says it must. **Stop and debug the harness before reading any p@k** —
   a metric table computed over a mechanism that did not fire is noise.

2. **`ranked@50` does not rise by ≥3 rings at any lookback.** Then P0 is a
   build-stage-only gain and **must be reported as "+N built, +0 ranked" with
   the S1 precedent named in the same sentence** — not as a recall improvement.
   This is the outcome I consider most likely.

3. **`score − size` loses CI-clarity at k=10, 20 *or* 50 in any arm.** That arm
   is unshippable regardless of recall. Quantified over every reported k,
   because a k=10-only check missed a reversal in B1 today.

4. **Spearman |ρ(score, size)| > 0.5 in any arm.** Size-confounded, and failed
   regardless of p@k. Reported for the shipped arm too, so the baseline value
   is known rather than assumed.

5. **`lb6` cycle cost exceeds 10× shipped.** The linear cost model is wrong and
   the sweep must be re-scoped before `lb24` is attempted.

## What this cannot settle

- **Whether to ship it.** A 4.3× generation cost for a build-stage gain is a
  trade, and the trade depends on kill criterion 2's answer.
- **Why the 22 rings are unsampled.** Widening the source recovers them; it does
  not explain whether their timing is a property of AMLworld's generator or of
  real laundering. One dataset.
- **Anything about lookback > 24.** Measured to saturate; not tested.

## Deviation policy

`lb1` must reproduce `data/eval_phase2.json` exactly. If it does not, the
harness has changed the shipped path and **the run is void** — no arm is
readable against a baseline that is not the baseline.
