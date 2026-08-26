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
from sklearn.metrics import average_precision_score

# `channel` never enters. 86.6% of laundering rows are ACH against an 11.8%
# base rate -- a generator artifact worth 7.3x that would inflate every number
# while teaching nothing transferable.
EXCLUDED = frozenset({"channel", "exact", "dominant_entity_type"})


def feature_names(features) -> list[str]:
    """Numeric feature keys, in a stable order, minus the excluded ones."""
    features = as_dict(features)
    return sorted(k for k, v in features.items()
                  if k not in EXCLUDED and isinstance(v, (int, float, bool)))


def as_dict(features) -> dict:
    """Accept either a raw feature dict or the Features dataclass.

    Cases store features as a dict (snapshotted at alert time); live candidates
    carry the dataclass. Both must vectorise identically or the model is trained
    on one representation and scored on another.
    """
    if isinstance(features, dict):
        return features
    to_dict = getattr(features, "to_dict", None)
    return to_dict() if callable(to_dict) else dict(vars(features))


def vectorise(features, names: list[str]) -> list[float]:
    features = as_dict(features)
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
    train_ap: float = 0.0
    test_ap: float = 0.0
    base_rate: float = 0.0
    features: list = field(default_factory=list)
    importances: dict = field(default_factory=dict)

    @property
    def ap_lift(self) -> float:
        return self.test_ap / self.base_rate if self.base_rate else 0.0

    def __str__(self) -> str:
        base = (f"trained on {self.n_train} cases "
                f"({self.n_positive_train} positive), "
                f"tested on {self.n_test} ({self.n_positive_test} positive)")
        if self.test_ap:
            base += ("\n  average precision: "
                     f"train {self.train_ap:.4f} (memorised) / "
                     f"test {self.test_ap:.4f} vs base {self.base_rate:.4f} "
                     f"= {self.ap_lift:.2f}x")
        return base


class Reranker:
    """Predicts P(an analyst confirms this case)."""

    def __init__(self, seed: int = 7, max_iter: int = 200):
        self.model: HistGradientBoostingClassifier | None = None
        self.names: list[str] = []
        self.seed = seed
        self.max_iter = max_iter

    # -- training -------------------------------------------------------------

    def fit(self, cases, validation=None) -> TrainReport:
        """Fit on disposed cases, optionally scoring importance on held-out ones.

        `validation` matters more than it looks. With a rare positive class this
        model memorises the training set completely (train average precision
        1.0000), so permutation importance measured there reports 0.0000 for
        every feature -- shuffling one cannot hurt a model that has the rest of
        the row memorised. Importance is only meaningful on data the model has
        not seen.
        """
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

        val = [c for c in (validation or [])
               if c.disposition.verdict.is_resolved]
        if val:
            Xv = np.array([vectorise(c.features, self.names) for c in val])
            yv = np.array([int(c.disposition.verdict.is_positive) for c in val])
            rep.n_test = len(val)
            rep.n_positive_test = int(yv.sum())
            if 0 < yv.sum() < len(yv):
                rep.train_ap = float(average_precision_score(
                    y, self.model.predict_proba(X)[:, 1]))
                rep.test_ap = float(average_precision_score(
                    yv, self.model.predict_proba(Xv)[:, 1]))
                rep.base_rate = float(yv.mean())
                rep.importances = self.permutation_importance(Xv, yv)
        return rep

    def permutation_importance(self, X, y, repeats: int = 5) -> dict:
        """Which features actually carry the ranking.

        Scored by **average precision, not accuracy**. At a 2.6% positive rate
        accuracy is dominated by predicting "no", so shuffling any single
        feature barely moves it -- the first version of this method reported
        ~0.000 for every feature while the model was in fact re-ranking 4x
        better than the hand-set weights. Average precision measures the
        ordering, which is what this model is for.

        Reported because a rank an analyst cannot interrogate is not usable,
        and because it is the fastest way to see a model latch onto something
        it should not have.
        """
        if self.model is None:
            return {}
        rng = np.random.default_rng(self.seed)
        base = average_precision_score(y, self.model.predict_proba(X)[:, 1])
        out: dict[str, float] = {}
        for i, name in enumerate(self.names):
            drops = []
            for _ in range(repeats):
                Xp = X.copy()
                rng.shuffle(Xp[:, i])
                drops.append(base - average_precision_score(
                    y, self.model.predict_proba(Xp)[:, 1]))
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
            return [], np.array([])
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
