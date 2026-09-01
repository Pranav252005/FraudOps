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


# --------------------------------------------------------------------------
# the superseded-value check -- the hole the ratchet did not cover
# --------------------------------------------------------------------------
#
# WHAT THIS EXISTS FOR. Phase 4 made README a template rendered from
# results/metrics.json and asserted that the rendered file matches a fresh
# render. That check is real, and it is blind in exactly one direction: it
# compares the OUTPUT to the TEMPLATE, so a hardcoded number in the template
# renders faithfully and is certified correct. Six unmarked instances of
# `0.278` -- a superseded reading of `supervised_p_at_10`, which is 0.2111 --
# survived in README.template.md that way, inside the document whose §6 claims
# the render system prevents precisely this. See
# docs/negative-results/template-literal-leak.md.
#
# The ratchet did not catch it either: the ratchet counts literals, and six
# literals that were already counted do not raise the count when the
# measurement behind them moves. A count cannot see staleness. This can.
#
# THE TWO SOURCES, AND WHY BOTH ARE NEEDED. Git history of the metrics file is
# the live half: it grows on its own as measurements move, with no one to
# remember to update it. It cannot reach back before the file existed, and
# every value in this project's first defect predates it -- so the values that
# rotted are declared explicitly. The explicit half is a ledger, not a
# workaround, and it is small on purpose: anything git can establish is not
# written here.

# Values a live metric id has held and no longer holds, from before
# results/metrics.json existed to record them. Append, never edit in place.
#
# Format them as they would appear in prose, at whatever precision they were
# written -- `0.278` and `0.2778` are the same wrong number and both must be
# caught, because METRIC_LITERAL matches either.
PRE_HISTORY_SUPERSEDED: dict[str, list[tuple[str, str, str]]] = {
    "supervised_p_at_10": [
        ("0.2778", "6253ac5",
         "the reading before `gargaml` and `stack` were retired as "
         "anti-signal; the blend's floor rose and this did not move"),
        ("0.2500", "0b4debd",
         "the clean re-run, before the dead training query groups were "
         "closed at 63066d1"),
        ("0.278", "unknown",
         "the 3dp rounding of 0.2778. This is the one that survived six times "
         "in README.template.md after both corrections above were written up "
         "three paragraphs earlier in the same file"),
    ],
}


def _as_written(value: float) -> set[str]:
    """Every rendering of `value` that METRIC_LITERAL would match.

    Three and four decimal places, because prose in this repository uses both
    and the scanner accepts both. Trailing-zero forms are included rather than
    normalised away: `0.2500` and `0.250` are different strings in a file and
    the check reads files, not floats.
    """
    return {f"{value:.3f}", f"{value:.4f}"}


def _metrics_at_commit(root: Path, sha: str) -> dict[str, float]:
    """`{id: value}` from results/metrics.json as of `sha`, or `{}`.

    Returns empty rather than raising for any commit where the file is absent,
    unparseable, or shaped differently -- the file's schema has changed once
    already and a history walk must survive its own past.
    """
    import json
    import subprocess

    try:
        blob = subprocess.run(
            ["git", "show", f"{sha}:results/metrics.json"],
            cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return {}
    if blob.returncode != 0:
        return {}
    try:
        payload = json.loads(blob.stdout)
        return {k: v["value"] for k, v in payload.get("metrics", {}).items()
                if isinstance(v, dict) and isinstance(v.get("value"),
                                                      (int, float))}
    except (ValueError, TypeError, AttributeError):
        return {}


def superseded_values(root: Path, current: dict[str, float],
                      use_git: bool = True) -> dict[str, set[str]]:
    """`{literal_as_written: {metric ids it is a superseded value of}}`.

    A value counts as superseded for an id when that id held it at some point
    and does not hold it now. A value the id still holds is not superseded --
    quoting the current number in prose is a staleness risk the ratchet already
    tracks, and is not this check's business.
    """
    import subprocess

    out: dict[str, set[str]] = {}

    def add(literal: str, mid: str) -> None:
        out.setdefault(literal, set()).add(mid)

    live_forms = {mid: _as_written(v) for mid, v in current.items()}

    for mid, entries in PRE_HISTORY_SUPERSEDED.items():
        if mid not in current:
            continue
        for literal, _commit, _why in entries:
            if literal in live_forms[mid]:
                continue
            add(literal, mid)

    if not use_git:
        return out

    try:
        log = subprocess.run(
            ["git", "log", "--format=%H", "--", "results/metrics.json"],
            cwd=root, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return out
    if log.returncode != 0:
        return out

    for sha in log.stdout.split():
        for mid, value in _metrics_at_commit(root, sha).items():
            if mid not in current:
                continue
            for literal in _as_written(value):
                if literal in live_forms[mid]:
                    continue
                add(literal, mid)
    return out


def stale_literals(root: Path, current: dict[str, float],
                   use_git: bool = True
                   ) -> list[tuple[str, int, str, set[str]]]:
    """Unmarked literals in prose that are superseded values of live metrics.

    Returns `(relative_path, line_number, literal, metric_ids)`. A literal
    carrying a well-formed historical marker is not reported: narrating a past
    state is the marker's whole purpose, and the two corrections written up in
    README.template.md are exactly that.
    """
    bad = superseded_values(root, current, use_git=use_git)
    if not bad:
        return []
    found: list[tuple[str, int, str, set[str]]] = []
    for path in prose_files(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
        for line_no, literal, exempt in scan(path):
            if exempt or literal not in bad:
                continue
            found.append((rel, line_no, literal, bad[literal]))
    return found
