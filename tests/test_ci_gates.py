"""The determinism gate must be ABLE to fail.

History, because it is the whole justification for this file. The gate in
`scripts/ci_gates.py` ran the fixture with `registry=None`, since the AMLworld
accounts CSV is not committed. That skipped the jurisdiction and entity-type
block of `sentinel/detect/features.build` entirely -- which is precisely where
bug #17 lived (`dominant_entity_type` chosen by `max(set(types), ...)`, i.e. by
set iteration order, i.e. by PYTHONHASHSEED). The gate was run against the
pre-fix code and PASSED.

That is this repo's characteristic defect wearing a green tick: not an error,
a plausible wrong answer. A gate that cannot fail is worse than no gate,
because it retires the question. `run_fixture` now builds a synthetic registry
from the fixture's own node keys, and these tests pin that the guarded path is
both EXECUTED and OBSERVED by the fingerprint.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ci_gates  # noqa: E402


def test_the_fixture_exercises_the_registry_guarded_path():
    """`registry is not None and node_key is not None` must be true in the gate.

    Checked by observing a feature that ONLY that block can set, rather than by
    inspecting the call, so the test survives a refactor of how the registry
    reaches the generator.
    """
    result = ci_gates.run_fixture()
    entity_typed = [
        c for cyc in result["cycles"] for c in cyc["candidates"]
        if c.features.dominant_entity_type
    ]
    assert entity_typed, (
        "no candidate carries a dominant_entity_type, so the jurisdiction / "
        "entity block of features.build did not execute -- the determinism "
        "gate is back to covering nothing"
    )


def test_ties_actually_occur_so_the_bug_could_have_fired():
    """A tie is the only state in which the old formulation was unstable.

    Executing the block is not enough: if every candidate had one clear
    majority entity type, `max(set(types), key=...)` and
    `max(sorted(set(types)), key=...)` would agree on every input and the gate
    would still be unable to fail. So this recomputes the type multiset from
    the registry and counts EXACT maximal ties, rather than inferring them from
    `entity_type_purity` -- a low purity can also come from a clear winner over
    a long tail, which is not a tie and would not have triggered the bug.
    """
    from collections import Counter

    from sentinel.stream.replay import Stream

    stream = Stream(ci_gates.FIXTURE)
    reg = ci_gates._synthetic_registry(stream)
    result = ci_gates.run_fixture()

    ties = 0
    for cyc in result["cycles"]:
        for c in cyc["candidates"]:
            counts = Counter()
            for n in c.nodes:
                acct = reg.get(stream.key(n))
                if acct is not None:
                    counts[acct.entity_type] += 1
            if not counts:
                continue
            top = max(counts.values())
            if sum(1 for v in counts.values() if v == top) > 1:
                ties += 1
    assert ties > 0, (
        "no candidate has a MAXIMAL TIE on entity type, so reintroducing "
        "bug #17 would not change the fingerprint and the gate could not fail"
    )


def test_the_fingerprint_observes_the_guarded_features():
    """The gate compares fingerprints, so a feature the fingerprint ignores is
    a feature the gate cannot police."""
    result = ci_gates.run_fixture()
    cand = next(
        c for cyc in result["cycles"] for c in cyc["candidates"]
        if c.features.dominant_entity_type
    )
    before = ci_gates.fingerprint(result)
    original = cand.features.dominant_entity_type
    cand.features.dominant_entity_type = original + "_perturbed"
    try:
        assert ci_gates.fingerprint(result) != before, (
            "perturbing dominant_entity_type did not move the fingerprint, so "
            "the determinism gate is blind to the field bug #17 corrupted"
        )
    finally:
        cand.features.dominant_entity_type = original


def test_synthetic_registry_is_itself_deterministic():
    """If the registry were order-dependent the gate would fail for its own
    reasons, which is a different and equally useless kind of broken."""
    from sentinel.stream.replay import Stream

    stream = Stream(ci_gates.FIXTURE)
    a = ci_gates._synthetic_registry(stream)
    b = ci_gates._synthetic_registry(stream)
    assert len(a.accounts) == len(b.accounts)
    for key, acct in a.accounts.items():
        other = b.accounts[key]
        assert (acct.country, acct.entity_id, acct.entity_type) == (
            other.country, other.entity_id, other.entity_type
        )
