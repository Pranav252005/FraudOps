"""Phase D: seed-reach coverage, in both domains, on one definition.

Runs the predictions pre-registered in
`prereg/synthetic_identity_fragmentation.md`:

  P1  identity coverage decreases monotonically in rotation_rate
  P2  coverage(0.7) - coverage(0.3) < 0, interval excluding zero   <- decides
  P3  cluster diameter increases monotonically in rotation_rate    <- mechanism

and, as a SECONDARY DESCRIPTIVE arm, the same quantity on AMLworld -- reported
beside the identity number, never pooled with it.

    python scripts/eval_fragmentation.py                 # identity only
    python scripts/eval_fragmentation.py --with-amlworld # adds the replay

The quantity is what the investigation can SEE from where it started:

    reach    = expand(seeds inside the group, shipped hops/caps/hub guard)
    coverage = |group & reach| / |group|

Not `is_hit`, not candidate containment -- those come after scoring, pruning and
suppression, and the finding this phase is about happens before any of them.
Groups with no seeded member are excluded and their share reported: with no seed
there is nothing to have coverage from, and scoring them zero would fold a
seeding failure into a reach measurement.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sentinel import config                                          # noqa: E402
from sentinel.data.datasets import active as _active_dataset
from sentinel.data.datasets import active_stream_dir
from sentinel.corpus import CorpusKey, stratify_by_dataset           # noqa: E402
from sentinel.eval import identity as ident                          # noqa: E402
from sentinel.eval.bootstrap import bootstrap_ci                     # noqa: E402
from sentinel.generators import synthetic_identity as gen            # noqa: E402

#: The split in play. This module used `DATASET` without defining it.
DATASET = _active_dataset()

PREREG = ("prereg/synthetic_identity_fragmentation.md",)
OUT = ROOT / "data" / "fragmentation.json"

# From the prereg. A divergence here is a bug in this file.
PRIMARY_SIZE = 8
OVERLAPS = (0.0, 0.1)          # 0.2 was marked TOO_EASY by Phase A's kill rule
SECONDARY_SIZES = (3, 5, 12)
WORLDS = 20
N_RESAMPLES = 2000
SEED = 7


def require_committed_prereg() -> dict:
    shas = {}
    for rel in PREREG:
        if not (ROOT / rel).is_file():
            raise SystemExit(f"refusing to run: {rel} does not exist.")
        log = subprocess.run(["git", "log", "-1", "--format=%H", "--", rel],
                             cwd=ROOT, capture_output=True, text=True)
        sha = log.stdout.strip()
        if log.returncode != 0 or not sha:
            raise SystemExit(
                f"refusing to run: {rel} is not committed. An uncommitted "
                f"prereg can be edited after seeing the result, which is the "
                f"entire thing a pre-registration exists to prevent.")
        dirty = subprocess.run(["git", "status", "--porcelain", "--", rel],
                               cwd=ROOT, capture_output=True, text=True)
        if dirty.stdout.strip():
            raise SystemExit(f"refusing to run: {rel} has uncommitted changes.")
        shas[rel] = sha
    return shas


# -- the shared quantity ----------------------------------------------------

def coverage_of(group: set, seeds: set, graph) -> float | None:
    """What a 2-hop expansion from the group's own seeds can see of it.

    Returns None when the group has no seed, which is an exclusion and not a
    zero.
    """
    inside = group & seeds
    if not inside:
        return None
    reach = graph.expand(sorted(inside), hops=config.EXPAND_HOPS,
                          max_nodes=config.EXPAND_MAX_NODES,
                          max_degree=config.EXPAND_MAX_DEGREE)
    return len(group & reach) / len(group)


def induced_shape(group: set, graph) -> tuple[int, int]:
    """(components, diameter) of the group on its OWN edges.

    The mechanism behind P1: at low rotation an attribute value survives many
    hops so the cluster is near-clique; at high rotation values die quickly and
    it degenerates towards a path a 2-hop expansion cannot cross.
    """
    adj = {u: {v for v in graph.neighbours(u) if v in group} for u in group}

    seen, comps = set(), 0
    for start in sorted(group):
        if start in seen:
            continue
        comps += 1
        stack = [start]
        seen.add(start)
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)

    diameter = 0
    for s in group:
        dist, queue = {s: 0}, [s]
        while queue:
            nxt = []
            for u in queue:
                for v in adj[u]:
                    if v not in dist:
                        dist[v] = dist[u] + 1
                        nxt.append(v)
            queue = nxt
        diameter = max(diameter, max(dist.values()))
    return comps, diameter


# -- identity arm -----------------------------------------------------------

def identity_config(rotation_rate: float, cluster_size: int, overlap: float,
                    worlds: int = WORLDS) -> dict:
    """Per-world mean coverage, diameter and component count."""
    per_world = []
    for seed in range(worlds):
        world = gen.generate(seed=seed, rotation_rate=rotation_rate,
                              cluster_size=cluster_size, overlap=overlap)
        graph, _ = ident.build_graph(world)
        seeds = ident.seed_applications(world)
        members, _ = ident.cluster_membership(world)

        covs, diams, comps = [], [], []
        eligible = 0
        for group in members.values():
            comp, diam = induced_shape(group, graph)
            diams.append(diam)
            comps.append(comp)
            c = coverage_of(group, seeds, graph)
            if c is not None:
                eligible += 1
                covs.append(c)
        per_world.append({
            "coverage": sum(covs) / len(covs) if covs else None,
            "diameter": sum(diams) / len(diams),
            "components": sum(comps) / len(comps),
            "seeded_share": eligible / len(members) if members else 0.0,
            "n_groups": len(members),
        })

    usable = [w for w in per_world if w["coverage"] is not None]
    ci = bootstrap_ci(usable, lambda ws: sum(w["coverage"] for w in ws) / len(ws),
                       n_resamples=N_RESAMPLES, seed=SEED)
    return {
        "params": {"rotation_rate": rotation_rate, "cluster_size": cluster_size,
                    "overlap": overlap},
        "coverage": {**ci, "ci_method": "world_clustered_bootstrap"},
        "diameter": sum(w["diameter"] for w in per_world) / len(per_world),
        "components": sum(w["components"] for w in per_world) / len(per_world),
        "seeded_share": sum(w["seeded_share"] for w in per_world) / len(per_world),
        "n_worlds": len(per_world),
        "_per_world": [w["coverage"] for w in per_world],
    }


def paired_delta(hi: dict, lo: dict) -> dict:
    """coverage(0.7) - coverage(0.3), resampling the SAME worlds on both sides.

    Paired because the two arms differ only in `rotation_rate`: world 3's
    background is the same background on both sides, so pairing removes
    between-world variance that is not what the prediction is about.
    """
    pairs = [(a, b) for a, b in zip(hi["_per_world"], lo["_per_world"])
             if a is not None and b is not None]
    rng = random.Random(SEED)
    draws = []
    for _ in range(N_RESAMPLES):
        sample = [pairs[rng.randrange(len(pairs))] for _ in pairs]
        draws.append(sum(a - b for a, b in sample) / len(sample))
    draws.sort()
    return {"point": sum(a - b for a, b in pairs) / len(pairs),
            "lo": draws[int(0.025 * N_RESAMPLES)],
            "hi": draws[min(int(0.975 * N_RESAMPLES), N_RESAMPLES - 1)],
            "n_pairs": len(pairs),
            "ci_method": "paired_world_clustered_bootstrap"}


# -- amlworld arm (secondary, descriptive) ----------------------------------

def _clustered(rows, key_index, value):
    keys = sorted({r[key_index] for r in rows})
    groups = defaultdict(list)
    for r in rows:
        groups[r[key_index]].append(r)
    rng = random.Random(SEED)
    draws = []
    for _ in range(N_RESAMPLES):
        sample = [x for _ in keys for x in groups[keys[rng.randrange(len(keys))]]]
        draws.append(value(sample) if sample else 0.0)
    draws.sort()
    return (draws[int(0.025 * N_RESAMPLES)],
            draws[min(int(0.975 * N_RESAMPLES), N_RESAMPLES - 1)])


def amlworld_coverage(every: int = 6) -> dict:
    """The same quantity over the compiled AMLworld stream.

    Rule 5: these trials nest within rings -- one ring recurs across cycles --
    so both clusterings are computed and the WIDER interval is reported.
    """
    from sentinel.data.accounts import AccountRegistry
    from sentinel.detect.candidates import CandidateGenerator
    from sentinel.graph.window import WindowedGraph
    from sentinel.stream.replay import Stream

    stream = Stream(active_stream_dir(ROOT))
    registry = AccountRegistry.load(
        DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=config.WINDOW_MINUTES)
    generator = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    rows = []            # (cycle, ring, coverage)
    seen_rings, seeded_rings = set(), set()
    for i, batch in enumerate(stream.ticks(config.TICK_MINUTES,
                                            end=config.EVAL_END)):
        graph.add_batch(batch)
        if i % every or graph.now < config.WINDOW_MINUTES // 2:
            continue
        lo, hi = graph.now - graph.window, graph.now
        mask = ((stream.ts >= lo) & (stream.ts < hi) & (stream.ring >= 0))
        members = defaultdict(set)
        for a, b, r in zip(stream.src[mask], stream.dst[mask], stream.ring[mask]):
            members[int(r)] |= {int(a), int(b)}
        if not members:
            continue
        seeds = generator.seeds(batch)
        if not seeds:
            continue
        for ring, group in members.items():
            if len(group) < 2:
                continue
            seen_rings.add(ring)
            c = coverage_of(group, seeds, graph)
            if c is None:
                continue
            seeded_rings.add(ring)
            rows.append((i, ring, c))

    def mean(rs):
        return sum(r[2] for r in rs) / len(rs) if rs else 0.0

    lo_c, hi_c = _clustered(rows, 0, mean)
    lo_r, hi_r = _clustered(rows, 1, mean)
    return {
        "coverage": {
            "point": mean(rows), "lo": min(lo_c, lo_r), "hi": max(hi_c, hi_r),
            "cycle_clustered": {"lo": lo_c, "hi": hi_c, "width": hi_c - lo_c},
            "ring_clustered": {"lo": lo_r, "hi": hi_r, "width": hi_r - lo_r},
            "ci_method": "wider_of_cycle_and_ring_clustered_bootstrap"},
        "n_trials": len(rows),
        "n_rings": len(seeded_rings),
        "n_rings_seen": len(seen_rings),
        "seeded_share": len(seeded_rings) / len(seen_rings) if seen_rings else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=WORLDS)
    ap.add_argument("--with-amlworld", action="store_true")
    args = ap.parse_args()

    shas = require_committed_prereg()
    for rel, sha in shas.items():
        print(f"pre-registration {rel} committed at {sha[:7]}")

    # -- primary -------------------------------------------------------------
    primary = {}
    print(f"\nidentity, cluster_size={PRIMARY_SIZE}")
    for overlap in OVERLAPS:
        for rot in gen.ROTATION_RATES:
            r = identity_config(rot, PRIMARY_SIZE, overlap, worlds=args.worlds)
            primary[(rot, overlap)] = r
            cov = r["coverage"]
            print(f"  rot={rot} ovl={overlap}  coverage {cov['point']:.4f} "
                  f"[{cov['lo']:.4f}, {cov['hi']:.4f}] world-clustered   "
                  f"diameter {r['diameter']:.2f}  components "
                  f"{r['components']:.2f}  seeded {r['seeded_share']:.2f}")

    results = {"predictions": {}, "primary": [], "secondary_sizes": [],
               "prereg": shas}
    for (rot, ovl), r in primary.items():
        results["primary"].append({k: v for k, v in r.items()
                                    if not k.startswith("_")})

    verdicts = {}
    for overlap in OVERLAPS:
        covs = [primary[(rot, overlap)]["coverage"]["point"]
                for rot in gen.ROTATION_RATES]
        diams = [primary[(rot, overlap)]["diameter"]
                 for rot in gen.ROTATION_RATES]
        delta = paired_delta(primary[(0.7, overlap)], primary[(0.3, overlap)])
        verdicts[f"overlap={overlap}"] = {
            "P1_monotone_decreasing": covs[0] > covs[1] > covs[2],
            "P2_delta": delta,
            "P2_pass": delta["point"] < 0 and delta["hi"] < 0,
            "P3_diameter_monotone_increasing": diams[0] < diams[1] < diams[2],
            "coverage_by_rotation": dict(zip(map(str, gen.ROTATION_RATES), covs)),
            "diameter_by_rotation": dict(zip(map(str, gen.ROTATION_RATES), diams)),
        }
    results["predictions"] = verdicts

    print("\npredictions")
    for name, v in verdicts.items():
        d = v["P2_delta"]
        print(f"  {name}")
        print(f"    P1 monotone decreasing coverage: "
              f"{'HOLDS' if v['P1_monotone_decreasing'] else 'FAILS'}")
        print(f"    P2 delta(0.7-0.3) = {d['point']:+.4f} "
              f"[{d['lo']:+.4f}, {d['hi']:+.4f}] paired world-clustered: "
              f"{'HOLDS' if v['P2_pass'] else 'FAILS'}")
        print(f"    P3 monotone increasing diameter: "
              f"{'HOLDS' if v['P3_diameter_monotone_increasing'] else 'FAILS'}")

    # -- secondary sweep -----------------------------------------------------
    print("\nsecondary sweep (reported, not tested)")
    for size in SECONDARY_SIZES:
        for rot in gen.ROTATION_RATES:
            r = identity_config(rot, size, 0.1, worlds=args.worlds)
            results["secondary_sizes"].append(
                {k: v for k, v in r.items() if not k.startswith("_")})
            print(f"  size={size:>2} rot={rot}  "
                  f"coverage {r['coverage']['point']:.4f}  "
                  f"diameter {r['diameter']:.2f}")

    # -- secondary cross-domain contrast ------------------------------------
    if args.with_amlworld:
        print("\namlworld replay (secondary, descriptive)")
        t0 = time.time()
        aml = amlworld_coverage()
        results["amlworld"] = aml
        cov = aml["coverage"]
        print(f"  coverage {cov['point']:.4f} [{cov['lo']:.4f}, {cov['hi']:.4f}] "
              f"{cov['ci_method']}  "
              f"({aml['n_trials']} trials, {aml['n_rings']} rings, "
              f"{time.time() - t0:.0f}s)")

        idn = primary[(0.5, 0.1)]["coverage"]["point"]
        strata = stratify_by_dataset(
            [CorpusKey.for_current_config("amlworld-hi-small", ["n_nodes"],
                                           "constructed"),
             CorpusKey.for_current_config(ident.DATASET, ["n_nodes"],
                                           "constructed")],
            [cov["point"], idn])
        results["side_by_side"] = {k: v for k, v in strata.items()}
        print(f"  side by side (never pooled): {results['side_by_side']}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nwritten to {OUT.relative_to(ROOT)}")

    decided = all(v["P2_pass"] for v in verdicts.values())
    print(f"P2, which decides: {'HOLDS' if decided else 'FAILS'} on every "
          f"overlap arm")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
