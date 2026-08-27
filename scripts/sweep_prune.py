"""Which pruning strategy actually helps? Measured, not argued.

Runs every strategy in `sentinel.detect.prune` over the same seeded rings the
build diagnosis used, and reports the two numbers that must move in opposite
directions for a pruner to be worth shipping:

  * mean containment  -- must NOT fall. A pruner that raises Jaccard by
    deleting ring members is worse while looking better.
  * mean Jaccard / BUILT count -- should rise, because the candidate got
    genuinely tighter rather than because the hit floor moved.

Both are reported per typology, because the strategies are expected to trade
against each other by shape (the 2-core in particular should damage FAN,
whose sinks are legitimately degree-1).

Run: python scripts/sweep_prune.py
Writes data/prune_sweep.json
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.config import (EVAL_END, EXPAND_HOPS, EXPAND_MAX_DEGREE,
                             EXPAND_MAX_NODES, TICK_MINUTES, WINDOW_MINUTES)
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.detect.prune import STRATEGIES, prune
from sentinel.eval.funnel import HIT_SHARE, MIN_JACCARD
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

ROOT = Path(__file__).resolve().parent.parent
EVERY = 6
MIN_RING_NODES = 3


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def main() -> None:
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(ROOT / "data" / "amlworld" / "HI-Small_accounts.csv")
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    # strategy -> ring_id -> best attempt
    best: dict[str, dict[int, dict]] = {s: {} for s in STRATEGIES}
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
                continue
            for s in ring_seeds:
                raw = graph.expand(list([s]), hops=EXPAND_HOPS,
                                    max_nodes=EXPAND_MAX_NODES,
                                    max_degree=EXPAND_MAX_DEGREE)
                for strat in STRATEGIES:
                    nodes = prune(raw, s, graph, strat)
                    inter = len(nodes & members)
                    containment = inter / len(members)
                    jaccard = inter / len(nodes | members)
                    prev = best[strat].get(ring_id)
                    if prev is None or (containment, jaccard) > (
                            prev["containment"], prev["jaccard"]):
                        best[strat][ring_id] = {
                            "containment": containment, "jaccard": jaccard,
                            "ring_size": len(members), "cand_size": len(nodes)}
        print(f"  run {runs:>3} rings={len(rings):>4} ({time.time()-t0:.0f}s)",
              flush=True)

    print(f"\n{runs} cycles in {time.time()-t0:.0f}s\n")

    out = {"config": {"hops": EXPAND_HOPS, "max_nodes": EXPAND_MAX_NODES,
                      "max_degree": EXPAND_MAX_DEGREE,
                      "hit_share": HIT_SHARE, "min_jaccard": MIN_JACCARD},
           "cycles": runs, "by_strategy": {}}

    print(f"{'strategy':<16}{'rings':>7}{'BUILT':>7}{'FOUND':>7}"
          f"{'cont':>8}{'jacc':>8}{'cand':>8}")
    for strat in STRATEGIES:
        rows = best[strat]
        n = max(1, len(rows))
        built = sum(1 for r in rows.values()
                    if r["containment"] >= HIT_SHARE and r["jaccard"] >= MIN_JACCARD)
        found = sum(1 for r in rows.values() if r["containment"] >= HIT_SHARE)
        cont = sum(r["containment"] for r in rows.values()) / n
        jacc = sum(r["jaccard"] for r in rows.values()) / n
        cand = sum(r["cand_size"] for r in rows.values()) / n
        print(f"{strat:<16}{len(rows):>7}{built:>7}{found:>7}"
              f"{cont:>8.3f}{jacc:>8.3f}{cand:>8.1f}")

        by_typ = defaultdict(lambda: {"n": 0, "built": 0, "found": 0,
                                       "cont": 0.0, "jacc": 0.0})
        for ring_id, r in rows.items():
            t = by_typ[typ_by_ring.get(ring_id, "UNKNOWN")]
            t["n"] += 1
            t["built"] += int(r["containment"] >= HIT_SHARE
                              and r["jaccard"] >= MIN_JACCARD)
            t["found"] += int(r["containment"] >= HIT_SHARE)
            t["cont"] += r["containment"]
            t["jacc"] += r["jaccard"]
        out["by_strategy"][strat] = {
            "rings": len(rows), "built": built, "found": found,
            "mean_containment": cont, "mean_jaccard": jacc,
            "mean_cand_size": cand,
            "by_typology": {k: {"n": v["n"], "built": v["built"],
                                 "found": v["found"],
                                 "mean_containment": v["cont"] / max(1, v["n"]),
                                 "mean_jaccard": v["jacc"] / max(1, v["n"])}
                             for k, v in by_typ.items()},
        }

    print(f"\nper-typology BUILT by strategy:")
    typs = sorted(set(typ_by_ring.values()))
    header = f"{'typology':<16}" + "".join(f"{s:>16}" for s in STRATEGIES)
    print(header)
    for t in typs:
        row = f"{t:<16}"
        for strat in STRATEGIES:
            d = out["by_strategy"][strat]["by_typology"].get(t)
            row += f"{(d['built'] if d else 0):>6}/{(d['n'] if d else 0):<9}"
        print(row)

    (ROOT / "data" / "prune_sweep.json").write_text(json.dumps(out, indent=2))
    print("\nwritten to data/prune_sweep.json")


if __name__ == "__main__":
    main()
