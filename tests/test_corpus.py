"""The corpus key is a safety mechanism, so its refusals are what get tested.

A cached corpus quietly answering a question about a detector configuration it
was not built from is a confident wrong answer -- the failure class this
project keeps a bug catalogue for. Every test here is about that refusal
firing, not about storage round-tripping.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from sentinel import config
from sentinel.corpus import (FEATURE_VERSION, CorpusDrift, CorpusKey,
                             CorpusMismatch, detector_config_hash, load,
                             require_consistent, save, verify_scoring)

NAMES = ["conservation", "n_nodes", "passthrough_ratio"]
ARRAYS = {"test_X": np.zeros((3, 3)), "test_y": np.array([0, 1, 0])}


def test_key_is_stable_for_the_same_config():
    assert detector_config_hash(NAMES) == detector_config_hash(NAMES)


def test_key_does_not_depend_on_set_iteration_order():
    """EXCLUDED_FEATURES is a frozenset; a digest over its raw repr would be
    hash-seed dependent, which this project has already been bitten by once."""
    a = detector_config_hash(NAMES)
    assert a == detector_config_hash(list(NAMES))


def test_changing_a_generation_constant_changes_the_key(monkeypatch):
    before = detector_config_hash(NAMES)
    monkeypatch.setattr(config, "EXPAND_HOPS", config.EXPAND_HOPS + 1)
    assert detector_config_hash(NAMES) != before


def test_changing_the_prune_strategy_changes_the_key(monkeypatch):
    before = detector_config_hash(NAMES)
    monkeypatch.setattr(config, "PRUNE_STRATEGY", "definitely-not-leaf2")
    assert detector_config_hash(NAMES) != before


def test_changing_the_feature_schema_changes_the_key():
    assert detector_config_hash(NAMES) != detector_config_hash(NAMES + ["new"])


def test_renaming_a_feature_changes_the_key():
    """Same width, same values, different meaning per column."""
    renamed = ["conservation", "n_nodes", "passthrough_ratio_v2"]
    assert detector_config_hash(NAMES) != detector_config_hash(renamed)


def test_documentation_only_constants_do_not_invalidate_a_corpus(monkeypatch):
    """STRUCTURAL_RECALL_CEILING is a reported property, not an input to
    generation -- bumping it must not orphan every stored corpus."""
    before = detector_config_hash(NAMES)
    monkeypatch.setattr(config, "STRUCTURAL_RECALL_CEILING", 0.5)
    assert detector_config_hash(NAMES) == before


def test_round_trip_preserves_arrays_and_key(tmp_path):
    key = CorpusKey.for_current_config("test-set", NAMES)
    save(tmp_path / "c.npz", key, ARRAYS)
    arrays, got = load(tmp_path / "c.npz", expect=key)
    assert got == key
    assert np.array_equal(arrays["test_y"], ARRAYS["test_y"])


def test_load_refuses_a_corpus_built_for_another_config(tmp_path):
    stored = CorpusKey("test-set", "0" * 16, FEATURE_VERSION)
    save(tmp_path / "c.npz", stored, ARRAYS)
    wanted = CorpusKey.for_current_config("test-set", NAMES)
    with pytest.raises(CorpusMismatch, match="needs"):
        load(tmp_path / "c.npz", expect=wanted)


def test_load_refuses_a_corpus_from_another_dataset(tmp_path):
    key = CorpusKey.for_current_config("elliptic2", NAMES)
    save(tmp_path / "c.npz", key, ARRAYS)
    with pytest.raises(CorpusMismatch):
        load(tmp_path / "c.npz",
             expect=CorpusKey.for_current_config("amlworld-hi-small", NAMES))


def test_load_refuses_a_corpus_from_an_older_feature_version(tmp_path):
    key = CorpusKey.for_current_config("test-set", NAMES)
    save(tmp_path / "c.npz", key, ARRAYS)
    older = CorpusKey(key.dataset, key.detector_config_hash,
                      FEATURE_VERSION - 1)
    with pytest.raises(CorpusMismatch):
        load(tmp_path / "c.npz", expect=older)


def test_load_refuses_an_unkeyed_file(tmp_path):
    """The pre-corpus `ranker_pool.npz` shape: no key, so unverifiable."""
    np.savez_compressed(tmp_path / "bare.npz", **ARRAYS)
    with pytest.raises(CorpusMismatch, match="no corpus key"):
        load(tmp_path / "bare.npz",
             expect=CorpusKey.for_current_config("test-set", NAMES))


def test_load_without_an_expected_key_is_inspection_only(tmp_path):
    """Reading a corpus blind is allowed, but callers computing a number must
    pass the key they need -- that is the only way staleness surfaces early."""
    key = CorpusKey.for_current_config("test-set", NAMES)
    save(tmp_path / "c.npz", key, ARRAYS)
    _, got = load(tmp_path / "c.npz")
    assert got == key


# --- the regression gate ------------------------------------------------------
#
# The corpus architecture rests on one empirical claim: for a scorer question,
# querying the corpus IS the replay rather than an approximation of it. That is
# only true if a refit from the corpus reproduces the stored held-out number
# exactly. This is the test that would catch it becoming false.

CORPUS = Path(__file__).resolve().parent.parent / "data" / "corpus_amlworld_hi_small.npz"
ORACLE = Path(__file__).resolve().parent.parent / "data" / "eval_oracle.json"

pytestmark_reason = "needs the compiled corpus (data/, not in the repo)"


@pytest.mark.slow
@pytest.mark.skipif(not CORPUS.exists() or not ORACLE.exists(),
                    reason=pytestmark_reason)
def test_corpus_refit_reproduces_the_stored_held_out_p_at_10():
    from lightgbm import LGBMClassifier

    names = [str(n) for n in np.load(CORPUS, allow_pickle=True)["names"]]
    arrays, _ = load(CORPUS, expect=CorpusKey.for_current_config(
        "amlworld-hi-small", names))

    model = LGBMClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                           class_weight="balanced", random_state=7,
                           verbosity=-1)
    model.fit(arrays["train_X"], arrays["train_y"])
    score = model.predict_proba(arrays["test_X"])[:, 1]

    tte, yte = arrays["test_t"], arrays["test_y"]
    k, hits = 10, []
    for t in sorted(set(tte.tolist())):
        idx = np.flatnonzero(tte == t)
        top = idx[np.argsort(-score[idx], kind="stable")][:k]
        hits.append(yte[top].sum() / k)
    got = float(np.mean(hits))

    stored = json.loads(ORACLE.read_text(encoding="utf-8"))
    want = stored["oracle_as_is"]["precision_at"]["10"]["oracle"]
    assert got == pytest.approx(want, abs=1e-12), (
        f"corpus refit gives p@10 {got!r}, stored replay gives {want!r}. "
        f"The corpus is no longer equivalent to the replay for scorer "
        f"questions, which is the assumption the whole corpus rests on.")


# --- drift: the failure the key structurally cannot catch ---------------------
#
# The key covers generation constants and the feature schema. A change to how a
# feature is COMPUTED leaves the key identical and the corpus wrong. That is not
# hypothetical -- the first corpus adopted into this repo was stale in exactly
# that way, its key matched, and only a cold replay found it, by disagreeing in
# the last bit of the blend on 36% of rows.

def _synthetic_corpus(n=40):
    """A corpus whose blend really was produced by today's `score()`."""
    from sentinel.detect.features import Features, score

    rng = np.random.default_rng(11)
    names = ["conservation", "passthrough_ratio", "fast_passthrough_ratio",
             "cycle_coverage", "temporal_cycle_coverage", "gargaml",
             "bipartite_score", "stack_score", "round_amount_ratio",
             "burstiness", "scatter_gather_width", "gather_scatter_width",
             "n_countries", "has_cycle", "has_temporal_cycle",
             "shortest_cycle", "shortest_temporal_cycle"]
    X = rng.random((n, len(names)))
    X[:, names.index("shortest_cycle")] = 3.0
    X[:, names.index("shortest_temporal_cycle")] = 3.0
    X[:, names.index("n_countries")] = 2.0
    blend = np.empty(n)
    for i in range(n):
        f = Features()
        for j, nm in enumerate(names):
            setattr(f, nm, float(X[i, j]))
        blend[i] = score(f)[0]
    return {"test_X": X, "test_blend": blend}, names


def test_verify_scoring_passes_on_a_corpus_this_code_built():
    arrays, names = _synthetic_corpus()
    r = verify_scoring(arrays, names)
    assert r["consistent"] and r["n_disagreeing"] == 0
    assert r["max_abs_diff"] == 0.0


def test_verify_scoring_catches_a_one_ulp_drift():
    """The real drift was one ULP. A tolerance loose enough to admit it would
    have admitted the stale corpus, so the check is exact by design."""
    arrays, names = _synthetic_corpus()
    arrays["test_blend"] = np.nextafter(arrays["test_blend"], np.inf)
    r = verify_scoring(arrays, names)
    assert not r["consistent"]
    assert r["n_disagreeing"] == len(arrays["test_blend"])
    assert 0 < r["max_abs_diff"] < 1e-15


def test_require_consistent_raises_and_says_recompile():
    arrays, names = _synthetic_corpus()
    arrays["test_blend"] = np.nextafter(arrays["test_blend"], np.inf)
    with pytest.raises(CorpusDrift, match="Recompile"):
        require_consistent(arrays, names)


def test_drift_is_a_kind_of_mismatch():
    """Callers guarding with CorpusMismatch must also catch drift."""
    assert issubclass(CorpusDrift, CorpusMismatch)


def test_a_matching_key_does_not_imply_consistency():
    """The point of the whole check, stated as a test: key equality and
    scoring consistency are independent, and only one of them is cheap."""
    arrays, names = _synthetic_corpus()
    key = CorpusKey.for_current_config("test-set", names)
    arrays["test_blend"] = np.nextafter(arrays["test_blend"], np.inf)
    assert CorpusKey.for_current_config("test-set", names) == key
    assert not verify_scoring(arrays, names)["consistent"]
