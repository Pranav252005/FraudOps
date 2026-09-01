"""Features for the synthetic-identity domain, to the set pre-registered in
`prereg/synthetic_identity_features.md`.

Written after that file was committed. Where a family here disagrees with it,
that file is right and this one is a bug.

**The signature is the leak boundary.** `build` takes a candidate's node set,
the graph, and the observable applications. It is never handed a `World`, so
`World.clusters` is not in scope to be read by accident, and the module imports
neither the `World` type nor `sentinel.eval.identity`. The mechanical check is
in `tests/test_identity_features.py`: permute the ground-truth assignment and
every feature value must come back bit-identical.

**Almost nothing survived the port.** `sentinel/detect/features.py` is built on
flow -- `passthrough_ratio`, `conservation`, `mean_velocity`, `layer_depth`,
boundary inflow and outflow. Onboarding applications have no amounts and no
direction, so those are not weak here, they are undefined. What travels is the
graph-structural family, and it is rewritten rather than imported because the
AMLworld version reads `PairAgg` amounts that do not exist in this domain.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations

from sentinel.generators.synthetic_identity import ATTRS

MINUTES_PER_DAY = 1440

# Observable columns that may not be read by any feature. Not a statistical
# judgement like `config.EXCLUDED_FEATURES` -- these are generator bookkeeping.
#
#   app_id       an index. It is shuffled after construction so it carries no
#                signal today, but a feature reading an index is a bug waiting
#                for somebody to remove the shuffle.
#   ts_absolute  the 90-day span is a generator parameter. Differences between
#                timestamps are data; a position inside a chosen span is not.
FORBIDDEN_INPUTS = frozenset({"app_id", "ts_absolute"})

# Features excluded after measurement, with the numbers in
# docs/PHASEC-IDENTITY-FEATURES.md. Populated by the gate, not by taste; the
# pre-registered decision rule is that an attribute whose legitimate maximum
# multiplicity is bounded by a structure size in the generator cannot be used,
# because separation on it is the generator's construction rather than a
# property of onboarding data.
EXCLUDED_FEATURES_IDENTITY = frozenset({
    "max_pan_fanout",
    "max_phone_fanout",
    "max_device_fanout",
})


@dataclass
class IdentityFeatures:
    # -- candidate structure. The AMLworld family that survives ---------------
    n_nodes: int = 0
    n_edges: int = 0
    density: float = 0.0
    mean_degree: float = 0.0
    max_degree: int = 0
    boundary_ratio: float = 0.0        # external neighbours per member

    # -- fragmentation. The adversary's design, and Phase D's subject ---------
    n_components: int = 0
    largest_component_share: float = 0.0
    diameter: int = 0
    mean_component_size: float = 0.0

    # -- attribute multiplicity ----------------------------------------------
    # Which attributes link the members at all, and how heavily. The onboarding
    # analogue of flow: an edge exists because two applications agreed on
    # something, and WHICH something is most of the signal.
    link_share_pan: float = 0.0
    link_share_phone: float = 0.0
    link_share_address: float = 0.0
    link_share_device: float = 0.0
    link_share_ip: float = 0.0
    n_link_attributes: int = 0
    max_internal_value_multiplicity: int = 0
    mean_internal_value_multiplicity: float = 0.0
    rare_value_share: float = 0.0      # linking values held by <= 5 apps
    hub_value_share: float = 0.0       # linking values held by > 50 apps

    # -- rotation. No single attribute spans a rotated cluster ---------------
    spanning_attribute_share: float = 0.0   # best single value's member share
    rotation_index: float = 0.0             # 1 - spanning_attribute_share
    open_triangle_ratio: float = 0.0        # two edges present, third absent
    triangle_density: float = 0.0
    link_type_entropy: float = 0.0          # over which attribute links edges

    # -- attribute fan-out ----------------------------------------------------
    # Global multiplicity of the values the members hold. Separates a shared
    # office IP subnet from a shared handset. Three of these are excluded after
    # measurement; they are computed anyway so the exclusion can be checked.
    max_pan_fanout: int = 0
    max_phone_fanout: int = 0
    max_address_fanout: int = 0
    max_device_fanout: int = 0
    max_ip_fanout: int = 0
    mean_fanout: float = 0.0

    # -- temporal. Deliberate spacing is adversarial -------------------------
    span_days: float = 0.0
    mean_gap_days: float = 0.0
    max_gap_days: float = 0.0
    burst_index: float = 0.0           # busiest 7-day window, as a share

    def to_dict(self) -> dict:
        return asdict(self)

    def vector(self, exclude=EXCLUDED_FEATURES_IDENTITY) -> dict:
        """The feature vector as a scorer may see it: excluded columns removed.

        `to_dict` keeps them so the exclusion stays auditable -- a column that
        vanishes from the record cannot be checked against the numbers that
        justified removing it.
        """
        return {k: v for k, v in self.to_dict().items() if k not in exclude}


def feature_names(exclude=EXCLUDED_FEATURES_IDENTITY) -> list[str]:
    return sorted(IdentityFeatures().vector(exclude))


def _internal_links(nodes: set, apps: dict) -> tuple[dict, dict]:
    """(pair -> set of attributes linking it, (attr, value) -> member ids).

    Recomputed from the applications rather than read off the graph, because
    the graph's edges have lost WHICH attribute created them -- and which
    attribute it was is most of what distinguishes a household from a chain.
    """
    by_value: dict = defaultdict(list)
    for i in nodes:
        app = apps[i]
        for a in ATTRS:
            by_value[(a, getattr(app, a))].append(i)

    links: dict = defaultdict(set)
    groups: dict = {}
    for (attr, value), ids in by_value.items():
        if len(ids) < 2:
            continue
        groups[(attr, value)] = set(ids)
        for u, v in combinations(sorted(ids), 2):
            links[(u, v)].add(attr)
    return links, groups


def _components(nodes: set, adj: dict) -> list[set]:
    seen: set = set()
    out: list = []
    for start in sorted(nodes):
        if start in seen:
            continue
        stack, comp = [start], set()
        seen.add(start)
        while stack:
            u = stack.pop()
            comp.add(u)
            for v in adj.get(u, ()):
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        out.append(comp)
    return out


def _diameter(nodes: set, adj: dict) -> int:
    """Longest shortest path inside the candidate, over all components.

    Exact rather than sampled: candidates are bounded at
    `config.EXPAND_MAX_NODES`, so all-pairs BFS is affordable and an
    approximation would be a second thing to explain.
    """
    best = 0
    for s in nodes:
        dist = {s: 0}
        queue = [s]
        while queue:
            nxt = []
            for u in queue:
                for v in adj.get(u, ()):
                    if v in nodes and v not in dist:
                        dist[v] = dist[u] + 1
                        nxt.append(v)
            queue = nxt
        if dist:
            best = max(best, max(dist.values()))
    return best


def build(nodes, graph, apps: dict, global_counts: dict | None = None) -> IdentityFeatures:
    """Features for one candidate.

    `apps` is app_id -> Application: the observable record, with no labels in
    it. `global_counts` is attribute -> Counter over the whole population, for
    the fan-out family; computed once per world by `population_counts` and
    threaded through, since recomputing it per candidate would be quadratic.

    `graph` is used for one thing only -- the boundary count -- because
    everything else is more precisely computed from the applications, which
    still know WHICH attribute linked two of them.
    """
    nodes = set(nodes)
    f = IdentityFeatures(n_nodes=len(nodes))
    if len(nodes) < 2:
        return f

    links, groups = _internal_links(nodes, apps)
    adj: dict = defaultdict(set)
    for (u, v) in links:
        adj[u].add(v)
        adj[v].add(u)

    n = len(nodes)
    f.n_edges = len(links)
    f.density = f.n_edges / (n * (n - 1) / 2)
    degrees = [len(adj.get(i, ())) for i in nodes]
    f.mean_degree = sum(degrees) / n
    f.max_degree = max(degrees)

    external = set()
    for i in nodes:
        external |= {v for v in graph.neighbours(i) if v not in nodes}
    f.boundary_ratio = len(external) / n

    comps = _components(nodes, adj)
    f.n_components = len(comps)
    f.largest_component_share = max(len(c) for c in comps) / n
    f.mean_component_size = sum(len(c) for c in comps) / len(comps)
    f.diameter = _diameter(nodes, adj)

    attr_link_counts = Counter()
    for attrs in links.values():
        for a in attrs:
            attr_link_counts[a] += 1
    for a in ATTRS:
        setattr(f, f"link_share_{a}", attr_link_counts[a] / f.n_edges)
    f.n_link_attributes = sum(1 for a in ATTRS if attr_link_counts[a])

    sizes = [len(ids) for ids in groups.values()]
    f.max_internal_value_multiplicity = max(sizes)
    f.mean_internal_value_multiplicity = sum(sizes) / len(sizes)
    f.spanning_attribute_share = max(sizes) / n
    f.rotation_index = 1.0 - f.spanning_attribute_share

    counts = global_counts or {}
    if counts:
        globals_of = [counts[a][value] for (a, value) in groups]
        f.rare_value_share = sum(1 for g in globals_of if g <= 5) / len(globals_of)
        f.hub_value_share = sum(1 for g in globals_of if g > 50) / len(globals_of)
        for a in ATTRS:
            setattr(f, f"max_{a}_fanout",
                    max(counts[a][getattr(apps[i], a)] for i in nodes))
        # `sorted`, and iterating ATTRS rather than a dict, for the reason
        # `dominant_entity_type` is commented the way it is in
        # sentinel/detect/features.py: a float sum that follows set-iteration
        # order is a value that depends on node ids. It was caught here by the
        # index-invariance test, disagreeing in the last bit.
        f.mean_fanout = sum(
            counts[a][getattr(apps[i], a)] for i in sorted(nodes) for a in ATTRS
        ) / (n * len(ATTRS))

    closed = open_ = 0
    for u in sorted(nodes):
        nbrs = sorted(v for v in adj.get(u, ()) if v > u)
        for v, w in combinations(nbrs, 2):
            if w in adj.get(v, ()):
                closed += 1
            else:
                open_ += 1
    triples = closed + open_
    if triples:
        f.open_triangle_ratio = open_ / triples
        f.triangle_density = closed / triples

    total_links = sum(attr_link_counts.values())
    if total_links:
        # Summed over ATTRS in its fixed order, not over the Counter, for the
        # same reason as `mean_fanout` above.
        f.link_type_entropy = -sum(
            (attr_link_counts[a] / total_links)
            * math.log2(attr_link_counts[a] / total_links)
            for a in ATTRS if attr_link_counts[a])

    ts = sorted(apps[i].ts for i in nodes)
    f.span_days = (ts[-1] - ts[0]) / MINUTES_PER_DAY
    gaps = [(b - a) / MINUTES_PER_DAY for a, b in zip(ts, ts[1:])]
    f.mean_gap_days = sum(gaps) / len(gaps)
    f.max_gap_days = max(gaps)
    window = 7 * MINUTES_PER_DAY
    best = 0
    for i, t0 in enumerate(ts):
        j = i
        while j < len(ts) and ts[j] - t0 <= window:
            j += 1
        best = max(best, j - i)
    f.burst_index = best / n

    return f


def population_counts(applications) -> dict:
    """attribute -> Counter of value multiplicities over the whole population.

    Population-level context, not a label: how many applications hold a value
    is observable to anyone with the queue.
    """
    return {a: Counter(getattr(app, a) for app in applications) for a in ATTRS}
