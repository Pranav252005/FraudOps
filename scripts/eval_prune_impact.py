"""Does pruning actually help, and does it re-tie a baseline?

Runs candidate generation twice per cycle over the same replay -- once with
`PRUNE_STRATEGY=none` (pre-prune baseline) and once with the shipped `leaf2`
strategy -- so every downstream comparison is paired on the same cycles
rather than compared across two separate runs with different sampling noise.

Reports, all with bootstrap CIs (`sentinel/eval/bootstrap.py`, resampled over
generation cycles, matching the project's existing methodology):

  1. score p@k and ring recall, leaf2 vs none (does pruning move the
     headline metric, or is the point estimate move noise).
  2. score vs size baseline delta *under leaf2* (the re-tie check demanded by
     bug #8's history -- pruning changes candidate sizes, which is exactly
     the axis that baseline tied on before).
  3. Per-typology built-stage funnel, none vs leaf2 (containment >= 0.5 and
     jaccard >= 0.3, matching eval_phase2.py's HIT_SHARE/MIN_JACCARD).

Run: python scripts/eval_prune_impact.py
Writes data/prune_impact.json
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.eval.bootstrap import paired_bootstrap_delta, ratio_of_sums, union_recall
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream
from sentinel.data.datasets import active as _active_dataset

#: The AMLworld split in play. Defaults to HI-Small; override with
#: SENTINEL_DATASET. A split whose constants are underived refuses.
DATASET = _active_dataset()

ROOT = Path(__file__).resolve().parent.parent
HIT_SHARE = 0.5
MIN_JACCARD = 0.3
KS = (10, 20, 50, 100)
EVERY = 6
MIN_RING_NODES = 3
STRATS = ("none", "leaf2")


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def hits(nodes, rings, strict=True):
    out = []
    for r, acc in rings.items():
        inter = len(nodes & acc)
        if not inter or inter / len(acc) < HIT_SHARE:
            continue
        if strict and inter / len(nodes | acc) < MIN_JACCARD:
            continue
        out.append(r)
    return out


def main() -> None:
    import random
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gens = {s: CandidateGenerator(graph, registry=registry, node_key=stream.key,
                                   prune_strategy=s) for s in STRATS}
    rngs = {s: random.Random(7) for s in STRATS}

    # per-cycle records, one dict per strategy per cycle
    records = {s: [] for s in STRATS}
    # typology funnel: strat -> typology -> {seeded, built}
    typ_funnel = {s: defaultdict(lambda: {"seeded": 0, "built": 0}) for s in STRATS}
    typ_seen_total = defaultdict(int)

    runs = 0
    t0 = time.time()
    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue
        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue
        runs += 1
        for r in rings:
            typ_seen_total[stream.ring_typology(r)] += 1

        # One expansion per seed, shared by both strategies. Expansion depends
        # only on the seed and the graph -- never on the prune strategy, which
        # is applied to its result -- so this is exact, and it halves the
        # dominant cost of this A/B (docs/ARCHITECTURE_UPLIFT.md 5.2 item 5).
        # `generate` asserts the cache's expansion bounds match the generator's
        # rather than trusting the caller.
        expansion_cache: dict = {}
        for strat in STRATS:
            gen = gens[strat]
            cands = gen.generate(b, expansion_cache=expansion_cache)
            rec = {"k": {}, "found": {}, "seen": set(rings.keys())}
            if not cands:
                for name in ("score", "random", "degree", "size"):
                    for k in KS:
                        rec["k"][(name, k)] = (0, 0)
                    rec["found"][name] = set()
                records[strat].append(rec)
                print(f"  [{strat}] run {runs:>3} 0 cands ({time.time()-t0:.0f}s)",
                      flush=True)
                continue

            orders = {
                "score": cands,
                "random": rngs[strat].sample(cands, len(cands)),
                "degree": sorted(cands, key=lambda c: -c.features.max_fan),
                "size": sorted(cands, key=lambda c: -c.size),
            }
            for name, ordered in orders.items():
                found = set()
                for k in KS:
                    top = ordered[:k]
                    hit = 0
                    for c in top:
                        ns = set(c.nodes)
                        h = hits(ns, rings, strict=True)
                        if h:
                            hit += 1
                            found.update(h)
                    rec["k"][(name, k)] = (hit, len(top))
                rec["found"][name] = found
            records[strat].append(rec)

            # built-stage funnel: did *any* candidate cover this ring?
            ring_built = set()
            for c in cands:
                h = hits(set(c.nodes), rings, strict=True)
                ring_built.update(h)
            for r in rings:
                t = stream.ring_typology(r) or "UNKNOWN"
                typ_funnel[strat][t]["seeded"] += 1
                if r in ring_built:
                    typ_funnel[strat][t]["built"] += 1

            print(f"  [{strat}] run {runs:>3} cands={len(cands):>5} "
                  f"p@20={rec['k'][('score', 20)][0]/max(1, rec['k'][('score', 20)][1]):.3f} "
                  f"({time.time()-t0:.0f}s)", flush=True)

    print(f"\n{runs} cycles in {time.time()-t0:.0f}s")

    def stat_precision(strat, name, k):
        def f(recs):
            hit = sum(r["k"][(name, k)][0] for r in recs)
            tot = sum(r["k"][(name, k)][1] for r in recs)
            return hit / tot if tot else 0.0
        return f

    def stat_recall(strat, name):
        def f(recs):
            found, seen = set(), set()
            for r in recs:
                found |= r["found"][name]
                seen |= r["seen"]
            return len(found) / len(seen) if seen else 0.0
        return f

    out = {"cycles": runs, "config": {"hit_share": HIT_SHARE,
                                       "min_jaccard": MIN_JACCARD}}

    # 1. headline: leaf2 vs none, per k, per ranking
    out["headline_delta_leaf2_minus_none"] = {}
    for name in ("score", "degree", "size", "random"):
        out["headline_delta_leaf2_minus_none"][name] = {}
        for k in KS:
            recs = list(zip(records["none"], records["leaf2"]))
            # paired_bootstrap_delta expects one record list; build combined
            # records so statistic_a/b can each pull from the same resample.
            combined = [{"none": a, "leaf2": b} for a, b in recs]
            def stat_a(rs, name=name, k=k):
                hit = sum(r["none"]["k"][(name, k)][0] for r in rs)
                tot = sum(r["none"]["k"][(name, k)][1] for r in rs)
                return hit / tot if tot else 0.0
            def stat_b(rs, name=name, k=k):
                hit = sum(r["leaf2"]["k"][(name, k)][0] for r in rs)
                tot = sum(r["leaf2"]["k"][(name, k)][1] for r in rs)
                return hit / tot if tot else 0.0
            ci = paired_bootstrap_delta(combined, stat_a, stat_b)
            out["headline_delta_leaf2_minus_none"][name][k] = ci

    # 2. re-tie check: score vs size, under leaf2 only
    out["retie_check_score_minus_size_leaf2"] = {}
    for k in KS:
        def stat_size(rs, k=k):
            hit = sum(r["k"][("size", k)][0] for r in rs)
            tot = sum(r["k"][("size", k)][1] for r in rs)
            return hit / tot if tot else 0.0
        def stat_score(rs, k=k):
            hit = sum(r["k"][("score", k)][0] for r in rs)
            tot = sum(r["k"][("score", k)][1] for r in rs)
            return hit / tot if tot else 0.0
        ci = paired_bootstrap_delta(records["leaf2"], stat_size, stat_score)
        out["retie_check_score_minus_size_leaf2"][k] = ci

    # same check under none, for comparison (did this exist before pruning?)
    out["retie_check_score_minus_size_none"] = {}
    for k in KS:
        def stat_size(rs, k=k):
            hit = sum(r["k"][("size", k)][0] for r in rs)
            tot = sum(r["k"][("size", k)][1] for r in rs)
            return hit / tot if tot else 0.0
        def stat_score(rs, k=k):
            hit = sum(r["k"][("score", k)][0] for r in rs)
            tot = sum(r["k"][("score", k)][1] for r in rs)
            return hit / tot if tot else 0.0
        ci = paired_bootstrap_delta(records["none"], stat_size, stat_score)
        out["retie_check_score_minus_size_none"][k] = ci

    # 3. per-typology built funnel, before/after
    out["funnel_by_typology"] = {}
    all_typs = sorted(set(typ_funnel["none"]) | set(typ_funnel["leaf2"]))
    for t in all_typs:
        out["funnel_by_typology"][t] = {
            s: dict(typ_funnel[s][t]) for s in STRATS
        }

    print("\n=== headline: score p@k, leaf2 vs none ===")
    for k in KS:
        d = out["headline_delta_leaf2_minus_none"]["score"][k]
        print(f"  k={k:<4} none={d['a']:.4f} leaf2={d['b']:.4f} "
              f"delta={d['point']:+.4f} CI=[{d['lo']:+.4f},{d['hi']:+.4f}] "
              f"excl0={d['excludes_zero']}")

    print("\n=== re-tie check: score - size, under leaf2 ===")
    for k in KS:
        d = out["retie_check_score_minus_size_leaf2"][k]
        print(f"  k={k:<4} size={d['a']:.4f} score={d['b']:.4f} "
              f"delta={d['point']:+.4f} CI=[{d['lo']:+.4f},{d['hi']:+.4f}] "
              f"excl0={d['excludes_zero']}")

    print("\n=== re-tie check: score - size, under none (pre-prune) ===")
    for k in KS:
        d = out["retie_check_score_minus_size_none"][k]
        print(f"  k={k:<4} size={d['a']:.4f} score={d['b']:.4f} "
              f"delta={d['point']:+.4f} CI=[{d['lo']:+.4f},{d['hi']:+.4f}] "
              f"excl0={d['excludes_zero']}")

    print("\n=== per-typology built, none -> leaf2 ===")
    for t in all_typs:
        n = out["funnel_by_typology"][t]["none"]
        l = out["funnel_by_typology"][t]["leaf2"]
        print(f"  {t:<16} seeded={n['seeded']:>4} built {n['built']:>4} -> {l['built']:>4}")

    (ROOT / "data" / "prune_impact.json").write_text(json.dumps(out, indent=2, default=str))
    print("\nwritten to data/prune_impact.json")


if __name__ == "__main__":
    main()
