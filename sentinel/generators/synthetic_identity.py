"""The synthetic-identity domain, generated to the process pre-registered in
`prereg/synthetic_identity_generator.md`.

The generative process was committed before this file existed. Where a constant
here disagrees with that file, that file is right and this one is a bug.

Two things about the shape of this module are load-bearing:

**`Application` has no label field.** Observables and ground truth leave the
generator as two separate objects (`World.applications` and `World.clusters`),
because in a generated domain the labels are written by the same code that
writes the data. A feature module that can reach the truth side has a leak that
no prevalence audit would catch, so the truth side is somewhere it cannot reach
by accident.

**The background is the experiment.** Households, offices, landlords, joint
accounts and roommates are not decoration -- each one exists to make a specific
trivial baseline fail, and `prereg/synthetic_identity_kill_rule.md` names which.
If the background is thin, a degree count solves the problem and the graph
engine is measuring its own generator.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# The observable attribute schema. Order is fixed because it is iterated during
# rotation and a reorder would change every world for a given seed.
ATTRS = ("pan", "phone", "address", "device", "ip")

MINUTES_PER_DAY = 1440
SPAN_DAYS = 90
SPAN = SPAN_DAYS * MINUTES_PER_DAY

# Mean gap between one fraudulent registration and the next, in days. Deliberate
# spacing is adversarial; see the prereg's temporal section.
FRAUD_GAP_DAYS = 6.0

# Mixture over legitimate APPLICATIONS -- not over draws. Sums to 1.0; asserted
# at import.
LEGIT_MIX = {
    "solo": 0.34,
    "household": 0.30,
    "office": 0.16,
    "roommates": 0.10,
    "landlord": 0.06,
    "joint": 0.04,
}
assert abs(sum(LEGIT_MIX.values()) - 1.0) < 1e-9

# Expected applications per draw of each structure, from the size ranges in
# `_legit_group`. A structure is SELECTED with probability proportional to
# `LEGIT_MIX[k] / EXPECTED_SIZE[k]`, which is what makes the mixture a mixture
# over applications. Weighting the draws directly would put ~83% of the
# population inside offices at a nominal weight of 0.16, because one office draw
# is worth a hundred solo draws.
EXPECTED_SIZE = {
    "solo": 1.0,
    "household": 3.5,
    "joint": 2.5,
    "office": 110.0,
    "landlord": 17.5,
    "roommates": 3.0,
}

# Target share of applications that belong to a planted cluster.
FRAUD_SHARE = 0.05

# The sweep, and the one configuration that speaks for it.
ROTATION_RATES = (0.3, 0.5, 0.7)
CLUSTER_SIZES = (3, 5, 8, 12)
OVERLAPS = (0.0, 0.1, 0.2)
PRIMARY = {"rotation_rate": 0.5, "cluster_size": 8, "overlap": 0.1}


@dataclass(frozen=True, slots=True)
class Application:
    """One onboarding application, as an investigator would see it.

    No label. Not an oversight -- see the module docstring.
    """

    app_id: int
    ts: int
    pan: str
    phone: str
    address: str
    device: str
    ip: str

    def attrs(self) -> dict:
        return {a: getattr(self, a) for a in ATTRS}


@dataclass
class World:
    """One generated population: observables, ground truth, and provenance."""

    applications: list = field(default_factory=list)
    clusters: list = field(default_factory=list)   # list[set[app_id]]
    params: dict = field(default_factory=dict)
    background: dict = field(default_factory=dict)

    @property
    def fraudulent(self) -> set:
        out: set = set()
        for c in self.clusters:
            out |= c
        return out

    def prevalence(self) -> float:
        n = len(self.applications)
        return (len(self.fraudulent) / n) if n else 0.0


class _Values:
    """Fresh attribute values, and a pool of legitimate ones to steal from.

    The steal pool is what `overlap` draws on: a synthetic identity registering
    against a real office's IP subnet is the reason the adversary does not live
    in its own disconnected corner of the value space.
    """

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self._n: Counter = Counter()
        self.pool: dict = defaultdict(list)

    def fresh(self, kind: str) -> str:
        self._n[kind] += 1
        return f"{kind}:{self._n[kind]}"

    def offer(self, kind: str, value: str) -> None:
        """Publish a legitimate value as stealable."""
        self.pool[kind].append(value)

    def steal(self, kind: str) -> str:
        vals = self.pool.get(kind)
        if not vals:
            return self.fresh(kind)
        return self.rng.choice(vals)


def _legit_group(kind: str, vals: _Values, rng: random.Random) -> list:
    """One legitimate co-occurrence structure, as a list of attribute dicts.

    Every branch here is answering a baseline. The table in
    `prereg/synthetic_identity_kill_rule.md` says which.
    """
    def base() -> dict:
        return {a: vals.fresh(a) for a in ATTRS}

    if kind == "solo":
        return [base()]

    if kind == "household":
        n = rng.randint(2, 5)
        addr, ip = vals.fresh("address"), vals.fresh("ip")
        phone = vals.fresh("phone") if rng.random() < 0.6 else None
        device = vals.fresh("device") if rng.random() < 0.5 else None
        vals.offer("address", addr)
        out = []
        for _ in range(n):
            a = base()
            a["address"], a["ip"] = addr, ip
            if phone:
                a["phone"] = phone
            if device:
                a["device"] = device
            out.append(a)
        return out

    if kind == "joint":
        # The only legitimate reason two applications share a PAN. Small on
        # purpose: without it, a shared-PAN count alone names the adversary.
        n = rng.randint(2, 3)
        pan, phone, addr = (vals.fresh("pan"), vals.fresh("phone"),
                            vals.fresh("address"))
        vals.offer("address", addr)
        out = []
        for _ in range(n):
            a = base()
            a["pan"], a["phone"], a["address"] = pan, phone, addr
            out.append(a)
        return out

    if kind == "office":
        n = rng.randint(20, 200)
        ip = vals.fresh("ip")
        addr = vals.fresh("address") if rng.random() < 0.7 else None
        vals.offer("ip", ip)
        if addr:
            vals.offer("address", addr)
        out = []
        for _ in range(n):
            a = base()
            a["ip"] = ip
            if addr:
                a["address"] = addr
            out.append(a)
        return out

    if kind == "landlord":
        n = rng.randint(5, 30)
        addr = vals.fresh("address")
        vals.offer("address", addr)
        out = []
        for _ in range(n):
            a = base()
            a["address"] = addr
            out.append(a)
        return out

    if kind == "roommates":
        n = rng.randint(2, 4)
        addr, ip = vals.fresh("address"), vals.fresh("ip")
        out = []
        for _ in range(n):
            a = base()
            a["address"], a["ip"] = addr, ip
            out.append(a)
        return out

    raise ValueError(f"unknown legitimate structure {kind!r}")


def _rotation_chain(size: int, rotation_rate: float, overlap: float,
                    vals: _Values, rng: random.Random) -> list:
    """A fraudulent cluster, as a chain of attribute dicts.

    Each hop shares at least one attribute with its predecessor and rotates at
    least one. Those two constraints are the adversary: without the first there
    is no cluster, without the second the cluster is a clique and one attribute
    links the whole of it. With both, A shares a device with B, B shares an
    address with C, and A and C share nothing.
    """
    cur = {a: vals.fresh(a) for a in ATTRS}
    chain = [dict(cur)]
    for _ in range(size - 1):
        rotated = [a for a in ATTRS if rng.random() < rotation_rate]
        # Force at least one of each, so the chain neither breaks nor collapses.
        if not rotated:
            rotated = [rng.choice(ATTRS)]
        if len(rotated) == len(ATTRS):
            rotated.remove(rng.choice(rotated))
        nxt = dict(cur)
        for a in rotated:
            nxt[a] = vals.fresh(a)
        if rng.random() < overlap:
            a = rng.choice(ATTRS)
            nxt[a] = vals.steal(a)
        chain.append(nxt)
        cur = nxt
    return chain


def generate(seed: int, n_apps: int = 4000, rotation_rate: float = 0.5,
             cluster_size: int = 8, overlap: float = 0.1,
             fraud_share: float = FRAUD_SHARE) -> World:
    """One world. A deterministic function of (seed, params).

    Legitimate structures are drawn first so that their values are in the steal
    pool by the time the adversary wants one.
    """
    rng = random.Random(seed)
    vals = _Values(rng)

    n_fraud_target = int(round(n_apps * fraud_share))
    n_legit_target = n_apps - n_fraud_target

    kinds = list(LEGIT_MIX)
    weights = [LEGIT_MIX[k] / EXPECTED_SIZE[k] for k in kinds]

    legit_attrs: list = []
    group_of: list = []
    while len(legit_attrs) < n_legit_target:
        kind = rng.choices(kinds, weights=weights)[0]
        group = _legit_group(kind, vals, rng)
        for a in group:
            legit_attrs.append(a)
            group_of.append(kind)

    fraud_chains: list = []
    n_fraud = 0
    while n_fraud < n_fraud_target:
        size = min(cluster_size, n_fraud_target - n_fraud)
        if size < 2:
            break
        chain = _rotation_chain(size, rotation_rate, overlap, vals, rng)
        fraud_chains.append(chain)
        n_fraud += len(chain)

    apps: list = []
    clusters: list = []

    for a in legit_attrs:
        apps.append((rng.randrange(SPAN), a))

    for chain in fraud_chains:
        t = rng.randrange(SPAN)
        ids = []
        for a in chain:
            apps.append((min(t, SPAN - 1), a))
            ids.append(len(apps) - 1)  # provisional; remapped after the shuffle
            t += int(rng.expovariate(1.0 / (FRAUD_GAP_DAYS * MINUTES_PER_DAY)))
        clusters.append(ids)

    # Shuffle so app_id order carries no information about who was generated
    # when or by which branch, then remap the ground truth onto the new ids.
    order = list(range(len(apps)))
    rng.shuffle(order)
    new_id = {old: i for i, old in enumerate(order)}

    applications: list = [None] * len(apps)
    for old, i in new_id.items():
        ts, a = apps[old]
        applications[i] = Application(app_id=i, ts=int(ts), **a)

    clusters = [{new_id[o] for o in ids} for ids in clusters]

    return World(
        applications=applications,
        clusters=clusters,
        params={"seed": seed, "n_apps": len(applications),
                "rotation_rate": rotation_rate, "cluster_size": cluster_size,
                "overlap": overlap, "fraud_share": fraud_share},
        background=background_stats(applications, group_of),
    )


def background_stats(applications: list, group_kinds: list | None = None) -> dict:
    """Density of legitimate co-occurrence, logged per world.

    The prereg's claim is that the background is dense enough to defeat a
    counting baseline. That claim is a number, so it is measured here rather
    than asserted, and it travels with every world.
    """
    per_attr = {}
    for a in ATTRS:
        counts = Counter(getattr(app, a) for app in applications)
        multi = [c for c in counts.values() if c > 1]
        per_attr[a] = {
            "distinct_values": len(counts),
            "shared_values": len(multi),
            "max_multiplicity": max(counts.values()) if counts else 0,
            "mean_apps_per_shared_value": (sum(multi) / len(multi)) if multi else 0.0,
        }
    out = {"per_attribute": per_attr}
    if group_kinds is not None:
        out["legit_structures"] = dict(Counter(group_kinds))
    return out


def cooccurrence(applications: list, max_multiplicity: int | None = None) -> dict:
    """app_id -> set of app_ids sharing at least one attribute value.

    `max_multiplicity` drops attribute values held by more than that many
    applications before linking. It is not a hub guard for the detector -- it is
    what makes the `rare_multiplicity` baseline possible, and that baseline is
    the one the kill rule expects to be dangerous.
    """
    by_value: dict = defaultdict(list)
    for app in applications:
        for a in ATTRS:
            by_value[(a, getattr(app, a))].append(app.app_id)

    adj: dict = defaultdict(set)
    for ids in by_value.values():
        if len(ids) < 2:
            continue
        if max_multiplicity is not None and len(ids) > max_multiplicity:
            continue
        for i in ids:
            adj[i].update(ids)
    for i, s in adj.items():
        s.discard(i)
    return adj


def components(adj: dict, n: int) -> dict:
    """app_id -> size of its connected component in `adj`."""
    seen: dict = {}
    for start in range(n):
        if start in seen:
            continue
        stack, comp = [start], []
        seen[start] = -1
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in adj.get(u, ()):
                if v not in seen:
                    seen[v] = -1
                    stack.append(v)
        for u in comp:
            seen[u] = len(comp)
    return seen
