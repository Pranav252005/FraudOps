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

**Second finding, added later**: the top-k F1 numbers below are threshold-
sensitive in the same spirit as the oracle's fixed-0.5-probability pathology,
just via a different mechanism. Each edge's "predicted positive" status is a
step function of whether it happens to fall inside one of the top-k
*candidates'* member sets that cycle -- not a per-edge score compared against
a chosen cutoff, but the effect is the same: F1 collapses at any single k
because k is a coarse, arbitrarily-chosen operating point, not a calibrated
decision boundary the way a supervised classifier's threshold is. A
threshold-free view is added here too: every edge gets the score of the
highest-scoring candidate it was ever a member of (0.0 if never flagged), and
average precision is computed over ALL pairs in the evaluation window against
that score -- the same logic `scripts/eval_oracle.py` uses to argue AP is the
informative number when F1 collapses under imbalance. This does not make the
comparison to the *supervised* baselines fair (their number is still a
per-edge classification with full label access; this is an unsupervised
by-neighbourhood-membership score), but it separates "F1 at one arbitrary k is
bad" from "the ranking itself carries no signal," which are different claims.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sklearn.metrics import average_precision_score

from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.graph.window import WindowedGraph
from sentinel.stream.replay import Stream
from sentinel.data.datasets import active as _active_dataset

#: The AMLworld split in play. Defaults to HI-Small; override with
#: SENTINEL_DATASET. A split whose constants are underived refuses.
DATASET = _active_dataset()

ROOT = Path(__file__).resolve().parent.parent
EVERY = 6
KS = (10, 20, 50, 100, 500)


def main() -> None:
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(
        DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    # An edge is "flagged" if it sits inside a candidate promoted at any point.
    flagged: dict[int, set[tuple[int, int]]] = {k: set() for k in KS}
    # Threshold-free companion: the highest score any candidate containing
    # this edge ever received, across the whole run.
    max_score: dict[tuple[int, int], float] = {}
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
        for c in cands:
            for s, d, _ in graph.subgraph_edges(set(c.nodes)):
                p = (s, d)
                if c.score > max_score.get(p, 0.0):
                    max_score[p] = c.score
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

    # Threshold-free: rank every pair in the evaluation window by the best
    # score any candidate containing it ever received (0.0 if never flagged
    # by anything), and score that ranking with average precision.
    pairs_list = list(allpairs)
    scores = [max_score.get(p, 0.0) for p in pairs_list]
    labels = [1 if p in truth else 0 for p in pairs_list]
    ap = float(average_precision_score(labels, scores)) if truth else 0.0
    print(f"\nthreshold-free average precision over all {len(allpairs):,} pairs: "
          f"{ap:.4f} (vs base rate {base:.4f} = {ap/base if base else 0:.1f}x)")

    out = {
        "note": "unsupervised; published AMLworld baselines are supervised",
        "base_rate": base,
        "pairs": len(allpairs),
        "laundering_pairs": len(truth),
        "runs": runs,
        "by_k": results,
        "average_precision_threshold_free": ap,
        "published_hi_small": {
            "GNN_no_adaptations_minorityF1": 0.269,
            "GNN_with_adaptations_minorityF1": 0.429,
            "GIN_adapted_minorityF1": 0.572,
            "note": "supervised, transaction classification, full label access; "
                    "F1 at their own calibrated threshold over the full test "
                    "set, not comparable to a top-k or AP number from this "
                    "unsupervised, by-neighbourhood-membership system",
        },
    }
    (ROOT / "data" / "eval_vs_published.json").write_text(json.dumps(out, indent=2))
    print("\nwritten to data/eval_vs_published.json")


if __name__ == "__main__":
    main()
