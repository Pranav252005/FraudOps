"""Phase 0, gate 2: profile the transaction file and prove the labels join.

The pattern file is only useful if its edges can be located in the main stream.
If the join fails, ring-level ground truth cannot be attached to the data the
detector actually sees.
"""
import sys, time
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sentinel.data.patterns import load_rings
from sentinel.data.datasets import active as _active_dataset

#: The AMLworld split in play. Defaults to HI-Small; override with
#: SENTINEL_DATASET. A split whose constants are underived refuses.
DATASET = _active_dataset()

ROOT = Path(__file__).resolve().parent.parent
TRANS = DATASET.trans(ROOT)
PATTERNS = DATASET.patterns(ROOT)

COLS = ["Timestamp","From Bank","Account","To Bank","Account.1","Amount Received",
        "Receiving Currency","Amount Paid","Payment Currency","Payment Format","Is Laundering"]

rings = load_rings(PATTERNS)
# Join key: the tuple that identifies a transaction row uniquely enough.
ring_keys = {}
for r in rings:
    for e in r.edges:
        k = (e.ts.strftime("%Y/%m/%d %H:%M"), e.src, e.dst, f"{e.amount:.2f}", e.currency)
        ring_keys.setdefault(k, []).append((r.id, r.typology))
print(f"ring edge keys: {len(ring_keys):,} (from {sum(len(r.edges) for r in rings):,} edges)")

t0 = time.time()
n_rows = 0
n_laundering = 0
fmt = Counter(); fmt_laund = Counter(); cur = Counter()
banks = set(); accounts = set()
matched = set()
ts_min = ts_max = None
self_loops = 0

reader = pd.read_csv(TRANS, chunksize=500_000, header=0, names=COLS, skiprows=1, dtype=str)
for chunk in reader:
    n_rows += len(chunk)
    lab = chunk["Is Laundering"].astype("int8")
    n_laundering += int(lab.sum())
    fmt.update(chunk["Payment Format"].value_counts().to_dict())
    fmt_laund.update(chunk.loc[lab == 1, "Payment Format"].value_counts().to_dict())
    cur.update(chunk["Receiving Currency"].value_counts().to_dict())
    banks.update(chunk["From Bank"].unique()); banks.update(chunk["To Bank"].unique())
    src = chunk["From Bank"] + ":" + chunk["Account"]
    dst = chunk["To Bank"] + ":" + chunk["Account.1"]
    accounts.update(src.unique()); accounts.update(dst.unique())
    self_loops += int((src == dst).sum())
    lo, hi = chunk["Timestamp"].min(), chunk["Timestamp"].max()
    ts_min = lo if ts_min is None else min(ts_min, lo)
    ts_max = hi if ts_max is None else max(ts_max, hi)
    # only laundering rows can be in a pattern, so test just those
    sub = chunk.loc[lab == 1]
    for ts, s, d, a, c in zip(sub["Timestamp"], src[lab==1], dst[lab==1],
                              sub["Amount Received"], sub["Receiving Currency"]):
        k = (ts, s, d, f"{float(a):.2f}", c)
        if k in ring_keys:
            matched.add(k)
    print(f"  ...{n_rows:,} rows  matched {len(matched):,}/{len(ring_keys):,}", flush=True)

print(f"\nparsed in {time.time()-t0:.0f}s")
print(f"rows                {n_rows:,}")
print(f"laundering rows     {n_laundering:,}  (1 in {n_rows/max(1,n_laundering):.0f})")
print(f"distinct accounts   {len(accounts):,}")
print(f"distinct banks      {len(banks):,}")
print(f"self-loop rows      {self_loops:,}  ({100*self_loops/n_rows:.2f}%)")
print(f"time span           {ts_min}  ->  {ts_max}")
print(f"\nRING EDGE JOIN     {len(matched):,}/{len(ring_keys):,} = {100*len(matched)/len(ring_keys):.1f}%")

print("\nPayment Format      overall %      laundering %     lift")
for f, n in fmt.most_common():
    o = 100*n/n_rows
    l = 100*fmt_laund.get(f,0)/max(1,n_laundering)
    print(f"  {f:<16}{o:>8.2f}%{l:>14.2f}%{l/o if o else 0:>9.1f}x")

print(f"\ncurrencies: {len(cur)}  top: {[c for c,_ in cur.most_common(6)]}")
