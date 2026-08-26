"""Sliding-window money graph with incremental add and expiry.

The window is the graph the detector actually sees. Holding the full 17.7 days
at once would be both slower and wrong: laundering structure is a burst, and a
cycle spread across three days is only visible as a cycle if the window is wide
enough to contain it and narrow enough that ordinary traffic has not buried it.

Design notes that matter for scale:

  * Edges are aggregated per ordered pair, not stored individually. A pair that
    transacts 40 times is one entry with a count, which is what the structural
    features want anyway and keeps the window an order of magnitude smaller.
  * Expiry is driven by a deque of per-tick arrays, so the cost of ageing an
    edge out is paid once and is proportional to what actually expired. It is
    batch-granular rather than edge-exact: a tick retires as a unit, so an edge
    survives for the window plus up to one tick. At a 72h window and 60min
    ticks that is a 1.4% overhang, traded deliberately for not having to track
    per-edge expiry on 4.5M edges.
  * Node ids are ints and adjacency is dict-of-set. This is the structure the
    two-hop expansion walks, so it is deliberately the cheapest thing to walk.
"""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass

import numpy as np

from sentinel.graph.stats import AccountStats

# Pack an ordered pair into one int64 key. Node ids are int32, so the shift is
# lossless and lets the aggregate live in a single flat dict.
_SHIFT = 32
_MASK = (1 << _SHIFT) - 1


def pair_key(src: int, dst: int) -> int:
    return (int(src) << _SHIFT) | int(dst)


def unpair(key: int) -> tuple[int, int]:
    return key >> _SHIFT, key & _MASK


@dataclass(slots=True)
class PairAgg:
    """Everything the window remembers about one ordered pair."""

    count: int = 0
    amount: float = 0.0
    first_t: int = 0
    last_t: int = 0
    laundering: int = 0

    def add(self, t: int, amount: float, label: int) -> None:
        if self.count == 0:
            self.first_t = t
        self.count += 1
        self.amount += amount
        self.last_t = t
        self.laundering += label

    def remove(self, amount: float, label: int) -> None:
        self.count -= 1
        self.amount -= amount
        self.laundering -= label


class WindowedGraph:
    """Directed multigraph over a trailing time window."""

    def __init__(self, window_minutes: int = 72 * 60):
        self.window = window_minutes
        self.pairs: dict[int, PairAgg] = {}
        self.out_adj: dict[int, set[int]] = defaultdict(set)
        self.in_adj: dict[int, set[int]] = defaultdict(set)
        self._pending: deque = deque()   # (t_end, arrays) awaiting expiry
        # Per-account behavioural statistics. Deliberately NOT expired with the
        # window: dormancy and lifetime velocity are only meaningful against an
        # account's whole observed history, and re-deriving them from a 72h
        # window would erase the signal they exist to capture.
        self.account_stats: dict[int, AccountStats] = defaultdict(AccountStats)
        self.now: int = 0
        self.n_added = 0
        self.n_expired = 0

    # -- mutation -------------------------------------------------------------

    def add_batch(self, batch) -> None:
        """Insert one tick's edges, then age out anything past the window."""
        self.now = max(self.now, batch.t_end)
        if len(batch):
            src, dst = batch.src, batch.dst
            amount, ts, lab = batch.amount, batch.ts, batch.is_laundering
            for i in range(len(batch)):
                s, d = int(src[i]), int(dst[i])
                k = pair_key(s, d)
                agg = self.pairs.get(k)
                if agg is None:
                    agg = self.pairs[k] = PairAgg()
                    self.out_adj[s].add(d)
                    self.in_adj[d].add(s)
                agg.add(int(ts[i]), float(amount[i]), int(lab[i]))
                a_t, a_amt = int(ts[i]), float(amount[i])
                so = self.account_stats[s]
                if so.outflow.n == 0 and so.inflow.n == 0:
                    so.quiet_before_first = a_t
                so.add_out(a_amt, a_t)
                sd = self.account_stats[d]
                if sd.outflow.n == 0 and sd.inflow.n == 0:
                    sd.quiet_before_first = a_t
                sd.add_in(a_amt, a_t)
            self.n_added += len(batch)
            self._pending.append((batch.t_end, src, dst, amount, lab))
        self._expire()

    def _expire(self) -> None:
        cutoff = self.now - self.window
        while self._pending and self._pending[0][0] <= cutoff:
            _, src, dst, amount, lab = self._pending.popleft()
            for i in range(src.shape[0]):
                s, d = int(src[i]), int(dst[i])
                k = pair_key(s, d)
                agg = self.pairs.get(k)
                if agg is None:
                    continue
                agg.remove(float(amount[i]), int(lab[i]))
                if agg.count <= 0:
                    del self.pairs[k]
                    self.out_adj[s].discard(d)
                    if not self.out_adj[s]:
                        del self.out_adj[s]
                    self.in_adj[d].discard(s)
                    if not self.in_adj[d]:
                        del self.in_adj[d]
            self.n_expired += src.shape[0]

    # -- inspection -----------------------------------------------------------

    def __len__(self) -> int:
        return len(self.pairs)

    @property
    def n_nodes(self) -> int:
        return len(set(self.out_adj) | set(self.in_adj))

    def neighbours(self, node: int) -> set[int]:
        """Counterparties in either direction.

        Direction is deliberately ignored for expansion: a mule receiving from
        one account and paying another is one structure, and following only
        out-edges would cut it in half.
        """
        return self.out_adj.get(node, set()) | self.in_adj.get(node, set())

    def degree(self, node: int) -> tuple[int, int]:
        return len(self.out_adj.get(node, ())), len(self.in_adj.get(node, ()))

    def volume(self, node: int) -> tuple[float, float]:
        out = sum(self.pairs[pair_key(node, d)].amount
                  for d in self.out_adj.get(node, ()))
        inc = sum(self.pairs[pair_key(s, node)].amount
                  for s in self.in_adj.get(node, ()))
        return out, inc

    def expand(self, seeds, hops: int = 2, max_nodes: int = 200,
               max_degree: int = 50) -> set[int]:
        """Bounded neighbourhood around `seeds`.

        `max_degree` is the hub guard. Expanding through a node with hundreds of
        counterparties pulls in an unrelated crowd and produces the giant
        garbage cluster that discredits this whole class of system, so such
        nodes are included but not traversed *through*.
        """
        seen: set[int] = set(seeds)
        frontier: set[int] = set(seeds)
        for _ in range(hops):
            nxt: set[int] = set()
            for node in frontier:
                nbrs = self.neighbours(node)
                if len(nbrs) > max_degree:
                    continue
                nxt |= nbrs - seen
            if not nxt:
                break
            room = max_nodes - len(seen)
            if room <= 0:
                break
            if len(nxt) > room:
                # Prefer the tightest-connected candidates rather than an
                # arbitrary slice, so truncation degrades gracefully.
                nxt = set(sorted(nxt, key=lambda n: len(self.neighbours(n)))[:room])
            seen |= nxt
            frontier = nxt
        return seen

    def subgraph_edges(self, nodes: set[int]) -> list[tuple[int, int, PairAgg]]:
        """Edges with both endpoints inside `nodes`."""
        out = []
        for s in nodes:
            for d in self.out_adj.get(s, ()):
                if d in nodes:
                    out.append((s, d, self.pairs[pair_key(s, d)]))
        return out

    def stats(self) -> dict:
        return {
            "pairs": len(self.pairs),
            "nodes": self.n_nodes,
            "window_minutes": self.window,
            "now": self.now,
            "added": self.n_added,
            "expired": self.n_expired,
        }
