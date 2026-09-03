"""Timed, output-fingerprinted candidate-generation runs.

Exists to make the "exact" claim in docs/ARCHITECTURE_UPLIFT.md section 5.2
falsifiable rather than assumed. Every efficiency change in that tier is
supposed to leave every metric byte-identical; this script produces, for a
fixed set of generation cycles:

  * wall time per cycle and in total, and the generator's own stage counters;
  * a full fingerprint of the output -- every candidate's canonical key, score,
    per-term contributions and every field of its `Features` -- serialised with
    `repr` on floats so the comparison is bit-exact, not rounded.

Run it at the commit before a change and at the commit after, then diff the two
JSON files. Any difference in the `fingerprint` section means the change was
not exact and must be reverted, regardless of what p@k does.

    python scripts/bench_cycle.py --out data/bench_before.json
    python scripts/bench_cycle.py --out data/bench_after.json
    python scripts/bench_cycle.py --compare data/bench_before.json data/bench_after.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.config import PRUNE_STRATEGY, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

ROOT = Path(__file__).resolve().parent.parent
EVERY = 6


def fingerprint(cands) -> list:
    """Bit-exact record of everything a candidate carries downstream.

    Floats go through `repr`, which round-trips exactly on CPython, so a
    one-ulp difference in a feature shows up as a string difference rather than
    being hidden by JSON's float formatting.
    """
    out = []
    for c in cands:
        feats = {k: (repr(v) if isinstance(v, float) else v)
                 for k, v in c.features.to_dict().items()}
        contrib = {k: repr(v) for k, v in sorted(c.contrib.items())}
        out.append({
            "key": c.key,
            "seed": c.seed,
            "score": repr(c.score),
            "size": c.size,
            "absorbed": c.absorbed,
            "absorbed_seeds": sorted(c.absorbed_seeds),
            "features": feats,
            "contrib": contrib,
        })
    return out


def run(n_cycles: int, warm_ticks: int) -> dict:
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(
        DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    cycles = []
    ingest_s = 0.0
    done = 0
    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=None)):
        t0 = time.perf_counter()
        graph.add_batch(b)
        ingest_s += time.perf_counter() - t0
        if i % EVERY or graph.now < warm_ticks * TICK_MINUTES:
            continue

        t0 = time.perf_counter()
        cands = gen.generate(b)
        elapsed = time.perf_counter() - t0

        cycles.append({
            "tick": i,
            "now": graph.now,
            "seconds": elapsed,
            "n_candidates": len(cands),
            "window_pairs": len(graph.pairs),
            "fingerprint": fingerprint(cands),
        })
        done += 1
        print(f"  tick {i:>4} cands={len(cands):>6,} {elapsed:8.2f}s", flush=True)
        if done >= n_cycles:
            break

    total = sum(c["seconds"] for c in cycles)
    print(f"\n{len(cycles)} cycles, generate total {total:.2f}s, "
          f"ingest {ingest_s:.2f}s")
    return {
        "prune_strategy": PRUNE_STRATEGY,
        "every_ticks": EVERY,
        "warm_ticks": warm_ticks,
        "ingest_seconds": ingest_s,
        "generate_seconds_total": total,
        "generator_stats": dict(gen.stats),
        "cycles": cycles,
    }


def compare(a_path: Path, b_path: Path) -> int:
    a = json.loads(a_path.read_text())
    b = json.loads(b_path.read_text())

    print(f"before: {a['generate_seconds_total']:.2f}s   "
          f"after: {b['generate_seconds_total']:.2f}s   "
          f"speedup {a['generate_seconds_total'] / b['generate_seconds_total']:.2f}x")
    print(f"stage counters equal: {a['generator_stats'] == b['generator_stats']}")
    if a["generator_stats"] != b["generator_stats"]:
        print(f"  before {a['generator_stats']}")
        print(f"  after  {b['generator_stats']}")

    if len(a["cycles"]) != len(b["cycles"]):
        print(f"CYCLE COUNT DIFFERS: {len(a['cycles'])} vs {len(b['cycles'])}")
        return 1

    n_diff = 0
    for ca, cb in zip(a["cycles"], b["cycles"]):
        assert ca["tick"] == cb["tick"]
        fa, fb = ca["fingerprint"], cb["fingerprint"]
        if len(fa) != len(fb):
            print(f"tick {ca['tick']}: candidate COUNT differs "
                  f"{len(fa)} vs {len(fb)}")
            n_diff += 1
            continue
        for ra, rb in zip(fa, fb):
            if ra == rb:
                continue
            n_diff += 1
            if n_diff <= 10:
                keys = [k for k in ra if ra[k] != rb.get(k)]
                print(f"tick {ca['tick']} key={ra['key'][:40]}: differs in {keys}")
                for k in keys:
                    if k in ("features", "contrib"):
                        sub = [f for f in ra[k] if ra[k][f] != rb[k].get(f)]
                        for f in sub:
                            print(f"    {k}.{f}: {ra[k][f]} -> {rb[k][f]}")
                    else:
                        print(f"    {k}: {ra[k]} -> {rb[k]}")
        # ordering check: the queue is what ships, so order matters as much
        # as content
        if [r["key"] for r in fa] != [r["key"] for r in fb]:
            print(f"tick {ca['tick']}: RANK ORDER differs")
            n_diff += 1

    if n_diff:
        print(f"\nNOT byte-identical: {n_diff} differing records")
        return 1
    print("\nbyte-identical: every candidate key, rank, score, contribution "
          "and feature field matches exactly")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--cycles", type=int, default=5)
    ap.add_argument("--warm-ticks", type=int, default=36)
    ap.add_argument("--compare", nargs=2, type=Path)
    args = ap.parse_args()

    if args.compare:
        raise SystemExit(compare(*args.compare))
    if not args.out:
        raise SystemExit("need --out or --compare")
    result = run(args.cycles, args.warm_ticks)
    args.out.write_text(json.dumps(result, indent=1))
    print(f"written to {args.out}")


if __name__ == "__main__":
    main()
