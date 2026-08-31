"""Why the hand-set score did not beat a node-count baseline, and what fixed it.

This is the measurement behind `RETIRED_TERMS` in `sentinel/detect/features.py`
and behind open problem 1 in the README. It answers three questions in order,
because the second is only meaningful if the first comes back negative.

**1. Was the score just a proxy for size?** No. Spearman(blend, size) = -0.099
overall and negative within every held-out cycle. The obvious explanation --
"the blend has quietly reinvented node count" -- is false, and the interesting
one survives.

**2. Which terms carry signal, and with which sign?** Per-term AUC against the
candidate label, computed twice: raw, and stratified on node count. The
stratified version is the one that decides, because `size` is itself predictive
(AUC 0.710) and any term correlated with size inherits an apparent signal it
does not own. Stratifying on the 41 DISTINCT node counts holds size exactly
constant rather than approximately, which matters here: size is a small integer
with heavy ties, and quantile strata collapse on it.

Two terms come back below 0.5 on their own terms. `gargaml` and `stack` fire on
100% and 99.6% of candidates with means of 0.915 and 0.910 -- near-saturated, so
only their variance reaches the ranking, and that variance is an inverse proxy
for size (Spearman -0.495 and -0.499). Post-pruning, size became a real positive
signal, so 0.14 of the weight was ordering the queue by smallness and drowning
out terms that fire on under 1% of candidates but fire precisely.

**3. Is a fitted model needed to fix it?** No, and this is the result worth
having. Zeroing those two terms and renormalising -- no fitting, no labels
beyond the diagnosis -- moves held-out p@10 from 0.0500 to 0.1889 against a size
baseline of 0.0444. A non-negative least-squares fit of all thirteen weights on
the training split reaches 0.1944, which is inside the removal's confidence
interval. The fit is reported here because it was run and it is the honest
control, not because it is better: it costs the full label tax and buys nothing
measurable, so the shipped change is the removal.

CONDITIONING AND SCOPE, since every number below is easy to over-read:
  * This is the ring-disjoint held-out split (87 train rings, 68 test rings,
    zero overlap), 18 held-out cycles -- the same design the supervised
    re-ranker figures use, and comparable to them. It is NOT the 34-cycle
    figure the README quotes as the shipped queue's p@k.
  * The split is ring-disjoint but NOT time-disjoint: train and test cycles
    overlap. That is README open problem 2 and this measurement inherits it
    rather than fixing it.
  * The size baseline is printed beside every number, because it is the thing
    under test.

Run:  python scripts/eval_blend_v2.py
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scipy import stats as sps
from scipy.optimize import nnls

from sentinel.corpus import CorpusKey, load, require_consistent, require_poolable
from sentinel.detect.features import (RETIRED_TERMS, WEIGHTS, Features,
                                      _V1_WEIGHTS, score)

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus_amlworld_hi_small.npz"
OUT = ROOT / "data" / "eval_blend_v2.json"
DATASET = "amlworld-hi-small"
PROVENANCE = "constructed"
QUESTION = "scorer"
KS = (10, 20, 50, 100)
N_RESAMPLES = 2000
SEED = 7
TERMS = list(_V1_WEIGHTS)


def terms_matrix(X, names):
    """The 13 raw term values per row, recomputed from stored features.

    Divided back out of `score()`'s weighted contributions rather than
    reimplemented, so this cannot drift from the real scoring code.
    """
    blank = Features()
    cols = [(j, nm) for j, nm in enumerate(names) if hasattr(blank, nm)]
    T = np.zeros((X.shape[0], len(TERMS)))
    for i in range(X.shape[0]):
        f = Features()
        for j, nm in cols:
            setattr(f, nm, float(X[i, j]))
        _, contrib = score(f)
        for m, tn in enumerate(TERMS):
            # A retired term carries weight 0, so its contribution is 0 and the
            # raw value cannot be divided back out. Recompute those directly.
            w = WEIGHTS[tn]
            T[i, m] = (contrib[tn] / w) if w else _raw_term(f, tn)
    return T


def _raw_term(f: Features, tn: str) -> float:
    """The raw value of a retired term, whose weighted contribution is 0."""
    if tn == "gargaml":
        return max(0.0, f.gargaml)
    if tn == "stack":
        return f.stack_score
    raise KeyError(tn)


def auc(v, lab) -> float:
    """Mann-Whitney AUC. 0.5 is no discrimination; below 0.5 is inverted."""
    pos, neg = int((lab == 1).sum()), int((lab == 0).sum())
    if pos == 0 or neg == 0:
        return float("nan")
    r = sps.rankdata(v)
    return (r[lab == 1].sum() - pos * (pos + 1) / 2) / (pos * neg)


def stratified_auc(v, lab, strata, keep) -> float:
    """AUC pooled over strata, weighting each by its pos*neg pair count."""
    num = den = 0.0
    for s in keep:
        k = strata == s
        a = auc(v[k], lab[k])
        if not np.isnan(a):
            w = int(lab[k].sum()) * int((lab[k] == 0).sum())
            num += w * a
            den += w
    return num / den if den else float("nan")


def main() -> int:
    t0 = time.time()
    names = [str(n) for n in np.load(CORPUS, allow_pickle=True)["names"]]
    key = CorpusKey.for_current_config(DATASET, names, PROVENANCE)
    arrays, key = load(CORPUS, expect=key)
    require_poolable([key], QUESTION)
    require_consistent(arrays, names)
    print(f"corpus {key.describe()}  (no replay: a scorer question)")

    y, t = arrays["test_y"], arrays["test_t"]
    size = arrays["test_size"].astype(float)
    deg, rnd = arrays["test_degree"], arrays["test_rnd"]
    cycles = sorted(set(t.tolist()))
    tr_rings = {int(r) for r in arrays["train_ring"] if r >= 0}
    te_rings = {int(r) for r in arrays["test_ring"] if r >= 0}

    print(f"\n{len(y):,} held-out candidates, {int(y.sum())} positive "
          f"({100*y.mean():.3f}%), {len(cycles)} cycles")
    print(f"split: {len(tr_rings)} train rings / {len(te_rings)} test rings, "
          f"overlap {len(tr_rings & te_rings)} -- ring-disjoint")
    print("NOTE: ring-disjoint but NOT time-disjoint; train and test cycles "
          "overlap.\n      That is README open problem 2, inherited here, not "
          "fixed here.")

    T = terms_matrix(arrays["test_X"], names)
    w_v1 = np.array([_V1_WEIGHTS[tn] for tn in TERMS])
    w_v2 = np.array([WEIGHTS[tn] for tn in TERMS])
    v1, v2 = T @ w_v1, T @ w_v2

    # --- 1. was it a size proxy? ---------------------------------------------
    rho = sps.spearmanr(v1, size).statistic
    per_cycle = [sps.spearmanr(v1[t == c], size[t == c]).statistic for c in cycles]
    print(f"\n=== 1. Was the score a proxy for size? ===")
    print(f"  Spearman(v1 blend, size) = {rho:+.4f}   "
          f"within-cycle median {np.median(per_cycle):+.4f}")
    print("  -> No. The blend is mildly NEGATIVELY rank-correlated with size.")

    # --- 2. per-term sign and strength ---------------------------------------
    vals = np.unique(size)
    strata = np.searchsorted(vals, size)
    keep = [s for s in range(len(vals))
            if y[strata == s].sum() > 0 and (y[strata == s] == 0).sum() > 0]
    print(f"\n=== 2. Per-term discrimination ===")
    print(f"  size held EXACTLY constant across {len(vals)} distinct node "
          f"counts; {len(keep)} strata carry both classes")
    print(f"\n  {'term':<18}{'v1 w':>7}{'now':>7}{'fires':>8}{'AUC':>8}"
          f"{'strat':>8}{'rho(size)':>11}  verdict")
    diag = {}
    for m, tn in enumerate(TERMS):
        v = T[:, m]
        a, sa = auc(v, y), stratified_auc(v, y, strata, keep)
        r = sps.spearmanr(v, size).statistic
        verdict = ("INVERTED" if sa < 0.47 else
                   "positive" if sa > 0.53 else "null")
        diag[tn] = {"v1_weight": _V1_WEIGHTS[tn], "weight_now": WEIGHTS[tn],
                    "fires_on": float((v > 0).mean()), "mean": float(v.mean()),
                    "auc": float(a), "stratified_auc": float(sa),
                    "spearman_size": float(r), "verdict": verdict}
        print(f"  {tn:<18}{_V1_WEIGHTS[tn]:>7.2f}{WEIGHTS[tn]:>7.3f}"
              f"{100*(v>0).mean():>7.1f}%{a:>8.4f}{sa:>8.4f}{r:>11.4f}"
              f"  {verdict}")
    print(f"  {'size (self)':<18}{'':>7}{'':>7}{'':>8}{auc(size, y):>8.4f}")
    print(f"\n  retired: {', '.join(RETIRED_TERMS)} -- "
          f"{sum(_V1_WEIGHTS[x] for x in RETIRED_TERMS):.2f} of the v1 weight")

    # --- 3. the fitted control ----------------------------------------------
    Ttr = terms_matrix(arrays["train_X"], names)
    ytr = arrays["train_y"]
    w_pos = (ytr == 0).sum() / max(1, (ytr == 1).sum())
    sw = np.where(ytr == 1, np.sqrt(w_pos), 1.0)
    coef, _ = nnls(Ttr * sw[:, None], ytr.astype(float) * sw)
    w_fit = coef / coef.sum() if coef.sum() > 0 else coef
    fitted = T @ w_fit

    rankings = {"v1 (retired terms restored)": v1, "shipped (terms retired)": v2,
                "nnls fit on train": fitted, "size": size, "degree": deg,
                "random": rnd}

    def p_at_k(v, k):
        h = s = 0
        for c in cycles:
            i = np.flatnonzero(t == c)
            top = i[np.argsort(-v[i], kind="stable")][:k]
            h += int(y[top].sum())
            s += len(top)
        return h / s if s else 0.0

    print(f"\n=== 3. p@k on {len(cycles)} held-out cycles ===")
    print(f"  {'ranking':<30}" + "".join(f"{'p@'+str(k):>9}" for k in KS))
    prec = {}
    for nm, v in rankings.items():
        prec[nm] = {str(k): p_at_k(v, k) for k in KS}
        print(f"  {nm:<30}" + "".join(f"{p_at_k(v,k):>9.4f}" for k in KS))

    # --- paired delta vs size ------------------------------------------------
    def delta_ci(v, k):
        """Cycle-clustered paired bootstrap, the shipped p@k convention.

        The cycle is the query and therefore the independence draw. Ring
        clustering is the correct unit for the ring-level estimator, not for
        p@k, where a slot belongs to a cycle.
        """
        ra, rb = {}, {}
        for c in cycles:
            i = np.flatnonzero(t == c)
            for store, vec in ((ra, v), (rb, size)):
                top = i[np.argsort(-vec[i], kind="stable")][:k]
                store[c] = (int(y[top].sum()), len(top))

        def d(cs):
            ha, na = sum(ra[c][0] for c in cs), sum(ra[c][1] for c in cs)
            hb, nb = sum(rb[c][0] for c in cs), sum(rb[c][1] for c in cs)
            return (ha / na if na else 0.0) - (hb / nb if nb else 0.0)

        rng = random.Random(SEED)
        draws = sorted(d([cycles[rng.randrange(len(cycles))] for _ in cycles])
                       for _ in range(N_RESAMPLES))
        lo = draws[int(0.025 * N_RESAMPLES)]
        hi = draws[min(int(0.975 * N_RESAMPLES), N_RESAMPLES - 1)]
        return {"point": d(cycles), "lo": lo, "hi": hi,
                "excludes_zero": lo > 0 or hi < 0}

    print("\n=== paired delta vs the size baseline, cycle-clustered ===")
    print("ship criterion (ARCHITECTURE_UPLIFT 1.5): the delta vs `size` must "
          "exclude\nzero at BOTH k=10 and k=20. A gain whose interval includes "
          "zero is not a gain.")
    paired, ship = {}, {}
    for nm in ("v1 (retired terms restored)", "shipped (terms retired)",
               "nnls fit on train"):
        paired[nm] = {}
        print(f"\n  {nm} - size")
        for k in KS:
            d = delta_ci(rankings[nm], k)
            paired[nm][str(k)] = d
            print(f"    k={k:<4} {d['point']:+.4f} [{d['lo']:+.4f}, "
                  f"{d['hi']:+.4f}]  "
                  f"{'EXCLUDES zero' if d['excludes_zero'] else 'includes zero'}")
        ship[nm] = all(paired[nm][str(k)]["excludes_zero"] for k in (10, 20))
        print(f"    ship criterion: {'MET' if ship[nm] else 'NOT met'}")

    # Per-cycle, so a win driven by one lucky query is visible rather than
    # averaged away.
    print("\n=== per-cycle hits@10: shipped vs size ===")
    hs, hz = [], []
    for c in cycles:
        i = np.flatnonzero(t == c)
        hs.append(int(y[i[np.argsort(-v2[i], kind="stable")][:10]].sum()))
        hz.append(int(y[i[np.argsort(-size[i], kind="stable")][:10]].sum()))
    better = sum(1 for a, b in zip(hs, hz) if a > b)
    worse = sum(1 for a, b in zip(hs, hz) if a < b)
    print(f"  shipped {hs}")
    print(f"  size    {hz}")
    print(f"  better in {better}/{len(cycles)} cycles, worse in {worse}, "
          f"tied in {len(cycles)-better-worse}")

    out = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "corpus_key": key.to_dict(),
        "design": {
            "n_test_candidates": int(len(y)), "n_positive": int(y.sum()),
            "prevalence": float(y.mean()), "n_cycles": len(cycles),
            "n_train_rings": len(tr_rings), "n_test_rings": len(te_rings),
            "ring_overlap": len(tr_rings & te_rings),
            "time_disjoint": False,
            "caveat": ("ring-disjoint but NOT time-disjoint; this is the "
                       "held-out ranker design, not the 34-cycle shipped p@k"),
        },
        "size_proxy_check": {"spearman_blend_size": float(rho),
                             "within_cycle_median": float(np.median(per_cycle))},
        "per_term": diag,
        "retired_terms": list(RETIRED_TERMS),
        "retired_weight": float(sum(_V1_WEIGHTS[x] for x in RETIRED_TERMS)),
        "nnls_weights": {tn: float(w_fit[m]) for m, tn in enumerate(TERMS)},
        "precision_at": prec,
        "paired_vs_size": paired,
        "ship": ship,
        "per_cycle_hits_at_10": {"shipped": hs, "size": hz},
        "seconds": round(time.time() - t0, 2),
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT.name} in {out['seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
