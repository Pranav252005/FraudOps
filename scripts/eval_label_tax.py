"""Phase 3 -- what degraded labels cost, as a coefficient with units.

TWO ARMS, TWO PRE-REGISTRATIONS, NEVER AVERAGED.

  noise   prereg/label_tax_noise.md   -- cost of WORSE labels
  budget  prereg/label_tax_budget.md  -- cost of FEWER labels

They share a pool, a split, a model and a metric, and nothing else. There is no
combined "label tax" number in this file and there must not be one downstream:
halving the labels and mislabelling half of them are different interventions
with different mechanisms, and a single figure spanning both has no estimand
behind it.

THE RUNNER REFUSES TO START without the pre-registration for the arm being run,
committed to git. Not merely present on disk -- committed. A prereg written in
the same breath as the result it judges is not a prereg, and the only mechanical
way to tell the difference is to ask git.

EVALUATION IS ALWAYS AGAINST TRUE LABELS. Only training labels are degraded.
Scoring against corrupted labels too would measure the corruption twice and
produce a number that falls for reasons unrelated to the model.

NO REPLAY. This reads `data/ranker_pool.npz`, which is legitimate here in a way
it is NOT legitimate for a scorer-weight change: the intervention is on the
LABELS, and labels do not participate in candidate generation. `suppress()` is
ordered by score, not by y, so the candidate set is identical across every arm
and every seed. See sentinel/corpus/__init__.py for the staleness class this
reasoning is carefully avoiding.

Run:  python scripts/eval_label_tax.py --arm noise
      python scripts/eval_label_tax.py --arm budget
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightgbm import LGBMClassifier

from sentinel.eval.bootstrap import bootstrap_ci, ratio_of_sums

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "data" / "ranker_pool.npz"

KS = (10, 20, 50)
HEADLINE_K = 10
SEEDS = (11, 22, 33, 44, 55)

NOISE_GRID = (0.0, 0.05, 0.10, 0.20, 0.40)
BUDGET_GRID = (1.0, 0.5, 0.25, 0.1)

PREREG = {"noise": "prereg/label_tax_noise.md",
          "budget": "prereg/label_tax_budget.md"}


def require_committed_prereg(arm: str) -> str:
    """Refuse to run without a COMMITTED pre-registration for this arm.

    Returns the commit sha the prereg was last changed in, which is stored
    beside the results so a reader can check the order for themselves rather
    than taking this function's word for it.
    """
    rel = PREREG[arm]
    if not (ROOT / rel).is_file():
        raise SystemExit(
            f"refusing to run: {rel} does not exist. The pre-registration is "
            f"written BEFORE the experiment, not alongside it.")
    log = subprocess.run(["git", "log", "-1", "--format=%H", "--", rel],
                         cwd=ROOT, capture_output=True, text=True)
    sha = log.stdout.strip()
    if log.returncode != 0 or not sha:
        raise SystemExit(
            f"refusing to run: {rel} is not committed. An uncommitted prereg "
            f"can be edited after seeing the result, which is the entire "
            f"thing a pre-registration exists to prevent.")
    dirty = subprocess.run(["git", "status", "--porcelain", "--", rel],
                           cwd=ROOT, capture_output=True, text=True)
    if dirty.stdout.strip():
        raise SystemExit(
            f"refusing to run: {rel} has uncommitted changes. Commit them "
            f"first, so the version that judged this run is the version on "
            f"record.")
    return sha


def load_pool() -> dict:
    if not POOL.exists():
        raise SystemExit(f"missing {POOL}; run scripts/eval_ranker.py first")
    z = np.load(POOL, allow_pickle=True)
    return {"Xtr": z["train_X"], "ytr": z["train_y"].astype(int),
            "Xte": z["test_X"], "yte": z["test_y"].astype(int),
            "tte": z["test_t"], "names": [str(n) for n in z["names"]]}


def fit_and_score(Xtr, ytr, Xte) -> np.ndarray:
    """The shipped configuration, unchanged across every arm and seed.

    `random_state` is passed for form only: at default bagging LightGBM never
    consults it, so every difference between two runs here comes from the
    LABELS, which is precisely the design. See
    docs/negative-results/inert-seed-sweep.md.
    """
    m = LGBMClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                       class_weight="balanced", random_state=7, verbosity=-1)
    m.fit(Xtr, ytr)
    return m.predict_proba(Xte)[:, 1]


def cycle_rows(score, yte, tte) -> list[dict]:
    """One row per held-out cycle: hits and n at each k, scored on TRUE labels."""
    rows = []
    for t in sorted(set(int(x) for x in tte.tolist())):
        idx = np.flatnonzero(tte == t)
        order = idx[np.argsort(-score[idx], kind="stable")]
        row = {"t": int(t)}
        for k in KS:
            top = order[:k]
            row[f"hit_{k}"] = int(yte[top].sum())
            row[f"n_{k}"] = int(len(top))
        rows.append(row)
    return rows


def p_at(rows, k) -> float:
    return ratio_of_sums(f"hit_{k}", f"n_{k}")(rows)


def noise_arm(pool, p, seed) -> dict:
    """Flip `p` of the training positives to negative (raw), or drop them
    (prevalence-matched control). Positives only, one direction."""
    ytr = pool["ytr"]
    pos = np.flatnonzero(ytr == 1)
    rng = np.random.default_rng(seed)
    n_flip = int(round(p * len(pos)))
    flip = rng.choice(pos, size=n_flip, replace=False) if n_flip else np.array([], int)

    y_raw = ytr.copy()
    y_raw[flip] = 0
    keep = np.ones(len(ytr), dtype=bool)
    keep[flip] = False

    out = {}
    for label, X, y in (("raw", pool["Xtr"], y_raw),
                        ("control", pool["Xtr"][keep], ytr[keep])):
        score = fit_and_score(X, y, pool["Xte"])
        rows = cycle_rows(score, pool["yte"], pool["tte"])
        out[label] = {
            "rows": rows,
            "p_at": {k: p_at(rows, k) for k in KS},
            "n_train": int(len(y)),
            "n_positive": int(y.sum()),
            "prevalence": float(y.sum() / len(y)),
        }
    out["n_flipped"] = int(n_flip)
    return out


def budget_arm(pool, f, seed) -> dict:
    """Retain a uniform random fraction `f` of training rows, labels correct."""
    ytr = pool["ytr"]
    rng = np.random.default_rng(seed)
    n_keep = max(int(round(f * len(ytr))), 1)
    keep = rng.choice(len(ytr), size=n_keep, replace=False)
    X, y = pool["Xtr"][keep], ytr[keep]
    if y.sum() == 0:
        # Refuse to report a p@k from a model that saw no positive at all;
        # it is not a degraded model, it is a different object.
        return {"degenerate": True, "n_train": int(len(y)), "n_positive": 0}
    score = fit_and_score(X, y, pool["Xte"])
    rows = cycle_rows(score, pool["yte"], pool["tte"])
    return {
        "degenerate": False,
        "rows": rows,
        "p_at": {k: p_at(rows, k) for k in KS},
        "n_train": int(len(y)),
        "n_positive": int(y.sum()),
        "prevalence": float(y.sum() / len(y)),
    }


def ols(xs, ys) -> tuple[float, float, list[float]]:
    """Slope, intercept, residuals. Written out rather than imported so the
    residuals are available and the fit cannot silently become something else."""
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    xm, ym = x.mean(), y.mean()
    denom = ((x - xm) ** 2).sum()
    slope = ((x - xm) * (y - ym)).sum() / denom if denom else 0.0
    intercept = ym - slope * xm
    resid = (y - (slope * x + intercept)).tolist()
    return float(slope), float(intercept), resid


def slope_ci(per_point_rows: dict, xs, k, n_resamples=2000, seed=7) -> dict:
    """Bootstrap the SLOPE by resampling held-out cycles, not points.

    The cycles are the shared unit across every grid point -- the same 18 in
    all of them -- so one resample of cycles induces a p@k at every point at
    once, and the slope is recomputed on that resample. Resampling the five
    grid points instead would be bootstrapping a design, which is not a sample
    of anything.
    """
    import random
    n_cycles = len(per_point_rows[xs[0]])
    rng = random.Random(seed)
    draws = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n_cycles) for _ in range(n_cycles)]
        ys = []
        for x in xs:
            rows = per_point_rows[x]
            sample = [rows[i] for i in idx]
            ys.append(p_at(sample, k))
        draws.append(ols(xs, ys)[0])
    draws.sort()
    lo = draws[int(0.025 * n_resamples)]
    hi = draws[min(int(0.975 * n_resamples), n_resamples - 1)]
    return {"lo": lo, "hi": hi, "excludes_zero": lo > 0 or hi < 0,
            "n_resamples": n_resamples, "n_units": n_cycles}


def tax_slope_ci(raw_rows: dict, ctl_rows: dict, xs, k,
                 n_resamples=2000, seed=7) -> dict:
    """Interval on `raw_slope - control_slope`, which IS the estimand.

    Bootstrapping raw and control separately and eyeballing whether their
    intervals overlap is not this. Two intervals can overlap while their
    difference is CI-clear, and can both include zero while their difference
    does not. The arms are also strongly correlated -- same cycles, same
    features, same model, differing only in whether the flipped rows are
    present-and-wrong or absent -- so the difference is far better determined
    than either slope.

    So both slopes are recomputed on the SAME resample of cycles and
    subtracted there, which is the paired-bootstrap logic already used for
    every other delta in this repository.
    """
    import random
    n_cycles = len(raw_rows[xs[0]])
    rng = random.Random(seed)
    draws = []
    for _ in range(n_resamples):
        idx = [rng.randrange(n_cycles) for _ in range(n_cycles)]
        raw_y, ctl_y = [], []
        for x in xs:
            raw_y.append(p_at([raw_rows[x][i] for i in idx], k))
            ctl_y.append(p_at([ctl_rows[x][i] for i in idx], k))
        draws.append(ols(xs, raw_y)[0] - ols(xs, ctl_y)[0])
    draws.sort()
    lo = draws[int(0.025 * n_resamples)]
    hi = draws[min(int(0.975 * n_resamples), n_resamples - 1)]
    return {"lo": lo, "hi": hi, "excludes_zero": lo > 0 or hi < 0,
            "n_resamples": n_resamples, "n_units": n_cycles}


def required_n(spread: float, effect: float) -> int | None:
    """Cycles needed for the effect to clear its own between-seed spread.

    Computed from the observed variance rather than guessed, as the plan
    requires. Scaling is 1/sqrt(n): to shrink a half-width from `spread` to
    `effect` needs n * (spread/effect)^2 cycles. Returns None when the effect
    is zero, because no n resolves a null.
    """
    if not effect:
        return None
    return int(np.ceil(18 * (spread / abs(effect)) ** 2))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=("noise", "budget"), required=True)
    args = ap.parse_args()

    prereg_sha = require_committed_prereg(args.arm)
    print(f"pre-registration {PREREG[args.arm]} committed at {prereg_sha[:7]}")

    pool = load_pool()
    grid = NOISE_GRID if args.arm == "noise" else BUDGET_GRID
    print(f"pool: {len(pool['ytr']):,} train ({int(pool['ytr'].sum())} "
          f"positive), {len(pool['yte']):,} test "
          f"({int(pool['yte'].sum())} positive), "
          f"{len(set(pool['tte'].tolist()))} held-out cycles")
    print(f"arm={args.arm}  grid={grid}  seeds={SEEDS}")
    print("evaluation is against TRUE labels at every point.\n")

    t0 = time.time()
    points: dict = {}
    for x in grid:
        runs = []
        for seed in SEEDS:
            r = (noise_arm(pool, x, seed) if args.arm == "noise"
                 else budget_arm(pool, x, seed))
            runs.append(r)
        points[x] = runs
        if args.arm == "noise":
            raw = [r["raw"]["p_at"][HEADLINE_K] for r in runs]
            ctl = [r["control"]["p_at"][HEADLINE_K] for r in runs]
            prev = runs[0]["raw"]["prevalence"]
            print(f"  p={x:<5} raw p@10 {np.mean(raw):.4f} "
                  f"[{min(raw):.4f}, {max(raw):.4f}]   "
                  f"control {np.mean(ctl):.4f} [{min(ctl):.4f}, {max(ctl):.4f}]"
                  f"   prevalence {prev:.6f}  ({time.time()-t0:.0f}s)",
                  flush=True)
        else:
            ok = [r for r in runs if not r["degenerate"]]
            vals = [r["p_at"][HEADLINE_K] for r in ok]
            print(f"  f={x:<5} p@10 {np.mean(vals):.4f} "
                  f"[{min(vals):.4f}, {max(vals):.4f}]   "
                  f"n_train {ok[0]['n_train']:,} "
                  f"({ok[0]['n_positive']} positive, "
                  f"prevalence {ok[0]['prevalence']:.6f})"
                  f"  ({time.time()-t0:.0f}s)", flush=True)

    # --- the fit -----------------------------------------------------------
    xs = list(grid)
    out: dict = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "arm": args.arm,
        "prereg": PREREG[args.arm],
        "prereg_commit": prereg_sha,
        "grid": xs, "seeds": list(SEEDS),
        "k": HEADLINE_K,
        "ci_method": "cycle_clustered_bootstrap",
        "n_cycles": len(set(pool["tte"].tolist())),
        "evaluation_labels": "true",
        "points": {},
    }

    def seed_mean_rows(x, which=None):
        """Cycle rows averaged over seeds: hits summed, n summed.

        Averaging at the ROW level rather than averaging five p@k values keeps
        the bootstrap's unit intact -- it still resamples cycles, and each
        cycle still carries a hit count.
        """
        runs = points[x]
        sel = [(r[which] if which else r) for r in runs]
        sel = [s for s in sel if not s.get("degenerate")]
        base = sel[0]["rows"]
        merged = []
        for i, row in enumerate(base):
            m = {"t": row["t"]}
            for k in KS:
                m[f"hit_{k}"] = sum(s["rows"][i][f"hit_{k}"] for s in sel) / len(sel)
                m[f"n_{k}"] = sum(s["rows"][i][f"n_{k}"] for s in sel) / len(sel)
            merged.append(m)
        return merged

    if args.arm == "noise":
        raw_rows = {x: seed_mean_rows(x, "raw") for x in xs}
        ctl_rows = {x: seed_mean_rows(x, "control") for x in xs}
        raw_y = [p_at(raw_rows[x], HEADLINE_K) for x in xs]
        ctl_y = [p_at(ctl_rows[x], HEADLINE_K) for x in xs]
        tax_y = [r - c for r, c in zip(raw_y, ctl_y)]

        s_raw, i_raw, res_raw = ols(xs, raw_y)
        s_ctl, i_ctl, res_ctl = ols(xs, ctl_y)
        s_tax, i_tax, res_tax = ols(xs, tax_y)
        ci_raw = slope_ci(raw_rows, xs, HEADLINE_K)
        ci_ctl = slope_ci(ctl_rows, xs, HEADLINE_K)
        ci_tax = tax_slope_ci(raw_rows, ctl_rows, xs, HEADLINE_K)

        for x in xs:
            out["points"][str(x)] = {
                "raw_p_at_10": p_at(raw_rows[x], HEADLINE_K),
                "control_p_at_10": p_at(ctl_rows[x], HEADLINE_K),
                "raw_seed_values": [r["raw"]["p_at"][HEADLINE_K]
                                     for r in points[x]],
                "control_seed_values": [r["control"]["p_at"][HEADLINE_K]
                                         for r in points[x]],
                "prevalence_raw": points[x][0]["raw"]["prevalence"],
                "prevalence_control": points[x][0]["control"]["prevalence"],
                "n_flipped": points[x][0]["n_flipped"],
            }
        out["fit"] = {
            "raw_slope_per_unit_p": s_raw,
            "raw_slope_per_0.1": s_raw * 0.1,
            "raw_slope_ci": ci_raw,
            "control_slope_per_unit_p": s_ctl,
            "control_slope_per_0.1": s_ctl * 0.1,
            "control_slope_ci": ci_ctl,
            "label_tax_slope_per_unit_p": s_tax,
            "label_tax_slope_per_0.1": s_tax * 0.1,
            "label_tax_slope_ci": ci_tax,
            "residuals_raw": res_raw,
            "monotone_in_p": all(a >= b for a, b in zip(raw_y, raw_y[1:])),
        }
        print(f"\nOLS on p@{HEADLINE_K} against p:")
        print(f"  raw      slope {s_raw:+.4f} per unit p "
              f"= {s_raw*0.1:+.4f} per 0.1   "
              f"CI [{ci_raw['lo']:+.4f}, {ci_raw['hi']:+.4f}] "
              f"{'EXCLUDES ZERO' if ci_raw['excludes_zero'] else 'includes zero'}")
        print(f"  control  slope {s_ctl:+.4f} per unit p "
              f"= {s_ctl*0.1:+.4f} per 0.1   "
              f"CI [{ci_ctl['lo']:+.4f}, {ci_ctl['hi']:+.4f}] "
              f"{'EXCLUDES ZERO' if ci_ctl['excludes_zero'] else 'includes zero'}")
        print(f"  LABEL TAX (raw - control) slope {s_tax:+.4f} per unit p "
              f"= {s_tax*0.1:+.4f} per 0.1   "
              f"CI [{ci_tax['lo']:+.4f}, {ci_tax['hi']:+.4f}] "
              f"{'EXCLUDES ZERO' if ci_tax['excludes_zero'] else 'includes zero'}")
        print(f"  monotone in p: {out['fit']['monotone_in_p']}")
        if not out["fit"]["monotone_in_p"]:
            print("  NON-MONOTONE. Recorded, not smoothed. See "
                  "docs/negative-results/.")
        spread = float(np.mean([max(v["raw_seed_values"]) - min(v["raw_seed_values"])
                                for v in out["points"].values()]))
        out["fit"]["mean_between_seed_spread"] = spread
        out["fit"]["required_n_for_raw_slope"] = required_n(spread, s_raw * 0.1)
    else:
        rows = {x: seed_mean_rows(x) for x in xs}
        logs = [float(np.log2(x)) for x in xs]
        ys = [p_at(rows[x], HEADLINE_K) for x in xs]
        slope, intercept, resid = ols(logs, ys)
        ci = slope_ci({l: rows[x] for l, x in zip(logs, xs)}, logs, HEADLINE_K)
        for x in xs:
            ok = [r for r in points[x] if not r["degenerate"]]
            out["points"][str(x)] = {
                "p_at_10": p_at(rows[x], HEADLINE_K),
                "seed_values": [r["p_at"][HEADLINE_K] for r in ok],
                "n_train": ok[0]["n_train"],
                "n_positive": ok[0]["n_positive"],
                "prevalence": ok[0]["prevalence"],
                "degenerate_seeds": len(points[x]) - len(ok),
            }
        out["fit"] = {
            "slope_per_halving": slope,
            "slope_ci": ci,
            "residuals": resid,
            # The grid runs f DESCENDING (1.0 -> 0.1), so "p@10 increases with
            # f" means ys is descending in grid order. An earlier version
            # asserted the opposite and recorded a perfectly monotone response
            # as non-monotone -- which would have sent a reader looking for an
            # anomaly that was not there. The noise arm's check has the
            # opposite orientation for the same reason: its grid ascends.
            "monotone_in_f": all(a >= b for a, b in zip(ys, ys[1:])),
        }
        print(f"\nOLS on p@{HEADLINE_K} against log2(f):")
        print(f"  slope {slope:+.4f} per halving   "
              f"CI [{ci['lo']:+.4f}, {ci['hi']:+.4f}] "
              f"{'EXCLUDES ZERO' if ci['excludes_zero'] else 'includes zero'}")
        print(f"  (positive slope on log2(f) = precision FALLS as labels are "
              f"removed; each halving costs {slope:.4f})")
        print(f"  monotone in f: {out['fit']['monotone_in_f']}")
        if not out["fit"]["monotone_in_f"]:
            print("  NON-MONOTONE. Recorded, not smoothed. See "
                  "docs/negative-results/.")
        spread = float(np.mean([max(v["seed_values"]) - min(v["seed_values"])
                                for v in out["points"].values()]))
        out["fit"]["mean_between_seed_spread"] = spread
        out["fit"]["required_n_for_slope"] = required_n(spread, slope)

    out["seconds"] = round(time.time() - t0, 1)
    path = ROOT / "data" / f"eval_label_tax_{args.arm}.json"
    path.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwritten to {path.relative_to(ROOT)}  ({out['seconds']}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
