"""B1: shape-directed fragment linking, against its own null.

Pre-registered in `prereg/fragment_linking.md`. Read that first — the bounds,
the arms, the expectations and five kill criteria were fixed before this file
existed.

Three arms, ONE generation per cycle. Linking is a post-generation operation,
so all three arms derive from the same candidate pool and are paired by
construction:

    shipped       the pool as generated
    link          + merges witnessed by a bounded, time-ordered bridge
    link_random   + the SAME NUMBER of merges between random eligible pairs,
                  with no witness required

`link_random` is the arm that matters. The risk this experiment runs is that
*any* pool growth raises built-recall regardless of criterion; if `link` does
not beat `link_random`, the witness earned nothing.

DECLARED DEVIATION FROM THE PRE-REGISTRATION. The prereg flags, as an
uncontrolled confound, that merged candidates "enter the same score-ordered
NMS and can suppress their own parents". They do not here: merges are appended
to the already-suppressed pool and the pool is re-sorted by score, with no
second NMS pass. That honours the stronger guarantee the same document makes —
"emitted in addition to their parents, never instead" — and it removes the
confound rather than leaving it. Recorded as a deviation because it is one,
and because it makes the result *easier* to interpret, which is the direction
in which an unrecorded deviation is most tempting.

    python scripts/eval_fragment_link.py
    python scripts/eval_fragment_link.py --limit 4
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
from sentinel.detect import features as F
from sentinel.detect import link as L
from sentinel.detect.candidates import Candidate, CandidateGenerator, canonical_key
from sentinel.detect.motifs import detect
from sentinel.eval.bootstrap import paired_bootstrap_delta
from sentinel.eval.funnel import FunnelTracker, is_hit
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

DATASET = _active_dataset()
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "eval_fragment_link.json"

ARMS = ("shipped", "link", "link_random")
KS = (10, 20, 50)
EVERY = 6
MIN_RING_NODES = 3
RANK_K = 50
BASELINES = ("score", "size", "degree", "random")


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def score_merge(nodes, graph, seed, t, registry, node_key, absorbed_from):
    """Build and score a merged candidate through the shipped feature path."""
    nodes = set(nodes)
    edges = graph.subgraph_edges(nodes)
    motifs = detect(edges)
    feats = F.build(nodes, graph, motifs, registry=registry,
                    node_key=node_key, internal_edges=edges)
    s, contrib = F.score(feats)
    return Candidate(key=canonical_key(nodes), nodes=frozenset(nodes),
                     seed=seed, t=t, score=s, contrib=contrib,
                     features=feats, motifs=motifs, absorbed=absorbed_from)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    rngs = {arm: random.Random(7) for arm in ARMS}
    pair_rng = random.Random(11)
    trackers = {arm: FunnelTracker(rank_k=RANK_K) for arm in ARMS}
    rows = {arm: [] for arm in ARMS}
    n_links = []
    # Kill criterion 4: containment and Jaccard, reported together.
    quality = {"merged": [], "unmerged": []}

    runs = 0
    t0 = time.time()
    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue
        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue
        cands = gen.generate(b)
        if not cands:
            continue
        runs += 1

        t_link = time.time()
        links = L.find_links(cands, graph, max_degree=gen.max_degree)
        pool = cands[:L.MAX_CANDIDATES]
        merged = []
        seen_keys = {c.key for c in cands}
        for a, c, bridge in links:
            nodes = pool[a].nodes | pool[c].nodes
            key = canonical_key(nodes)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(score_merge(nodes, graph, pool[a].seed, b.t_end,
                                      registry, stream.key, len(bridge)))
        link_secs = time.time() - t_link

        # The null: the same NUMBER of merges, random eligible pairs, no
        # witness. Eligibility is only the size bound, so the arms differ in
        # the criterion and not in how many candidates they add.
        rnd_merged = []
        if merged and len(pool) >= 2:
            seen_r = {c.key for c in cands}
            tries = 0
            while len(rnd_merged) < len(merged) and tries < 40 * len(merged):
                tries += 1
                a, c = pair_rng.sample(range(len(pool)), 2)
                nodes = pool[a].nodes | pool[c].nodes
                if len(nodes) > L.MAX_MERGED_NODES:
                    continue
                if len(nodes) in (len(pool[a].nodes), len(pool[c].nodes)):
                    continue
                key = canonical_key(nodes)
                if key in seen_r:
                    continue
                seen_r.add(key)
                rnd_merged.append(score_merge(nodes, graph, pool[a].seed,
                                              b.t_end, registry, stream.key, 0))
        n_links.append({"run": runs, "n_links": len(merged),
                        "n_random": len(rnd_merged),
                        "n_candidates": len(cands), "link_secs": link_secs})

        pools = {
            "shipped": cands,
            "link": sorted(cands + merged, key=lambda c: -c.score),
            "link_random": sorted(cands + rnd_merged, key=lambda c: -c.score),
        }

        # Kill criterion 4: for each ring covered in the link arm, the best
        # containment/Jaccard from a merged candidate vs from an unmerged one.
        merged_keys = {c.key for c in merged}
        for r, mem in rings.items():
            for label, subset in (("merged", merged), ("unmerged", cands)):
                best = None
                for c in subset:
                    inter = len(c.nodes & mem)
                    if not inter:
                        continue
                    cont = inter / len(mem)
                    jac = inter / len(c.nodes | mem)
                    if best is None or jac > best[1]:
                        best = (cont, jac)
                if best is not None:
                    quality[label].append({"ring": r, "containment": best[0],
                                           "jaccard": best[1]})

        for arm, ordered in pools.items():
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

        print(f"  run {runs:>3} t={graph.now//1440}d cands={len(cands):>6,} "
              f"links={len(merged):>4} ({link_secs:.1f}s) "
              f"({time.time()-t0:.0f}s)", flush=True)
        if args.limit and runs >= args.limit:
            break

    def rate(rs, name, k):
        num = sum(r[f"{name}_hit_{k}"] for r in rs)
        den = sum(r[f"{name}_n_{k}"] for r in rs)
        return num / den if den else 0.0

    def stat(key, k):
        def f(rs):
            num = sum(r[key][f"score_hit_{k}"] for r in rs)
            den = sum(r[key][f"score_n_{k}"] for r in rs)
            return num / den if den else 0.0
        return f

    arms_out = {}
    for arm in ARMS:
        t = trackers[arm]
        arms_out[arm] = {
            "funnel_totals": t.totals(),
            "funnel_by_typology": t.table(),
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
    for a, bname in (("shipped", "link"), ("shipped", "link_random"),
                     ("link_random", "link")):
        merged_rows = [{"a": x, "b": y} for x, y in zip(rows[a], rows[bname])]
        paired[f"{bname}_minus_{a}"] = {
            str(k): paired_bootstrap_delta(merged_rows, stat("a", k), stat("b", k))
            for k in KS}

    def mean(xs, key):
        return sum(x[key] for x in xs) / len(xs) if xs else 0.0

    out = {
        "runs": runs, "clustering": "cycle_clustered_bootstrap",
        "bounds": {"max_candidates": L.MAX_CANDIDATES,
                   "max_bridge": L.MAX_BRIDGE,
                   "max_merged_nodes": L.MAX_MERGED_NODES,
                   "max_witness_fanout": L.MAX_WITNESS_FANOUT},
        "links_per_cycle": n_links,
        "quality": {k: {"n": len(v), "mean_containment": mean(v, "containment"),
                        "mean_jaccard": mean(v, "jaccard")}
                    for k, v in quality.items()},
        "arms": arms_out, "paired": paired, "cycle_rows": rows,
    }
    args.out.write_text(json.dumps(out, indent=2, default=str))
    print(f"\n{runs} cycles, {time.time()-t0:.0f}s -> {args.out}")

    total_links = sum(r["n_links"] for r in n_links)
    print(f"\nmerges: {total_links} over {runs} cycles "
          f"(mean {total_links/max(1,runs):.1f}/cycle); "
          f"link cost mean {sum(r['link_secs'] for r in n_links)/max(1,runs):.2f}s/cycle")

    print(f"\n{'arm':<14}{'pool':>9}{'built':>7}{'ranked':>8}{'p@10':>9}{'p@20':>9}{'p@50':>9}")
    for arm in ARMS:
        a = arms_out[arm]
        f = a["funnel_totals"]
        pool_mean = sum(r["n_pool"] for r in rows[arm]) / max(1, len(rows[arm]))
        print(f"{arm:<14}{pool_mean:>9,.0f}{f['built']:>7}{f['ranked']:>8}"
              + "".join(f"{a['precision']['score'][str(k)]:>9.4f}" for k in KS))

    print("\ncontainment and Jaccard together (best per covered ring):")
    for k, v in out["quality"].items():
        print(f"  {k:<10} n={v['n']:>5}  containment={v['mean_containment']:.4f}  "
              f"jaccard={v['mean_jaccard']:.4f}")

    print(f"\n{'paired delta (score p@k)':<28}{'k=10':>26}{'k=20':>26}")
    for name, d in paired.items():
        print(f"{name:<28}" + "".join(
            f"{d[str(k)]['point']:>+9.4f} [{d[str(k)]['lo']:+.3f},{d[str(k)]['hi']:+.3f}]"
            for k in (10, 20)))

    print("\nre-tie check (score - size):")
    for arm in ARMS:
        d = arms_out[arm]["score_minus_size"]["10"]
        print(f"  {arm:<14}{d['point']:>+9.4f} [{d['lo']:+.4f},{d['hi']:+.4f}]"
              f"  {'clear' if d['excludes_zero'] else 'INCLUDES ZERO'}")

    # ------------------------------------------------------- kill criteria
    print("\n=== kill criteria ===")
    b_link = arms_out["link"]["funnel_totals"]["built"]
    b_rand = arms_out["link_random"]["funnel_totals"]["built"]
    b_ship = arms_out["shipped"]["funnel_totals"]["built"]
    print(f"1. built: shipped {b_ship} / link_random {b_rand} / link {b_link}"
          f"  -> {'FIRED (witness earned nothing)' if b_link <= b_rand else 'not fired'}")
    d10 = paired["link_minus_shipped"]["10"]
    fired2 = d10["point"] < 0 and d10["excludes_zero"]
    print(f"2. p@10 delta {d10['point']:+.4f} [{d10['lo']:+.4f},{d10['hi']:+.4f}]"
          f"  -> {'FIRED' if fired2 else 'not fired'}")
    d3 = arms_out["link"]["score_minus_size"]["10"]
    print(f"3. score-size under link {'clear' if d3['excludes_zero'] else 'INCLUDES ZERO'}"
          f"  -> {'not fired' if d3['excludes_zero'] else 'FIRED'}")
    qm, qu = out["quality"]["merged"], out["quality"]["unmerged"]
    fired4 = qm["n"] > 0 and qm["mean_jaccard"] < qu["mean_jaccard"]
    print(f"4. merged jaccard {qm['mean_jaccard']:.4f} vs unmerged "
          f"{qu['mean_jaccard']:.4f} -> {'FIRED (dilutes)' if fired4 else 'not fired'}")
    worst = max((r["n_links"] for r in n_links), default=0)
    print(f"5. max merges in a cycle {worst} -> "
          f"{'FIRED (infeasible)' if worst > 20000 else 'not fired'}")


if __name__ == "__main__":
    main()
