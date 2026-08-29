"""Freeze a small, real slice of the compiled stream as a committed fixture.

Section 6.4 of docs/ARCHITECTURE_UPLIFT.md. The existing fixtures are one tiny
`elliptic2_sample`; nothing in the suite exercises the real pipeline on real
data at a size CI can carry. That is why the FAN-IN 23 -> 21 regression shipped
unnoticed (docs/HANDOFF.md 5e) -- it was only visible in a full 40-minute
evaluation nobody runs on a diff.

What this builds: three consecutive generation cycles' worth of the real
stream, restricted to the accounts that matter for them, with node ids remapped
to a dense range. The output is a drop-in `Stream` directory, so the fixture
pipeline is the real pipeline -- not a reimplementation that can drift from it.

Determinism of the fixture itself is the point, so every selection step is
sorted before it is used. A fixture whose contents depend on set iteration
order would make the determinism gate it exists to support meaningless.

    python scripts/build_fixture.py
    python scripts/build_fixture.py --max-edges 120000
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.config import TICK_MINUTES, WINDOW_MINUTES
from sentinel.stream.replay import Stream

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "fixtures" / "mini_stream"

# The slice starts here. Chosen so the window is full (the detector ignores
# cycles before WINDOW_MINUTES//2) and several labelled rings are active.
START_TICK = 36
N_CYCLES = 3
EVERY = 6


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-edges", type=int, default=150_000,
                    help="hard cap so the fixture stays committable")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    stream = Stream(ROOT / "data" / "stream")

    # The slice must cover the window feeding the last cycle, so it starts a
    # full window before the first cycle's tick.
    last_tick = START_TICK + (N_CYCLES - 1) * EVERY
    t_hi = (last_tick + 1) * TICK_MINUTES
    t_lo = max(0, t_hi - WINDOW_MINUTES - EVERY * TICK_MINUTES)
    m = (stream.ts >= t_lo) & (stream.ts < t_hi)
    print(f"slice t=[{t_lo}, {t_hi}) -> {int(m.sum()):,} edges before selection")

    src, dst = stream.src[m], stream.dst[m]
    ring = stream.ring[m]

    # Keep every account touching a labelled ring in the slice, plus one hop of
    # their counterparties, plus a deterministic sample of the background so the
    # fixture is not an unrepresentatively clean graph.
    ring_nodes = set(int(x) for x in src[ring >= 0]) | \
        set(int(x) for x in dst[ring >= 0])
    print(f"{len(ring_nodes)} accounts touch a labelled ring in the slice")

    keep = set(ring_nodes)
    for a, b in zip(src.tolist(), dst.tolist()):
        if a in ring_nodes or b in ring_nodes:
            keep.add(a)
            keep.add(b)
    print(f"{len(keep)} accounts after one hop")

    touches = np.array([a in keep or b in keep
                        for a, b in zip(src.tolist(), dst.tolist())])
    idx = np.flatnonzero(touches)
    if len(idx) > args.max_edges:
        # Deterministic thinning: keep every ring edge, then take the earliest
        # background edges up to the cap. Earliest rather than random so the
        # fixture is reproducible from the source without carrying a seed.
        is_ring = ring[idx] >= 0
        ring_idx = idx[is_ring]
        bg_idx = idx[~is_ring][: max(0, args.max_edges - len(ring_idx))]
        idx = np.sort(np.concatenate([ring_idx, bg_idx]))
        print(f"thinned to {len(idx):,} edges "
              f"({len(ring_idx):,} labelled kept in full)")

    # Remap node ids to a dense range, ordered by original id so the mapping is
    # a pure function of the selection.
    used = sorted(set(src[idx].tolist()) | set(dst[idx].tolist()))
    remap = {old: new for new, old in enumerate(used)}
    node_keys = [stream.key(old) for old in used]

    ts = stream.ts[m][idx]
    cols = {
        "ts": ts.astype("int32"),
        "src": np.array([remap[int(x)] for x in src[idx]], dtype="int32"),
        "dst": np.array([remap[int(x)] for x in dst[idx]], dtype="int32"),
        "amount": stream.amount[m][idx].astype("float64"),
        "currency": stream.currency[m][idx].astype("int8"),
        "channel": stream.channel[m][idx].astype("int8"),
        "is_laundering": stream.is_laundering[m][idx].astype("int8"),
        "ring": ring[idx].astype("int32"),
    }
    order = np.argsort(cols["ts"], kind="stable")
    cols = {k: v[order] for k, v in cols.items()}
    assert bool((np.diff(cols["ts"]) >= 0).all()), "fixture is not time-ordered"

    args.out.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table(cols), args.out / "edges.parquet",
                   compression="zstd")
    (args.out / "nodes.json").write_text(json.dumps(node_keys))
    meta = dict(stream.meta)
    meta.update({
        "n_edges": int(len(idx)),
        "n_nodes": len(used),
        "derived_from": "data/stream",
        "slice_t_lo": int(t_lo), "slice_t_hi": int(t_hi),
        "start_tick": START_TICK, "n_cycles": N_CYCLES, "every_ticks": EVERY,
        "note": ("Deterministic slice of the compiled HI-Small stream, node "
                  "ids remapped to a dense range. Ring ids and typologies are "
                  "carried over unchanged so `ring` values still index "
                  "meta['ring_ids']."),
    })
    (args.out / "meta.json").write_text(json.dumps(meta))

    size = sum(f.stat().st_size for f in args.out.iterdir())
    n_rings = len(set(int(r) for r in cols["ring"] if r >= 0))
    print(f"\nwrote {args.out}: {len(idx):,} edges, {len(used):,} nodes, "
          f"{n_rings} labelled rings, {size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
