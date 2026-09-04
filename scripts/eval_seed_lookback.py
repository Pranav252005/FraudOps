"""P0: how much does the seed source's one-hour window cost?

Pre-registered in `prereg/seed_lookback.md`. Read that first — the arms, the
expectations and five kill criteria were fixed before `seed_lookback_ticks`
existed, and the ranked@50 range is deliberately low because S1 produced
"+14 built, +0 ranked" from the same shape of intervention this morning.

Two arms as shipped in this file, ONE replay, generators over one shared
graph. `observe()` is called on EVERY tick for every generator, so each arm
sees the same history and the comparison is paired exactly:

    lb1     the current tick -- shipped; must reproduce data/eval_phase2.json
    lb6     last 6 ticks -- time-lossless, since cycles are 6 apart

Lookback 72 was excluded by the pre-registration on a measured saturation
argument (120,502 seeds against 117,159 for lookback 24 -- 2.9% more for
another 48 hours). Lookback 24 was excluded AFTER a one-cycle cost run, which
is a post-hoc scope change and is declared as such next to `LOOKBACKS` below.

    python scripts/eval_seed_lookback.py
    python scripts/eval_seed_lookback.py --limit 4
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
from sentinel.eval.bootstrap import paired_bootstrap_delta
from sentinel.eval.funnel import FunnelTracker, is_hit
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

DATASET = _active_dataset()
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "eval_seed_lookback.json"

# DECLARED DEVIATION from prereg/seed_lookback.md, which named arms {1, 6, 24}.
# A one-cycle cost run (data/_cost_lb.log, cycle 36) measured:
#
#   arm    seeds     candidates   seconds   x shipped   rings seeded
#   lb1    15,854    15,494          17       1.00        24
#   lb6    68,235    65,283         150       8.93        32
#   lb24  117,159   109,300         296      17.62        33
#
# lb24 costs 2x lb6 and reached ONE more ring in that cycle. The full
# three-arm sweep projects to ~4 hours; dropping lb24 brings it to ~95
# minutes. This is the same saturation argument the pre-registration used to
# drop lb72, applied to one more arm on data seen after the fact -- so it is a
# POST-HOC scope change and is declared as one rather than presented as the
# original plan. lb24 is reported as measured-but-not-swept.
LOOKBACKS = (1, 6)
SHIPPED = 1
KS = (10, 20, 50)
EVERY = 6
MIN_RING_NODES = 3
RANK_K = 50
BASELINES = ("score", "size", "degree", "random")

# prereg kill criteria
MIN_NEWLY_SEEDED = 10      # #1
MIN_RANKED_GAIN = 3        # #2
MAX_ABS_RHO = 0.5          # #4
MAX_COST_RATIO = 10.0      # #5


def arm(lb):
    return f"lb{lb}"


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def spearman(xs, ys):
    """Rank correlation, with average ranks for ties.

    Hand-rolled rather than imported so the diagnostic has no dependency and
    its tie handling is visible: candidate sizes are small integers and ties
    are the common case, so a naive rank would bias this badly.
    """
    n = len(xs)
    if n < 3:
        return 0.0

    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        out = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    stream = Stream(active_stream_dir(ROOT))
    registry = AccountRegistry.load(DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)

    gens = {arm(lb): CandidateGenerator(graph, registry=registry,
                                        node_key=stream.key,
                                        seed_lookback_ticks=lb)
            for lb in LOOKBACKS}
    rngs = {a: random.Random(7) for a in gens}
    trackers = {a: FunnelTracker(rank_k=RANK_K) for a in gens}
    rows = {a: [] for a in gens}
    secs = {a: 0.0 for a in gens}
    rho_pairs = {a: [] for a in gens}

    runs = 0
    t0 = time.time()
    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        # EVERY tick, for EVERY arm. Calling this only on cycle ticks would
        # make the lookback count cycles and silently mean six times longer.
        for g in gens.values():
            g.observe(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue
        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue

        any_c = False
        for a, gen in gens.items():
            t = time.time()
            cands = gen.generate(b)
            secs[a] += time.time() - t
            if not cands:
                continue
            any_c = True
            trackers[a].observe_cycle(
                rings, lambda r: stream.ring_typology(r) or "UNKNOWN",
                seed_nodes=gen.last_seeds, candidates=cands)
            rho_pairs[a] += [(c.score, c.size) for c in cands[:200]]

            orders = {
                "score": cands,
                "random": rngs[a].sample(cands, len(cands)),
                "degree": sorted(cands, key=lambda c: (-c.features.max_fan, c.key)),
                "size": sorted(cands, key=lambda c: (-c.size, c.key)),
            }
            row = {"run": runs + 1, "t": int(graph.now),
                   "n_candidates": len(cands), "n_seeds": len(gen.last_seeds)}
            for name, o in orders.items():
                for k in KS:
                    top = o[:k]
                    row[f"{name}_hit_{k}"] = sum(
                        1 for c in top
                        if any(is_hit(set(c.nodes), mem) for mem in rings.values()))
                    row[f"{name}_n_{k}"] = len(top)
            rows[a].append(row)

        if any_c:
            runs += 1
            sh = rows[arm(SHIPPED)]
            p10 = (sum(r["score_hit_10"] for r in sh)
                   / max(1, sum(r["score_n_10"] for r in sh)))
            print(f"  run {runs:>3} t={graph.now//1440}d "
                  + " ".join(f"{a}={rows[a][-1]['n_seeds']:,}" for a in gens)
                  + f" lb1 p@10={p10:.3f} ({time.time()-t0:.0f}s)", flush=True)
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
    for a in gens:
        t = trackers[a]
        xs = [s for s, _ in rho_pairs[a]]
        ys = [float(n) for _, n in rho_pairs[a]]
        arms_out[a] = {
            "lookback_ticks": int(a[2:]),
            "funnel_totals": t.totals(),
            "funnel_by_typology": t.table(),
            "stats": dict(gens[a].stats),
            "seconds": secs[a],
            "mean_seeds": sum(r["n_seeds"] for r in rows[a]) / max(1, len(rows[a])),
            "mean_candidates": sum(r["n_candidates"] for r in rows[a]) / max(1, len(rows[a])),
            "spearman_score_size": spearman(xs, ys),
            "precision": {n: {str(k): rate(rows[a], n, k) for k in KS}
                          for n in BASELINES},
            "score_minus_size": {
                str(k): paired_bootstrap_delta(
                    rows[a],
                    lambda rs, k=k: rate(rs, "size", k),
                    lambda rs, k=k: rate(rs, "score", k))
                for k in KS},
        }

    paired = {}
    base = arm(SHIPPED)
    for a in gens:
        if a == base:
            continue
        merged = [{"a": x, "b": y} for x, y in zip(rows[base], rows[a])]
        paired[f"{a}_minus_{base}"] = {
            str(k): paired_bootstrap_delta(merged, stat("a", k), stat("b", k))
            for k in KS}

    out = {"runs": runs, "lookbacks": list(LOOKBACKS),
           "clustering": "cycle_clustered_bootstrap",
           "arms": arms_out, "paired": paired, "cycle_rows": rows}
    args.out.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n{runs} cycles, {time.time()-t0:.0f}s -> {args.out}")

    print(f"\n{'arm':<7}{'seeds':>10}{'cands':>9}{'secs':>8}{'x cost':>8}"
          f"{'seeded':>8}{'built':>7}{'ranked':>8}{'p@10':>9}{'p@20':>9}{'p@50':>9}")
    base_secs = arms_out[base]["seconds"]
    for a in gens:
        o = arms_out[a]
        f = o["funnel_totals"]
        print(f"{a:<7}{o['mean_seeds']:>10,.0f}{o['mean_candidates']:>9,.0f}"
              f"{o['seconds']:>8.0f}{o['seconds']/max(1e-9,base_secs):>8.2f}"
              f"{f['seeded']:>8}{f['built']:>7}{f['ranked']:>8}"
              + "".join(f"{o['precision']['score'][str(k)]:>9.4f}" for k in KS))

    print(f"\n{'paired vs lb1':<18}" + "".join(f"{'k='+str(k):>26}" for k in KS))
    for name, d in paired.items():
        print(f"{name:<18}" + "".join(
            f"{d[str(k)]['point']:>+9.4f} [{d[str(k)]['lo']:+.3f},{d[str(k)]['hi']:+.3f}]"
            for k in KS))

    print("\n=== kill criteria ===")
    seeded = {a: arms_out[a]["funnel_totals"]["seeded"] for a in gens}
    gain6 = seeded[arm(6)] - seeded[base]
    print(f"1. newly seeded rings, lb6 - lb1 = {gain6}  (floor {MIN_NEWLY_SEEDED})"
          f"  -> {'FIRED -- debug before reading p@k' if gain6 < MIN_NEWLY_SEEDED else 'not fired'}")
    ranked = {a: arms_out[a]["funnel_totals"]["ranked"] for a in gens}
    best = max(ranked[a] - ranked[base] for a in gens if a != base)
    print(f"2. ranked@50 {ranked}  best gain {best:+d} (need >= {MIN_RANKED_GAIN})"
          f"  -> {'FIRED -- report as +N built, +0 ranked, with the S1 precedent' if best < MIN_RANKED_GAIN else 'not fired'}")
    print("3. score - size, every k:")
    for a in gens:
        bad = [k for k in KS
               if not arms_out[a]["score_minus_size"][str(k)]["excludes_zero"]]
        cells = "  ".join(
            f"k={k}:{arms_out[a]['score_minus_size'][str(k)]['point']:+.4f}"
            f"{'*' if k in bad else ' '}" for k in KS)
        print(f"   {a:<6}{cells}   -> "
              f"{'FIRED at k=' + str(bad) if bad else 'clear at every k'}")
    print("4. spearman rho(score, size):")
    for a in gens:
        r = arms_out[a]["spearman_score_size"]
        print(f"   {a:<6}{r:+.4f}  -> "
              f"{'FIRED (size-confounded)' if abs(r) > MAX_ABS_RHO else 'ok'}")
    c6 = arms_out[arm(6)]["seconds"] / max(1e-9, base_secs)
    print(f"5. lb6 cost ratio {c6:.2f}x (cap {MAX_COST_RATIO}x)"
          f"  -> {'FIRED -- re-scope' if c6 > MAX_COST_RATIO else 'not fired'}")


if __name__ == "__main__":
    main()
