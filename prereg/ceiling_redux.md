# D1 — make HI-Small's ceiling the same quantity as the other two splits

**Pre-registered 2026-09-05, before any new reading of the ceiling was computed.**

## Where this stands

`STRUCTURAL_RECALL_CEILING = 0.733` is committed with the provenance string
"363 of 370 rings begin inside the boundary, and 266 of those 363 have more
than two accounts visible in-window". 266/363 = 0.7328, so the string is
internally consistent.

`scripts/derive_dataset_constants.py` reproduces the **denominator exactly**
— `rings_beginning_inside = 363` — and gets **282**, not 266, for the
numerator. Four readings were tried on 2026-09-05 (ring size > 2, and > 2
accounts co-visible in a 72h window, each with and without self-loops) and
gave 278–282. LI-Small and HI-Medium are registered under the derived
definition, so **the three splits currently report two different quantities**
and `sentinel/data/datasets.py` carries a comment saying a cross-split ceiling
comparison is invalid.

## Primary change (this is the deliverable, and it is not a search)

**Replace HI-Small's 0.733 with the value derived under the same definition as
LI-Small and HI-Medium**, and delete the comment saying the comparison is
invalid, because it then is not.

Expected value **0.777** (282/363), already recorded in
`data/dataset_constants.json` from the 2026-09-05 scan. It is re-derived rather
than copied.

The old number is not deleted from the record. It moves into the provenance
string as what Phase 0 reported and what could not be reconstructed.

## Kill criteria for the primary change

1. **The ceiling must be inert.** It is asserted to be "a reported property,
   not an input" by `tests/test_corpus.py`. If changing it moves ANY evaluation
   output — the five gates included — the change is **rejected**, because that
   would mean a number nobody can reconstruct is load-bearing, which is a
   larger problem than the inconsistency being fixed.
2. **The denominator must still be 363.** If a re-run does not reproduce
   `rings_beginning_inside = 363`, the harness has drifted and no value from it
   may be committed.
3. **`eval_end_day` must still be 10.** It gates correctness and its control
   already passes; a change here means something unrelated broke.

## Secondary: a bounded, declared search for 266

Four readings have been tried. Four more are pre-committed here, chosen as
plain readings of the provenance string and **fixed before any is computed**:

* **R5** — accounts appearing on edges with `ts` before the boundary
  (time-truncated; the current reading counts every account of the ring
  regardless of when it transacts).
* **R6** — R5, excluding self-loop edges.
* **R7** — accounts identified as `(bank, account)` pairs rather than bare
  account ids, if the current reading uses bare ids (or the reverse).
* **R8** — R5 combined with the 72h co-visibility constraint.

**The decision rule, fixed now: no reading discovered by this enumeration may
be adopted as the shipped definition, even one that hits 266 exactly.**
Searching eight readings for one that matches a known target is fitting, not
deriving. A hit would be reported as a *candidate explanation* of what Phase 0
probably did, with the multiplicity stated (1 of 8), and nothing more. The
shipped value stays the one from the primary change above.

**Negative control:** the harness must reproduce the current definition's
282/363 exactly before any new reading is believed. If it does not, every
number it produces is discarded.

## Declared in advance

* This needs the Patterns file only, not a transaction scan, except for the
  epoch ordinal — which is read from `data/dataset_constants.json` rather than
  re-derived, because the HI-Medium funnel is running on the same machine.
  If that file's `eval_end_day` is not 10, the run aborts (kill criterion 3).
* `scripts/derive_dataset_constants.py` cites
  `docs/DATASET-CONSTANTS-FINDINGS.md` for the four earlier readings. **That
  file does not exist** — the citation is stale and the readings live only in
  the ledger. Fixing that citation is part of this change.
