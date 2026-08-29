"""Stage 3 of the GFP control: sentinel's feature block vs IBM GFP's.

Split out of `scripts/gfp_control.py` so that stage runs on any OS while stage
2 runs only where snapml's native GFP exists. See that module's docstring for
why the two cannot share a process.

The comparison holds everything except the feature block fixed: same candidate
pool, same ring-disjoint time-ordered split, same LGBMClassifier
hyperparameters, same per-cycle p@k, same paired bootstrap over held-out
cycles. Three blocks are scored:

  sentinel   the 54 features `sentinel/learn/reranker.py` already produces
  gfp        GFP's engineered block, mean/max/sum-pooled onto candidates
  both       concatenated, to separate "GFP is better" from "GFP adds
             something sentinel lacks", which are different claims and are
             routinely conflated

The pre-registered reading, written before the numbers exist:

  * `gfp - sentinel` CI excluding zero and positive  -> sentinel's feature
    engineering is genuinely behind GFP's, and the "essentially at parity"
    claim was false in the direction that flatters us.
  * `gfp - sentinel` CI including zero               -> no measured difference
    on this data at this sample size. That is NOT parity; it is an absence of
    evidence at n held-out cycles, and must be reported as such.
  * `both - sentinel` positive while `gfp - sentinel` is not -> GFP carries
    complementary signal even though its block alone is not better. This is
    the most likely outcome and the most useful one, because it localises
    which families to implement.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightgbm import LGBMClassifier

from sentinel.eval.bootstrap import (bootstrap_ci, paired_bootstrap_delta,
                                     ratio_of_sums)

ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = ROOT / "data" / "gfp_export"
GFP_FEATURES = ROOT / "data" / "gfp_features.npz"
COMPARE_OUT = ROOT / "data" / "eval_gfp.json"
KS = (10, 20, 50)
SPLIT_FRACTION = 0.5


def load_export(in_dir: Path = EXPORT_DIR):
    """Concatenate the per-tick export into flat arrays."""
    manifest = json.loads((in_dir / "manifest.json").read_text())
    keys, t, ring, X, blend, size, degree, rnd = [], [], [], [], [], [], [], []
    for path in sorted(in_dir.glob("tick_*.npz")):
        z = np.load(path, allow_pickle=False)
        n = len(z["keys"])
        keys.extend(str(k) for k in z["keys"])
        t.extend([int(z["t"])] * n)
        ring.append(z["ring"])
        X.append(z["sentinel_X"])
        blend.append(z["blend"])
        size.append(z["size"])
        degree.append(z["degree"])
        rnd.append(z["rnd"])
    return {
        "names": manifest["feature_names"],
        "ring_first_t": {int(k): int(v)
                         for k, v in manifest["ring_first_t"].items()},
        "keys": keys, "t": np.array(t, dtype=np.int64),
        "ring": np.concatenate(ring), "X": np.concatenate(X),
        "blend": np.concatenate(blend), "size": np.concatenate(size),
        "degree": np.concatenate(degree), "rnd": np.concatenate(rnd),
    }


def split_mask(ring, t, ring_first_t, fraction=SPLIT_FRACTION):
    """The same rule as `scripts/eval_oracle.ring_time_split`, on arrays.

    Positives go wholly to one side by ring identity; negatives split purely on
    their own timestamp. Reimplemented over arrays rather than imported because
    that function consumes record dicts, but the RULE is identical and the two
    invariants it asserts are asserted here too.
    """
    ordered = sorted(ring_first_t, key=lambda r: ring_first_t[r])
    if not ordered:
        raise SystemExit("no rings in the export; nothing to split")
    cut = max(1, int(len(ordered) * fraction))
    split_t = ring_first_t[ordered[min(cut - 1, len(ordered) - 1)]]
    train_rings = set(ordered[:cut])

    is_train = np.zeros(len(ring), dtype=bool)
    for i in range(len(ring)):
        r = int(ring[i])
        is_train[i] = (r in train_rings) if r >= 0 else (int(t[i]) < split_t)

    tr_rings = {int(r) for r in ring[is_train] if r >= 0}
    te_rings = {int(r) for r in ring[~is_train] if r >= 0}
    assert not (tr_rings & te_rings), "a ring leaked across the split"
    tr_neg = t[is_train & (ring < 0)]
    te_neg = t[~is_train & (ring < 0)]
    if len(tr_neg) and len(te_neg):
        assert tr_neg.max() <= te_neg.min(), "a negative leaked from the future"
    return is_train, split_t


def fit(Xtr, ytr, Xte, seed=7):
    """The same model everywhere, so the feature block is the only variable."""
    m = LGBMClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                       class_weight="balanced", random_state=seed,
                       verbosity=-1)
    m.fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1], m


def cycle_rows(t, y, rnd, ring, scores: dict) -> tuple[list, list]:
    """Per-cycle (hits, n) at each k, on both denominators.

    Returns (candidate_level_rows, distinct_ring_rows). Candidate-level counts
    a positive candidate; ring-level counts each ring at most once per cut,
    which is what an analyst working the queue actually gets.
    """
    by_t: dict[int, list[int]] = defaultdict(list)
    for i, tv in enumerate(t):
        by_t[int(tv)].append(i)

    cand_rows, ring_rows = [], []
    for tv in sorted(by_t):
        idx = by_t[tv]
        c_row = {"t": tv, "n_positive": int(sum(y[i] for i in idx))}
        r_row = {"t": tv, "n_distinct_rings": len({int(ring[i]) for i in idx
                                                   if ring[i] >= 0})}
        for name, s in scores.items():
            ordered = sorted(idx, key=lambda i: (-s[i], rnd[i]))
            for k in KS:
                top = ordered[:k]
                c_row[f"{name}_hit_{k}"] = int(sum(y[i] for i in top))
                c_row[f"{name}_n_{k}"] = len(top)
                r_row[f"{name}_hit_{k}"] = len({int(ring[i]) for i in top
                                                if ring[i] >= 0})
                r_row[f"{name}_n_{k}"] = len(top)
        cand_rows.append(c_row)
        ring_rows.append(r_row)
    return cand_rows, ring_rows


def compare(export_dir: Path = EXPORT_DIR, gfp_path: Path = GFP_FEATURES,
            out: Path = COMPARE_OUT) -> None:
    if not (export_dir / "manifest.json").exists():
        raise SystemExit(
            f"no export at {export_dir}. Run:\n"
            f"    python scripts/gfp_control.py export")
    if not gfp_path.exists():
        raise SystemExit(
            f"no GFP features at {gfp_path}.\n"
            f"Stage 2 has not been run, and it CANNOT be run on Windows: the\n"
            f"Windows snapml wheels contain no gf_* native symbols at any\n"
            f"version (see scripts/gfp_control.py's docstring). Run\n"
            f"    python scripts/gfp_control.py gfp-features\n"
            f"on Linux or macOS in a 3.11 venv with snapml installed, then\n"
            f"re-run this stage.\n\n"
            f"Until that has happened there is NO measured GFP comparison and\n"
            f"no parity claim of any kind belongs in the README, HANDOFF, or\n"
            f"anywhere else in this repo.")

    t0 = time.time()
    exp = load_export(export_dir)
    g = np.load(gfp_path, allow_pickle=False)

    # A smoke run (`--limit`) produces a real-looking file over a fraction of
    # the pool. Refused explicitly, because a p@k over a subset of cycles is
    # not comparable to any other number in this project and would be
    # indistinguishable from a full run once it is written down.
    if "n_ticks_processed" in g.files and \
            int(g["n_ticks_processed"]) != int(g["manifest_ticks"]):
        raise SystemExit(
            f"{gfp_path} covers {int(g['n_ticks_processed'])} of "
            f"{int(g['manifest_ticks'])} ticks -- a smoke run, not a result. "
            f"Re-run `gfp-features` without --limit.")

    # Join on (key, t). Both stages emit candidates in the same per-tick order,
    # but the join is done by identity rather than by position so a silent
    # reordering cannot misalign two feature blocks against one label vector.
    gfp_index = {(str(k), int(tv)): i
                 for i, (k, tv) in enumerate(zip(g["keys"], g["t"]))}
    rows = [gfp_index.get((k, int(tv)))
            for k, tv in zip(exp["keys"], exp["t"])]
    missing = sum(r is None for r in rows)
    if missing:
        raise SystemExit(
            f"{missing:,} of {len(rows):,} candidates have no GFP row. The "
            f"export and the GFP stage disagree about the pool; re-run both.")
    Xg = g["X"][np.array(rows, dtype=np.int64)]
    Xs = exp["X"]
    y = (exp["ring"] >= 0).astype(np.int32)

    is_train, split_t = split_mask(exp["ring"], exp["t"], exp["ring_first_t"])
    te = ~is_train
    print(f"split_t={split_t}  train {is_train.sum():,} rows "
          f"/ {int(y[is_train].sum())} positive   "
          f"test {te.sum():,} rows / {int(y[te].sum())} positive")
    print(f"feature blocks: sentinel {Xs.shape[1]}, "
          f"gfp {Xg.shape[1]} (pooled from {int(g['n_raw_gfp_features'])} raw "
          f"GFP features), both {Xs.shape[1] + Xg.shape[1]}")
    print(f"GFP stage ran on: {str(g['platform'])}")

    blocks = {
        "sentinel": (Xs[is_train], Xs[te]),
        "gfp": (Xg[is_train], Xg[te]),
        "both": (np.hstack([Xs, Xg])[is_train], np.hstack([Xs, Xg])[te]),
    }
    scores: dict[str, np.ndarray] = {}
    for name, (Xtr, Xte) in blocks.items():
        scores[name], _ = fit(Xtr, y[is_train], Xte)
        print(f"  fitted {name} ({time.time() - t0:.0f}s)")

    # The standing baselines, carried on every ranking change by the project's
    # own rule: a ranker that cannot beat node count is not a ranker.
    scores["blend"] = exp["blend"][te]
    scores["size"] = exp["size"][te]
    scores["degree"] = exp["degree"][te]
    scores["random"] = exp["rnd"][te]

    cand_rows, ring_rows = cycle_rows(exp["t"][te], y[te], exp["rnd"][te],
                                      exp["ring"][te], scores)
    print(f"\n{len(cand_rows)} held-out cycles, "
          f"{sum(r['n_positive'] for r in cand_rows)} positive candidates")

    result: dict = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "split_t": int(split_t),
                    "gfp_platform": str(g["platform"]),
                    "gfp_params": json.loads(str(g["gfp_params"])),
                    "n_sentinel_features": int(Xs.shape[1]),
                    "n_gfp_features_pooled": int(Xg.shape[1]),
                    "n_test_cycles": len(cand_rows)}

    for label, rws in (("candidate", cand_rows), ("distinct_ring", ring_rows)):
        print(f"\n--- {label}-level p@k ---")
        print(f"{'block':<12}" + "".join(f"{'p@' + str(k):>12}" for k in KS))
        point, ci = {}, {}
        for k in KS:
            point[k] = {}
            for name in scores:
                stat = ratio_of_sums(f"{name}_hit_{k}", f"{name}_n_{k}")
                point[k][name] = stat(rws)
                ci[f"{name}@{k}"] = bootstrap_ci(rws, stat)
        for name in scores:
            print(f"{name:<12}" + "".join(f"{point[k][name]:>12.4f}"
                                          for k in KS))

        print(f"\npaired bootstrap deltas, 95% CI over the same cycles:")
        paired = {}
        pairs = [("gfp", "sentinel"), ("both", "sentinel"), ("both", "gfp"),
                 ("sentinel", "size"), ("gfp", "size"), ("sentinel", "blend"),
                 ("gfp", "blend")]
        for k in KS:
            for a, b in pairs:
                a_stat = ratio_of_sums(f"{a}_hit_{k}", f"{a}_n_{k}")
                b_stat = ratio_of_sums(f"{b}_hit_{k}", f"{b}_n_{k}")
                d = paired_bootstrap_delta(rws, b_stat, a_stat)
                paired[f"{a}-{b}@{k}"] = d
                flag = "REAL" if d["excludes_zero"] else "includes zero"
                print(f"  k={k:<3} {a:<9} - {b:<9} "
                      f"{d['point']:+.4f} [{d['lo']:+.4f}, {d['hi']:+.4f}]"
                      f"  {flag}")
        result[label] = {"precision_at": {str(k): point[k] for k in KS},
                         "precision_ci": ci, "paired": paired,
                         "cycle_rows": rws}

    # The claim, generated from the numbers rather than written by hand, so it
    # cannot drift away from them.
    d10 = result["candidate"]["paired"]["gfp-sentinel@10"]
    d20 = result["candidate"]["paired"]["gfp-sentinel@20"]
    if d10["excludes_zero"] or d20["excludes_zero"]:
        sign = "BEHIND" if (d10["point"] > 0 or d20["point"] > 0) else "AHEAD OF"
        verdict = (f"sentinel's feature block is measurably {sign} GFP's on "
                   f"ring-level p@k on this pool.")
    else:
        verdict = ("no measured difference between the two feature blocks at "
                   f"k=10 or k=20 on {len(cand_rows)} held-out cycles. This is "
                   "an absence of evidence at this sample size, NOT a "
                   "demonstration of parity, and must not be written up as "
                   "one.")
    result["verdict"] = verdict
    print(f"\nVERDICT: {verdict}")

    out.write_text(json.dumps(result, indent=2, default=float))
    print(f"written to {out}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    compare()
