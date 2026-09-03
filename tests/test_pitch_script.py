"""The one number spoken aloud in the pitch must match the measurement.

`docs/PITCH-SCRIPT.md` is rendered, so every figure shown ON SCREEN comes from
results/metrics.json and cannot go stale. The spoken lines are different: a
presenter cannot read "0.2912" naturally, so the headline is glossed in words
("zero point two nine"). A gloss is hand-written, and a hand-written number
beside a rendered one is exactly the drift standing rule 1 exists to stop --
`0.2778` survived in README through two corrections that way.

This closes that gap for the only figure actually said out loud. If the
precision at ten moves, this fails and names the line, instead of the number
being wrong on camera in a submission video that cannot be edited afterwards.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.report.store import read

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "docs" / "PITCH-SCRIPT.md"
METRICS = ROOT / "results" / "metrics.json"

DIGIT_WORDS = ("zero", "one", "two", "three", "four", "five",
               "six", "seven", "eight", "nine")


def _spoken(text: str) -> str:
    """Only the blockquote lines are read aloud; stage directions are not."""
    return " ".join(l.lstrip(">").strip() for l in text.splitlines()
                    if l.startswith(">")).replace("**", " ").lower()


def test_the_spoken_headline_matches_the_measured_value():
    if not (SCRIPT.exists() and METRICS.exists()):
        pytest.skip("pitch script or metrics not built")
    value = read(METRICS)["shipped_score_p_at_10"].value

    # Two decimals is how a presenter says it, and how the script writes it.
    a, b = f"{value:.2f}".split(".")[1]
    expected = f"zero point {DIGIT_WORDS[int(a)]} {DIGIT_WORDS[int(b)]}"

    assert expected in _spoken(SCRIPT.read_text(encoding="utf-8")), (
        f"docs/PITCH-SCRIPT.md speaks a precision at ten that no longer "
        f"matches results/metrics.json. The measured value is {value:.4f}, so "
        f"the spoken line should read {expected!r}. Fix the gloss in "
        f"docs/PITCH-SCRIPT.template.md (section [2:05]) and re-render. This "
        f"number is said out loud in a submission video.")


def test_the_check_can_fail():
    """Negative control. Without this, the assertion above would pass for any
    script that happened to contain the phrase for an unrelated reason."""
    a, b = "0.99".split(".")[1]
    wrong = f"zero point {DIGIT_WORDS[int(a)]} {DIGIT_WORDS[int(b)]}"
    assert wrong not in _spoken(SCRIPT.read_text(encoding="utf-8"))
