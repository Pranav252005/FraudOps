"""Tests for the Elliptic2 loader and the dataset-agnostic evaluation path.

The real Elliptic2 dataset requires a manual, licensed download and is not
available in CI or this sandbox (see sentinel/data/elliptic2.py). These tests
validate the loader and the static-funnel adapter against a small synthetic
fixture in tests/fixtures/elliptic2_sample/ that matches the dataset's exact
column schema -- it proves the pipeline is correct, not that the real
dataset's numbers reproduce anything.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sentinel.data import elliptic2
from sentinel.eval.dataset import (build_node_ids, edges_to_batch,
                                   ring_membership, run_static_funnel)
from sentinel.schema import Edge

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "elliptic2_sample"


class TestAvailability:
    def test_available_true_for_the_fixture(self):
        assert elliptic2.available(FIXTURE)

    def test_available_false_for_a_missing_directory(self, tmp_path):
        assert not elliptic2.available(tmp_path)

    def test_missing_files_lists_what_is_absent(self, tmp_path):
        missing = elliptic2.missing_files(tmp_path)
        assert set(missing) == set(elliptic2.REQUIRED_FILES)

    def test_load_raises_with_instructions_when_absent(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="elliptic.co/elliptic2"):
            elliptic2.load(tmp_path)


class TestLoad:
    def test_loads_background_graph_size(self):
        data = elliptic2.load(FIXTURE)
        assert data.n_background_nodes == 10
        assert data.n_background_edges == 8

    def test_only_suspicious_components_become_rings(self):
        data = elliptic2.load(FIXTURE)
        assert data.n_licit_components == 1
        assert data.n_suspicious_components == 1
        assert len(data.rings) == 1
        assert data.rings[0].typology == "SUSPICIOUS"

    def test_ring_members_match_the_component(self):
        data = elliptic2.load(FIXTURE)
        ring = data.rings[0]
        assert ring.accounts == {"n1", "n2", "n3"}

    def test_background_edges_are_normalised_edges(self):
        data = elliptic2.load(FIXTURE)
        assert all(isinstance(e, Edge) for e in data.edges)
        pairs = {(e.src, e.dst) for e in data.edges}
        assert ("n0", "n1") in pairs
        assert ("n8", "n9") in pairs

    def test_published_baselines_are_present(self):
        assert "GLASS" in elliptic2.PUBLISHED_BASELINES["test"]
        assert elliptic2.PUBLISHED_BASELINES["n_suspicious"] == 2_763


class TestScaleHandling:
    """The real background graph is 49.3M nodes / 196.2M edges. These pin the
    behaviours that make that survivable; an earlier version materialised
    both files as lists of dicts and would have died on the first real run."""

    def test_reports_scan_vs_retention_so_the_reduction_is_visible(self):
        data = elliptic2.load(FIXTURE)
        assert data.stats["background_edges_scanned"] == 8
        assert data.stats["background_edges_retained"] == data.n_background_edges
        assert 0.0 <= data.stats["background_edge_retention_ratio"] <= 1.0

    def test_induced_filter_drops_edges_far_from_any_labelled_node(self, tmp_path):
        """An edge touching no labelled subgraph carries no evaluation signal
        and must not be retained under the default induced load."""
        for name in elliptic2.REQUIRED_FILES:
            (tmp_path / name).write_text((FIXTURE / name).read_text())
        # n90->n91 touches nothing labelled (labelled = n1,n2,n3,n6,n7,n8)
        with open(tmp_path / "background_edges.csv", "a") as fh:
            fh.write("n90,n91\n")
        induced = elliptic2.load(tmp_path, induced=True)
        full = elliptic2.load(tmp_path, induced=False)
        assert induced.stats["background_edges_scanned"] == 9
        assert induced.n_background_edges == 8, "the far edge must be dropped"
        assert full.n_background_edges == 9, "induced=False keeps everything"

    def test_max_background_edges_caps_a_smoke_run(self):
        data = elliptic2.load(FIXTURE, max_background_edges=3)
        assert data.n_background_edges == 3

    def test_node_count_is_streamed_not_materialised(self):
        """Only the row count of background_nodes.csv is kept -- its 43
        anonymised feature columns are not consumed by anything yet."""
        data = elliptic2.load(FIXTURE)
        assert data.n_background_nodes == 10
        assert data.stats["n_background_nodes_file"] == 10


class TestDatasetAdapter:
    def test_build_node_ids_is_stable_and_dense(self):
        edges = [Edge(ts=None, src="a", dst="b", amount=1.0, currency="BTC"),
                 Edge(ts=None, src="b", dst="c", amount=1.0, currency="BTC")]
        ids = build_node_ids(edges)
        assert ids == {"a": 0, "b": 1, "c": 2}

    def test_edges_to_batch_round_trips_endpoints(self):
        edges = [Edge(ts=None, src="a", dst="b", amount=5.0, currency="BTC")]
        ids = build_node_ids(edges)
        batch = edges_to_batch(edges, ids)
        assert len(batch) == 1
        assert batch.src[0] == ids["a"] and batch.dst[0] == ids["b"]
        assert batch.amount[0] == 5.0

    def test_ring_membership_drops_singletons(self):
        data = elliptic2.load(FIXTURE)
        ids = build_node_ids(data.edges)
        members, typology = ring_membership(data.rings, ids)
        assert len(members) == 1
        assert list(typology.values()) == ["SUSPICIOUS"]

    def test_run_static_funnel_finds_the_seeded_ring(self):
        """n1/n2/n3 form a pass-through chain -- the seed rule should fire,
        and 2-hop expansion from it should recover a candidate covering the
        ring closely enough to pass the hit floor."""
        data = elliptic2.load(FIXTURE)
        tracker, candidates, node_ids = run_static_funnel(data.edges, data.rings)
        assert candidates, "expected at least one candidate from the pass-through seed"
        rows = tracker.rings()
        assert len(rows) == 1
        row = next(iter(rows.values()))
        assert row["seed_reachable"] is True
        assert row["seeded"] is True
        assert row["built"] is True

    def test_run_static_funnel_handles_no_edges(self):
        tracker, candidates, node_ids = run_static_funnel([], [])
        assert candidates == []
        assert tracker.rings() == {}
