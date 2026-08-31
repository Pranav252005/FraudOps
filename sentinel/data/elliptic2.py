"""Loader/adapter for Elliptic2: 122K labelled Bitcoin laundering subgraphs.

Elliptic2 (Bellei et al., "The Shape of Money Laundering", arXiv:2404.19109,
KDD MLF '24) is a background graph of 49,299,864 Bitcoin address clusters and
196,215,606 transactions between them, with 121,810 labelled connected
components: 2,763 "suspicious" (linked to laundering) and 119,047 "licit".
Its central thesis -- that AML is a subgraph-level problem, not a node-level
one -- is exactly this project's premise, and unlike AMLworld it carries real
labels on real data plus a published SOTA baseline (GLASS: test F1 0.933,
PR-AUC 0.208, ROC-AUC 0.889; see PUBLISHED_BASELINES below).

**Public on Kaggle; the download is automatable.** An earlier revision of
this docstring claimed the dataset was licence-gated behind a request form at
http://elliptic.co/elliptic2 and that "no script can fetch it unattended".
That is wrong. Elliptic2 is published openly by Elliptic Co. at
https://www.kaggle.com/datasets/ellipticco/elliptic2-data-set and
`scripts/download_elliptic2.bat` fetches it via the Kaggle CLI (one-time
manual step: a Kaggle API token at `%USERPROFILE%/.kaggle/kaggle.json`).

**Do not extract it.** `background_edges.csv` alone is 82.9 GB extracted
against roughly 24.5 GB inside the archive, and the extract step fails on any
machine without that much spare disk -- which is most of them. Nothing in this
module needs the extracted file: every read is a sequential single pass, so
pass `archive=` to `load()` and the members are streamed out of the zip with
nothing written to disk. See `Source`.

The archive contains these five files, which `load()` will also read from a
directory (`data/elliptic2/`) if you did extract them:

    background_nodes.csv       44 columns: `clId` then `feat#1` .. `feat#43`,
                                anonymised node features, pre-binned to
                                integer codes (observed range 0-99)
    background_edges.csv       98 columns: `clId1,clId2,txId` then `feat#1`
                                .. `feat#95`. Only the two endpoint columns are
                                read, here and in the official
                                `preprocess_glass.py`, and NOT because the rest
                                are absent -- because they are unusable. Every
                                feature column is an anonymous ordinal bin code
                                (observed ranges 0-99, 10-88, 0-9, 0-4), the
                                paper names transaction volume and fee as being
                                among the 95 but never says which index, and no
                                bin edges are published. So there is no amount
                                to read: `amount=1.0` below is a placeholder
                                standing in for a quantity the dataset does not
                                ship, not a simplification of one it does. See
                                docs/PHASE5-FINDINGS.md section 2.
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
import io
import zipfile
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
    """Materialise a whole CSV. Only safe for the SMALL files.

    Deliberately not used for `background_nodes.csv` (49.3M rows) or
    `background_edges.csv` (196.2M rows) -- see `_stream_csv` and the
    scale note in the module docstring.
    """
    with (path if hasattr(path, "read")
          else open(path, "r", encoding="utf-8", newline="")) as fh:
        return list(csv.DictReader(fh))


class _ClosingText(io.TextIOWrapper):
    """A text stream that also closes the ZipFile it came out of.

    Without this, each per-file archive stays open for the process lifetime.
    That is a leaked handle on a 24.5 GB file, and on Windows it also keeps the
    file locked against being moved or deleted.
    """

    def __init__(self, zf, raw):
        self._zf = zf
        super().__init__(raw, encoding="utf-8", newline="")

    def close(self) -> None:
        try:
            super().close()
        finally:
            self._zf.close()


class Source:
    """Resolves the five file names to text handles, from a directory OR a zip.

    **Why the zip path exists.** `background_edges.csv` is 82.9 GB extracted
    and about 24.5 GB inside the Kaggle archive. Extracting it needs more free
    disk than a typical laptop has spare -- the machine this was written on had
    50 GB -- so `scripts/download_elliptic2.bat` fails at the extract step with
    "Free space on the target drive" and leaves nothing usable behind.

    Nothing here ever needs the extracted file. Every reader in this module is
    already sequential and single-pass (see `_stream_csv`), and that is exactly
    what `zipfile.ZipFile.open` provides: a decompress-on-demand stream. So the
    archive is read in place and the 82.9 GB is never written anywhere.

    Members are matched by basename, because Kaggle archives sometimes nest the
    files under a directory and sometimes do not.
    """

    def __init__(self, root: str | Path | None = None,
                 archive: str | Path | None = None):
        if root is None and archive is None:
            raise ValueError("Source needs a directory or an archive")
        self.root = Path(root) if root is not None else None
        self.archive = Path(archive) if archive is not None else None
        self._zf: zipfile.ZipFile | None = None
        self._members: dict[str, str] = {}
        if self.archive is not None:
            if not self.archive.exists():
                raise FileNotFoundError(f"archive not found: {self.archive}")
            self._zf = zipfile.ZipFile(self.archive)
            for name in self._zf.namelist():
                self._members.setdefault(name.rsplit("/", 1)[-1], name)

    def _per_file_zip(self, name: str) -> Path | None:
        """`<name>.zip` sitting next to the extracted files, if present.

        This is the layout `kaggle datasets download -f <file>` produces: one
        zip per requested file, rather than one archive for the dataset. It is
        the layout `scripts/download_elliptic2.bat` now uses for the two large
        files, so they never need extracting.
        """
        if self.root is None:
            return None
        z = self.root / f"{name}.zip"
        return z if z.exists() else None

    def has(self, name: str) -> bool:
        if self.root is not None and (self.root / name).exists():
            return True
        if self._per_file_zip(name) is not None:
            return True
        return name in self._members

    def open(self, name: str):
        """A text handle for `name`, from whichever of three layouts has it.

        Order: extracted file, then `<name>.zip` beside it, then the
        whole-dataset archive. Extracted wins so a caller who unpacked the
        three SMALL files gets the fast path there and the streamed path for
        the two huge ones -- which is the recommended layout, since
        background_edges.csv is 82.9 GB extracted and 24.5 GB packed.
        """
        if self.root is not None and (self.root / name).exists():
            return open(self.root / name, "r", encoding="utf-8", newline="")
        z = self._per_file_zip(name)
        if z is not None:
            zf = zipfile.ZipFile(z)
            member = next((m for m in zf.namelist()
                           if m.rsplit("/", 1)[-1] == name), None)
            if member is None:
                zf.close()
                raise FileNotFoundError(f"{name} not found inside {z}")
            return _ClosingText(zf, zf.open(member))
        if name in self._members:
            raw = self._zf.open(self._members[name])
            return io.TextIOWrapper(raw, encoding="utf-8", newline="")
        raise FileNotFoundError(name)

    def describe(self) -> str:
        bits = []
        if self.root is not None:
            bits.append(f"dir={self.root}")
        if self.archive is not None:
            bits.append(f"archive={self.archive}")
        return " ".join(bits)

    def close(self) -> None:
        if self._zf is not None:
            self._zf.close()
            self._zf = None


def _stream_csv(handle):
    """Yield (handle, header, row_iterator) using csv.reader, never materialising.

    csv.reader rather than DictReader: at 196M rows the per-row dict alone
    is tens of gigabytes, and every column but two is discarded anyway.

    Takes an already-open handle rather than a path so the caller can hand it
    a plain file or a stream decompressing out of the Kaggle zip -- see
    `Source`. Both are sequential single-pass reads, which is all this needs.
    """
    reader = csv.reader(handle)
    try:
        header = next(reader, [])
    except Exception:
        handle.close()
        raise
    return handle, header, reader


def _col_index(header: list[str], preferred: str, fallback: int) -> int:
    return header.index(preferred) if preferred in header else fallback


@dataclass
class Elliptic2Data:
    edges: list[Edge]              # background-graph edges
    rings: list[LabeledRing]       # suspicious subgraphs only
    n_background_nodes: int
    n_background_edges: int
    n_licit_components: int
    n_suspicious_components: int
    stats: dict = field(default_factory=dict)


def available(root) -> bool:
    return not missing_files(root)


def missing_files(root) -> list[str]:
    """Which of the five are absent. Accepts a directory path or a `Source`.

    The Path() coercion happens AFTER the Source check, not before: coercing
    first turns a Source into a nonsense path and reports all five missing,
    which is the kind of failure that looks like a data problem for an hour.
    """
    if isinstance(root, Source):
        return [f for f in REQUIRED_FILES if not root.has(f)]
    root = Path(root)
    return [f for f in REQUIRED_FILES if not (root / f).exists()]


def load(root=None, induced: bool = True,
         max_background_edges: int | None = None,
         progress_every: int = 0, archive=None) -> Elliptic2Data:
    """Parse the five Elliptic2 files into the normalised Edge/LabeledRing shape.

    **Scale.** The real background graph is 49,299,864 nodes and 196,215,606
    edges. Materialising either file as a list of dicts needs tens of
    gigabytes and will not complete on an ordinary machine -- an earlier
    version of this function did exactly that, and would have died on the
    first real run. The two big files are therefore streamed with
    `csv.reader`, never held whole.

    `induced=True` (the default) keeps only background edges with at least
    one endpoint inside a labelled subgraph. That is the *evaluation-relevant*
    neighbourhood: the labelled components total roughly 122K subgraphs of
    ~3.7 nodes, so the retained graph is orders of magnitude smaller than the
    full background while still carrying the immediate context around every
    ring the metrics are scored against. It is a deliberate reduction, not a
    silent one -- `stats` reports edges scanned vs retained, so the ratio is
    always visible. Pass `induced=False` for the literal full graph, which is
    honest but is not expected to fit in memory on this hardware.

    `max_background_edges` caps retained edges (for a quick smoke run);
    `progress_every` prints scan progress, since a 196M-row pass is slow
    enough that silence is indistinguishable from a hang.

    `archive` reads the CSVs straight out of the Kaggle zip instead of a
    directory of extracted files, and is the option to use on any machine that
    cannot spare 82.9 GB for `background_edges.csv` alone. Everything here is a
    sequential single pass, so streaming out of the archive costs decompression
    time and no disk at all. `root` and `archive` can both be given: extracted
    files win where they exist, so the three small files can be unpacked for
    speed while the two huge ones stay compressed. See `Source`.

    Raises FileNotFoundError with the manual-download instructions if any
    file is missing, rather than silently returning an empty dataset --
    empty ground truth would corrupt every downstream metric while looking
    like a legitimate (if small) run.
    """
    src = root if isinstance(root, Source) else Source(root, archive)
    missing = missing_files(src)
    if missing:
        # This message used to say the dataset "requires a manual, licensed
        # download ... there is no automatable bulk endpoint". That was wrong
        # and docs/HANDOFF.md 11d already flagged it: Elliptic2 is public on
        # Kaggle. Corrected here rather than left to mislead whoever hits it.
        # This message used to say the dataset "requires a manual,
        # licensed download ... there is no automatable bulk endpoint".
        # That was wrong and docs/HANDOFF.md 11d already flagged it:
        # Elliptic2 is public on Kaggle. Corrected here rather than left
        # to mislead whoever actually hits it.
        raise FileNotFoundError(
            f"Elliptic2 files missing from {src.describe()}: {missing}.\n"
            "Elliptic2 is PUBLIC on Kaggle (it is not licence-gated):\n"
            "  https://www.kaggle.com/datasets/ellipticco/"
            "elliptic2-data-set\n\n"
            "You do NOT need to extract the archive. background_edges.csv"
            " is 82.9 GB extracted, and every read in this module is a\n"
            "sequential single pass -- so point `archive` at the\n"
            "downloaded zip instead:\n"
            "    elliptic2.load(archive='data/elliptic2.zip')\n"
            "which streams the members and writes nothing to disk."
        )

    # --- small files: safe to materialise -------------------------------
    cc_rows = _read_csv(src.open("connected_components.csv"))
    node_rows = _read_csv(src.open("nodes.csv"))
    edge_rows = _read_csv(src.open("edges.csv"))

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
    labelled_nodes = set(node_to_cc)

    def is_licit(label: str) -> bool:
        return label in LICIT_LABELS

    # --- background_nodes.csv: streamed, counted only -------------------
    # 49.3M rows and 43 anonymised pre-binned feature columns. Nothing
    # downstream consumes those features yet, so only the row count is kept.
    fh, _header, reader = _stream_csv(src.open("background_nodes.csv"))
    try:
        n_background_nodes = sum(1 for _ in reader)
    finally:
        fh.close()
    if n_background_nodes == 0:
        raise ValueError("background_nodes.csv is empty")

    # --- background_edges.csv: streamed, filtered -----------------------
    edges: list[Edge] = []
    scanned = 0
    fh, header, reader = _stream_csv(src.open("background_edges.csv"))
    try:
        c1 = _col_index(header, "clId1", 0)
        c2 = _col_index(header, "clId2", 1)
        for row in reader:
            scanned += 1
            if progress_every and scanned % progress_every == 0:
                print(f"  background_edges: scanned {scanned:,}, "
                      f"retained {len(edges):,}", flush=True)
            if len(row) <= max(c1, c2):
                continue
            src, dst = str(row[c1]), str(row[c2])
            if induced and src not in labelled_nodes and dst not in labelled_nodes:
                continue
            # amount=1.0 is a PLACEHOLDER, not a unit amount. Elliptic2
            # publishes no magnitude -- see the file schema in the module
            # docstring. Every amount-derived feature therefore degenerates:
            # with a constant amount, `inflow`/`outflow` become boundary edge
            # COUNTS and `conservation` becomes a boundary-degree ratio wearing
            # the name of a flow ratio. It does not crash and it produces a
            # plausible number in 0..1, which is what makes it dangerous.
            edges.append(Edge(ts=EPOCH, src=src, dst=dst, amount=1.0, currency="BTC"))
            if max_background_edges is not None and len(edges) >= max_background_edges:
                break
    finally:
        fh.close()

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
        "n_background_nodes_file": n_background_nodes,
        "background_edges_scanned": scanned,
        "background_edges_retained": len(edges),
        # The reduction this load applied, stated rather than implied. At
        # full scale this should be a very small fraction; if it is close to
        # 1.0 the induced filter is not actually reducing anything and the
        # run is about to behave like a full load.
        "background_edge_retention_ratio": (len(edges) / scanned) if scanned else 0.0,
        "induced": induced,
        "max_background_edges": max_background_edges,
        "n_labelled_nodes": len(labelled_nodes),
        "n_components_labelled": len(cc_rows),
        "n_components_with_edges": len(by_cc),
    }
    return Elliptic2Data(
        edges=edges, rings=rings,
        n_background_nodes=n_background_nodes, n_background_edges=len(edges),
        n_licit_components=n_licit, n_suspicious_components=n_suspicious,
        stats=stats,
    )
