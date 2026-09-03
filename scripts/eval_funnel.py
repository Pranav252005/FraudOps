"""Permanent funnel report: seed-reachable -> seeded -> built -> ranked.

Every ring-level accuracy number this project reports is uninterpretable
without knowing which stage lost the ring. This script measures the funnel
per typology, and reports bootstrap confidence intervals on the headline
metrics (ring p@10/p@20/p@50, ring recall) so a point estimate is never
presented alone.

The printed report also states each stage's loss in *percentage points* of
ring recall, so the reader is not left subtracting two percentages to find
out which stage is the expensive one, and labels each typology row with an
interpretation derived from its own build retention (see THRESHOLDS below).
Both are arithmetic over numbers already measured -- no new measurement, no
new parameter, and nothing that can move the funnel counts.

Writes two permanent artifacts:
  data/funnel.json  -- full stage counts, recalls, and metric CIs
  data/funnel.csv   -- the per-typology funnel table alone, for a quick look

Both schemas are strictly additive: existing keys and CSV columns keep their
names, types and order, and the loss/interpretation fields append.

Run: python scripts/eval_funnel.py
"""
from __future__ import annotations

import csv
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.eval.bootstrap import bootstrap_ci, ratio_of_sums, union_recall
from sentinel.eval.funnel import FunnelTracker, is_hit
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

ROOT = Path(__file__).resolve().parent.parent
KS = (10, 20, 50)
EVERY = 6
MIN_RING_NODES = 3
RANK_K_FOR_FUNNEL = 50

# The three stage-to-stage drops, as (label, from_stage, to_stage). The loss is
# reported in percentage points of ring recall, which is the unit the reader
# actually wants: "ranking costs 44 points" is a claim, "63% then 19%" is
# homework.
STAGE_PAIRS = (("seeding", "seed_reachable", "seeded"),
               ("build", "seeded", "built"),
               ("ranking", "built", "ranked"))

# THRESHOLDS for the per-typology interpretation label.
#
# The label is derived from one axis only -- build retention, built/seeded --
# because on the measured rows that single number separates the three classes
# cleanly, and it separates them into exactly the classes the stage losses
# describe. Sorted, the measured retentions are:
#
#   BIPARTITE .18  STACK .30  |  RANDOM .77  FAN-OUT .80  FAN-IN .81  |
#   GATHER-SCATTER .89  CYCLE .90  SCATTER-GATHER .96
#
# so both cuts are placed inside an empty gap rather than on top of a row.
BUILD_DESTROYED_BELOW = 0.50      # gap .30 -> .77; the cut has ~.2 slack either
                                  # way, so it is not a fragile boundary
BUILD_HEALTHY_AT_OR_ABOVE = 0.85  # gap .81 -> .89; the TIGHTER of the two cuts
#
# Boundary behaviour, stated because a threshold nobody has poked at is a
# hidden assumption:
#   * the comparison is `>=` at .85 and `<` at .50, so a row landing exactly on
#     .85 is called healthy and one landing exactly on .50 is not called
#     destroyed;
#   * the .85 cut has only ~.04 of clearance on each side (FAN-IN .808 below,
#     GATHER-SCATTER .886 above). A row shifting by four points across that
#     line changes label, and that is a real limitation of the label, not of
#     the measurement underneath it;
#   * a typology seeded zero times has no defined retention and is labelled
#     "not seeded" rather than being forced into one of the three classes;
#   * the TOTAL row is labelled "aggregate": mixing eight typologies into one
#     retention and then reading it as a diagnosis is exactly the averaging
#     mistake this funnel exists to prevent.
#
# One axis is enough because ranking is the larger of the two losses for every
# row that is not build-destroyed -- so "healthy through build" and "ordinary
# attrition" differ in how much survives the build stage, not in where the rest
# of the loss lands.
LABEL_DESTROYED = "build-destroyed"
LABEL_RANKING = "ranking-limited"
LABEL_ORDINARY = "ordinary attrition"


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def stage_losses_pts(row: dict) -> dict:
    """Each stage's drop in percentage points of ring recall, from one row.

    Pure arithmetic over recalls the tracker already reported; it cannot
    change a count.
    """
    return {name: 100.0 * (row[f"{a}_recall"] - row[f"{b}_recall"])
            for name, a, b in STAGE_PAIRS}


def build_retention(row: dict) -> float | None:
    """Share of a typology's *seeded* rings that go on to be built."""
    return (row["built"] / row["seeded"]) if row["seeded"] else None


def interpret(row: dict) -> str:
    """Classify one funnel row from its own numbers. See THRESHOLDS above."""
    if row["typology"] == "TOTAL":
        return "aggregate"
    r = build_retention(row)
    if r is None:
        return "not seeded"
    if r < BUILD_DESTROYED_BELOW:
        return LABEL_DESTROYED
    if r >= BUILD_HEALTHY_AT_OR_ABOVE:
        return LABEL_RANKING
    return LABEL_ORDINARY


def annotate(rows: list[dict]) -> list[dict]:
    """Append the derived fields to every row, in place and at the end.

    Order matters: `csv.DictWriter` takes its field order from the first row's
    keys, so appending here is what keeps the CSV schema additive.
    """
    for row in rows:
        losses = stage_losses_pts(row)
        r = build_retention(row)
        row["build_retention"] = r if r is not None else 0.0
        for name, _, _ in STAGE_PAIRS:
            row[f"{name}_loss_pts"] = losses[name]
        row["interpretation"] = interpret(row)
    return rows


def main() -> None:
    rng = random.Random(7)
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)
    tracker = FunnelTracker(rank_k=RANK_K_FOR_FUNNEL)

    # Per-cycle records for bootstrap CIs, one dict per generation run.
    cycle_records: list[dict] = []
    runs = 0
    t0 = time.time()

    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue

        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue

        seed_nodes = gen.seeds(b)
        cands = gen.generate(b)
        if not cands:
            continue
        runs += 1

        tracker.observe_cycle(rings, stream.ring_typology, seed_nodes, cands)

        rec = {"seen": set(rings), "found": {k: set() for k in KS}}
        for k in KS:
            rec[f"hit_{k}"] = 0
            rec[f"tot_{k}"] = 0
            top = cands[:k]
            rec[f"tot_{k}"] = len(top)
            for c in top:
                nodes = set(c.nodes)
                hit_rings = [r for r, members in rings.items() if is_hit(nodes, members)]
                if hit_rings:
                    rec[f"hit_{k}"] += 1
                    rec["found"][k].update(hit_rings)
        cycle_records.append(rec)

        print(f"  run {runs:>3} t={graph.now//1440}d{(graph.now%1440)//60:02d}h "
              f"cands={len(cands):>6,} rings={len(rings):>4} "
              f"({time.time()-t0:.0f}s)", flush=True)

    print(f"\n{runs} generation runs over {EVAL_END//1440} days "
          f"in {time.time()-t0:.0f}s\n")

    # --- the funnel table ---------------------------------------------------
    rows = annotate(tracker.to_rows())
    print(f"{'typology':<16}{'total':>7}" +
          "".join(f"{s:>16}" for s in ('seed_reachable', 'seeded', 'built', 'ranked')) +
          f"   {'interpretation':<19}")
    for row in rows:
        print(f"{row['typology']:<16}{row['total']:>7}" +
              "".join(f"{row[s]:>7}({row[s+'_recall']:>5.0%})"
                      for s in ('seed_reachable', 'seeded', 'built', 'ranked')) +
              f"   {row['interpretation']:<19}")

    total_row = rows[-1]

    # --- where the loss lives, in points -------------------------------------
    # Percentage points of ring recall, so the largest loss is a number on the
    # page rather than a subtraction the reader has to perform.
    losses = stage_losses_pts(total_row)
    worst = max(losses, key=losses.get)
    print(f"\nstage losses, in percentage points of ring recall "
          f"({total_row['total']} rings, all typologies):")
    for name, a, b in STAGE_PAIRS:
        mark = "   <-- LARGEST LOSS" if name == worst else ""
        print(f"  {name:<9}{total_row[a+'_recall']:>7.1%} -> "
              f"{total_row[b+'_recall']:>6.1%}   {-losses[name]:>+7.1f} pts{mark}")
    print(f"  {'total':<9}{total_row['seed_reachable_recall']:>7.1%} -> "
          f"{total_row['ranked_recall']:>6.1%}   {-sum(losses.values()):>+7.1f} pts")
    print(f"\n{worst.upper()} is the single largest loss in the funnel, at "
          f"{losses[worst]:.1f} points.")

    print(f"\nOnly {total_row['built_recall']:.0%} of active rings become "
          f"candidates at all (built stage), of {total_row['total']} rings seen.")
    zero_built = [r["typology"] for r in rows[:-1] if r["total"] and r["built"] == 0]
    if zero_built:
        print(f"Typologies with ZERO candidates generated: {', '.join(zero_built)}")
    destroyed = [r["typology"] for r in rows[:-1]
                 if r["interpretation"] == LABEL_DESTROYED]
    if destroyed:
        print(f"Seeded, then destroyed at the build stage "
              f"(build retention < {BUILD_DESTROYED_BELOW:.0%}): "
              f"{', '.join(destroyed)}")

    # --- bootstrap CIs on the headline metrics -------------------------------
    print(f"\n{'metric':<14}{'point':>8}{'lo':>8}{'hi':>8}   (95% CI, n={len(cycle_records)} cycles)")
    ci_out = {}
    for k in KS:
        stat = ratio_of_sums(f"hit_{k}", f"tot_{k}")
        result = bootstrap_ci(cycle_records, stat)
        ci_out[f"p@{k}"] = result
        print(f"{'p@'+str(k):<14}{result['point']:>8.3f}{result['lo']:>8.3f}{result['hi']:>8.3f}")

    for k in KS:
        def found_k(records, k=k):
            return union_recall(f"__found_{k}", "seen")(
                [{"__found_" + str(k): r["found"][k], "seen": r["seen"]} for r in records])
        result = bootstrap_ci(cycle_records, found_k)
        ci_out[f"ring_recall@{k}"] = result
        print(f"{'recall@'+str(k):<14}{result['point']:>8.3f}{result['lo']:>8.3f}{result['hi']:>8.3f}")

    # Additive only: `runs`, `rank_k_for_funnel`, `funnel_by_typology` and
    # `metric_cis` keep their names, types and meaning; the rest is new.
    out = {
        "runs": runs,
        "rank_k_for_funnel": RANK_K_FOR_FUNNEL,
        "funnel_by_typology": rows,
        "metric_cis": ci_out,
        "stage_losses_pts": losses,
        "largest_loss_stage": worst,
        "interpretation_thresholds": {
            "axis": "build_retention (built / seeded)",
            "build_destroyed_below": BUILD_DESTROYED_BELOW,
            "build_healthy_at_or_above": BUILD_HEALTHY_AT_OR_ABOVE,
        },
    }
    (ROOT / "data" / "funnel.json").write_text(json.dumps(out, indent=2))
    with open(ROOT / "data" / "funnel.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("\nwritten to data/funnel.json and data/funnel.csv")


if __name__ == "__main__":
    main()
