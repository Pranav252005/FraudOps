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

# -- suppression ordering (experiment B3) ------------------------------------
#
# WHICH candidate survives an overlapping group is decided by this ordering, so
# ordering by score means the SCORE PARTICIPATES IN GENERATION: changing a blend
# weight changes the candidate set, not just its order. That is recorded in
# docs/HANDOFF-NEXT.md, sentinel/corpus/__init__.py and
# docs/graph-review/2026-09-04.md 2b, and it is what makes every scorer A/B in
# this repository structurally confounded.
#
# A score-free key decouples the two: the pool becomes a function of the
# generator alone, so a scorer experiment measures the scorer. The cost is that
# the highest-scoring representative is no longer the one kept.
#
# `score` is the shipped default and is byte-identical to the original
# implementation, including its lack of a tie-break -- Python's sort is stable,
# so ties preserve insertion order, and reproducing the headline requires
# reproducing that.
SUPPRESS_SCORE = "score"
SUPPRESS_LARGEST = "largest"      # the review's proposal
SUPPRESS_SMALLEST = "smallest"
SUPPRESS_KEY = "key"
SUPPRESS_ORDERINGS = (SUPPRESS_SCORE, SUPPRESS_LARGEST, SUPPRESS_SMALLEST,
                      SUPPRESS_KEY)

# Every score-free ordering breaks ties on `canonical_key`, which is a pure
# function of the member set, so the surviving pool cannot depend on set
# iteration order or on PYTHONHASHSEED.
_ORDER_KEYS = {
    SUPPRESS_SCORE: lambda c: -c.score,
    SUPPRESS_LARGEST: lambda c: (-len(c.nodes), c.key),
    SUPPRESS_SMALLEST: lambda c: (len(c.nodes), c.key),
    SUPPRESS_KEY: lambda c: c.key,
}


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


def suppress(candidates, threshold: float = DEFAULT_THRESHOLD,
             ordering: str = SUPPRESS_SCORE):
    """Greedy non-maximum suppression over candidate member sets.

    Candidates must already be scored. Returns the surviving list, in
    `ordering` order, with `absorbed` populated on each survivor.

    `ordering` decides WHICH member of an overlapping group survives, and
    therefore which candidates exist at all. Under the shipped `score`
    ordering that makes the scorer part of the generator; under any
    score-free ordering the emitted member sets are a function of the
    generator alone. See the constants above and prereg/suppression_key.md.

    An inverted node->candidate index keeps this near-linear: only candidates
    sharing at least one member can overlap at all, so the 14k x 14k pairwise
    comparison never happens.
    """
    try:
        order_key = _ORDER_KEYS[ordering]
    except KeyError:
        raise ValueError(f"unknown suppression ordering {ordering!r}; "
                         f"expected one of {SUPPRESS_ORDERINGS}") from None
    ordered = sorted(candidates, key=order_key)
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
