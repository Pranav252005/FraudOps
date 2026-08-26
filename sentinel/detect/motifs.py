"""Structural motif detection on candidate subgraphs.

Community detection was measured against this dataset first and rejected: it
achieves 78-82% ring coverage but places almost every covered ring inside a
4,000-8,000 node community, so only 1-2% of them land in anything an analyst
could work. Laundering rings here are small structures embedded in a large,
largely unstructured graph -- there is no modular structure for Leiden to find.

Motif matching is therefore the primary detector. It looks for the shapes the
typologies are actually named after, on subgraphs small enough (median 14 nodes)
that exact algorithms are affordable.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx

from sentinel.detect.layers import LayerProfile, profile as layer_profile

# Above this the exact cycle enumeration is skipped. Neighbourhoods are median
# 14 nodes and 99% sit under 60, so this bounds a tail case rather than the
# common path.
MAX_EXACT_NODES = 120
MAX_CYCLE_LEN = 8
MAX_CYCLES = 200


@dataclass
class Motifs:
    """What shapes a candidate subgraph contains."""

    n_nodes: int = 0
    n_edges: int = 0
    # fan-out / fan-in: one account distributing to or collecting from many
    max_out_degree: int = 0
    max_in_degree: int = 0
    fan_out_hub: int | None = None
    fan_in_hub: int | None = None
    # cycles: value returning to where it started
    n_cycles: int = 0
    max_cycle_len: int = 0
    shortest_cycle: int = 0
    nodes_in_cycles: int = 0
    # A cycle whose edges are chronologically ordered, so value could actually
    # have travelled the loop. Structural cycles occur by chance constantly in a
    # 244k-node graph; temporally valid ones do not.
    n_temporal_cycles: int = 0
    shortest_temporal_cycle: int = 0
    nodes_in_temporal_cycles: int = 0
    # scatter-gather: A distributes to S, S reconverges on B
    scatter_gather: int = 0
    sg_pairs: list[tuple[int, int, int]] = field(default_factory=list)
    # The reverse shape: many collect into one, which then disperses again.
    gather_scatter: int = 0
    # Pattern counts rather than only the maximum degree, matching GFP.
    fan_out_count: int = 0
    fan_in_count: int = 0
    # pass-through nodes are the mule signature
    n_passthrough: int = 0
    # GARG-AML layered read: block densities, bipartite and stack strength.
    layers: LayerProfile = field(default_factory=LayerProfile)
    exact: bool = True

    def to_dict(self) -> dict:
        return {
            "n_nodes": self.n_nodes, "n_edges": self.n_edges,
            "max_out_degree": self.max_out_degree,
            "max_in_degree": self.max_in_degree,
            "n_cycles": self.n_cycles,
            "max_cycle_len": self.max_cycle_len,
            "shortest_cycle": self.shortest_cycle,
            "nodes_in_cycles": self.nodes_in_cycles,
            "n_temporal_cycles": self.n_temporal_cycles,
            "shortest_temporal_cycle": self.shortest_temporal_cycle,
            "nodes_in_temporal_cycles": self.nodes_in_temporal_cycles,
            "scatter_gather": self.scatter_gather,
            "gather_scatter": self.gather_scatter,
            "fan_out_count": self.fan_out_count,
            "fan_in_count": self.fan_in_count,
            "n_passthrough": self.n_passthrough,
            **{f"layer_{k}": v for k, v in self.layers.to_dict().items()},
            "exact": self.exact,
        }


def build_digraph(edges) -> nx.DiGraph:
    """edges: iterable of (src, dst, agg)."""
    G = nx.DiGraph()
    for s, d, agg in edges:
        G.add_edge(s, d, count=agg.count, amount=agg.amount,
                   first_t=agg.first_t, last_t=agg.last_t)
    return G


def find_cycles(G: nx.DiGraph, max_len: int = MAX_CYCLE_LEN,
                limit: int = MAX_CYCLES) -> list[list[int]]:
    """Simple directed cycles up to `max_len`, capped at `limit`.

    Capped because a dense subgraph can contain combinatorially many cycles and
    the score only needs to know that they exist, how short they are, and how
    much of the subgraph they involve.
    """
    out: list[list[int]] = []
    for cyc in nx.simple_cycles(G, length_bound=max_len):
        out.append(cyc)
        if len(out) >= limit:
            break
    return out


def is_temporally_valid(G: nx.DiGraph, cycle: list[int]) -> bool:
    """Could value actually have travelled this loop?

    A cycle is temporally valid when each hop can occur after the previous one
    arrived. Edges carry a window (first_t..last_t) because a pair may transact
    several times, so the test asks whether *some* choice of transactions is
    consistent, using the earliest feasible time at each step.

    This is what separates a laundering loop from three unrelated payments that
    happen to form a triangle.
    """
    n = len(cycle)
    if n < 2:
        return False
    # Try each starting point: the loop is a cycle, so any hop may be first.
    for start in range(n):
        t = -1
        ok = True
        for i in range(n):
            a = cycle[(start + i) % n]
            b = cycle[(start + i + 1) % n]
            e = G.get_edge_data(a, b)
            if e is None:
                ok = False
                break
            # Earliest transaction on this pair at or after t.
            if e["last_t"] < t:
                ok = False
                break
            t = max(t, e["first_t"])
        if ok:
            return True
    return False


def find_gather_scatter(G: nx.DiGraph, min_width: int = 2) -> int:
    """Widest S -> A -> T where |S| and |T| both reach min_width.

    The mirror of scatter-gather: many sources collect into one account which
    then disperses again. GFP treats these as distinct features and so does
    this, because they implicate different accounts as the controller.
    """
    best = 0
    for a in G:
        preds = [p for p in G.predecessors(a) if p != a]
        succs = [s for s in G.successors(a) if s != a]
        if len(preds) >= min_width and len(succs) >= min_width:
            best = max(best, min(len(preds), len(succs)))
    return best


def find_scatter_gather(G: nx.DiGraph, min_width: int = 2) -> list[tuple[int, int, int]]:
    """A -> S -> B where |S| >= min_width and A != B.

    This is the layering shape: split a payment across intermediaries and
    recombine it, so no single hop carries the whole amount. Returns
    (source, sink, width) triples.
    """
    found: list[tuple[int, int, int]] = []
    for a in G:
        succ = set(G.successors(a))
        if len(succ) < min_width:
            continue
        sinks: dict[int, int] = {}
        for mid in succ:
            for b in G.successors(mid):
                if b != a and b not in succ:
                    sinks[b] = sinks.get(b, 0) + 1
        for b, width in sinks.items():
            if width >= min_width:
                found.append((a, b, width))
    return found


def detect(edges) -> Motifs:
    """Run every motif detector over one candidate subgraph."""
    G = build_digraph(edges)
    m = Motifs(n_nodes=G.number_of_nodes(), n_edges=G.number_of_edges())
    if m.n_nodes == 0:
        return m

    out_deg = dict(G.out_degree())
    in_deg = dict(G.in_degree())
    if out_deg:
        m.fan_out_hub = max(out_deg, key=out_deg.get)
        m.max_out_degree = out_deg[m.fan_out_hub]
    if in_deg:
        m.fan_in_hub = max(in_deg, key=in_deg.get)
        m.max_in_degree = in_deg[m.fan_in_hub]

    m.n_passthrough = sum(1 for n in G
                          if out_deg.get(n, 0) > 0 and in_deg.get(n, 0) > 0)

    # Layered structure is cheap and does not need the exact-enumeration guard,
    # so it is computed even for subgraphs too large for cycle enumeration --
    # those are exactly the ones where a stack or bipartite shape is likeliest.
    m.layers = layer_profile(G)

    if m.n_nodes > MAX_EXACT_NODES:
        # Too large for exact enumeration. Say so rather than reporting zeros
        # that would read as "no structure found".
        m.exact = False
        return m

    cycles = find_cycles(G)
    if cycles:
        lengths = [len(c) for c in cycles]
        m.n_cycles = len(cycles)
        m.max_cycle_len = max(lengths)
        m.shortest_cycle = min(lengths)
        m.nodes_in_cycles = len({n for c in cycles for n in c})

        temporal = [c for c in cycles if is_temporally_valid(G, c)]
        if temporal:
            m.n_temporal_cycles = len(temporal)
            m.shortest_temporal_cycle = min(len(c) for c in temporal)
            m.nodes_in_temporal_cycles = len({n for c in temporal for n in c})

    sg = find_scatter_gather(G)
    m.sg_pairs = sg[:20]
    m.scatter_gather = max((w for _, _, w in sg), default=0)
    m.gather_scatter = find_gather_scatter(G)

    # Pattern counts: how many accounts act as a fan hub at all, not just the
    # single largest. GFP reports these separately from max degree.
    m.fan_out_count = sum(1 for n in G if out_deg.get(n, 0) >= 2)
    m.fan_in_count = sum(1 for n in G if in_deg.get(n, 0) >= 2)
    return m
