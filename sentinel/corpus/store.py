"""Content-addressed storage for a compiled candidate corpus.

The key is `(dataset, detector_config_hash, feature_version)`. Any change to a
constant that alters which candidates exist, or to the feature vector's
composition, produces a different hash and makes an existing corpus unreadable
for the new question -- loudly, at load time, rather than silently in a number
somebody later quotes.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from sentinel import config

# Bump when the MEANING of a stored feature changes -- a new feature, a removed
# one, a changed unit or normalisation. Renaming without changing values still
# counts, because `names` is part of the hash and a stale corpus would other-
# wise be matched to the wrong column.
FEATURE_VERSION = 1

# The constants that determine WHICH candidates exist. A corpus built under one
# set cannot answer a question posed under another. `STRUCTURAL_RECALL_CEILING`
# is deliberately excluded: it is a reported property of the dataset, not an
# input to generation, so including it would invalidate corpora for a
# documentation change.
_GENERATION_CONSTANTS = ("EVAL_END", "TICK_MINUTES", "WINDOW_MINUTES",
                         "EXPAND_HOPS", "EXPAND_MAX_NODES",
                         "EXPAND_MAX_DEGREE", "PRUNE_STRATEGY",
                         "EXCLUDED_FEATURES")


class CorpusMismatch(RuntimeError):
    """A stored corpus does not answer the question being asked of it."""


class CorpusDrift(CorpusMismatch):
    """The corpus disagrees with the code that would score it today.

    Distinct from a key mismatch, and the more dangerous of the two. The key
    covers generation CONSTANTS and the feature SCHEMA; it is structurally
    blind to a change in how a feature is COMPUTED. A corpus can therefore
    carry a perfectly matching key and still have been built by different code.

    This was not hypothetical: the first corpus adopted into this repo was
    stale in exactly that way, and the key did not catch it. A cold replay did,
    by disagreeing in the last bit of the blend on 36% of rows. Hashing the
    source files would also catch it, but this project rewrites docstrings
    constantly and that would discard a 55-minute compile over a comment. So
    the check is behavioural instead: recompute the score from the stored
    features and see whether today's code agrees.
    """


def detector_config_hash(feature_names: list[str] | tuple[str, ...]) -> str:
    """Stable short hash over generation constants and the feature schema.

    Sorted and JSON-encoded so the digest does not depend on dict ordering or
    on a set's iteration order -- this project has already been bitten once by
    a `set` whose order changed under `PYTHONHASHSEED`.
    """
    payload = {name: _stable(getattr(config, name))
               for name in _GENERATION_CONSTANTS}
    payload["feature_names"] = list(feature_names)
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _stable(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value)
    return value


@dataclass(frozen=True)
class CorpusKey:
    """What a corpus can answer questions about."""

    dataset: str
    detector_config_hash: str
    feature_version: int = FEATURE_VERSION

    @classmethod
    def for_current_config(cls, dataset: str,
                           feature_names: list[str] | tuple[str, ...]) -> "CorpusKey":
        return cls(dataset=dataset,
                   detector_config_hash=detector_config_hash(feature_names),
                   feature_version=FEATURE_VERSION)

    def to_dict(self) -> dict:
        return {"dataset": self.dataset,
                "detector_config_hash": self.detector_config_hash,
                "feature_version": self.feature_version}

    def describe(self) -> str:
        return (f"{self.dataset}/{self.detector_config_hash}"
                f"/v{self.feature_version}")


def verify_scoring(arrays: dict, names: list[str], n_sample: int = 2000,
                   seed: int = 7, tol: float = 0.0) -> dict:
    """Recompute the v1 blend from stored features and compare to the stored one.

    A pure-function check: `score()` reads only Features attributes, all of
    which are columns of the stored matrix, so today's code applied to the
    stored features must reproduce the stored blend exactly. Any disagreement
    means the corpus was compiled by different code, whatever its key says.

    `tol` defaults to 0.0 -- exact. A last-bit difference is small enough to
    change no ranking today and large enough to prove the corpus is not what it
    claims, and the second fact is the one worth failing on.
    """
    import numpy as _np

    from sentinel.detect.features import Features, score

    X = arrays["test_X"]
    stored = arrays["test_blend"]
    rng = _np.random.default_rng(seed)
    n = min(n_sample, X.shape[0])
    rows = rng.choice(X.shape[0], size=n, replace=False)
    blank = Features()
    cols = [(j, nm) for j, nm in enumerate(names) if hasattr(blank, nm)]

    worst, n_diff = 0.0, 0
    for i in rows:
        f = Features()
        for j, nm in cols:
            # Every field is set as a float. `score()` only ever tests
            # truthiness or compares numerically, so an int/bool field holding
            # 1.0 behaves identically -- and round-tripping through the stored
            # float64 is what makes this an honest reproduction of the value
            # the corpus actually carries.
            setattr(f, nm, float(X[i, j]))
        got, _ = score(f)
        d = abs(got - float(stored[i]))
        if d > 0:
            n_diff += 1
            worst = max(worst, d)
    return {"n_checked": int(n), "n_disagreeing": n_diff, "max_abs_diff": worst,
            "consistent": worst <= tol}


def require_consistent(arrays: dict, names: list[str], **kw) -> dict:
    """`verify_scoring`, raising on drift. Call before computing any number."""
    r = verify_scoring(arrays, names, **kw)
    if not r["consistent"]:
        raise CorpusDrift(
            f"corpus disagrees with current scoring code on "
            f"{r['n_disagreeing']} of {r['n_checked']} sampled rows "
            f"(max {r['max_abs_diff']:.3e}). The key matched, so a generation "
            f"constant did not change -- a feature's COMPUTATION did. "
            f"Recompile; do not reinterpret.")
    return r


def save(path: Path, key: CorpusKey, arrays: dict) -> Path:
    """Write a compiled corpus, stamped with the key that produced it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(arrays)
    payload["__key__"] = np.array(json.dumps(key.to_dict()))
    np.savez_compressed(path, **payload)
    return path


def load(path: Path, expect: CorpusKey | None = None) -> tuple[dict, CorpusKey]:
    """Read a corpus, refusing to serve one built for a different question.

    Passing `expect=None` reads whatever is stored and returns its key. That is
    for inspection only; any caller computing a number must pass the key it
    actually needs, so that a stale corpus fails here rather than downstream.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"no corpus at {path}")
    blob = np.load(path, allow_pickle=True)
    if "__key__" not in blob.files:
        raise CorpusMismatch(
            f"{path} carries no corpus key. It predates keyed storage and "
            f"cannot be verified against a detector config -- recompile it, "
            f"or stamp it with scripts/compile_corpus.py --adopt if you can "
            f"confirm which config produced it.")
    stored = CorpusKey(**json.loads(str(blob["__key__"])))
    if expect is not None and stored != expect:
        raise CorpusMismatch(
            f"corpus at {path} answers {stored.describe()}, but this question "
            f"needs {expect.describe()}. A detector constant, the prune "
            f"strategy, or the feature schema changed since it was compiled. "
            f"Recompile rather than reinterpreting the stored one.")
    arrays = {k: blob[k] for k in blob.files if k != "__key__"}
    return arrays, stored
