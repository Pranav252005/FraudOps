"""Dataset-agnostic evaluation: the same funnel/candidate pipeline over any
(edges, rings) pair, whether that is AMLworld's time-ordered stream or
Elliptic2's static labelled subgraphs.

AMLworld is temporal: `scripts/eval_funnel.py` replays it tick by tick through
a sliding-window graph. Elliptic2 has no timestamp worth trusting for that
(see sentinel/data/elliptic2.py) and is not naturally a replay at all -- it is
one enormous static background graph with labelled subgraphs scattered through
it. So this module evaluates it as a single static pass: build the whole graph
at once, seed-and-expand once, score once. Both paths bottom out in the same
primitives -- `WindowedGraph`, `CandidateGenerator`, `FunnelTracker`, `is_hit`
-- so the same metrics and the same bootstrap CIs apply to either without a
second implementation of any of them.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from sentinel.detect.candidates import CandidateGenerator
from sentinel.eval.funnel import FunnelTracker
from sentinel.graph.window import WindowedGraph
from sentinel.schema import Edge, LabeledRing


@dataclass(slots=True)
class StaticBatch:
    """A `stream.replay.Batch`-shaped view over an entire edge list.

    For a dataset with no trustworthy time axis, the "batch" is everything at
    once. Only the fields `WindowedGraph.add_batch` and `CandidateGenerator`
    actually read are present.
    """

    t_start: int
    t_end: int
    ts: np.ndarray
    src: np.ndarray
    dst: np.ndarray
    amount: np.ndarray
    is_laundering: np.ndarray

    def __len__(self) -> int:
        return int(self.ts.shape[0])


def build_node_ids(edges: list[Edge]) -> dict[str, int]:
    """Stable string-key -> dense int-id map, in first-seen order."""
    ids: dict[str, int] = {}
    for e in edges:
        if e.src not in ids:
            ids[e.src] = len(ids)
        if e.dst not in ids:
            ids[e.dst] = len(ids)
    return ids


def edges_to_batch(edges: list[Edge], node_ids: dict[str, int]) -> StaticBatch:
    n = len(edges)
    src = np.empty(n, dtype=np.int32)
    dst = np.empty(n, dtype=np.int32)
    amount = np.empty(n, dtype=np.float64)
    ts = np.zeros(n, dtype=np.int32)
    lab = np.zeros(n, dtype=np.int8)
    for i, e in enumerate(edges):
        src[i] = node_ids[e.src]
        dst[i] = node_ids[e.dst]
        amount[i] = e.amount
        lab[i] = e.label
    return StaticBatch(t_start=0, t_end=1, ts=ts, src=src, dst=dst,
                        amount=amount, is_laundering=lab)


def ring_membership(rings: list[LabeledRing],
                     node_ids: dict[str, int]) -> tuple[dict[int, set[int]], dict]:
    """LabeledRings -> (ring_index -> member node-id set, index -> typology).

    Rings with fewer than 2 members inside the background graph (an account
    the background edges never mention) are dropped -- there is no structure
    to find in a singleton, and keeping it would only inflate "seen" counts.
    """
    members: dict[int, set[int]] = {}
    typology: dict[int, str] = {}
    for i, r in enumerate(rings):
        m = {node_ids[a] for a in r.accounts if a in node_ids}
        if len(m) < 2:
            continue
        members[i] = m
        typology[i] = r.typology
    return members, typology


def run_static_funnel(edges: list[Edge], rings: list[LabeledRing],
                       rank_k: int = 50, hops: int = 2, max_nodes: int = 200,
                       max_degree: int = 50) -> tuple[FunnelTracker, list, dict]:
    """One seed-and-expand pass over the whole graph, scored against `rings`.

    Returns (tracker, candidates, node_ids) so a caller can compute p@k /
    recall with the same `is_hit` the tracker uses internally, or map node
    ids back to the dataset's own account keys.
    """
    if not edges:
        return FunnelTracker(rank_k=rank_k), [], {}

    node_ids = build_node_ids(edges)
    graph = WindowedGraph(window_minutes=10**9)  # large enough to never expire
    batch = edges_to_batch(edges, node_ids)
    graph.add_batch(batch)

    gen = CandidateGenerator(graph, hops=hops, max_nodes=max_nodes, max_degree=max_degree)
    candidates = gen.generate(batch)

    ring_members, typology = ring_membership(rings, node_ids)
    tracker = FunnelTracker(rank_k=rank_k)
    tracker.observe_cycle(ring_members, lambda r: typology.get(r, "UNKNOWN"),
                           seed_nodes=gen.seeds(batch), candidates=candidates)
    return tracker, candidates, node_ids
