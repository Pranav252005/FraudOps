"""Tests for the auditable case-file evidence layer.

`build_transactions` needs a `Stream`-shaped object; a small fake stands in
here rather than the real compiled 4.5M-edge parquet, so these tests are fast
and do not depend on the licensed AMLworld download being present.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from sentinel.cases.case import Case, Lane
from sentinel.cases.evidence import (ROLE_ISOLATED, ROLE_PASS_THROUGH,
                                     ROLE_SINK, ROLE_SOURCE, Transaction,
                                     build_case_file, build_member_roles,
                                     build_transactions, classify_role,
                                     typology_evidence_for)


class FakeStream:
    """Duck-types the subset of sentinel.stream.replay.Stream that
    build_transactions actually touches."""

    def __init__(self, rows):
        # rows = [(ts, src_key, dst_key, amount, currency, channel)]
        self.ts = np.array([r[0] for r in rows], dtype="int32")
        self._src_keys = [r[1] for r in rows]
        self._dst_keys = [r[2] for r in rows]
        self.amount = np.array([r[3] for r in rows], dtype="float64")
        self.currency = [r[4] for r in rows]
        self.channel = [r[5] for r in rows]
        # src/dst columns must be int ids; key() maps id -> key string.
        self.src = np.arange(len(rows), dtype="int32")
        self.dst = np.arange(len(rows), dtype="int32")
        self._keys_by_id = {i: (self._src_keys[i], self._dst_keys[i])
                             for i in range(len(rows))}
        self.epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)

    def when(self, t: int):
        return self.epoch + timedelta(minutes=int(t))


def make_stream(rows):
    """rows = [(ts, src_key, dst_key, amount, currency, channel)]"""
    stream = FakeStream(rows)
    n = len(rows)
    # Use disjoint id ranges for src and dst columns so `key()` can tell them
    # apart unambiguously: src ids are 0..n-1, dst ids are n..2n-1.
    stream.src = np.arange(n, dtype="int32")
    stream.dst = np.arange(n, 2 * n, dtype="int32")
    key_map = {}
    for i, row in enumerate(rows):
        key_map[i] = row[1]
        key_map[n + i] = row[2]
    stream.key = lambda node_id, _m=key_map: _m[node_id]
    return stream


class TestClassifyRole:
    def test_pass_through_needs_both_directions(self):
        assert classify_role(1, 1) == ROLE_PASS_THROUGH

    def test_source_only_sends(self):
        assert classify_role(0, 3) == ROLE_SOURCE

    def test_sink_only_receives(self):
        assert classify_role(2, 0) == ROLE_SINK

    def test_isolated_neither(self):
        assert classify_role(0, 0) == ROLE_ISOLATED


class TestBuildTransactions:
    def test_recovers_rows_inside_window_and_members(self):
        rows = [
            (100, "1:A", "1:B", 500.0, "USD", "wire"),
            (150, "1:B", "1:C", 480.0, "USD", "wire"),
            (900, "1:A", "1:B", 10.0, "USD", "wire"),   # outside window
        ]
        stream = make_stream(rows)
        txns = build_transactions(["1:A", "1:B", "1:C"], opened_t=200,
                                  window_minutes=200, stream=stream)
        assert len(txns) == 2
        assert txns[0].txn_id == "TXN-00000000"
        assert txns[1].txn_id == "TXN-00000001"
        assert txns[0].src == "1:A" and txns[0].dst == "1:B"

    def test_excludes_edges_touching_non_members(self):
        rows = [(100, "1:A", "1:B", 500.0, "USD", "wire"),
                (100, "1:A", "1:X", 500.0, "USD", "wire")]
        stream = make_stream(rows)
        txns = build_transactions(["1:A", "1:B"], opened_t=200,
                                  window_minutes=200, stream=stream)
        assert len(txns) == 1
        assert txns[0].dst == "1:B"

    def test_empty_member_list_yields_no_transactions(self):
        stream = make_stream([(100, "1:A", "1:B", 500.0, "USD", "wire")])
        txns = build_transactions([], opened_t=200, window_minutes=200, stream=stream)
        assert txns == []


class TestBuildMemberRoles:
    def test_roles_from_transaction_ledger(self):
        txns = [Transaction("TXN-1", "t1", "1:A", "1:B", 100.0, "USD", "wire"),
                Transaction("TXN-2", "t2", "1:B", "1:C", 90.0, "USD", "wire")]
        roles = build_member_roles(["1:A", "1:B", "1:C"], txns)
        by_acct = {r.account: r for r in roles}
        assert by_acct["1:A"].role == ROLE_SOURCE
        assert by_acct["1:B"].role == ROLE_PASS_THROUGH
        assert by_acct["1:C"].role == ROLE_SINK
        assert by_acct["1:B"].evidence == ["TXN-1", "TXN-2"]

    def test_pass_through_sorts_first(self):
        txns = [Transaction("TXN-1", "t1", "1:A", "1:B", 100.0, "USD", "wire"),
                Transaction("TXN-2", "t2", "1:B", "1:C", 90.0, "USD", "wire")]
        roles = build_member_roles(["1:A", "1:B", "1:C"], txns)
        assert roles[0].role == ROLE_PASS_THROUGH


class TestTypologyEvidence:
    def test_temporal_cycle_wins(self):
        typ, ev = typology_evidence_for({"has_temporal_cycle": True,
                                         "shortest_temporal_cycle": 3,
                                         "temporal_cycle_coverage": 1.0})
        assert typ == "CYCLE"
        assert any("shortest_temporal_cycle=3" in e for e in ev)

    def test_falls_back_to_cluster(self):
        typ, ev = typology_evidence_for({"n_nodes": 5})
        assert typ == "CLUSTER"


class TestBuildCaseFile:
    def test_full_assembly_is_internally_consistent(self):
        rows = [(100, "1:A", "1:B", 500.0, "USD", "wire"),
                (150, "1:B", "1:C", 480.0, "USD", "wire")]
        stream = make_stream(rows)
        case = Case(id="CASE-00001", opened_at="2024-01-01T00:03:20+00:00",
                   opened_t=200, lane=Lane.PRIMARY, members=["1:A", "1:B", "1:C"],
                   seed=1, score=0.5, contrib={}, features={"n_nodes": 3},
                   motifs={}, subgraph=[])
        cf = build_case_file(case, stream, window_minutes=200, run_id="test-run")
        assert cf.case_id == "CASE-00001"
        assert len(cf.transactions) == 2
        assert {m.account for m in cf.members} == {"1:A", "1:B", "1:C"}
        valid = cf.valid_citation_ids()
        assert "TXN-00000000" in valid and "1:A" in valid and "CASE-00001" in valid
        assert len(cf.provenance) == 4
