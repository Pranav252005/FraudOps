"""Stage-wise, per-typology recall across the whole detection funnel.

    seed-reachable -> seeded -> built (candidate generated) -> ranked (top-k)

Every accuracy number this project reports upstream of this module is
uninterpretable without knowing which stage lost the ring. This module makes
that loss visible and quantified, broken down by typology, and is
dataset-agnostic: it only needs ring membership, a typology label, and the
generator's own candidates -- not anything specific to AMLworld.

**CORRECTION, 2026-09-04.** This docstring used to state that "only ~26% of
active rings become candidates at all, and BIPARTITE / FAN-OUT / RANDOM /
STACK generate 0%, because the seed rule requires a pass-through account and
those typologies contain no pass-through account by construction."

**That is wrong and had already been corrected in docs/HANDOFF.md 5b on
2026-08-26; this docstring was simply never updated.** The seed rule checks
whether an account is pass-through against its whole position in the window
graph, not against its role inside one ring -- and AMLworld's background
traffic gives almost every active account both inbound and outbound edges. So
the four typologies named above are seeded at 83-100%, not 0%.

The measured funnel (data/funnel.json, 34 cycles, 259 rings) says seeding is
the SMALLEST of the three losses:

    seeding  11.2 points     build  26.6 points     ranking  39.8 points

Leaving the stale claim here cost something real: docs/graph-review/2026-09-04.md
2a read this docstring rather than the data and ranked a second seed predicate
as "the single largest structural recall loss in the funnel", which it is not.
See prereg/seed_predicate.md, which corrects the premise before the experiment
that rested on it was run.

A ring only needs to clear a stage once across the whole eval run; stages are
tracked as a boolean OR over every cycle in which the ring is active.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

STAGES = ("seed_reachable", "seeded", "built", "ranked")

HIT_SHARE = 0.5
MIN_JACCARD = 0.3


def is_hit(candidate_nodes: set[int], ring_nodes: set[int],
           hit_share: float = HIT_SHARE, min_jaccard: float = MIN_JACCARD) -> bool:
    """A candidate "covers" a ring: containment floor plus a Jaccard floor.

    Containment alone rewards bulk -- a 158-node candidate trivially contains
    half of a 4-account ring -- which is why a bare containment metric once
    tied a baseline that ranks by node count. See docs/PHASE0-FINDINGS.md.
    """
    inter = candidate_nodes & ring_nodes
    if not inter:
        return False
    if len(inter) / len(ring_nodes) < hit_share:
        return False
    if len(inter) / len(candidate_nodes | ring_nodes) < min_jaccard:
        return False
    return True


@dataclass
class FunnelTracker:
    """Accumulates stage-reached flags for every ring seen across an eval run."""

    rank_k: int = 50
    _reached: dict = field(default_factory=lambda: defaultdict(dict))
    _typology: dict = field(default_factory=dict)

    def _mark(self, ring: int, typ: str | None, stage: str) -> None:
        self._typology[ring] = typ or "UNKNOWN"
        self._reached[ring][stage] = True

    def observe_cycle(self, rings: dict, typology_of, seed_nodes: set[int],
                       candidates: list, rank_k: int | None = None) -> None:
        """Record one generation cycle's contribution to every ring's funnel.

        `rings`: ring_id -> set of member node ids active in this cycle's
        window. `typology_of(ring_id)` -> typology label. `seed_nodes`: the
        accounts this cycle's seed rule actually fired on. `candidates`:
        this cycle's emitted candidates, in rank order (best first) -- exactly
        what the generator returns, so "built" and "ranked" are measured
        against what a real run would have queued.
        """
        k = self.rank_k if rank_k is None else rank_k
        for ring, members in rings.items():
            typ = typology_of(ring)
            self._mark(ring, typ, "seed_reachable")
            if members & seed_nodes:
                self._mark(ring, typ, "seeded")

        for rank, c in enumerate(candidates):
            nodes = set(c.nodes)
            for ring, members in rings.items():
                if not is_hit(nodes, members):
                    continue
                typ = typology_of(ring)
                self._mark(ring, typ, "built")
                if rank < k:
                    self._mark(ring, typ, "ranked")

    # -- reporting --------------------------------------------------------

    def rings(self) -> dict[int, dict]:
        """ring_id -> {"typology": str, "seed_reachable": bool, ...}."""
        out = {}
        for ring, stages in self._reached.items():
            out[ring] = {"typology": self._typology[ring],
                         **{s: stages.get(s, False) for s in STAGES}}
        return out

    def table(self) -> dict[str, dict[str, int]]:
        """typology -> {"total": n, "seed_reachable": n, "seeded": n, ...}."""
        by_typ: dict[str, dict[str, int]] = defaultdict(
            lambda: {"total": 0, **{s: 0 for s in STAGES}})
        for ring, stages in self._reached.items():
            typ = self._typology[ring]
            row = by_typ[typ]
            row["total"] += 1
            for s in STAGES:
                if stages.get(s):
                    row[s] += 1
        return dict(by_typ)

    def totals(self) -> dict[str, int]:
        row = {"total": 0, **{s: 0 for s in STAGES}}
        for stages in self._reached.values():
            row["total"] += 1
            for s in STAGES:
                if stages.get(s):
                    row[s] += 1
        return row

    def to_rows(self) -> list[dict]:
        """Flat rows for CSV: one row per typology, stage counts and recalls."""
        rows = []
        table = self.table()
        for typ in sorted(table):
            row = table[typ]
            total = row["total"]
            out = {"typology": typ, "total": total}
            for s in STAGES:
                out[s] = row[s]
                out[f"{s}_recall"] = (row[s] / total) if total else 0.0
            rows.append(out)
        t = self.totals()
        total = t["total"]
        out = {"typology": "TOTAL", "total": total}
        for s in STAGES:
            out[s] = t[s]
            out[f"{s}_recall"] = (t[s] / total) if total else 0.0
        rows.append(out)
        return rows
