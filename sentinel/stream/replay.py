"""Time-ordered replay of the compiled stream.

The compiled parquet is already sorted, so replay is a forward scan with no
buffering. Each tick yields every edge whose timestamp falls in one bucket,
which is what lets the rest of the system behave as if it were reading a live
topic rather than a file.

Timestamps are stored as int32 minutes since a fixed epoch. Integer time is not
a micro-optimisation here: window expiry and per-hour baseline keys are on the
hot path for every edge, and doing that arithmetic on datetimes costs more than
the entire clustering step.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq


@dataclass(slots=True)
class Batch:
    """One tick's worth of edges, as column arrays."""

    t_start: int                  # minutes since epoch, inclusive
    t_end: int                    # exclusive
    ts: np.ndarray                # int32
    src: np.ndarray               # int32 node id
    dst: np.ndarray               # int32 node id
    amount: np.ndarray            # float64
    currency: np.ndarray          # int8
    channel: np.ndarray           # int8
    is_laundering: np.ndarray     # int8
    ring: np.ndarray              # int32, -1 when not part of a labelled ring

    def __len__(self) -> int:
        return int(self.ts.shape[0])


class Stream:
    """Reads the compiled stream and hands it out one tick at a time."""

    def __init__(self, path: str | Path):
        path = Path(path)
        self.meta = json.loads((path / "meta.json").read_text(encoding="utf-8"))
        self.node_keys: list[str] = json.loads(
            (path / "nodes.json").read_text(encoding="utf-8"))
        self.epoch = datetime.fromisoformat(self.meta["epoch"])

        table = pq.read_table(path / "edges.parquet")
        self.ts = table.column("ts").to_numpy(zero_copy_only=False)
        self.src = table.column("src").to_numpy(zero_copy_only=False)
        self.dst = table.column("dst").to_numpy(zero_copy_only=False)
        self.amount = table.column("amount").to_numpy(zero_copy_only=False)
        self.currency = table.column("currency").to_numpy(zero_copy_only=False)
        self.channel = table.column("channel").to_numpy(zero_copy_only=False)
        self.is_laundering = table.column("is_laundering").to_numpy(zero_copy_only=False)
        self.ring = table.column("ring").to_numpy(zero_copy_only=False)

        if self.ts.size and not bool((np.diff(self.ts) >= 0).all()):
            raise ValueError("compiled stream is not time-ordered; rebuild it")

        self.t_min = int(self.ts[0]) if self.ts.size else 0
        self.t_max = int(self.ts[-1]) if self.ts.size else 0

    # -- naming ---------------------------------------------------------------

    def key(self, node_id: int) -> str:
        return self.node_keys[node_id]

    def when(self, t: int) -> datetime:
        return self.epoch + timedelta(minutes=int(t))

    def ring_name(self, ring_idx: int) -> str | None:
        if ring_idx < 0:
            return None
        return self.meta["ring_ids"][ring_idx]

    def ring_typology(self, ring_idx: int) -> str | None:
        if ring_idx < 0:
            return None
        return self.meta["ring_typologies"][ring_idx]

    # -- replay ---------------------------------------------------------------

    def ticks(self, minutes: int = 60, start: int | None = None,
              end: int | None = None):
        """Yield `Batch` objects covering [start, end) in `minutes` steps.

        Empty buckets are yielded too. A quiet hour is information -- the
        detector needs to see that time passed, or baselines drift out of step
        with the clock they are keyed on.
        """
        if minutes <= 0:
            raise ValueError("tick length must be positive")

        lo = self.t_min if start is None else start
        hi = (self.t_max + 1) if end is None else end
        # Align to the tick grid so buckets are stable across runs and across
        # different start points.
        lo -= lo % minutes

        left = int(np.searchsorted(self.ts, lo, side="left"))
        t = lo
        while t < hi:
            t_next = t + minutes
            right = int(np.searchsorted(self.ts, t_next, side="left"))
            sl = slice(left, right)
            yield Batch(
                t_start=t, t_end=t_next,
                ts=self.ts[sl], src=self.src[sl], dst=self.dst[sl],
                amount=self.amount[sl], currency=self.currency[sl],
                channel=self.channel[sl], is_laundering=self.is_laundering[sl],
                ring=self.ring[sl],
            )
            left = right
            t = t_next

    def n_ticks(self, minutes: int = 60) -> int:
        lo = self.t_min - (self.t_min % minutes)
        return (self.t_max + 1 - lo + minutes - 1) // minutes
