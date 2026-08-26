"""Permanent funnel report: seed-reachable -> seeded -> built -> ranked.

Every ring-level accuracy number this project reports is uninterpretable
without knowing which stage lost the ring. This script measures the funnel
per typology, and reports bootstrap confidence intervals on the headline
metrics (ring p@10/p@20/p@50, ring recall) so a point estimate is never
presented alone.

Writes two permanent artifacts:
  data/funnel.json  -- full stage counts, recalls, and metric CIs
  data/funnel.csv   -- the per-typology funnel table alone, for a quick look

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


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def main() -> None:
    rng = random.Random(7)
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(ROOT / "data" / "amlworld" / "HI-Small_accounts.csv")
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
    rows = tracker.to_rows()
    print(f"{'typology':<16}{'total':>7}" +
          "".join(f"{s:>16}" for s in ('seed_reachable', 'seeded', 'built', 'ranked')))
    for row in rows:
        print(f"{row['typology']:<16}{row['total']:>7}" +
              "".join(f"{row[s]:>7}({row[s+'_recall']:>5.0%})"
                      for s in ('seed_reachable', 'seeded', 'built', 'ranked')))

    total_row = rows[-1]
    print(f"\nOnly {total_row['built_recall']:.0%} of active rings become "
          f"candidates at all (built stage), of {total_row['total']} rings seen.")
    zero_built = [r["typology"] for r in rows[:-1] if r["total"] and r["built"] == 0]
    if zero_built:
        print(f"Typologies with ZERO candidates generated: {', '.join(zero_built)}")

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

    out = {
        "runs": runs,
        "rank_k_for_funnel": RANK_K_FOR_FUNNEL,
        "funnel_by_typology": rows,
        "metric_cis": ci_out,
    }
    (ROOT / "data" / "funnel.json").write_text(json.dumps(out, indent=2))
    with open(ROOT / "data" / "funnel.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print("\nwritten to data/funnel.json and data/funnel.csv")


if __name__ == "__main__":
    main()
