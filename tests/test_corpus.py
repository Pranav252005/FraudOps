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
                             CorpusMismatch, DatasetMismatch,
                             ProvenanceMismatch, detector_config_hash, load,
                             require_consistent, require_poolable,
                             require_same_dataset, save, stratify_by_dataset,
                             stratify_by_provenance, verify_scoring)

NAMES = ["conservation", "n_nodes", "passthrough_ratio"]
# Sentinel's own candidates are constructed by seed-and-expand. Spelled out in
# every call rather than defaulted, because the argument exists precisely so
# that nobody gets it by accident.
CONSTRUCTED = "constructed"
ARRAYS = {"test_X": np.zeros((3, 3)), "test_y": np.array([0, 1, 0])}


def test_key_is_stable_for_the_same_config():
    assert detector_config_hash(NAMES, CONSTRUCTED) == detector_config_hash(NAMES, CONSTRUCTED)


def test_key_does_not_depend_on_set_iteration_order():
    """EXCLUDED_FEATURES is a frozenset; a digest over its raw repr would be
    hash-seed dependent, which this project has already been bitten by once."""
    a = detector_config_hash(NAMES, CONSTRUCTED)
    assert a == detector_config_hash(list(NAMES), CONSTRUCTED)


def test_changing_a_generation_constant_changes_the_key(monkeypatch):
    before = detector_config_hash(NAMES, CONSTRUCTED)
    monkeypatch.setattr(config, "EXPAND_HOPS", config.EXPAND_HOPS + 1)
    assert detector_config_hash(NAMES, CONSTRUCTED) != before


def test_changing_the_prune_strategy_changes_the_key(monkeypatch):
    before = detector_config_hash(NAMES, CONSTRUCTED)
    monkeypatch.setattr(config, "PRUNE_STRATEGY", "definitely-not-leaf2")
    assert detector_config_hash(NAMES, CONSTRUCTED) != before


def test_changing_the_feature_schema_changes_the_key():
    assert detector_config_hash(NAMES, CONSTRUCTED) != detector_config_hash(NAMES + ["new"], CONSTRUCTED)


def test_renaming_a_feature_changes_the_key():
    """Same width, same values, different meaning per column."""
    renamed = ["conservation", "n_nodes", "passthrough_ratio_v2"]
    assert detector_config_hash(NAMES, CONSTRUCTED) != detector_config_hash(renamed, CONSTRUCTED)


def test_documentation_only_constants_do_not_invalidate_a_corpus(monkeypatch):
    """STRUCTURAL_RECALL_CEILING is a reported property, not an input to
    generation -- bumping it must not orphan every stored corpus."""
    before = detector_config_hash(NAMES, CONSTRUCTED)
    monkeypatch.setattr(config, "STRUCTURAL_RECALL_CEILING", 0.5)
    assert detector_config_hash(NAMES, CONSTRUCTED) == before


def test_round_trip_preserves_arrays_and_key(tmp_path):
    key = CorpusKey.for_current_config("test-set", NAMES, CONSTRUCTED)
    save(tmp_path / "c.npz", key, ARRAYS)
    arrays, got = load(tmp_path / "c.npz", expect=key)
    assert got == key
    assert np.array_equal(arrays["test_y"], ARRAYS["test_y"])


def test_load_refuses_a_corpus_built_for_another_config(tmp_path):
    stored = CorpusKey("test-set", "0" * 16, CONSTRUCTED, FEATURE_VERSION)
    save(tmp_path / "c.npz", stored, ARRAYS)
    wanted = CorpusKey.for_current_config("test-set", NAMES, CONSTRUCTED)
    with pytest.raises(CorpusMismatch, match="needs"):
        load(tmp_path / "c.npz", expect=wanted)


def test_load_refuses_a_corpus_from_another_dataset(tmp_path):
    key = CorpusKey.for_current_config("elliptic2", NAMES, CONSTRUCTED)
    save(tmp_path / "c.npz", key, ARRAYS)
    with pytest.raises(CorpusMismatch):
        load(tmp_path / "c.npz",
             expect=CorpusKey.for_current_config("amlworld-hi-small", NAMES, CONSTRUCTED))


def test_load_refuses_a_corpus_from_an_older_feature_version(tmp_path):
    key = CorpusKey.for_current_config("test-set", NAMES, CONSTRUCTED)
    save(tmp_path / "c.npz", key, ARRAYS)
    older = CorpusKey(key.dataset, key.detector_config_hash,
                      key.candidate_provenance, FEATURE_VERSION - 1)
    with pytest.raises(CorpusMismatch):
        load(tmp_path / "c.npz", expect=older)


def test_load_refuses_an_unkeyed_file(tmp_path):
    """The pre-corpus `ranker_pool.npz` shape: no key, so unverifiable."""
    np.savez_compressed(tmp_path / "bare.npz", **ARRAYS)
    with pytest.raises(CorpusMismatch, match="no corpus key"):
        load(tmp_path / "bare.npz",
             expect=CorpusKey.for_current_config("test-set", NAMES, CONSTRUCTED))


def test_load_without_an_expected_key_is_inspection_only(tmp_path):
    """Reading a corpus blind is allowed, but callers computing a number must
    pass the key they need -- that is the only way staleness surfaces early."""
    key = CorpusKey.for_current_config("test-set", NAMES, CONSTRUCTED)
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
        "amlworld-hi-small", names, CONSTRUCTED))

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
    key = CorpusKey.for_current_config("test-set", names, CONSTRUCTED)
    arrays["test_blend"] = np.nextafter(arrays["test_blend"], np.inf)
    assert CorpusKey.for_current_config("test-set", names, CONSTRUCTED) == key
    assert not verify_scoring(arrays, names)["consistent"]


# --- candidate provenance -----------------------------------------------------
#
# The key's fourth field, and the one added last. Constructed candidates
# (seed-and-expand chose the boundary) and given ones (the dataset shipped it)
# are different objects; before this field they hashed identically, so two
# corpora answering different questions were interchangeable. These tests are
# about that collision staying closed and about the pooling refusal firing.


def test_provenance_changes_the_hash():
    """The collision this field was added to close, stated directly."""
    assert (detector_config_hash(NAMES, "constructed")
            != detector_config_hash(NAMES, "given"))


def test_provenance_is_in_the_digest_not_merely_beside_it():
    """Carrying it as a field alone would leave the hashes equal, and a hash is
    what gets compared when someone reaches past CorpusKey."""
    a = CorpusKey.for_current_config("elliptic2", NAMES, "constructed")
    b = CorpusKey.for_current_config("elliptic2", NAMES, "given")
    assert a.detector_config_hash != b.detector_config_hash


def test_provenance_has_no_default():
    with pytest.raises(TypeError):
        detector_config_hash(NAMES)


def test_an_unknown_provenance_is_refused():
    with pytest.raises(ValueError, match="candidate_provenance"):
        detector_config_hash(NAMES, "somewhere")
    with pytest.raises(ValueError, match="candidate_provenance"):
        CorpusKey("test-set", "0" * 16, "somewhere")


def test_provenance_appears_in_describe():
    """It has to be visible wherever a key is printed, or a reader comparing
    two runs by eye cannot tell they answer different questions."""
    key = CorpusKey.for_current_config("elliptic2", NAMES, "given")
    assert "given" in key.describe()


def test_load_refuses_a_corpus_of_the_other_provenance(tmp_path):
    given = CorpusKey.for_current_config("elliptic2", NAMES, "given")
    save(tmp_path / "c.npz", given, ARRAYS)
    with pytest.raises(CorpusMismatch):
        load(tmp_path / "c.npz",
             expect=CorpusKey.for_current_config("elliptic2", NAMES,
                                                 "constructed"))


def test_load_refuses_a_key_written_before_provenance_existed(tmp_path):
    """Every corpus stamped before this field cannot say which it is, and a
    guess would be exactly the silent wrong answer the field prevents."""
    payload = dict(ARRAYS)
    payload["__key__"] = np.array(json.dumps(
        {"dataset": "test-set", "detector_config_hash": "0" * 16,
         "feature_version": FEATURE_VERSION}))
    np.savez_compressed(tmp_path / "old.npz", **payload)
    with pytest.raises(CorpusMismatch, match="candidate_provenance"):
        load(tmp_path / "old.npz")


def test_pooling_one_provenance_returns_it():
    key = CorpusKey.for_current_config("test-set", NAMES, CONSTRUCTED)
    assert require_poolable([key], "recall") == CONSTRUCTED


def test_pooling_across_provenance_is_allowed_for_a_scorer_question():
    """Both corpora are Elliptic2 -- the shipped components and a seed-and-
    expand pass over the same background edges. That pair is the collision
    `candidate_provenance` was invented for, and it is the case where pooling
    is legitimate: a scorer is a function on feature vectors.

    This test used to spell the two sides as different DATASETS, which made it
    read as a licence to pool across domains. It never was one; see
    `test_pooling_across_datasets_is_refused_for_every_question`.
    """
    a = CorpusKey.for_current_config("elliptic2", NAMES, "constructed")
    b = CorpusKey.for_current_config("elliptic2", NAMES, "given")
    assert require_poolable([a, b], "scorer") == "constructed+given"


def test_pooling_across_provenance_is_refused_for_a_recall_question():
    """A scorer is a function on feature vectors and does not care where the
    boundary came from. Recall does: `given` candidates have no seeding step to
    have recall about."""
    a = CorpusKey.for_current_config("elliptic2", NAMES, "constructed")
    b = CorpusKey.for_current_config("elliptic2", NAMES, "given")
    with pytest.raises(ProvenanceMismatch, match="recall"):
        require_poolable([a, b], "recall")


def test_the_funnel_is_a_recall_question_and_cannot_pool():
    a = CorpusKey.for_current_config("elliptic2", NAMES, "constructed")
    b = CorpusKey.for_current_config("elliptic2", NAMES, "given")
    with pytest.raises(ProvenanceMismatch):
        require_poolable([a, b], "funnel")


def test_an_unlisted_question_is_refused_not_assumed_poolable():
    """The default has to be refusal. A question that silently defaulted to
    poolable is the confident wrong answer this key exists to prevent."""
    a = CorpusKey.for_current_config("elliptic2", NAMES, "constructed")
    b = CorpusKey.for_current_config("elliptic2", NAMES, "given")
    with pytest.raises(ProvenanceMismatch, match="unknown question"):
        require_poolable([a, b], "whatever-this-is")


def test_refusal_is_a_kind_of_mismatch():
    """Callers already guarding with CorpusMismatch keep working."""
    assert issubclass(ProvenanceMismatch, CorpusMismatch)


def test_stratify_groups_by_provenance():
    """The alternative to refusing: answer per stratum, never averaged."""
    a = CorpusKey.for_current_config("elliptic2", NAMES, "constructed")
    b = CorpusKey.for_current_config("elliptic2", NAMES, "given")
    c = CorpusKey.for_current_config("other", NAMES, "given")
    groups = stratify_by_provenance([a, b, c], ["A", "B", "C"])
    assert groups == {"constructed": ["A"], "given": ["B", "C"]}


# -- the cross-domain guard --------------------------------------------------
#
# Added when a second domain (synthetic identity) was built. Provenance was
# assumed to be this guard and is not: seed-and-expand candidates are
# `constructed` in every domain, so the provenance check agrees with itself
# across two domains that share no feature space.


def test_pooling_across_datasets_is_refused_for_every_question():
    """Including the ones provenance lets through.

    `scorer` is poolable across PROVENANCE because a scorer is a function on
    feature vectors. It is not poolable across DATASETS, because the two sides
    do not have the same feature vectors: one is built from `passthrough_ratio`
    and the other from attribute rotation. Averaging them describes neither.
    """
    a = CorpusKey.for_current_config("amlworld-hi-small", NAMES, CONSTRUCTED)
    b = CorpusKey.for_current_config("synthetic-identity-v1", NAMES, CONSTRUCTED)
    for question in ("scorer", "ranking", "calibration", "recall", "funnel"):
        with pytest.raises(DatasetMismatch, match="different domains"):
            require_poolable([a, b], question)


def test_provenance_alone_would_have_passed_this():
    """The negative control: the guard that was assumed to cover this, doesn't.

    Both keys are `constructed`, so the provenance sets agree and the old
    implementation -- which looked at nothing else -- returned "constructed"
    and pooled two domains. This test asserts the premise of the bug, so the
    fix cannot be mistaken for a fix to something else.
    """
    a = CorpusKey.for_current_config("amlworld-hi-small", NAMES, CONSTRUCTED)
    b = CorpusKey.for_current_config("synthetic-identity-v1", NAMES, CONSTRUCTED)
    assert {a.candidate_provenance, b.candidate_provenance} == {CONSTRUCTED}


def test_one_dataset_is_returned_not_refused():
    a = CorpusKey.for_current_config("amlworld-hi-small", NAMES, CONSTRUCTED)
    b = CorpusKey.for_current_config("amlworld-hi-small", NAMES, CONSTRUCTED)
    assert require_same_dataset([a, b]) == "amlworld-hi-small"


def test_dataset_refusal_is_a_kind_of_mismatch():
    """Callers already guarding with CorpusMismatch keep working."""
    assert issubclass(DatasetMismatch, CorpusMismatch)


def test_dataset_refusal_is_not_a_provenance_refusal():
    """They are different failures and a caller may want to tell them apart.

    A provenance refusal has a sanctioned workaround -- ask a question that
    does not depend on the boundary's origin. A dataset refusal does not: there
    is no question that survives it, only per-domain reporting.
    """
    assert not issubclass(DatasetMismatch, ProvenanceMismatch)
    assert not issubclass(ProvenanceMismatch, DatasetMismatch)


def test_stratify_groups_by_dataset():
    """The sanctioned cross-domain path: two answers, side by side."""
    a = CorpusKey.for_current_config("amlworld-hi-small", NAMES, CONSTRUCTED)
    b = CorpusKey.for_current_config("synthetic-identity-v1", NAMES, CONSTRUCTED)
    c = CorpusKey.for_current_config("synthetic-identity-v1", NAMES, CONSTRUCTED)
    groups = stratify_by_dataset([a, b, c], ["A", "B", "C"])
    assert groups == {"amlworld-hi-small": ["A"],
                      "synthetic-identity-v1": ["B", "C"]}
