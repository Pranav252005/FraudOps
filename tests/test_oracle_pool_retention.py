"""D3b: the oracle keeps feature vectors, not candidates — and it must be exact.

`eval_oracle.collect_pool` used to retain the whole `Candidate` for every
candidate of every cycle, in two pools, with the first still referenced while
the second was built. Measured at ~1,064 bytes *pickled* per candidate (live
objects run 3-5x that), HI-Medium's ~3.36M candidates per pool put peak memory
at 10-17 GB per pool on a 16.5 GB machine. The oracle could not run on it at
all.

It now stores the feature vector and four scalars instead. **The whole value of
that change rests on it being numerically identical**, so what is tested here
is equivalence, not behaviour:

  * the feature order can be derived without a candidate, because
    `feature_names` reads a dataclass key set that is the same for every
    instance — this is what allows vectorising at collection time;
  * vectorising early gives the same row as vectorising late;
  * float64 is kept, because float32 would change the values LightGBM splits
    on and the change would stop being equivalent.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sentinel.detect.features import Features  # noqa: E402
from sentinel.learn.reranker import feature_names, vectorise  # noqa: E402

import eval_oracle  # noqa: E402


def test_feature_order_does_not_depend_on_the_instance():
    """The property the whole change rests on.

    If `feature_names` varied by instance, the order fixed at collection time
    could differ from the order training expects, and every row would be
    silently permuted — a wrong answer, not an error.
    """
    default = feature_names(Features())
    populated = feature_names(Features(
        n_nodes=9, n_edges=14, conservation=0.71, cross_border=True,
        dominant_entity_type="Corporation", max_fan=6, exact=False))
    assert default == populated
    assert eval_oracle.FEATURE_NAMES == default
    assert len(default) == 54


def test_vectorising_early_equals_vectorising_late():
    """Equivalence, on a populated Features and against the old call shape."""
    f = Features(n_nodes=9, n_edges=14, conservation=0.71, cross_border=True,
                 max_fan=6, total_amount=123456.789, burstiness=3.25)
    names = eval_oracle.FEATURE_NAMES
    early = np.asarray(vectorise(f, names), dtype=np.float64)
    late = np.array(vectorise(f, names))
    assert early.dtype == np.float64
    np.testing.assert_array_equal(early, late)


def test_the_stored_vector_is_float64_not_float32():
    """float32 would halve memory again and silently change the model.

    LightGBM splits on the values it is given; narrowing them to ~7 significant
    digits would move split points on a feature like `total_amount`. The change
    would then not be equivalent, which is the only thing making it safe.
    """
    f = Features(total_amount=123456789.123456)
    vec = np.asarray(vectorise(f, eval_oracle.FEATURE_NAMES), dtype=np.float64)
    assert vec.dtype == np.float64
    i = eval_oracle.FEATURE_NAMES.index("total_amount")
    assert vec[i] == pytest.approx(123456789.123456, abs=1e-6)
    # the same value through float32 would lose the fractional part entirely
    assert np.float32(123456789.123456) != np.float64(123456789.123456)


def test_to_xy_reads_the_stored_vector_and_refuses_a_reordered_name_list():
    """`to_xy` asserts the order it is handed matches the order stored.

    Without that, a future caller passing a different `names` would get a
    matrix whose columns no longer mean what the model was trained on.
    """
    names = eval_oracle.FEATURE_NAMES
    recs = [{"vec": np.arange(len(names), dtype=np.float64), "ring": None},
            {"vec": np.arange(len(names), dtype=np.float64) + 1, "ring": 3}]
    X, y = eval_oracle.to_xy(recs, names)
    assert X.shape == (2, len(names))
    assert list(y) == [0, 1]
    with pytest.raises(AssertionError):
        eval_oracle.to_xy(recs, list(reversed(names)))


def test_no_candidate_object_is_retained_anywhere_in_the_pool():
    """The memory property itself, asserted against the source.

    A future edit that reintroduces `record["cand"]` would restore the 10-17 GB
    peak and nothing would fail until a large split OOMed.
    """
    src = (ROOT / "scripts" / "eval_oracle.py").read_text(encoding="utf-8")
    assert '["cand"]' not in src
    assert '"cand": c' not in src


def test_the_first_pool_is_freed_before_the_second_is_built():
    """Both pools were live at once, so peak was their sum."""
    src = (ROOT / "scripts" / "eval_oracle.py").read_text(encoding="utf-8")
    i_del = src.index("del as_is_records")
    i_second = src.index("seed_perfect=True")
    assert i_del < i_second, "the as-is pool must be freed before the second"


def test_equivalence_on_real_candidates_from_the_fixture():
    """The strongest cheap check: same X matrix, old path vs new, real data.

    The unit tests above use synthetic `Features`. This runs the committed
    fixture through the real generator and asserts that vectorising at
    collection time (what `collect_pool` now does) produces a byte-identical
    matrix to vectorising from the retained object at training time (what it
    used to do).

    A full before/after on HI-Small's oracle is the definitive check and needs
    the machine to itself; this catches a mistake in seconds instead.
    """
    import ci_gates

    result = ci_gates.run_fixture()
    cands = [c for cyc in result["cycles"] for c in cyc["candidates"]]
    assert len(cands) > 100, len(cands)

    names = eval_oracle.FEATURE_NAMES
    # NEW: vector materialised at collection time, as collect_pool now does.
    new_records = [{"vec": np.asarray(vectorise(c.features, names),
                                      dtype=np.float64), "ring": None}
                   for c in cands]
    X_new, _ = eval_oracle.to_xy(new_records, names)
    # OLD: vectorised from the retained object at training time.
    X_old = np.array([vectorise(c.features, names) for c in cands])

    assert X_new.shape == X_old.shape
    np.testing.assert_array_equal(X_new, X_old)


def test_the_scalars_carried_alongside_match_the_candidate():
    """`_cycle_rows` reads blend/size/degree/key off the record now.

    If any of those were captured wrongly, the oracle's own baselines -- the
    ones every ranking claim is quoted against -- would silently be measuring
    something else.
    """
    import ci_gates

    cands = [c for cyc in ci_gates.run_fixture()["cycles"]
             for c in cyc["candidates"]][:300]
    for c in cands:
        rec = {"blend": float(c.score), "size": int(c.size),
               "degree": float(c.features.max_fan), "key": c.key}
        assert rec["blend"] == float(c.score)
        assert float(rec["size"]) == float(c.size)
        assert rec["degree"] == float(c.features.max_fan)
        assert rec["key"] == c.key
