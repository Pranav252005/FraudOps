"""Elliptic2 baseline run: the second dataset, and the one with real labels.

AMLworld's 370 rings are synthetic and generator-shaped (see the two leaks in
docs/PHASE0-FINDINGS.md). Elliptic2 is 122K labelled subgraphs of real Bitcoin
laundering activity, with a published SOTA baseline (GLASS) to compare
against -- exactly the measurement AMLworld cannot provide. Its central
thesis, that AML is a subgraph-level problem, is this project's own premise.

This script:
  1. Looks for the real dataset in `data/elliptic2/` (default) or a path
     given on the command line.
  2. If absent, prints the manual download step (there is no automatable
     bulk endpoint -- see sentinel/data/elliptic2.py) and instead validates
     the pipeline end-to-end against the small synthetic sample in
     tests/fixtures/elliptic2_sample/, so the plumbing is provably correct
     even without the licensed data in hand.
  3. Runs the same static seed-and-expand funnel (sentinel/eval/dataset.py)
     used for any dataset, reports the funnel table and p@k, and prints our
     numbers next to the paper's published GLASS/Sub2Vec/GNN-Seg baselines.

AMLworld stays the controlled ablation bench (it is the only dataset where
ring generation and seeding are things this project's own code controls);
this script does not replace scripts/eval_funnel.py or scripts/eval_oracle.py.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.data.datasets import active_result_path
from sentinel.data import elliptic2
from sentinel.eval.funnel import is_hit
from sentinel.eval.dataset import run_static_funnel

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = ROOT / "data" / "elliptic2"
SAMPLE_DIR = ROOT / "tests" / "fixtures" / "elliptic2_sample"
KS = (10, 20, 50)


def precision_at_k(candidates, rings: dict, k: int) -> tuple[int, int]:
    top = candidates[:k]
    hit = 0
    for c in top:
        nodes = set(c.nodes)
        if any(is_hit(nodes, members) for members in rings.values()):
            hit += 1
    return hit, len(top)


def report(data_dir: Path, is_sample: bool) -> dict:
    data = elliptic2.load(data_dir)
    label = "SYNTHETIC SAMPLE (validation only)" if is_sample else "real Elliptic2"
    print(f"\n=== {label}: {data_dir} ===")
    print(f"background: {data.n_background_nodes:,} nodes, "
          f"{data.n_background_edges:,} edges")
    print(f"components: {data.n_suspicious_components:,} suspicious, "
          f"{data.n_licit_components:,} licit")

    tracker, candidates, node_ids = run_static_funnel(data.edges, data.rings)
    from sentinel.eval.dataset import ring_membership
    ring_members, _ = ring_membership(data.rings, node_ids)

    rows = tracker.to_rows()
    print(f"\n{'stage':<16}{'count':>8}{'recall':>8}")
    total = rows[-1]
    for stage in ("seed_reachable", "seeded", "built", "ranked"):
        print(f"{stage:<16}{total[stage]:>8}{total[stage+'_recall']:>8.0%}")

    precision = {}
    for k in KS:
        hit, tot = precision_at_k(candidates, ring_members, k)
        precision[k] = hit / tot if tot else 0.0
        print(f"p@{k:<3}          {precision[k]:>8.3f}   ({hit}/{tot})")

    if not is_sample:
        print("\npublished baselines (arXiv:2404.19109, Table 2, test split):")
        for method, m in elliptic2.PUBLISHED_BASELINES["test"].items():
            print(f"  {method:<10} f1={m['f1']:.3f}  pr_auc={m['pr_auc']:.3f}  "
                  f"roc_auc={m['roc_auc']:.3f}")
        print("  (this run reports an unsupervised structural p@k, not a "
              "trained classifier's F1/AUC -- not directly comparable to the "
              "table above, same caveat as scripts/eval_vs_published.py for "
              "AMLworld. A supervised comparison needs the oracle approach "
              "from scripts/eval_oracle.py re-run on Elliptic2's own "
              "features once the real files are in hand.)")

    return {
        "is_sample": is_sample,
        "data_dir": str(data_dir),
        "n_background_nodes": data.n_background_nodes,
        "n_background_edges": data.n_background_edges,
        "n_suspicious_components": data.n_suspicious_components,
        "n_licit_components": data.n_licit_components,
        "funnel": rows,
        "precision_at_k": precision,
        "published_baselines": elliptic2.PUBLISHED_BASELINES if not is_sample else None,
    }


def main() -> None:
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DATA_DIR

    if elliptic2.available(data_dir):
        out = report(data_dir, is_sample=False)
    else:
        missing = elliptic2.missing_files(data_dir)
        print(f"Elliptic2 not found at {data_dir} (missing: {missing}).")
        print("\nMANUAL STEP REQUIRED: request and download the dataset from")
        print("  http://elliptic.co/elliptic2")
        print(f"then unzip its five CSV files into {data_dir}/ and re-run this script.")
        print("\nValidating the pipeline against a small synthetic sample instead...")
        out = report(SAMPLE_DIR, is_sample=True)

    (active_result_path(ROOT, "eval_elliptic2.json")).write_text(json.dumps(out, indent=2))
    print("\nwritten to data/eval_elliptic2.json")


if __name__ == "__main__":
    main()
