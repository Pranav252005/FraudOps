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
    "cycle": 0.28,
    "conservation": 0.22,
    "scatter_gather": 0.16,
    "passthrough": 0.12,
    "cross_border": 0.10,
    "burstiness": 0.07,
    "round_amounts": 0.05,
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
    scatter_gather_width: int = 0
    passthrough_ratio: float = 0.0
    max_fan: int = 0

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
    f.scatter_gather_width = motifs.scatter_gather
    f.passthrough_ratio = motifs.n_passthrough / len(nodes)
    f.max_fan = max(motifs.max_out_degree, motifs.max_in_degree)

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

    return f


def score(f: Features) -> tuple[float, dict[str, float]]:
    """Transparent weighted blend. Returns (score, per-term contributions).

    Contributions are returned alongside the total because the case file shows
    the analyst *why* a candidate ranked where it did. A score without its
    decomposition is not reviewable, and an unreviewable queue does not produce
    the labels the whole system depends on.
    """
    terms = {
        # A short cycle covering much of the candidate is the strongest single
        # structural signal available.
        "cycle": (0.6 * f.cycle_coverage
                  + 0.4 * (1.0 if 0 < f.shortest_cycle <= 4 else 0.0))
        if f.has_cycle else 0.0,
        "conservation": f.conservation,
        "scatter_gather": _norm(f.scatter_gather_width, 5),
        "passthrough": f.passthrough_ratio,
        "cross_border": _norm(max(0, f.n_countries - 1), 4),
        "burstiness": _norm(f.burstiness, 20),
        "round_amounts": f.round_amount_ratio,
    }
    contrib = {k: WEIGHTS[k] * v for k, v in terms.items()}
    return sum(contrib.values()), contrib
