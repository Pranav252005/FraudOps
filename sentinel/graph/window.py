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
        # Per-node total in/out value *inside the window*, maintained
        # incrementally at O(1) per edge. These exist so candidate boundary
        # flow can be computed by an identity rather than by walking every
        # member's whole adjacency:
        #
        #   external_inflow(C) = sum_{n in C} total_in[n] - sum_{internal} amt
        #
        # which is exact because every edge into a member is either internal to
        # C (counted once in the internal sum) or external. Unlike
        # `account_stats`, these ARE expired with the window: they describe the
        # window's graph, which is what boundary flow is a property of.
        self.total_in: dict[int, float] = defaultdict(float)
        self.total_out: dict[int, float] = defaultdict(float)
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
                self.total_out[s] += a_amt
                self.total_in[d] += a_amt
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
                # Kept strictly paired with `agg.remove` -- inside the same
                # `agg is not None` branch as the add side is paired with
                # `agg.add` -- so the totals can never drift from what `pairs`
                # actually holds. A drift here would not raise; it would
                # silently return a wrong inflow, which is this codebase's
                # characteristic failure mode. `check_invariants()` asserts the
                # pairing directly.
                a_amt = float(amount[i])
                self.total_out[s] -= a_amt
                self.total_in[d] -= a_amt
                if agg.count <= 0:
                    del self.pairs[k]
                    self.out_adj[s].discard(d)
                    if not self.out_adj[s]:
                        del self.out_adj[s]
                    self.in_adj[d].discard(s)
                    if not self.in_adj[d]:
                        del self.in_adj[d]
                    # Reset the running total to an exact zero whenever the
                    # node empties, keyed on adjacency rather than on the float
                    # being == 0.0. Incremental float accumulation leaves a
                    # residue (a+b-a-b is not exactly 0 in binary floating
                    # point); without this reset that residue would persist on
                    # a node with no edges left and be reported as boundary
                    # flow. Bounding it to nodes that stay continuously live is
                    # the difference between a rounding artifact and a wrong
                    # answer that never raises.
                    if s not in self.out_adj:
                        self.total_out.pop(s, None)
                    if d not in self.in_adj:
                        self.total_in.pop(d, None)
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
        return self.expand_traced(seeds, hops=hops, max_nodes=max_nodes,
                                   max_degree=max_degree)[0]

    def expand_traced(self, seeds, hops: int = 2, max_nodes: int = 200,
                      max_degree: int = 50) -> tuple[set[int], dict]:
        """`expand`, plus a record of *why* it stopped where it did.

        The funnel measurement (scripts/eval_funnel.py) showed BIPARTITE and
        STACK rings are seeded at 90-100% but produce a covering candidate
        only 3% and 13% of the time -- the loss is here, in expansion, not in
        seeding. Distinguishing "the hub guard refused to traverse", "the node
        cap truncated", and "expansion simply ran out of graph" is what turns
        that into an actionable change, so the trace is produced by the real
        expansion path rather than by a reimplementation that could drift
        from it.
        """
        seen: set[int] = set(seeds)
        frontier: set[int] = set(seeds)
        trace = {"hops_completed": 0, "hub_blocked": 0, "truncated": False,
                 "exhausted": False, "hit_node_cap": False}
        for _ in range(hops):
            nxt: set[int] = set()
            for node in frontier:
                nbrs = self.neighbours(node)
                if len(nbrs) > max_degree:
                    trace["hub_blocked"] += 1
                    continue
                nxt |= nbrs - seen
            if not nxt:
                trace["exhausted"] = True
                break
            room = max_nodes - len(seen)
            if room <= 0:
                trace["hit_node_cap"] = True
                break
            if len(nxt) > room:
                # Prefer the tightest-connected candidates rather than an
                # arbitrary slice, so truncation degrades gracefully.
                nxt = set(sorted(nxt, key=lambda n: len(self.neighbours(n)))[:room])
                trace["truncated"] = True
            seen |= nxt
            frontier = nxt
            trace["hops_completed"] += 1
        return seen, trace

    def subgraph_edges(self, nodes: set[int]) -> list[tuple[int, int, PairAgg]]:
        """Edges with both endpoints inside `nodes`."""
        out = []
        for s in nodes:
            for d in self.out_adj.get(s, ()):
                if d in nodes:
                    out.append((s, d, self.pairs[pair_key(s, d)]))
        return out

    def check_invariants(self, sample: int | None = None) -> None:
        """Assert the incrementally maintained state still matches `pairs`.

        `total_in` / `total_out` are maintained by O(1) deltas on every add and
        expire. That is fast and it is also exactly the shape of defect this
        codebase keeps a catalogue of: if the two sides ever stop being paired,
        nothing raises -- candidates simply get a wrong boundary flow. So the
        pairing is checkable, and the check runs in the test suite and in CI.

        Floating-point accumulation means the running total will not be
        bit-identical to a fresh sum over `pairs`, so the comparison is a
        relative tolerance, not equality. `sample` limits the check to the
        first N nodes for use on a large live window.
        """
        from_pairs_out: dict[int, float] = defaultdict(float)
        from_pairs_in: dict[int, float] = defaultdict(float)
        for k, agg in self.pairs.items():
            s, d = unpair(k)
            from_pairs_out[s] += agg.amount
            from_pairs_in[d] += agg.amount

        assert set(self.total_out) == set(from_pairs_out), (
            "total_out node set diverged from pairs: "
            f"{len(self.total_out)} vs {len(from_pairs_out)}")
        assert set(self.total_in) == set(from_pairs_in), (
            "total_in node set diverged from pairs: "
            f"{len(self.total_in)} vs {len(from_pairs_in)}")

        for name, running, fresh in (("out", self.total_out, from_pairs_out),
                                      ("in", self.total_in, from_pairs_in)):
            for i, (n, want) in enumerate(fresh.items()):
                if sample is not None and i >= sample:
                    break
                got = running[n]
                scale = max(abs(want), abs(got), 1.0)
                assert abs(got - want) <= 1e-6 * scale, (
                    f"total_{name}[{n}] drifted: running={got!r} "
                    f"recomputed={want!r}")

        assert self.n_added - self.n_expired == sum(a.count for a in self.pairs.values()),             "window conservation broken: added - expired != sum of pair counts"

    def stats(self) -> dict:
        return {
            "pairs": len(self.pairs),
            "nodes": self.n_nodes,
            "window_minutes": self.window,
            "now": self.now,
            "added": self.n_added,
            "expired": self.n_expired,
        }
