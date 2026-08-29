"""The gates that fail the build. Section 6.5 of docs/ARCHITECTURE_UPLIFT.md.

Before this there was no CI at all -- no .github/, no pyproject.toml, no
pytest.ini. 363 tests ran when someone remembered. That is the first
reliability gap in a codebase whose characteristic defect is a plausible wrong
answer rather than an error, because a plausible wrong answer is exactly what a
test suite catches and a human reading a diff does not.

Every gate here answers a question that a *passing test suite* would not:

  determinism  Does the pipeline produce the same output twice, in fresh
               processes, under different PYTHONHASHSEED? The plan pre-registers
               an expectation that this FIRES: `expand_traced` truncates by
               `sorted(nxt, key=degree)` over a set, so ties break on iteration
               order.
  retie        On the frozen fixture, does the score still beat a node-count
               baseline at k=10 and k=20? A point estimate only -- a 3-cycle
               fixture cannot support a CI, and pretending otherwise would be
               the error this project keeps correcting. The CI version runs on
               demand over 34 cycles.
  regression   Do p@10, p@20 and ring recall on the fixture stay within a
               stated tolerance of a checked-in baseline?
  cost         Does a cost input flagged `unsourced()` reach a reported
               headline? Absolute rupee figures resting on placeholders must
               not ship.

Usage:
    python scripts/ci_gates.py all
    python scripts/ci_gates.py determinism
    python scripts/ci_gates.py retie --write-baseline
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "mini_stream"
BASELINE = ROOT / "tests" / "fixtures" / "mini_baseline.json"

# Explicit, stated tolerance -- section 6.5.3 requires the number to be written
# down rather than implied. Absolute, because the fixture's p@k values are
# small enough that a relative tolerance would be meaninglessly wide.
METRIC_TOLERANCE = 0.005


# --------------------------------------------------------------------------
# the fixture pipeline -- one place, so every gate measures the same thing
# --------------------------------------------------------------------------

def run_fixture() -> dict:
    """Replay the committed fixture and return everything the gates read."""
    from sentinel.config import TICK_MINUTES, WINDOW_MINUTES
    from sentinel.detect.candidates import CandidateGenerator
    from sentinel.eval.funnel import is_hit
    from sentinel.graph.window import WindowedGraph
    from sentinel.stream.replay import Stream

    stream = Stream(FIXTURE)
    meta = stream.meta
    every = meta.get("every_ticks", 6)
    start = meta.get("start_tick", 36)
    n_cycles = meta.get("n_cycles", 3)

    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    # No registry: the accounts CSV is not committed, and the jurisdiction
    # block is not what these gates measure.
    gen = CandidateGenerator(graph, registry=None, node_key=None)

    cycles = []
    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=None)):
        graph.add_batch(b)
        if i < start or (i - start) % every:
            continue
        rings = _active_rings(stream, graph.now - graph.window, graph.now)
        cands = gen.generate(b)
        cycles.append({"tick": i, "rings": rings, "candidates": cands})
        if len(cycles) >= n_cycles:
            break

    graph.check_invariants()
    return {"cycles": cycles, "stats": dict(gen.stats), "is_hit": is_hit}


def _active_rings(stream, t_lo, t_hi, min_nodes=3):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= min_nodes}


def fingerprint(result: dict) -> str:
    """A hash over everything the pipeline decided, order included."""
    h = hashlib.sha256()
    for cyc in result["cycles"]:
        h.update(f"tick={cyc['tick']}|".encode())
        for c in cyc["candidates"]:
            h.update(f"{c.key}|{c.score!r}|{c.seed}|{c.absorbed}|".encode())
            for k, v in sorted(c.features.to_dict().items()):
                h.update(f"{k}={v!r};".encode())
    h.update(json.dumps(result["stats"], sort_keys=True).encode())
    return h.hexdigest()


def metrics(result: dict) -> dict:
    """p@k for the score and the standing baselines, plus ring recall."""
    import random
    is_hit = result["is_hit"]
    ks = (10, 20, 50)
    names = ("score", "size", "degree", "random")
    hits = {n: {k: [0, 0] for k in ks} for n in names}
    found = {n: set() for n in names}
    seen: set = set()

    for cyc in result["cycles"]:
        rings, cands = cyc["rings"], cyc["candidates"]
        seen |= set(rings)
        if not cands:
            continue
        orders = {
            "score": list(cands),
            "size": sorted(cands, key=lambda c: (-c.size, c.key)),
            "degree": sorted(cands, key=lambda c: (-c.features.max_fan, c.key)),
            # Seeded off the candidate key, not a global rng, so the random
            # baseline does not depend on how many cycles ran before it.
            "random": sorted(cands, key=lambda c: random.Random(c.key).random()),
        }
        for name, ordered in orders.items():
            for k in ks:
                for c in ordered[:k]:
                    ns = set(c.nodes)
                    hit = [r for r, mem in rings.items() if is_hit(ns, mem)]
                    if hit:
                        hits[name][k][0] += 1
                        found[name].update(hit)
                    hits[name][k][1] += 1

    out = {"rings_seen": len(seen), "precision": {}, "ring_recall": {}}
    for name in names:
        out["precision"][name] = {
            str(k): (hits[name][k][0] / hits[name][k][1]
                     if hits[name][k][1] else 0.0) for k in ks}
        out["ring_recall"][name] = len(found[name]) / len(seen) if seen else 0.0
    out["stats"] = result["stats"]
    out["n_candidates"] = [len(c["candidates"]) for c in result["cycles"]]
    return out


# --------------------------------------------------------------------------
# gates
# --------------------------------------------------------------------------

def gate_determinism(verbose=True) -> int:
    """Two in-process runs and two fresh processes with different hash seeds.

    The subprocess half is the half that matters: PYTHONHASHSEED is fixed for
    the life of an interpreter, so two in-process runs cannot detect a
    dependence on string hashing at all.
    """
    a = fingerprint(run_fixture())
    b = fingerprint(run_fixture())
    ok = a == b
    if verbose:
        print(f"in-process   run1={a[:16]} run2={b[:16]}  "
              f"{'MATCH' if ok else 'DIFFER'}")

    prints = []
    for seed in ("0", "1", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        proc = subprocess.run(
            [sys.executable, str(Path(__file__)), "_fingerprint"],
            capture_output=True, text=True, env=env, cwd=str(ROOT))
        if proc.returncode:
            print(proc.stdout[-2000:])
            print(proc.stderr[-2000:])
            return 1
        fp = proc.stdout.strip().splitlines()[-1]
        prints.append((seed, fp))
        if verbose:
            print(f"PYTHONHASHSEED={seed:<6} {fp[:16]}")

    cross = len({fp for _, fp in prints}) == 1 and prints[0][1] == a
    if verbose:
        print(f"\ndeterminism gate: {'PASS' if ok and cross else 'FAIL'}")
        if not cross:
            print("  the pipeline's output depends on interpreter hash seeding. "
                  "docs/ARCHITECTURE_UPLIFT.md 6.5.4 pre-registered this as "
                  "expected to fire: expand_traced truncates by "
                  "sorted(nxt, key=degree) with arbitrary tie-breaking over a "
                  "set, and merge.suppress iterates a set of rivals.")
    return 0 if (ok and cross) else 1


def gate_retie(write_baseline=False) -> int:
    """Score must beat node count at k=10 and k=20 on the fixture."""
    m = metrics(run_fixture())
    print(json.dumps(m["precision"], indent=2))
    ok = True
    for k in ("10", "20"):
        d = m["precision"]["score"][k] - m["precision"]["size"][k]
        verdict = "ok" if d > 0 else "RE-TIED"
        print(f"  score - size @{k} = {d:+.4f}  {verdict}")
        ok = ok and d > 0
    if write_baseline:
        BASELINE.write_text(json.dumps(m, indent=2))
        print(f"wrote baseline to {BASELINE}")
    print(f"re-tie gate: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def gate_regression() -> int:
    if not BASELINE.exists():
        print(f"no baseline at {BASELINE}; run "
              f"`python scripts/ci_gates.py retie --write-baseline`")
        return 1
    want = json.loads(BASELINE.read_text())
    got = metrics(run_fixture())
    ok = True
    for k in ("10", "20", "50"):
        a = want["precision"]["score"][k]
        b = got["precision"]["score"][k]
        bad = b < a - METRIC_TOLERANCE
        ok = ok and not bad
        print(f"  p@{k:<3} baseline {a:.4f} -> {b:.4f} "
              f"{'REGRESSED' if bad else 'ok'}")
    a, b = want["ring_recall"]["score"], got["ring_recall"]["score"]
    bad = b < a - METRIC_TOLERANCE
    ok = ok and not bad
    print(f"  recall  baseline {a:.4f} -> {b:.4f} "
          f"{'REGRESSED' if bad else 'ok'}")
    if got["stats"] != want["stats"]:
        print(f"  stage counters moved:\n    {want['stats']}\n -> {got['stats']}")
    print(f"regression gate (tolerance {METRIC_TOLERANCE}): "
          f"{'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def gate_cost() -> int:
    """An unsourced cost input must not reach an absolute headline figure."""
    from sentinel.economics.cost import CostModel
    m = CostModel()
    missing = m.unsourced()
    print(f"unsourced cost inputs: {missing}")
    # The break-even precision and the inversion are the figures this project
    # is allowed to quote, because they do not depend on the unsourced inputs
    # being right. An absolute expected-loss figure would.
    if missing and getattr(m, "quotes_absolute_headline", False):
        print("cost gate: FAIL -- an absolute figure rests on an unsourced input")
        return 1
    print(f"cost gate: PASS ({len(missing)} inputs remain unsourced and are "
          f"reported as such, no absolute headline depends on them)")
    return 0


GATES = {
    "determinism": lambda: gate_determinism(),
    "retie": lambda: gate_retie(),
    "regression": gate_regression,
    "cost": gate_cost,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("gate", choices=list(GATES) + ["all", "_fingerprint"])
    ap.add_argument("--write-baseline", action="store_true")
    args = ap.parse_args()

    if args.gate == "_fingerprint":
        print(fingerprint(run_fixture()))
        return
    if args.gate == "retie":
        raise SystemExit(gate_retie(args.write_baseline))
    if args.gate != "all":
        raise SystemExit(GATES[args.gate]())

    rc = 0
    for name, fn in GATES.items():
        print(f"\n=== {name} ===")
        rc |= fn()
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
