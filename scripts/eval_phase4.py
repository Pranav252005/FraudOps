"""Phase 4 evaluation: does the learned re-ranker beat the hand-set weights?

The experiment, end to end:

  1. Replay the evaluation window, generating candidates as in phase 2.
  2. Promote the top of each cycle into cases, with the control arm.
  3. A simulated analyst disposes each case from ground truth, with human-like
     error, producing the label corpus.
  4. Split by TIME. Train the re-ranker on the first half only.
  5. On the held-out second half, rank the same candidates two ways -- by the v1
     hand-set score and by the model -- and compare precision@k.

Both rankings see identical candidates, so the comparison isolates ordering.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.cases.case import Lane
from sentinel.cases.manager import CaseManager
from sentinel.cases.store import CaseStore
from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.eval.bootstrap import paired_bootstrap_delta, ratio_of_sums
from sentinel.graph.window import WindowedGraph
from sentinel.learn.analyst import SimulatedAnalyst
from sentinel.learn.reranker import Reranker, time_split
from sentinel.stream.replay import Stream
from sentinel.data.datasets import active as _active_dataset

#: The AMLworld split in play. Defaults to HI-Small; override with
#: SENTINEL_DATASET. A split whose constants are underived refuses.
DATASET = _active_dataset()

ROOT = Path(__file__).resolve().parent.parent
EVERY = 6
CAPACITY = 40
KS = (5, 10, 20, 50)
HIT_SHARE = 0.5
MIN_JACCARD = 0.3


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= 3}


def truth_overlap(nodes, rings, key):
    """Members of the best-matching ground-truth ring, if it qualifies."""
    best, best_n = set(), 0
    for acc in rings.values():
        inter = nodes & acc
        if not inter:
            continue
        if len(inter) / len(acc) < HIT_SHARE:
            continue
        if len(inter) / len(nodes | acc) < MIN_JACCARD:
            continue
        if len(inter) > best_n:
            best, best_n = inter, len(inter)
    return {key(n) for n in best}


def precision_at(ordered, k):
    top = ordered[:k]
    if not top:
        return 0.0
    return sum(1 for c in top if c._is_hit) / len(top)


def main() -> None:
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(
        DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)
    store = CaseStore(ROOT / "data" / "cases")
    mgr = CaseManager(store, stream=stream, capacity=CAPACITY,
                      control_fraction=0.10)
    analyst = SimulatedAnalyst(seed=7)

    # Candidates are kept per cycle so the two rankings can be compared on
    # identical inputs later.
    cycles: list[dict] = []
    t0 = time.time()
    runs = 0

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

        for c in cands:
            c._truth = truth_overlap(set(c.nodes), rings, stream.key)
            c._is_hit = bool(c._truth)
        cycles.append({"t": graph.now, "cands": cands})

        for case, lane in mgr.select(cands):
            opened = mgr.open_case(case, lane, graph)
            verdict, reason, keep, drop = analyst.dispose(opened, case._truth)
            store.dispose(opened.id, verdict, reason=reason,
                          at=opened.opened_at, analyst="simulated",
                          confirmed_members=keep, dropped_members=drop)
        print(f"  run {runs:>3} cands={len(cands):>6,} "
              f"cases={len(store.all()):>5} ({time.time()-t0:.0f}s)", flush=True)

    print(f"\n{runs} cycles in {time.time()-t0:.0f}s")
    print(f"case store: {store.stats()}")
    print(f"analyst   : {analyst.stats}")

    # --- train on the first half of the timeline only ---
    train_cases, test_cases, split_t = time_split(store.labelled(), 0.5)
    print(f"\ntime split at t={split_t} "
          f"({split_t//1440}d{(split_t%1440)//60:02d}h): "
          f"{len(train_cases)} train / {len(test_cases)} test")

    ranker = Reranker()
    rep = ranker.fit(train_cases, validation=test_cases)
    print(f"{rep}")
    pos = rep.n_positive_train
    print(f"positive class: {pos}/{rep.n_train} = {100*pos/max(1,rep.n_train):.1f}% "
          f"of the training corpus")
    print("\ntop features by permutation importance:")
    for name, imp in list(rep.importances.items())[:12]:
        print(f"   {name:<32}{imp:+.4f}")

    # --- compare rankings on held-out cycles ---
    held = [c for c in cycles if c["t"] >= split_t]
    print(f"\nheld-out cycles: {len(held)}")

    tally = {"v1_score": {k: [0, 0] for k in KS},
             "reranker": {k: [0, 0] for k in KS}}
    # One record per held-out cycle, for the bootstrap CI below. The
    # resampling unit is the cycle, exactly as in scripts/eval_funnel.py.
    cycle_records: list[dict] = []
    for cy in held:
        cands = cy["cands"]
        by_score = sorted(cands, key=lambda c: -c.score)
        by_model, _ = ranker.rank(cands, key=lambda c: c.features)
        rec = {}
        for k in KS:
            for name, ordered in (("v1_score", by_score), ("reranker", by_model)):
                top = ordered[:k]
                hit = sum(1 for c in top if c._is_hit)
                tally[name][k][0] += hit
                tally[name][k][1] += len(top)
                rec[f"{name}_hit_{k}"] = hit
                rec[f"{name}_tot_{k}"] = len(top)
        cycle_records.append(rec)

    print(f"\n{'ranking':<12}" + "".join(f"{'p@'+str(k):>10}" for k in KS))
    out = {}
    for name in ("v1_score", "reranker"):
        row = f"{name:<12}"
        out[name] = {}
        for k in KS:
            h, n = tally[name][k]
            p = h / max(1, n)
            out[name][k] = p
            row += f"{p:>10.3f}"
        print(row)

    row = f"{'lift':<12}"
    for k in KS:
        a, b = out["v1_score"][k], out["reranker"][k]
        row += f"{(b/a if a else float('inf')):>9.2f}x"
    print(row)

    # --- does the lift survive its own confidence interval? ---
    # A point estimate at this sample size (a few dozen held-out cycles) can
    # be moved substantially by one or two cycles, so the headline "+lift"
    # number is reported here paired with a 95% CI on the delta. If the CI
    # includes zero, the lift is not distinguishable from noise at this
    # sample size, and that is stated plainly rather than left implicit.
    print(f"\n{'k':<6}{'delta':>10}{'lo':>10}{'hi':>10}  excludes 0?   (95% CI, "
          f"n={len(cycle_records)} held-out cycles)")
    ci_out = {}
    for k in KS:
        stat_v1 = ratio_of_sums(f"v1_score_hit_{k}", f"v1_score_tot_{k}")
        stat_rr = ratio_of_sums(f"reranker_hit_{k}", f"reranker_tot_{k}")
        result = paired_bootstrap_delta(cycle_records, stat_v1, stat_rr)
        ci_out[k] = result
        print(f"{k:<6}{result['point']:>10.3f}{result['lo']:>10.3f}"
              f"{result['hi']:>10.3f}{str(result['excludes_zero']):>13}")
    if 10 in ci_out:
        verdict = ("survives" if ci_out[10]["excludes_zero"] else
                    "does NOT survive -- indistinguishable from noise at this sample size")
        print(f"\nThe p@10 lift {verdict} its own 95% CI.")

    (ROOT / "data" / "eval_phase4.json").write_text(json.dumps({
        "runs": runs, "split_t": split_t,
        "n_train": len(train_cases), "n_test": len(test_cases),
        "case_stats": store.stats(), "analyst_stats": analyst.stats,
        "precision": out, "importances": rep.importances,
        "lift_ci": ci_out,
    }, indent=2, default=str))
    print("\nwritten to data/eval_phase4.json")


if __name__ == "__main__":
    main()
