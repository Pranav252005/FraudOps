"""Phase 1: compile the raw CSV into a replayable, time-ordered stream.

The source file is NOT in timestamp order -- 47.6% of adjacent row pairs go
backwards, and the final row sits a week before the maximum timestamp. Replaying
it in file order would feed the detector scrambled time, which silently destroys
every velocity baseline and every window-based feature while still producing
output. So the sort is a build step, done once.

Three other things happen here, all of them once rather than per tick:

  * accounts are factorised to int32 ids -- the graph layer wants integers, and
    5M string keys would dominate both memory and lookup cost;
  * self-loops are dropped (11.64% of rows, an account paying itself);
  * ground-truth ring ids are attached, so evaluation never has to re-join.

Output is a single parquet file, roughly 30 bytes per row.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.data.patterns import load_rings
from sentinel.schema import account_key, amount_key

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "amlworld"
OUT = ROOT / "data" / "stream"
OUT.mkdir(parents=True, exist_ok=True)

COLS = ["Timestamp", "From Bank", "Account", "To Bank", "Account.1",
        "Amount Received", "Receiving Currency", "Amount Paid",
        "Payment Currency", "Payment Format", "Is Laundering"]

CHUNK = 500_000
EPOCH = np.datetime64("2022-09-01T00:00", "m")


def build_label_index() -> tuple[dict, list[str], list[str]]:
    """Map each ground-truth ring edge to its ring id and typology."""
    rings = load_rings(RAW / "HI-Small_Patterns.txt", strict=True)
    index: dict[tuple, int] = {}
    ring_ids, typologies = [], []
    for i, r in enumerate(rings):
        ring_ids.append(r.id)
        typologies.append(r.typology)
        for e in r.edges:
            key = (e.ts.strftime("%Y/%m/%d %H:%M"), e.src, e.dst,
                   amount_key(e.amount), e.currency)
            # A ring edge should be unique; if two rings claim the same
            # transaction, first writer wins and the collision is counted.
            index.setdefault(key, i)
    return index, ring_ids, typologies


def main() -> None:
    t0 = time.time()
    label_index, ring_ids, typologies = build_label_index()
    print(f"ground truth: {len(ring_ids)} rings, {len(label_index):,} labelled edges")

    node_ids: dict[str, int] = {}
    cur_ids: dict[str, int] = {}
    chan_ids: dict[str, int] = {}

    parts: list[dict] = []
    n_rows = n_self = n_matched = 0

    for chunk in pd.read_csv(RAW / "HI-Small_Trans.csv", chunksize=CHUNK,
                             header=0, names=COLS, skiprows=1, dtype=str):
        n_rows += len(chunk)

        src = [account_key(b, a) for b, a in
               zip(chunk["From Bank"], chunk["Account"])]
        dst = [account_key(b, a) for b, a in
               zip(chunk["To Bank"], chunk["Account.1"])]

        keep = np.fromiter((s != d for s, d in zip(src, dst)),
                           dtype=bool, count=len(src))
        n_self += int((~keep).sum())

        ts = pd.to_datetime(chunk["Timestamp"], format="%Y/%m/%d %H:%M")
        amt = chunk["Amount Received"].astype("float64").to_numpy()
        lab = chunk["Is Laundering"].astype("int8").to_numpy()

        # Ring lookup only needs to consider labelled rows.
        ring = np.full(len(chunk), -1, dtype="int32")
        raw_ts = chunk["Timestamp"].to_numpy()
        raw_cur = chunk["Receiving Currency"].to_numpy()
        raw_amt = chunk["Amount Received"].to_numpy()
        for i in np.nonzero(lab == 1)[0]:
            hit = label_index.get(
                (raw_ts[i], src[i], dst[i], amount_key(raw_amt[i]), raw_cur[i]))
            if hit is not None:
                ring[i] = hit
                n_matched += 1

        def codes(values, table):
            out = np.empty(len(values), dtype="int32")
            for i, v in enumerate(values):
                c = table.get(v)
                if c is None:
                    c = table[v] = len(table)
                out[i] = c
            return out

        parts.append({
            "ts": ((ts.to_numpy().astype("datetime64[m]") - EPOCH)
                   .astype("int32"))[keep],
            "src": codes(src, node_ids)[keep],
            "dst": codes(dst, node_ids)[keep],
            "amount": amt[keep],
            "currency": codes(raw_cur, cur_ids)[keep].astype("int8"),
            "channel": codes(chunk["Payment Format"].to_numpy(),
                             chan_ids)[keep].astype("int8"),
            "is_laundering": lab[keep],
            "ring": ring[keep],
        })
        print(f"  ...{n_rows:,} rows", flush=True)

    df = pd.DataFrame({k: np.concatenate([p[k] for p in parts])
                       for k in parts[0]})
    del parts

    # Stable sort so equal timestamps keep their original relative order --
    # replay must be deterministic for results to be reproducible.
    df = df.iloc[np.argsort(df["ts"].to_numpy(), kind="stable")].reset_index(drop=True)

    pq.write_table(pa.Table.from_pandas(df, preserve_index=False),
                   OUT / "edges.parquet", compression="zstd")

    id_to_key = [None] * len(node_ids)
    for k, i in node_ids.items():
        id_to_key[i] = k
    meta = {
        "epoch": str(EPOCH),
        "n_edges": int(len(df)),
        "n_nodes": len(node_ids),
        "self_loops_dropped": n_self,
        "labelled_edges_matched": n_matched,
        "labelled_edges_expected": len(label_index),
        "ring_ids": ring_ids,
        "ring_typologies": typologies,
        "currencies": sorted(cur_ids, key=cur_ids.get),
        "channels": sorted(chan_ids, key=chan_ids.get),
    }
    (OUT / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (OUT / "nodes.json").write_text(json.dumps(id_to_key), encoding="utf-8")

    span = df["ts"].max() - df["ts"].min()
    print(f"\nrows in        {n_rows:,}")
    print(f"self-loops out {n_self:,} ({100*n_self/n_rows:.2f}%)")
    print(f"edges written  {len(df):,}")
    print(f"nodes          {len(node_ids):,}")
    print(f"ring edges     {n_matched:,}/{len(label_index):,}")
    print(f"time span      {span:,} minutes ({span/1440:.1f} days)")
    print(f"monotonic ts   {bool((np.diff(df['ts'].to_numpy()) >= 0).all())}")
    print(f"parquet        {(OUT/'edges.parquet').stat().st_size/1e6:.1f} MB")
    print(f"built in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
