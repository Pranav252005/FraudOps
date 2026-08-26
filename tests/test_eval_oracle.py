"""Tests for the oracle diagnostic's pure logic: labelling and the ring/time
split. The LightGBM training itself needs the compiled AMLworld stream and is
exercised by running `scripts/eval_oracle.py` directly, not by the suite.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.eval_oracle import label_candidate, ring_time_split


class TestLabelCandidate:
    def test_labels_the_covering_ring(self):
        rings = {0: {1, 2, 3}, 1: {10, 11, 12}}
        assert label_candidate({1, 2, 3}, rings) == 0

    def test_none_when_no_ring_covered(self):
        rings = {0: {1, 2, 3}}
        assert label_candidate({100, 101}, rings) is None

    def test_below_hit_floor_is_none(self):
        rings = {0: {1, 2, 3, 4, 5}}
        assert label_candidate({1, 200, 201}, rings) is None


class TestRingTimeSplit:
    def _rec(self, ring, t):
        class _F:
            pass
        class _C:
            features = _F()
        return {"cand": _C(), "ring": ring, "t": t}

    def test_a_ring_is_never_split_across_train_and_test(self):
        records = [self._rec(0, 10), self._rec(0, 50), self._rec(0, 90),
                   self._rec(1, 20), self._rec(1, 60)]
        ring_first_t = {0: 10, 1: 20}
        train, test, split_t = ring_time_split(records, ring_first_t, fraction=0.5)
        train_rings = {r["ring"] for r in train}
        test_rings = {r["ring"] for r in test}
        assert not (train_rings & test_rings)

    def test_negatives_split_purely_by_time(self):
        records = [self._rec(0, 10), self._rec(None, 5), self._rec(None, 95)]
        ring_first_t = {0: 10}
        train, test, split_t = ring_time_split(records, ring_first_t, fraction=1.0)
        # fraction=1.0 -> the only ring goes entirely to train
        neg_train = [r for r in train if r["ring"] is None]
        neg_test = [r for r in test if r["ring"] is None]
        assert all(r["t"] < split_t for r in neg_train)
        assert all(r["t"] >= split_t for r in neg_test)

    def test_empty_input(self):
        train, test, split_t = ring_time_split([], {})
        assert train == [] and test == [] and split_t == 0

    def test_all_rings_before_cutoff_go_to_train(self):
        records = [self._rec(0, 10), self._rec(1, 20), self._rec(2, 30)]
        ring_first_t = {0: 10, 1: 20, 2: 30}
        train, test, split_t = ring_time_split(records, ring_first_t, fraction=0.67)
        train_rings = {r["ring"] for r in train}
        assert 0 in train_rings and 1 in train_rings
