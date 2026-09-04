"""M1: the `is_hit` threshold sensitivity band.

Pre-registered in `prereg/threshold_band.md`. Read that first -- the grid, the
expectations, the invariant and the three kill criteria were all fixed before
this file existed.

`HIT_SHARE = 0.5` and `MIN_JACCARD = 0.3` decide what counts as finding a ring
and therefore decide every ring-level number this project reports. The
existence of a Jaccard floor is argued for and documented (bug #8: containment
alone let a node-count baseline tie the score). The values are not defended by
a curve. This produces the curve.

WHY ONE REPLAY COVERS NINE CELLS. `is_hit` is an evaluation function. It takes
no part in seeding, expansion, pruning, suppression or scoring, so every cell
scores the *same* candidate pool in the *same* rank order. The cells are paired
by construction rather than by arrangement -- which is what makes this the one
experiment in the queue that `suppress()`'s score-ordered NMS cannot confound.

WHY THE ORDERINGS ARE COPIED FROM eval_phase2 RATHER THAN IMPROVED. The centre
cell must reproduce `data/eval_phase2.json`, or the band is a band around
something other than the headline. That means matching the baseline
tie-breaking and the random baseline's rng consumption exactly, including where
it is less than ideal. Any change to them belongs in that file, not here.

    python scripts/eval_threshold_band.py
    python scripts/eval_threshold_band.py --limit 4     # smoke test
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

from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.data.datasets import active as _active_dataset
from sentinel.detect.candidates import CandidateGenerator
from sentinel.eval.bootstrap import paired_bootstrap_delta, ratio_of_sums
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

DATASET = _active_dataset()
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "eval_threshold_band.json"

# The grid, fixed in the pre-registration. Shipped pair is the centre.
HIT_SHARES = (0.4, 0.5, 0.6)
MIN_JACCARDS = (0.2, 0.3, 0.4)
SHIPPED = (0.5, 0.3)

KS = (10, 20, 50, 100)
EVERY = 6
MIN_RING_NODES = 3
RANKINGS = ("score", "size", "degree", "random")


def cell_id(hs: float, mj: float) -> str:
    return f"hs{hs}_mj{mj}"


def active_rings(stream, t_lo, t_hi):
    """Ground-truth rings with edges inside the current window.

    Byte-for-byte the same rule as `scripts/eval_phase2.py`, deliberately.
    """
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def overlaps(nodes: set[int], rings: dict) -> list[tuple[int, int, int, int]]:
    """(ring_id, |intersection|, |ring|, |candidate|) for every ring touched.

    Computed once per candidate. Every cell in the grid is then a pure
    arithmetic predicate over these four integers, so no cell re-walks the
    node sets and no cell can accidentally see a different candidate.
    """
    out = []
    n_cand = len(nodes)
    for r, acc in rings.items():
        inter = len(nodes & acc)
        if inter:
            out.append((r, inter, len(acc), n_cand))
    return out


def is_hit_cell(inter: int, n_ring: int, n_cand: int,
                hit_share: float, min_jaccard: float) -> bool:
    """`sentinel.eval.funnel.is_hit`, re-expressed over precomputed counts.

    |A u B| = |A| + |B| - |A n B|, so the Jaccard floor needs no set algebra.
    A test asserts this agrees with the real `is_hit` on random node sets --
    a reimplementation that silently disagreed with the shipped metric would
    make this whole band a measurement of a different question.
    """
    if not inter:
        return False
    if inter / n_ring < hit_share:
        return False
    if inter / (n_cand + n_ring - inter) < min_jaccard:
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="stop after N cycles (smoke test only)")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    rng = random.Random(7)
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    cells = [(hs, mj) for hs in HIT_SHARES for mj in MIN_JACCARDS]
    cycle_rows: dict[str, list[dict]] = {cell_id(*c): [] for c in cells}
    ring_found: dict[str, dict[str, set]] = {
        cell_id(*c): {n: set() for n in RANKINGS} for c in cells}
    ring_seen: set[int] = set()
    runs = 0
    t0 = time.time()

    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue

        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue
        ring_seen |= set(rings)

        cands = gen.generate(b)
        if not cands:
            continue
        runs += 1

        # Orderings copied from eval_phase2.py, including the rng consumption
        # pattern, so the centre cell reproduces the stored headline.
        orders = {
            "score": cands,
            "random": rng.sample(cands, len(cands)),
            "degree": sorted(cands, key=lambda c: -c.features.max_fan),
            "size": sorted(cands, key=lambda c: -c.size),
        }

        # Overlaps computed once per (ranking, rank position), then reused by
        # all nine cells.
        top_overlaps = {
            name: [overlaps(set(c.nodes), rings) for c in ordered[:max(KS)]]
            for name, ordered in orders.items()
        }

        rows = {cell_id(*c): {"run": runs, "t": int(graph.now),
                              "n_candidates": len(cands)} for c in cells}
        for hs, mj in cells:
            cid = cell_id(hs, mj)
            row = rows[cid]
            for name in RANKINGS:
                per_cand = top_overlaps[name]
                for k in KS:
                    hit = 0
                    for ov in per_cand[:k]:
                        found = [r for r, inter, nr, nc in ov
                                 if is_hit_cell(inter, nr, nc, hs, mj)]
                        if found:
                            hit += 1
                            ring_found[cid][name].update(found)
                    row[f"{name}_hit_{k}"] = hit
                    row[f"{name}_n_{k}"] = min(k, len(orders[name]))
            cycle_rows[cid].append(row)

        shipped = cycle_rows[cell_id(*SHIPPED)]
        p20 = (sum(r["score_hit_20"] for r in shipped)
               / max(1, sum(r["score_n_20"] for r in shipped)))
        print(f"  run {runs:>3} t={graph.now//1440}d{(graph.now%1440)//60:02d}h "
              f"cands={len(cands):>6,} rings={len(rings):>4} "
              f"shipped p@20={p20:.3f} ({time.time()-t0:.0f}s)", flush=True)

        if args.limit and runs >= args.limit:
            break

    # ---------------------------------------------------------------- report
    def rate(rows, name, k):
        num = sum(r[f"{name}_hit_{k}"] for r in rows)
        den = sum(r[f"{name}_n_{k}"] for r in rows)
        return num / den if den else 0.0

    results = {}
    for hs, mj in cells:
        cid = cell_id(hs, mj)
        rows = cycle_rows[cid]
        entry = {
            "hit_share": hs, "min_jaccard": mj, "is_shipped": (hs, mj) == SHIPPED,
            "precision": {n: {str(k): rate(rows, n, k) for k in KS}
                          for n in RANKINGS},
            "ring_recall": {n: (len(ring_found[cid][n]) / len(ring_seen)
                                if ring_seen else 0.0) for n in RANKINGS},
            "score_minus_size": {
                str(k): paired_bootstrap_delta(
                    rows,
                    ratio_of_sums(f"size_hit_{k}", f"size_n_{k}"),
                    ratio_of_sums(f"score_hit_{k}", f"score_n_{k}"))
                for k in (10, 20, 50)},
        }
        results[cid] = entry

    # ------------------------------------------------- the readability check
    # Pre-registered invariant: tightening either threshold can only remove
    # hits. Checked BEFORE anything is reported, because a violation means the
    # harness is wrong and no number from this run is readable.
    violations = []
    for name in RANKINGS:
        for k in KS:
            for a, hs in enumerate(HIT_SHARES):
                for c, mj in enumerate(MIN_JACCARDS):
                    here = results[cell_id(hs, mj)]["precision"][name][str(k)]
                    if a + 1 < len(HIT_SHARES):
                        nxt = results[cell_id(HIT_SHARES[a + 1], mj)]["precision"][name][str(k)]
                        if nxt > here + 1e-12:
                            violations.append(
                                f"{name}@{k}: hit_share {hs}->{HIT_SHARES[a+1]} "
                                f"raised p@k {here:.4f}->{nxt:.4f}")
                    if c + 1 < len(MIN_JACCARDS):
                        nxt = results[cell_id(hs, MIN_JACCARDS[c + 1])]["precision"][name][str(k)]
                        if nxt > here + 1e-12:
                            violations.append(
                                f"{name}@{k}: min_jaccard {mj}->{MIN_JACCARDS[c+1]} "
                                f"raised p@k {here:.4f}->{nxt:.4f}")

    out = {
        "runs": runs, "every_ticks": EVERY, "ks": list(KS),
        "rings_seen": len(ring_seen),
        "hit_shares": list(HIT_SHARES), "min_jaccards": list(MIN_JACCARDS),
        "shipped": {"hit_share": SHIPPED[0], "min_jaccard": SHIPPED[1]},
        "clustering": "cycle_clustered_bootstrap",
        "monotonicity_violations": violations,
        "cells": results,
        "cycle_rows": cycle_rows,
    }
    args.out.write_text(json.dumps(out, indent=2))

    print(f"\n{runs} cycles, {len(ring_seen)} rings seen, "
          f"{time.time()-t0:.0f}s -> {args.out}")

    if violations:
        print("\n*** KILL CRITERION 1 FIRED: monotonicity violated ***")
        for v in violations[:20]:
            print("   ", v)
        print("The harness is wrong. No number from this run is reportable.")
        raise SystemExit(2)
    print("\nmonotonicity: OK (p@k non-increasing in both thresholds "
          "for every ranking at every k)")

    print(f"\n{'cell':<16}{'p@10':>9}{'size@10':>9}{'d-10':>9}"
          f"{'95% CI':>20}{'p@20':>9}{'recall':>9}")
    for hs, mj in cells:
        e = results[cell_id(hs, mj)]
        d = e["score_minus_size"]["10"]
        star = " *" if e["is_shipped"] else "  "
        flag = "" if d["excludes_zero"] else "   <- includes 0"
        print(f"{hs},{mj}{star:<10}"
              f"{e['precision']['score']['10']:>9.4f}"
              f"{e['precision']['size']['10']:>9.4f}"
              f"{d['point']:>+9.4f}"
              f"  [{d['lo']:+.4f},{d['hi']:+.4f}]"
              f"{e['precision']['score']['20']:>9.4f}"
              f"{e['ring_recall']['score']:>9.4f}{flag}")
    print("  * = shipped thresholds")

    neg = [cell_id(hs, mj) for hs, mj in cells
           if results[cell_id(hs, mj)]["score_minus_size"]["10"]["point"] < 0]
    clear = sum(1 for c in cells
                if results[cell_id(*c)]["score_minus_size"]["10"]["excludes_zero"])
    print(f"\nscore-size at k=10: positive in {len(cells)-len(neg)}/{len(cells)} "
          f"cells, CI-clear in {clear}/{len(cells)}")
    if neg:
        print(f"*** KILL CRITERION 3 FIRED: score loses to size in {neg} ***")
    if not results[cell_id(*SHIPPED)]["score_minus_size"]["10"]["excludes_zero"]:
        print("*** KILL CRITERION 2 FIRED: shipped cell does not exclude zero ***")


if __name__ == "__main__":
    main()
