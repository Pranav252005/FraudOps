"""Listwise ranking (LambdaMART) against the pointwise scorers it would replace.

Tier 1 of docs/ARCHITECTURE_UPLIFT.md, items 1.2, 1.3 and 1.5 in one run,
because they share a candidate pool that costs ~25 minutes to collect.

The mismatch being tested. p@k is a *per-cycle* metric: candidates inside one
generation cycle compete for 10/20/50 slots. Both shipped rankers are
pointwise -- the v1 blend produces an absolute score with no reference to the
cycle it sits in, and the learned re-ranker optimises log-loss over the whole
pool. With ~1-3 positives per cycle against thousands of negatives, almost all
of that gradient is spent separating negatives from each other far below the
cut. LambdaMART weights each pairwise swap by the change it causes in the
ranking metric, which concentrates the gradient at the top of each cycle's list
(Burges, MSR-TR-2010-82).

Four models, all on the same features, same pool, same ring-disjoint
time-ordered split:

  pointwise            LGBMClassifier -- the existing oracle, for reference
  lambdamart           LGBMRanker, objective=lambdarank, group = cycle
  lambdamart_intensive LGBMRanker on the SIZE-BLIND feature subset only
  pointwise_intensive  LGBMClassifier on the same subset, to separate "listwise
                       helped" from "dropping extensive features helped"

`lambdamart_intensive` is how the size re-tie is avoided **by construction**
rather than patched afterwards: it never sees n_nodes, n_edges, n_txns, any
count, or any absolute amount, so it cannot rank by size even if size is the
best available signal. FEATURE_KIND partitions every feature explicitly and
`_partition` asserts the partition is total -- a new feature cannot slip into
the size-blind set by defaulting.

Baselines, all evaluated on the same cycles in the same paired frame
(section 1.5's list):

  size   node count
  degree max_fan
  random deterministic per-candidate key
  blend  the shipped v1 hand-set score
  best1  the single strongest feature chosen on TRAIN and applied unchanged on
         test, sign included. This baseline did not exist before and it is the
         one that matters most: a learned ranker that cannot beat one feature
         is an expensive way to compute that feature.

Ship criterion, pre-registered in section 1.5: the paired delta against `size`
must exclude zero at k=10 AND k=20. The plan also pre-registers the expected
outcome -- at n=17 held-out cycles the CI is expected to still include zero.

    python scripts/eval_ranker.py                 # collects the pool (~25 min)
    python scripts/eval_ranker.py --use-cache     # re-trains in seconds
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightgbm import LGBMClassifier, LGBMRanker

from sentinel.config import PRUNE_STRATEGY
from sentinel.data.accounts import AccountRegistry
from sentinel.eval.bootstrap import bootstrap_ci, paired_bootstrap_delta, ratio_of_sums
from sentinel.learn.reranker import feature_names, vectorise
from sentinel.stream.replay import Stream

from scripts.eval_oracle import collect_pool, ring_time_split

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "data" / "ranker_pool.npz"
KS = (10, 20, 50)

# Every feature is classified as intensive (scale-free: a ratio, a density, a
# per-member average) or extensive (grows with the candidate's size: a count, a
# width, an absolute amount, a time extent). The partition is the measurement
# docs/HANDOFF.md 5d's two competing readings of the post-prune re-tie turn on,
# and it is the mechanism by which a size-blind ranker is built rather than
# tested for afterwards.
#
# Judgement calls, recorded rather than hidden:
#   shortest_cycle / shortest_temporal_cycle -- small integers bounded above by
#     candidate size, so they leak a weak size signal. Classified EXTENSIVE, the
#     conservative choice for a subset whose whole purpose is to be size-blind.
#   burstiness -- txns per hour. The numerator grows with candidate size, so
#     extensive despite being a rate.
#   span_minutes -- a time extent, not a node count, but larger candidates span
#     longer. Extensive, same conservative reasoning.
#   median_dormancy_h / mean_velocity / median_passthrough_value /
#     max_amount_skew -- per-member statistics aggregated by median/mean/max,
#     which do not grow with member count. Intensive.
INTENSIVE = frozenset({
    "conservation", "churn", "passthrough_ratio", "cycle_coverage",
    "temporal_cycle_coverage", "round_amount_ratio", "entity_reuse",
    "entity_type_purity", "gargaml", "layer_high_density", "layer_low_density",
    "bipartite_score", "stack_score", "fast_passthrough_ratio",
    "median_passthrough_value", "median_dormancy_h", "max_amount_skew",
    "mean_velocity", "has_cycle", "has_temporal_cycle", "cross_border",
    # GFP vertex statistics, added when the three parity gaps were closed.
    # A mean across members does not grow with member count; a max over members
    # does, weakly, because the maximum of more samples trends upward. So the
    # means are intensive and every max is classified extensive -- the
    # conservative direction for a subset whose entire purpose is size-blindness.
    "mean_out_amount", "mean_in_amount", "mean_amount_std",
    "mean_time_std_h", "mean_time_skew",
})
EXTENSIVE = frozenset({
    "n_nodes", "n_edges", "n_txns", "total_amount", "inflow", "outflow",
    "internal", "scatter_gather_width", "gather_scatter_width",
    "fan_out_count", "fan_in_count", "max_fan", "n_senders", "n_mules",
    "n_receivers", "layer_depth", "n_banks", "n_countries", "n_entities",
    "span_minutes", "burstiness", "shortest_cycle", "shortest_temporal_cycle",
    "scatter_gather_width_6h",
    "min_member_amount", "max_member_amount", "max_amount_kurtosis",
    "max_time_kurtosis",
})


def _partition(names: list[str]) -> list[int]:
    """Indices of the intensive (size-blind) features. Asserts totality."""
    unknown = [n for n in names if n not in INTENSIVE and n not in EXTENSIVE]
    assert not unknown, (
        f"features not classified as intensive or extensive: {unknown}. "
        f"Classify them in scripts/eval_ranker.py -- defaulting a new feature "
        f"into the size-blind set would quietly break the one property that "
        f"subset exists to guarantee.")
    return [i for i, n in enumerate(names) if n in INTENSIVE]


# --------------------------------------------------------------------------
# pool -> flat arrays
# --------------------------------------------------------------------------

def build_arrays(records, names):
    """Vectorise a candidate pool into the flat arrays every model reads.

    Candidate objects are not cached -- they hold the whole feature dataclass
    and a frozenset per row, which is ~2 GB for this pool. Everything
    downstream needs is numeric plus a stable per-candidate random key.
    """
    X = np.array([vectorise(r["cand"].features, names) for r in records],
                 dtype=np.float64)
    y = np.array([1 if r["ring"] is not None else 0 for r in records],
                 dtype=np.int32)
    t = np.array([r["t"] for r in records], dtype=np.int64)
    blend = np.array([r["cand"].score for r in records], dtype=np.float64)
    size = np.array([r["cand"].size for r in records], dtype=np.float64)
    degree = np.array([r["cand"].features.max_fan for r in records],
                      dtype=np.float64)
    rnd = np.array([random.Random(r["cand"].key).random() for r in records],
                   dtype=np.float64)
    return {"X": X, "y": y, "t": t, "blend": blend, "size": size,
            "degree": degree, "rnd": rnd}


def collect(cache: Path):
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(
        ROOT / "data" / "amlworld" / "HI-Small_accounts.csv")
    print("=== collecting candidate pool: AS-IS (real seeding) ===")
    records, first_t = collect_pool(stream, registry, seed_perfect=False)
    train, test, split_t = ring_time_split(records, first_t)
    names = feature_names(records[0]["cand"].features)

    tr = build_arrays(train, names)
    te = build_arrays(test, names)
    np.savez_compressed(
        cache, names=np.array(names), split_t=split_t,
        **{f"train_{k}": v for k, v in tr.items()},
        **{f"test_{k}": v for k, v in te.items()})
    print(f"cached pool to {cache} "
          f"(train {len(tr['y']):,}/{int(tr['y'].sum())} pos, "
          f"test {len(te['y']):,}/{int(te['y'].sum())} pos)")
    return names, tr, te, split_t


def load(cache: Path):
    z = np.load(cache, allow_pickle=False)
    names = [str(n) for n in z["names"]]
    keys = ("X", "y", "t", "blend", "size", "degree", "rnd")
    tr = {k: z[f"train_{k}"] for k in keys}
    te = {k: z[f"test_{k}"] for k in keys}
    return names, tr, te, int(z["split_t"])


# --------------------------------------------------------------------------
# models
# --------------------------------------------------------------------------

def _groups(t: np.ndarray):
    """Order rows by cycle and return (order, group_sizes).

    LGBMRanker requires rows grouped contiguously by query. The query here is
    the generation cycle, which is the unit p@k is computed over and the unit
    the bootstrap resamples -- the same object in all three places, deliberately.
    """
    order = np.argsort(t, kind="stable")
    ts = t[order]
    sizes = []
    i = 0
    while i < len(ts):
        j = i
        while j < len(ts) and ts[j] == ts[i]:
            j += 1
        sizes.append(j - i)
        i = j
    return order, np.array(sizes)


def fit_pointwise(Xtr, ytr, seed=7):
    m = LGBMClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                       class_weight="balanced", random_state=seed, verbosity=-1)
    m.fit(Xtr, ytr)
    return lambda X: m.predict_proba(X)[:, 1], m


def fit_lambdamart(Xtr, ytr, ttr, seed=7):
    order, sizes = _groups(ttr)
    m = LGBMRanker(
        objective="lambdarank", n_estimators=300, max_depth=6,
        learning_rate=0.05, random_state=seed, verbosity=-1,
        # The metric is precision at a fixed alert budget, so the truncation
        # level is set at the depths actually reported rather than left at
        # LightGBM's default of the whole list.
        label_gain=[0, 1], eval_at=list(KS), lambdarank_truncation_level=50,
    )
    m.fit(Xtr[order], ytr[order], group=sizes)
    return lambda X: m.predict(X), m


# --------------------------------------------------------------------------
# evaluation
# --------------------------------------------------------------------------

def cycle_rows(te, ranking_scores: dict) -> list[dict]:
    """One row per held-out cycle with (hits, n) at each k for every ranking."""
    by_t: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(te["t"]):
        by_t[int(t)].append(i)

    rows = []
    for t in sorted(by_t):
        idx = by_t[t]
        row = {"t": t, "n_cands": len(idx),
               "n_positive": int(sum(te["y"][i] for i in idx))}
        for name, s in ranking_scores.items():
            # Ties broken on the candidate's own deterministic random key, so
            # no ranking gets a free ride from input order -- `size` in
            # particular has huge tie groups.
            ordered = sorted(idx, key=lambda i: (-s[i], te["rnd"][i]))
            for k in KS:
                top = ordered[:k]
                row[f"{name}_hit_{k}"] = int(sum(te["y"][i] for i in top))
                row[f"{name}_n_{k}"] = len(top)
        rows.append(row)
    return rows


def best_single_feature(names, tr, k=20):
    """Strongest single feature on TRAIN, sign included, applied on test.

    Chosen by train p@k with the same per-cycle grouping the metric uses, not by
    correlation, so the baseline is selected on the quantity it is compared on.
    """
    by_t: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(tr["t"]):
        by_t[int(t)].append(i)

    best = (None, 1.0, -1.0)   # (name, sign, p@k)
    for j, name in enumerate(names):
        col = tr["X"][:, j]
        for sign in (1.0, -1.0):
            hit = tot = 0
            for idx in by_t.values():
                ordered = sorted(idx, key=lambda i: (-sign * col[i], tr["rnd"][i]))
                top = ordered[:k]
                hit += int(sum(tr["y"][i] for i in top))
                tot += len(top)
            p = hit / tot if tot else 0.0
            if p > best[2]:
                best = (name, sign, p)
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--use-cache", action="store_true")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "data" / "eval_ranker.json")
    args = ap.parse_args()

    t0 = time.time()
    if args.use_cache and CACHE.exists():
        names, tr, te, split_t = load(CACHE)
        print(f"loaded cached pool from {CACHE}")
    else:
        names, tr, te, split_t = collect(CACHE)

    intensive_idx = _partition(names)
    print(f"\n{len(names)} features: {len(intensive_idx)} intensive "
          f"(size-blind), {len(names) - len(intensive_idx)} extensive")
    print(f"train {len(tr['y']):,} rows / {int(tr['y'].sum())} positive")
    print(f"test  {len(te['y']):,} rows / {int(te['y'].sum())} positive")

    Xi_tr, Xi_te = tr["X"][:, intensive_idx], te["X"][:, intensive_idx]

    print("\ntraining...")
    scores: dict[str, np.ndarray] = {}
    predict, _ = fit_pointwise(tr["X"], tr["y"])
    scores["pointwise"] = predict(te["X"])
    predict, _ = fit_lambdamart(tr["X"], tr["y"], tr["t"])
    scores["lambdamart"] = predict(te["X"])
    predict, _ = fit_pointwise(Xi_tr, tr["y"])
    scores["pointwise_intensive"] = predict(Xi_te)
    predict, _ = fit_lambdamart(Xi_tr, tr["y"], tr["t"])
    scores["lambdamart_intensive"] = predict(Xi_te)

    # baselines
    scores["blend"] = te["blend"]
    scores["size"] = te["size"]
    scores["degree"] = te["degree"]
    scores["random"] = te["rnd"]

    b_name, b_sign, b_train_p = best_single_feature(names, tr)
    print(f"best single feature on train: {b_name} "
          f"(sign {b_sign:+.0f}, train p@20 {b_train_p:.4f})")
    scores["best1"] = b_sign * te["X"][:, names.index(b_name)]

    rows = cycle_rows(te, scores)
    print(f"\n{len(rows)} held-out cycles, "
          f"{sum(r['n_positive'] for r in rows)} positives")

    models = ("pointwise", "lambdamart", "pointwise_intensive",
              "lambdamart_intensive")
    baselines = ("blend", "size", "degree", "random", "best1")

    point: dict = {}
    ci: dict = {}
    for k in KS:
        point[k] = {}
        for name in scores:
            stat = ratio_of_sums(f"{name}_hit_{k}", f"{name}_n_{k}")
            point[k][name] = stat(rows)
            ci[f"{name}@{k}"] = bootstrap_ci(rows, stat)

    print(f"\n{'ranking':<22}" + "".join(f"{'p@' + str(k):>12}" for k in KS))
    for name in list(models) + list(baselines):
        print(f"{name:<22}" + "".join(f"{point[k][name]:>12.4f}" for k in KS))

    # Paired deltas: every model against every baseline, on the same cycles.
    paired: dict = {}
    print("\npaired bootstrap deltas (model - baseline), 95% CI over cycles:")
    for k in KS:
        for m in models:
            m_stat = ratio_of_sums(f"{m}_hit_{k}", f"{m}_n_{k}")
            for base in baselines:
                b_stat = ratio_of_sums(f"{base}_hit_{k}", f"{base}_n_{k}")
                d = paired_bootstrap_delta(rows, b_stat, m_stat)
                paired[f"{m}-{base}@{k}"] = d
                if base in ("size", "blend", "best1"):
                    flag = "REAL" if d["excludes_zero"] else "includes zero"
                    print(f"  k={k:<3} {m:<22} vs {base:<7} "
                          f"{d['point']:+.4f} [{d['lo']:+.4f}, {d['hi']:+.4f}]"
                          f"  {flag}")

    # The standing re-tie check, run alongside every ranking change.
    print("\nbaseline re-tie check (does anything beat node count?):")
    ship = {}
    for k in KS:
        for name in list(models) + ["blend", "best1"]:
            d = paired[f"{name}-size@{k}"] if name in models else None
            if d is None:
                m_stat = ratio_of_sums(f"{name}_hit_{k}", f"{name}_n_{k}")
                s_stat = ratio_of_sums(f"size_hit_{k}", f"size_n_{k}")
                d = paired_bootstrap_delta(rows, s_stat, m_stat)
                paired[f"{name}-size@{k}"] = d
            ship[f"{name}@{k}"] = bool(d["excludes_zero"] and d["point"] > 0)

    for name in list(models) + ["blend", "best1"]:
        verdict = ("SHIPPABLE" if ship.get(f"{name}@10") and ship.get(f"{name}@20")
                   else "not a gain (CI includes zero at k=10 or k=20)")
        print(f"  {name:<22} {verdict}")

    out = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "prune_strategy": PRUNE_STRATEGY,
        "split_t": split_t,
        "n_features": len(names),
        "n_intensive": len(intensive_idx),
        "intensive_features": [names[i] for i in intensive_idx],
        "n_train": int(len(tr["y"])), "n_train_positive": int(tr["y"].sum()),
        "n_test": int(len(te["y"])), "n_test_positive": int(te["y"].sum()),
        "n_cycles": len(rows),
        "best_single_feature": {"name": b_name, "sign": b_sign,
                                 "train_p_at_20": b_train_p},
        "precision_at": {str(k): point[k] for k in KS},
        "precision_ci": ci,
        "paired": paired,
        "ship_criterion": (
            "paired delta vs `size` must exclude zero at BOTH k=10 and k=20 "
            "(docs/ARCHITECTURE_UPLIFT.md 1.5). A gain whose interval includes "
            "zero is not a gain."),
        "ship": ship,
        "cycle_rows": rows,
        "seconds": time.time() - t0,
    }
    args.out.write_text(json.dumps(out, indent=2, default=float))
    print(f"\nwritten to {args.out}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
