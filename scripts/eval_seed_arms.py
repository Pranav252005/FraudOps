"""S1/S2: four seed arms, one replay, equal budget.

Pre-registered in `prereg/seed_predicate.md`. Read that first: it records that
the premise the queue ranked this experiment on was **wrong** (seeding is the
smallest of the three funnel losses, not the largest), what the corrected
ceiling is, and four kill criteria fixed before this file existed.

Arms, all seeded from the same graph state at every cycle so every comparison
is paired:

    passthrough           shipped
    passthrough+gargaml   S1  -- + top-B by node_smurf_score
    passthrough+degree    S2  -- + top-B by width alone (the control)
    passthrough+random    the null -- + B at random

Every arm spends the same B. That is what makes a difference between arms a
difference in criterion rather than in spend, and it is the review's own kill
rule for S1.

KILL CRITERION 1 IS CHECKED FIRST AND CAN STOP THE RUN. Before any arm's p@k
is read, the unseeded rings are decomposed into "no member was ever touched in
a tick while the ring was active" -- which no seed rule drawing from `touched`
can reach, S1 included -- and "touched but never pass-through", which is S1's
actual addressable set. If the second group is smaller than 5 rings, the
ceiling is below the noise floor and the arms are not worth reading.

    python scripts/eval_seed_arms.py
    python scripts/eval_seed_arms.py --limit 4      # smoke test
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.data.datasets import active as _active_dataset
from sentinel.detect import candidates as C
from sentinel.eval.bootstrap import paired_bootstrap_delta, ratio_of_sums
from sentinel.eval.funnel import FunnelTracker, is_hit
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

DATASET = _active_dataset()
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "eval_seed_arms.json"

ARMS = (C.SEED_PASSTHROUGH, C.SEED_GARGAML, C.SEED_DEGREE_BURST, C.SEED_RANDOM)
SHIPPED = C.SEED_PASSTHROUGH
KS = (10, 20, 50)
EVERY = 6
MIN_RING_NODES = 3
RANK_K = 50
BASELINES = ("score", "size", "degree", "random")

# prereg kill criterion 1: below this many addressable rings, the arms are not
# worth reading.
MIN_ADDRESSABLE = 5


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--budget", type=float, default=C.SEED_BUDGET)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)

    gens = {arm: C.CandidateGenerator(
                graph, registry=registry, node_key=stream.key,
                seed_strategy=arm, seed_budget=args.budget)
            for arm in ARMS}
    rngs = {arm: random.Random(7) for arm in ARMS}
    trackers = {arm: FunnelTracker(rank_k=RANK_K) for arm in ARMS}
    rows = {arm: [] for arm in ARMS}

    # The ceiling decomposition (kill criterion 1).
    ring_reachable: set[int] = set()
    ring_touched: set[int] = set()        # some member appeared in a batch
    ring_passthrough: set[int] = set()    # some member was pass-through
    ring_typ: dict[int, str] = {}

    runs = 0
    t0 = time.time()
    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue
        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue

        touched: set[int] = set()
        if len(b):
            touched.update(int(x) for x in b.src)
            touched.update(int(x) for x in b.dst)
        base = {n for n in touched
                if graph.out_adj.get(n) and graph.in_adj.get(n)}

        for r, members in rings.items():
            ring_reachable.add(r)
            ring_typ[r] = stream.ring_typology(r) or "UNKNOWN"
            if members & touched:
                ring_touched.add(r)
            if members & base:
                ring_passthrough.add(r)

        any_cands = False
        for arm in ARMS:
            gen = gens[arm]
            before_extra = gen.stats["seeds_extra"]
            cands = gen.generate(b)
            if not cands:
                continue
            any_cands = True
            trackers[arm].observe_cycle(
                rings, lambda r: stream.ring_typology(r) or "UNKNOWN",
                seed_nodes=gen.last_seeds, candidates=cands)

            orders = {
                "score": cands,
                "random": rngs[arm].sample(cands, len(cands)),
                "degree": sorted(cands, key=lambda c: (-c.features.max_fan, c.key)),
                "size": sorted(cands, key=lambda c: (-c.size, c.key)),
            }
            row = {"run": runs + 1, "t": int(graph.now),
                   "n_candidates": len(cands),
                   "extra_this_cycle": gen.stats["seeds_extra"] - before_extra}
            for name, ordered in orders.items():
                for k in KS:
                    top = ordered[:k]
                    hit = sum(1 for c in top
                              if any(is_hit(set(c.nodes), mem)
                                     for mem in rings.values()))
                    row[f"{name}_hit_{k}"] = hit
                    row[f"{name}_n_{k}"] = len(top)
            rows[arm].append(row)

        if any_cands:
            runs += 1
            sh = rows[SHIPPED]
            p10 = (sum(r["score_hit_10"] for r in sh)
                   / max(1, sum(r["score_n_10"] for r in sh)))
            print(f"  run {runs:>3} t={graph.now//1440}d "
                  f"rings={len(rings):>4} shipped p@10={p10:.3f} "
                  f"({time.time()-t0:.0f}s)", flush=True)
        if args.limit and runs >= args.limit:
            break

    # ------------------------------------------------ kill criterion 1 first
    unseeded = ring_reachable - ring_passthrough
    untouched = unseeded - ring_touched
    addressable = unseeded & ring_touched
    print(f"\n=== ceiling decomposition (kill criterion 1) ===")
    print(f"  seed-reachable rings          {len(ring_reachable)}")
    print(f"  seeded by pass-through        {len(ring_passthrough)}")
    print(f"  UNSEEDED                      {len(unseeded)}")
    print(f"    never touched in any cycle  {len(untouched)}  "
          f"<- unreachable by ANY touched-based rule, S1 included")
    print(f"    touched, never pass-through {len(addressable)}  "
          f"<- S1's entire addressable set")
    if addressable:
        by_typ = defaultdict(int)
        for r in addressable:
            by_typ[ring_typ[r]] += 1
        print(f"    addressable by typology     {dict(sorted(by_typ.items()))}")

    def rate(rs, name, k):
        num = sum(r[f"{name}_hit_{k}"] for r in rs)
        den = sum(r[f"{name}_n_{k}"] for r in rs)
        return num / den if den else 0.0

    arms_out = {}
    for arm in ARMS:
        t = trackers[arm]
        arms_out[arm] = {
            "stats": dict(gens[arm].stats),
            "funnel_totals": t.totals(),
            "funnel_by_typology": t.table(),
            "precision": {n: {str(k): rate(rows[arm], n, k) for k in KS}
                          for n in BASELINES},
            "score_minus_size": {
                str(k): paired_bootstrap_delta(
                    rows[arm],
                    ratio_of_sums(f"size_hit_{k}", f"size_n_{k}"),
                    ratio_of_sums(f"score_hit_{k}", f"score_n_{k}"))
                for k in KS},
        }

    # Paired arm-vs-arm deltas. Rows are aligned per cycle by construction.
    paired = {}
    for arm in ARMS:
        if arm == SHIPPED or len(rows[arm]) != len(rows[SHIPPED]):
            continue
        merged = [{"a": a, "b": bb}
                  for a, bb in zip(rows[SHIPPED], rows[arm])]
        paired[f"{arm}_minus_shipped"] = {
            str(k): paired_bootstrap_delta(
                merged,
                lambda rs, k=k: (sum(r["a"][f"score_hit_{k}"] for r in rs)
                                 / max(1, sum(r["a"][f"score_n_{k}"] for r in rs))),
                lambda rs, k=k: (sum(r["b"][f"score_hit_{k}"] for r in rs)
                                 / max(1, sum(r["b"][f"score_n_{k}"] for r in rs))))
            for k in KS}
    # S1 vs S2: the attribution question.
    if len(rows[C.SEED_GARGAML]) == len(rows[C.SEED_DEGREE_BURST]):
        merged = [{"a": a, "b": bb} for a, bb in
                  zip(rows[C.SEED_DEGREE_BURST], rows[C.SEED_GARGAML])]
        paired["gargaml_minus_degree"] = {
            str(k): paired_bootstrap_delta(
                merged,
                lambda rs, k=k: (sum(r["a"][f"score_hit_{k}"] for r in rs)
                                 / max(1, sum(r["a"][f"score_n_{k}"] for r in rs))),
                lambda rs, k=k: (sum(r["b"][f"score_hit_{k}"] for r in rs)
                                 / max(1, sum(r["b"][f"score_n_{k}"] for r in rs))))
            for k in KS}

    out = {
        "runs": runs, "budget": args.budget, "rank_k": RANK_K,
        "clustering": "cycle_clustered_bootstrap",
        "ceiling": {
            "seed_reachable": len(ring_reachable),
            "seeded_passthrough": len(ring_passthrough),
            "unseeded": len(unseeded),
            "unseeded_untouched": len(untouched),
            "unseeded_addressable": len(addressable),
            # Counted, not zipped. An earlier version built this from
            # `{k: v for k, v in sorted((typ, 1) ...)}`, which silently
            # collapses duplicates to 1 each -- the JSON summed to 4 against a
            # true 7 while the console printed the right table. A field that
            # looks well-formed and understates is this project's
            # characteristic defect, so it is a Counter now.
            "addressable_by_typology": dict(sorted(
                Counter(ring_typ[r] for r in addressable).items())),
        },
        "arms": arms_out, "paired": paired,
        "cycle_rows": rows,
    }
    args.out.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n{runs} cycles, {time.time()-t0:.0f}s -> {args.out}")

    if len(addressable) < MIN_ADDRESSABLE:
        print(f"\n*** KILL CRITERION 1 FIRED: only {len(addressable)} rings are "
              f"addressable by ANY new seed rule (floor {MIN_ADDRESSABLE}). ***")
        print("The arms' p@k is not worth reading against a ceiling this small.")

    # ------------------------------------------------------------- the table
    print(f"\n{'arm':<24}{'seeds':>10}{'extra':>8}{'seeded':>8}{'built':>7}"
          f"{'ranked':>8}{'p@10':>9}{'p@20':>9}")
    for arm in ARMS:
        a = arms_out[arm]
        f = a["funnel_totals"]
        print(f"{arm:<24}{a['stats']['seeds']:>10,}{a['stats']['seeds_extra']:>8,}"
              f"{f['seeded']:>8}{f['built']:>7}{f['ranked']:>8}"
              f"{a['precision']['score']['10']:>9.4f}"
              f"{a['precision']['score']['20']:>9.4f}")

    print(f"\n{'paired delta (score p@k)':<32}{'k=10':>26}{'k=20':>26}")
    for name, d in paired.items():
        cells = "".join(
            f"{d[str(k)]['point']:>+9.4f} [{d[str(k)]['lo']:+.3f},{d[str(k)]['hi']:+.3f}]"
            for k in (10, 20))
        print(f"{name:<32}{cells}")

    print("\nre-tie check (score - size, per arm):")
    for arm in ARMS:
        d = arms_out[arm]["score_minus_size"]["10"]
        print(f"  {arm:<24}{d['point']:>+9.4f} [{d['lo']:+.4f},{d['hi']:+.4f}]"
              f"  {'clear' if d['excludes_zero'] else 'INCLUDES ZERO'}")

    spends = {arms_out[a]["stats"]["seeds_extra"] for a in ARMS if a != SHIPPED}
    if len(spends) > 1:
        print(f"\n*** KILL CRITERION 2 FIRED: arms spent different budgets "
              f"{spends}; attribution is void. ***")


if __name__ == "__main__":
    main()
