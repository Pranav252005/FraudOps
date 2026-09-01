"""Phase D: the coverage definition, and the shape of the test around it.

The predictions themselves are measured by `scripts/eval_fragmentation.py`.
What is asserted here is that the measurement means what the pre-registration
says it means -- an exclusion is an exclusion and not a zero, the expansion is
the shipped one, and the AMLworld interval names a clustering Rule 5 allows.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sentinel import config
from sentinel.eval import identity as ident
from sentinel.generators import synthetic_identity as gen
from scripts import eval_fragmentation as frag

ROOT = Path(__file__).resolve().parents[1]


class _PathGraph:
    """0-1-2-...-n: the shape a fully rotated chain degenerates to."""

    def __init__(self, n):
        self.n = n

    def neighbours(self, node):
        return {v for v in (node - 1, node + 1) if 0 <= v < self.n}

    def expand(self, seeds, hops, max_nodes, max_degree):
        seen = set(seeds)
        frontier = set(seeds)
        for _ in range(hops):
            nxt = set()
            for u in frontier:
                nxt |= self.neighbours(u)
            frontier = nxt - seen
            seen |= nxt
        return seen


class TestTheQuantity:
    def test_an_unseeded_group_is_excluded_not_scored_zero(self):
        """With no seed there is nothing to have coverage from.

        Scoring it zero would fold a seeding failure into a reach measurement,
        which is the exact conflation the funnel exists to prevent.
        """
        assert frag.coverage_of({1, 2, 3}, set(), _PathGraph(10)) is None

    def test_coverage_is_what_two_hops_can_see(self):
        """A 2-hop expansion from one end of a path of six sees three of it."""
        group = set(range(6))
        assert frag.coverage_of(group, {0}, _PathGraph(6)) == pytest.approx(3 / 6)

    def test_a_clique_is_fully_covered(self):
        """The low-rotation end: one value spans the cluster, one hop reaches
        everything."""
        class Clique:
            def neighbours(self, node):
                return {v for v in range(5) if v != node}

            def expand(self, seeds, hops, max_nodes, max_degree):
                return set(range(5))

        assert frag.coverage_of(set(range(5)), {0}, Clique()) == 1.0

    def test_coverage_uses_the_shipped_expansion_constants(self):
        """Not a private set of parameters: the queue's own hops and hub guard.

        A coverage number measured under looser expansion would describe a
        system nobody ships.
        """
        src = Path(frag.__file__).read_text(encoding="utf-8")
        assert "config.EXPAND_HOPS" in src
        assert "config.EXPAND_MAX_NODES" in src
        assert "config.EXPAND_MAX_DEGREE" in src


class TestTheMechanism:
    def test_a_path_has_the_diameter_of_a_path(self):
        comps, diam = frag.induced_shape(set(range(6)), _PathGraph(6))
        assert comps == 1
        assert diam == 5

    def test_components_count_the_pieces(self):
        class Split:
            def neighbours(self, node):
                return {1} if node == 0 else ({0} if node == 1 else set())

        comps, _ = frag.induced_shape({0, 1, 2}, Split())
        assert comps == 2


class TestPreregTranscription:
    def test_the_grid_is_the_pre_registered_one(self):
        assert frag.PRIMARY_SIZE == 8
        assert frag.OVERLAPS == (0.0, 0.1)

    def test_the_too_easy_arm_is_excluded(self):
        """overlap=0.2 at cluster_size=8 failed Phase A's kill rule.

        Including it here would be the retune-after-seeing that `prereg/`
        exists to stop, and it would be invisible in the output.
        """
        assert 0.2 not in frag.OVERLAPS
        assert 0.2 in gen.OVERLAPS, "the generator still offers it; Phase D declines it"

    def test_the_prereg_names_all_three_predictions(self):
        text = (ROOT / "prereg" / "synthetic_identity_fragmentation.md").read_text(
            encoding="utf-8")
        for marker in ("P1", "P2", "P3"):
            assert marker in text
        assert "P2 is the one that decides" in text


class TestIntervalsNameTheirClustering:
    def test_the_identity_interval_names_the_world(self):
        r = frag.identity_config(0.5, 3, 0.1, worlds=3)
        assert r["coverage"]["ci_method"] == "world_clustered_bootstrap"

    def test_the_paired_delta_pairs_the_same_worlds(self):
        """Both arms differ only in rotation_rate, so world 3's background is
        the same background on both sides. Pairing removes variance that is not
        what the prediction is about."""
        hi = frag.identity_config(0.7, 5, 0.1, worlds=4)
        lo = frag.identity_config(0.3, 5, 0.1, worlds=4)
        d = frag.paired_delta(hi, lo)
        assert d["n_pairs"] == 4
        assert d["ci_method"] == "paired_world_clustered_bootstrap"

    def test_the_amlworld_arm_reports_the_wider_of_two_clusterings(self):
        """Rule 5. AMLworld coverage trials nest within rings, so both are
        computed and the wider is reported; the name is one `Metric` accepts."""
        from sentinel.report.metric import CI_METHODS
        src = Path(frag.__file__).read_text(encoding="utf-8")
        assert "ring_clustered" in src and "cycle_clustered" in src
        assert "wider_of_cycle_and_ring_clustered_bootstrap" in CI_METHODS, (
            "the AMLworld arm reports under this name, so Metric must accept "
            "it -- otherwise the number cannot be rendered under rule 5")
        assert "wider_of_cycle_and_ring_clustered_bootstrap" in src

    def test_the_identity_clustering_is_deliberately_not_a_metric_name(self):
        """World-clustered is a real unit here and not one Metric accepts.

        That is on purpose: no Phase A-D identity number is a candidate-level
        p@k, and refusing to render them through `Metric` is what stops one
        being mistaken for one later.
        """
        from sentinel.report.metric import CI_METHODS
        assert "world_clustered_bootstrap" not in CI_METHODS
        assert "paired_world_clustered_bootstrap" not in CI_METHODS


class TestTheDomainsStayApart:
    def test_the_side_by_side_is_stratified_never_pooled(self):
        src = Path(frag.__file__).read_text(encoding="utf-8")
        assert "stratify_by_dataset" in src
        assert "require_poolable" not in src
