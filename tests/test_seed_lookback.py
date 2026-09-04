"""P0: the seed source is one hour of a seventy-two hour window.

Pre-registered in `prereg/seed_lookback.md`. `seeds()` builds `touched` from
one tick's batch while the generator expands into a `WINDOW_MINUTES` graph, and
cycles fire every 6 ticks — so five ticks in six are never sampled for seeds at
all. Measured over `data/stream`: 22 of 259 active rings are reachable only by
widening this source, and none are unreachable from the whole window.

The properties here are the ones the experiment's validity depends on, not the
ones its result depends on:

  * the shipped lookback of 1 is byte-identical to the pre-P0 behaviour;
  * `observe()` is a no-op at lookback 1, so a caller that never calls it is
    unaffected;
  * the lookback counts TICKS, not cycles — the failure mode is a lookback that
    silently means something six times longer than it says;
  * a wider lookback can only ever add seeds, never remove one.
"""
from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.detect import candidates as C  # noqa: E402


class FakeGraph:
    def __init__(self, edges):
        self.out_adj = defaultdict(set)
        self.in_adj = defaultdict(set)
        for a, b in edges:
            self.out_adj[a].add(b)
            self.in_adj[b].add(a)

    def neighbours(self, n):
        return self.out_adj.get(n, set()) | self.in_adj.get(n, set())


class FakeBatch:
    """Carries t_start/t_end because the lookback guards require them.

    A batch that cannot say when it happened cannot be checked for tick
    contiguity, and a lookback that cannot verify its own tick spacing is a
    lookback of unknown length — so `observe()` refuses one.
    """

    def __init__(self, edges, t_start=0, t_end=None):
        self.src = [a for a, _ in edges]
        self.dst = [b for _, b in edges]
        self.t_start = t_start
        self.t_end = t_start + 60 if t_end is None else t_end

    def __len__(self):
        return len(self.src)


def _contiguous(ticks):
    """FakeBatches at 60-minute spacing, the way `Stream.ticks` yields them."""
    return [FakeBatch(t, t_start=60 * i) for i, t in enumerate(ticks)]


# Three disjoint pass-through triangles, one per tick.
TICKS = [
    [(1, 2), (2, 3), (3, 1)],
    [(10, 11), (11, 12), (12, 10)],
    [(20, 21), (21, 22), (22, 20)],
]
ALL_EDGES = [e for t in TICKS for e in t]


def _run(lookback, n_ticks=3):
    g = FakeGraph(ALL_EDGES)
    gen = C.CandidateGenerator(g, seed_lookback_ticks=lookback)
    batches = _contiguous(TICKS[:n_ticks])
    for b in batches:
        gen.observe(b)
    return gen, gen.seeds(batches[-1])


def test_the_shipped_lookback_is_one():
    assert C.SEED_LOOKBACK_TICKS == 1
    import inspect
    sig = inspect.signature(C.CandidateGenerator.__init__)
    assert sig.parameters["seed_lookback_ticks"].default == C.SEED_LOOKBACK_TICKS


def test_lookback_one_sees_only_the_current_tick():
    """The shipped behaviour, asserted directly rather than assumed from the
    fixture fingerprint."""
    _, seeds = _run(1)
    assert seeds == {10, 11, 12, 20, 21, 22} - {10, 11, 12} | {20, 21, 22}
    assert seeds == {20, 21, 22}


def test_observe_is_a_no_op_at_lookback_one():
    """A caller that never calls `observe` must be unaffected — this is what
    keeps every pre-P0 test and the fixture fingerprint valid."""
    g = FakeGraph(ALL_EDGES)
    gen = C.CandidateGenerator(g)                      # default lookback
    last = _contiguous(TICKS)[-1]
    without = gen.seeds(last)
    gen2 = C.CandidateGenerator(g)
    for b in _contiguous(TICKS):
        gen2.observe(b)
    assert gen2.seeds(last) == without
    assert not gen2._recent_touched


def test_a_wider_lookback_unions_earlier_ticks():
    _, seeds = _run(3)
    assert seeds == {1, 2, 3, 10, 11, 12, 20, 21, 22}


def test_lookback_counts_ticks_not_cycles():
    """The failure mode this test exists for: a lookback of 2 must mean two
    TICKS. If `observe` were called only on cycle ticks — every 6th — the same
    number would silently mean twelve hours."""
    _, seeds = _run(2)
    assert seeds == {10, 11, 12, 20, 21, 22}
    assert 1 not in seeds


@pytest.mark.parametrize("lookback", [1, 2, 3, 6, 24])
def test_widening_never_removes_a_seed(lookback):
    """Monotonicity. A wider source may only add. If it could remove, the arms
    would not be nested and a built-recall comparison between them would be
    against a different detector rather than a wider one."""
    _, base = _run(1)
    _, wider = _run(lookback)
    assert wider >= base


def test_the_deque_is_bounded_by_the_lookback():
    """Memory: the window holds ~340k nodes and 72 ticks of touched sets is not
    free. The bound must actually bind."""
    g = FakeGraph(ALL_EDGES)
    gen = C.CandidateGenerator(g, seed_lookback_ticks=2)
    for i in range(50):
        gen.observe(FakeBatch(TICKS[0], t_start=60 * i))
    assert len(gen._recent_touched) == 2


def test_a_lookback_below_one_is_refused():
    with pytest.raises(ValueError, match="seed_lookback_ticks must be >= 1"):
        C.CandidateGenerator(FakeGraph([]), seed_lookback_ticks=0)


def test_an_empty_tick_does_not_erase_the_lookback():
    """Quiet hours exist in this stream and are yielded as empty batches. An
    empty tick contributes nothing but must not blank the accumulated set —
    otherwise the lookback would collapse to 1 after any quiet hour."""
    g = FakeGraph(ALL_EDGES)
    gen = C.CandidateGenerator(g, seed_lookback_ticks=3)
    gen.observe(FakeBatch(TICKS[0], t_start=0))
    quiet = FakeBatch([], t_start=60)
    gen.observe(quiet)
    assert gen.seeds(quiet) == {1, 2, 3}


# -- P0b: the guards, each with a negative control ---------------------------
#
# `seed_lookback_ticks` is the one parameter here whose misuse produces no
# error and no visible symptom: the deque stays empty, `seeds()` falls back to
# the single batch, and every metric looks exactly like a correct lookback-1
# run. That is this project's characteristic defect, so it gets guards rather
# than a docstring.


def test_forgetting_observe_raises_instead_of_silently_meaning_lookback_one():
    """The foot-gun the queue named. Without this the caller gets shipped
    behaviour while believing they configured a six-hour lookback."""
    g = FakeGraph(ALL_EDGES)
    gen = C.CandidateGenerator(g, seed_lookback_ticks=6)
    with pytest.raises(RuntimeError, match=r"observe\(\) was never called"):
        gen.seeds(_contiguous(TICKS)[-1])


def test_the_omission_guard_does_not_fire_when_observe_was_called():
    """The negative control for the guard above: it must not fire on correct
    usage, or it would just be a ban on the feature."""
    _, seeds = _run(3)
    assert seeds


def test_observing_only_every_nth_tick_raises():
    """The subtler failure: observing on cycle ticks only would make a
    lookback of 6 silently mean 36 hours. Caught by tick contiguity."""
    g = FakeGraph(ALL_EDGES)
    gen = C.CandidateGenerator(g, seed_lookback_ticks=6)
    gen.observe(FakeBatch(TICKS[0], t_start=0))
    with pytest.raises(ValueError, match="non-contiguous tick"):
        gen.observe(FakeBatch(TICKS[1], t_start=360))     # skipped 5 ticks


def test_contiguous_observation_is_accepted():
    """Negative control for the contiguity guard."""
    g = FakeGraph(ALL_EDGES)
    gen = C.CandidateGenerator(g, seed_lookback_ticks=6)
    for b in _contiguous(TICKS):
        gen.observe(b)
    assert gen.stats["observed_ticks"] == len(TICKS)


def test_a_batch_without_timestamps_is_refused_when_a_lookback_is_asked_for():
    """A lookback that cannot verify its own tick spacing is a lookback of
    unknown length."""
    class Timeless:
        src, dst = [1], [2]

        def __len__(self):
            return 1

    g = FakeGraph(ALL_EDGES)
    gen = C.CandidateGenerator(g, seed_lookback_ticks=6)
    with pytest.raises(TypeError, match="t_start and t_end"):
        gen.observe(Timeless())


def test_seeding_a_batch_that_was_not_the_last_observed_raises():
    """observe() and generate() drifting out of step would mean the tick being
    seeded is not in its own lookback."""
    g = FakeGraph(ALL_EDGES)
    gen = C.CandidateGenerator(g, seed_lookback_ticks=6)
    for b in _contiguous(TICKS):
        gen.observe(b)
    with pytest.raises(RuntimeError, match="out of step"):
        gen.seeds(FakeBatch(TICKS[0], t_start=99999))


def test_none_of_the_guards_fire_at_the_shipped_lookback():
    """Lookback 1 is the shipped configuration and must be entirely
    unaffected: no observe required, no timestamps required, no contiguity."""
    class Timeless:
        src, dst = [1], [2]

        def __len__(self):
            return 1

    g = FakeGraph(ALL_EDGES)
    gen = C.CandidateGenerator(g)
    gen.observe(Timeless())                      # no-op, must not raise
    assert gen.seeds(FakeBatch(TICKS[0])) == {1, 2, 3}
    assert gen.stats["observed_ticks"] == 0


def test_observed_ticks_is_reported_so_a_harness_can_assert_wiring():
    gen, _ = _run(3)
    assert gen.stats["observed_ticks"] == 3
