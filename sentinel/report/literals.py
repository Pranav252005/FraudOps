"""Find metric-shaped literals sitting in prose.

Rule 1 says never state a number that has not been measured. `Metric` enforces
that for numbers going OUT through the reporting layer. It does nothing about
the numbers already written into README and docs/ by hand -- and that is where
the problem actually is: `docs/inventory/metric_literals.csv` counted **1,699**
of them, with `0.2778` alone appearing 40 times, at least two of which were
measurably wrong at the time of the count.

This module is the scanner behind the ratchet in
`tests/test_prose_literals.py`. It is deliberately separate from that test so
the Phase 4 README renderer can use the same definition of "metric-shaped"
rather than inventing a second one that disagrees at the edges.

THE MARKER. A literal that narrates a past state is legitimate and must stay a
literal -- rewriting history to the current number would be worse than leaving
it. Such a literal is exempted by an HTML comment on the line before it:

    <!-- historical: measured at commit 0b4debd, 2026-08-31 -->
    Re-run after the fix, the pointwise model reached 0.2500.

The marker must carry a commit and a date. `unknown` is an acceptable commit
when the producing commit genuinely cannot be established -- an auditable
admission beats an invented sha, and beats an unmarked literal.
"""
from __future__ import annotations

import re
from pathlib import Path

# 0.1234 / 0.123, 12%/12.5%, 2.2x/2.2×. Deliberately NOT matching bare integers
# or one-decimal floats: those are overwhelmingly counts, versions and k values,
# and including them would bury the signal the ratchet is meant to track.
METRIC_LITERAL = re.compile(
    r'(?<![\w.])(?:0\.\d{3,4}|\d{1,3}(?:\.\d)?%|\d\.\d{1,2}(?:x|×))(?![\w])')

MARKER = re.compile(
    r'<!--\s*historical:\s*measured at commit\s+(?P<commit>[0-9a-f]{7,40}|unknown)\s*,\s*'
    r'(?P<date>\d{4}-\d{2}-\d{2}|unknown)\s*-->', re.I)


def prose_files(root: Path) -> list[Path]:
    """README plus docs/, excluding the machine-generated inventory.

    `docs/inventory/metric_literals.csv` is the OUTPUT of counting literals; it
    is not prose and counting it would be circular. `docs/negative-results/` IS
    counted -- a negative result quoting a stale number is exactly as
    misleading as a headline doing it.
    """
    files = [root / "README.md"]
    files += sorted(p for p in (root / "docs").rglob("*.md")
                    if "inventory" not in p.parts)
    return [p for p in files if p.is_file()]


def scan(path: Path) -> list[tuple[int, str, bool]]:
    """Return (line_number, literal, is_exempt) for every literal in `path`.

    A literal is exempt when the immediately preceding non-blank line carries a
    well-formed historical marker. "Immediately preceding" is deliberate: a
    marker that could exempt a whole section would drift out of alignment with
    the numbers it covers, which is the failure mode the marker exists to stop.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[tuple[int, str, bool]] = []
    for i, line in enumerate(lines):
        if not METRIC_LITERAL.search(line):
            continue
        prev = ""
        for j in range(i - 1, -1, -1):
            if lines[j].strip():
                prev = lines[j]
                break
        exempt = bool(MARKER.search(prev)) or bool(MARKER.search(line))
        for m in METRIC_LITERAL.finditer(line):
            out.append((i + 1, m.group(0), exempt))
    return out


def count_unmarked(root: Path) -> tuple[int, dict[str, int]]:
    """Total unmarked literals, and the per-file breakdown."""
    per_file: dict[str, int] = {}
    total = 0
    for path in prose_files(root):
        n = sum(1 for _, _, exempt in scan(path) if not exempt)
        if n:
            per_file[str(path.relative_to(root)).replace("\\", "/")] = n
            total += n
    return total, per_file
