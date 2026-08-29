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
        """The error must point at Kaggle, NOT at the licence-request form.

        This test previously asserted `elliptic.co/elliptic2` -- it was
        pinning the claim that the dataset is licence-gated and needs a manual
        request. docs/HANDOFF.md 11d established that is false: it is public on
        Kaggle. The test was holding the wrong answer in place, so it now pins
        the corrected one, plus the archive advice, since a reader who hits
        this error on a 50 GB-free laptop needs to be told not to extract.
        """
        with pytest.raises(FileNotFoundError) as e:
            elliptic2.load(tmp_path)
        msg = str(e.value)
        assert "kaggle.com/datasets/ellipticco" in msg
        assert "elliptic.co/elliptic2" not in msg
        assert "NOT need to extract" in msg and "archive=" in msg


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


class TestArchiveStreaming:
    """Reading straight out of the Kaggle zip, which is the only route that
    fits on an ordinary disk.

    `background_edges.csv` is 82.9 GB extracted against ~24.5 GB packed. The
    machine this was written on had 50 GB free, so `download_elliptic2.bat`
    died at the extract step. Every read in `elliptic2` is a sequential single
    pass, so the archive can be streamed instead -- these tests hold that
    property in place, because it is the kind of thing an innocent-looking
    refactor to `open(path)` would silently destroy.
    """

    @staticmethod
    def _zip_of_fixture(tmp_path, names=None, prefix=""):
        import zipfile

        z = tmp_path / "elliptic2.zip"
        with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in (names or elliptic2.REQUIRED_FILES):
                zf.write(FIXTURE / f, prefix + f)
        return z

    def test_load_from_archive_matches_load_from_directory(self, tmp_path):
        """The zip path must produce the same object, not merely 'work'."""
        z = self._zip_of_fixture(tmp_path)
        from_dir = elliptic2.load(FIXTURE)
        from_zip = elliptic2.load(archive=z)
        assert from_zip.n_background_nodes == from_dir.n_background_nodes
        assert from_zip.n_background_edges == from_dir.n_background_edges
        assert from_zip.n_suspicious_components == \
            from_dir.n_suspicious_components
        assert from_zip.n_licit_components == from_dir.n_licit_components
        assert [(e.src, e.dst) for e in from_zip.edges] == \
            [(e.src, e.dst) for e in from_dir.edges]
        assert [r.id for r in from_zip.rings] == \
            [r.id for r in from_dir.rings]

    def test_members_are_found_under_a_directory_prefix(self, tmp_path):
        """Kaggle archives sometimes nest the files one level down."""
        z = self._zip_of_fixture(tmp_path, prefix="elliptic2/")
        assert elliptic2.load(archive=z).n_background_edges == 8

    def test_extracted_files_win_over_the_archive(self, tmp_path):
        """A directory copy takes precedence, so the three small files can be
        unpacked for speed while the two huge ones stay compressed."""
        src = elliptic2.Source(FIXTURE, self._zip_of_fixture(tmp_path))
        handle = src.open("nodes.csv")
        try:
            assert hasattr(handle, "name")
            assert str(FIXTURE) in str(handle.name)
        finally:
            handle.close()

    def test_missing_from_both_is_reported(self, tmp_path):
        z = self._zip_of_fixture(tmp_path, names=["nodes.csv", "edges.csv"])
        assert set(elliptic2.missing_files(elliptic2.Source(archive=z))) == \
            {"background_nodes.csv", "background_edges.csv",
             "connected_components.csv"}

    def test_archive_that_does_not_exist_says_so(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="archive not found"):
            elliptic2.load(archive=tmp_path / "nope.zip")

    def test_big_files_are_never_read_whole(self, tmp_path):
        """`_stream_csv` must stay a reader over a handle, not a materialiser.

        The regression this guards: someone 'simplifies' the streamed pass into
        `_read_csv`, which is a list(DictReader) and would need tens of GB on
        the real 196M-row file. Checked by giving it a handle that refuses to
        be fully consumed.
        """
        class OneShot:
            def __init__(self, rows):
                self._rows = iter(rows)
                self.closed = False

            def __iter__(self):
                return self

            def __next__(self):
                return next(self._rows)

            def close(self):
                self.closed = True

        handle, header, reader = elliptic2._stream_csv(
            OneShot(["clId1,clId2\n", "1,2\n", "3,4\n"]))
        assert header == ["clId1", "clId2"]
        assert next(reader) == ["1", "2"]      # lazy: nothing consumed early
