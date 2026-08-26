"""A simulated analyst, so the feedback loop can be demonstrated end to end.

In production the labels come from humans. Here they come from the ground truth
the benchmark ships, which lets the flywheel be *measured* rather than asserted:
replay, let the simulated analyst dispose cases, train the re-ranker on the
first half of the timeline, and see whether precision improves on the second.

This is a stand-in and is labelled as one everywhere it is used. It is also
deliberately imperfect, because a perfect oracle would make the experiment
meaningless -- a real queue is disposed by people who miss things, disagree, and
occasionally wave through a case they should not have.
"""
from __future__ import annotations

import random

from sentinel.cases.case import Verdict

# A real analyst working a ring case is not an oracle. These rates make the
# simulation honest rather than flattering; the re-ranker has to learn from
# noisy labels, which is what it will get in production.
MISS_RATE = 0.10        # a true ring dismissed
# Measured consequence of getting this wrong: at 3%, applied across a queue
# where only ~3% of cases contain a real ring, false confirmations *equalled*
# genuine ones and the label corpus was half noise -- the re-ranker learned
# nothing (every permutation importance came back ~0.000). Real analysts do not
# confirm 3% of visibly clean clusters, so this is both more realistic and the
# difference between a corpus that can train a model and one that cannot.
FALSE_CONFIRM = 0.005

# Below this share of a case's members belonging to one ring, an analyst who
# confirms it would be confirming mostly noise -- so it becomes partial.
PARTIAL_BELOW = 0.8


class SimulatedAnalyst:
    """Disposes cases from ground truth, with human-like error."""

    def __init__(self, seed: int = 7, miss_rate: float = MISS_RATE,
                 false_confirm: float = FALSE_CONFIRM):
        self.rng = random.Random(seed)
        self.miss_rate = miss_rate
        self.false_confirm = false_confirm
        self.stats = {"confirmed": 0, "partial": 0, "rejected": 0,
                      "missed": 0, "false_confirmed": 0}

    def dispose(self, case, truth_members: set[str]) -> tuple[Verdict, str, list, list]:
        """Return (verdict, reason, confirmed_members, dropped_members).

        `truth_members` is the set of account keys in the ground-truth ring that
        this case overlaps, or empty if it overlaps none.
        """
        members = set(case.members)
        overlap = members & truth_members

        if not overlap:
            if self.rng.random() < self.false_confirm:
                self.stats["false_confirmed"] += 1
                self.stats["confirmed"] += 1
                return Verdict.CONFIRMED_RING, "mule_network", sorted(members), []
            self.stats["rejected"] += 1
            return (Verdict.NOT_A_RING, "coincidental_structure", [],
                    sorted(members))

        if self.rng.random() < self.miss_rate:
            self.stats["missed"] += 1
            self.stats["rejected"] += 1
            return (Verdict.NOT_A_RING, "insufficient_linkage", [],
                    sorted(members))

        share = len(overlap) / len(members)
        if share >= PARTIAL_BELOW:
            self.stats["confirmed"] += 1
            return Verdict.CONFIRMED_RING, "layering", sorted(members), []

        # The most informative label available: positives and negatives inside
        # one subgraph.
        self.stats["partial"] += 1
        return (Verdict.CONFIRMED_PARTIAL, "subset_confirmed",
                sorted(overlap), sorted(members - overlap))
