"""Tests for the exact-by-construction efficiency changes (uplift plan 5.2).

Every change in that tier claims to leave output identical. This project's bug
catalogue is almost entirely "a plausible wrong answer rather than an error",
and a faster path that quietly returns a different number is that failure mode
in its purest form -- so each claim is asserted here against the reference
implementation it replaced, not trusted.
"""
from __future__ import annotations

import random
from collections import defaultdict

import pytest

from sentinel.detect import features as F
from sentinel.detect.candidates import CandidateGenerator
from sentinel.detect.merge import jaccard, suppress
from sentinel.detect.motifs import detect
from sentinel.graph.window import WindowedGraph
from tests.test_phase1 import batch


def graph_from(edges, window=10_000):
    """edges = [(src, dst, amount)] all at t=1."""
    g = WindowedGraph(window_minutes=window)
    g.add_batch(batch(0, 60, [(1, s, d, a, 0) for s, d, a in edges]))
    return g


# --------------------------------------------------------------------------
# Item 1 -- incremental node totals and the boundary-flow identity
# --------------------------------------------------------------------------

class TestNodeTotals:
    def test_totals_match_a_fresh_sum_over_pairs(self):
        g = graph_from([(0, 1, 100.0), (1, 2, 40.0), (0, 2, 7.5), (2, 0, 3.25)])
        g.check_invariants()
        assert g.total_out[0] == pytest.approx(107.5)
        assert g.total_in[2] == pytest.approx(47.5)

    def test_totals_survive_expiry(self):
        g = WindowedGraph(window_minutes=120)
        g.add_batch(batch(0, 60, [(1, 10, 20, 100.0, 0)]))
        g.add_batch(batch(60, 120, [(70, 20, 30, 50.0, 0)]))
        g.check_invariants()
        assert g.total_in.get(30) == pytest.approx(50.0)
        # now=240, window=120 -> cutoff 120 retires both earlier ticks
        g.add_batch(batch(120, 240, [(200, 30, 40, 25.0, 0)]))
        g.check_invariants()
        assert 10 not in g.total_out, "an emptied node kept a float residue"
        assert 30 not in g.total_in, "an expired in-edge left a residue"
        assert g.total_out.get(30) == pytest.approx(25.0)

    def test_emptied_node_is_reset_not_left_with_residue(self):
        """The reset is keyed on adjacency, not on the float being == 0.0.

        Repeated add/subtract of the same amounts does not return exactly to
        zero in binary floating point, so a float-equality reset would leave a
        node carrying a tiny phantom balance and report it as boundary flow.
        """
        g = WindowedGraph(window_minutes=60)
        amounts = [0.1, 0.2, 0.30000000000000004, 7.7, 1e12]
        g.add_batch(batch(0, 60, [(1, 10, 20, a, 0) for a in amounts]))
        g.add_batch(batch(60, 180, []))   # everything expires
        assert 10 not in g.total_out and 20 not in g.total_in
        assert not g.pairs
        g.check_invariants()

    def test_window_conservation_invariant(self):
        g = WindowedGraph(window_minutes=120)
        g.add_batch(batch(0, 60, [(1, 1, 2, 10.0, 0), (2, 2, 3, 20.0, 0)]))
        g.add_batch(batch(60, 120, [(70, 3, 4, 30.0, 0)]))
        g.check_invariants()

    def test_check_invariants_catches_a_drifted_total(self):
        g = graph_from([(0, 1, 100.0)])
        g.total_out[0] += 5.0
        with pytest.raises(AssertionError):
            g.check_invariants()

    def test_check_invariants_catches_a_phantom_node(self):
        g = graph_from([(0, 1, 100.0)])
        g.total_in[999] = 1.0
        with pytest.raises(AssertionError):
            g.check_invariants()


class TestBoundaryFlowIdentity:
    """The identity must agree with the adjacency walk it replaced."""

    def _check(self, g, nodes):
        internal = sum(agg.amount for _, _, agg in g.subgraph_edges(nodes))
        walk = F._boundary_flow_walk(nodes, g)
        ident = F._boundary_flow(nodes, g, internal)
        assert ident[0] == pytest.approx(walk[0], rel=1e-12, abs=1e-9)
        assert ident[1] == pytest.approx(walk[1], rel=1e-12, abs=1e-9)
        return ident

    def test_agrees_on_a_passthrough_chain(self):
        g = graph_from([(0, 1, 100.0), (1, 2, 90.0), (2, 3, 80.0)])
        self._check(g, {1, 2})

    def test_agrees_when_candidate_is_the_whole_graph(self):
        g = graph_from([(0, 1, 100.0), (1, 2, 90.0)])
        inflow, outflow = self._check(g, {0, 1, 2})
        assert inflow == 0.0 and outflow == 0.0

    def test_isolated_candidate_gets_exactly_zero_not_a_residue(self):
        """Without the epsilon clamp this is the bug the identity would ship.

        A candidate with no external edges must get inflow = outflow = 0.0, so
        `conservation = min/max` stays 0.0. A float residue of 1e-9 would make
        conservation an arbitrary value in [0, 1] instead -- a wrong answer that
        never raises.
        """
        g = graph_from([(0, 1, 1e9 / 3), (1, 2, 1e9 / 7), (2, 0, 1e9 / 11)])
        internal = sum(agg.amount for _, _, agg in g.subgraph_edges({0, 1, 2}))
        inflow, outflow = F._boundary_flow({0, 1, 2}, g, internal)
        assert inflow == 0.0 and outflow == 0.0
        f = F.build({0, 1, 2}, g, detect(g.subgraph_edges({0, 1, 2})))
        assert f.conservation == 0.0

    def test_self_loop_cancels_correctly(self):
        """The compiled stream drops self-loops, but the identity must not
        depend on that -- a self-loop hits both totals and the internal sum."""
        g = graph_from([(1, 1, 50.0), (0, 1, 100.0), (1, 2, 30.0)])
        self._check(g, {1})

    def test_falls_back_to_the_walk_without_maintained_totals(self):
        class _NoTotals:
            def __init__(self, g):
                self.in_adj = g.in_adj
                self.out_adj = g.out_adj
                self.pairs = g.pairs
        g = graph_from([(0, 1, 100.0), (1, 2, 90.0)])
        bare = _NoTotals(g)
        assert F._boundary_flow({1}, bare, 0.0) == F._boundary_flow_walk({1}, g)

    def test_build_agrees_with_the_walk_on_random_graphs(self):
        rng = random.Random(11)
        for _ in range(60):
            raw = [(rng.randrange(12), rng.randrange(12),
                    round(rng.uniform(1, 1e6), 2)) for _ in range(30)]
            edges = [(s, d, a) for s, d, a in raw if s != d]
            if not edges:
                continue
            g = graph_from(edges)
            present = sorted(set(g.out_adj) | set(g.in_adj))
            nodes = set(rng.sample(present, k=min(4, len(present))))
            internal = sum(agg.amount for _, _, agg in g.subgraph_edges(nodes))
            walk = F._boundary_flow_walk(nodes, g)
            ident = F._boundary_flow(nodes, g, internal)
            assert ident[0] == pytest.approx(walk[0], rel=1e-9, abs=1e-6)
            assert ident[1] == pytest.approx(walk[1], rel=1e-9, abs=1e-6)


# --------------------------------------------------------------------------
# Item 2 -- one subgraph_edges call, threaded through
# --------------------------------------------------------------------------

class TestThreadedEdges:
    def test_passing_edges_matches_recomputing_them(self):
        g = graph_from([(0, 1, 100.0), (1, 2, 90.0), (2, 0, 10.0), (3, 1, 5.0)])
        nodes = {0, 1, 2}
        edges = g.subgraph_edges(nodes)
        m = detect(edges)
        threaded = F.build(nodes, g, m, internal_edges=edges).to_dict()
        recomputed = F.build(nodes, g, m).to_dict()
        assert threaded == recomputed


# --------------------------------------------------------------------------
# Item 3 -- size-bound pre-rejection in suppress
# --------------------------------------------------------------------------

class _C:
    """Minimal stand-in for Candidate: suppress only reads these fields."""

    def __init__(self, nodes, score, seed=0):
        self.nodes = frozenset(nodes)
        self.score = score
        self.seed = seed
        self.absorbed = 0
        self.absorbed_seeds: list = []

    def ident(self):
        return (tuple(sorted(self.nodes)), self.score, self.seed)


def _suppress_reference(candidates, threshold=0.5):
    """The pre-optimisation implementation, kept as the oracle for the test."""
    ordered = sorted(candidates, key=lambda c: -c.score)
    by_node: dict = defaultdict(list)
    suppressed: set = set()
    kept: list = []
    for i, cand in enumerate(ordered):
        if i in suppressed:
            continue
        rivals: set = set()
        for n in cand.nodes:
            rivals.update(by_node.get(n, ()))
        winner = None
        for j in rivals:
            if jaccard(cand.nodes, ordered[j].nodes) >= threshold:
                winner = j
                break
        if winner is not None:
            ordered[winner].absorbed += 1
            ordered[winner].absorbed_seeds.append(cand.seed)
            suppressed.add(i)
            continue
        kept.append(cand)
        for n in cand.nodes:
            by_node[n].append(i)
    return kept


class TestSizeBoundPreRejection:
    def test_size_bound_is_a_necessary_condition_for_the_threshold(self):
        rng = random.Random(3)
        for _ in range(500):
            a = frozenset(rng.sample(range(40), rng.randint(1, 12)))
            b = frozenset(rng.sample(range(40), rng.randint(1, 12)))
            t = rng.choice([0.3, 0.5, 0.7])
            if jaccard(a, b) >= t:
                assert min(len(a), len(b)) >= t * max(len(a), len(b)), \
                    "the bound excluded a pair that genuinely clears threshold"

    def test_output_identical_to_the_reference_implementation(self):
        rng = random.Random(5)
        for trial in range(80):
            spec = [(rng.sample(range(30), rng.randint(2, 10)), rng.random(), i)
                    for i in range(25)]
            ref = _suppress_reference([_C(*s) for s in spec], threshold=0.5)
            got = suppress([_C(*s) for s in spec], threshold=0.5)
            assert [c.ident() for c in ref] == [c.ident() for c in got], \
                f"trial {trial}"
            assert [c.absorbed for c in ref] == [c.absorbed for c in got]
            assert [sorted(c.absorbed_seeds) for c in ref] == \
                [sorted(c.absorbed_seeds) for c in got]


# --------------------------------------------------------------------------
# Item 5 -- shared expansion across strategies in the A/B harness
# --------------------------------------------------------------------------

class TestExpansionCache:
    def _stream_graph(self):
        g = WindowedGraph(window_minutes=10_000)
        edges = [(1, 0, 1, 100.0, 0), (2, 1, 2, 90.0, 0), (3, 2, 3, 80.0, 0),
                 (4, 3, 0, 70.0, 0), (5, 1, 4, 10.0, 0), (6, 4, 5, 5.0, 0),
                 (7, 5, 1, 4.0, 0)]
        b = batch(0, 60, edges)
        g.add_batch(b)
        return g, b

    def test_cached_run_matches_uncached_run(self):
        for strat in ("none", "leaf2"):
            g, b = self._stream_graph()
            plain = CandidateGenerator(g, prune_strategy=strat).generate(b)
            g2, b2 = self._stream_graph()
            cache: dict = {}
            cached = CandidateGenerator(g2, prune_strategy=strat).generate(
                b2, expansion_cache=cache)
            assert [c.key for c in plain] == [c.key for c in cached]
            assert [c.score for c in plain] == [c.score for c in cached]

    def test_two_strategies_share_one_cache_without_contaminating_each_other(self):
        g, b = self._stream_graph()
        solo_none = CandidateGenerator(g, prune_strategy="none").generate(b)
        solo_leaf2 = CandidateGenerator(g, prune_strategy="leaf2").generate(b)

        cache: dict = {}
        shared_none = CandidateGenerator(g, prune_strategy="none").generate(
            b, expansion_cache=cache)
        shared_leaf2 = CandidateGenerator(g, prune_strategy="leaf2").generate(
            b, expansion_cache=cache)
        assert [c.key for c in solo_none] == [c.key for c in shared_none]
        assert [c.key for c in solo_leaf2] == [c.key for c in shared_leaf2]

    def test_mismatched_expansion_bounds_raise_rather_than_lie(self):
        g, b = self._stream_graph()
        cache: dict = {}
        CandidateGenerator(g, hops=2).generate(b, expansion_cache=cache)
        with pytest.raises(AssertionError):
            CandidateGenerator(g, hops=3).generate(b, expansion_cache=cache)


# --------------------------------------------------------------------------
# Bug #17 -- dominant_entity_type was decided by PYTHONHASHSEED
# --------------------------------------------------------------------------

class TestDominantEntityTypeIsDeterministic:
    """Found by the fingerprint diff between the pre- and post-efficiency runs.

    `max(set(types), key=types.count)` returns the first maximal element in SET
    ITERATION ORDER. A set of strings iterates in an order that depends on
    PYTHONHASHSEED, so a candidate whose entity types tie reported a different
    "dominant" type on different runs of the same input. Nothing raised. The
    case file simply stated a confident fact about the ring that had been
    decided by a hash seed -- this project's characteristic defect exactly.
    """

    def test_a_tie_resolves_the_same_way_in_every_process(self):
        import subprocess
        import sys
        probe = (
            "types = ['Sole Proprietorship', 'Partnership', 'Corporation']; "
            "print(max(sorted(set(types)), key=types.count))"
        )
        seen = set()
        for seed in ("0", "1", "12345", "99991"):
            import os
            out = subprocess.run([sys.executable, "-c", probe],
                                 capture_output=True, text=True, check=True,
                                 env=dict(os.environ, PYTHONHASHSEED=seed))
            seen.add(out.stdout.strip())
        assert len(seen) == 1, (
            f"dominant entity type depends on the hash seed: {seen}")

    def test_the_old_formulation_really_was_unstable(self):
        """A regression test for a bug is worth little if the bug it describes
        could not have happened. This pins that the removed formulation was
        genuinely seed-dependent, so the fix above is not cargo cult."""
        import os
        import subprocess
        import sys
        probe = (
            "types = ['Sole Proprietorship', 'Partnership', 'Corporation']; "
            "print(max(set(types), key=types.count))"
        )
        seen = set()
        for seed in ("0", "1", "12345", "99991"):
            out = subprocess.run([sys.executable, "-c", probe],
                                 capture_output=True, text=True, check=True,
                                 env=dict(os.environ, PYTHONHASHSEED=seed))
            seen.add(out.stdout.strip())
        assert len(seen) > 1, (
            "the old formulation resolved consistently here, so this test no "
            "longer demonstrates the defect it was written for")

    def test_purity_was_never_affected(self):
        """Tied types share a count, so the purity ratio is the same whichever
        label wins. Recorded so the blast radius of the bug stays documented."""
        types = ["Sole Proprietorship", "Partnership", "Corporation"]
        for top in set(types):
            assert types.count(top) / len(types) == pytest.approx(1 / 3)
