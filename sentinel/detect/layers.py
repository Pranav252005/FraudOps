"""Layered structure: GARG-AML block density, plus BIPARTITE and STACK.

GARG-AML (2025) scores a neighbourhood by how closely it resembles a pure
smurfing pattern. In the directed formulation, nodes are assigned to three
levels -- senders (0), mules (1), receivers (2) -- the adjacency matrix is
partitioned into the nine level-to-level blocks, and the score is

    mean(density of the high blocks 0->1 and 1->2)
        - mean(density of the other seven)

In a pure smurfing structure value flows strictly 0 -> 1 -> 2, so those two
blocks are full and the rest are empty, giving a score near 1. Noise in any
other block pulls it down.

The same decomposition answers the two typologies this project scores worst on.
BIPARTITE is a two-layer structure (sources straight to sinks, no intermediary)
and STACK is the three-layer version. v1 had no detector for either, and scored
3% and 7% on them.

Every measure here is a density in a named block, so an analyst can be shown
exactly which part of the structure drove the score. That interpretability is
GARG-AML's argument for preferring this over a graph neural network, and it is
the reason the case file can explain itself at all.
"""
from __future__ import annotations

from dataclasses import dataclass

import networkx as nx

# Level indices, named so the block table reads as the paper describes it.
SENDER, MULE, RECEIVER = 0, 1, 2

# The two blocks that should be dense in a pure smurfing structure.
HIGH_BLOCKS = ((SENDER, MULE), (MULE, RECEIVER))


@dataclass
class LayerProfile:
    """The layered read of one candidate subgraph."""

    n_senders: int = 0
    n_mules: int = 0
    n_receivers: int = 0
    depth: int = 0                 # how many levels are populated

    gargaml: float = 0.0           # -1..1, resemblance to pure smurfing
    high_density: float = 0.0
    low_density: float = 0.0

    bipartite: float = 0.0         # density of sender->receiver, 2-layer shape
    stack: float = 0.0             # strength of the 3-layer shape
    blocks: dict = None

    def to_dict(self) -> dict:
        return {
            "n_senders": self.n_senders, "n_mules": self.n_mules,
            "n_receivers": self.n_receivers, "depth": self.depth,
            "gargaml": round(self.gargaml, 4),
            "high_density": round(self.high_density, 4),
            "low_density": round(self.low_density, 4),
            "bipartite": round(self.bipartite, 4),
            "stack": round(self.stack, 4),
        }


def assign_levels(G: nx.DiGraph) -> dict[int, int]:
    """Place every node on a sender / mule / receiver level.

    A node that only sends is a sender, one that only receives is a receiver,
    and one that does both is a mule -- the pass-through role that is the whole
    mule signature. Isolated nodes are dropped rather than defaulted, since
    assigning them a level would put mass in a block they do not belong to.
    """
    levels: dict[int, int] = {}
    for n in G:
        has_in = G.in_degree(n) > 0
        has_out = G.out_degree(n) > 0
        if has_in and has_out:
            levels[n] = MULE
        elif has_out:
            levels[n] = SENDER
        elif has_in:
            levels[n] = RECEIVER
    return levels


def block_densities(G: nx.DiGraph, levels: dict[int, int]) -> dict[tuple, float]:
    """Density of each of the nine level-to-level blocks.

    Density is edges present over edges possible between the two level sets.
    The diagonal blocks exclude self-pairs, so a level of one node has no
    possible internal edge and reports 0 rather than dividing by zero.
    """
    members: dict[int, list[int]] = {SENDER: [], MULE: [], RECEIVER: []}
    for n, lvl in levels.items():
        members[lvl].append(n)

    out: dict[tuple, float] = {}
    for a in (SENDER, MULE, RECEIVER):
        for b in (SENDER, MULE, RECEIVER):
            src, dst = members[a], members[b]
            if not src or not dst:
                out[(a, b)] = 0.0
                continue
            possible = len(src) * len(dst) - (len(src) if a == b else 0)
            if possible <= 0:
                out[(a, b)] = 0.0
                continue
            present = sum(1 for s in src for d in dst
                          if s != d and G.has_edge(s, d))
            out[(a, b)] = present / possible
    return out


def profile(G: nx.DiGraph) -> LayerProfile:
    """Full layered read: GARG-AML score, bipartite and stack strength."""
    p = LayerProfile(blocks={})
    if G.number_of_nodes() == 0:
        return p

    levels = assign_levels(G)
    if not levels:
        return p

    p.n_senders = sum(1 for v in levels.values() if v == SENDER)
    p.n_mules = sum(1 for v in levels.values() if v == MULE)
    p.n_receivers = sum(1 for v in levels.values() if v == RECEIVER)
    p.depth = sum(1 for c in (p.n_senders, p.n_mules, p.n_receivers) if c)

    blocks = block_densities(G, levels)
    p.blocks = {f"{a}->{b}": round(v, 4) for (a, b), v in blocks.items()}

    high = [blocks[k] for k in HIGH_BLOCKS]
    low = [v for k, v in blocks.items() if k not in HIGH_BLOCKS]
    p.high_density = sum(high) / len(high)
    p.low_density = sum(low) / len(low) if low else 0.0
    p.gargaml = p.high_density - p.low_density

    # BIPARTITE: sources feeding sinks directly, with no intermediary layer.
    # Requiring both sides to have width is what separates the pattern from a
    # single fan-out, which is a different typology with its own detector.
    if p.n_senders >= 2 and p.n_receivers >= 2:
        p.bipartite = blocks[(SENDER, RECEIVER)]

    # STACK: the three-layer version. Both hops must carry weight, so the
    # weaker of the two bounds the score -- a strong first hop into a dead end
    # is not a stack.
    if p.n_senders and p.n_mules and p.n_receivers:
        p.stack = min(blocks[(SENDER, MULE)], blocks[(MULE, RECEIVER)])

    return p


# ---------------------------------------------------------------------------
# Per-node score, for seeding (experiment S1)
# ---------------------------------------------------------------------------
#
# Everything above operates on a *candidate subgraph* -- it needs a candidate
# to already exist, which means it can only ever describe what seeding already
# reached. `docs/graph-review/2026-09-04.md` §2a names the consequence: the
# pass-through seed rule cannot reach BIPARTITE / FAN-OUT / RANDOM / STACK by
# construction, because those typologies contain no account with money in AND
# out, and no amount of scoring rescues a candidate that was never built.
#
# What GARG-AML contributes that this file does not yet use is a score defined
# for EVERY node from its own neighbourhood, with no candidate required --
# including nodes with no pass-through.
#
# HONESTY ABOUT PROVENANCE, because the standing rule is that no parity claim
# against a surveyed project may enter this repo without a head-to-head run on
# this machine (docs/EXPERIMENT-QUEUE.md X1):
#
#   Taken from GARG-AML (arXiv:2506.04292): the idea of scoring a node by how
#   closely the adjacency structure of its own neighbourhood resembles a pure
#   smurfing pattern, read as block densities, as a single interpretable
#   number.
#
#   NOT taken, and not claimed: the paper's exact second-order construction,
#   its normalisation, or its reported performance. The functional form below
#   is this project's, chosen to be computable at seeding cost over every
#   touched account in a tick. **This is not an implementation of GARG-AML and
#   no result from it may be quoted as a comparison against GARG-AML.**

# Width at which the shape term saturates. 5 matches `_norm(x, 5)` in
# features.py for the scatter/gather widths, so "wide enough to matter" means
# the same thing at seeding as it does at scoring.
SMURF_WIDTH_SATURATION = 5


def _participates(u: int, targets: set[int], graph) -> bool:
    """Does `u` send to anything in `targets`? Early-exits on the first hit.

    Iterates whichever side is smaller. The mean full-graph degree of a node in
    this window is in the hundreds while `targets` is capped in the tens, so
    picking the smaller side is the difference between a usable seeding cost
    and an unusable one.
    """
    outs = graph.out_adj.get(u)
    if not outs:
        return False
    if len(outs) <= len(targets):
        return any(v in targets for v in outs)
    return any(v in outs for v in targets)


def _participation(src: set[int], dst: set[int], graph) -> float:
    """Fraction of `src` with at least one edge into `dst`.

    WHY PARTICIPATION AND NOT PAIRWISE DENSITY, which is what the block-density
    machinery above uses and what GARG-AML's formulation reads. Pairwise
    density divides by |src| x |dst|, so it shrinks quadratically as the
    neighbourhood widens -- six contaminating edges among ten counterparties
    score 0.05, and the term is effectively inert at exactly the widths that
    matter for laundering. Measured on synthetic shapes during design: a
    visibly contaminated hub scored 0.95 against a pure one at 1.00, a
    separation too small to rank on.

    Participation asks the question the shape actually poses -- "how many of
    these senders are doing something other than feeding the hub" -- and does
    not decay with width.

    **This is a deliberate deviation from GARG-AML's formulation**, recorded
    here rather than glossed, and it is one of the reasons nothing produced by
    this function may be quoted as a GARG-AML result.
    """
    if not src or not dst:
        return 0.0
    return sum(1 for u in src if _participates(u, dst, graph)) / len(src)


def node_smurf_score(graph, node: int, max_width: int = 50) -> tuple[float, int]:
    """(score, width) for one node, from its immediate neighbourhood.

    A pure pass-through or fan shape has senders feeding the node and the node
    feeding receivers, and **nothing else**: the senders do not pay each other,
    the receivers do not pay each other, and no sender reaches a receiver
    without going through the node. Every one of those "and nothing else"
    clauses is a block density that should be zero, so the cleanliness term is
    one minus their mean.

    Cleanliness alone is not enough and the reason is worth stating, because it
    is the difference between this predicate and its own control arm. In a
    sparse window most nodes have a neighbourhood with no internal edges at
    all, so cleanliness is 1.0 for the majority of accounts and carries almost
    no information on its own -- selection would collapse to ranking by degree,
    which is exactly what experiment S2 does. So the score is cleanliness times
    a saturating width term, and S2 exists to measure whether the cleanliness
    factor earned anything over width alone.

    `max_width` is the hub guard, matching `EXPAND_MAX_DEGREE`. A node with
    hundreds of counterparties is not a mule and expanding from it is already
    refused downstream, so scoring it would only spend time to reject it. The
    measured mean full-graph degree of a candidate member in this window is in
    the hundreds with a maximum in the thousands, so this bound is load-bearing
    for cost, not cosmetic.

    Returns 0.0 for an isolated node and for a hub, so callers can rank without
    special-casing either.
    """
    ins = graph.in_adj.get(node)
    outs = graph.out_adj.get(node)
    S = (set(ins) - {node}) if ins else set()
    R = (set(outs) - {node}) if outs else set()
    width_raw = len(S) + len(R)
    if width_raw == 0 or width_raw > max_width:
        return 0.0, width_raw

    # The relations a pure pattern does not contain.
    low = [
        _participation(S, S, graph),    # senders paying each other
        _participation(R, R, graph),    # receivers paying each other
        _participation(S, R, graph),    # bypass: sender straight to receiver
        _participation(R, S, graph),    # backflow
    ]
    # Counterparties on both sides at once -- an ordinary trading relationship
    # rather than a one-way hop. Counted as contamination on whichever sides
    # exist.
    both = len(S & R)
    if S:
        low.append(both / len(S))
    if R:
        low.append(both / len(R))
    cleanliness = 1.0 - (sum(low) / len(low))

    # Width: for a layering shape the evidence is the narrower side, since a
    # node with 40 senders and 1 receiver is a collector, not a layer. For a
    # one-sided fan shape there is no narrower side, so the single side counts
    # at half weight -- one-sided evidence is real (it is exactly what the
    # pass-through rule cannot see) but weaker.
    if S and R:
        effective = min(len(S), len(R))
    else:
        effective = max(len(S), len(R)) / 2.0
    width = min(1.0, effective / SMURF_WIDTH_SATURATION)

    return max(0.0, cleanliness) * width, width_raw
