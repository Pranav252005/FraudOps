"""Overlap suppression: collapse near-duplicate candidates before ranking.

Exact member-set dedup removed only 23 of 14,001 candidates in a measured tick.
Expansions from adjacent seeds produce overlapping-but-distinct sets, so the
queue fills with many views of the same neighbourhood and the top-k burns its
slots re-showing one region.

This keeps the highest-scoring representative of each overlapping group and
suppresses the rest, recording what was absorbed so the case file can show
"discovered from 7 seeds" rather than silently dropping evidence.

Suppression rather than union: merging node sets would grow candidates, and
candidate size is already a measured confound -- the `size` baseline tied the
score until the evaluation metric was corrected for it.
"""
from __future__ import annotations

from collections import defaultdict

# Two candidates overlapping this much are treated as the same finding. Distinct
# rings rarely share half their members; adjacent expansions of one ring
# routinely do.
DEFAULT_THRESHOLD = 0.5


def jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if not inter:
        return 0.0
    return inter / len(a | b)


def suppress(candidates, threshold: float = DEFAULT_THRESHOLD):
    """Greedy non-maximum suppression over candidate member sets.

    Candidates must already be scored. Returns the surviving list, still in
    score order, with `absorbed` populated on each survivor.

    An inverted node->candidate index keeps this near-linear: only candidates
    sharing at least one member can overlap at all, so the 14k x 14k pairwise
    comparison never happens.
    """
    ordered = sorted(candidates, key=lambda c: -c.score)
    by_node: dict[int, list[int]] = defaultdict(list)
    suppressed: set[int] = set()
    kept: list = []

    for i, cand in enumerate(ordered):
        if i in suppressed:
            continue

        # Only candidates already kept and sharing a node can absorb this one.
        rivals: set[int] = set()
        for n in cand.nodes:
            rivals.update(by_node.get(n, ()))

        winner = None
        for j in rivals:
            if jaccard(cand.nodes, ordered[j].nodes) >= threshold:
                winner = j
                break

        if winner is not None:
            ordered[winner].absorbed += 1
            ordered[winner].absorbed_seeds.append(cand.seed)
            suppressed.add(i)
            continue

        kept.append(cand)
        for n in cand.nodes:
            by_node[n].append(i)

    return kept
