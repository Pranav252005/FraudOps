"""The synthetic-identity domain, run through the existing harness.

Nothing here re-implements a primitive. `WindowedGraph`, `CandidateGenerator`,
`FunnelTracker` and `is_hit` are the same objects AMLworld uses, which is the
whole point: a cross-domain claim made with two different pipelines is a claim
about the pipelines.

Three things had to be decided rather than inherited, and all three are
pre-registered in `prereg/synthetic_identity_generator.md` and
`prereg/synthetic_identity_kill_rule.md`:

**No window.** The graph is built in one static pass, reusing the path
`sentinel/eval/dataset.py` opened for Elliptic2. `WINDOW_MINUTES` is an
AMLworld constant and it does not travel: this adversary's strategy *includes*
deliberate temporal spacing, so fragmentation measured under a window would be
partly the window's own artefact -- which is the AMLworld finding re-derived
rather than a contrast with it.

**The seed rule is exogenous.** AMLworld seeds on pass-through -- money in and
out -- and there is no flow in onboarding data. Worse, the co-occurrence graph
is undirected, so every application would be a pass-through account and the
seed rule would fire on all 4,000. So a seed is an outside signal: a chargeback,
a manual report, a failed step-up, at pre-registered rates.

**The seed rule reads ground truth, and features never may.** That asymmetry is
deliberate and is the one place truth enters. An exogenous signal is *correlated
with* fraud by definition -- that is what makes it a signal -- and modelling it
requires knowing who is fraudulent. It lives here, in the evaluation harness,
and `sentinel/generators/synthetic_identity.py` keeps `Application` label-free
so that no feature can reach the same information.

`is_hit`'s Jaccard floor is inherited UNCHANGED at 0.3. Whether 0.3 is the right
floor for identity clusters is an empirical question, but changing it would
invalidate every cross-domain comparison, so it is fixed before measuring rather
than tuned after.
"""
from __future__ import annotations

import random
from collections import defaultdict

import numpy as np

from sentinel import config
from sentinel.detect.candidates import CandidateGenerator
from sentinel.eval.dataset import StaticBatch
from sentinel.eval.funnel import FunnelTracker
from sentinel.generators import synthetic_identity as gen
from sentinel.graph.window import WindowedGraph

# The dataset name this domain's corpora are keyed by. Distinct from
# "amlworld-hi-small", and that distinction is now load-bearing:
# `require_same_dataset` refuses to pool the two, which `candidate_provenance`
# would not have done -- both domains construct their candidates.
DATASET = "synthetic-identity-v1"

# Every cluster is one adversarial shape, so there is one typology. Named rather
# than left blank because `FunnelTracker` reports per typology, and "UNKNOWN"
# in a funnel table reads as a defect.
TYPOLOGY = "ROTATION-CHAIN"

# A window wide enough never to expire anything: the static-pass idiom
# `sentinel/eval/dataset.py` established for a dataset with no usable time axis.
NO_WINDOW = 10 ** 9


def seed_applications(world, salt: int = 0) -> set[int]:
    """The exogenous seed signal, at the pre-registered rates.

    Deterministic in `(world seed, salt)` so a run is reproducible, and drawn
    independently of the graph so that seeding cannot be tuned by the detector.
    The legitimate rate is non-zero on purpose: an investigation that only ever
    starts from a true positive is not an investigation, and false-alarm seeds
    are what make expansion's precision cost visible.
    """
    rng = random.Random(f"seed-rule:{world.params['seed']}:{salt}")
    fraud = world.fraudulent
    out = set()
    for app in world.applications:
        rate = (config.IDENTITY_SEED_RATE_FRAUD if app.app_id in fraud
                else config.IDENTITY_SEED_RATE_LEGIT)
        if rng.random() < rate:
            out.add(app.app_id)
    return out


def world_batch(world, max_multiplicity: int | None = None) -> StaticBatch:
    """One co-occurrence edge per pair of applications sharing a value.

    Emitted once per pair rather than in both directions: `WindowedGraph`
    already ignores direction when it expands, for its own reason -- a mule
    receiving from one account and paying another is one structure -- and that
    is exactly the semantics an undirected co-occurrence edge wants.

    `amount` is 1.0 on every edge and `is_laundering` is 0 on every edge. There
    are no amounts in onboarding data and no per-edge labels, so every
    amount-derived feature in `sentinel/detect/features.py` is meaningless here
    rather than merely weak. Phase C replaces them; until then, this is why the
    numbers a shared scorer produces on this domain are not to be quoted.
    """
    by_value: dict = defaultdict(list)
    for app in world.applications:
        for a in gen.ATTRS:
            by_value[(a, getattr(app, a))].append(app.app_id)

    pairs: set = set()
    for ids in by_value.values():
        if len(ids) < 2:
            continue
        if max_multiplicity is not None and len(ids) > max_multiplicity:
            continue
        for i, u in enumerate(ids):
            for v in ids[i + 1:]:
                pairs.add((u, v) if u < v else (v, u))

    n = len(pairs)
    src = np.empty(n, dtype=np.int32)
    dst = np.empty(n, dtype=np.int32)
    for i, (u, v) in enumerate(sorted(pairs)):
        src[i], dst[i] = u, v
    return StaticBatch(t_start=0, t_end=1, ts=np.zeros(n, dtype=np.int32),
                        src=src, dst=dst,
                        amount=np.ones(n, dtype=np.float64),
                        is_laundering=np.zeros(n, dtype=np.int8))


def build_graph(world, max_multiplicity: int | None = None):
    graph = WindowedGraph(window_minutes=NO_WINDOW)
    batch = world_batch(world, max_multiplicity=max_multiplicity)
    graph.add_batch(batch)
    return graph, batch


def cluster_membership(world) -> tuple[dict, dict]:
    """cluster index -> member app ids, and index -> typology.

    Clusters of fewer than two applications are dropped, matching
    `sentinel.eval.dataset.ring_membership`: there is no structure to find in a
    singleton and keeping it would inflate the funnel's denominator.
    """
    members, typology = {}, {}
    for i, c in enumerate(world.clusters):
        if len(c) < 2:
            continue
        members[i] = set(c)
        typology[i] = TYPOLOGY
    return members, typology


def run_identity_funnel(world, rank_k: int = 50, hops: int = config.EXPAND_HOPS,
                        max_nodes: int = config.EXPAND_MAX_NODES,
                        max_degree: int = config.EXPAND_MAX_DEGREE,
                        salt: int = 0, max_multiplicity: int | None = None):
    """One seed-and-expand pass over a whole world, scored against its clusters.

    The identity counterpart of `sentinel.eval.dataset.run_static_funnel`, and
    it differs in exactly one line: `seed_override`. That function calls the
    generator's own pass-through seed rule, which on an undirected co-occurrence
    graph fires on every node.

    Returns (tracker, candidates, seeds).
    """
    graph, batch = build_graph(world, max_multiplicity=max_multiplicity)
    seeds = seed_applications(world, salt=salt)

    generator = CandidateGenerator(graph, hops=hops, max_nodes=max_nodes,
                                    max_degree=max_degree)
    candidates = generator.generate(batch, seed_override=seeds)

    members, typology = cluster_membership(world)
    tracker = FunnelTracker(rank_k=rank_k)
    tracker.observe_cycle(members, lambda c: typology.get(c, "UNKNOWN"),
                           seed_nodes=seeds, candidates=candidates)
    return tracker, candidates, seeds
