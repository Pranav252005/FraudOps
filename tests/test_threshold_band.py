"""The threshold band's arithmetic must be the shipped metric, not a lookalike.

`scripts/eval_threshold_band.py` re-expresses `is_hit` over four precomputed
integers so nine grid cells can share one pass over the node sets. That is a
reimplementation of the metric every headline in this repository depends on,
and a reimplementation that silently disagreed would produce a confident band
around a different question.

So it is checked against the real thing on random inputs rather than trusted.
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sentinel.eval.funnel import HIT_SHARE, MIN_JACCARD, is_hit  # noqa: E402

import eval_threshold_band as band  # noqa: E402


def test_the_grid_contains_the_shipped_thresholds_as_its_centre():
    """A band whose centre is not the shipped pair is a band around nothing."""
    assert band.SHIPPED == (HIT_SHARE, MIN_JACCARD)
    assert band.SHIPPED[0] in band.HIT_SHARES
    assert band.SHIPPED[1] in band.MIN_JACCARDS
    assert len(band.HIT_SHARES) == 3 and len(band.MIN_JACCARDS) == 3


def test_the_grid_brackets_the_shipped_pair_on_both_axes():
    """Looser and tighter, not three values all on one side of the shipped one.

    A grid that only loosened would answer "what could we have claimed", which
    is the question this experiment exists to NOT be accused of asking.
    """
    assert min(band.HIT_SHARES) < HIT_SHARE < max(band.HIT_SHARES)
    assert min(band.MIN_JACCARDS) < MIN_JACCARD < max(band.MIN_JACCARDS)


def test_precomputed_predicate_agrees_with_the_shipped_is_hit():
    """Random node sets, every grid cell, against `sentinel.eval.funnel.is_hit`.

    Universe kept small (0..24) so intersections are common; sizes kept small
    so ring/candidate ratios span the interesting range rather than sitting at
    one extreme.
    """
    rng = random.Random(20260904)
    cells = [(hs, mj) for hs in band.HIT_SHARES for mj in band.MIN_JACCARDS]
    checked = agreed = 0
    for _ in range(3000):
        cand = set(rng.sample(range(25), rng.randint(1, 14)))
        ring = set(rng.sample(range(25), rng.randint(2, 12)))
        inter = len(cand & ring)
        for hs, mj in cells:
            want = is_hit(cand, ring, hit_share=hs, min_jaccard=mj)
            got = band.is_hit_cell(inter, len(ring), len(cand), hs, mj)
            assert want == got, (cand, ring, hs, mj, want, got)
            checked += 1
            agreed += int(want)
    # Both outcomes must actually occur, or the agreement above is agreement
    # about a constant.
    assert 0 < agreed < checked, (agreed, checked)


def test_overlaps_reports_every_touched_ring_and_only_those():
    rings = {1: {1, 2, 3}, 2: {4, 5}, 3: {90, 91}}
    got = band.overlaps({1, 2, 4, 7}, rings)
    assert {r for r, *_ in got} == {1, 2}
    by_ring = {r: (inter, nr, nc) for r, inter, nr, nc in got}
    assert by_ring[1] == (2, 3, 4)
    assert by_ring[2] == (1, 2, 4)


def test_cell_ids_are_unique_and_stable():
    ids = [band.cell_id(hs, mj)
           for hs in band.HIT_SHARES for mj in band.MIN_JACCARDS]
    assert len(set(ids)) == 9
    assert band.cell_id(0.5, 0.3) == "hs0.5_mj0.3"
