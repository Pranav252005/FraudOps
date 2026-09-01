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

# Phrases where a percent-shaped token is a LABEL rather than a measurement.
# Kept deliberately short and anchored: "95% CI" names the confidence level of
# an interval and cannot go stale, because changing it would change the
# estimator rather than the estimate. Every addition here weakens the scanner,
# so each one has to be a fixed phrase whose number is part of the phrase.
NOT_A_MEASUREMENT = re.compile(
    r'\b9[05]%\s*(?:CI|confidence)|\bconfidence\s+interval', re.I)

MARKER = re.compile(
    r'<!--\s*historical:\s*measured at commit\s+(?P<commit>[0-9a-f]{7,40}|unknown)\s*,\s*'
    r'(?P<date>\d{4}-\d{2}-\d{2}|unknown)\s*-->', re.I)


def prose_files(root: Path) -> list[Path]:
    """The hand-written prose, excluding generated files and the inventory.

    README.template.md is scanned and README.md is NOT, because README.md is a
    build artefact rendered from the template. Scanning both would double-count
    every literal and, worse, would count the rendered VALUES -- which are
    correct by construction and which nobody can fix by editing, since editing
    them is overwritten on the next render. The template is where a human can
    introduce a stale number, so the template is what the ratchet watches.

    `docs/inventory/metric_literals.csv` is the OUTPUT of counting literals; it
    is not prose and counting it would be circular. `docs/negative-results/` IS
    counted -- a negative result quoting a stale number is exactly as
    misleading as a headline doing it.
    """
    template = root / "README.template.md"
    files = [template] if template.is_file() else [root / "README.md"]
    files += sorted(p for p in (root / "docs").rglob("*.md")
                    if "inventory" not in p.parts)

    def is_generated(p: Path) -> bool:
        """True when `p` is rendered from a sibling `*.template.md`.

        Checked by file existence rather than by reading the DO-NOT-EDIT
        banner, so a generated file that somebody stripped the banner off is
        still recognised as generated.
        """
        if p.name.endswith(".template.md"):
            return False
        return p.with_name(p.name[:-3] + ".template.md").is_file()

    return [p for p in files if p.is_file() and not is_generated(p)]


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
        label_spans = [m.span() for m in NOT_A_MEASUREMENT.finditer(line)]
        for m in METRIC_LITERAL.finditer(line):
            inside_label = any(a <= m.start() < b for a, b in label_spans)
            out.append((i + 1, m.group(0), exempt or inside_label))
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
