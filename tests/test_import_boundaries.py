"""Architectural boundaries that must hold, checked transitively.

docs/HANDOFF.md 11b states: "nothing in sentinel/detect or sentinel/eval may
import sentinel.llm -- a non-deterministic component inside a measured path
would contaminate every reported interval", and lists it among "two properties
locked by tests".

**It was not.** Only the calibration boundary (test_calibrate.py) had a test.
The detect/eval boundary was a docstring promise. Written here, and gated in
CI, because a promise that nothing checks is exactly how the measured path
acquires a non-deterministic dependency without anyone noticing.

Every check runs in a subprocess against the *transitive* module set. A
direct-import check would pass while a dependency dragged the forbidden module
in behind it -- the same reasoning test_calibrate.py already applies.
"""
from __future__ import annotations

import subprocess
import sys

import pytest

# (importing these modules) must not pull in (any module with these prefixes)
BOUNDARIES = [
    ("sentinel.detect.candidates", ("sentinel.llm",)),
    ("sentinel.detect.features", ("sentinel.llm",)),
    ("sentinel.detect.motifs", ("sentinel.llm",)),
    ("sentinel.detect.prune", ("sentinel.llm",)),
    ("sentinel.detect.merge", ("sentinel.llm",)),
    ("sentinel.eval.bootstrap", ("sentinel.llm",)),
    ("sentinel.eval.funnel", ("sentinel.llm",)),
    ("sentinel.eval.dataset", ("sentinel.llm",)),
    ("sentinel.eval.identity", ("sentinel.llm",)),
    ("sentinel.generators.synthetic_identity", ("sentinel.llm",)),
    # The reporting contract sits on every measured path by construction: it is
    # what a measured number is rendered and stored through, so a
    # non-deterministic dependency here would reach every reported interval at
    # once rather than one script at a time.
    ("sentinel.report", ("sentinel.llm",)),
    ("sentinel.report.metric", ("sentinel.llm",)),
    ("sentinel.report.store", ("sentinel.llm",)),
]


def _forbidden_after_importing(module: str, prefixes: tuple[str, ...]) -> str:
    probe = (
        f"import sys; import {module}; "
        f"bad=[m for m in sys.modules if m.startswith({prefixes!r})]; "
        f"print(','.join(sorted(bad)))"
    )
    out = subprocess.run([sys.executable, "-c", probe],
                         capture_output=True, text=True, check=True)
    return out.stdout.strip()


@pytest.mark.parametrize("module,prefixes", BOUNDARIES,
                         ids=[m for m, _ in BOUNDARIES])
def test_measured_path_never_imports_the_llm(module, prefixes):
    found = _forbidden_after_importing(module, prefixes)
    assert found == "", (
        f"{module} transitively imports {found}. A non-deterministic component "
        f"inside a measured path contaminates every reported interval.")


def test_the_probe_would_actually_catch_a_violation():
    """A boundary test that cannot fail is not evidence.

    This project has already shipped one check that could never fail (the
    template narrative's citations were correct by construction, so the
    verifier could not reject anything -- docs/HANDOFF.md 11b). So the probe is
    pointed at a module that genuinely does import sentinel.llm, and must
    report it.
    """
    found = _forbidden_after_importing("sentinel.narrative.llm_draft",
                                        ("sentinel.llm",))
    assert "sentinel.llm" in found
