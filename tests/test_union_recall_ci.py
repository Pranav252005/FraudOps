"""D5: a cluster bootstrap cannot bound a union statistic.

WHY THIS EXISTS. `ring_recall@k` shipped with intervals that do not contain
their own point estimates. On HI-Medium it failed at all three k, on HI-Small
at k=20 and k=50:

    HI-Medium ring_recall@10   point 0.11947   CI [0.09609, 0.11249]
    HI-Small  ring_recall@50   point 0.16000   CI [0.14290, 0.15500]

`ring_recall` is quoted in this project's headline tables, so the interval
beside it was not merely wide, it was invalid.

THE MECHANISM. `union_recall` computes `|union found| / |union seen|` over the
resampled cycles. A resample of n cycles with replacement holds only ~63.2%
distinct cycles, so both unions shrink -- but not at the same rate. A ring is
*seen* in every cycle whose window it is active in, typically several
consecutive ones, and *found* in a strict subset, often exactly one. The
numerator rests on fewer supporting cycles per ring than the denominator, so
dropping a cycle removes rings from `found` faster than from `seen` and the
ratio is biased downward by construction.

THE FIX. Attribute each distinct ring to one owning cycle and carry counts,
making ring recall a ratio of sums -- the same shape as p@k, where duplicating
a cycle duplicates numerator and denominator together.

Pre-registered in `prereg/ring_recall_ci.md`, with the decision rule fixed in
advance: first-appearance ownership ships regardless of whether fractional
attribution gives a nicer interval. It does give a nicer one -- roughly half
the width -- and it is still not what ships.
"""
from __future__ import annotations

import ast
import json
import random
from pathlib import Path

import pytest

from sentinel.eval.bootstrap import (bootstrap_ci, owner_attributed_counts,
                                     ratio_of_sums, union_recall)

ROOT = Path(__file__).resolve().parent.parent
RECALL = ratio_of_sums("rings_found", "rings_owned")


def synthetic(n_cycles=40, n_rings=200, span=4, found_frac=0.30, seed=3):
    """Records with the real mechanism: seen across a span, found in one cycle.

    This is not an arbitrary generator -- the span is what creates the
    asymmetry between the two unions, and without it the defect does not
    appear at all.
    """
    rng = random.Random(seed)
    seen = [set() for _ in range(n_cycles)]
    found = [set() for _ in range(n_cycles)]
    for r in range(n_rings):
        start = rng.randrange(n_cycles - span)
        window = list(range(start, start + span))
        for c in window:
            seen[c].add(r)
        if rng.random() < found_frac:
            found[rng.choice(window)].add(r)
    return [{"seen": s, "found": f} for s, f in zip(seen, found)]


# --- the negative control ---------------------------------------------------

def test_the_old_estimator_fails_on_data_built_from_the_real_mechanism():
    """A fix with no demonstrated failure of what it replaces is not evidence.

    Kill criterion 3. The old interval must land entirely BELOW its own point,
    which is the exact shape of the shipped defect -- not merely be wide.
    """
    recs = synthetic()
    old = bootstrap_ci(recs, union_recall("found", "seen"))
    assert old["hi"] < old["point"], (
        f"the control does not reproduce the defect: point {old['point']} "
        f"in [{old['lo']}, {old['hi']}]")


def test_the_new_estimator_contains_its_point_on_the_same_data():
    recs = synthetic()
    new = bootstrap_ci(owner_attributed_counts(recs, "found", "seen"), RECALL)
    assert new["lo"] <= new["point"] <= new["hi"]


@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("fractional", [False, True])
def test_the_interval_brackets_the_point_across_many_configurations(
        seed, fractional):
    """Kill criterion 2, as a property rather than as one example."""
    rng = random.Random(seed)
    recs = synthetic(n_cycles=rng.choice([12, 25, 40]),
                     n_rings=rng.choice([50, 200, 400]),
                     span=rng.choice([2, 3, 6]),
                     found_frac=rng.choice([0.05, 0.3, 0.8]),
                     seed=seed)
    counts = owner_attributed_counts(recs, "found", "seen",
                                     fractional=fractional)
    r = bootstrap_ci(counts, RECALL)
    assert r["lo"] <= r["point"] <= r["hi"], (seed, fractional, r)


# --- kill criterion 1: the reported number must not move --------------------

@pytest.mark.parametrize("seed", range(12))
@pytest.mark.parametrize("fractional", [False, True])
def test_the_point_estimate_is_identical_to_the_union(seed, fractional):
    """Exact float equality, not approx.

    If owner attribution moved the number, the fix would silently restate a
    published metric while claiming only to repair its interval. The
    pre-registration rejects that outright, so it is asserted at the strongest
    strength available.
    """
    recs = synthetic(found_frac=[0.05, 0.3, 0.8][seed % 3], seed=seed)
    counts = owner_attributed_counts(recs, "found", "seen",
                                     fractional=fractional)
    assert RECALL(counts) == union_recall("found", "seen")(recs)


def test_the_point_is_identical_when_every_ring_is_found():
    """The boundary. Recall 1.0 must stay exactly 1.0, not 0.9999."""
    recs = [{"seen": {1, 2, 3}, "found": {1, 2}},
            {"seen": {2, 3, 4}, "found": {3, 4}}]
    for frac in (False, True):
        assert RECALL(owner_attributed_counts(recs, "found", "seen",
                                              fractional=frac)) == 1.0


def test_no_rings_seen_gives_zero_not_a_crash():
    assert RECALL(owner_attributed_counts([], "found", "seen")) == 0.0
    recs = [{"seen": set(), "found": set()}]
    assert RECALL(owner_attributed_counts(recs, "found", "seen")) == 0.0


# --- the shipped choice is the worse-looking one ----------------------------

def test_fractional_is_narrower_and_is_still_not_what_ships():
    """The pre-registration's whole point, asserted.

    First-appearance ownership is unbalanced -- the first cycle owns every ring
    active at the start -- which inflates variance. Fractional attribution
    balances the blocks and produces a visibly tighter interval. The decision
    rule was fixed before either was measured, so the wider one ships.
    """
    recs = synthetic()
    shipped = bootstrap_ci(owner_attributed_counts(recs, "found", "seen"),
                           RECALL)
    alt = bootstrap_ci(
        owner_attributed_counts(recs, "found", "seen", fractional=True), RECALL)
    assert alt["hi"] - alt["lo"] < shipped["hi"] - shipped["lo"]

    src = (ROOT / "scripts" / "eval_funnel.py").read_text(encoding="utf-8")
    i_ship = src.index('owner_attributed_counts(pairs, "found", "seen")')
    i_alt = src.index("fractional=True")
    assert i_ship < i_alt
    assert 'ci_out[f"ring_recall@{k}"] = result' in src, (
        "the shipped interval must be the first-appearance `result`, not `alt`")


# --- contract details -------------------------------------------------------

def test_a_ring_found_but_never_seen_is_refused():
    """Silently, that would give a recall above 1.0."""
    with pytest.raises(ValueError, match="never seen"):
        owner_attributed_counts([{"seen": {1}, "found": {1, 99}}],
                                "found", "seen")


def test_the_input_records_are_not_mutated():
    recs = synthetic(n_cycles=6, n_rings=20)
    before = [(set(r["seen"]), set(r["found"])) for r in recs]
    owner_attributed_counts(recs, "found", "seen")
    assert [(r["seen"], r["found"]) for r in recs] == before


def test_every_ring_is_owned_exactly_once():
    """What makes the denominator |union seen| rather than a sum of set sizes."""
    recs = synthetic(n_cycles=15, n_rings=60)
    counts = owner_attributed_counts(recs, "found", "seen")
    distinct = len(set().union(*[r["seen"] for r in recs]))
    assert sum(c["rings_owned"] for c in counts) == distinct
    frac = owner_attributed_counts(recs, "found", "seen", fractional=True)
    assert sum(c["rings_owned"] for c in frac) == pytest.approx(distinct)


# --- guards against the defect returning ------------------------------------

def test_the_funnel_asserts_both_kill_criteria_at_runtime():
    """The script must refuse to WRITE a result that fails the pre-registration.

    Without this, a future change to the estimator could reintroduce an
    interval that does not contain its point, and it would ship silently the
    same way this one did.
    """
    src = (ROOT / "scripts" / "eval_funnel.py").read_text(encoding="utf-8")
    assert "Kill criterion 1" in src and "Kill criterion 2" in src
    tree = ast.parse(src)
    asserts = [n for n in ast.walk(tree) if isinstance(n, ast.Assert)]
    assert len(asserts) >= 2


def test_no_committed_interval_fails_to_contain_its_point():
    """The data-level guard, over every result this project has published.

    SELF-RETIRING EXEMPTION. Files written before this fix cannot be repaired
    offline -- `eval_funnel.py` did not persist per-cycle records, which is
    precisely why D5 needed a re-run -- so a result carrying `metric_cis` but
    no `cycle_rows` is known to predate the fix and is skipped. It stops being
    skipped the moment it is regenerated. Nothing else is exempt, and the
    exemption cannot be widened without deleting this docstring.
    """
    stale, checked = [], 0
    for path in sorted((ROOT / "data").glob("*.json")):
        try:
            d = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(d, dict) or "metric_cis" not in d:
            continue
        if "cycle_rows" not in d:
            stale.append(path.name)
            continue
        for name, ci in d["metric_cis"].items():
            checked += 1
            assert ci["lo"] <= ci["point"] <= ci["hi"], (
                f"{path.name}: {name} point {ci['point']} outside "
                f"[{ci['lo']}, {ci['hi']}]")
    if stale:
        pytest.skip(f"pre-fix results, awaiting re-run: {stale}")
    assert checked > 0
