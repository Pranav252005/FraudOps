"""Candidate features and the transparent hand-set score.

Three measured findings shape this file.

Two of the thirteen blend terms were pointing the wrong way, and they were the
reason the score did not beat a node-count baseline. `gargaml` and `stack` are
near-saturated across almost every candidate, so only their variance reaches
the ranking, and that variance is an inverse proxy for candidate size. See
RETIRED_TERMS.

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

# The hand-set weights as originally shipped. Kept literally, because two of
# them turned out to be pointing the wrong way and the correction below is only
# legible next to what it corrects.
#
# Deliberately a transparent linear blend: every term is displayed separately in
# the case file, so an analyst can see which evidence drove the rank. The
# learned re-ranker is a separate artefact -- it does not replace the features.
#
# Rebalanced to sum to exactly 1.0 when the layered terms were added, so a
# saturated score is 1.0 and remains comparable across versions. A test asserts
# the sum; adding a term without rebalancing would silently inflate every score
# in the queue.
#
# A temporally valid cycle leads: in a 244k-node graph triangles arise by
# chance constantly, but triangles whose timestamps let value actually travel
# the loop do not.
_V1_WEIGHTS = {
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

# RETIRED: measured anti-signal. These two terms were the reason the score did
# not beat a node-count baseline, and the mechanism is specific enough to state.
#
# Both are near-saturated and near-universal -- `gargaml` fires on 100% of
# candidates with mean 0.915, `stack` on 99.6% with mean 0.910. A term that is
# almost always ~0.91 contributes almost nothing but its VARIANCE to the
# ranking, and their variance is an inverse proxy for candidate size:
# Spearman(gargaml, n_nodes) = -0.495, Spearman(stack, n_nodes) = -0.499.
# Post-pruning, size became a genuine positive signal (AUC 0.710), so those two
# terms were ordering the queue by smallness, carrying 0.14 of the weight while
# doing it, and drowning out the rare high-precision terms that fire on well
# under 1% of candidates.
#
# The inversion is not a size artefact. Holding node count EXACTLY constant --
# stratifying on the 41 distinct values and pooling -- gargaml scores AUC 0.4534
# and stack 0.4552 against the label. Both are below 0.5 on their own terms.
#
# Zeroed rather than deleted, so the case file still shows the analyst a stack
# or GARG-AML reading as evidence; it just no longer drives the rank. Read this
# as "these two do not discriminate on AMLworld HI-Small after pruning", NOT as
# a claim about GARG-AML as a method.
#
# Measured by scripts/eval_blend_v2.py. Removing them takes held-out p@10 from
# 0.0500 to 0.1889 against a size baseline of 0.0444.
RETIRED_TERMS = ("gargaml", "stack")

_KEPT = sum(v for k, v in _V1_WEIGHTS.items() if k not in RETIRED_TERMS)

# Renormalised over the surviving terms rather than hand-retyped, so the
# sum-to-1.0 property is structural and cannot drift from the literal above.
WEIGHTS = {k: (0.0 if k in RETIRED_TERMS else v / _KEPT)
           for k, v in _V1_WEIGHTS.items()}


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
    # The same shape bounded at GFP's 6h AML window (see motifs.py). Present
    # alongside the unbounded width, not instead of it.
    scatter_gather_width_6h: int = 0
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

    # GFP's vertex-statistic family over AMOUNTS, aggregated across members.
    # `AccountStats` has computed these per account since the behavioural axis
    # was added; until now only `max_amount_skew` and `mean_velocity` reached
    # the feature vector, so the rest were paid for and thrown away. That is
    # the second of the three real gaps behind the "essentially at parity with
    # GFP" claim in docs/HANDOFF.md section 4.
    #
    # Not closed, and stated rather than glossed: GFP also reports a per-account
    # MEDIAN amount. Welford moments cannot produce a median without retaining
    # samples, which would defeat the O(1)-per-edge design. `median_passthrough
    # _value` is a median across members, which is a different quantity.
    mean_out_amount: float = 0.0
    mean_in_amount: float = 0.0
    min_member_amount: float = 0.0
    max_member_amount: float = 0.0
    mean_amount_std: float = 0.0
    max_amount_kurtosis: float = 0.0

    # GFP's vertex-statistic family over TIMESTAMPS, which was absent entirely.
    # span_minutes and burstiness say how wide and how busy; these say what
    # SHAPE the activity has in time -- one burst, two, or a steady trickle.
    mean_time_std_h: float = 0.0
    mean_time_skew: float = 0.0
    max_time_kurtosis: float = 0.0

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


# The band in which the boundary-flow identity is not trustworthy, expressed
# relative to the total value summed.
#
# `_boundary_flow` computes external flow as (sum of members' whole-window
# totals) - (sum of internal edge amounts). That is exact in real arithmetic
# and NOT exact in floating point: it is a difference of two large, nearly
# equal numbers, so its absolute error scales with the MAGNITUDE OF THE TOTALS,
# not with the magnitude of the answer. When a candidate's external flow is
# tiny beside its internal flow, the answer is entirely inside that error.
#
# This is not hypothetical. Measured on tick 36 of the real stream, 4 of 15,496
# candidates land in that band, and the worst case had a genuine external
# inflow of 0.09 against 6,948,663.08 of internal flow -- the identity returned
# 0.0, which would have made `conservation` 0.0 rather than 1.3e-8. Small
# enough not to move any ranking (rank order was identical across all 65,114
# candidates benchmarked), and still a wrong number reported with confidence,
# which is the defect class this project exists to resist.
#
# So the identity is used where it is reliable and the O(degree) adjacency walk
# is used where it is not. The walk fires for ~0.03% of candidates, so the
# speedup is kept, and inside the band the result is bit-identical to the
# implementation the identity replaced rather than merely close to it.
BOUNDARY_CANCELLATION_REL = 1e-6


def _boundary_flow_walk(nodes: set[int], graph) -> tuple[float, float]:
    """External inflow/outflow by walking every member's window adjacency.

    O(sum of member degrees), and numerically exact: it sums only the external
    edges, so no cancellation against the internal total occurs. This is the
    reference implementation, still used directly whenever the identity lands
    in its unreliable band.
    """
    inflow = outflow = 0.0
    for n in nodes:
        for s in graph.in_adj.get(n, ()):
            if s not in nodes:
                inflow += graph.pairs[(s << 32) | n].amount
        for d in graph.out_adj.get(n, ()):
            if d not in nodes:
                outflow += graph.pairs[(n << 32) | d].amount
    return inflow, outflow


def _boundary_flow(nodes: set[int], graph, internal: float) -> tuple[float, float]:
    """External inflow/outflow. O(|nodes|) in the common case.

        external_inflow(C)  = sum_{n in C} total_in[n]  - sum_{internal} amt
        external_outflow(C) = sum_{n in C} total_out[n] - sum_{internal} amt

    Every edge into a member is either internal to C or external, and each
    internal edge contributes to exactly one member's `total_in` and one
    member's `total_out`, so both identities hold exactly in real arithmetic. A
    self-loop contributes to both totals and appears once in the internal sum,
    so it cancels correctly too (the dataset drops self-loops at compile time,
    but the identity does not depend on that).

    Falls back to the adjacency walk in two cases: when the graph does not
    maintain the totals (hand-built graphs in tests), and when the result lands
    within BOUNDARY_CANCELLATION_REL of the totals summed, where floating-point
    cancellation makes the identity unreliable. See that constant for the
    measured case this exists to prevent.
    """
    totals_in = getattr(graph, "total_in", None)
    totals_out = getattr(graph, "total_out", None)
    if totals_in is None or totals_out is None:
        return _boundary_flow_walk(nodes, graph)

    sum_in = sum_out = 0.0
    for n in nodes:
        sum_in += totals_in.get(n, 0.0)
        sum_out += totals_out.get(n, 0.0)
    inflow = sum_in - internal
    outflow = sum_out - internal

    guard = BOUNDARY_CANCELLATION_REL * max(sum_in, sum_out, 0.0)
    if abs(inflow) <= guard or abs(outflow) <= guard:
        return _boundary_flow_walk(nodes, graph)
    return inflow, outflow


def build(nodes: set[int], graph, motifs: Motifs, registry=None,
          node_key=None, internal_edges=None) -> Features:
    """Compute features for one candidate.

    `graph` is the WindowedGraph; `nodes` the candidate's members. Boundary flow
    is measured against the whole window, not just the induced subgraph -- the
    laundering signature is what crosses the boundary, so ignoring outside edges
    would discard the most informative part.

    `internal_edges` may be passed in by a caller that has already computed
    `graph.subgraph_edges(nodes)`. It must be that exact list for these exact
    nodes; passing anything else silently changes every value below.
    `CandidateGenerator` computes it once and threads it through, which removes
    one of three redundant walks per candidate.
    """
    f = Features(n_nodes=len(nodes), exact=motifs.exact)
    if not nodes:
        return f

    if internal_edges is None:
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

    # Boundary flow. Measured over 2,996 real pruned candidates, the adjacency
    # walk this replaces was 76% of the cost of `build` and ~44% of total cycle
    # time: 7.7 members at a mean whole-window degree of 478 is ~3,700 dict
    # lookups to produce two scalars. The identity produces the same two
    # scalars in O(|nodes|).
    f.inflow, f.outflow = _boundary_flow(nodes, graph, f.internal)

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
    f.scatter_gather_width_6h = motifs.scatter_gather_windowed
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

            # Amount moments, aggregated across members. Accounts with no
            # transactions in that direction are skipped rather than counted as
            # zero -- a mean over "no outflow = 0.0" would report a candidate of
            # pure receivers as having small outflows rather than none.
            outs = [a.outflow for a in members if a.outflow.n]
            ins = [a.inflow for a in members if a.inflow.n]
            if outs:
                f.mean_out_amount = _st.fmean(m.mean for m in outs)
                f.mean_amount_std = _st.fmean(m.std for m in outs)
                f.max_amount_kurtosis = max(abs(m.kurtosis) for m in outs)
            if ins:
                f.mean_in_amount = _st.fmean(m.mean for m in ins)
            both = outs + ins
            if both:
                f.min_member_amount = min(m.lo for m in both)
                f.max_member_amount = max(m.hi for m in both)

            # Timestamp moments. Members with fewer than the moment's minimum
            # sample count return 0.0 from the property, which is the honest
            # "no information" value rather than a fabricated one.
            times = [a for a in members if a.times.n]
            if times:
                f.mean_time_std_h = _st.fmean(a.time_std_hours for a in times)
                f.mean_time_skew = _st.fmean(a.time_skewness for a in times)
                f.max_time_kurtosis = max(abs(a.time_kurtosis) for a in times)

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
            # `sorted`, not `set`, and the reason is a real defect found by the
            # efficiency benchmark's fingerprint diff. `max(set(types), ...)`
            # returns the first maximal element in SET ITERATION ORDER, and a
            # set of strings iterates in an order that depends on
            # PYTHONHASHSEED. So a candidate whose entity types tie -- one
            # Sole Proprietorship, one Partnership, one Corporation -- reported
            # a different "dominant" type on different runs of the same input:
            # "Sole Proprietorship" under one seed, "Corporation" under
            # another. Nothing raised; the case file simply stated a confident
            # fact about the ring that was decided by a hash seed.
            #
            # `entity_type_purity` was unaffected (tied types share a count),
            # and `dominant_entity_type` is in the re-ranker's EXCLUDED set, so
            # no reported metric moved. The analyst-facing case file did.
            top = max(sorted(set(types)), key=types.count)
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
