"""Candidate features and the transparent v1 score.

Two measured findings shape this file.

Value conservation is a *ring-level* property, not a node-level one. Measured as
a per-account trigger it gives 4.0x lift at only 3.9% recall, because laundering
accounts do not individually conserve -- the ring conserves as a whole. So
conservation is computed here, across the candidate's boundary, and never used
for seeding.

`channel` (Payment Format) is excluded on purpose. 86.6% of laundering rows are
ACH against an 11.8% base rate, a 7.3x lift from one column. It is a generator
artifact, and using it would inflate every metric while teaching nothing that
transfers to real data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

from sentinel.detect.motifs import Motifs

# Weights for the v1 score. Deliberately a transparent linear blend: every term
# is displayed separately in the case file, so an analyst can see which evidence
# drove the rank. The learned re-ranker replaces this in v2 -- it does not
# replace the features.
WEIGHTS = {
    # Rebalanced to sum to exactly 1.0 when the layered terms were added, so a
    # saturated score is 1.0 and remains comparable across versions. A test
    # asserts the sum; adding a term without rebalancing would silently inflate
    # every score in the queue.
    #
    # A temporally valid cycle leads: in a 244k-node graph triangles arise by
    # chance constantly, but triangles whose timestamps let value actually
    # travel the loop do not.
    "temporal_cycle": 0.22,
    "conservation": 0.15,
    "fast_passthrough": 0.12,
    "scatter_gather": 0.10,
    "gargaml": 0.09,
    "cycle": 0.08,
    "gather_scatter": 0.05,
    "bipartite": 0.05,
    "stack": 0.05,
    "passthrough": 0.04,
    "cross_border": 0.03,
    "burstiness": 0.01,
    "round_amounts": 0.01,
}


def _norm(x: float, cap: float) -> float:
    """Squash to 0..1 with a saturating cap rather than a hard clip."""
    if cap <= 0:
        return 0.0
    return min(1.0, max(0.0, x / cap))


@dataclass
class Features:
    n_nodes: int = 0
    n_edges: int = 0
    n_txns: int = 0
    total_amount: float = 0.0

    # structure
    has_cycle: bool = False
    shortest_cycle: int = 0
    cycle_coverage: float = 0.0       # share of nodes sitting on a cycle
    has_temporal_cycle: bool = False
    shortest_temporal_cycle: int = 0
    temporal_cycle_coverage: float = 0.0
    scatter_gather_width: int = 0
    gather_scatter_width: int = 0
    fan_out_count: int = 0
    fan_in_count: int = 0
    passthrough_ratio: float = 0.0
    max_fan: int = 0

    # Layered structure (GARG-AML). `gargaml` runs -1..1; the two typology
    # scores are block densities in 0..1.
    gargaml: float = 0.0
    layer_high_density: float = 0.0
    layer_low_density: float = 0.0
    layer_depth: int = 0
    n_senders: int = 0
    n_mules: int = 0
    n_receivers: int = 0
    bipartite_score: float = 0.0
    stack_score: float = 0.0

    # Behavioural family -- aggregated from per-account statistics. Absent
    # entirely from v1, which modelled structure only.
    fast_passthrough_ratio: float = 0.0   # share of members forwarding >=80% within 48h
    median_passthrough_value: float = 0.0
    median_dormancy_h: float = 0.0
    max_amount_skew: float = 0.0
    mean_velocity: float = 0.0

    # money
    inflow: float = 0.0               # value entering the candidate
    outflow: float = 0.0              # value leaving it
    internal: float = 0.0             # value circulating inside
    conservation: float = 0.0         # min(in,out)/max(in,out)
    churn: float = 0.0                # internal / boundary flow
    round_amount_ratio: float = 0.0

    # context
    n_banks: int = 0
    n_countries: int = 0
    cross_border: bool = False
    # Registry context: loaded since phase 0 but unused until now. A cluster of
    # sole proprietorships behaves differently from one of corporations, and
    # entity-type uniformity is itself a signal that accounts were created for
    # one purpose.
    n_entities: int = 0
    entity_reuse: float = 0.0        # members per distinct legal owner
    dominant_entity_type: str = ""
    entity_type_purity: float = 0.0
    span_minutes: int = 0
    burstiness: float = 0.0           # txns per hour

    exact: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def is_round(amount: float) -> bool:
    """Round-number amounts are a weak but real structuring signal."""
    return amount >= 100 and (amount % 100 == 0 or amount % 1000 == 0)


def build(nodes: set[int], graph, motifs: Motifs, registry=None,
          node_key=None) -> Features:
    """Compute features for one candidate.

    `graph` is the WindowedGraph; `nodes` the candidate's members. Boundary flow
    is measured against the whole window, not just the induced subgraph -- the
    laundering signature is what crosses the boundary, so ignoring outside edges
    would discard the most informative part.
    """
    f = Features(n_nodes=len(nodes), exact=motifs.exact)
    if not nodes:
        return f

    internal_edges = graph.subgraph_edges(nodes)
    f.n_edges = len(internal_edges)

    first_t = last_t = None
    n_round = 0
    for _, _, agg in internal_edges:
        f.internal += agg.amount
        f.n_txns += agg.count
        if is_round(agg.amount / max(1, agg.count)):
            n_round += agg.count
        first_t = agg.first_t if first_t is None else min(first_t, agg.first_t)
        last_t = agg.last_t if last_t is None else max(last_t, agg.last_t)

    # Boundary flow.
    for n in nodes:
        for s in graph.in_adj.get(n, ()):
            if s not in nodes:
                f.inflow += graph.pairs[(s << 32) | n].amount
        for d in graph.out_adj.get(n, ()):
            if d not in nodes:
                f.outflow += graph.pairs[(n << 32) | d].amount

    hi = max(f.inflow, f.outflow)
    lo = min(f.inflow, f.outflow)
    f.conservation = (lo / hi) if hi > 0 else 0.0
    boundary = f.inflow + f.outflow
    f.churn = (f.internal / boundary) if boundary > 0 else 0.0
    f.total_amount = f.internal + f.inflow
    f.round_amount_ratio = (n_round / f.n_txns) if f.n_txns else 0.0

    # Structure.
    f.has_cycle = motifs.n_cycles > 0
    f.shortest_cycle = motifs.shortest_cycle
    f.cycle_coverage = motifs.nodes_in_cycles / len(nodes) if nodes else 0.0
    f.has_temporal_cycle = motifs.n_temporal_cycles > 0
    f.shortest_temporal_cycle = motifs.shortest_temporal_cycle
    f.temporal_cycle_coverage = (
        motifs.nodes_in_temporal_cycles / len(nodes) if nodes else 0.0)
    f.scatter_gather_width = motifs.scatter_gather
    f.gather_scatter_width = motifs.gather_scatter
    f.fan_out_count = motifs.fan_out_count
    f.fan_in_count = motifs.fan_in_count
    f.passthrough_ratio = motifs.n_passthrough / len(nodes)
    f.max_fan = max(motifs.max_out_degree, motifs.max_in_degree)

    lp = motifs.layers
    f.gargaml = lp.gargaml
    f.layer_high_density = lp.high_density
    f.layer_low_density = lp.low_density
    f.layer_depth = lp.depth
    f.n_senders, f.n_mules, f.n_receivers = lp.n_senders, lp.n_mules, lp.n_receivers
    f.bipartite_score = lp.bipartite
    f.stack_score = lp.stack

    # Behavioural family, from the per-account statistics the graph maintains.
    stats = getattr(graph, "account_stats", None)
    if stats:
        members = [stats[n] for n in nodes if n in stats]
        if members:
            import statistics as _st
            f.fast_passthrough_ratio = (
                sum(1 for a in members if a.is_fast_passthrough) / len(members))
            f.median_passthrough_value = _st.median(
                a.passthrough_value_ratio for a in members)
            f.median_dormancy_h = _st.median(a.dormancy_hours for a in members)
            f.max_amount_skew = max(
                (abs(a.outflow.skewness) for a in members), default=0.0)
            f.mean_velocity = _st.fmean(a.velocity for a in members)

    # Timing.
    if first_t is not None and last_t is not None:
        f.span_minutes = int(last_t - first_t)
        hours = max(1.0, f.span_minutes / 60.0)
        f.burstiness = f.n_txns / hours

    # Jurisdiction.
    if registry is not None and node_key is not None:
        banks, countries = set(), set()
        for n in nodes:
            key = node_key(n)
            banks.add(key.split(":", 1)[0])
            countries.add(registry.country(key))
        f.n_banks = len(banks)
        f.n_countries = len(countries)
        f.cross_border = len(countries) > 1

        ents, types = [], []
        for n in nodes:
            acct = registry.get(node_key(n))
            if acct is not None:
                ents.append(acct.entity_id)
                types.append(acct.entity_type)
        if ents:
            distinct = len(set(ents))
            f.n_entities = distinct
            # Several accounts owned by one legal entity inside one cluster is
            # a far stronger link than a shared transaction, because it is a
            # fact about the world rather than an inference from behaviour.
            f.entity_reuse = len(ents) / distinct if distinct else 0.0
        if types:
            top = max(set(types), key=types.count)
            f.dominant_entity_type = top
            f.entity_type_purity = types.count(top) / len(types)

    return f


def score(f: Features) -> tuple[float, dict[str, float]]:
    """Transparent weighted blend. Returns (score, per-term contributions).

    Contributions are returned alongside the total because the case file shows
    the analyst *why* a candidate ranked where it did. A score without its
    decomposition is not reviewable, and an unreviewable queue does not produce
    the labels the whole system depends on.
    """
    terms = {
        "temporal_cycle": (0.6 * f.temporal_cycle_coverage
                           + 0.4 * (1.0 if 0 < f.shortest_temporal_cycle <= 4
                                    else 0.0))
        if f.has_temporal_cycle else 0.0,
        "cycle": (0.6 * f.cycle_coverage
                  + 0.4 * (1.0 if 0 < f.shortest_cycle <= 4 else 0.0))
        if f.has_cycle else 0.0,
        "conservation": f.conservation,
        "scatter_gather": _norm(f.scatter_gather_width, 5),
        "gather_scatter": _norm(f.gather_scatter_width, 5),
        # The industry mule rule, applied at candidate level.
        "fast_passthrough": f.fast_passthrough_ratio,
        "passthrough": f.passthrough_ratio,
        "cross_border": _norm(max(0, f.n_countries - 1), 4),
        "burstiness": _norm(f.burstiness, 20),
        "round_amounts": f.round_amount_ratio,
        # gargaml is -1..1; only its positive half indicates smurfing.
        "gargaml": max(0.0, f.gargaml),
        "bipartite": f.bipartite_score,
        "stack": f.stack_score,
    }
    contrib = {k: WEIGHTS[k] * v for k, v in terms.items()}
    return sum(contrib.values()), contrib
