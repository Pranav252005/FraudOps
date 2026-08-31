"""Rule 1 for prose: a ratchet now, an assertion after Phase 4.

The goal state is that no metric-shaped literal appears in README or docs/
except ones explicitly marked as historical narration. That is Phase 4 work --
README becomes a template rendered from a metrics file -- and it is not done.

So this file ships two tests that do different jobs:

  * `test_no_unmarked_metric_literals_in_prose` is the GOAL. It is marked
    xfail, so it does not block the build, and `strict=True`, so it will fail
    the build the day it starts passing and nobody has removed the marker.
  * `test_the_unmarked_literal_count_never_increases` is the RATCHET, and it
    passes today. It is the part that does real work in the meantime: the
    count may fall, never rise.

A baseline recorded and enforced is worth more than a goal asserted and
skipped. The count is the honest measure of how far rule 1 is from being a
property rather than a practice.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.report.literals import (MARKER, count_unmarked, prose_files,
                                      scan)

# The ledger. Every entry is a deliberate change to the allowed count, with the
# reason it moved. Measured by `sentinel.report.literals.count_unmarked`.
#
# The ratchet's job is to make an increase VISIBLE AND JUSTIFIED, not
# impossible. Writing up a new measurement legitimately adds literals -- those
# numbers exist and were measured today. What the ratchet stops is literals
# accumulating without anyone noticing, and numbers surviving in prose after the
# measurement behind them has moved. A raise that cannot state its cause in one
# line is the case this is designed to catch.
#
# Append, never edit in place.
LEDGER = [
    ("2026-08-31", "63066d1", 1636,
     "baseline at first measurement"),
    ("2026-09-01", "phase-2a", 1730,
     "+94: docs/PHASE2-SEED-CHEAT-FINDINGS.md (68) and "
     "docs/negative-results/builder-budget-refuted.md (26), both written up "
     "from measurements taken the same day. Not marked historical, because "
     "they are current: the marker asserts a number narrates a PAST state, "
     "and using it to silence the scanner on live numbers would be a lie that "
     "the scanner itself cannot detect."),
    ("2026-09-01", "phase-3", 1835,
     "+105: docs/PHASE3-LABEL-TAX-FINDINGS.md and two negative-results "
     "entries (analyst-pool-mismatch, label-noise-non-monotone), all from the "
     "label-tax arms run the same day against pre-registrations committed at "
     "a4eee6e. Same reasoning as the previous entry -- these are current "
     "measurements, so the historical marker does not apply to them."),
]

BASELINE_UNMARKED = LEDGER[-1][2]


def test_the_unmarked_literal_count_never_increases():
    total, per_file = count_unmarked(ROOT)
    assert total <= BASELINE_UNMARKED, (
        f"unmarked metric literals rose from {BASELINE_UNMARKED} to {total}. "
        f"Every one is a number that can go stale independently of the "
        f"measurement it came from -- which has already happened twice to "
        f"0.2778 (see docs/STANDING-RULES.md rule 1). Per file: "
        f"{dict(sorted(per_file.items(), key=lambda kv: -kv[1])[:5])}")


def test_the_ledger_is_append_only_and_every_entry_gives_a_reason():
    """The ledger is the audit trail; without these it is just a number.

    Each entry must carry a date, a commit or tag, a count, and a reason long
    enough to be a sentence. A raise that cannot say why in one line is exactly
    what the ratchet exists to surface.
    """
    assert LEDGER, "the ledger may not be emptied"
    for date, ref, count, reason in LEDGER:
        assert len(date) == 10 and date[4] == "-", date
        assert ref, date
        assert isinstance(count, int) and count >= 0, date
        assert len(reason) > 20, f"{date}: reason too thin to audit: {reason!r}"
    dates = [e[0] for e in LEDGER]
    assert dates == sorted(dates), "ledger entries must be in date order"


def test_the_baseline_is_not_stale_by_a_wide_margin():
    """Keeps the ratchet tight.

    A baseline left far above the actual count stops being a ratchet -- it
    permits a large regression before firing. If the real count has dropped
    well below the recorded baseline, the baseline should be lowered in the
    same commit that dropped it.
    """
    total, _ = count_unmarked(ROOT)
    assert total >= BASELINE_UNMARKED - 50, (
        f"count is {total}, baseline is {BASELINE_UNMARKED}: lower "
        f"BASELINE_UNMARKED to {total} so the ratchet keeps biting.")


@pytest.mark.xfail(strict=True, reason=(
    "Phase 4 has not run: README is not yet a template rendered from "
    "results/metrics.json, so 1,636 literals remain unmarked. Strict, so this "
    "fails the build when it starts passing and the xfail is left behind."))
def test_no_unmarked_metric_literals_in_prose():
    total, per_file = count_unmarked(ROOT)
    assert total == 0, per_file


def test_the_scanner_finds_the_literals_it_is_supposed_to():
    """The negative control: a scanner that matched nothing would pass the
    ratchet forever."""
    total, per_file = count_unmarked(ROOT)
    assert total > 0
    assert "README.md" in per_file


def test_the_historical_marker_actually_exempts(tmp_path):
    """The exemption must work, or Phase 4 has no way to keep true history."""
    doc = tmp_path / "d.md"
    doc.write_text(
        "<!-- historical: measured at commit 0b4debd, 2026-08-31 -->\n"
        "The pointwise model reached 0.2500 before the split fix.\n",
        encoding="utf-8")
    assert all(exempt for _, _, exempt in scan(doc))

    doc.write_text("The pointwise model reaches 0.2500.\n", encoding="utf-8")
    assert not any(exempt for _, _, exempt in scan(doc))


@pytest.mark.parametrize("marker", [
    "<!-- historical -->",
    "<!-- historical: 2026-08-31 -->",
    "<!-- historical: measured at commit 0b4debd -->",
    "<!-- historical: measured at commit zzzzzzz, 2026-08-31 -->",
])
def test_a_marker_without_a_commit_and_a_date_does_not_exempt(tmp_path, marker):
    """Phase 4.3 requires both. A marker that carries neither is a way to
    silence the scanner without recording anything."""
    doc = tmp_path / "d.md"
    doc.write_text(f"{marker}\nIt reached 0.2500.\n", encoding="utf-8")
    assert not any(exempt for _, _, exempt in scan(doc))


def test_unknown_is_an_acceptable_commit():
    """An auditable admission beats an invented sha.

    The inventory found literals whose producing commit cannot be established
    from history. Forcing a sha there would mean inventing one.
    """
    assert MARKER.search(
        "<!-- historical: measured at commit unknown, 2026-08-31 -->")


def test_the_inventory_csv_is_not_scanned():
    """It is the output of counting literals; counting it would be circular."""
    assert not any("inventory" in p.parts for p in prose_files(ROOT))
