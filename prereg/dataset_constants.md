# Pre-registration — deriving the per-split constants

**Written 2026-09-05, before `scripts/derive_dataset_constants.py` existed and
before any per-day statistic of LI-Small or HI-Medium was computed.**

## Why this needs a pre-registration at all

`sentinel/data/datasets.py` refuses to evaluate on a split whose
`eval_end_day` and `structural_recall_ceiling` have never been derived, and its
docstring says why:

> `EVAL_END_DAY` is the leak boundary… Carrying the number 10 onto a different
> split either leaks (if the new split's tail turns bad earlier) or silently
> discards good data (if it turns bad later). Nothing would crash.

The tool it names — `scripts/derive_dataset_constants.py` — **does not exist**.
So both splits have sat on disk unused: LI-Small (650 MB, 117 rings) and
HI-Medium (3.03 GB, **2,756 rings**).

**The boundary must be chosen by a rule fixed in advance.** Picking the cut
after seeing where the laundering rate spikes is choosing a threshold to suit
the data, which is the failure this repository catalogues.

## The rule for `eval_end_day`

The boundary exists to stop "timestamp ≥ D" being a near-perfect classifier.
Per day: edge count, laundering count. Let the global base rate be
`total_laundering / total_edges`.

> **`eval_end_day` = the smallest day `D` such that the tail `[D, last]`
> contains ≤ 1% of all edges AND has a laundering rate ≥ 10× the global base
> rate.**
>
> **If no such `D` exists, there is no leak and no truncation:
> `eval_end_day = last_day + 1`.**

*Smallest* qualifying `D`, because the leak is a suffix and cutting later would
leave part of it inside. The two thresholds are fixed here, before any split's
curve is seen, and are deliberately loose: 1% of edges is far more than the
0.016% HI-Small's tail holds, and 10× is far less than its ~900×.

## The rule for `structural_recall_ceiling`

> **ceiling = (rings beginning before `eval_end_day` with **more than two**
> distinct accounts) ÷ (rings beginning before `eval_end_day`)**

A two-account ring has no community structure to detect, so it bounds recall
before detector quality enters. A ring "begins" at its earliest transaction.

## The control that makes this trustworthy

**The same script must re-derive HI-Small and reproduce its committed values
exactly: `eval_end_day = 10` and `structural_recall_ceiling = 0.733`.**

Those were derived by hand in Phase 0 by different reasoning. If a rule fixed
in advance reproduces both, it is measuring what Phase 0 measured. **If it does
not, the rule is wrong and no other split may be derived with it** — that is
the kill criterion, and it fires before any new number is used.

## Pre-registered expectations

| quantity | prediction |
|---|---|
| HI-Small re-derived | **exactly 10 and 0.733**, or the exercise stops |
| LI-Small `eval_end_day` | **a leak exists**, cut somewhere in days 8–12 — same generator, same shape |
| HI-Medium `eval_end_day` | **a leak exists**, and I expect a *later* cut than 10 because the split spans more days |
| LI-Small ceiling | **0.60–0.85** |
| HI-Medium ceiling | **0.60–0.85** |
| rings surviving the boundary | ≥ 90% of each split's total, as with HI-Small's 363/370 |

**Most likely to disappoint: LI-Small has only 117 rings.** Even a clean
derivation leaves a split whose intervals will be roughly `sqrt(370/117) ≈ 1.8×`
wider than HI-Small's. It is a generalisation check, not a stronger measurement.
**HI-Medium at 2,756 rings is the one that could actually narrow anything.**

## Scope, stated so it is not quietly widened

This pre-registration covers **deriving and registering the constants only**.
Building a stream and running an evaluation on a new split is separate work
with its own cost, and nothing here pre-commits to it or predicts its result.

**No claim about HI-Small's numbers transfers to another split**, and no
cross-split comparison may be reported until both have been run through the
same pipeline on this machine.
