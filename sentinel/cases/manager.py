"""Case lifecycle: promote candidates into a capacity-bounded queue.

Two decisions here are load-bearing.

**Capacity, not threshold.** A fixed score cut produces a flood or a drought as
the world drifts. An ops team has a fixed number of reviews per day, so the
queue is filled with the best available candidates up to that capacity and is
stable by construction.

**Control-arm sampling.** A small random share of *low-scoring* candidates is
promoted alongside the top-ranked ones. Without it the label corpus only ever
describes what the detector already finds: the next model faithfully inherits
this one's blind spots, and production recall cannot be estimated at all because
nothing outside the flagged set is ever reviewed. It costs a few percent of
analyst time and is the difference between a feedback loop and an echo chamber.
"""
from __future__ import annotations

import random

from sentinel.cases.case import Case, Lane
from sentinel.cases.store import CaseStore

# Reviews available per generation cycle.
DEFAULT_CAPACITY = 20

# Share of capacity spent on randomly-drawn unflagged candidates.
CONTROL_FRACTION = 0.10

# Below this a candidate goes to the low-confidence lane rather than the main
# queue, so uniform-looking confidence never trains analysts to distrust it all.
LOW_CONFIDENCE_SCORE = 0.15


class CaseManager:
    def __init__(self, store: CaseStore, stream=None, capacity: int = DEFAULT_CAPACITY,
                 control_fraction: float = CONTROL_FRACTION, seed: int = 7):
        self.store = store
        self.stream = stream
        self.capacity = capacity
        self.control_fraction = control_fraction
        self.rng = random.Random(seed)
        self.stats = {"promoted": 0, "control": 0, "low_confidence": 0,
                      "merged_into_existing": 0}

    # -- naming ---------------------------------------------------------------

    def _key(self, node_id: int) -> str:
        return self.stream.key(node_id) if self.stream else str(node_id)

    def _when(self, t: int) -> str:
        return self.stream.when(t).isoformat() if self.stream else str(t)

    # -- promotion ------------------------------------------------------------

    def select(self, candidates) -> list[tuple]:
        """Choose which candidates become cases this cycle.

        Returns (candidate, lane) pairs. Ranked candidates fill the primary
        capacity; the control arm is drawn from everything below the cut so it
        genuinely samples what the detector did *not* surface.
        """
        if not candidates:
            return []
        ordered = sorted(candidates, key=lambda c: -c.score)
        n_control = max(1, int(round(self.capacity * self.control_fraction))) \
            if self.control_fraction > 0 else 0
        n_primary = max(0, self.capacity - n_control)

        picked: list[tuple] = []
        for c in ordered[:n_primary]:
            lane = Lane.PRIMARY if c.score >= LOW_CONFIDENCE_SCORE else Lane.LOW_CONFIDENCE
            picked.append((c, lane))

        rest = ordered[n_primary:]
        if rest and n_control:
            for c in self.rng.sample(rest, min(n_control, len(rest))):
                picked.append((c, Lane.CONTROL))
        return picked

    def open_case(self, candidate, lane: Lane, graph) -> Case:
        """Freeze a candidate into an immutable, point-in-time case record."""
        members = sorted(self._key(n) for n in candidate.nodes)
        subgraph = [
            [self._key(s), self._key(d), agg.count, round(agg.amount, 2)]
            for s, d, agg in graph.subgraph_edges(set(candidate.nodes))
        ]
        at = self._when(candidate.t)
        case = Case(
            id=self.store.next_id(),
            opened_at=at,
            opened_t=candidate.t,
            lane=lane,
            members=members,
            seed=self._key(candidate.seed),
            score=round(candidate.score, 6),
            contrib={k: round(v, 6) for k, v in candidate.contrib.items()},
            features=candidate.features.to_dict(),
            motifs=candidate.motifs.to_dict(),
            subgraph=subgraph,
            absorbed=candidate.absorbed,
        )
        f = candidate.features
        case.log(at, "detect",
                 f"{case.size} accounts across {f.n_banks} banks"
                 + (f" and {f.n_countries} countries" if f.n_countries > 1 else "")
                 + f"; score {case.score:.3f}"
                 + (f"; corroborated by {candidate.absorbed} overlapping views"
                    if candidate.absorbed else ""))
        if f.has_cycle:
            case.log(at, "evidence",
                     f"Cycle of length {f.shortest_cycle} covering "
                     f"{f.cycle_coverage:.0%} of members.")
        if f.conservation >= 0.8:
            case.log(at, "evidence",
                     f"{f.conservation:.0%} value conservation across the "
                     f"boundary -- money in closely matches money out.")
        if f.scatter_gather_width >= 2:
            case.log(at, "evidence",
                     f"Scatter-gather of width {f.scatter_gather_width}.")

        self.store.open(case)
        self.stats["promoted"] += 1
        if lane is Lane.CONTROL:
            self.stats["control"] += 1
        elif lane is Lane.LOW_CONFIDENCE:
            self.stats["low_confidence"] += 1
        return case

    def promote(self, candidates, graph) -> list[Case]:
        return [self.open_case(c, lane, graph)
                for c, lane in self.select(candidates)]
