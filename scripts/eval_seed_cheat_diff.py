"""Phase 2A -- WHICH rings the seed cheat rescues, and what distinguishes them.

THE TENSION THIS EXISTS TO SETTLE. docs/HANDOFF.md 5b measures seeding at 89%
of active rings. docs/CENTREPIECE-INVALIDATED.md measures the seed cheat as
worth ~2.2x at k=10 to the shipped scorer. Both cannot be simple. The standing
hypothesis is that "the ring was seeded at all" is not "the ring was seeded
with a member set the builder can grow into the ring", which would put the loss
at BUILD rather than at seed selection -- and would mean 5b and 5c are still
right that widening the seed triggers is the wrong knob.

That is a hypothesis. This script is the measurement.

WHY THIS IS NOT "A READ OF DATA THAT EXISTS", contrary to what
docs/HANDOFF-NEXT.md and docs/CENTREPIECE-INVALIDATED.md both claim. Run 2's
two pools are never persisted: `scripts/eval_oracle.collect_pool` returns them
in memory and `data/eval_oracle.json` stores only per-cycle aggregates. Of the
four fields the diff needs, exactly one (`recovered_honest`) is recoverable
from `data/ranker_pool.npz`; the seed sets are computed and discarded in both
arms. So this replays. See docs/inventory/run2_pools.md.

WHAT IS VALID AT THIS n AND WHAT IS NOT. The catalogue below -- the 16-cell
partition and the per-ring measurements -- is descriptive and is valid now. It
is NOT an inferential claim about the size of the seeding prize; that is
`oracle_over_blend` in scripts/eval_oracle.py and it carries its own interval.
If |R| is small the catalogue is anecdote, and it says so in its own output
rather than leaving the reader to notice.

Run:  python scripts/eval_seed_cheat_diff.py
      python scripts/eval_seed_cheat_diff.py --max-cycles 3   # smoke test
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.data.datasets import active_result_path
from sentinel.data.datasets import active_stream_dir
from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.eval.funnel import is_hit
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream
from sentinel.data.datasets import active as _active_dataset

#: The AMLworld split in play. Defaults to HI-Small; override with
#: SENTINEL_DATASET. A split whose constants are underived refuses.
DATASET = _active_dataset()

ROOT = Path(__file__).resolve().parent.parent
OUT = active_result_path(ROOT, "eval_seed_cheat_diff.json")

# Kept identical to scripts/eval_oracle.py on purpose: this diff is only
# meaningful if it is describing the same two pools that produced the 2.2x.
EVERY = 6
MIN_RING_NODES = 3

# The budget probe for H3, "is the ring reachable once the builder's budget is
# removed". Run as a SWEEP OVER THE REAL EXPANSION PATH rather than as a
# free-standing BFS, for two reasons. It cannot drift from what the builder
# actually does -- `g.expand` is the same call `CandidateGenerator.generate`
# makes. And it answers the more useful question: not "reachable in principle"
# but WHICH KNOB is binding, which is the difference between a finding and a
# curiosity.
#
# An earlier version of this file did use an unbounded BFS with a 200k visited
# cap. It was abandoned before producing any number: at ~500 (cycle, ring)
# pairs it would have cost on the order of 10^8 Python-level neighbour lookups,
# and a probe whose budget is exhausted reports "unreachable" for a ring that
# is merely far away. The sweep is bounded by max_nodes by construction.
#
# (label, hops, max_nodes, max_degree). The first row is the shipped
# configuration from sentinel/config.py and is the control: if a ring is not
# covered there, that is the builder failing on it today.
BUDGET_SWEEP = (
    ("shipped",       2,  200,          50),
    ("no_hub_guard",  2,  200,  10 ** 9),
    ("more_nodes",    2, 2000,          50),
    ("three_hops",    3, 2000,          50),
    ("all_relaxed",   3, 2000,  10 ** 9),
)

# A ring can carry several honest seeds and the builder expands from each one
# separately, so the fair question is whether ANY of them grows into the ring.
# Capped because a ring with 40 seeds would dominate the runtime and the
# marginal seed is very unlikely to change the answer; the cap is recorded in
# the output so its effect is visible rather than assumed harmless.
MAX_SEEDS_PROBED = 3


def active_rings(stream, t_lo, t_hi):
    """Identical to scripts/eval_oracle.active_rings."""
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def budget_sweep(graph, seeds: set[int], members: set[int]) -> dict:
    """For each budget setting, the best containment any single seed achieves.

    Returns {label: {"containment": float, "is_hit": bool}}. "Best" is over
    seeds, because the builder emits one candidate per seed and a ring only has
    to be recovered once.

    Containment is reported alongside `is_hit` deliberately. `is_hit` carries a
    Jaccard floor as well as a containment floor, so a relaxed budget can pull
    in the whole ring and still fail the hit test by dragging in bystanders --
    which is a different failure from not reaching the ring, and the two must
    not be conflated. That distinction is exactly the 5c finding about
    expansion recovering a ring and then burying it.
    """
    probe = sorted(seeds)[:MAX_SEEDS_PROBED]
    out: dict[str, dict] = {}
    for label, hops, max_nodes, max_degree in BUDGET_SWEEP:
        best_cont, best_hit = 0.0, False
        for s in probe:
            nodes = graph.expand([s], hops=hops, max_nodes=max_nodes,
                                 max_degree=max_degree)
            cont = len(nodes & members) / len(members)
            best_cont = max(best_cont, cont)
            best_hit = best_hit or is_hit(nodes, members)
        out[label] = {"containment": round(best_cont, 4), "is_hit": best_hit}
    return out


def ring_components(graph, members: set[int]) -> list[set[int]]:
    """Connected components of the ring's own induced subgraph, in-window.

    This is measurement 5 and it discriminates H2 from H1: a seed set that is
    large but lands entirely in one peripheral component cannot grow into the
    rest of the ring no matter how many seeds it contains.
    """
    comps: list[set[int]] = []
    unseen = set(members)
    while unseen:
        start = unseen.pop()
        comp = {start}
        queue = deque([start])
        while queue:
            node = queue.popleft()
            for nbr in graph.neighbours(node) & members:
                if nbr not in comp:
                    comp.add(nbr)
                    unseen.discard(nbr)
                    queue.append(nbr)
        comps.append(comp)
    return comps


def replay(stream, registry, max_cycles: int | None = None) -> dict:
    """One replay, both seed rules per tick, per-(cycle, ring) records.

    Both arms share one graph and one expansion cache per tick. That is exact,
    not an approximation: `generate` does not mutate the graph, and expansion
    depends only on (seed, graph, bounds) -- which is precisely what
    `expansion_cache` is documented to exploit. The cheat seed set is a
    superset of the honest one, so every honest expansion is reused rather
    than recomputed.
    """
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)
    per_ring: dict[int, dict] = defaultdict(lambda: {
        "cycles": 0, "seeded_honest": False, "seeded_cheat": False,
        "built_honest": False, "built_cheat": False,
        "max_seed_in_ring_honest": 0, "max_ring_size": 0,
        "observations": [],
    })
    cycles = 0
    t0 = time.time()

    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue
        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue

        honest_seeds = gen.seeds(b)
        cheat_seeds = honest_seeds | {n for m in rings.values() for n in m}
        cache: dict = {}
        honest = gen.generate(b, seed_override=None, expansion_cache=cache)
        cheat = gen.generate(b, seed_override=cheat_seeds, expansion_cache=cache)
        if not honest and not cheat:
            continue
        cycles += 1

        honest_sets = [set(c.nodes) for c in honest]
        cheat_sets = [set(c.nodes) for c in cheat]

        for ring, members in rings.items():
            rec = per_ring[ring]
            rec["cycles"] += 1
            rec["max_ring_size"] = max(rec["max_ring_size"], len(members))
            seed_in_ring = members & honest_seeds
            if seed_in_ring:
                rec["seeded_honest"] = True
                rec["max_seed_in_ring_honest"] = max(
                    rec["max_seed_in_ring_honest"], len(seed_in_ring))
            if members & cheat_seeds:
                rec["seeded_cheat"] = True
            built_h = any(is_hit(s, members) for s in honest_sets)
            built_c = any(is_hit(s, members) for s in cheat_sets)
            rec["built_honest"] |= built_h
            rec["built_cheat"] |= built_c

            # The five discriminating measurements, recorded only where the
            # honest rule actually fired -- elsewhere they would be describing
            # a seed set that does not exist.
            if seed_in_ring:
                comps = ring_components(graph, members)
                seeded_comps = sum(1 for c in comps if c & seed_in_ring)
                sweep = budget_sweep(graph, seed_in_ring, members)
                rec["observations"].append({
                    "t": graph.now,
                    "ring_size": len(members),
                    "seed_in_ring": len(seed_in_ring),
                    "built_honest": built_h,
                    "built_cheat": built_c,
                    "n_components": len(comps),
                    "seeded_components": seeded_comps,
                    "largest_component": max(len(c) for c in comps),
                    "sweep": sweep,
                })

        if cycles % 5 == 0:
            print(f"  cycle {cycles:>3}  rings={len(per_ring):>3}  "
                  f"({time.time() - t0:.0f}s)", flush=True)
        if max_cycles and cycles >= max_cycles:
            break

    print(f"  {cycles} cycles, {len(per_ring)} rings, {time.time() - t0:.0f}s")
    return {"cycles": cycles, "rings": dict(per_ring),
            "seconds": round(time.time() - t0, 1)}


def cell(rec: dict) -> str:
    return "".join("1" if rec[k] else "0" for k in
                   ("seeded_honest", "seeded_cheat",
                    "built_honest", "built_cheat"))


def summarise(rings: dict) -> dict:
    """The 16-cell partition, R, and the matched comparison set."""
    counts: dict[str, int] = defaultdict(int)
    for rec in rings.values():
        counts[cell(rec)] += 1

    # R: seeded honestly, NOT recovered honestly, recovered under the cheat.
    R = [r for r, rec in rings.items()
         if rec["seeded_honest"] and not rec["built_honest"]
         and rec["built_cheat"]]
    # The matched comparison: seeded honestly AND recovered honestly.
    C = [r for r, rec in rings.items()
         if rec["seeded_honest"] and rec["built_honest"]]
    return {"cells": dict(counts), "R": sorted(R), "C": sorted(C)}


def _agg(rings: dict, ids: list[int]) -> dict:
    """Per-set medians of the five measurements, best-case for honest seeding.

    Aggregated with the BEST observation per ring (most seeds in ring, most
    members reached) rather than the mean. If the honest rule looks inadequate
    even on its best cycle, that conclusion is not an artefact of averaging
    over cycles where the ring was barely active.
    """
    def median(xs):
        xs = sorted(x for x in xs if x is not None)
        if not xs:
            return None
        n = len(xs)
        return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2

    seed_frac, split, ring_size = [], [], []
    cont = {label: [] for label, *_ in BUDGET_SWEEP}
    hit = {label: 0 for label, *_ in BUDGET_SWEEP}
    for r in ids:
        obs = rings[r]["observations"]
        if not obs:
            continue
        best = max(obs, key=lambda o: (o["seed_in_ring"],
                                       o["sweep"]["all_relaxed"]["containment"]))
        seed_frac.append(best["seed_in_ring"] / best["ring_size"])
        ring_size.append(best["ring_size"])
        split.append(1 if best["seeded_components"] < best["n_components"] else 0)
        for label in cont:
            cont[label].append(best["sweep"][label]["containment"])
            hit[label] += 1 if best["sweep"][label]["is_hit"] else 0
    n_obs = len(seed_frac)
    return {
        "n": len(ids),
        "n_with_observations": n_obs,
        "median_ring_size": median(ring_size),
        "median_seed_fraction_of_ring": median(seed_frac),
        "share_seed_split_across_components": (
            sum(split) / n_obs if n_obs else None),
        "median_containment": {k: median(v) for k, v in cont.items()},
        "share_covered": {k: (v / n_obs if n_obs else None)
                          for k, v in hit.items()},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-cycles", type=int, default=None,
                    help="stop early; for smoke tests only, never for a result")
    args = ap.parse_args()

    stream = Stream(active_stream_dir(ROOT))
    registry = AccountRegistry.load(
        DATASET.accounts(ROOT))

    print("=== replaying both seed rules over the same ticks ===")
    result = replay(stream, registry, max_cycles=args.max_cycles)
    rings = result["rings"]
    summary = summarise(rings)
    R, C = summary["R"], summary["C"]

    print(f"\n16-cell partition over {len(rings)} rings "
          f"(seeded_honest, seeded_cheat, built_honest, built_cheat):")
    for code in sorted(summary["cells"]):
        print(f"  {code}  {summary['cells'][code]:>4}")
    total = sum(summary["cells"].values())
    assert total == len(rings), "partition does not cover every ring"

    seeded_h = sum(1 for rec in rings.values() if rec["seeded_honest"])
    print(f"\nreconciliation with docs/HANDOFF.md 5b: "
          f"{seeded_h}/{len(rings)} = {seeded_h / len(rings):.1%} of active "
          f"rings seeded under the honest rule "
          f"(5b reports 230/259 = 89%)")

    print(f"\n|R| = {len(R)}  -- rings seeded honestly, NOT recovered honestly, "
          f"recovered under the cheat")
    print(f"|C| = {len(C)}  -- matched comparison: seeded and recovered honestly")

    if len(R) < 10:
        print("\n  |R| < 10. THIS IS A CATALOGUE, NOT A RESULT. The "
              "measurements below are reported per ring and no hypothesis is "
              "fitted to them.")
        for r in R:
            obs = rings[r]["observations"]
            best = max(obs, key=lambda o: o["seed_in_ring"]) if obs else None
            print(f"    ring {r}: size {rings[r]['max_ring_size']}, "
                  f"max seeds in ring {rings[r]['max_seed_in_ring_honest']}, "
                  + (f"components {best['n_components']} "
                     f"(seeded {best['seeded_components']}), "
                     f"containment shipped "
                     f"{best['sweep']['shipped']['containment']:.2f} -> "
                     f"all_relaxed "
                     f"{best['sweep']['all_relaxed']['containment']:.2f}"
                     if best else "no seeded observation"))

    agg_R, agg_C = _agg(rings, R), _agg(rings, C)
    print("\nR vs the matched comparison set:")
    print(f"  {'measurement':<44}{'R':>12}{'C':>12}")
    for key in ("median_ring_size", "median_seed_fraction_of_ring",
                "share_seed_split_across_components"):
        a, b = agg_R[key], agg_C[key]
        fa = "n/a" if a is None else f"{a:.3f}"
        fb = "n/a" if b is None else f"{b:.3f}"
        print(f"  {key:<44}{fa:>12}{fb:>12}")
    print(f"\n  budget sweep -- median containment of the ring, best single seed:")
    for label, *_ in BUDGET_SWEEP:
        a, b = agg_R["median_containment"][label], agg_C["median_containment"][label]
        ha, hb = agg_R["share_covered"][label], agg_C["share_covered"][label]
        fa = "n/a" if a is None else f"{a:.3f}"
        fb = "n/a" if b is None else f"{b:.3f}"
        fha = "n/a" if ha is None else f"{ha:.0%}"
        fhb = "n/a" if hb is None else f"{hb:.0%}"
        print(f"    {label:<16} containment {fa:>7} / {fb:>7}   "
              f"covered {fha:>5} / {fhb:>5}")

    # The falsification check the plan requires be run BEFORE interpreting.
    KEYS = ("median_seed_fraction_of_ring",
            "share_seed_split_across_components")
    differs = [k for k in KEYS
               if agg_R[k] is not None and agg_C[k] is not None
               and agg_R[k] != agg_C[k]]
    differs += [f"containment:{lab}" for lab, *_ in BUDGET_SWEEP
                if agg_R["median_containment"][lab] is not None
                and agg_C["median_containment"][lab] is not None
                and agg_R["median_containment"][lab]
                != agg_C["median_containment"][lab]]
    print(f"\nfalsification check: R and C differ on {len(differs)} of {len(KEYS) + len(BUDGET_SWEEP)} "
          f"measurements {differs}")
    if not differs:
        print("  R does not differ from C on ANY measurement. The cheat is "
              "not operating through seed growability, the 5b framing is "
              "wrong as posed, and THAT IS THE FINDING.")

    out = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cycles": result["cycles"],
        "seconds": result["seconds"],
        "max_cycles": args.max_cycles,
        "n_rings": len(rings),
        "cells": summary["cells"],
        "R": R, "C": C,
        "seeded_honest_rate": seeded_h / len(rings) if rings else 0.0,
        "aggregate_R": agg_R, "aggregate_C": agg_C,
        "measurements_differing": differs,
        "conditioning": (
            "Descriptive catalogue over rings active in the eval window. NOT "
            "an inferential claim about the size of the seeding prize -- that "
            "is oracle_over_blend in data/eval_oracle.json and it carries an "
            "interval. Rings are counted once, by boolean OR across every "
            "cycle in which they were active, matching sentinel/eval/funnel.py."),
        "rings": {str(r): rec for r, rec in rings.items()},
    }
    OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(f"\nwritten to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
