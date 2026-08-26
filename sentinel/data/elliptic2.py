"""Loader/adapter for Elliptic2: 122K labelled Bitcoin laundering subgraphs.

Elliptic2 (Bellei et al., "The Shape of Money Laundering", arXiv:2404.19109,
KDD MLF '24) is a background graph of 49,299,864 Bitcoin address clusters and
196,215,606 transactions between them, with 121,810 labelled connected
components: 2,763 "suspicious" (linked to laundering) and 119,047 "licit".
Its central thesis -- that AML is a subgraph-level problem, not a node-level
one -- is exactly this project's premise, and unlike AMLworld it carries real
labels on real data plus a published SOTA baseline (GLASS: test F1 0.933,
PR-AUC 0.208, ROC-AUC 0.889; see PUBLISHED_BASELINES below).

**Manual step, required and not automatable here.** The dataset is only
available after requesting it at http://elliptic.co/elliptic2 -- there is no
public bulk-download endpoint, so no script can fetch it unattended. Download,
unzip, and place these five files into a directory (default `data/elliptic2/`):

    background_nodes.csv       one row per wallet cluster; first column is
                                the cluster id; remaining 43 columns are
                                anonymised, pre-binned node features
    background_edges.csv       columns `clId1,clId2` -- one background-graph
                                transaction edge between two clusters
    connected_components.csv   one row per labelled subgraph: an id column
                                plus `ccLabel` ("licit" / "suspicious")
    nodes.csv                  node -> connected-component membership
                                (column 0 = node id, column 1 = component id)
    edges.csv                  edges internal to (or bridging into) a
                                labelled subgraph

Column names are taken directly from the official preprocessing script
(`preprocess_glass.py` in github.com/MITIBMxGraph/Elliptic2), because the
dataset itself ships with no separate schema document.

Elliptic2 carries no wall-clock timestamp worth trusting for this project's
window/replay machinery, so every edge is stamped at a fixed placeholder
epoch -- see EPOCH below. Only "suspicious" components are surfaced as
`LabeledRing`s (the evaluation target, mirroring AMLworld's labelled rings);
licit components are counted but not returned as rings, since there is
nothing to "find" in a licit subgraph.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sentinel.schema import Edge, LabeledRing

REQUIRED_FILES = ("background_nodes.csv", "background_edges.csv",
                   "connected_components.csv", "nodes.csv", "edges.csv")

# A placeholder only -- Elliptic2's real timestamps are not exposed at this
# granularity. Do not read an absolute date out of this.
EPOCH = datetime(2024, 1, 1, tzinfo=timezone.utc)

LICIT_LABELS = {"licit", "0", "0.0"}
SUSPICIOUS_TYPOLOGY = "SUSPICIOUS"

# Table 2 of arXiv:2404.19109, test split (80:10:10 random split by subgraph).
# Reported here so scripts/eval_elliptic2.py can print our number next to it
# without re-deriving it from the paper each time.
PUBLISHED_BASELINES = {
    "n_subgraphs": 121_810,
    "n_suspicious": 2_763,
    "n_licit": 119_047,
    "background_nodes": 49_299_864,
    "background_edges": 196_215_606,
    "test": {
        "GNN-Seg": {"f1": 0.398, "pr_auc": 0.026, "roc_auc": 0.537},
        "Sub2Vec": {"f1": 0.944, "pr_auc": 0.022, "roc_auc": 0.496},
        "GLASS": {"f1": 0.933, "pr_auc": 0.208, "roc_auc": 0.889},
    },
    "note": ("GLASS's own baselines do not use node/edge features (compute "
             "budget on a 49M-node graph); GLASS's PR-AUC/ROC-AUC edge over "
             "GNN-Seg and Sub2Vec comes from using the background graph "
             "structure around each subgraph, not from richer features."),
}


def _read_csv(path: Path) -> list[dict]:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


@dataclass
class Elliptic2Data:
    edges: list[Edge]              # background-graph edges
    rings: list[LabeledRing]       # suspicious subgraphs only
    n_background_nodes: int
    n_background_edges: int
    n_licit_components: int
    n_suspicious_components: int
    stats: dict = field(default_factory=dict)


def available(root: str | Path) -> bool:
    root = Path(root)
    return all((root / f).exists() for f in REQUIRED_FILES)


def missing_files(root: str | Path) -> list[str]:
    root = Path(root)
    return [f for f in REQUIRED_FILES if not (root / f).exists()]


def load(root: str | Path) -> Elliptic2Data:
    """Parse the five Elliptic2 files into the normalised Edge/LabeledRing shape.

    Raises FileNotFoundError with the manual-download instructions if any
    file is missing, rather than silently returning an empty dataset --
    empty ground truth would corrupt every downstream metric while looking
    like a legitimate (if small) run.
    """
    root = Path(root)
    missing = missing_files(root)
    if missing:
        raise FileNotFoundError(
            f"Elliptic2 files missing from {root}: {missing}. "
            "This dataset requires a manual, licensed download from "
            "http://elliptic.co/elliptic2 -- there is no automatable bulk "
            "endpoint. See the sentinel/data/elliptic2.py module docstring "
            "for the exact files and layout expected."
        )

    bg_nodes = _read_csv(root / "background_nodes.csv")
    bg_edges = _read_csv(root / "background_edges.csv")
    cc_rows = _read_csv(root / "connected_components.csv")
    node_rows = _read_csv(root / "nodes.csv")
    edge_rows = _read_csv(root / "edges.csv")

    if not bg_nodes:
        raise ValueError("background_nodes.csv is empty")
    if not cc_rows:
        raise ValueError("connected_components.csv is empty")
    if "ccLabel" not in cc_rows[0]:
        raise ValueError("connected_components.csv is missing the ccLabel column")
    cc_id_col = next(iter(cc_rows[0].keys()))
    cc_label = {row[cc_id_col]: row["ccLabel"].strip().lower() for row in cc_rows}

    if not node_rows:
        raise ValueError("nodes.csv is empty")
    node_cols = list(node_rows[0].keys())
    if len(node_cols) < 2:
        raise ValueError("nodes.csv needs at least a node-id and a component-id column")
    node_id_field, node_cc_field = node_cols[0], node_cols[1]
    node_to_cc = {row[node_id_field]: row[node_cc_field] for row in node_rows}

    def is_licit(label: str) -> bool:
        return label in LICIT_LABELS

    edges: list[Edge] = []
    if bg_edges:
        edge_cols = list(bg_edges[0].keys())
        if "clId1" in bg_edges[0] and "clId2" in bg_edges[0]:
            c1_col, c2_col = "clId1", "clId2"
        else:
            c1_col, c2_col = edge_cols[0], edge_cols[1]
        for row in bg_edges:
            edges.append(Edge(ts=EPOCH, src=str(row[c1_col]), dst=str(row[c2_col]),
                               amount=1.0, currency="BTC"))

    by_cc: dict[str, list[Edge]] = defaultdict(list)
    if edge_rows:
        edge_cols = list(edge_rows[0].keys())
        src_col, dst_col = edge_cols[0], edge_cols[1]
        for row in edge_rows:
            src, dst = str(row[src_col]), str(row[dst_col])
            cc = node_to_cc.get(src) or node_to_cc.get(dst)
            if cc is None:
                continue
            by_cc[cc].append(Edge(ts=EPOCH, src=src, dst=dst, amount=1.0, currency="BTC"))

    rings: list[LabeledRing] = []
    n_licit = n_suspicious = 0
    for cc, cc_edges in by_cc.items():
        label = cc_label.get(cc, "")
        if is_licit(label):
            n_licit += 1
            continue
        if not cc_edges:
            continue
        n_suspicious += 1
        rings.append(LabeledRing(
            id=f"ELLIPTIC2-{cc}", typology=SUSPICIOUS_TYPOLOGY,
            description=f"connected component {cc}", edges=cc_edges,
        ))

    stats = {
        "n_background_nodes_file": len(bg_nodes),
        "n_background_edges_file": len(bg_edges),
        "n_components_labelled": len(cc_rows),
        "n_components_with_edges": len(by_cc),
    }
    return Elliptic2Data(
        edges=edges, rings=rings,
        n_background_nodes=len(bg_nodes), n_background_edges=len(bg_edges),
        n_licit_components=n_licit, n_suspicious_components=n_suspicious,
        stats=stats,
    )
