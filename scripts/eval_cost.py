"""Cost-evaluate the measured queue: break-even precision, and which depths clear it.

Reads `data/eval_phase2.json` if it is present (written by
`scripts/eval_phase2.py`) and falls back to the figures recorded in
docs/HANDOFF.md §5d so the script is runnable on a clean clone with no
dataset. Which source was used is printed, because a number whose provenance
is not on screen is the failure mode this project keeps a bug catalogue for.

The headline is the break-even precision, not a rupee figure -- see
`sentinel/economics/cost.py` for why that choice is the whole design.

Run:  python scripts/eval_cost.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.economics.cost import (CostModel, evaluate_queue, joint_adverse,
                                     optimal_k, sensitivity)

ROOT = Path(__file__).resolve().parent.parent
MEASURED = ROOT / "data" / "eval_phase2.json"
# This script used to print its results and write nothing, which is why the
# joint worst-case break-even reached README as a TYPED literal -- the one
# class of number standing rule 1 exists to stop. It now writes an artefact so
# `scripts/collect_metrics.py` can carry the figure into results/metrics.json
# and the document can render it.
OUT = ROOT / "data" / "eval_cost.json"

# Post-pruning figures from docs/HANDOFF.md §5d, kept here only so this script
# runs without the dataset. The size baseline is carried alongside because
# §5d's standing rule is that no headline p@k is quoted without it.
FALLBACK_SCORE = {10: 0.291, 20: 0.157, 50: 0.076}
FALLBACK_SIZE = {10: 0.094, 20: 0.074, 50: 0.051}
# Both rows moved when `gargaml` and `stack` were retired. The SIZE row moved
# too, which looks wrong for a re-ranking and is not: `suppress()` is greedy
# non-maximum suppression ordered by score, so the score decides which of
# several overlapping views of a neighbourhood survives. Change the score and
# the candidate SET changes, which every baseline is then measured on.
# See docs/SCORE-VS-SIZE-FINDINGS.md section 5.


def load_precision() -> tuple[dict, dict, str]:
    if MEASURED.exists():
        blob = json.loads(MEASURED.read_text(encoding="utf-8"))
        # `eval_phase2.py` writes {"precision": {"score": {"10": ...}}}. An
        # earlier version of this loader looked for a "rankings" wrapper with a
        # "p_at_k" sub-key, which that script has never produced -- so the
        # measured branch silently never fired and the fallback constants below
        # were always used. Both shapes are accepted now; the real one first.
        rankings = blob.get("precision") or blob.get("rankings") or blob

        def p_at_k(name: str) -> dict:
            row = rankings.get(name, {}) or {}
            if "p_at_k" in row:          # the shape the old loader expected
                row = row["p_at_k"] or {}
            return {int(k): v for k, v in row.items()}

        score, size = p_at_k("score"), p_at_k("size")
        if score:
            return score, size, str(MEASURED)
    return FALLBACK_SCORE, FALLBACK_SIZE, "docs/HANDOFF.md §5d (no local eval run)"


def main() -> int:
    score, size, provenance = load_precision()
    model = CostModel()

    print("Cost model")
    print(f"  source of p@k:        {provenance}")
    print(f"  review cost/case:     {model.review_cost:,.0f}")
    print(f"  benefit per true pos: {model.benefit_per_true_positive:,.0f}")
    print(f"  residual harm per FP: {model.harm_per_false_positive:,.0f}")
    print()
    print(f"  BREAK-EVEN PRECISION: {model.break_even_precision():.4f}")
    print()

    unsourced = model.unsourced()
    if unsourced:
        print("  !! every input below is a PLACEHOLDER, not a measured or")
        print("     cited figure. Do not quote the absolute numbers; the")
        print("     break-even and the sensitivity table are the results.")
        for name in unsourced:
            print(f"       - {name}")
        print()

    print("Queue, cost-evaluated (score ranking, size baseline alongside)")
    print(f"  {'k':>5} {'p@k':>8} {'size p@k':>9} {'net/case':>12} "
          f"{'total':>14}  pays?")
    for point in evaluate_queue(score, model):
        baseline = size.get(point.k)
        baseline_text = f"{baseline:.3f}" if baseline is not None else "  -  "
        print(f"  {point.k:>5} {point.precision:>8.3f} {baseline_text:>9} "
              f"{point.net_benefit_per_case:>12,.0f} "
              f"{point.total_net_benefit:>14,.0f}  "
              f"{'yes' if point.above_break_even else 'no'}")

    print()
    print("Inverted: the exposure per ring at which each depth breaks even")
    print("  (this does not depend on the assumed ring value -- it solves for it)")
    for point in evaluate_queue(score, model):
        need = model.required_value_at_risk(point.precision)
        print(f"    top {point.k:>3}: pays if the average confirmed ring has "
              f"more than {need:>12,.0f} at risk")

    best = optimal_k(score, model)
    print()
    if best is None:
        print("  Cost-optimal depth: none -- no depth is net-positive under "
              "these inputs.")
    else:
        print(f"  Cost-optimal depth: top {best}")

    print()
    print("Sensitivity of the break-even precision (x0.5 / x1 / x2)")
    for name, row in sensitivity(model).items():
        cells = "  ".join(f"{row[f]:.4f}" for f in sorted(row))
        print(f"  {name:<32} {cells}")
    print()
    print("  A conclusion that survives an order of magnitude on an input")
    print("  does not depend on that input's exact value.")

    print()
    print("Joint stress: all six inputs adverse at once, each by x2")
    print("  (each of review cost, benefit and FP harm is a product of two of "
          "them, so they move x4, /4 and x4 respectively)")
    print("  (sensitivity moves one input at a time, which understates the risk --")
    print("   these are placeholders, so their errors need not offset)")
    worst = joint_adverse(model, factor=2.0)
    worst_be = worst.break_even_precision()
    print(f"    break-even precision rises {model.break_even_precision():.4f} "
          f"-> {worst_be:.4f}")
    pays = {}
    for k in sorted(score):
        pays[k] = bool(score[k] > worst_be)
        verdict = "still pays" if pays[k] else "does NOT pay"
        print(f"    top {k:>3}: p@k {score[k]:.3f} vs {worst_be:.4f}  {verdict}")

    # THE FACTOR IS THE CONDITIONING, and it was not travelling with the
    # number. README quoted a joint break-even of 1.8382 -- "a precision above
    # 1.0, unreachable by any detector" -- while this script's own joint
    # section printed 0.0864, at which top 10 and top 20 STILL PAY. Both are
    # correct: 1.8382 is every input adverse by x10, 0.0864 is x2. A reader
    # given either without its factor has been given a conclusion, not a
    # measurement, so the whole sweep is recorded and every consumer must name
    # the factor it quotes.
    sweep = {}
    for f in (2.0, 3.0, 5.0, 10.0):
        be = joint_adverse(model, factor=f).break_even_precision()
        sweep[str(f)] = {
            "break_even_precision": round(be, 4),
            "exceeds_one_so_unreachable": bool(be > 1.0),
            "depths_that_pay": sorted(k for k in score if score[k] > be),
        }

    payload = {
        # Repo-relative: an absolute path in a tracked artefact leaks the
        # author's home directory and is meaningless on any other machine.
        "provenance_of_p_at_k": (
            str(Path(provenance).relative_to(ROOT)).replace("\\", "/")
            if Path(provenance).is_absolute() else provenance),
        "joint_adverse_sweep": sweep,
        "conditioning": (
            "Every joint break-even MUST be quoted with the factor that "
            "produced it. At x2 the break-even is "
            f"{sweep['2.0']['break_even_precision']} and the queue still pays "
            f"at depths {sweep['2.0']['depths_that_pay']}; at x10 it is "
            f"{sweep['10.0']['break_even_precision']}, above 1.0, so no "
            "detector of any quality pays at any depth. 'The queue does not "
            "pay' is a statement about the x10 stress and is false at x2."),
        "inputs_are_placeholders": sorted(unsourced),
        "n_unsourced_inputs": len(unsourced),
        "break_even_precision": round(model.break_even_precision(), 4),
        "joint_adverse_factor": 2.0,
        "joint_adverse_break_even_precision": round(worst_be, 4),
        # The whole point of the joint figure: a break-even precision ABOVE 1.0
        # is unreachable by any detector, perfect ones included. So under
        # simultaneous adverse inputs the queue does not pay at any depth, and
        # that is stated as a boolean rather than left for a reader to infer
        # from a number being greater than one.
        "joint_adverse_break_even_exceeds_one": bool(worst_be > 1.0),
        "queue_pays_under_joint_adverse": {str(k): v for k, v in pays.items()},
        "any_depth_pays_under_joint_adverse": any(pays.values()),
        "cost_optimal_k": best,
        "note": (
            "The break-even is INVERTED from the cost model rather than "
            "asserted as a rupee figure, so a reader who rejects every "
            "placeholder input can still check the claim. Sensitivity moves "
            "one input at a time and therefore understates the risk; these "
            "are placeholders, so their errors need not offset, which is why "
            "the joint figure is the one reported."),
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("")
    print(f"  wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
