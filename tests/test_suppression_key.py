"""B3: is the candidate SET a function of the generator, or of the scorer too?

Pre-registered in `prereg/suppression_key.md`. **This file is the experiment**,
not a supporting check for it. B3's claim is a property, not a metric:

    Under a score-free suppression key the emitted member sets are invariant to
    the blend weights. Under the shipped score-ordered key they are not.

`suppress()` is greedy NMS ordered by score, so which member of an overlapping
group survives — and therefore which candidates exist at all — is decided by
the score. That is recorded in `docs/HANDOFF-NEXT.md`, `sentinel/corpus/`, and
`docs/graph-review/2026-09-04.md` §2b, and it is why every scorer A/B in this
repository is structurally confounded.

BOTH HALVES MUST FIRE OR THE EXPERIMENT IS VOID, and the pre-registration says
so before any number was seen:

  * if the shipped pool does NOT move under a weight perturbation, there is no
    confound to fix and B3 is unnecessary;
  * if a score-free pool DOES move, the key is not score-free and the
    implementation is wrong.

The perturbation is recorded rather than described: the weight *values* are
reassigned to the same keys in reverse rank order. It preserves the sum-to-1.0
invariant `tests/test_blend_weights.py` asserts, so the perturbed blend is a
legal blend and not a broken one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import ci_gates  # noqa: E402

from sentinel.detect import features as F  # noqa: E402
from sentinel.detect import merge as M  # noqa: E402

SCORE_FREE = (M.SUPPRESS_LARGEST, M.SUPPRESS_SMALLEST, M.SUPPRESS_KEY)


def perturbed_weights() -> dict:
    """Reassign the same weight values to the same keys, in reverse rank order.

    Sum-preserving by construction, so the perturbed blend still satisfies the
    invariant `features.py` is asserted against — a perturbation that produced
    an illegal blend would be testing the assertion, not the suppression key.
    """
    keys = sorted(F.WEIGHTS)
    values = sorted((F.WEIGHTS[k] for k in keys), reverse=True)
    ranked = sorted(keys, key=lambda k: (F.WEIGHTS[k], k))
    return {k: v for k, v in zip(ranked, values)}


def pool(ordering, weights=None) -> frozenset[str]:
    """The set of candidate keys the fixture emits, under `ordering`."""
    original = dict(F.WEIGHTS)
    try:
        if weights is not None:
            F.WEIGHTS.clear()
            F.WEIGHTS.update(weights)
        result = ci_gates.run_fixture(suppress_ordering=ordering)
        return frozenset(c.key for cyc in result["cycles"]
                         for c in cyc["candidates"])
    finally:
        F.WEIGHTS.clear()
        F.WEIGHTS.update(original)


@pytest.fixture(scope="module")
def base_pools():
    return {o: pool(o) for o in (M.SUPPRESS_SCORE,) + SCORE_FREE}


def test_the_perturbation_is_a_real_and_legal_change():
    """Guards both ways: a perturbation that changed nothing would make every
    invariance assertion below pass vacuously, and one that broke the
    sum-to-1.0 invariant would be testing that instead."""
    p = perturbed_weights()
    assert p != F.WEIGHTS, "the perturbation is a no-op"
    assert set(p) == set(F.WEIGHTS)
    assert sum(p.values()) == pytest.approx(sum(F.WEIGHTS.values()))
    assert sum(p.values()) == pytest.approx(1.0)


def test_the_shipped_pool_moves_when_the_weights_move(base_pools):
    """The negative control, and the reason B3 exists at all.

    If this fails, the documented confound does not occur in practice on this
    fixture and the rest of the experiment is unnecessary — which the
    pre-registration names as a legitimate outcome, not a bug.
    """
    before = base_pools[M.SUPPRESS_SCORE]
    after = pool(M.SUPPRESS_SCORE, perturbed_weights())
    assert before != after, (
        "the shipped score-ordered pool did NOT change when the blend weights "
        "changed. Either the confound does not occur on this fixture or the "
        "perturbation is inert — check test_the_perturbation_is_a_real_and_"
        "legal_change before concluding anything from the rest of this file.")


@pytest.mark.parametrize("ordering", SCORE_FREE)
def test_a_score_free_pool_is_invariant_to_the_weights(ordering, base_pools):
    """B3's actual claim. The member sets must be IDENTICAL, not similar."""
    before = base_pools[ordering]
    after = pool(ordering, perturbed_weights())
    assert before == after, (
        f"the {ordering!r} pool changed when the blend weights changed, so it "
        f"is not score-free. Symmetric difference: "
        f"{len(before ^ after)} of {len(before)} candidates.")


def test_score_free_orderings_disagree_with_each_other(base_pools):
    """Otherwise 'invariant' would be trivially satisfied by three names for
    one thing, and the three arms would not be three arms."""
    pools = {o: base_pools[o] for o in SCORE_FREE}
    assert len(set(pools.values())) > 1, (
        "every score-free ordering produced the same pool; they are not "
        "distinct arms")


def test_every_ordering_keeps_a_covering_subset(base_pools):
    """Suppression must suppress, and must not invent.

    Candidate counts are allowed to differ between orderings — that is the
    point — but none may exceed the unsuppressed population, and none may be
    empty.
    """
    unsuppressed = ci_gates.run_fixture()["stats"]["emitted"]
    for ordering, keys in base_pools.items():
        assert 0 < len(keys) <= unsuppressed, (ordering, len(keys))


def test_an_unknown_ordering_is_refused():
    with pytest.raises(ValueError, match="unknown suppression ordering"):
        M.suppress([], ordering="whatever")


def test_the_shipped_default_is_the_score_ordering():
    """The experiment must not change the shipped system as a side effect."""
    from sentinel.detect.candidates import CandidateGenerator
    import inspect
    sig = inspect.signature(CandidateGenerator.__init__)
    assert sig.parameters["suppress_ordering"].default == M.SUPPRESS_SCORE
    assert inspect.signature(M.suppress).parameters["ordering"].default == \
        M.SUPPRESS_SCORE
