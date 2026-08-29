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

# Slack on the size pre-rejection bound (see `suppress`). Sizes are integers,
# so anything well under 1.0 can only ever admit extra rivals to the exact
# jaccard test -- never exclude one -- which is what keeps the optimisation
# output-identical rather than merely nearly so.
SIZE_BOUND_SLACK = 1e-9


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

        # Size-bound pre-rejection. J(A,B) = |A&B| / |A|B| <= min/max, so
        # J >= t is impossible unless t*|A| <= |B| <= |A|/t. Comparing two
        # integers rules out most rivals before any set intersection is built,
        # and because the bound is a *necessary* condition for J >= t, the set
        # of rivals that pass `jaccard(...) >= threshold` is unchanged -- so is
        # the first one found in iteration order, and so is the winner. The
        # profile counted 21.5M jaccard calls in `suppress`, 15.4% of cycle
        # time; most of them cannot possibly clear the threshold.
        # Written as min >= t*max on the two integer sizes rather than as a
        # precomputed size window, so the only floating-point step is one
        # multiply of an integer by the threshold. SIZE_BOUND_SLACK absorbs
        # that multiply's rounding: candidate sizes are integers, so a slack
        # far below 1 cannot admit a size that the exact bound excludes, but it
        # does guarantee a size sitting exactly on the bound is never dropped.
        n_a = len(cand.nodes)

        winner = None
        for j in rivals:
            other = ordered[j].nodes
            n_b = len(other)
            if n_a < n_b:
                n_min, n_max = n_a, n_b
            else:
                n_min, n_max = n_b, n_a
            if n_min < threshold * n_max - SIZE_BOUND_SLACK:
                continue
            if jaccard(cand.nodes, other) >= threshold:
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
