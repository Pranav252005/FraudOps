"""IBM Graph Feature Preprocessor as a real control, on this candidate pool.

Section 2 of docs/ARCHITECTURE_UPLIFT.md. The point is to replace HANDOFF
section 4's *coverage checklist* ("essentially at parity") with a measurement:
substitute GFP's feature block for sentinel's, hold the pool, the split, the
model and the metric fixed, and report the paired delta with its CI.

WHY THIS SCRIPT IS SPLIT IN THREE
--------------------------------
The recorded blocker was wrong. Commit `d7dba2f` concluded "snapml is
obtainable, just not on 3.14", and uplift plan 2.1 ranked "make a 3.11 venv,
~30 minutes, lowest risk" as the way to clear it. Measured, on this machine:

  * Python 3.11 was provisioned and `snapml==1.15.6` installed cleanly.
  * `from snapml import GraphFeaturePreprocessor` imports -- the wrapper module
    ships on Windows.
  * Constructing it dies: `module 'snapml.libsnapmllocal3_avx2' has no
    attribute 'gf_allocate'`.
  * None of the six `.pyd` binaries in the Windows wheel export ANY `gf_*`
    symbol. The manylinux wheel of the identical version exports all eight
    (`gf_allocate`, `gf_set_params`, `gf_transform`, `gf_partial_fit`,
    `gf_import_graph`, `gf_export_graph`, `gf_get_num_engineered_features`,
    `gf_get_output_array_dims`).
  * snapml 1.17.x, the current release, ships **no Windows wheels at all**;
    1.15.6 is the last Windows release, and it is the one without GFP.

So the Python version was never the blocker. **The Graph Feature Preprocessor
is not built for Windows at any snapml version or any Python version.** A 3.11
venv cannot fix that, and the "~30 minutes, lowest risk" estimate was wrong
because it was costed against the wrong obstacle.

What that leaves is a file boundary between a Windows half and a Linux half:

  export        (any OS, 3.14)   replay the stream, write per-tick raw edge
                                 lists + the candidates generated at that tick,
                                 with sentinel's own feature block alongside.
  gfp-features  (LINUX/macOS)    read the export, run GraphFeaturePreprocessor
                                 over each tick's edges, aggregate the
                                 per-transaction output up to candidate
                                 node-sets, write candidate-level GFP features.
  compare       (any OS, 3.14)   same split, same model, same metric, same
                                 paired bootstrap: sentinel block vs GFP block
                                 vs both.

`export` and `compare` run here. `gfp-features` needs a Linux box -- WSL, a
container, or a CI runner. Until it has been run, `compare` refuses to invent
a result and NO parity claim belongs anywhere in the repo.

GRANULARITY, STATED RATHER THAN PAPERED OVER
--------------------------------------------
GFP emits features per transaction; sentinel emits them per candidate. This
takes route (b) of uplift plan 2.3: aggregate GFP's transaction features UP to
sentinel's candidate node-sets and compare both blocks under sentinel's own
ring-level p@k. That answers the question the paper does not ask -- do GFP's
features rank *rings* better? -- rather than the paper's own per-transaction
F1, which HANDOFF section 3 already established is not a valid target here.

GFP is fed the RAW transactions in each window, not sentinel's pair-aggregated
window graph. That is deliberately generous to the control: sentinel's
`WindowedGraph` collapses an ordered pair into one `PairAgg`, so GFP is being
handed strictly more information than sentinel's own graph retains.

    python scripts/gfp_control.py export
    # on Linux, in a 3.11 venv with snapml:
    python scripts/gfp_control.py gfp-features
    python scripts/gfp_control.py compare
"""
from __future__ import annotations

import argparse
import json
import platform
import random
import sys
import time
from collections import defaultdict, deque
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.data.datasets import active_stream_dir
from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.graph.window import WindowedGraph
from sentinel.learn.reranker import feature_names, vectorise
from sentinel.stream.replay import Stream
from sentinel.data.datasets import active as _active_dataset

#: The AMLworld split in play. Defaults to HI-Small; override with
#: SENTINEL_DATASET. A split whose constants are underived refuses.
DATASET = _active_dataset()

from scripts.eval_oracle import EVERY, active_rings, label_candidate

ROOT = Path(__file__).resolve().parent.parent
EXPORT_DIR = ROOT / "data" / "gfp_export"
GFP_FEATURES = ROOT / "data" / "gfp_features.npz"
COMPARE_OUT = ROOT / "data" / "eval_gfp.json"

# The paper's AML configuration (arXiv:2402.08593, section 5): scatter-gather
# bounded at 6 h, simple cycles at 1 day and 10 hops, temporal cycles on. These
# are GFP's own published parameters for this dataset family and are NOT tuned
# here -- tuning the control to this data would make the comparison meaningless
# in the direction that flatters us.
GFP_PARAMS = {
    "num_threads": 8,
    "vertex_stats": True,
    "vertex_stats_cols": [4],          # the amount column of our edge layout
    # 0:fan 1:degree 2:ratio 3:avg 4:sum 5:min 6:max 7:median 8:var 9:skew
    # 10:kurtosis -- the full published set, including median/min/max, which
    # the default omits.
    "vertex_stats_feats": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "fan": True,
    "fan_tw": 12 * 3600,
    "degree": True,
    "degree_tw": 12 * 3600,
    "scatter-gather": True,
    "scatter-gather_tw": 6 * 3600,     # the paper's 6 h bound
    "temp-cycle": True,
    "temp-cycle_tw": 24 * 3600,
    "lc-cycle": True,
    "lc-cycle_tw": 24 * 3600,          # the paper's 1 day
    "lc-cycle_len": 10,                # the paper's 10 hops
}

# Edge layout handed to GFP. Its contract is
# [edge id, source, target, timestamp, <raw features...>], so `amount` lands at
# column 4 and that is what `vertex_stats_cols` above points at.
EDGE_COLS = ("edge_id", "src", "dst", "ts_seconds", "amount")

# How a candidate's member-edge feature rows are pooled into one candidate-level
# row. All three are kept because GFP's block is a histogram-plus-moment vector
# and there is no single defensible pooling: sum preserves pattern counts, max
# preserves "the most extreme member", mean normalises for candidate size. The
# size-blindness question is handled downstream, not here.
POOLS = ("mean", "max", "sum")


# --------------------------------------------------------------------------
# stage 1: export (runs anywhere)
# --------------------------------------------------------------------------

def export(out_dir: Path = EXPORT_DIR) -> None:
    """Replay once, writing per-tick raw window edges plus that tick's
    candidates, their node sets, labels and sentinel's own feature block.

    The replay is the SAME one `scripts/eval_oracle.collect_pool` performs --
    same tick length, same `EVERY`, same window, same `EVAL_END`, same
    generator and registry -- so the candidate pool this produces is the pool
    every other number in the project is computed on, not a re-derived
    lookalike. It is re-run rather than reusing the cached pool because the
    cached pool does not retain the raw window edges GFP needs as input.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stream = Stream(active_stream_dir(ROOT))
    registry = AccountRegistry.load(
        DATASET.accounts(ROOT))
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)

    # Raw transactions of the trailing window, which the pair-aggregated
    # WindowedGraph does not keep. Batches are dropped once wholly expired.
    pending: deque = deque()
    names: list[str] | None = None
    ring_first_t: dict[int, int] = {}
    manifest: list[dict] = []
    runs = 0
    t0 = time.time()

    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        pending.append(b)
        cutoff = graph.now - WINDOW_MINUTES
        while pending and pending[0].t_end <= cutoff:
            pending.popleft()

        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue
        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue
        for r in rings:
            ring_first_t.setdefault(r, graph.now)
        cands = gen.generate(b)
        if not cands:
            continue
        runs += 1

        keep = [np.asarray(x.ts) > cutoff for x in pending]
        ts = np.concatenate([x.ts[m] for x, m in zip(pending, keep)])
        src = np.concatenate([x.src[m] for x, m in zip(pending, keep)])
        dst = np.concatenate([x.dst[m] for x, m in zip(pending, keep)])
        amt = np.concatenate([x.amount[m] for x, m in zip(pending, keep)])
        order = np.argsort(ts, kind="stable")   # GFP wants ascending timestamps
        ts, src, dst, amt = ts[order], src[order], dst[order], amt[order]

        edges = np.empty((len(ts), len(EDGE_COLS)), dtype=np.float64)
        edges[:, 0] = np.arange(len(ts))
        edges[:, 1] = src
        edges[:, 2] = dst
        edges[:, 3] = ts.astype(np.float64) * 60.0   # minutes -> seconds
        edges[:, 4] = amt

        if names is None:
            names = feature_names(cands[0].features)

        nodes_flat: list[int] = []
        offsets = [0]
        keys, rings_out, sent = [], [], []
        for c in cands:
            nodes_flat.extend(sorted(c.nodes))
            offsets.append(len(nodes_flat))
            keys.append(c.key)
            r = label_candidate(set(c.nodes), rings)
            rings_out.append(-1 if r is None else int(r))
            sent.append(vectorise(c.features, names))

        np.savez_compressed(
            out_dir / f"tick_{graph.now:08d}.npz",
            t=graph.now, edges=edges,
            nodes_flat=np.array(nodes_flat, dtype=np.int64),
            offsets=np.array(offsets, dtype=np.int64),
            keys=np.array(keys), ring=np.array(rings_out, dtype=np.int64),
            sentinel_X=np.array(sent, dtype=np.float64),
            blend=np.array([c.score for c in cands], dtype=np.float64),
            size=np.array([c.size for c in cands], dtype=np.float64),
            degree=np.array([c.features.max_fan for c in cands],
                            dtype=np.float64),
            rnd=np.array([random.Random(c.key).random() for c in cands],
                         dtype=np.float64),
        )
        manifest.append({"t": int(graph.now), "n_edges": int(len(ts)),
                         "n_candidates": len(cands),
                         "n_positive": int(sum(r >= 0 for r in rings_out))})
        if runs % 5 == 0:
            print(f"  tick {runs:>3} t={graph.now} edges={len(ts):>8,} "
                  f"cands={len(cands):>6,} ({time.time() - t0:.0f}s)",
                  flush=True)

    (out_dir / "manifest.json").write_text(json.dumps({
        "ticks": manifest,
        "feature_names": names,
        "ring_first_t": {str(k): int(v) for k, v in ring_first_t.items()},
        "edge_cols": list(EDGE_COLS),
        "gfp_params": GFP_PARAMS,
        "window_minutes": WINDOW_MINUTES,
        "tick_minutes": TICK_MINUTES,
        "every": EVERY,
        "seconds": time.time() - t0,
    }, indent=2))
    print(f"\nexported {len(manifest)} ticks to {out_dir} "
          f"({time.time() - t0:.0f}s)")


# --------------------------------------------------------------------------
# stage 2: GFP features (Linux/macOS only)
# --------------------------------------------------------------------------

def gfp_features(in_dir: Path = EXPORT_DIR, out: Path = GFP_FEATURES,
                 limit: int | None = None) -> None:
    """Run GraphFeaturePreprocessor per tick, pooled up to candidate level.

    `limit` processes only the first N ticks. It exists so the expensive run
    can be smoke-tested before it is committed to in full: the windows here
    carry 0.9-1.6M edges each and GFP searches 10-hop cycles over every one of
    them, so a full pass is not something to discover is misconfigured at
    tick 30. A limited run writes a file that `compare` will REFUSE, because a
    partial pool is not the pool every other number is computed on.
    """
    try:
        from snapml import GraphFeaturePreprocessor
    except ImportError as e:                                # pragma: no cover
        raise SystemExit(
            f"snapml not importable: {e}\n"
            f"This stage needs Linux or macOS. The Windows wheels of snapml "
            f"ship GraphFeaturePreprocessor.py but none of the gf_* native "
            f"symbols, at every version -- see this module's docstring.")

    manifest = json.loads((in_dir / "manifest.json").read_text())
    ticks = sorted(in_dir.glob("tick_*.npz"))
    if not ticks:
        raise SystemExit(f"no exported ticks in {in_dir}; run `export` first")
    n_total = len(ticks)
    if limit:
        ticks = ticks[:limit]
        print(f"SMOKE RUN: {len(ticks)} of {n_total} ticks. The output will be "
              f"rejected by `compare` -- this is for checking the pipeline "
              f"works, not for producing a result.")
    print(f"{len(ticks)} ticks, {sum(x['n_edges'] for x in manifest['ticks']):,} "
          f"edges total. GFP searches 10-hop cycles over every window; this is "
          f"the long stage.")

    all_keys, all_t, all_ring, all_X = [], [], [], []
    col_names: list[str] | None = None
    t0 = time.time()

    for path in ticks:
        z = np.load(path, allow_pickle=False)
        edges = z["edges"]
        # A fresh preprocessor per tick. The export already carries the full
        # trailing window in `edges`, so GFP is given exactly the window
        # sentinel's graph holds; carrying one preprocessor across ticks would
        # let GFP's own time_window silently disagree with sentinel's.
        gfp = GraphFeaturePreprocessor()
        params = dict(GFP_PARAMS)
        params["time_window"] = WINDOW_MINUTES * 60
        gfp.set_params(params)
        enriched = gfp.transform(edges)
        eng = enriched[:, len(EDGE_COLS):]      # drop the raw columns back off
        if col_names is None:
            col_names = [f"gfp_{j}" for j in range(eng.shape[1])]

        # Outgoing adjacency, so a candidate's internal edges cost the sum of
        # its members' out-degrees rather than a scan of every pair in the
        # window. At ~10k candidates and ~100k pairs per tick the scan is a
        # billion set tests; this is three orders of magnitude cheaper.
        out_pairs: dict[int, list[tuple[int, list[int]]]] = defaultdict(list)
        by_pair: dict[tuple[int, int], list[int]] = defaultdict(list)
        for j in range(edges.shape[0]):
            by_pair[(int(edges[j, 1]), int(edges[j, 2]))].append(j)
        for (s, d), idxs in by_pair.items():
            out_pairs[s].append((d, idxs))

        nodes_flat, offsets = z["nodes_flat"], z["offsets"]
        for c in range(len(z["keys"])):
            members = set(nodes_flat[offsets[c]:offsets[c + 1]].tolist())
            rows = []
            for s in members:
                for d, idxs in out_pairs.get(s, ()):
                    if d in members:
                        rows.extend(idxs)
            if rows:
                block = eng[rows]
                pooled = np.concatenate([block.mean(axis=0), block.max(axis=0),
                                         block.sum(axis=0)])
            else:
                # A candidate whose members share no edge inside the window.
                # Zeros, not dropped: dropping would silently change the pool
                # GFP is scored on relative to sentinel's.
                pooled = np.zeros(eng.shape[1] * len(POOLS))
            all_X.append(pooled)
            all_keys.append(str(z["keys"][c]))
            all_t.append(int(z["t"]))
            all_ring.append(int(z["ring"][c]))
        print(f"  {path.name}: {edges.shape[0]:,} edges -> {eng.shape[1]} GFP "
              f"features, {len(z['keys']):,} candidates "
              f"({time.time() - t0:.0f}s)", flush=True)

    pooled_names = [f"{p}_{n}" for p in POOLS for n in col_names]
    np.savez_compressed(
        out, X=np.array(all_X, dtype=np.float64),
        keys=np.array(all_keys), t=np.array(all_t, dtype=np.int64),
        ring=np.array(all_ring, dtype=np.int64),
        names=np.array(pooled_names),
        n_raw_gfp_features=len(col_names),
        gfp_params=json.dumps(GFP_PARAMS),
        platform=platform.platform(),
        n_ticks_processed=len(ticks),
        manifest_ticks=len(manifest["ticks"]))
    print(f"\nwrote {len(all_X):,} candidate rows x {len(pooled_names)} "
          f"pooled GFP features to {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("stage", choices=("export", "gfp-features", "compare"))
    ap.add_argument("--export-dir", type=Path, default=EXPORT_DIR,
                    help="per-tick export. On a dual boot, point this at the "
                         "other OS's mounted copy rather than re-running the "
                         "10-minute replay to reproduce it byte for byte.")
    ap.add_argument("--gfp-features", type=Path, default=GFP_FEATURES)
    ap.add_argument("--out", type=Path, default=COMPARE_OUT)
    ap.add_argument("--limit", type=int, default=None,
                    help="gfp-features: process only the first N ticks, as a "
                         "smoke test. `compare` rejects the result.")
    args = ap.parse_args()

    if args.stage == "export":
        export(args.export_dir)
    elif args.stage == "gfp-features":
        gfp_features(args.export_dir, args.gfp_features, args.limit)
    else:
        from scripts.gfp_compare import compare
        compare(args.export_dir, args.gfp_features, args.out)


if __name__ == "__main__":
    main()
