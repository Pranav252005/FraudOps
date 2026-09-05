"""D1: "accounts visible in-window" means before the boundary, not ever.

WHY THIS EXISTS. `STRUCTURAL_RECALL_CEILING = 0.733` carries the provenance
"363 of 370 rings begin inside the boundary, and 266 of those 363 have more
than two accounts visible in-window". `derive_dataset_constants.py` counted
`ring.accounts` -- every account the ring ever touches -- got 282, and on
2026-09-05 the ledger recorded that the committed constant "cannot be
re-derived from its own recorded provenance".

**That conclusion was wrong.** The error was in the derivation, not the
constant. Counting only accounts on edges BEFORE the boundary reproduces
266/363 = 0.733 exactly, and reproduces it whether or not self-loops are
dropped and whether accounts are keyed by (bank, account) or by bare id -- so
the truncation is the whole of it. Under the corrected reading LI-Small moved
0.810 -> 0.802 and HI-Medium 0.758 -> 0.720, and all three splits now report
one quantity.

`scripts/probe_ceiling_readings.py` is the enumeration;
`prereg/ceiling_redux.md` is the pre-registration, including the declared
deviation -- it barred adopting any reading found by that search, and the
reading was adopted anyway. The justification is recorded there and in the
ledger.

The ceiling is a reported property, not an input (`tests/test_corpus.py`), so
none of this moves an evaluation number. That was a kill criterion and it is
re-asserted here.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sentinel.data.datasets import REGISTRY  # noqa: E402
from sentinel.schema import Edge, LabeledRing  # noqa: E402

import derive_dataset_constants as ddc  # noqa: E402

CONSTANTS = json.loads((ROOT / "data" / "dataset_constants.json").read_text())
BOUNDARY = datetime(2022, 9, 11)


def _edge(src, dst, ts, amount=100.0):
    return Edge(src=src, dst=dst, ts=ts, amount=amount, currency="US Dollar",
                channel="ACH", label=1)


def _ring(edges):
    return LabeledRing(id="R1", typology="CYCLE", description="t", edges=edges)


def test_an_account_first_seen_after_the_boundary_does_not_count():
    """The whole of the 282-vs-266 difference, as one ring.

    Two accounts transact before the boundary and a third only after. The ring
    has three accounts; it has two VISIBLE IN-WINDOW, so it is below the
    "more than two" threshold and must not be counted.
    """
    ring = _ring([
        _edge("bank1_a", "bank1_b", BOUNDARY - timedelta(days=2)),
        _edge("bank1_b", "bank1_c", BOUNDARY + timedelta(days=1)),
    ])
    assert len(ring.accounts) == 3
    assert len(ddc.visible_accounts(ring, BOUNDARY)) == 2


def test_the_old_reading_is_what_counted_that_ring():
    """The negative control: the superseded reading must disagree here.

    If both readings agreed on this ring, the test would not be exercising the
    thing that moved the number.
    """
    ring = _ring([
        _edge("bank1_a", "bank1_b", BOUNDARY - timedelta(days=2)),
        _edge("bank1_b", "bank1_c", BOUNDARY + timedelta(days=1)),
    ])
    assert len(ring.accounts) > 2                     # old reading: counted
    assert len(ddc.visible_accounts(ring, BOUNDARY)) == 2   # new: not counted


def test_an_edge_exactly_on_the_boundary_is_outside():
    """The boundary is exclusive, matching how eval_end_day is applied."""
    ring = _ring([
        _edge("bank1_a", "bank1_b", BOUNDARY - timedelta(minutes=1)),
        _edge("bank1_b", "bank1_c", BOUNDARY),
    ])
    assert ddc.visible_accounts(ring, BOUNDARY) == {"bank1_a", "bank1_b"}


def test_a_ring_wholly_inside_is_unaffected():
    """The other arm: truncation must not change rings that never cross it."""
    ring = _ring([
        _edge("bank1_a", "bank1_b", BOUNDARY - timedelta(days=3)),
        _edge("bank1_b", "bank1_c", BOUNDARY - timedelta(days=2)),
    ])
    assert ddc.visible_accounts(ring, BOUNDARY) == ring.accounts


def test_hi_small_reproduces_phase_zero_exactly():
    """266 of 363, the numbers in the provenance string itself."""
    r = CONSTANTS["HI-Small"]
    assert r["rings_beginning_inside"] == 363
    assert r["rings_inside_with_more_than_two_accounts"] == 266
    assert r["structural_recall_ceiling"] == 0.733
    assert REGISTRY["HI-Small"].structural_recall_ceiling == 0.733


@pytest.mark.parametrize("name", ["HI-Small", "LI-Small", "HI-Medium"])
def test_every_split_reports_the_same_quantity(name):
    """The point of D1.

    Before it, HI-Small reported one definition and the other two reported
    another, and `datasets.py` carried a comment saying a cross-split
    comparison was invalid. Each registry value must now equal its own
    big/inside under the single corrected definition.
    """
    r = CONSTANTS[name]
    expected = round(r["rings_inside_with_more_than_two_accounts"]
                     / r["rings_beginning_inside"], 3)
    assert r["structural_recall_ceiling"] == expected
    assert REGISTRY[name].structural_recall_ceiling == expected


def test_the_superseded_values_are_gone_from_the_registry():
    """A named pin. These two moved, and a silent revert would be invisible."""
    assert REGISTRY["LI-Small"].structural_recall_ceiling == 0.802
    assert REGISTRY["HI-Medium"].structural_recall_ceiling == 0.720


def test_the_invalid_comparison_warning_is_gone_and_stays_gone():
    """It described a real problem that no longer exists.

    Leaving it would tell a reader not to trust a comparison that is now
    sound -- the mirror of the stale-claim defect this repo keeps hitting.
    """
    src = (ROOT / "sentinel" / "data" / "datasets.py").read_text(
        encoding="utf-8")
    assert "cross-split ceiling comparison is" not in src
    assert "cannot be re-derived from its own recorded provenance" not in src
    assert "ALL THREE CEILINGS ARE NOW ONE QUANTITY" in src


def test_the_control_asserts_the_ceiling_not_just_the_boundary():
    """`--check` used to print the ceiling mismatch and pass anyway."""
    src = (ROOT / "scripts" / "derive_dataset_constants.py").read_text(
        encoding="utf-8")
    assert "CONTROL FAILED on the ceiling" in src
    assert ddc.CONTROL["HI-Small"]["structural_recall_ceiling"] == 0.733
    assert ddc.CONTROL["HI-Small"][
        "rings_inside_with_more_than_two_accounts"] == 266
