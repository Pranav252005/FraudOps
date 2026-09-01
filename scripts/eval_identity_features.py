"""Phase C gate: does any identity feature read the generator instead of the data?

Runs the two arms pre-registered in `prereg/synthetic_identity_features.md`:

  1. STRUCTURAL -- permute the ground-truth cluster assignment and recompute.
     Every feature value must come back bit-identical. Exact, not statistical.
  2. MEASURED -- per-feature AUC over candidates. A single feature at AUC >= 0.99
     is near-deterministic separation, which is what a generator artefact looks
     like and not what a real signal looks like.

Also reports the evidence behind the pre-registered exclusion rule: the measured
legitimate and fraudulent maximum multiplicity of all five attributes, so the
decision to drop three of the fan-out features can be checked rather than taken
on trust.

    python scripts/eval_identity_features.py
    python scripts/eval_identity_features.py --worlds 20

Refuses to run without a committed, clean pre-registration.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sentinel.detect import identity_features as IF                  # noqa: E402
from sentinel.eval import identity as ident                          # noqa: E402
from sentinel.eval.bootstrap import bootstrap_ci                     # noqa: E402
from sentinel.eval.funnel import is_hit                              # noqa: E402
from sentinel.generators import synthetic_identity as gen            # noqa: E402

PREREG = ("prereg/synthetic_identity_features.md",)
OUT = ROOT / "data" / "identity_features.json"

# Transcribed from the prereg. A divergence here is a bug in this file.
LEAK_AUC = 0.99
MAX_TRIPPING_FEATURES = 5
WORLDS = 20


def require_committed_prereg() -> dict:
    shas = {}
    for rel in PREREG:
        if not (ROOT / rel).is_file():
            raise SystemExit(
                f"refusing to run: {rel} does not exist. The pre-registration "
                f"is written BEFORE the experiment, not alongside it.")
        log = subprocess.run(["git", "log", "-1", "--format=%H", "--", rel],
                             cwd=ROOT, capture_output=True, text=True)
        sha = log.stdout.strip()
        if log.returncode != 0 or not sha:
            raise SystemExit(
                f"refusing to run: {rel} is not committed. An uncommitted "
                f"prereg can be edited after seeing the result.")
        dirty = subprocess.run(["git", "status", "--porcelain", "--", rel],
                               cwd=ROOT, capture_output=True, text=True)
        if dirty.stdout.strip():
            raise SystemExit(
                f"refusing to run: {rel} has uncommitted changes. Commit them "
                f"first, so the version that judged this run is on record.")
        shas[rel] = sha
    return shas


def candidate_rows(world, keep_excluded: bool = True) -> list[dict]:
    """One row per candidate: features, and whether it covers a planted cluster.

    Positivity is `is_hit` -- the same containment-and-Jaccard definition
    AMLworld reports under, inherited unchanged so the two domains remain
    comparable.
    """
    tracker, candidates, seeds = ident.run_identity_funnel(world)
    apps = {a.app_id: a for a in world.applications}
    counts = IF.population_counts(world.applications)
    graph, _ = ident.build_graph(world)
    members, _ = ident.cluster_membership(world)

    rows = []
    for c in candidates:
        nodes = set(c.nodes)
        f = IF.build(nodes, graph, apps, counts)
        hit = any(is_hit(nodes, m) for m in members.values())
        vec = f.to_dict() if keep_excluded else f.vector()
        rows.append({"y": int(hit), **vec})
    return rows


def auc(values: list, labels: list) -> float:
    """Rank AUC with ties credited a half, and no dependency added for it."""
    pairs = sorted(zip(values, labels))
    n_pos = sum(labels)
    n_neg = len(labels) - n_pos
    if not n_pos or not n_neg:
        return 0.5
    rank_sum = 0.0
    i = 0
    rank = 1
    while i < len(pairs):
        j = i
        while j < len(pairs) and pairs[j][0] == pairs[i][0]:
            j += 1
        avg_rank = (rank + (rank + (j - i) - 1)) / 2
        for k in range(i, j):
            if pairs[k][1]:
                rank_sum += avg_rank
        rank += j - i
        i = j
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def attribute_ceilings(worlds: list) -> dict:
    """Legitimate vs fraudulent maximum multiplicity, per attribute.

    The evidence for the pre-registered exclusion rule: an attribute whose
    legitimate maximum is bounded by a structure size in the generator cannot
    be used, because separating on it is the generator's construction rather
    than a fact about onboarding data.
    """
    out = {}
    for a in gen.ATTRS:
        legit_max, fraud_max = 0, 0
        for w in worlds:
            fraud = w.fraudulent
            counts = Counter(getattr(app, a) for app in w.applications)
            for app in w.applications:
                m = counts[getattr(app, a)]
                if app.app_id in fraud:
                    fraud_max = max(fraud_max, m)
                else:
                    legit_max = max(legit_max, m)
        out[a] = {"legit_max_multiplicity": legit_max,
                  "fraud_max_multiplicity": fraud_max,
                  "excluded": f"max_{a}_fanout" in IF.EXCLUDED_FEATURES_IDENTITY}
    return out


def relabelling_is_invariant(world) -> bool:
    """Arm 1. Permute the truth, recompute, demand bit-identical values.

    A feature that moves when only the labels moved is reading the labels. The
    permutation is a real reassignment of applications to clusters, not a
    renaming of cluster ids, so a feature keying on membership would move.
    """
    before = candidate_rows(world)

    rng = random.Random("relabel")
    ids = [i for c in world.clusters for i in c]
    rng.shuffle(ids)
    sizes = [len(c) for c in world.clusters]
    permuted, at = [], 0
    for s in sizes:
        permuted.append(set(ids[at:at + s]))
        at += s
    world.clusters = permuted

    after = candidate_rows(world)
    return [{k: v for k, v in r.items() if k != "y"} for r in before] == \
           [{k: v for k, v in r.items() if k != "y"} for r in after]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worlds", type=int, default=WORLDS)
    args = ap.parse_args()

    shas = require_committed_prereg()
    for rel, sha in shas.items():
        print(f"pre-registration {rel} committed at {sha[:7]}")

    worlds = [gen.generate(seed=s, **gen.PRIMARY) for s in range(args.worlds)]

    # -- arm 1 ---------------------------------------------------------------
    invariant = relabelling_is_invariant(gen.generate(seed=101, **gen.PRIMARY))
    print(f"\narm 1  relabelling invariance: {'PASS' if invariant else 'FAIL'}")

    # -- arm 2 ---------------------------------------------------------------
    rows = []
    per_world = []
    for w in worlds:
        r = candidate_rows(w)
        per_world.append(r)
        rows.extend(r)

    labels = [r["y"] for r in rows]
    names = [k for k in rows[0] if k != "y"]
    aucs = {name: auc([r[name] for r in rows], labels) for name in names}

    tripped = sorted(n for n, a in aucs.items()
                     if a >= LEAK_AUC and n not in IF.EXCLUDED_FEATURES_IDENTITY)
    print(f"arm 2  per-feature AUC over {len(rows)} candidates "
          f"({sum(labels)} positive)")
    for name in sorted(aucs, key=lambda n: -abs(aucs[n] - 0.5)):
        mark = ""
        if name in IF.EXCLUDED_FEATURES_IDENTITY:
            mark = "  [excluded before measuring]"
        elif aucs[name] >= LEAK_AUC:
            mark = "  LEAK"
        print(f"    {name:<34} {aucs[name]:.4f}{mark}")

    ceilings = attribute_ceilings(worlds)
    print("\nattribute multiplicity ceilings (the exclusion evidence)")
    for a, row in ceilings.items():
        print(f"    {a:<9} legit max {row['legit_max_multiplicity']:>4}   "
              f"fraud max {row['fraud_max_multiplicity']:>4}   "
              f"{'excluded' if row['excluded'] else 'kept'}")

    hit_rate = bootstrap_ci(
        [sum(r["y"] for r in w) / len(w) if w else 0.0 for w in per_world],
        lambda xs: sum(xs) / len(xs))

    passed = invariant and len(tripped) == 0
    verdict = {
        "arm1_relabelling_invariant": invariant,
        "arm2_features_tripping_leak_auc": tripped,
        "leak_auc": LEAK_AUC,
        "max_tripping_before_background_is_implicated": MAX_TRIPPING_FEATURES,
        "background_implicated": len(tripped) > MAX_TRIPPING_FEATURES,
        "pass": bool(passed),
    }

    payload = {"prereg": shas, "n_worlds": args.worlds,
               "n_candidates": len(rows), "n_positive": sum(labels),
               "candidate_hit_rate": {**hit_rate,
                                       "ci_method": "world_clustered_bootstrap"},
               "auc": aucs, "attribute_ceilings": ceilings,
               "excluded": sorted(IF.EXCLUDED_FEATURES_IDENTITY),
               "verdict": verdict}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\ngate: {'PASS' if passed else 'FAIL'}")
    if tripped:
        print(f"  {len(tripped)} feature(s) at AUC >= {LEAK_AUC}: {tripped}")
        if len(tripped) > MAX_TRIPPING_FEATURES:
            print("  more than five: the BACKGROUND is implicated, not the "
                  "features. Re-open Phase A's kill rule under its "
                  "one-amendment clause.")
    print(f"written to {OUT.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
