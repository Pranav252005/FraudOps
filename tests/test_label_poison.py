"""Rule 8 (proposed), runtime half: poison the label, demand the same answer.

`tests/test_measured_path_closure.py` bans `PairAgg.laundering` statically on
every measured path. That check reads source, so it is defeated by anything
the parser cannot resolve to a name -- `getattr(agg, "laun" + "dering")`, an
alias bound at runtime, a read through `vars()` or `dataclasses.asdict()`.

This file closes that from the other end and does not care how the label is
reached. It randomises the ground-truth label on every edge of the committed
fixture and asserts the pipeline's entire output is bit-identical: the same
candidates, the same member sets, the same features, the same scores, the same
rank order, the same generator statistics. Any read of the label, by any
syntax, moves that fingerprint.

WHY THIS IS THE STRONGER HALF. The static walk answers "did anyone write the
name". This answers "does the answer depend on the truth", which is the
property actually wanted. The static walk stays because it fails fast, on a
diff, with a line number, and needs no fixture.

WHAT IT DOES NOT COVER. Only the paths the fixture exercises: seeding,
expansion, pruning, dedup, suppression, motifs, the feature block and ranking.
A label read inside the re-ranker, the case layer or the narrative path is not
covered here -- the static walk is what covers those, and the `sentinel/detect`
and `sentinel/learn` scan in the closure test is what covers the ranker's
source. Stated rather than left for a reader to discover, because an
undocumented blind spot in a guard is worse than a missing guard.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import ci_gates  # noqa: E402  (needs the sys.path line above)

# Two seeds, not one. A single draw that happened to leave the pipeline's
# output unmoved by coincidence is not a result -- though with ~10^5 edges the
# chance is negligible, this is cheap and the project's standing habit is to
# not rely on "negligible".
POISON_SEEDS = (1, 20260904)


@pytest.fixture(scope="module")
def clean():
    return ci_gates.run_fixture()


def test_the_poison_actually_reaches_the_pair_counter():
    """Establish that the perturbation lands where the leak surface is.

    If the poisoned labels never reached `PairAgg.laundering`, every assertion
    below would pass while testing nothing -- the exact failure this project
    keeps a bug catalogue for. So the counter is compared directly, before any
    claim is made about the pipeline being insensitive to it.
    """
    import numpy as np

    from sentinel.config import TICK_MINUTES, WINDOW_MINUTES
    from sentinel.graph.window import WindowedGraph
    from sentinel.stream.replay import Stream

    def counters(seed):
        stream = Stream(ci_gates.FIXTURE)
        if seed is not None:
            stream.is_laundering = np.random.default_rng(seed).integers(
                0, 2, size=stream.is_laundering.shape,
                dtype=stream.is_laundering.dtype)
        graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
        for i, b in enumerate(stream.ticks(TICK_MINUTES, end=None)):
            graph.add_batch(b)
            if i >= 40:
                break
        return sorted((k, a.laundering) for k, a in graph.pairs.items())

    base = counters(None)
    poisoned = counters(POISON_SEEDS[0])
    assert base != poisoned, (
        "poisoning `is_laundering` did not change `PairAgg.laundering`; the "
        "poison never reaches the surface this test exists to guard")
    # Same pairs, different labels -- so the graph's structure is untouched
    # and only the label moved. Otherwise the test below would be comparing
    # two different graphs and would prove nothing about label independence.
    assert [k for k, _ in base] == [k for k, _ in poisoned]


@pytest.mark.parametrize("seed", POISON_SEEDS)
def test_pipeline_output_is_identical_under_label_poison(clean, seed):
    """The gate. Every candidate, feature, score and rank, bit-identical."""
    poisoned = ci_gates.run_fixture(label_poison=seed)
    assert ci_gates.fingerprint(poisoned) == ci_gates.fingerprint(clean), (
        f"the pipeline's output changed when the ground-truth label was "
        f"randomised (seed {seed}). Something on the detect path is reading "
        f"the label. See docs/EXPERIMENT-QUEUE.md L1.")


def test_generator_statistics_are_identical_under_label_poison(clean):
    """`gen.stats` is in the fingerprint, but assert it separately too.

    The counts (seeds, expanded, deduped, suppressed, pruned_nodes) are the
    cheapest thing to read in a failure report, and a diff here localises a
    leak to a stage rather than to "somewhere in the pipeline".
    """
    poisoned = ci_gates.run_fixture(label_poison=POISON_SEEDS[0])
    assert poisoned["stats"] == clean["stats"]


def test_measured_metrics_are_identical_under_label_poison(clean):
    """p@k and ring recall, not just the candidate fingerprint.

    The fingerprint covers what the detector decided. This covers what gets
    reported, which is the thing a leak would actually inflate.
    """
    poisoned = ci_gates.run_fixture(label_poison=POISON_SEEDS[0])
    assert ci_gates.metrics(poisoned) == ci_gates.metrics(clean)


def test_the_poison_test_would_catch_a_planted_leak(monkeypatch, clean):
    """The negative control. A guard that cannot fail is not evidence.

    Plants exactly the defect the review described: a feature computed from
    `PairAgg.laundering`, reached through `subgraph_edges` the way
    `features.build` already receives it. If the fingerprint does NOT move
    here, then every assertion above is passing vacuously and the guard is
    theatre.
    """
    from sentinel.detect import features as F

    real_build = F.build

    # `*args, **kwargs` deliberately: `features.build` has gained parameters
    # before (`internal_edges`, threaded in to kill a duplicate
    # `subgraph_edges` call) and a control that breaks on the next signature
    # change is a control that quietly stops being run.
    def leaky_build(nodes, graph, motifs, *args, **kwargs):
        f = real_build(nodes, graph, motifs, *args, **kwargs)
        # The leak, written the way a well-meaning future feature would write
        # it: "how much of this candidate's internal flow is flagged?"
        flagged = sum(agg.laundering for _, _, agg in graph.subgraph_edges(nodes))
        f.round_amount_ratio = float(flagged)
        return f

    monkeypatch.setattr(F, "build", leaky_build)

    leaked_clean = ci_gates.fingerprint(ci_gates.run_fixture())
    leaked_poisoned = ci_gates.fingerprint(
        ci_gates.run_fixture(label_poison=POISON_SEEDS[0]))
    assert leaked_clean != leaked_poisoned, (
        "a feature computed directly from the ground-truth label did not "
        "change the fingerprint. The poison test cannot detect a leak and "
        "must be fixed before it is trusted.")
    # And the planted leak really is a leak relative to the clean run, rather
    # than a no-op that happens to differ from itself.
    assert leaked_clean != ci_gates.fingerprint(clean)
