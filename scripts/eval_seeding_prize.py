"""Phase 2B -- the seeding prize, with the interval it has never carried.

docs/CENTREPIECE-INVALIDATED.md states the headline this file exists to
qualify: "Fixing seeding is worth ~2.2x at k=10 to the shipped scorer. Fixing
the scorer is worth 1.32x." Both halves of that sentence are ratios of point
estimates over 18 held-out cycles, and NEITHER has ever been quoted with an
interval. A ratio of two noisy quantities is noisier than either, so a bare
"2.2x" is the least defensible number in the repository -- and it is currently
carrying the strategic conclusion that the scorer was never the binding
constraint.

WHAT THIS DOES NOT NEED. No replay. `data/eval_oracle.json` already stores
per-cycle hit counts for both arms (`cycle_rows`), and both arms run over the
SAME 18 tick values -- asserted below rather than assumed. So the two arms can
be paired cycle by cycle and resampled together, which is what makes an
interval on the delta meaningful rather than a comparison of two independent
wide intervals.

CLUSTERING. Cycle-clustered, and that is the CORRECT choice here rather than a
convenient one: p@k is defined per cycle, one query, one ranked list, and its
trials are not nested within rings. See docs/STANDING-RULES.md rule 5, which
was restated after the original form ("never cycle-clustered") turned out to
be wrong for exactly this metric.

WHAT IS BEING COMPARED. The same scorer, the same features, the same harness,
the same cycles -- only the seed rule differs. Run 2 remains a CEILING
DIAGNOSTIC and nothing here makes it a result: it seeds on every active ring's
own members, which the real detector can never do. The quantity is "how much
headroom sits behind the seed rule", not "what the system would score".

Run:  python scripts/eval_seeding_prize.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.eval.bootstrap import (bootstrap_ci, paired_bootstrap_delta,
                                     ratio_of_sums)

ROOT = Path(__file__).resolve().parent.parent
ORACLE = ROOT / "data" / "eval_oracle.json"
OUT = ROOT / "data" / "eval_seeding_prize.json"

KS = (10, 20, 50)
# `blend` is the shipped v1 hand-set scorer and is the arm the 2.2x claim is
# about. `oracle` is the supervised re-ranker, included so the two headline
# ratios can be read on one denominator instead of from two documents.
RANKINGS = ("blend", "oracle", "size")

CONDITIONING = (
    "CEILING DIAGNOSTIC. The 'cheat' arm seeds on every active ring's own "
    "members -- something the real detector can never do. This measures the "
    "headroom behind the seed rule, not an achievable score. Nothing here may "
    "be quoted as a result. Both arms: true ring labels, 18 held-out cycles, "
    "same split, same harness.")


def ratio_stat(num_prefix: str, den_prefix: str, k: int):
    """cheat p@k / as-is p@k, computed on one resample.

    Written as a single statistic over paired rows rather than as a quotient of
    two separately bootstrapped numbers, because the arms are correlated -- a
    cycle that is hard for one is hard for the other -- and dividing two
    independent intervals would overstate the width considerably.
    """
    def stat(rows):
        num_h = sum(r[f"{num_prefix}_hit_{k}"] for r in rows)
        num_n = sum(r[f"{num_prefix}_n_{k}"] for r in rows)
        den_h = sum(r[f"{den_prefix}_hit_{k}"] for r in rows)
        den_n = sum(r[f"{den_prefix}_n_{k}"] for r in rows)
        if not num_n or not den_n:
            return float("nan")
        den = den_h / den_n
        return (num_h / num_n) / den if den > 0 else float("nan")
    return stat


def merge(as_is_rows, cheat_rows) -> list[dict]:
    """One row per cycle carrying both arms, keyed on the tick.

    The assertion is the point of the function. Pairing two arms that did not
    run over the same cycles would produce a delta that is partly a difference
    of denominators -- which is the exact defect uplift plan item 0.2 was
    written to fix, where a p@10 over ~17 cycles was compared against one over
    all 34 and the resulting "2.8x" was not a ratio of anything.
    """
    by_t_a = {r["t"]: r for r in as_is_rows}
    by_t_b = {r["t"]: r for r in cheat_rows}
    assert set(by_t_a) == set(by_t_b), (
        f"the two arms do not share cycles: "
        f"{sorted(set(by_t_a) ^ set(by_t_b))[:8]}")
    rows = []
    for t in sorted(by_t_a):
        row = {"t": t}
        for name, src in (("asis", by_t_a[t]), ("cheat", by_t_b[t])):
            for rank in RANKINGS:
                for k in KS:
                    row[f"{name}_{rank}_hit_{k}"] = src[f"{rank}_hit_{k}"]
                    row[f"{name}_{rank}_n_{k}"] = src[f"{rank}_n_{k}"]
        rows.append(row)
    return rows


def main() -> int:
    if not ORACLE.exists():
        print(f"missing {ORACLE}; run scripts/eval_oracle.py first")
        return 1
    d = json.loads(ORACLE.read_text(encoding="utf-8"))
    as_is, cheat = d["oracle_as_is"], d["oracle_on_all_rings"]
    rows = merge(as_is["cycle_rows"], cheat["cycle_rows"])

    print(CONDITIONING)
    print()
    print(f"n = {len(rows)} held-out cycles, paired by tick. "
          f"Interval: cycle-clustered bootstrap (rule 5).")
    print(f"oracle measured_at {d['measured_at']}")
    print()

    out: dict = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "source": "data/eval_oracle.json",
                 "oracle_measured_at": d["measured_at"],
                 "n_cycles": len(rows),
                 "ci_method": "cycle_clustered_bootstrap",
                 "conditioning": CONDITIONING,
                 "prize": {}}

    for rank in RANKINGS:
        print(f"--- {rank} : as-is seeding vs seed-cheat ---")
        for k in KS:
            a = ratio_of_sums(f"asis_{rank}_hit_{k}", f"asis_{rank}_n_{k}")
            b = ratio_of_sums(f"cheat_{rank}_hit_{k}", f"cheat_{rank}_n_{k}")
            delta = paired_bootstrap_delta(rows, a, b)
            ratio = bootstrap_ci(rows, ratio_stat(f"cheat_{rank}",
                                                  f"asis_{rank}", k))
            flag = "REAL" if delta["excludes_zero"] else "INCLUDES ZERO"
            # The absolute values are printed FIRST and on the same line as the
            # ratio, because a ratio without them is not interpretable and this
            # project has already shipped one that was not a ratio of anything.
            print(f"  k={k:<3} as-is {delta['a']:.4f} -> cheat {delta['b']:.4f}"
                  f"   delta {delta['point']:+.4f} "
                  f"[{delta['lo']:+.4f}, {delta['hi']:+.4f}]  {flag}")
            print(f"        ratio {ratio['point']:.2f}x "
                  f"[{ratio['lo']:.2f}x, {ratio['hi']:.2f}x]")
            out["prize"][f"{rank}@{k}"] = {
                "as_is": delta["a"], "cheat": delta["b"],
                "delta": delta["point"], "delta_lo": delta["lo"],
                "delta_hi": delta["hi"],
                "delta_excludes_zero": delta["excludes_zero"],
                "ratio": ratio["point"], "ratio_lo": ratio["lo"],
                "ratio_hi": ratio["hi"],
                "n_cycles": len(rows),
            }
        print()

    # The comparison the strategic claim actually rests on, stated on one
    # denominator: seeding headroom against scorer headroom, for the SHIPPED
    # scorer, at the depth the claim is made at.
    seed10 = out["prize"]["blend@10"]
    scorer10 = as_is["oracle_over_blend"]["10"]
    print("the claim this file exists to qualify "
          "(docs/CENTREPIECE-INVALIDATED.md):")
    print(f"  seeding prize, blend p@10:  {seed10['ratio']:.2f}x "
          f"[{seed10['ratio_lo']:.2f}x, {seed10['ratio_hi']:.2f}x]  "
          f"({seed10['as_is']:.4f} -> {seed10['cheat']:.4f})")
    print(f"  scorer prize, oracle/blend: {scorer10:.2f}x  "
          f"(NO INTERVAL -- oracle_over_blend is a ratio of point estimates)")
    overlap = seed10["ratio_lo"] <= scorer10 <= seed10["ratio_hi"]
    print(f"  is the scorer ratio inside the seeding ratio's interval? "
          f"{'YES -- the two are not separated at this n' if overlap else 'no'}")
    out["comparison"] = {
        "seeding_ratio_blend_at_10": seed10["ratio"],
        "seeding_ratio_lo": seed10["ratio_lo"],
        "seeding_ratio_hi": seed10["ratio_hi"],
        "scorer_ratio_oracle_over_blend_at_10": scorer10,
        "scorer_ratio_has_interval": False,
        "scorer_ratio_inside_seeding_interval": overlap,
    }

    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwritten to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
