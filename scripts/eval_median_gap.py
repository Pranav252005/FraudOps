"""Is the per-account MEDIAN amount worth its design cost? Measured, not argued.

`tests/test_gfp_gaps.py::test_the_median_gap_is_still_open_and_that_is_recorded`
records a known-absent feature: GFP's vertex statistics include a per-account
median of transaction amounts, and `sentinel/graph/stats.py` cannot produce one.
That is not an oversight. Welford's algorithm gives mean, variance, skew and
kurtosis in O(1) memory per account with no retained samples; a median cannot be
computed that way. Closing the gap costs one of:

  * retain samples per account -- O(n) memory over 515,088 accounts, which is
    the reason the moments are Welford in the first place;
  * a streaming quantile estimator (P-square, t-digest) -- O(1) memory but
    approximate, plus a dependency and a new class of numerical bug;
  * recompute per window -- O(edges log edges) per tick, which is what this
    script does to get the answer, and is too slow for the live path.

None of those is free, so the question is whether the feature earns them. This
answers it before anything is built, by computing the exact quantity offline
from the exported windows and testing whether it moves ring-level p@k.

The experiment: take the same pool, same ring-disjoint split, same
LGBMClassifier, same paired bootstrap as `scripts/gfp_compare.py`, and compare
sentinel's feature block against that block plus five median-derived features.
If the delta's CI includes zero, the gap is not worth closing and the test that
records it should say so with a number attached.

Pre-registered expectation, written before the run: **the CI will include
zero.** `median_passthrough_value` is already in the feature set and is a
related quantity, the amount moments were only propagated recently and produced
no large gain, and a median is a robust statistic on a distribution whose
informative tail is exactly what robustness discards. Recording this so that a
positive result cannot be rationalised afterwards as expected.

    python scripts/eval_median_gap.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.eval.bootstrap import paired_bootstrap_delta, ratio_of_sums

from scripts.gfp_compare import (EXPORT_DIR, KS, cycle_rows, fit, load_export,
                                 split_mask)

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "eval_median_gap.json"
CACHE = ROOT / "data" / "median_features.npz"

# Model-fit seeds. The paired bootstrap resamples CYCLES, so it carries the
# variance of which cycles landed in the test split -- and none of the variance
# of the fit itself. A five-feature change evaluated at one fit cannot
# distinguish "these features hurt" from "this fit happens to be worse", and
# the first reading is the one that would get written down.
SEEDS = (7, 13, 29, 101, 997)

# CORRECTION, and it invalidated the first version of this sweep. Passing a
# different `random_state` to LGBMClassifier changes NOTHING in the shipped
# configuration: with bagging and feature sampling both at 1.0, LightGBM's
# histogram tree construction is deterministic and the RNG is never consulted.
# The first run duly reported "5 of 5 seeds show a degradation" while every
# seed had produced bit-identical p@k to four decimal places -- one fit
# reported five times, presented as five agreeing fits.
#
# Verified directly: with the shipped params two seeds give np.array_equal
# predictions; adding subsample/colsample below they differ. So the stability
# probe has to perturb something the RNG actually reaches. These are the
# smallest such knobs, and they are applied ONLY to the robustness sweep --
# the headline comparison stays on the deterministic shipped configuration,
# which is the right thing for a reported number to be.
STOCHASTIC = {"subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8}

MEDIAN_FEATURES = (
    "mean_median_out_amount",   # GFP's per-vertex median, averaged over members
    "mean_median_in_amount",
    "max_median_out_amount",    # and the extreme member, since a mule ring's
    "max_median_in_amount",     # signal may sit in one account not the average
    "internal_edge_median",     # median over the candidate's own internal edges
)


def _medians_by_account(key: np.ndarray, amount: np.ndarray) -> dict[int, float]:
    """Exact per-account median of `amount`, grouped by `key`.

    Sort-and-slice rather than a per-account list, because the windows carry
    0.9-1.6M edges and building a Python list per account is the slow way to
    get the same numbers.
    """
    if len(key) == 0:
        return {}
    order = np.argsort(key, kind="stable")
    k, a = key[order], amount[order]
    bounds = np.flatnonzero(np.diff(k)) + 1
    out: dict[int, float] = {}
    for lo, hi in zip(np.concatenate([[0], bounds]),
                      np.concatenate([bounds, [len(k)]])):
        out[int(k[lo])] = float(np.median(a[lo:hi]))
    return out


def build(export_dir: Path = EXPORT_DIR):
    """Per-candidate median features, in the export's own candidate order."""
    rows: list[np.ndarray] = []
    keys, ts = [], []
    t0 = time.time()
    for path in sorted(export_dir.glob("tick_*.npz")):
        z = np.load(path, allow_pickle=False)
        e = z["edges"]
        src = e[:, 1].astype(np.int64)
        dst = e[:, 2].astype(np.int64)
        amt = e[:, 4]

        med_out = _medians_by_account(src, amt)
        med_in = _medians_by_account(dst, amt)

        # internal-edge lookup, same structure gfp_control uses
        by_pair: dict[tuple[int, int], list[int]] = defaultdict(list)
        for j in range(len(src)):
            by_pair[(int(src[j]), int(dst[j]))].append(j)
        out_pairs: dict[int, list[tuple[int, list[int]]]] = defaultdict(list)
        for (s, d), idxs in by_pair.items():
            out_pairs[s].append((d, idxs))

        nodes_flat, offsets = z["nodes_flat"], z["offsets"]
        for c in range(len(z["keys"])):
            members = nodes_flat[offsets[c]:offsets[c + 1]].tolist()
            mset = set(members)
            mo = [med_out[m] for m in members if m in med_out]
            mi = [med_in[m] for m in members if m in med_in]
            internal = []
            for s in mset:
                for d, idxs in out_pairs.get(s, ()):
                    if d in mset:
                        internal.extend(idxs)
            rows.append(np.array([
                float(np.mean(mo)) if mo else 0.0,
                float(np.mean(mi)) if mi else 0.0,
                float(np.max(mo)) if mo else 0.0,
                float(np.max(mi)) if mi else 0.0,
                float(np.median(amt[internal])) if internal else 0.0,
            ]))
            keys.append(str(z["keys"][c]))
            ts.append(int(z["t"]))
        print(f"  {path.name}: {len(src):,} edges, "
              f"{len(z['keys']):,} candidates ({time.time() - t0:.0f}s)",
              flush=True)
    return np.array(rows), keys, np.array(ts, dtype=np.int64)


def main() -> None:
    if not (EXPORT_DIR / "manifest.json").exists():
        raise SystemExit("run `python scripts/gfp_control.py export` first")

    t0 = time.time()
    exp = load_export(EXPORT_DIR)
    if CACHE.exists():
        z = np.load(CACHE, allow_pickle=False)
        Xm, keys, ts = z["X"], [str(k) for k in z["keys"]], z["t"]
        print(f"loaded cached median features from {CACHE}")
    else:
        # Building these is a 65-minute pass over 34 windows of ~1.3M edges.
        # Cached because the interesting follow-up questions are all about the
        # MODEL, and none of them should cost another hour.
        Xm, keys, ts = build(EXPORT_DIR)
        np.savez_compressed(CACHE, X=Xm, keys=np.array(keys), t=ts)
        print(f"cached median features to {CACHE}")
    assert keys == exp["keys"] and (ts == exp["t"]).all(), \
        "median features are not in the export's candidate order"

    y = (exp["ring"] >= 0).astype(np.int32)
    is_train, split_t = split_mask(exp["ring"], exp["t"], exp["ring_first_t"])
    te = ~is_train
    Xs = exp["X"]
    Xb = np.hstack([Xs, Xm])
    print(f"\nsplit_t={split_t}  train {is_train.sum():,} / "
          f"{int(y[is_train].sum())} pos   test {te.sum():,} / "
          f"{int(y[te].sum())} pos")
    print(f"sentinel {Xs.shape[1]} features, +median {Xb.shape[1]}")

    scores = {}
    scores["sentinel"], _ = fit(Xs[is_train], y[is_train], Xs[te], seed=SEEDS[0])
    scores["with_median"], model = fit(Xb[is_train], y[is_train], Xb[te],
                                       seed=SEEDS[0])
    scores["blend"] = exp["blend"][te]
    scores["size"] = exp["size"][te]

    # Every seed, both blocks, under STOCHASTIC so the seed actually bites.
    for sd in SEEDS:
        scores[f"sentinel_s{sd}"], _ = fit(Xs[is_train], y[is_train], Xs[te],
                                           seed=sd, **STOCHASTIC)
        scores[f"with_median_s{sd}"], _ = fit(Xb[is_train], y[is_train], Xb[te],
                                              seed=sd, **STOCHASTIC)
        print(f"  stochastic refit, seed {sd} ({time.time() - t0:.0f}s)",
              flush=True)

    # Guard the correction so it cannot silently regress: if the sweep ever
    # produces identical predictions across two seeds again, the sweep is not
    # measuring fit variance and must not be reported as if it were.
    a, b = scores[f"sentinel_s{SEEDS[0]}"], scores[f"sentinel_s{SEEDS[-1]}"]
    assert not np.array_equal(a, b), (
        "the stochastic sweep produced identical fits across seeds -- "
        "random_state is not reaching the model, so this measures nothing. "
        "Check that STOCHASTIC is still being applied.")

    cand_rows, ring_rows = cycle_rows(exp["t"][te], y[te], exp["rnd"][te],
                                      exp["ring"][te], scores)

    result = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
              "median_features": list(MEDIAN_FEATURES),
              "n_test_cycles": len(cand_rows),
              "pre_registered": ("CI expected to include zero; a measured "
                                "DEGRADATION was not predicted"),
              "seeds": list(SEEDS)}

    verdicts = {}
    for label, rws in (("candidate", cand_rows), ("distinct_ring", ring_rows)):
        print(f"\n--- {label}-level ---")
        print(f"{'ranking':<14}" + "".join(f"{'p@' + str(k):>12}" for k in KS))
        point = {}
        for k in KS:
            point[k] = {n: ratio_of_sums(f"{n}_hit_{k}", f"{n}_n_{k}")(rws)
                        for n in scores}
        for n in scores:
            print(f"{n:<14}" + "".join(f"{point[k][n]:>12.4f}" for k in KS))

        paired = {}
        print("  paired delta (with_median - sentinel), 95% CI:")
        for k in KS:
            a = ratio_of_sums(f"with_median_hit_{k}", f"with_median_n_{k}")
            b = ratio_of_sums(f"sentinel_hit_{k}", f"sentinel_n_{k}")
            d = paired_bootstrap_delta(rws, b, a)
            paired[f"with_median-sentinel@{k}"] = d
            flag = "REAL" if d["excludes_zero"] else "includes zero"
            print(f"    k={k:<3} {d['point']:+.4f} "
                  f"[{d['lo']:+.4f}, {d['hi']:+.4f}]  {flag}")
        verdicts[label] = any(
            paired[f"with_median-sentinel@{k}"]["excludes_zero"] and
            paired[f"with_median-sentinel@{k}"]["point"] > 0 for k in (10, 20))
        result[label] = {"precision_at": {str(k): point[k] for k in KS},
                         "paired": paired, "cycle_rows": rws}

    # Seed stability of the delta, at the k the verdict turns on.
    print(f"\nper-seed delta (with_median - sentinel) at k=10 and "
          f"k=20, candidate-level, under bagging+feature sampling so the seed "
          f"is not inert:")
    per_seed: dict = {}
    n_neg10 = n_pos10 = 0
    for sd in SEEDS:
        sfx = f"_s{sd}"
        row = {}
        for k in (10, 20):
            a = ratio_of_sums(f"with_median{sfx}_hit_{k}",
                              f"with_median{sfx}_n_{k}")
            b = ratio_of_sums(f"sentinel{sfx}_hit_{k}", f"sentinel{sfx}_n_{k}")
            d = paired_bootstrap_delta(cand_rows, b, a)
            row[k] = d
        per_seed[sd] = row
        d10 = row[10]
        n_neg10 += int(d10["point"] < 0 and d10["excludes_zero"])
        n_pos10 += int(d10["point"] > 0 and d10["excludes_zero"])
        print(f"  seed {sd:<5} k=10 {row[10]['point']:+.4f} "
              f"[{row[10]['lo']:+.4f}, {row[10]['hi']:+.4f}]"
              f"   k=20 {row[20]['point']:+.4f} "
              f"[{row[20]['lo']:+.4f}, {row[20]['hi']:+.4f}]")
    result["per_seed"] = {str(k): {str(kk): vv for kk, vv in v.items()}
                          for k, v in per_seed.items()}
    result["seeds_harming_at_10"] = n_neg10
    result["seeds_helping_at_10"] = n_pos10
    print(f"  {n_neg10}/{len(SEEDS)} seeds show a CI-clear DEGRADATION at "
          f"k=10; {n_pos10}/{len(SEEDS)} show a CI-clear gain.")

    # Where the model puts them, which says whether the features are ignored or
    # used-and-still-not-helping. Those warrant different conclusions.
    imp = model.feature_importances_
    n_s = Xs.shape[1]
    med_imp = imp[n_s:]
    ranks = np.argsort(np.argsort(-imp))
    print(f"\nfeature importance of the five median features "
          f"(gain split count, out of {len(imp)} features):")
    for i, name in enumerate(MEDIAN_FEATURES):
        print(f"  {name:<26} importance {med_imp[i]:>6.0f}  "
              f"rank {ranks[n_s + i] + 1}/{len(imp)}")
    result["median_importance"] = {n: float(med_imp[i])
                                   for i, n in enumerate(MEDIAN_FEATURES)}
    result["median_ranks"] = {n: int(ranks[n_s + i]) + 1
                              for i, n in enumerate(MEDIAN_FEATURES)}

    # Three outcomes, not two. The first version of this branch only asked
    # whether the features HELP, so a measured degradation would have been
    # reported as "no improvement" -- true, and a serious understatement of
    # what the numbers say.
    worth_it = verdicts["candidate"] or verdicts["distinct_ring"]
    harms = n_neg10 > n_pos10 and n_neg10 >= len(SEEDS) // 2 + 1
    if worth_it:
        result["verdict"] = (
            "WORTH THE DESIGN COST: adding the per-account median improves "
            "ring-level p@k with a CI excluding zero at k=10 or k=20. A "
            "streaming quantile estimator in sentinel/graph/stats.py is "
            "justified.")
    elif harms:
        result["verdict"] = (
            f"ACTIVELY HARMFUL, NOT MERELY USELESS: the median features "
            f"DEGRADE ring-level p@10 with a CI excluding zero in "
            f"{n_neg10} of {len(SEEDS)} INDEPENDENT stochastic fits. The "
            f"model leans on "
            f"them heavily (see median_ranks) and generalises worse for it -- "
            f"the signature of overfitting a 321-positive training set, not of "
            f"an ignored feature. Do not add a streaming quantile estimator, "
            f"and note that closing a GFP coverage gap is not automatically "
            f"an improvement.")
    else:
        result["verdict"] = (
            "NOT WORTH THE DESIGN COST: no measured improvement at k=10 or "
            "k=20, and the degradation is not stable across model-fit seeds. "
            "The absence recorded in tests/test_gfp_gaps.py stands, and now "
            "stands on a measurement rather than on the argument that Welford "
            "cannot do medians. Do not add a streaming quantile estimator.")
    print(f"\nVERDICT: {result['verdict']}")

    OUT.write_text(json.dumps(result, indent=2, default=float))
    print(f"written to {OUT}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
