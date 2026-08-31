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

# Measured 2026-08-31 at commit 63066d1, by
# `sentinel.report.literals.count_unmarked`. This number is allowed to go DOWN.
# Raising it requires deleting this comment, which is the point.
BASELINE_UNMARKED = 1636


def test_the_unmarked_literal_count_never_increases():
    total, per_file = count_unmarked(ROOT)
    assert total <= BASELINE_UNMARKED, (
        f"unmarked metric literals rose from {BASELINE_UNMARKED} to {total}. "
        f"Every one is a number that can go stale independently of the "
        f"measurement it came from -- which has already happened twice to "
        f"0.2778 (see docs/STANDING-RULES.md rule 1). Per file: "
        f"{dict(sorted(per_file.items(), key=lambda kv: -kv[1])[:5])}")


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
