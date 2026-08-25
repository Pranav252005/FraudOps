"""Phase 2 tests: motif detection, features and the candidate funnel.

Motifs are built on hand-constructed graphs whose shape is known exactly, so a
detector that drifts is caught by construction rather than by a metric moving.
The typology names match the AMLworld ground-truth labels deliberately -- these
are the shapes the evaluation is scored against.
"""
from __future__ import annotations

import numpy as np
import pytest

from sentinel.detect import features as F
from sentinel.detect.candidates import CandidateGenerator, canonical_key
from sentinel.detect.motifs import (MAX_EXACT_NODES, build_digraph, detect,
                                    find_cycles, find_scatter_gather)
from sentinel.graph.window import WindowedGraph
from tests.test_phase1 import batch


def graph_from(edges, window=10_000):
    """edges = [(src, dst, amount)] all at t=1."""
    g = WindowedGraph(window_minutes=window)
    g.add_batch(batch(0, 60, [(1, s, d, a, 0) for s, d, a in edges]))
    return g


def motifs_of(g, nodes):
    return detect(g.subgraph_edges(set(nodes)))


# --------------------------------------------------------------------------
# Motif shapes, named after the ground-truth typologies
# --------------------------------------------------------------------------

class TestMotifs:
    def test_fan_out(self):
        g = graph_from([(0, i, 100.0) for i in range(1, 6)])
        m = motifs_of(g, range(6))
        assert m.max_out_degree == 5
        assert m.fan_out_hub == 0
        assert m.n_cycles == 0

    def test_fan_in(self):
        g = graph_from([(i, 0, 100.0) for i in range(1, 6)])
        m = motifs_of(g, range(6))
        assert m.max_in_degree == 5
        assert m.fan_in_hub == 0

    def test_cycle_is_found_and_measured(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 3, 10.0), (3, 0, 10.0)])
        m = motifs_of(g, range(4))
        assert m.n_cycles == 1
        assert m.shortest_cycle == 4
        assert m.nodes_in_cycles == 4

    def test_two_node_cycle(self):
        g = graph_from([(0, 1, 10.0), (1, 0, 10.0)])
        m = motifs_of(g, [0, 1])
        assert m.n_cycles == 1
        assert m.shortest_cycle == 2

    def test_acyclic_chain_has_no_cycle(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 3, 10.0)])
        m = motifs_of(g, range(4))
        assert m.n_cycles == 0
        assert m.nodes_in_cycles == 0

    def test_scatter_gather(self):
        """0 -> {1,2,3} -> 9 is the layering shape."""
        g = graph_from([(0, 1, 10.0), (0, 2, 10.0), (0, 3, 10.0),
                        (1, 9, 10.0), (2, 9, 10.0), (3, 9, 10.0)])
        m = motifs_of(g, [0, 1, 2, 3, 9])
        assert m.scatter_gather == 3
        assert (0, 9, 3) in m.sg_pairs

    def test_scatter_gather_needs_width(self):
        g = graph_from([(0, 1, 10.0), (1, 9, 10.0)])
        m = motifs_of(g, [0, 1, 9])
        assert m.scatter_gather == 0

    def test_scatter_gather_ignores_return_to_source(self):
        """A -> S -> A is a cycle, not a scatter-gather."""
        g = graph_from([(0, 1, 10.0), (0, 2, 10.0), (1, 0, 10.0), (2, 0, 10.0)])
        sg = find_scatter_gather(build_digraph(g.subgraph_edges({0, 1, 2})))
        assert all(a != b for a, b, _ in sg)

    def test_passthrough_count(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0)])
        m = motifs_of(g, [0, 1, 2])
        assert m.n_passthrough == 1  # only node 1 both receives and sends

    def test_cycle_length_bound(self):
        g = graph_from([(i, (i + 1) % 12, 10.0) for i in range(12)])
        assert find_cycles(build_digraph(g.subgraph_edges(set(range(12)))),
                           max_len=8) == []

    def test_large_subgraph_is_marked_inexact_not_empty(self):
        """A skipped enumeration must not read as 'no structure found'."""
        n = MAX_EXACT_NODES + 10
        g = graph_from([(i, i + 1, 10.0) for i in range(n)])
        m = motifs_of(g, range(n + 1))
        assert m.exact is False
        assert m.n_nodes > MAX_EXACT_NODES

    def test_empty_subgraph(self):
        assert detect([]).n_nodes == 0


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------

class TestFeatures:
    def test_conservation_is_measured_at_the_boundary(self):
        """100 in, 100 out, circulating internally -- the layering signature."""
        g = graph_from([(90, 0, 100.0),          # inflow from outside
                        (0, 1, 100.0), (1, 2, 100.0),   # internal
                        (2, 91, 100.0)])         # outflow to outside
        nodes = {0, 1, 2}
        f = F.build(nodes, g, motifs_of(g, nodes))
        assert f.inflow == pytest.approx(100.0)
        assert f.outflow == pytest.approx(100.0)
        assert f.conservation == pytest.approx(1.0)
        assert f.internal == pytest.approx(200.0)

    def test_conservation_low_when_flow_is_one_sided(self):
        g = graph_from([(90, 0, 100.0), (0, 1, 50.0), (1, 91, 5.0)])
        f = F.build({0, 1}, g, motifs_of(g, {0, 1}))
        assert f.conservation < 0.1

    def test_no_boundary_flow_is_zero_not_one(self):
        """An isolated candidate must not score a perfect conservation."""
        g = graph_from([(0, 1, 10.0), (1, 0, 10.0)])
        f = F.build({0, 1}, g, motifs_of(g, {0, 1}))
        assert f.inflow == 0 and f.outflow == 0
        assert f.conservation == 0.0

    def test_passthrough_ratio(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0)])
        f = F.build({0, 1, 2}, g, motifs_of(g, {0, 1, 2}))
        assert f.passthrough_ratio == pytest.approx(1 / 3)

    def test_round_amount_detection(self):
        assert F.is_round(1000.0) and F.is_round(500.0)
        assert not F.is_round(2848.96)
        assert not F.is_round(50.0), "below the floor, too common to be signal"

    def test_empty_candidate(self):
        g = graph_from([(0, 1, 10.0)])
        f = F.build(set(), g, motifs_of(g, set()))
        assert f.n_nodes == 0 and f.conservation == 0.0


class TestScore:
    def test_score_is_bounded(self):
        f = F.Features(has_cycle=True, shortest_cycle=3, cycle_coverage=1.0,
                       conservation=1.0, scatter_gather_width=9,
                       passthrough_ratio=1.0, n_countries=9,
                       burstiness=1000.0, round_amount_ratio=1.0)
        s, _ = F.score(f)
        assert 0.0 <= s <= 1.0
        assert s == pytest.approx(sum(F.WEIGHTS.values()), abs=1e-9)

    def test_empty_features_score_zero(self):
        s, contrib = F.score(F.Features())
        assert s == 0.0
        assert all(v == 0.0 for v in contrib.values())

    def test_contributions_sum_to_score(self):
        f = F.Features(has_cycle=True, shortest_cycle=4, cycle_coverage=0.5,
                       conservation=0.8, passthrough_ratio=0.6, n_countries=3)
        s, contrib = F.score(f)
        assert sum(contrib.values()) == pytest.approx(s)

    def test_ring_shaped_candidate_outscores_a_chain(self):
        cyc = F.Features(has_cycle=True, shortest_cycle=3, cycle_coverage=1.0,
                         conservation=0.95, passthrough_ratio=1.0, n_countries=4)
        chain = F.Features(has_cycle=False, conservation=0.1,
                           passthrough_ratio=0.3, n_countries=1)
        assert F.score(cyc)[0] > F.score(chain)[0]

    def test_channel_is_never_a_feature(self):
        """The 7.3x ACH leak stays out of scoring, by construction."""
        assert "channel" not in F.WEIGHTS
        assert not hasattr(F.Features(), "channel")


# --------------------------------------------------------------------------
# The funnel
# --------------------------------------------------------------------------

class TestCandidateGenerator:
    def test_canonical_key_is_order_independent(self):
        assert canonical_key([3, 1, 2]) == canonical_key([1, 2, 3])
        assert canonical_key([1, 2]) != canonical_key([1, 2, 3])

    def test_seeds_are_passthrough_only(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0)])
        gen = CandidateGenerator(g)
        b = batch(0, 60, [(1, 0, 1, 10.0, 0), (1, 1, 2, 10.0, 0)])
        assert gen.seeds(b) == {1}

    def test_generates_and_scores_a_cycle(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 0, 10.0)])
        gen = CandidateGenerator(g)
        b = batch(0, 60, [(1, 0, 1, 10.0, 0), (1, 1, 2, 10.0, 0), (1, 2, 0, 10.0, 0)])
        cands = gen.generate(b)
        assert cands
        assert cands[0].features.has_cycle
        assert cands[0].score > 0

    def test_dedup_across_overlapping_seeds(self):
        """Neighbours share neighbourhoods; without dedup this rescores a lot."""
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 0, 10.0)])
        gen = CandidateGenerator(g)
        b = batch(0, 60, [(1, 0, 1, 10.0, 0), (1, 1, 2, 10.0, 0), (1, 2, 0, 10.0, 0)])
        cands = gen.generate(b)
        assert len(cands) == 1, "all three seeds reach the same member set"
        assert gen.stats["deduped"] == 2

    def test_results_are_rank_ordered(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 0, 10.0),
                        (10, 11, 10.0), (11, 12, 10.0)])
        gen = CandidateGenerator(g)
        b = batch(0, 60, [(1, s, d, 10.0, 0) for s, d in
                          [(0, 1), (1, 2), (2, 0), (10, 11), (11, 12)]])
        cands = gen.generate(b)
        scores = [c.score for c in cands]
        assert scores == sorted(scores, reverse=True)

    def test_too_small_candidates_are_rejected(self):
        g = graph_from([(0, 1, 10.0)])
        gen = CandidateGenerator(g)
        assert gen.generate(batch(0, 60, [(1, 0, 1, 10.0, 0)])) == []


# --------------------------------------------------------------------------
# Overlap suppression
# --------------------------------------------------------------------------

from sentinel.detect.candidates import Candidate
from sentinel.detect.merge import jaccard, suppress


def cand(nodes, score, seed=0):
    return Candidate(key=canonical_key(nodes), nodes=frozenset(nodes),
                     seed=seed, t=0, score=score)


class TestJaccard:
    def test_values(self):
        assert jaccard(frozenset({1, 2, 3}), frozenset({2, 3, 4})) == pytest.approx(0.5)
        assert jaccard(frozenset({1, 2}), frozenset({1, 2})) == 1.0
        assert jaccard(frozenset({1}), frozenset({2})) == 0.0

    def test_empty_is_zero_not_nan(self):
        assert jaccard(frozenset(), frozenset()) == 0.0
        assert jaccard(frozenset({1}), frozenset()) == 0.0


class TestSuppress:
    def test_keeps_highest_scoring_of_an_overlapping_pair(self):
        a = cand([1, 2, 3, 4], 0.9, seed=1)
        b = cand([1, 2, 3, 5], 0.4, seed=2)
        kept = suppress([a, b], threshold=0.5)
        assert kept == [a]
        assert a.absorbed == 1
        assert a.absorbed_seeds == [2]

    def test_keeps_both_when_overlap_is_below_threshold(self):
        a = cand([1, 2, 3, 4], 0.9)
        b = cand([4, 5, 6, 7], 0.8)
        assert len(suppress([a, b], threshold=0.5)) == 2

    def test_disjoint_candidates_are_untouched(self):
        a, b = cand([1, 2, 3], 0.9), cand([7, 8, 9], 0.8)
        kept = suppress([a, b], threshold=0.5)
        assert len(kept) == 2
        assert a.absorbed == 0 and b.absorbed == 0

    def test_output_stays_score_ordered(self):
        cs = [cand([i, i + 100, i + 200], 0.1 * i) for i in range(1, 6)]
        kept = suppress(cs, threshold=0.5)
        assert [c.score for c in kept] == sorted([c.score for c in kept], reverse=True)

    def test_chain_of_overlaps_collapses_to_the_best(self):
        a = cand([1, 2, 3, 4], 0.9, seed=1)
        b = cand([1, 2, 3, 4], 0.8, seed=2)
        c = cand([1, 2, 3, 4], 0.7, seed=3)
        kept = suppress([c, a, b], threshold=0.5)
        assert kept == [a]
        assert a.absorbed == 2
        assert sorted(a.absorbed_seeds) == [2, 3]

    def test_nothing_is_lost_when_threshold_is_impossible(self):
        cs = [cand([1, 2, 3], 0.9), cand([1, 2, 3], 0.5)]
        assert len(suppress(cs, threshold=1.01)) == 2

    def test_empty_input(self):
        assert suppress([], threshold=0.5) == []


class TestGeneratorMerging:
    def test_generate_suppresses_overlapping_neighbourhoods(self):
        g = graph_from([(0, 1, 10.0), (1, 2, 10.0), (2, 3, 10.0), (3, 0, 10.0)])
        b = batch(0, 60, [(1, s, d, 10.0, 0) for s, d in
                          [(0, 1), (1, 2), (2, 3), (3, 0)]])
        gen = CandidateGenerator(g)
        merged = gen.generate(b)
        gen2 = CandidateGenerator(g)
        raw = gen2.generate(b, merge_threshold=None)
        assert len(merged) <= len(raw)
        assert gen.stats["suppressed"] == len(raw) - len(merged)
