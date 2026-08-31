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
        """Rings 0 and 1 are on the TRAIN side of the partition, and neither
        may appear in test.

        Ring 1 contributes no training RECORD: its only candidate lands at
        t=20, which is split_t, and train is bounded by the cutoff. That is
        the documented cost of closing the all-positive-group defect -- a ring
        whose first appearance is exactly the cutoff has nothing before it --
        so this asserts the partition, which is the property the split
        guarantees, rather than record presence, which it does not.
        """
        records = [self._rec(0, 10), self._rec(1, 20), self._rec(2, 30)]
        ring_first_t = {0: 10, 1: 20, 2: 30}
        train, test, split_t = ring_time_split(records, ring_first_t, fraction=0.67)
        assert split_t == 20
        assert {r["ring"] for r in train} == {0}
        assert {r["ring"] for r in test} == {2}

    def test_train_ring_positives_after_the_cutoff_are_dropped_not_kept(self):
        """The defect this rule closes, stated as the behaviour that closes it.

        Ring 0 is a train ring that keeps producing candidates after the
        cutoff. Under the previous rule those post-cutoff positives stayed in
        train, and since negatives split on time with no exception, they formed
        an all-positive query group that contributed zero gradient to a
        listwise objective while remaining fully visible to a pointwise one.
        They are now dropped. They must NOT reappear in test -- that would be
        the ring leak the split exists to close.
        """
        records = [self._rec(0, 10), self._rec(0, 90), self._rec(1, 50),
                   self._rec(None, 5), self._rec(None, 95)]
        ring_first_t = {0: 10, 1: 50}
        train, test, split_t = ring_time_split(records, ring_first_t, fraction=0.5)
        assert split_t == 10
        assert [(r["ring"], r["t"]) for r in train] == [(None, 5)]
        assert (0, 90) not in [(r["ring"], r["t"]) for r in test]

    def test_post_cutoff_cycles_contribute_no_training_group_at_all(self):
        """The mechanism behind the 18-of-34 finding, at fixture scale.

        A cycle at or after the cutoff used to contribute its positives to
        train and its negatives to test, producing an all-positive group. It
        must now contribute nothing to train. This asserts the mechanism --
        that no training group exists at or after split_t -- rather than the
        downstream property "no group is all-positive", which is a property of
        the real pool and is asserted in scripts/eval_ranker.py against it.
        See docs/inventory/query_groups.md.
        """
        records = [self._rec(0, 10), self._rec(None, 10),
                   self._rec(0, 40), self._rec(None, 40),
                   self._rec(0, 80),                      # would be all-positive
                   self._rec(1, 90), self._rec(None, 90)]
        ring_first_t = {0: 10, 1: 90}
        train, test, split_t = ring_time_split(records, ring_first_t, fraction=0.5)
        assert split_t == 10
        assert all(r["t"] < split_t for r in train)
        # The t=80 positive is gone from both sides: dropped, not leaked.
        assert (0, 80) not in [(r["ring"], r["t"]) for r in train + test]

    def test_train_strictly_precedes_test_over_the_whole_split(self):
        """Not just over the negative pool.

        The previous rule could only guarantee time-ordering on negatives,
        because a train ring kept its post-cutoff positives. This is the
        stronger statement that replaces it.
        """
        records = [self._rec(0, 10), self._rec(0, 90), self._rec(1, 50),
                   self._rec(2, 70), self._rec(None, 5), self._rec(None, 95)]
        ring_first_t = {0: 10, 1: 50, 2: 70}
        train, test, split_t = ring_time_split(records, ring_first_t, fraction=0.34)
        assert train and test
        assert max(r["t"] for r in train) < split_t <= min(r["t"] for r in test)
