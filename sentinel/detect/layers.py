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
