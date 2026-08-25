"""Phase 2 evaluation: ring-level precision@k, recall, and honest baselines.

A candidate counts as a hit on a ground-truth ring when it contains at least
HIT_SHARE of that ring's accounts visible in the current window. Containment
rather than exact match, because an analyst working a case that holds 7 of a
9-account ring has found the ring -- and the case file lets them drop the two
members that do not belong.

Three baselines run alongside the score. A precision@20 with nothing to compare
it against is not a result.
"""
from __future__ import annotations

import json
import random
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

ROOT = Path(__file__).resolve().parent.parent
HIT_SHARE = 0.5
# Containment alone rewards bulk: a 158-node candidate trivially contains half
# of a 4-account ring, which is why the "size" baseline initially tied the
# score. A hit must also be a substantial share of the candidate, so Jaccard is
# the primary criterion and containment is reported alongside it.
MIN_JACCARD = 0.3
KS = (10, 20, 50, 100)
EVERY = 6          # generate candidates every N ticks (6h at 60min ticks)
MIN_RING_NODES = 3


def active_rings(stream, t_lo, t_hi):
    """Ground-truth rings with edges inside the current window."""
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def hits(nodes, rings, strict=True):
    """Which ground-truth rings this candidate covers.

    `strict` applies the Jaccard floor. Without it the metric measures candidate
    size as much as candidate quality.
    """
    out = []
    for r, acc in rings.items():
        inter = len(nodes & acc)
        if not inter:
            continue
        if inter / len(acc) < HIT_SHARE:
            continue
        if strict and inter / len(nodes | acc) < MIN_JACCARD:
            continue
        out.append(r)
    return out


def main() -> None:
    rng = random.Random(7)
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(ROOT / "data" / "amlworld" / "HI-Small_accounts.csv")
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    tally = {name: {k: [0, 0] for k in KS} for name in
             ("score", "random", "degree", "size")}
    loose = {name: {k: [0, 0] for k in KS} for name in tally}
    ring_found = {name: set() for name in tally}
    ring_seen: set[int] = set()
    typ_seen: defaultdict = defaultdict(set)
    typ_found: defaultdict = defaultdict(set)
    runs = 0
    t0 = time.time()

    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue

        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue
        for r in rings:
            ring_seen.add(r)
            typ_seen[stream.ring_typology(r)].add(r)

        cands = gen.generate(b)
        if not cands:
            continue
        runs += 1

        orders = {
            "score": cands,
            "random": rng.sample(cands, len(cands)),
            "degree": sorted(cands, key=lambda c: -c.features.max_fan),
            "size": sorted(cands, key=lambda c: -c.size),
        }
        for name, ordered in orders.items():
            for k in KS:
                top = ordered[:k]
                hit = lhit = 0
                for c in top:
                    ns = set(c.nodes)
                    h = hits(ns, rings, strict=True)
                    if h:
                        hit += 1
                        if name == "score":
                            for r in h:
                                typ_found[stream.ring_typology(r)].add(r)
                        ring_found[name].update(h)
                    if hits(ns, rings, strict=False):
                        lhit += 1
                tally[name][k][0] += hit
                tally[name][k][1] += len(top)
                loose[name][k][0] += lhit
                loose[name][k][1] += len(top)

        print(f"  run {runs:>3} t={graph.now//1440}d{(graph.now%1440)//60:02d}h "
              f"cands={len(cands):>6,} rings={len(rings):>4} "
              f"p@20={tally['score'][20][0]/max(1,tally['score'][20][1]):.3f} "
              f"({time.time()-t0:.0f}s)", flush=True)

    print(f"\n{runs} generation runs over {EVAL_END//1440} days "
          f"in {time.time()-t0:.0f}s")
    print(f"ground-truth rings seen (>={MIN_RING_NODES} accounts): {len(ring_seen)}")

    print(f"\n{'ranking':<10}" + "".join(f"{'p@'+str(k):>10}" for k in KS)
          + f"{'rings found':>13}{'ring recall':>13}")
    for name in ("score", "degree", "size", "random"):
        row = f"{name:<10}"
        for k in KS:
            hit, tot = tally[name][k]
            row += f"{hit/max(1,tot):>10.3f}"
        rec = len(ring_found[name]) / max(1, len(ring_seen))
        row += f"{len(ring_found[name]):>13}{rec:>12.1%}"
        print(row)

    print(f"\n{'typology':<18}{'seen':>7}{'found':>7}{'recall':>9}")
    for typ in sorted(typ_seen):
        s, f = len(typ_seen[typ]), len(typ_found[typ])
        print(f"{typ:<18}{s:>7}{f:>7}{f/max(1,s):>8.0%}")

    out = {
        "runs": runs, "hit_share": HIT_SHARE, "every_ticks": EVERY,
        "rings_seen": len(ring_seen),
        "min_jaccard": MIN_JACCARD,
        "precision": {n: {k: tally[n][k][0] / max(1, tally[n][k][1]) for k in KS}
                      for n in tally},
        "precision_loose": {n: {k: loose[n][k][0] / max(1, loose[n][k][1])
                                for k in KS} for n in loose},
        "ring_recall": {n: len(ring_found[n]) / max(1, len(ring_seen))
                        for n in ring_found},
        "by_typology": {t: {"seen": len(typ_seen[t]), "found": len(typ_found[t])}
                        for t in typ_seen},
        "generator_stats": gen.stats,
    }
    (ROOT / "data" / "eval_phase2.json").write_text(json.dumps(out, indent=2))
    print("\nwritten to data/eval_phase2.json")


if __name__ == "__main__":
    main()
