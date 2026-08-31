# Phase 0.2 — Inventory of `collect_pool`

**Produced:** 2026-08-31. **Method:** read of
`scripts/eval_oracle.py:205-259`, `sentinel/detect/candidates.py`,
`sentinel/learn/analyst.py`, `scripts/eval_phase4.py`. Verified against the
source, not against the claim.

## Full signature

```python
# scripts/eval_oracle.py:205
def collect_pool(stream, registry, seed_perfect: bool) -> tuple[list, dict]:
```

- `stream`: `sentinel.stream.replay.Stream`
- `registry`: `sentinel.data.accounts.AccountRegistry`
- `seed_perfect`: `bool` — when true, the seed set is unioned with every active
  ring's own members before `generate()` is called
- returns `(records, ring_first_t)`

## Return value, field by field

### `records: list[dict]`

| field | type | raw or derived | notes |
|---|---|---|---|
| `cand` | `Candidate` | raw | the candidate object; carries `.nodes`, `.key`, `.score`, `.size`, `.features`, `.seed`, `.absorbed` |
| `ring` | `int \| None` | **derived** | output of `label_candidate()`, which returns the first ring `r` for which `is_hit(cand.nodes, members)` holds. Ground-truth ring id, or `None` |
| `t` | `int` | raw | `graph.now`, the generation-cycle tick |

### `ring_first_t: dict[int, int]`

Raw. Maps each ring id that ever produced an active window to the first tick it
was seen. Basis of `ring_time_split`.

## The specific questions the plan asks

> **does it return per-item labels?**

**Yes, one label per candidate** — `record["ring"]`, and the binary
`y = 1 if ring is not None else 0` that `to_xy()` derives from it. It is a
**ground-truth** label read from `stream.ring`.

> **label provenance?**

**No.** There is exactly one label source and it is not recorded. Every label in
the returned pool is ground truth by construction. There is no field saying
where a label came from, because there is only ever one place it can have come
from.

> **a label-confidence or noise indicator?**

**No.** Ground-truth labels are treated as exact. `label_candidate` returns the
*first* matching ring under `is_hit` (a Jaccard/containment test in
`sentinel/eval/funnel.py`) and does not record the overlap fraction, the margin
to the hit floor, or whether more than one ring matched. That overlap fraction
is precisely what `SimulatedAnalyst.dispose()` would need
(`share = len(overlap) / len(members)`, compared against `PARTIAL_BELOW = 0.8`)
and **it is computed inside `is_hit` and thrown away.**

> **the pool before or after any label filtering?**

**After candidate pruning, before any label filtering.** `generate()` applies
`PRUNE_STRATEGY = "leaf2"` and greedy non-maximum suppression (`suppress()`,
ordered by score). No record is dropped on the basis of its label — negatives
and positives alike are appended. The `records` list is the complete post-prune
candidate set.

## GATE — the plan's stop condition

> **Gate:** If the fields needed for the label-tax arms (Phase 3) are absent,
> say so explicitly and stop before Phase 3.

**The fields are absent. The gate fires.**

`docs/HANDOFF-NEXT.md` §3, `scripts/eval_oracle.py:41`, `:159` and the
`collect_pool` docstring itself all assert some version of *"collect_pool
already returns everything it needs."* **That claim is false as written**, and
this document exists because the plan instructed that it be verified rather
than assumed.

The clean label-tax experiment is defined in those same places as *"same model,
same pool, same split, fitted once on truth and once on simulated verdicts."*
`collect_pool` returns truth. It does not return, and cannot produce without new
plumbing, the **simulated verdicts** — the second of the two label sets the
experiment is a comparison between.

What is specifically missing:

1. **A simulated-analyst label per candidate.** `SimulatedAnalyst.dispose()`
   (`sentinel/learn/analyst.py`) takes `(case, truth_members)` and returns a
   `Verdict`. It operates on **cases** (`sentinel/cases/case.py`), not on
   candidates. `scripts/eval_phase4.py` is the only caller and it builds cases
   from a different pipeline with a different split (`split_t = 8340`, 680
   train cases, 17 held-out cycles). Nothing today maps a `Candidate` to a
   `Verdict`.
2. **`truth_members` per candidate.** `dispose()` needs the set of account keys
   in the ground-truth ring this candidate overlaps. `label_candidate()` knows
   the ring id; the member set lives in `active_rings()`'s return value and is
   not carried into the record.
3. **The overlap fraction.** Needed to choose between `CONFIRMED_RING` and
   `CONFIRMED_PARTIAL`. Computed inside `is_hit` and discarded.

**Consequence for the plan:** Phase 3 is blocked as written. It needs a
**plumbing sub-phase (call it 3.-1)** before 3.0, whose entire content is:

- extend the `collect_pool` record with `ring_members: set[int]` and
  `overlap: float` (both already computed, neither retained), and
- add a candidate-level adapter for `SimulatedAnalyst` so the same pool can be
  labelled twice — once from truth, once from simulated verdicts — with the
  same seed and the same split.

Neither is large. Both are new code, and the plan's standing rule 1 means the
docstrings claiming otherwise must be corrected at the same time (see
`docs/inventory/metric_literals.csv` — this is not a metric literal but it is
the same class of defect: an unmeasured claim asserted as fact).

**No field has been synthesised. Phase 3 is not started.**
