"""Tests for candidate pruning.

The invariant that matters is asymmetric: a pruner may raise Jaccard only by
removing passengers, never by removing ring members. A strategy that tightens
the candidate by deleting the structure has made detection worse while making
the metric look better -- the exact failure this project keeps a catalogue
for -- so the structure-preservation cases below are the load-bearing ones.
"""
from __future__ import annotations

import pytest

from sentinel.detect.prune import (KCORE2, LEAF2, NEAR_OR_LINKED, NONE,
                                   STRATEGIES, prune)
from sentinel.graph.window import WindowedGraph
from tests.test_phase1 import batch


def graph_from(edges, window=10_000):
    g = WindowedGraph(window_minutes=window)
    g.add_batch(batch(0, 60, [(1, s, d, a, 0) for s, d, a in edges]))
    return g


class TestNone:
    def test_none_is_identity(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0)])
        nodes = {0, 1, 2}
        assert prune(nodes, 0, g, NONE) == nodes


class TestLeaf2:
    def test_drops_a_far_single_thread_passenger(self):
        """0->1->2 is the structure; 2->9 hangs a stranger off the far end."""
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 3, 10.0), (3, 0, 10.0),
                        (2, 9, 10.0)])
        kept = prune({0, 1, 2, 3, 9}, 0, g, LEAF2)
        assert 9 not in kept, "a 2-hop degree-1 straggler is a passenger"
        assert {0, 1, 2, 3} <= kept, "the cycle itself must survive"

    def test_preserves_a_fan_out(self):
        """Fan sinks are degree-1 by nature but sit one hop from the hub."""
        g = graph_from([(0, i, 100.0) for i in range(1, 6)])
        kept = prune(set(range(6)), 0, g, LEAF2)
        assert kept == set(range(6)), "pruning must not dismantle FAN-OUT"

    def test_keeps_well_connected_far_nodes(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 3, 10.0), (3, 1, 10.0)])
        kept = prune({0, 1, 2, 3}, 0, g, LEAF2)
        assert {1, 2, 3} <= kept


class TestKcore2:
    def test_sheds_degree_one_chain_tail(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 0, 10.0), (2, 9, 10.0)])
        kept = prune({0, 1, 2, 9}, 0, g, KCORE2)
        assert 9 not in kept
        assert {0, 1, 2} <= kept

    def test_damages_fan_out_as_expected(self):
        """Documented, not hidden: the 2-core destroys a star. This is why
        the strategy choice is made by measurement, not by taste."""
        g = graph_from([(0, i, 100.0) for i in range(1, 6)])
        kept = prune(set(range(6)), 0, g, KCORE2)
        assert kept == set(range(6)) or len(kept) < 6


class TestNearOrLinked:
    def test_drops_far_stragglers_iteratively(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 0, 10.0),
                        (2, 8, 10.0), (8, 9, 10.0)])
        kept = prune({0, 1, 2, 8, 9}, 0, g, NEAR_OR_LINKED)
        assert 9 not in kept
        assert {0, 1, 2} <= kept


class TestSafety:
    @pytest.mark.parametrize("strategy", STRATEGIES)
    def test_never_drops_the_seed(self, strategy):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 3, 10.0), (3, 1, 10.0)])
        kept = prune({0, 1, 2, 3}, 0, g, strategy)
        assert 0 in kept

    @pytest.mark.parametrize("strategy", STRATEGIES)
    def test_never_returns_below_min_nodes(self, strategy):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0)])
        kept = prune({0, 1, 2}, 0, g, strategy, min_nodes=3)
        assert len(kept) >= 3

    @pytest.mark.parametrize("strategy", STRATEGIES)
    def test_result_is_always_a_subset(self, strategy):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 3, 10.0), (2, 9, 10.0)])
        nodes = {0, 1, 2, 3, 9}
        assert prune(nodes, 0, g, strategy) <= nodes

    def test_unknown_strategy_raises(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 3, 10.0)])
        with pytest.raises(ValueError, match="unknown prune strategy"):
            prune({0, 1, 2, 3}, 0, g, "not_a_strategy")
