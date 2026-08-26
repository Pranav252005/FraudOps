"""Phase 4: the learned re-ranker — the flywheel closing.

The measured evidence says the loss is in ranking, not generation. Seeds reach
78.6% of ring accounts and two-hop expansion recovers a median 100% of a ring,
yet only 18.1% surface. Candidates are being produced and then ranked away by a
linear blend with hand-set weights.

This replaces the ordering, not the features. Every feature stays the one an
analyst can read, and the v1 score is retained and displayed alongside, because
a case whose rank cannot be interrogated does not produce a usable verdict --
GARG-AML's argument, and the reason IBM's Graph Feature Preprocessor pairs
hand-engineered features with boosting rather than reaching for a GNN.

Two rules are enforced here rather than left to discipline:

  * features come from the case record exactly as snapshotted at alert time,
    never recomputed;
  * train and test are split by time, never at random, because a random split
    lets the model learn from cases that had not happened yet.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

# `channel` never enters. 86.6% of laundering rows are ACH against an 11.8%
# base rate -- a generator artifact worth 7.3x that would inflate every number
# while teaching nothing transferable.
EXCLUDED = frozenset({"channel", "exact"})


def feature_names(features: dict) -> list[str]:
    """Numeric feature keys, in a stable order, minus the excluded ones."""
    return sorted(k for k, v in features.items()
                  if k not in EXCLUDED and isinstance(v, (int, float, bool)))


def vectorise(features: dict, names: list[str]) -> list[float]:
    out = []
    for n in names:
        v = features.get(n, 0.0)
        if isinstance(v, bool):
            v = float(v)
        elif not isinstance(v, (int, float)):
            v = 0.0
        # Infinities appear in latency features when an account never forwards.
        out.append(float(v) if math.isfinite(float(v)) else 0.0)
    return out


@dataclass
class TrainReport:
    n_train: int = 0
    n_test: int = 0
    n_positive_train: int = 0
    n_positive_test: int = 0
    split_t: int = 0
    features: list = field(default_factory=list)
    importances: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return (f"trained on {self.n_train} cases "
                f"({self.n_positive_train} positive), "
                f"tested on {self.n_test} ({self.n_positive_test} positive)")


class Reranker:
    """Predicts P(an analyst confirms this case)."""

    def __init__(self, seed: int = 7, max_iter: int = 200):
        self.model: HistGradientBoostingClassifier | None = None
        self.names: list[str] = []
        self.seed = seed
        self.max_iter = max_iter

    # -- training -------------------------------------------------------------

    def fit(self, cases) -> TrainReport:
        """Fit on disposed cases. `cases` carry `.features` and a binary label."""
        rows = [c for c in cases if c.disposition.verdict.is_resolved]
        if len(rows) < 20:
            raise ValueError(f"need at least 20 labelled cases, got {len(rows)}")

        self.names = feature_names(rows[0].features)
        X = np.array([vectorise(c.features, self.names) for c in rows])
        y = np.array([int(c.disposition.verdict.is_positive) for c in rows])

        if y.sum() == 0 or y.sum() == len(y):
            raise ValueError("labels are single-class; cannot train a ranker")

        self.model = HistGradientBoostingClassifier(
            max_iter=self.max_iter, random_state=self.seed,
            # The positive class is rare; without this the model learns to
            # predict "no" and is technically excellent and useless.
            class_weight="balanced",
            early_stopping=False,
        )
        self.model.fit(X, y)

        rep = TrainReport(n_train=len(rows), n_positive_train=int(y.sum()),
                          features=list(self.names))
        rep.importances = self.permutation_importance(X, y)
        return rep

    def permutation_importance(self, X, y, repeats: int = 3) -> dict:
        """Which features actually carry the ranking.

        Reported because an unexplainable ranker cannot be put in front of an
        analyst, and because it is the fastest way to discover that the model
        has latched onto something it should not have.
        """
        if self.model is None:
            return {}
        rng = np.random.default_rng(self.seed)
        base = self.model.score(X, y)
        out: dict[str, float] = {}
        for i, name in enumerate(self.names):
            drops = []
            for _ in range(repeats):
                Xp = X.copy()
                rng.shuffle(Xp[:, i])
                drops.append(base - self.model.score(Xp, y))
            out[name] = float(np.mean(drops))
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    # -- inference ------------------------------------------------------------

    def score_one(self, features: dict) -> float:
        if self.model is None:
            raise RuntimeError("reranker is not trained")
        X = np.array([vectorise(features, self.names)])
        return float(self.model.predict_proba(X)[0, 1])

    def rank(self, items, key=lambda c: c.features):
        """Order items by predicted confirmation probability, best first."""
        if self.model is None:
            raise RuntimeError("reranker is not trained")
        if not items:
            return []
        X = np.array([vectorise(key(c), self.names) for c in items])
        p = self.model.predict_proba(X)[:, 1]
        order = np.argsort(-p)
        return [items[i] for i in order], p[order]


def time_split(cases, fraction: float = 0.5) -> tuple[list, list, int]:
    """Split by time, never at random.

    A random split lets the model train on cases that had not happened yet when
    the test cases were scored. That inflates every number and is the single
    most common way a fraud model looks good offline and fails in production.
    """
    ordered = sorted(cases, key=lambda c: c.opened_t)
    if not ordered:
        return [], [], 0
    cut = int(len(ordered) * fraction)
    split_t = ordered[cut].opened_t if cut < len(ordered) else ordered[-1].opened_t
    train = [c for c in ordered if c.opened_t < split_t]
    test = [c for c in ordered if c.opened_t >= split_t]
    return train, test, split_t
