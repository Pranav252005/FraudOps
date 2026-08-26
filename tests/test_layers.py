"""Tests for the layered structure detectors.

These target the two typologies the project scores worst on — BIPARTITE at 3%
and STACK at 7% — so the shapes are built exactly as AMLworld defines them and
the expected block densities are asserted directly rather than inferred from a
score moving.
"""
from __future__ import annotations

import networkx as nx
import pytest

from sentinel.detect.layers import (HIGH_BLOCKS, MULE, RECEIVER, SENDER,
                                    assign_levels, block_densities, profile)
from sentinel.detect.motifs import detect
from tests.test_phase2 import graph_from


def dg(edges):
    G = nx.DiGraph()
    for a, b in edges:
        G.add_edge(a, b)
    return G


def stack_graph(n_src=2, n_mid=3, n_dst=2):
    """The three-layer shape: sources -> mules -> receivers, fully connected."""
    src = list(range(n_src))
    mid = list(range(10, 10 + n_mid))
    dst = list(range(20, 20 + n_dst))
    return dg([(s, m) for s in src for m in mid]
              + [(m, d) for m in mid for d in dst])


def bipartite_graph(n_src=3, n_dst=3):
    """Two layers: sources straight to receivers, no intermediary."""
    return dg([(s, d) for s in range(n_src) for d in range(20, 20 + n_dst)])


class TestLevelAssignment:
    def test_roles_by_direction(self):
        levels = assign_levels(dg([(0, 1), (1, 2)]))
        assert levels[0] == SENDER
        assert levels[1] == MULE
        assert levels[2] == RECEIVER

    def test_node_doing_both_is_a_mule(self):
        """Pass-through is the mule signature, so it wins over either role."""
        assert assign_levels(dg([(0, 1), (1, 2), (3, 1)]))[1] == MULE

    def test_cycle_members_are_all_mules(self):
        levels = assign_levels(dg([(0, 1), (1, 2), (2, 0)]))
        assert set(levels.values()) == {MULE}

    def test_isolated_nodes_are_dropped_not_defaulted(self):
        G = dg([(0, 1)])
        G.add_node(99)
        assert 99 not in assign_levels(G)


class TestBlockDensities:
    def test_pure_stack_fills_only_the_high_blocks(self):
        G = stack_graph()
        blocks = block_densities(G, assign_levels(G))
        for k in HIGH_BLOCKS:
            assert blocks[k] == pytest.approx(1.0)
        for k, v in blocks.items():
            if k not in HIGH_BLOCKS:
                assert v == pytest.approx(0.0)

    def test_single_member_level_has_no_internal_density(self):
        """Must report 0 rather than dividing by zero possible edges."""
        G = dg([(0, 1), (1, 2)])
        blocks = block_densities(G, assign_levels(G))
        assert blocks[(SENDER, SENDER)] == 0.0

    def test_empty_levels_are_zero(self):
        G = bipartite_graph()
        blocks = block_densities(G, assign_levels(G))
        assert blocks[(SENDER, MULE)] == 0.0
        assert blocks[(MULE, RECEIVER)] == 0.0


class TestGargAml:
    def test_pure_smurfing_scores_one(self):
        p = profile(stack_graph())
        assert p.gargaml == pytest.approx(1.0)
        assert p.high_density == pytest.approx(1.0)
        assert p.low_density == pytest.approx(0.0)

    def test_bipartite_is_not_smurfing(self):
        """No mule layer means no smurfing, so the score must not be positive."""
        assert profile(bipartite_graph()).gargaml <= 0.0

    def test_noise_in_other_blocks_lowers_the_score(self):
        clean = profile(stack_graph()).gargaml
        G = stack_graph()
        G.add_edge(10, 11)          # mule talking to mule
        assert profile(G).gargaml < clean

    def test_score_stays_in_range(self):
        for G in (stack_graph(), bipartite_graph(), dg([(0, 1)]),
                  dg([(0, 1), (1, 2), (2, 0)])):
            assert -1.0 <= profile(G).gargaml <= 1.0

    def test_empty_graph(self):
        p = profile(nx.DiGraph())
        assert p.gargaml == 0.0 and p.depth == 0


class TestTypologyDetectors:
    def test_stack_is_detected(self):
        p = profile(stack_graph())
        assert p.depth == 3
        assert p.stack == pytest.approx(1.0)
        assert p.n_senders == 2 and p.n_mules == 3 and p.n_receivers == 2

    def test_bipartite_is_detected(self):
        p = profile(bipartite_graph())
        assert p.depth == 2
        assert p.bipartite == pytest.approx(1.0)
        assert p.stack == 0.0

    def test_bipartite_needs_width_on_both_sides(self):
        """A single fan-out is a different typology with its own detector."""
        assert profile(dg([(0, d) for d in (20, 21, 22)])).bipartite == 0.0

    def test_stack_is_bounded_by_its_weaker_hop(self):
        """A strong first hop into a dead end is not a stack."""
        G = stack_graph()
        G.remove_edge(10, 20)
        G.remove_edge(11, 20)
        assert profile(G).stack < 1.0

    def test_stack_and_bipartite_are_mutually_exclusive_shapes(self):
        s, b = profile(stack_graph()), profile(bipartite_graph())
        assert s.stack > 0 and s.bipartite == 0
        assert b.bipartite > 0 and b.stack == 0


class TestIntegration:
    def test_motifs_carry_the_layer_profile(self):
        g = graph_from([(s, m, 10.0) for s in (0, 1) for m in (10, 11, 12)]
                       + [(m, d, 10.0) for m in (10, 11, 12) for d in (20, 21)])
        nodes = {0, 1, 10, 11, 12, 20, 21}
        m = detect(g.subgraph_edges(nodes))
        assert m.layers.stack == pytest.approx(1.0)
        assert m.layers.gargaml == pytest.approx(1.0)

    def test_layer_profile_reaches_the_feature_vector(self):
        from sentinel.detect import features as F
        g = graph_from([(s, m, 10.0) for s in (0, 1) for m in (10, 11, 12)]
                       + [(m, d, 10.0) for m in (10, 11, 12) for d in (20, 21)])
        nodes = {0, 1, 10, 11, 12, 20, 21}
        f = F.build(nodes, g, detect(g.subgraph_edges(nodes)))
        assert f.gargaml == pytest.approx(1.0)
        assert f.stack_score == pytest.approx(1.0)
        assert f.layer_depth == 3

    def test_stack_shape_outscores_a_plain_chain(self):
        from sentinel.detect import features as F
        stack_edges = ([(s, m, 10.0) for s in (0, 1) for m in (10, 11, 12)]
                       + [(m, d, 10.0) for m in (10, 11, 12) for d in (20, 21)])
        gs = graph_from(stack_edges)
        ns = {0, 1, 10, 11, 12, 20, 21}
        gc = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 3, 10.0)])
        nc = {0, 1, 2, 3}
        s_stack = F.score(F.build(ns, gs, detect(gs.subgraph_edges(ns))))[0]
        s_chain = F.score(F.build(nc, gc, detect(gc.subgraph_edges(nc))))[0]
        assert s_stack > s_chain

    def test_negative_gargaml_does_not_subtract_from_the_score(self):
        """The score is a blend of non-negative terms; -1 must not drag it down."""
        from sentinel.detect import features as F
        f = F.Features(n_nodes=4, gargaml=-1.0)
        s, contrib = F.score(f)
        assert contrib["gargaml"] == 0.0
        assert s >= 0.0
