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
    # scatter-gather: A distributes to S, S reconverges on B
    scatter_gather: int = 0
    sg_pairs: list[tuple[int, int, int]] = field(default_factory=list)
    # pass-through nodes are the mule signature
    n_passthrough: int = 0
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
            "scatter_gather": self.scatter_gather,
            "n_passthrough": self.n_passthrough,
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

    sg = find_scatter_gather(G)
    m.sg_pairs = sg[:20]
    m.scatter_gather = max((w for _, _, w in sg), default=0)
    return m
