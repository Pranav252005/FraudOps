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
