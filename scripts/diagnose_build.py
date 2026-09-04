"""Why does a seeded ring fail to become a candidate?

This is the follow-up the funnel measurement demanded. `scripts/eval_funnel.py`
established that seeding is not the bottleneck (89% of active rings are
seeded; BIPARTITE 90%, STACK 100%) but that BIPARTITE builds a covering
candidate only 3% of the time and STACK only 13%. That says the loss is in
two-hop expansion, and the obvious next move -- widening the seed rule -- would
target a stage that is already working.

A ring is "built" when some candidate both contains >=50% of it (containment)
and reaches Jaccard >= 0.3 against it. Those two floors fail for different
reasons and imply opposite fixes, so this script separates them per ring:

  CONTAINMENT_FAIL -- expansion never reached enough of the ring. Sub-reasons
      come from `WindowedGraph.expand_traced`: the hub guard refused to
      traverse a high-degree member (`hub_blocked`), the node cap truncated
      (`truncated`/`hit_node_cap`), or the graph simply ran out
      (`exhausted`) -- the last meaning the ring is genuinely further than
      `EXPAND_HOPS` away from its own seed, which is what a 3-layer STACK
      would look like.
      -> fix by raising hops / relaxing the hub guard for ring-shaped
         neighbourhoods.

  DILUTION_FAIL -- expansion DID reach >=50% of the ring, but the
      neighbourhood it dragged in alongside was so large that Jaccard fell
      under 0.3. The structure was found and then buried.
      -> fix by pruning the candidate (or by revisiting whether a flat
         Jaccard floor is the right hit test for wide, shallow typologies
         like BIPARTITE).

The distinction matters: CONTAINMENT_FAIL says expand harder, DILUTION_FAIL
says expand *less* and prune. Guessing wrong makes the other one worse.

Writes data/build_diagnosis.json and a per-typology table.

Run: python scripts/diagnose_build.py
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.data.datasets import active_stream_dir
from sentinel.config import (EVAL_END, EXPAND_HOPS, EXPAND_MAX_DEGREE,
                             EXPAND_MAX_NODES, TICK_MINUTES, WINDOW_MINUTES)
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.eval.funnel import HIT_SHARE, MIN_JACCARD
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

ROOT = Path(__file__).resolve().parent.parent
EVERY = 6
MIN_RING_NODES = 3

# Overridable so the "would more hops fix BIPARTITE/STACK?" question is a
# 35-second experiment rather than an argument:
#   python scripts/diagnose_build.py [hops] [max_nodes]
HOPS = int(sys.argv[1]) if len(sys.argv) > 1 else EXPAND_HOPS
MAX_NODES = int(sys.argv[2]) if len(sys.argv) > 2 else EXPAND_MAX_NODES
MAX_DEGREE = int(sys.argv[3]) if len(sys.argv) > 3 else EXPAND_MAX_DEGREE


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def classify(best: dict) -> str:
    """Turn the best expansion attempt for one ring into a failure class."""
    if best["containment"] >= HIT_SHARE and best["jaccard"] >= MIN_JACCARD:
        return "BUILT"
    if best["containment"] < HIT_SHARE:
        return "CONTAINMENT_FAIL"
    return "DILUTION_FAIL"


def sub_reason(best: dict) -> str:
    """For a containment failure, which bound actually stopped expansion.

    `hop_limit` is the residual and the most interesting one: expansion
    completed every hop it was allowed, was never truncated, never blocked by
    the hub guard, and never ran out of graph -- it simply was not permitted
    to go further. That is the signature of a ring whose members sit more
    than EXPAND_HOPS away from the seed, which is exactly what a multi-layer
    STACK or a wide BIPARTITE should look like.
    """
    t = best["trace"]
    if t.get("hit_node_cap") or t.get("truncated"):
        return "node_cap"
    if t.get("hub_blocked"):
        return "hub_guard"
    if t.get("exhausted"):
        return "out_of_reach"
    return "hop_limit"


def main() -> None:
    stream = Stream(active_stream_dir(ROOT))
    registry = AccountRegistry.load(DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    # ring_id -> best attempt seen across the whole run
    best_by_ring: dict[int, dict] = {}
    typ_by_ring: dict[int, str] = {}
    runs = 0
    t0 = time.time()

    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue
        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue
        seeds = gen.seeds(b)
        if not seeds:
            continue
        runs += 1

        for ring_id, members in rings.items():
            typ_by_ring[ring_id] = stream.ring_typology(ring_id) or "UNKNOWN"
            ring_seeds = members & seeds
            if not ring_seeds:
                continue  # not seeded this cycle; the funnel already covers that
            for s in ring_seeds:
                nodes, trace = graph.expand_traced(
                    [s], hops=HOPS, max_nodes=MAX_NODES,
                    max_degree=MAX_DEGREE)
                inter = len(nodes & members)
                containment = inter / len(members)
                jaccard = inter / len(nodes | members)
                prev = best_by_ring.get(ring_id)
                # "Best" = best containment, tie-broken on Jaccard: containment
                # is the floor that decides whether the ring was reached at all.
                if prev is None or (containment, jaccard) > (prev["containment"],
                                                              prev["jaccard"]):
                    best_by_ring[ring_id] = {
                        "containment": containment, "jaccard": jaccard,
                        "ring_size": len(members), "cand_size": len(nodes),
                        "trace": trace,
                    }
        print(f"  run {runs:>3} rings={len(rings):>4} tracked={len(best_by_ring):>4} "
              f"({time.time()-t0:.0f}s)", flush=True)

    print(f"\n{runs} cycles in {time.time()-t0:.0f}s; "
          f"{len(best_by_ring)} seeded rings analysed\n")

    rows: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "BUILT": 0, "CONTAINMENT_FAIL": 0, "DILUTION_FAIL": 0,
                 "node_cap": 0, "hub_guard": 0, "out_of_reach": 0, "hop_limit": 0,
                 "sum_containment": 0.0, "sum_jaccard": 0.0,
                 "sum_ring_size": 0.0, "sum_cand_size": 0.0})

    for ring_id, best in best_by_ring.items():
        typ = typ_by_ring.get(ring_id, "UNKNOWN")
        row = rows[typ]
        verdict = classify(best)
        row["total"] += 1
        row[verdict] += 1
        if verdict == "CONTAINMENT_FAIL":
            row[sub_reason(best)] += 1
        row["sum_containment"] += best["containment"]
        row["sum_jaccard"] += best["jaccard"]
        row["sum_ring_size"] += best["ring_size"]
        row["sum_cand_size"] += best["cand_size"]

    print(f"{'typology':<16}{'seeded':>7}{'built':>7}{'contain':>9}{'dilute':>8}"
          f"{'FOUND':>7}{'med_cont':>10}{'med_jacc':>10}{'ring':>7}{'cand':>7}")
    out_rows = []
    for typ in sorted(rows):
        r = rows[typ]
        n = max(1, r["total"])
        line = {
            "typology": typ, "seeded": r["total"], "built": r["BUILT"],
            "containment_fail": r["CONTAINMENT_FAIL"],
            "dilution_fail": r["DILUTION_FAIL"],
            "containment_sub_reasons": {
                "node_cap": r["node_cap"], "hub_guard": r["hub_guard"],
                "out_of_reach": r["out_of_reach"], "hop_limit": r["hop_limit"]},
            "recovered_at_containment": r["BUILT"] + r["DILUTION_FAIL"],
            "mean_best_containment": r["sum_containment"] / n,
            "mean_best_jaccard": r["sum_jaccard"] / n,
            "mean_ring_size": r["sum_ring_size"] / n,
            "mean_cand_size": r["sum_cand_size"] / n,
        }
        out_rows.append(line)
        print(f"{typ:<16}{r['total']:>7}{r['BUILT']:>7}"
              f"{r['CONTAINMENT_FAIL']:>9}{r['DILUTION_FAIL']:>8}"
              f"{line['recovered_at_containment']:>7}"
              f"{line['mean_best_containment']:>10.2f}"
              f"{line['mean_best_jaccard']:>10.2f}"
              f"{line['mean_ring_size']:>7.1f}{line['mean_cand_size']:>7.1f}")

    print(f"\nfailure sub-reasons for CONTAINMENT_FAIL "
          f"(why expansion stopped short):")
    print(f"{'typology':<16}{'node_cap':>10}{'hub_guard':>11}{'out_of_reach':>14}"
          f"{'hop_limit':>11}")
    for line in out_rows:
        s = line["containment_sub_reasons"]
        print(f"{line['typology']:<16}{s['node_cap']:>10}{s['hub_guard']:>11}"
              f"{s['out_of_reach']:>14}{s['hop_limit']:>11}")

    out = {
        "config": {"hops": HOPS, "max_nodes": MAX_NODES,
                   "max_degree": MAX_DEGREE,
                   "hit_share": HIT_SHARE, "min_jaccard": MIN_JACCARD},
        "cycles": runs, "seeded_rings_analysed": len(best_by_ring),
        "by_typology": out_rows,
    }
    (ROOT / "data" / f"build_diagnosis_h{HOPS}_d{MAX_DEGREE}.json").write_text(json.dumps(out, indent=2))
    print("\nwritten to data/build_diagnosis.json")


if __name__ == "__main__":
    main()
