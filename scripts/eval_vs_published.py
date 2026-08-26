"""Transaction-level metrics, so this system can be compared to published work.

The published AMLworld baselines report *minority-class F1 on transaction
classification*, trained supervised on the laundering labels. This project
reports *ring-level precision@k*, unsupervised. Those are different tasks and
quoting one against the other would be dishonest.

This script closes the gap in the only direction that is fair: it converts this
system's output into a transaction-level prediction (every edge inside a flagged
candidate is "predicted laundering") and scores it the way the papers do. The
comparison is still unequal -- theirs is supervised and this is not -- but at
least the metric is the same.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream

ROOT = Path(__file__).resolve().parent.parent
EVERY = 6
KS = (10, 20, 50, 100, 500)


def main() -> None:
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(
        ROOT / "data" / "amlworld" / "HI-Small_accounts.csv")
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    # An edge is "flagged" if it sits inside a candidate promoted at any point.
    flagged: dict[int, set[tuple[int, int]]] = {k: set() for k in KS}
    t0 = time.time()
    runs = 0

    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue
        cands = gen.generate(b)
        if not cands:
            continue
        runs += 1
        for k in KS:
            for c in cands[:k]:
                for s, d, _ in graph.subgraph_edges(set(c.nodes)):
                    flagged[k].add((s, d))
        print(f"  run {runs:>3} ({time.time()-t0:.0f}s)", flush=True)

    # Ground truth over the evaluation window, as ordered pairs.
    m = stream.ts < EVAL_END
    truth: set[tuple[int, int]] = set()
    allpairs: set[tuple[int, int]] = set()
    for s, d, lab in zip(stream.src[m], stream.dst[m], stream.is_laundering[m]):
        p = (int(s), int(d))
        allpairs.add(p)
        if lab:
            truth.add(p)

    print(f"\nevaluation window: {len(allpairs):,} distinct account pairs, "
          f"{len(truth):,} laundering ({100*len(truth)/len(allpairs):.3f}%)")
    print(f"\n{'top-k':>7}{'flagged':>12}{'TP':>8}{'precision':>11}"
          f"{'recall':>9}{'F1':>9}{'lift':>8}")

    base = len(truth) / len(allpairs)
    results = {}
    for k in KS:
        pred = flagged[k]
        tp = len(pred & truth)
        prec = tp / len(pred) if pred else 0.0
        rec = tp / len(truth) if truth else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        print(f"{k:>7}{len(pred):>12,}{tp:>8,}{prec:>10.1%}"
              f"{rec:>9.1%}{f1:>9.3f}{prec/base:>7.0f}x")
        results[k] = {"flagged": len(pred), "tp": tp, "precision": prec,
                      "recall": rec, "f1": f1, "lift": prec / base}

    out = {
        "note": "unsupervised; published AMLworld baselines are supervised",
        "base_rate": base,
        "pairs": len(allpairs),
        "laundering_pairs": len(truth),
        "runs": runs,
        "by_k": results,
        "published_hi_small": {
            "GNN_no_adaptations_minorityF1": 0.269,
            "GNN_with_adaptations_minorityF1": 0.429,
            "GIN_adapted_minorityF1": 0.572,
            "note": "supervised, transaction classification, full label access",
        },
    }
    (ROOT / "data" / "eval_vs_published.json").write_text(json.dumps(out, indent=2))
    print("\nwritten to data/eval_vs_published.json")


if __name__ == "__main__":
    main()
