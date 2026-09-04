"""B3: what a score-free suppression key costs.

Pre-registered in `prereg/suppression_key.md`. **The experiment's actual claim
— that a score-free pool is invariant to the blend weights and the shipped one
is not — is tested in `tests/test_suppression_key.py`, not here.** That is a
property, it needs no replay, and it is checked first. This script measures the
*price* of the property.

Four orderings, ONE generation per cycle. Suppression runs after scoring and
only decides which member of an overlapping group survives, so every arm is
derived from the same unsuppressed pool and the comparison is paired exactly:

    gen.generate(b, merge_threshold=None)   -> the unsuppressed pool, once
    suppress(pool, ordering=...)            -> four arms

The final ordering handed to the queue is `-score` in every arm, matching
`CandidateGenerator.generate`, which sorts by score *after* suppression. The
key decides which candidates exist; it does not decide how they are presented.

    python scripts/eval_suppression_key.py
    python scripts/eval_suppression_key.py --limit 4
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.data.datasets import active_stream_dir
from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.data.datasets import active as _active_dataset
from sentinel.detect.candidates import CandidateGenerator
from sentinel.detect.merge import (DEFAULT_THRESHOLD, SUPPRESS_ORDERINGS,
                                   SUPPRESS_SCORE, suppress)
from sentinel.eval.bootstrap import paired_bootstrap_delta
from sentinel.eval.funnel import FunnelTracker, is_hit
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

DATASET = _active_dataset()
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "eval_suppression_key.json"

ARMS = SUPPRESS_ORDERINGS
KS = (10, 20, 50)
EVERY = 6
MIN_RING_NODES = 3
RANK_K = 50
BASELINES = ("score", "size", "degree", "random")

# prereg kill criterion 3: interpretability bought below this is too expensive.
RANKED_FLOOR = 47


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    stream = Stream(active_stream_dir(ROOT))
    registry = AccountRegistry.load(DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    rngs = {arm: random.Random(7) for arm in ARMS}
    trackers = {arm: FunnelTracker(rank_k=RANK_K) for arm in ARMS}
    rows = {arm: [] for arm in ARMS}
    pools = {arm: [] for arm in ARMS}

    runs = 0
    t0 = time.time()
    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue
        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue

        # One generation, unsuppressed. Every arm suppresses this same pool.
        raw = gen.generate(b, merge_threshold=None)
        if not raw:
            continue
        runs += 1

        for arm in ARMS:
            # `suppress` accumulates onto `absorbed`/`absorbed_seeds`, so the
            # shared candidate objects are reset between arms. Without this the
            # second arm would inherit the first arm's corroboration counts --
            # a plausible wrong answer rather than an error, which is the shape
            # this project keeps a catalogue for.
            for c in raw:
                c.absorbed = 0
                c.absorbed_seeds = []
            kept = suppress(raw, threshold=DEFAULT_THRESHOLD, ordering=arm)
            ordered = sorted(kept, key=lambda c: -c.score)
            pools[arm].append(len(ordered))

            trackers[arm].observe_cycle(
                rings, lambda r: stream.ring_typology(r) or "UNKNOWN",
                seed_nodes=gen.last_seeds, candidates=ordered)
            orders = {
                "score": ordered,
                "random": rngs[arm].sample(ordered, len(ordered)),
                "degree": sorted(ordered, key=lambda c: (-c.features.max_fan, c.key)),
                "size": sorted(ordered, key=lambda c: (-c.size, c.key)),
            }
            row = {"run": runs, "t": int(graph.now), "n_pool": len(ordered)}
            for name, o in orders.items():
                for k in KS:
                    top = o[:k]
                    row[f"{name}_hit_{k}"] = sum(
                        1 for c in top
                        if any(is_hit(set(c.nodes), mem) for mem in rings.values()))
                    row[f"{name}_n_{k}"] = len(top)
            rows[arm].append(row)

        print(f"  run {runs:>3} t={graph.now//1440}d raw={len(raw):>6,} "
              + " ".join(f"{a}={pools[a][-1]:,}" for a in ARMS)
              + f" ({time.time()-t0:.0f}s)", flush=True)
        if args.limit and runs >= args.limit:
            break

    def rate(rs, name, k):
        num = sum(r[f"{name}_hit_{k}"] for r in rs)
        den = sum(r[f"{name}_n_{k}"] for r in rs)
        return num / den if den else 0.0

    def stat(side, k):
        def f(rs):
            num = sum(r[side][f"score_hit_{k}"] for r in rs)
            den = sum(r[side][f"score_n_{k}"] for r in rs)
            return num / den if den else 0.0
        return f

    arms_out = {}
    for arm in ARMS:
        t = trackers[arm]
        arms_out[arm] = {
            "funnel_totals": t.totals(),
            "funnel_by_typology": t.table(),
            "mean_pool": sum(pools[arm]) / max(1, len(pools[arm])),
            "precision": {n: {str(k): rate(rows[arm], n, k) for k in KS}
                          for n in BASELINES},
            "score_minus_size": {
                str(k): paired_bootstrap_delta(
                    rows[arm],
                    lambda rs, k=k: rate(rs, "size", k),
                    lambda rs, k=k: rate(rs, "score", k))
                for k in KS},
        }

    paired = {}
    for arm in ARMS:
        if arm == SUPPRESS_SCORE:
            continue
        merged = [{"a": x, "b": y} for x, y in zip(rows[SUPPRESS_SCORE], rows[arm])]
        paired[f"{arm}_minus_score"] = {
            str(k): paired_bootstrap_delta(merged, stat("a", k), stat("b", k))
            for k in KS}

    out = {
        "runs": runs, "clustering": "cycle_clustered_bootstrap",
        "ranked_floor": RANKED_FLOOR,
        "arms": arms_out, "paired": paired, "cycle_rows": rows,
    }
    args.out.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n{runs} cycles, {time.time()-t0:.0f}s -> {args.out}")

    print(f"\n{'ordering':<12}{'pool':>9}{'built':>7}{'ranked':>8}"
          f"{'p@10':>9}{'p@20':>9}{'p@50':>9}")
    for arm in ARMS:
        a = arms_out[arm]
        f = a["funnel_totals"]
        print(f"{arm:<12}{a['mean_pool']:>9,.0f}{f['built']:>7}{f['ranked']:>8}"
              + "".join(f"{a['precision']['score'][str(k)]:>9.4f}" for k in KS))

    print(f"\n{'paired delta vs score':<24}" + "".join(f"{'k='+str(k):>26}" for k in KS))
    for name, d in paired.items():
        print(f"{name:<24}" + "".join(
            f"{d[str(k)]['point']:>+9.4f} [{d[str(k)]['lo']:+.3f},{d[str(k)]['hi']:+.3f}]"
            for k in KS))

    # --------------------------------------------------------- kill criteria
    print("\n=== kill criteria ===")
    print("1. invariance property -> tests/test_suppression_key.py "
          "(checked there; this run assumes it passed)")

    # Criterion 2, quantified over EVERY reported k -- the defect in B1's
    # pre-registration, applied here rather than merely recorded.
    print("2. score - size, at every k:")
    fired2 = {}
    for arm in ARMS:
        bad = [k for k in KS
               if not arms_out[arm]["score_minus_size"][str(k)]["excludes_zero"]]
        fired2[arm] = bad
        cells = "  ".join(
            f"k={k}:{arms_out[arm]['score_minus_size'][str(k)]['point']:+.4f}"
            f"{'*' if k in bad else ' '}" for k in KS)
        print(f"   {arm:<12}{cells}   -> "
              f"{'FIRED at k=' + str(bad) if bad else 'clear at every k'}")

    ranked = {a: arms_out[a]["funnel_totals"]["ranked"] for a in ARMS}
    free = [a for a in ARMS if a != SUPPRESS_SCORE]
    fired3 = all(ranked[a] < RANKED_FLOOR for a in free)
    print(f"3. ranked@50 {ranked}  floor {RANKED_FLOOR}"
          f"  -> {'FIRED (every score-free arm below floor)' if fired3 else 'not fired'}")

    base_pool = arms_out[SUPPRESS_SCORE]["mean_pool"]
    fired4 = [a for a in ARMS if arms_out[a]["mean_pool"] > 2 * base_pool]
    print(f"4. pool sizes {{" + ", ".join(f'{a}: {arms_out[a]["mean_pool"]:,.0f}' for a in ARMS)
          + f"}}  -> {'FIRED ' + str(fired4) if fired4 else 'not fired'}")


if __name__ == "__main__":
    main()
