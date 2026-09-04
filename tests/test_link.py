"""B1: the fragment linker's witness must be a witness, not a proximity score.

Pre-registered in `prereg/fragment_linking.md`. The properties here are the
ones the experiment's validity rests on — that a link requires an actual
bridge, that the bridge is time-ordered, that the merge excludes the bridge,
and that the bounds bind — rather than the ones its result rests on.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.detect import link as L  # noqa: E402


class Agg:
    def __init__(self, first_t, last_t=None):
        self.first_t = first_t
        self.last_t = first_t if last_t is None else last_t


class FakeGraph:
    def __init__(self, edges):
        self.out_adj = defaultdict(set)
        self.in_adj = defaultdict(set)
        self.pairs = {}
        for a, b, t in edges:
            self.out_adj[a].add(b)
            self.in_adj[b].add(a)
            self.pairs[(a << 32) | b] = Agg(t)

    def neighbours(self, n):
        return self.out_adj.get(n, set()) | self.in_adj.get(n, set())


class Cand:
    def __init__(self, nodes, key):
        self.nodes = frozenset(nodes)
        self.key = key


def two_fragments(t_in=10, t_out=20, bridge=(4,)):
    """1-2-3 and 5-6-7, joined only through `bridge`."""
    edges = [(1, 2, 1), (2, 3, 2), (5, 6, 30), (6, 7, 31)]
    for x in bridge:
        edges += [(3, x, t_in), (x, 5, t_out)]
    return edges


C12 = [Cand([1, 2, 3], "a"), Cand([5, 6, 7], "b")]


def test_a_time_ordered_bridge_links_two_fragments():
    got = L.find_links(C12, FakeGraph(two_fragments()))
    assert len(got) == 1
    i, j, bridge = got[0]
    assert (i, j) == (0, 1)
    assert bridge == frozenset({4})


def test_a_reversed_bridge_does_not_link():
    """The intermediary paid the second fragment BEFORE the first paid it, so
    no value could have travelled the path. Same logic as
    `motifs.is_temporally_valid`, and the reason a structural link alone is
    not evidence."""
    assert L.find_links(C12, FakeGraph(two_fragments(t_in=20, t_out=10))) == []


def test_proximity_without_a_bridge_does_not_link():
    """The distinction the queue item asks for: a witness, not nearness.

    Both fragments touch node 9, but only as a *receiver* — 9 sends to
    neither, so there is no C1 -> x -> C2 path and no link.
    """
    edges = [(1, 2, 1), (2, 3, 2), (5, 6, 30), (6, 7, 31),
             (3, 9, 5), (5, 9, 6)]
    assert L.find_links(C12, FakeGraph(edges)) == []


def test_the_merge_excludes_the_bridge():
    """Pre-registered, and the reason is stated in the module docstring: the
    intermediaries are evidence that two fragments belong together, not a
    claim that they are ring members."""
    g = FakeGraph(two_fragments())
    (i, j, bridge), = L.find_links(C12, g)
    merged = C12[i].nodes | C12[j].nodes
    assert merged == {1, 2, 3, 5, 6, 7}
    assert not (merged & bridge)


def test_a_bridge_wider_than_the_bound_is_refused():
    wide = two_fragments(bridge=(41, 42, 43, 44))
    assert L.find_links(C12, FakeGraph(wide), max_bridge=3) == []
    assert L.find_links(C12, FakeGraph(wide), max_bridge=4)


def test_a_merge_over_the_size_bound_is_refused():
    big = Cand(range(100, 140), "big")
    edges = two_fragments() + [(101, 4, 10)]
    got = L.find_links([C12[0], big], FakeGraph(edges), max_merged=40)
    assert got == []


def test_containment_is_not_a_link():
    """If one candidate already contains the other there is nothing to
    assemble, and emitting the merge would be emitting a duplicate."""
    inner = Cand([1, 2, 3], "in")
    outer = Cand([1, 2, 3, 5, 6, 7], "out")
    assert L.find_links([inner, outer], FakeGraph(two_fragments())) == []


def test_a_hub_intermediary_is_excluded_by_the_degree_guard():
    """An intermediary with hundreds of counterparties is a correspondent
    account; a 'link' through one says nothing about the two candidates."""
    edges = two_fragments()
    edges += [(4, 900 + k, 50) for k in range(80)]     # node 4 becomes a hub
    assert L.find_links(C12, FakeGraph(edges), max_degree=50) == []
    assert L.find_links(C12, FakeGraph(edges), max_degree=500)


def test_a_thoroughfare_intermediary_is_refused():
    """One node bridging very many candidates is a thoroughfare, not a
    witness, and pair generation through it is quadratic."""
    n = L.MAX_WITNESS_FANOUT + 5
    cands, edges = [], []
    for i in range(n):
        a, b = 1000 + 10 * i, 1001 + 10 * i
        cands.append(Cand([a, b, b + 1], f"c{i}"))
        edges += [(a, b, 1), (b, b + 1, 2), (b + 1, 7777, 10), (7777, a, 20)]
    assert L.find_links(cands, FakeGraph(edges)) == []


def test_the_candidate_pool_is_bounded():
    """The witness search is quadratic in the pool, so the bound must bind."""
    cands = [Cand([i * 10, i * 10 + 1, i * 10 + 2], f"c{i}") for i in range(50)]
    edges = []
    for i in range(50):
        a = i * 10
        edges += [(a, a + 1, 1), (a + 1, a + 2, 2)]
    edges += [(2, 999, 10), (999, 490, 20)]     # links candidate 0 to 49
    g = FakeGraph(edges)
    assert L.find_links(cands, g, max_candidates=50)
    assert L.find_links(cands, g, max_candidates=10) == []


def test_links_are_deterministic():
    """Witness discovery walks dict iteration order over set-derived
    sequences, so the output is sorted. Without that the emitted merge set
    would depend on PYTHONHASHSEED and the determinism gate would fail for the
    experiment's own reasons."""
    g = FakeGraph(two_fragments(bridge=(4, 8)))
    runs = {tuple(L.find_links(C12, g)) for _ in range(5)}
    assert len(runs) == 1


def test_bounds_are_the_pre_registered_values():
    """Fixed in prereg/fragment_linking.md before the first run. Asserted so a
    later change to any of them is a reviewed line in a diff rather than a
    quiet loosening mid-experiment, which kill criterion 5 forbids."""
    assert L.MAX_CANDIDATES == 200
    assert L.MAX_BRIDGE == 3
    assert L.MAX_MERGED_NODES == 40
