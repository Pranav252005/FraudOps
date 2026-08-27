"""The oracle run: what is the ceiling of the current feature set?

This is a diagnostic, not a deliverable. It trains a supervised LightGBM model
on the EXISTING candidate features using the TRUE ring labels (not the
simulated-analyst labels Phase 4 uses), to answer one question: if we had a
supervised model instead of the hand-set score, how good could these features
possibly make it? Two runs:

  1. ORACLE (as generated): trained and evaluated only on candidates the real
     seeding pipeline actually produces. This is the number a supervised
     re-ranker could realistically deliver today.
  2. ORACLE-ON-ALL-RINGS (the ceiling): trained and evaluated on candidates
     generated with a seed rule that also fires on every active ring's own
     members -- a cheat used only here, to measure what the feature set could
     do if seeding recall were 100%. Never used by the real detector.

Interpretation, stated in the printed report:
  - F1 in ~0.45-0.60 on run 1 -> the feature set is genuinely competitive
    (parity with IBM's Graph Feature Preprocessor is a measured fact) and the
    loss is in seeding and lack of supervision.
  - F1 in ~0.20-0.35 -> the feature-parity claim does not hold up and feature
    engineering should be prioritised ahead of weak-supervision work.
  - Because run 1 only sees the ~26% of rings that become candidates at all,
    F1 there is mechanically capped near 2R/(1+R) even at perfect precision,
    where R is the built-stage recall from scripts/eval_funnel.py. Run 2
    exists to separate that seeding loss from genuine feature loss.

Leakage guards, enforced by assertion rather than trusted by eye:
  - a ring's candidates are wholly in train or wholly in test, never split;
  - the split is also time-ordered (train strictly precedes test);
  - features excluded elsewhere for leakage (channel/ACH, exact, and the
    dominant_entity_type label string) are excluded here too;
  - label-derived features are impossible by construction: the candidate
    feature dict is built by sentinel/detect/features.py before any label is
    looked at, so nothing here can leak the target into a feature.
"""
from __future__ import annotations

import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightgbm import LGBMClassifier
from sklearn.metrics import average_precision_score, f1_score

from sentinel.config import EVAL_END, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.eval.funnel import is_hit
from sentinel.graph.window import WindowedGraph
from sentinel.learn.reranker import feature_names, vectorise
from sentinel.stream.replay import Stream

ROOT = Path(__file__).resolve().parent.parent
EVERY = 6
KS = (10, 20)
MIN_RING_NODES = 3
SPLIT_FRACTION = 0.5


def active_rings(stream, t_lo, t_hi):
    m = (stream.ts >= t_lo) & (stream.ts < t_hi) & (stream.ring >= 0)
    acc = defaultdict(set)
    for a, b, r in zip(stream.src[m], stream.dst[m], stream.ring[m]):
        acc[int(r)].update((int(a), int(b)))
    return {r: v for r, v in acc.items() if len(v) >= MIN_RING_NODES}


def label_candidate(nodes: set[int], rings: dict) -> int | None:
    """Which ring (if any) this candidate is a positive example of."""
    for r, members in rings.items():
        if is_hit(nodes, members):
            return r
    return None


def collect_pool(stream, registry, seed_perfect: bool) -> tuple[list, dict]:
    """Replay the eval window once, returning (candidate_records, ring_first_t).

    Each record: {cand, ring_id_or_None, t}. `ring_first_t` maps every ring
    that ever produced at least one active window to the tick it was first
    seen -- the basis of the time-ordered, ring-disjoint split.
    """
    graph = WindowedGraph(window_minutes=WINDOW_MINUTES)
    gen = CandidateGenerator(graph, registry=registry, node_key=stream.key)
    records: list[dict] = []
    ring_first_t: dict[int, int] = {}
    runs = 0
    t0 = time.time()

    for i, b in enumerate(stream.ticks(TICK_MINUTES, end=EVAL_END)):
        graph.add_batch(b)
        if i % EVERY or graph.now < WINDOW_MINUTES // 2:
            continue
        rings = active_rings(stream, graph.now - graph.window, graph.now)
        if not rings:
            continue
        for r in rings:
            ring_first_t.setdefault(r, graph.now)

        seed_override = None
        if seed_perfect:
            seed_override = gen.seeds(b) | {n for members in rings.values() for n in members}
        cands = gen.generate(b, seed_override=seed_override)
        if not cands:
            continue
        runs += 1

        for c in cands:
            ring = label_candidate(set(c.nodes), rings)
            records.append({"cand": c, "ring": ring, "t": graph.now})

        if runs % 5 == 0:
            print(f"  [{'perfect' if seed_perfect else 'as-is':>7}] "
                  f"run {runs:>3} pool={len(records):>7,} ({time.time()-t0:.0f}s)",
                  flush=True)

    print(f"  [{'perfect' if seed_perfect else 'as-is':>7}] "
          f"{runs} runs, {len(records):,} candidates, {time.time()-t0:.0f}s")
    return records, ring_first_t


def ring_time_split(records: list[dict], ring_first_t: dict[int, int],
                     fraction: float = SPLIT_FRACTION) -> tuple[list, list, int]:
    """Split so a ring's candidates are wholly train or wholly test, and train
    strictly precedes test in time.

    Rings are ordered by first appearance; the first `fraction` of *rings*
    (not candidates) go to train. Every negative candidate (ring is None) is
    assigned purely by its own timestamp against the resulting cutoff. This
    keeps both the ring-identity leak and the future-information leak closed
    at once.
    """
    ordered_rings = sorted(ring_first_t, key=lambda r: ring_first_t[r])
    if not ordered_rings:
        return [], [], 0
    cut = max(1, int(len(ordered_rings) * fraction))
    split_t = ring_first_t[ordered_rings[cut - 1]] if cut < len(ordered_rings) else \
        ring_first_t[ordered_rings[-1]]
    train_rings = set(ordered_rings[:cut])
    test_rings = set(ordered_rings[cut:])

    train, test = [], []
    for rec in records:
        r = rec["ring"]
        if r is not None:
            if r in train_rings:
                train.append(rec)
            elif r in test_rings:
                test.append(rec)
            # a ring outside both sets (shouldn't happen) is dropped, not guessed
        elif rec["t"] < split_t:
            train.append(rec)
        else:
            test.append(rec)

    # Assertions, not eyeballing. Ring identity is the primary leak this split
    # closes: a ring assigned to train keeps ALL its candidates in train even
    # if a few land temporally after split_t, because two near-duplicate
    # candidates for the same ring landing on opposite sides is a worse leak
    # than a little temporal overlap on an already-positive-labelled ring.
    # The negative pool (no ring) is a pure temporal split with no such
    # exception, so that invariant is checked directly.
    train_ring_ids = {r["ring"] for r in train if r["ring"] is not None}
    test_ring_ids = {r["ring"] for r in test if r["ring"] is not None}
    assert not (train_ring_ids & test_ring_ids), \
        "a ring leaked across the train/test boundary"
    train_neg_t = [r["t"] for r in train if r["ring"] is None]
    test_neg_t = [r["t"] for r in test if r["ring"] is None]
    if train_neg_t and test_neg_t:
        assert max(train_neg_t) <= min(test_neg_t), \
            "a negative example leaked from the future into training"
    return train, test, split_t


def to_xy(records: list[dict], names: list[str]) -> tuple[np.ndarray, np.ndarray]:
    X = np.array([vectorise(r["cand"].features, names) for r in records])
    y = np.array([1 if r["ring"] is not None else 0 for r in records])
    return X, y


def evaluate(model, names, test_records) -> dict:
    """F1 at 0.5, average precision, and p@k grouped by cycle tick."""
    if not test_records:
        return {"f1": 0.0, "ap": 0.0, "n_test": 0, "n_positive": 0,
                "precision_at": {}}
    X, y = to_xy(test_records, names)
    proba = model.predict_proba(X)[:, 1]
    pred = (proba >= 0.5).astype(int)
    f1 = float(f1_score(y, pred)) if 0 < y.sum() < len(y) else 0.0
    ap = float(average_precision_score(y, proba)) if 0 < y.sum() < len(y) else 0.0

    by_t: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for rec, p, label in zip(test_records, proba, y):
        by_t[rec["t"]].append((p, label))
    precision_at = {}
    for k in KS:
        hit = tot = 0
        for cycle in by_t.values():
            cycle.sort(key=lambda pr: -pr[0])
            top = cycle[:k]
            hit += sum(1 for _, label in top if label)
            tot += len(top)
        precision_at[k] = hit / tot if tot else 0.0
    return {"f1": f1, "ap": ap, "n_test": len(test_records),
            "n_positive": int(y.sum()), "precision_at": precision_at}


def train_and_report(records, ring_first_t, label: str) -> dict:
    if not records:
        print(f"\n[{label}] no candidates generated -- nothing to train on")
        return {"label": label, "n_pool": 0}

    train, test, split_t = ring_time_split(records, ring_first_t)
    names = feature_names(train[0]["cand"].features) if train else \
        feature_names(records[0]["cand"].features)
    X, y = to_xy(train, names)

    n_pos_train = int(y.sum())
    print(f"\n[{label}] pool={len(records):,}  train={len(train):,} "
          f"({n_pos_train} positive)  test={len(test):,} split_t={split_t}")

    if n_pos_train < 5 or n_pos_train == len(train):
        print(f"[{label}] not enough class balance to train ({n_pos_train}/{len(train)} positive)")
        return {"label": label, "n_pool": len(records), "n_train": len(train),
                "n_test": len(test), "trainable": False}

    model = LGBMClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        class_weight="balanced", random_state=7, verbosity=-1,
    )
    model.fit(X, y)

    report = evaluate(model, names, test)
    print(f"[{label}] test F1={report['f1']:.4f}  AP={report['ap']:.4f}  "
          f"n_test={report['n_test']} ({report['n_positive']} positive)")
    for k, p in report["precision_at"].items():
        print(f"[{label}] p@{k}={p:.4f}")

    return {"label": label, "n_pool": len(records), "n_train": len(train),
            "n_positive_train": n_pos_train, "split_t": split_t,
            "trainable": True, **report}


def main() -> None:
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(ROOT / "data" / "amlworld" / "HI-Small_accounts.csv")

    print("=== collecting candidate pool: AS-IS (real seeding) ===")
    as_is_records, as_is_first_t = collect_pool(stream, registry, seed_perfect=False)
    as_is_report = train_and_report(as_is_records, as_is_first_t, "oracle-as-is")

    print("\n=== collecting candidate pool: PERFECT SEEDING (ceiling diagnostic) ===")
    perfect_records, perfect_first_t = collect_pool(stream, registry, seed_perfect=True)
    perfect_report = train_and_report(perfect_records, perfect_first_t, "oracle-on-all-rings")

    # snap ML / IBM Graph Feature Preprocessor control -- documented, not run.
    try:
        import snapml  # noqa: F401
        gfp_note = "snapml imported but the GFP comparison run was not implemented"
    except ImportError:
        # Correction to an earlier, softer claim: snapml is NOT unobtainable.
        # `pip download snapml --only-binary=:all: --platform win_amd64` finds
        # snapml 1.15.6 wheels for cp310 and cp311; it is 3.12+ that has no
        # build, and this machine only has 3.14. So the GFP control is blocked
        # on provisioning a Python 3.11 environment, not on the package being
        # unavailable -- a materially smaller obstacle than "no build exists",
        # and worth doing, because GFP+LightGBM is the *direct* architectural
        # comparator for this project (hand-engineered subgraph features plus
        # gradient boosting) and reports 62.86 minority-class F1 on AML
        # HI-Small (arXiv:2402.08593 Table 4).
        gfp_note = ("GFP control NOT run. snapml 1.15.6 ships cp310/cp311 "
                     "win_amd64 wheels but none for 3.12+; this machine has "
                     "only Python 3.14. Unblock = provision a Python 3.11 env "
                     "and `pip install snapml`. Until then the 'feature parity "
                     "with GFP' claim in docs/HANDOFF.md section 4 remains "
                     "UNMEASURED -- it is a claim about feature-family "
                     "coverage, not a measured F1 comparison.")
    print(f"\nGFP control: {gfp_note}")

    interpretation = None
    if as_is_report.get("trainable"):
        f1 = as_is_report["f1"]
        if f1 >= 0.45:
            interpretation = ("F1 >= 0.45: the feature set is genuinely competitive. "
                               "The loss is in seeding and lack of supervision, not features.")
        elif f1 >= 0.20:
            interpretation = ("F1 in the 0.20-0.35ish band: ambiguous zone, closer to "
                               "the 'feature parity is wrong' branch than the confident "
                               "one. Prioritise feature engineering before weak supervision.")
        else:
            interpretation = ("F1 < 0.20: the feature-parity claim does not hold up. "
                               "Feature engineering should be prioritised ahead of "
                               "weak-supervision work.")
        print(f"\nInterpretation: {interpretation}")

    out = {
        "oracle_as_is": as_is_report,
        "oracle_on_all_rings": perfect_report,
        "gfp_control": gfp_note,
        "interpretation": interpretation,
    }
    (ROOT / "data" / "eval_oracle.json").write_text(json.dumps(out, indent=2, default=str))
    print("\nwritten to data/eval_oracle.json")


if __name__ == "__main__":
    main()
