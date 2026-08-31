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

Four models, all on the same features, same pool, same ring-disjoint split
(time-ordered on the negative pool only -- positives follow their ring; see
ring_time_split in scripts/eval_oracle.py for why that trade is taken):

  pointwise            LGBMClassifier -- an independent re-fit of the same
                       supervised re-ranker scripts/eval_oracle.py run 1
                       reports, on this pool and the same ring-disjoint split.
                       Keyed "pointwise" here and "oracle" there; both are
                       trained on TRUE ring labels, which a deployment does not
                       have. It is a reference arm for the listwise comparison
                       AND the second reading of that result: the two scripts
                       agree to every digit, on the point estimate, both CI
                       bounds and the paired deltas, at every k. The digits
                       themselves are deliberately not written here -- they
                       have moved twice (0.2778 -> 0.2500 -> 0.2111) while the
                       agreement held throughout, so quoting them would decay
                       a true sentence into a false one. The agreement is the
                       claim, and it is checked live against both files rather
                       than against a literal.
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
    # Ring identity, -1 for a negative. Needed because p@k over CANDIDATES and
    # p@k over distinct RINGS are different quantities and only the second one
    # is worth an analyst's time: three candidates for the same ring filling
    # three of the top ten slots is one investigation, not three.
    ring = np.array([-1 if r["ring"] is None else int(r["ring"])
                     for r in records], dtype=np.int64)
    return {"X": X, "y": y, "t": t, "blend": blend, "size": size,
            "degree": degree, "rnd": rnd, "ring": ring}


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
    # `ring` was added after the first cached pool was built. A cache without
    # it still works for everything except the distinct-ring metric, which is
    # skipped rather than silently faked.
    for split, d in (("train", tr), ("test", te)):
        if f"{split}_ring" in z.files:
            d["ring"] = z[f"{split}_ring"]
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


# LightGBM's lambdarank objective hard-fails on any query group with more than
# this many rows. It is a compile-time constant in `rank_objective.hpp`, not a
# tunable parameter, so there is no way to raise it from Python. This pool's
# generation cycles reach 24,533 candidates, which is why the first run of this
# script died with "Number of rows 15496 exceeds upper limit of 10000 for a
# query" rather than producing a result.
LGBM_MAX_QUERY_ROWS = 10_000


def _cap_query_rows(order, sizes, y, cap, seed):
    """Subsample negatives inside oversized query groups. TRAIN ONLY.

    Every positive is kept and only negatives are dropped, and only from groups
    that actually exceed `cap`. The test arrays are never passed through here,
    so nothing about the evaluation, the bootstrap, or the reported p@k changes
    -- this is a constraint of the trainer, not of the metric.

    The choice of `cap` is reported and swept (see `--cap-sweep`) rather than
    asserted to be harmless, because "we dropped 60% of the negatives in the
    six biggest training lists" is exactly the kind of decision that should not
    be load-bearing without evidence.
    """
    rng = np.random.default_rng(seed)
    keep, kept_sizes = [], []
    n_capped = n_dropped = 0
    i = 0
    for n in sizes:
        grp = order[i:i + n]
        i += n
        if n <= cap:
            keep.append(grp)
            kept_sizes.append(int(n))
            continue
        pos = grp[y[grp] > 0]
        neg = grp[y[grp] == 0]
        room = max(cap - len(pos), 0)
        if len(neg) > room:
            neg = rng.choice(neg, size=room, replace=False)
        sel = np.sort(np.concatenate([pos, neg]))
        keep.append(sel)
        kept_sizes.append(int(len(sel)))
        n_capped += 1
        n_dropped += int(n - len(sel))
    return np.concatenate(keep), np.array(kept_sizes), n_capped, n_dropped


def group_diagnostics(t, y):
    """What the listwise objective actually receives, per query group.

    Exists because of a confound found while fixing the row cap, not because
    it was planned. `ring_time_split` assigns POSITIVES by ring identity and
    NEGATIVES by timestamp. A ring whose first appearance lands before the cut
    keeps all of its candidates in train even when some occur after it -- so
    every cycle after `split_t` contributes an all-positive remnant group to
    train, with no negatives at all.

    A lambdarank group whose labels are all identical generates no discordant
    pairs and therefore contributes exactly zero gradient. Those positives are
    invisible to LambdaMART while remaining fully visible to the pointwise
    classifier, which has no notion of groups. So "same pool, same features,
    same split" is true of the arrays and false of what the two objectives
    learn from, and the listwise-vs-pointwise comparison is confounded by
    training signal unless it is stated.
    """
    by_t: dict[int, list[int]] = defaultdict(list)
    for i, tv in enumerate(t):
        by_t[int(tv)].append(i)
    informative_pos = informative_groups = 0
    dead_pos = dead_groups = 0
    all_positive_groups = all_negative_groups = 0
    for idx in by_t.values():
        p = int(sum(y[i] for i in idx))
        if p == 0 or p == len(idx):          # one label only -> no pairs
            dead_groups += 1
            dead_pos += p
            if p == 0:
                all_negative_groups += 1
            else:
                all_positive_groups += 1
        else:
            informative_groups += 1
            informative_pos += p
    return {
        "n_groups": len(by_t),
        "pairwise_informative_groups": informative_groups,
        "pairwise_informative_positives": informative_pos,
        "single_label_groups": dead_groups,
        "positives_in_single_label_groups": dead_pos,
        # Split out because the two are not the same defect. An all-negative
        # group wastes nothing and occurs naturally; an all-positive group
        # strands positives that the pointwise model can still see, which is
        # what confounded the listwise-vs-pointwise head-to-head.
        "all_positive_groups": all_positive_groups,
        "all_negative_groups": all_negative_groups,
        "largest_group": max(len(v) for v in by_t.values()),
    }


def fit_pointwise(Xtr, ytr, seed=7):
    m = LGBMClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                       class_weight="balanced", random_state=seed, verbosity=-1)
    m.fit(Xtr, ytr)
    return lambda X: m.predict_proba(X)[:, 1], m


def fit_lambdamart(Xtr, ytr, ttr, seed=7, cap=LGBM_MAX_QUERY_ROWS,
                   report=None):
    order, sizes = _groups(ttr)
    order, sizes, n_capped, n_dropped = _cap_query_rows(
        order, sizes, ytr, cap, seed)
    if report is not None:
        report.update(cap=int(cap), groups_capped=n_capped,
                      negatives_dropped=n_dropped, rows_trained=int(len(order)),
                      positives_trained=int(ytr[order].sum()))
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


def ring_cycle_rows(te, ranking_scores: dict) -> list[dict] | None:
    """Per-cycle DISTINCT-RING hits at each k, the analyst-facing denominator.

    `cycle_rows` counts positive candidates in the top k. If the generator
    emits several surviving candidates for one ring, that metric pays for the
    same ring more than once while an analyst working the queue would open one
    case and be done. This counts each ring at most once per cut, so the gap
    between the two numbers is the duplication the candidate-level figure is
    absorbing. Returns None when the cached pool predates ring capture.
    """
    if "ring" not in te:
        return None
    by_t: dict[int, list[int]] = defaultdict(list)
    for i, t in enumerate(te["t"]):
        by_t[int(t)].append(i)

    rows = []
    for t in sorted(by_t):
        idx = by_t[t]
        row = {"t": t,
               "n_distinct_rings": len({int(te["ring"][i]) for i in idx
                                        if te["ring"][i] >= 0})}
        for name, s in ranking_scores.items():
            ordered = sorted(idx, key=lambda i: (-s[i], te["rnd"][i]))
            for k in KS:
                top = ordered[:k]
                row[f"{name}_hit_{k}"] = len({int(te["ring"][i]) for i in top
                                              if te["ring"][i] >= 0})
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
    ap.add_argument("--cap", type=int, default=LGBM_MAX_QUERY_ROWS,
                    help="max rows per training query group (LightGBM's own "
                         "ceiling is 10000 and cannot be raised)")
    ap.add_argument("--cap-sweep", action="store_true",
                    help="also train LambdaMART at 2000/5000/10000 to show the "
                         "cap is not load-bearing")
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

    # Printed before any model is fitted, because it changes how the headline
    # table should be read. See group_diagnostics.__doc__.
    diag = group_diagnostics(tr["t"], tr["y"])
    print(f"\ntrain query groups: {diag['n_groups']} total, "
          f"{diag['pairwise_informative_groups']} carry pairwise signal "
          f"(mixed labels), {diag['single_label_groups']} do not.")
    print(f"  positives LambdaMART can actually learn from: "
          f"{diag['pairwise_informative_positives']} of "
          f"{int(tr['y'].sum())}.")

    # THE GUARD ON THE FIX, placed where it can actually fail: on the real
    # pool, before anything is fitted. `ring_time_split` bounds train by the
    # cutoff so that no cycle contributes positives without its negatives; if
    # an all-positive group survives that, the rule has regressed and the
    # head-to-head below is confounded again -- silently, because a confounded
    # comparison still produces a number. See docs/negative-results/
    # dead-query-groups.md for the 18-of-34 state this replaced.
    assert diag["all_positive_groups"] == 0, (
        f"{diag['all_positive_groups']} of {diag['n_groups']} training query "
        f"groups are all-positive, stranding "
        f"{diag['positives_in_single_label_groups']} positives that the "
        f"pointwise model still sees. The listwise-vs-pointwise comparison is "
        f"confounded in the pointwise model's favour. This is the defect "
        f"ring_time_split's cutoff exists to close.")
    print(f"  all-positive groups: 0 (asserted). The two objectives receive "
          f"the same signal, so the head-to-head below is not confounded by "
          f"training-set differences -- which it was, in every run before "
          f"2026-08-31.")
    if diag["all_negative_groups"]:
        print(f"  all-negative groups: {diag['all_negative_groups']} -- these "
              f"generate no pairs either, but strand no positives and arise "
              f"naturally from cycles in which nothing hit a ring.")
    print(f"  largest group {diag['largest_group']:,} rows vs LightGBM's "
          f"{LGBM_MAX_QUERY_ROWS:,}-row ceiling; oversized groups are "
          f"negative-subsampled at cap={args.cap:,}.")

    Xi_tr, Xi_te = tr["X"][:, intensive_idx], te["X"][:, intensive_idx]

    print("\ntraining...")
    scores: dict[str, np.ndarray] = {}
    predict, _ = fit_pointwise(tr["X"], tr["y"])
    scores["pointwise"] = predict(te["X"])
    cap_report: dict = {}
    predict, _ = fit_lambdamart(tr["X"], tr["y"], tr["t"], cap=args.cap,
                                report=cap_report)
    scores["lambdamart"] = predict(te["X"])
    predict, _ = fit_pointwise(Xi_tr, tr["y"])
    scores["pointwise_intensive"] = predict(Xi_te)
    predict, _ = fit_lambdamart(Xi_tr, tr["y"], tr["t"], cap=args.cap)
    scores["lambdamart_intensive"] = predict(Xi_te)
    print(f"  cap={cap_report['cap']:,}: {cap_report['groups_capped']} groups "
          f"subsampled, {cap_report['negatives_dropped']:,} negatives dropped, "
          f"{cap_report['rows_trained']:,} rows trained "
          f"({cap_report['positives_trained']} positive -- every positive kept)")

    sweep: dict = {}
    if args.cap_sweep:
        for c in (2000, 5000, LGBM_MAX_QUERY_ROWS):
            rep: dict = {}
            pr, _ = fit_lambdamart(tr["X"], tr["y"], tr["t"], cap=c, report=rep)
            scores[f"lambdamart_cap{c}"] = pr(te["X"])
            sweep[str(c)] = rep

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

    if sweep:
        print(f"\ncap sensitivity (LambdaMART, all features, same test cycles):")
        for c in sorted(sweep, key=int):
            nm = f"lambdamart_cap{c}"
            print(f"  cap={int(c):<6,} dropped "
                  f"{sweep[c]['negatives_dropped']:>7,} neg"
                  + "".join(f"{point[k][nm]:>12.4f}" for k in KS))

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

    # The comparison item 1.3 actually turns on. `size` and `blend` are the
    # standing baselines, but neither is what LambdaMART would replace -- the
    # proposal is to swap out the POINTWISE model, so that is the contrast
    # that decides it. It was absent from the first version of this script,
    # which reported six flattering comparisons and not the deciding one.
    print(f"\nhead-to-head: listwise vs the pointwise model it would replace")
    h2h: dict = {}
    for k in KS:
        for m, base in (("lambdamart", "pointwise"),
                        ("lambdamart_intensive", "pointwise_intensive")):
            m_stat = ratio_of_sums(f"{m}_hit_{k}", f"{m}_n_{k}")
            b_stat = ratio_of_sums(f"{base}_hit_{k}", f"{base}_n_{k}")
            d = paired_bootstrap_delta(rows, b_stat, m_stat)
            h2h[f"{m}-{base}@{k}"] = d
            flag = "REAL" if d["excludes_zero"] else "includes zero"
            print(f"  k={k:<3} {m:<22} vs {base:<20} "
                  f"{d['point']:+.4f} [{d['lo']:+.4f}, {d['hi']:+.4f}]  {flag}")

    # Distinct-ring precision, the same rankings on the analyst's denominator.
    ring_rows = ring_cycle_rows(te, scores)
    ring_point: dict = {}
    ring_ci: dict = {}
    if ring_rows is None:
        print(f"\ndistinct-ring p@k: SKIPPED (cached pool predates ring "
              f"capture; delete the cache and re-collect to get it)")
    else:
        print(f"\ndistinct-ring p@k -- each ring counted once per cut:")
        print(f"{'ranking':<22}" + "".join(f"{'p@' + str(k):>12}" for k in KS))
        for k in KS:
            ring_point[k] = {}
            for name in scores:
                stat = ratio_of_sums(f"{name}_hit_{k}", f"{name}_n_{k}")
                ring_point[k][name] = stat(ring_rows)
                ring_ci[f"{name}@{k}"] = bootstrap_ci(ring_rows, stat)
        for name in list(models) + list(baselines):
            print(f"{name:<22}"
                  + "".join(f"{ring_point[k][name]:>12.4f}" for k in KS))
        print("  candidate-level minus ring-level = duplicate candidates for "
              "one ring:")
        for name in list(models) + list(baselines):
            gaps = "".join(f"{point[k][name] - ring_point[k][name]:>12.4f}"
                           for k in KS)
            print(f"  {name:<20}{gaps}")

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
        "train_group_diagnostics": diag,
        "query_row_cap": cap_report,
        "cap_sweep": sweep,
        "best_single_feature": {"name": b_name, "sign": b_sign,
                                 "train_p_at_20": b_train_p},
        "precision_at": {str(k): point[k] for k in KS},
        "precision_ci": ci,
        "paired": paired,
        "head_to_head_vs_pointwise": h2h,
        "distinct_ring_precision_at": ({str(k): ring_point[k] for k in KS}
                                       if ring_rows is not None else None),
        "distinct_ring_precision_ci": ring_ci or None,
        "distinct_ring_cycle_rows": ring_rows,
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
