"""Phase 2A's logic, on fixtures with a known answer.

The replay itself needs `data/` and ~10 minutes, so it is exercised by running
the script. What is tested here is everything that decides what the numbers
MEAN: the partition, the definition of R, the component split, and the budget
sweep. A bug in any of those produces a plausible catalogue of the wrong rings.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.eval_seed_cheat_diff import (BUDGET_SWEEP, MAX_SEEDS_PROBED,
                                          budget_sweep, cell, ring_components,
                                          summarise)


def _ring(seeded_honest=False, seeded_cheat=True,
          built_honest=False, built_cheat=False, **kw):
    rec = {"cycles": 1, "seeded_honest": seeded_honest,
           "seeded_cheat": seeded_cheat, "built_honest": built_honest,
           "built_cheat": built_cheat, "max_seed_in_ring_honest": 1,
           "max_ring_size": 5, "observations": []}
    rec.update(kw)
    return rec


class FakeGraph:
    """Undirected adjacency, and an `expand` whose bounds actually bite.

    Reimplements expansion rather than importing WindowedGraph so that a test
    fixture cannot be built that accidentally depends on real graph state.
    The bounds semantics mirror `WindowedGraph.expand`: `max_degree` blocks
    traversal THROUGH a node without excluding it, and `max_nodes` truncates.
    """

    def __init__(self, edges):
        self.adj: dict[int, set[int]] = {}
        for a, b in edges:
            self.adj.setdefault(a, set()).add(b)
            self.adj.setdefault(b, set()).add(a)

    def neighbours(self, n):
        return self.adj.get(n, set())

    def expand(self, seeds, hops=2, max_nodes=200, max_degree=50):
        seen = set(seeds)
        frontier = set(seeds)
        for _ in range(hops):
            nxt = set()
            for node in frontier:
                nbrs = self.neighbours(node)
                if len(nbrs) > max_degree:
                    continue
                nxt |= nbrs - seen
            if not nxt:
                break
            room = max_nodes - len(seen)
            if room <= 0:
                break
            if len(nxt) > room:
                nxt = set(sorted(nxt)[:room])
            seen |= nxt
            frontier = nxt
        return seen


class TestThePartition:
    def test_every_ring_falls_in_exactly_one_cell(self):
        rings = {
            1: _ring(seeded_honest=True, built_honest=True, built_cheat=True),
            2: _ring(seeded_honest=True, built_honest=False, built_cheat=True),
            3: _ring(seeded_honest=False, built_honest=False, built_cheat=False),
            4: _ring(seeded_honest=True, built_honest=False, built_cheat=False),
        }
        summary = summarise(rings)
        assert sum(summary["cells"].values()) == len(rings)

    def test_cell_codes_are_four_bits(self):
        rings = {i: _ring(seeded_honest=bool(i % 2), built_cheat=bool(i % 3))
                 for i in range(12)}
        summary = summarise(rings)
        assert all(len(c) == 4 and set(c) <= {"0", "1"}
                   for c in summary["cells"])

    def test_R_is_exactly_seeded_unrecovered_and_rescued(self):
        """The definition of R, which is the whole measurement.

        A fixture with a KNOWN rescue set: three rings qualify and five do not,
        each for a different reason.
        """
        rings = {
            # in R
            10: _ring(seeded_honest=True, built_honest=False, built_cheat=True),
            11: _ring(seeded_honest=True, built_honest=False, built_cheat=True),
            12: _ring(seeded_honest=True, built_honest=False, built_cheat=True),
            # not in R: recovered honestly already
            20: _ring(seeded_honest=True, built_honest=True, built_cheat=True),
            # not in R: never seeded honestly
            21: _ring(seeded_honest=False, built_honest=False, built_cheat=True),
            # not in R: the cheat did not rescue it either
            22: _ring(seeded_honest=True, built_honest=False, built_cheat=False),
            # not in R: recovered honestly but not under the cheat (possible --
            # the cheat changes which candidates survive suppression)
            23: _ring(seeded_honest=True, built_honest=True, built_cheat=False),
            # not in R: nothing happened at all
            24: _ring(seeded_honest=False, built_honest=False, built_cheat=False),
        }
        summary = summarise(rings)
        assert summary["R"] == [10, 11, 12]

    def test_the_comparison_set_excludes_R(self):
        """R and C must be disjoint, or the falsification check compares a set
        with a superset of itself and can never find a difference."""
        rings = {
            10: _ring(seeded_honest=True, built_honest=False, built_cheat=True),
            20: _ring(seeded_honest=True, built_honest=True, built_cheat=True),
        }
        summary = summarise(rings)
        assert not set(summary["R"]) & set(summary["C"])

    def test_cell_is_stable_for_a_known_record(self):
        rec = _ring(seeded_honest=True, seeded_cheat=True,
                    built_honest=False, built_cheat=True)
        assert cell(rec) == "1101"


class TestRingComponents:
    def test_a_connected_ring_is_one_component(self):
        g = FakeGraph([(1, 2), (2, 3), (3, 4)])
        assert [len(c) for c in ring_components(g, {1, 2, 3, 4})] == [4]

    def test_a_split_ring_is_two_components(self):
        """The measurement that discriminates H2 (seed placement) from H1
        (seed count): the edge joining the halves is OUTSIDE the ring, so the
        ring's induced subgraph is disconnected even though the graph is not."""
        g = FakeGraph([(1, 2), (3, 4), (2, 99), (99, 3)])
        comps = ring_components(g, {1, 2, 3, 4})
        assert sorted(len(c) for c in comps) == [2, 2]

    def test_an_isolated_member_is_its_own_component(self):
        g = FakeGraph([(1, 2)])
        comps = ring_components(g, {1, 2, 7})
        assert sorted(len(c) for c in comps) == [1, 2]


class TestBudgetSweep:
    def test_the_hub_guard_is_what_blocks_a_hub_separated_ring(self):
        """Soundness, on a fixture built so exactly one knob is binding.

        The ring is {1, 2, 3}, seeded at 1. Member 2 is adjacent; member 3 sits
        exactly two hops away THROUGH node 99, which carries 62 neighbours --
        above the shipped max_degree of 50. So the hop budget is not what
        binds: relaxing only the hub guard must reach the whole ring.

        Getting this fixture wrong is easy and instructive. A first version put
        member 3 three hops from the seed, so the shipped row failed on the HOP
        budget and `no_hub_guard` failed with it -- the test would have
        reported the guard as innocent regardless of the code.
        """
        edges = [(1, 2), (1, 99), (99, 3)]
        edges += [(99, 1000 + i) for i in range(60)]
        g = FakeGraph(edges)
        members = {1, 2, 3}

        sweep = budget_sweep(g, {1}, members)
        assert sweep["shipped"]["containment"] == pytest.approx(2 / 3, abs=1e-4)
        assert sweep["no_hub_guard"]["containment"] == 1.0
        # and the hop budget is genuinely not the binding constraint here
        assert sweep["three_hops"]["containment"] == pytest.approx(2 / 3, abs=1e-4)

    def test_a_reachable_ring_is_reported_reachable(self):
        g = FakeGraph([(1, 2), (2, 3), (3, 4)])
        sweep = budget_sweep(g, {1}, {1, 2, 3})
        assert sweep["shipped"]["containment"] == 1.0
        assert sweep["shipped"]["is_hit"]

    def test_an_unreachable_ring_is_reported_unreachable(self):
        """Disconnected from the seed at any budget."""
        g = FakeGraph([(1, 2), (50, 51), (51, 52)])
        sweep = budget_sweep(g, {1}, {50, 51, 52})
        for label, *_ in BUDGET_SWEEP:
            assert sweep[label]["containment"] == 0.0, label
            assert not sweep[label]["is_hit"], label

    def test_containment_and_is_hit_are_reported_separately(self):
        """Full containment does not imply a hit: the Jaccard floor can still
        reject a candidate that dragged in bystanders. Conflating them would
        hide exactly the 5c 'recovers the ring and then buries it' failure."""
        edges = [(1, 2), (2, 3)] + [(2, 500 + i) for i in range(40)]
        g = FakeGraph(edges)
        members = {1, 2, 3}
        sweep = budget_sweep(g, {1}, members)
        assert sweep["shipped"]["containment"] == 1.0
        assert not sweep["shipped"]["is_hit"]

    def test_every_budget_row_is_evaluated(self):
        g = FakeGraph([(1, 2), (2, 3)])
        sweep = budget_sweep(g, {1}, {1, 2, 3})
        assert set(sweep) == {label for label, *_ in BUDGET_SWEEP}

    def test_the_seed_probe_cap_is_applied(self):
        """The cap must bite, or its presence in the output is misleading."""
        g = FakeGraph([(i, i + 1) for i in range(20)])
        calls = []
        orig = g.expand

        def counting(seeds, **kw):
            calls.append(tuple(seeds))
            return orig(seeds, **kw)

        g.expand = counting
        budget_sweep(g, set(range(10)), {0, 1, 2})
        distinct = {c[0] for c in calls}
        assert len(distinct) == MAX_SEEDS_PROBED


RESULT = ROOT / "data" / "eval_seed_cheat_diff.json"


@pytest.mark.skipif(not RESULT.exists(),
                    reason="needs data/eval_seed_cheat_diff.json")
class TestAgainstTheRealOutput:
    """Checks the plan requires be run against the measurement, not a fixture."""

    @pytest.fixture(scope="class")
    @classmethod
    def out(cls):
        import json
        return json.loads(RESULT.read_text(encoding="utf-8"))

    def test_the_partition_is_exhaustive(self, out):
        assert sum(out["cells"].values()) == out["n_rings"]

    def test_the_partition_is_disjoint(self, out):
        """Each ring contributes to exactly one cell, so the cell counts and
        the ring count cannot both be right unless the cells are disjoint."""
        assert len(out["rings"]) == out["n_rings"]
        assert sum(out["cells"].values()) == len(out["rings"])

    def test_R_and_C_are_disjoint_and_within_the_partition(self, out):
        R, C = set(out["R"]), set(out["C"])
        assert not R & C
        assert len(R) + len(C) <= out["n_rings"]

    def test_it_reconciles_with_the_published_89_percent(self, out):
        """docs/HANDOFF.md 5b reports 230 of 259 active rings seeded.

        A partition that disagreed with the published figure would be
        describing a different pool, and nothing downstream of it would be
        quotable. This is the check that makes the catalogue trustworthy.
        """
        assert out["n_rings"] == 259
        seeded = sum(n for cell, n in out["cells"].items() if cell[0] == "1")
        assert seeded == 230
        assert out["seeded_honest_rate"] == pytest.approx(230 / 259, abs=1e-6)

    def test_R_matches_its_own_definition_in_the_stored_rings(self, out):
        """Recompute R from the per-ring records and compare to the stored
        list, so a bug in `summarise` cannot travel into the write-up."""
        recomputed = sorted(
            int(r) for r, rec in out["rings"].items()
            if rec["seeded_honest"] and not rec["built_honest"]
            and rec["built_cheat"])
        assert recomputed == out["R"]

    def test_the_falsification_check_was_actually_run(self, out):
        """The plan requires it before interpreting. Its result is recorded
        either way -- an empty list is a finding, not a missing field."""
        assert "measurements_differing" in out


def test_the_shipped_row_matches_sentinel_config():
    """The control row must BE the shipped configuration.

    If these drift apart, "the shipped budget fails on this ring" becomes a
    statement about a configuration nothing runs.
    """
    from sentinel.config import (EXPAND_HOPS, EXPAND_MAX_DEGREE,
                                 EXPAND_MAX_NODES)

    shipped = next(row for row in BUDGET_SWEEP if row[0] == "shipped")
    assert shipped[1:] == (EXPAND_HOPS, EXPAND_MAX_NODES, EXPAND_MAX_DEGREE)
