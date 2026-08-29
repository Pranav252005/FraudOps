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

# A "cycle" of length 2 is A->B->A: a mutual payment pair, which is ordinary
# commerce (refunds, trade between two businesses) and passes temporal validity
# trivially in either order.
#
# Measured: 91% of queued cases contained one, and 100% of those were length 2.
# The feature was effectively a constant carrying no information, while holding
# the single largest score weight. AMLworld's CYCLE typology has a median of 4
# accounts, so genuine laundering loops are length 3 or more.
MIN_CYCLE_LEN = 3


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
    # The same shape bounded at GFP's 6h AML window. Kept alongside the
    # unbounded count rather than replacing it, so the difference between the
    # two is measurable instead of asserted.
    scatter_gather_windowed: int = 0
    sg_pairs: list[tuple[int, int, int]] = field(default_factory=list)
    # The reverse shape: many collect into one, which then disperses again.
    gather_scatter: int = 0
    # Pattern counts rather than only the maximum degree, matching GFP.
    fan_out_count: int = 0
    fan_in_count: int = 0
    # pass-through nodes are the mule signature
    n_passthrough: int = 0
    # Mutual A<->B pairs. Retained as a separate, unweighted count because they
    # are ordinary commerce and must not be reported as laundering loops.
    n_mutual_pairs: int = 0
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
            "scatter_gather_windowed": self.scatter_gather_windowed,
            "gather_scatter": self.gather_scatter,
            "fan_out_count": self.fan_out_count,
            "fan_in_count": self.fan_in_count,
            "n_passthrough": self.n_passthrough,
            "n_mutual_pairs": self.n_mutual_pairs,
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
                limit: int = MAX_CYCLES,
                min_len: int = MIN_CYCLE_LEN) -> list[list[int]]:
    """Simple directed cycles up to `max_len`, capped at `limit`.

    Capped because a dense subgraph can contain combinatorially many cycles and
    the score only needs to know that they exist, how short they are, and how
    much of the subgraph they involve.
    """
    out: list[list[int]] = []
    for cyc in nx.simple_cycles(G, length_bound=max_len):
        if len(cyc) < min_len:
            continue
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


# GFP's AML configuration bounds the scatter-gather shape at 6 hours
# (arXiv:2402.08593). sentinel bounded it not at all, which is one of the three
# real gaps behind docs/HANDOFF.md section 4's "essentially at parity" claim: a
# scatter-gather spread over 72 hours is a different object from one completed
# in an afternoon, and only the second is evidence of a single coordinated
# movement of value.
SCATTER_GATHER_WINDOW_MINUTES = 6 * 60


def _leg_pair_fits(e1: dict, e2: dict, window: int) -> bool:
    """Can value have gone a -> mid -> b within `window` minutes?

    Each pair carries an interval (first_t..last_t) rather than one timestamp,
    because the window aggregates repeated transactions on a pair. So the
    question is whether SOME choice t1 in [f1,l1], t2 in [f2,l2] satisfies
    0 <= t2 - t1 <= window. That is feasible exactly when the second leg can
    happen at or after the first (l2 >= f1) and can happen soon enough
    (f2 <= l1 + window).

    Using the intervals rather than, say, the midpoints is deliberate: choosing
    a representative timestamp would make the answer depend on an arbitrary
    convention, and this project has a bug in its catalogue for exactly that
    class of quiet choice.
    """
    return e2["last_t"] >= e1["first_t"] and e2["first_t"] <= e1["last_t"] + window


def find_scatter_gather(G: nx.DiGraph, min_width: int = 2,
                        window_minutes: int | None = None
                        ) -> list[tuple[int, int, int]]:
    """A -> S -> B where |S| >= min_width and A != B.

    This is the layering shape: split a payment across intermediaries and
    recombine it, so no single hop carries the whole amount. Returns
    (source, sink, width) triples.

    `window_minutes` bounds the shape in time, matching GFP. An intermediary
    counts toward the width only if its own two legs are individually feasible
    within the window; the width is then the number of intermediaries that
    qualify. Per-intermediary rather than a single span across all of them,
    because the shape's meaning is "each strand of this split-and-recombine
    completed quickly", and a span test would let one slow strand veto a
    genuine pattern. `None` (the default) keeps the original unbounded
    behaviour, so the two are measurable against each other rather than one
    silently replacing the other.
    """
    found: list[tuple[int, int, int]] = []
    for a in G:
        succ = set(G.successors(a))
        if len(succ) < min_width:
            continue
        sinks: dict[int, int] = {}
        for mid in succ:
            for b in G.successors(mid):
                if b == a or b in succ:
                    continue
                if window_minutes is not None and not _leg_pair_fits(
                        G[a][mid], G[mid][b], window_minutes):
                    continue
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
    m.n_mutual_pairs = sum(1 for a, b in G.edges() if a < b and G.has_edge(b, a))

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
    sg_w = find_scatter_gather(G, window_minutes=SCATTER_GATHER_WINDOW_MINUTES)
    m.scatter_gather_windowed = max((w for _, _, w in sg_w), default=0)
    m.gather_scatter = find_gather_scatter(G)

    # Pattern counts: how many accounts act as a fan hub at all, not just the
    # single largest. GFP reports these separately from max degree.
    m.fan_out_count = sum(1 for n in G if out_deg.get(n, 0) >= 2)
    m.fan_in_count = sum(1 for n in G if in_deg.get(n, 0) >= 2)
    return m
