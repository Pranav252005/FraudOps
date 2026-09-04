"""M2: does the bootstrap's own Monte Carlo error change any verdict?

Pre-registered in `prereg/bootstrap_mc.md`. Every interval this project reports
uses `seed=7, n_resamples=2000`, and every result is adjudicated by asking
whether one of those endpoints excludes zero. A percentile bootstrap is itself
a Monte Carlo estimate, so those endpoints have sampling error of their own.

**No replay.** Seven committed runs persist their per-cycle rows, so every
comparison is re-run over the stored records at other seeds. Only the
resampling RNG changes; the data does not.

The unit of interest is a **verdict flip** — `excludes_zero` differing from the
committed value — not endpoint wobble. Endpoints will move; that is what Monte
Carlo error is. Only a changed conclusion is a finding.

    python scripts/eval_bootstrap_mc.py
    python scripts/eval_bootstrap_mc.py --seeds 8      # quick pass
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.eval.bootstrap import paired_bootstrap_delta

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "eval_bootstrap_mc.json"

# Files with persisted per-cycle rows, and the arm each one compares against.
# `None` means the file's rows are a flat list (one arm) and only the
# within-arm score-vs-baseline family applies.
SOURCES = {
    "eval_phase2.json": None,
    "eval_ranker.json": None,
    "eval_threshold_band.json": "hs0.5_mj0.3",
    "eval_seed_arms.json": "passthrough",
    "eval_fragment_link.json": "shipped",
    "eval_suppression_key.json": "score",
    "eval_seed_lookback.json": "lb1",
}

# The baseline every "does the score earn its place" check is against.
RETIE_BASELINE = "size"
RESAMPLES = (2000, 10000)


def ratio(rows, name, k):
    num = sum(r.get(f"{name}_hit_{k}", 0) for r in rows)
    den = sum(r.get(f"{name}_n_{k}", 0) for r in rows)
    return num / den if den else 0.0


def schema(rows):
    """(names, ks) present in these rows, from the key naming convention."""
    names, ks = set(), set()
    for key in rows[0]:
        m = re.fullmatch(r"(.+)_hit_(\d+)", key)
        if m and f"{m.group(1)}_n_{m.group(2)}" in rows[0]:
            names.add(m.group(1))
            ks.add(int(m.group(2)))
    return sorted(names), sorted(ks)


def comparisons(path, ref_arm):
    """Yield (label, records, stat_a, stat_b) for every verdict-bearing test."""
    d = json.loads(path.read_text())
    cr = d.get("cycle_rows")
    if not cr:
        return
    stem = path.stem

    if isinstance(cr, list):
        arms = {"_": cr}
    else:
        arms = cr

    for a, rows in arms.items():
        if not rows:
            continue
        names, ks = schema(rows)
        # within-arm: every ranking against the size baseline
        if RETIE_BASELINE in names:
            for other in names:
                if other == RETIE_BASELINE:
                    continue
                for k in ks:
                    yield (f"{stem}|{a}|{other}-{RETIE_BASELINE}@{k}", rows,
                           (lambda rs, k=k: ratio(rs, RETIE_BASELINE, k)),
                           (lambda rs, o=other, k=k: ratio(rs, o, k)))

    # between-arm: each arm against the reference, paired per cycle
    if ref_arm and ref_arm in arms:
        base = arms[ref_arm]
        for a, rows in arms.items():
            if a == ref_arm or len(rows) != len(base):
                continue
            names, ks = schema(rows)
            if "score" not in names:
                continue
            merged = [{"a": x, "b": y} for x, y in zip(base, rows)]
            for k in ks:
                yield (f"{stem}|{a}-{ref_arm}|score@{k}", merged,
                       (lambda rs, k=k: ratio([r["a"] for r in rs], "score", k)),
                       (lambda rs, k=k: ratio([r["b"] for r in rs], "score", k)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    t0 = time.time()
    results = []
    for fname, ref in SOURCES.items():
        path = ROOT / "data" / fname
        if not path.exists():
            print(f"  skip {fname} (absent)")
            continue
        for label, records, sa, sb in comparisons(path, ref):
            committed = paired_bootstrap_delta(records, sa, sb,
                                               n_resamples=2000, seed=7)
            entry = {"label": label, "n_units": len(records),
                     "point": committed["point"],
                     "committed": {"lo": committed["lo"], "hi": committed["hi"],
                                   "excludes_zero": committed["excludes_zero"]},
                     "nearest_endpoint": min(abs(committed["lo"]),
                                             abs(committed["hi"])),
                     "by_resamples": {}}
            for B in RESAMPLES:
                los, his, agree = [], [], 0
                for s in range(1, args.seeds + 1):
                    r = paired_bootstrap_delta(records, sa, sb,
                                               n_resamples=B, seed=s)
                    los.append(r["lo"])
                    his.append(r["hi"])
                    agree += int(r["excludes_zero"]
                                 == committed["excludes_zero"])
                entry["by_resamples"][str(B)] = {
                    "agree": agree, "seeds": args.seeds,
                    "flip_rate": 1 - agree / args.seeds,
                    "lo_spread": max(los) - min(los),
                    "hi_spread": max(his) - min(his),
                }
            results.append(entry)
        print(f"  {fname}: {sum(1 for r in results)} comparisons so far "
              f"({time.time()-t0:.0f}s)", flush=True)

    flips = {B: [r for r in results if r["by_resamples"][str(B)]["flip_rate"] > 0]
             for B in RESAMPLES}
    out = {"n_comparisons": len(results), "seeds": args.seeds,
           "resamples": list(RESAMPLES),
           "n_flipping": {str(B): len(flips[B]) for B in RESAMPLES},
           "results": results}
    args.out.write_text(json.dumps(out, indent=2))
    print(f"\n{len(results)} comparisons, {time.time()-t0:.0f}s -> {args.out}")

    for B in RESAMPLES:
        n = len(flips[B])
        print(f"\n=== n_resamples={B}: {n}/{len(results)} comparisons flip "
              f"({100*n/max(1,len(results)):.1f}%) ===")
        for r in sorted(flips[B], key=lambda x: -x["by_resamples"][str(B)]["flip_rate"]):
            d = r["by_resamples"][str(B)]
            print(f"  {r['label']:<52} point {r['point']:+.4f} "
                  f"committed [{r['committed']['lo']:+.4f},{r['committed']['hi']:+.4f}] "
                  f"excl={str(r['committed']['excludes_zero']):<5} "
                  f"flip {d['flip_rate']:.0%}  nearest {r['nearest_endpoint']:.4f}")

    far = [r for r in results if r["nearest_endpoint"] > 0.01]
    far_flip = [r for r in far if r["by_resamples"]["2000"]["flip_rate"] > 0]
    print(f"\nprereg check: comparisons with nearest endpoint > 0.01 from zero: "
          f"{len(far)}, of which flipping at B=2000: {len(far_flip)}")
    worst = max(results, key=lambda r: r["by_resamples"]["2000"]["lo_spread"],
                default=None)
    if worst:
        print(f"widest lo-endpoint spread across seeds at B=2000: "
              f"{worst['by_resamples']['2000']['lo_spread']:.4f} ({worst['label']})")


if __name__ == "__main__":
    main()
