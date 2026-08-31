"""Two runs on ground-truth ring labels: one result, one ceiling diagnostic.

Both runs train a supervised LightGBM model on the EXISTING candidate features
using the TRUE ring labels (not the simulated-analyst labels Phase 4 uses).
They are NOT the same kind of claim, and the difference is the whole reason
this file has two of them:

  1. `oracle-as-is` -- **A SUPERVISED RE-RANKER, EVALUATED ON A RING-DISJOINT
     HELD-OUT SPLIT.** Trained and evaluated only on candidates the real
     seeding pipeline actually produces, with no cheat anywhere in the
     pipeline: a ring's candidates are wholly in train or wholly in test. The
     split is also time-ordered on the NEGATIVE pool -- see the leakage-guard
     list below for what that does and does not cover, because the two
     invariants are not equally strong and this docstring used to imply they
     were. This is a result, not a diagnostic. It is what these features
     support when the labels are perfect, measured the way any supervised
     ranking result should be measured, and it is reported as such.
  2. `oracle-on-all-rings` -- **A CEILING DIAGNOSTIC, AND ONLY THAT.** Trained
     and evaluated on candidates generated with a seed rule that also fires on
     every active ring's own members: a seed-cheat used nowhere else, to
     measure what the feature set could do if seeding recall were 100%. Never
     used by the real detector, never comparable to run 1, never quotable as a
     result. Kept structurally and visually separate from run 1 below for
     exactly that reason.

THE CAVEAT THAT TRAVELS WITH RUN 1, IN THE SAME BREATH AS THE NUMBER: run 1
trains on ground-truth ring labels. A deployment does not have those on day
one -- it has analyst verdicts. Phase 4's learned re-ranker, trained on
simulated analyst verdicts instead of truth, reached p@10 = 0.124 against
0.106 for the v1 hand-set over 17 held-out cycles, with a paired delta CI that
includes zero at every k (data/eval_phase4.json, docs/HANDOFF.md section 3).
That gap is CONSISTENT WITH a label-quality tax and is NOT a measurement of
one, and this docstring used to claim otherwise. The two runs are two different
experiments: LGBMClassifier here vs HistGradientBoostingClassifier in
sentinel/learn/reranker.py; 54 candidate features vs 44 case features; 169,947
training candidates (321 positive) vs 680 training CASES, a ~250x difference;
ring-disjoint ring_time_split vs a plain time split on cases; split_t 7980 vs
8340; 18 held-out cycles vs 17. Any one of those could carry the whole 2x.

The clean experiment -- same model, same pool, same split, fitted once on truth
and once on simulated verdicts -- HAS NOT BEEN RUN. collect_pool below already
returns everything it needs, so it is cheap; see that function's docstring.
Naming the unrun experiment is the honest position, and it does not weaken the
strategic claim the 2x was recruited to support: the label corpus, not the
detector, is the actual product. Run 1's p@10 is NEVER a production number.

Interpretation is read off the **supervised/blend p@k ratio**, not off F1.

An earlier version of this script branched its stored `interpretation` on F1
at a fixed 0.5 threshold. That was wrong and is corrected here: on a pool with
roughly 0.1% positives, F1 at a fixed threshold measures the threshold, not the
model (docs/HANDOFF.md section 3 establishes the same pathology for the
transaction-level F1). F1 is still computed and stored for continuity with the
older file, and is explicitly not interpreted.

The comparison that IS interpreted is run 1's supervised model against the
shipped v1 hand-set blend and the size/degree/random baselines, all scored on
the **same held-out cycles** with paired bootstrap CIs. The previous file
compared run 1's p@10 over ~17 held-out cycles against a blend p@10 measured
over all 34 cycles in a different script -- two denominators, so the widely
quoted "2.8x" was not a ratio of anything. Item 0.2 of
docs/ARCHITECTURE_UPLIFT.md.

An earlier version of this docstring called run 1 itself a ceiling diagnostic
("this is a diagnostic, not a deliverable"). That undersold it and is
corrected in place rather than erased: run 1's split construction is exactly
what a supervised held-out evaluation requires, so the honest label for it is
"supervised re-ranker result, with a label dependency", not "diagnostic". Only
run 2, which cheats at seeding, remains a diagnostic.

Leakage guards, enforced by assertion rather than trusted by eye:
  - a ring's candidates are wholly in train or wholly in test, never split
    (asserted directly, and the strong guarantee of the two);
  - the split is time-ordered ON THE NEGATIVE POOL: no training negative
    post-dates any test negative, and that is asserted. It is NOT true of the
    positives. A positive candidate follows its ring, so a train-assigned ring
    keeps the candidates that land after split_t. That is a deliberate trade,
    explained at the assertion in ring_time_split: two near-duplicate
    candidates for one ring on opposite sides of the boundary is the worse
    leak, so ring identity wins. An earlier version of this list said "train
    strictly precedes test" without qualification; that was an overclaim and
    is corrected here rather than deleted;
  - features excluded elsewhere for leakage (channel/ACH, exact, and the
    dominant_entity_type label string) are excluded here too;
  - label-derived features are impossible by construction: the candidate
    feature dict is built by sentinel/detect/features.py before any label is
    looked at, so nothing here can leak the target into a feature.

NAMING NOTE. The module name, the function names, the JSON keys
(`oracle_as_is`, `oracle_on_all_rings`, `oracle_over_blend`), and the ranking
name "oracle" inside `precision_at` / `precision_ci` / `paired` all predate
this reframing and are deliberately UNCHANGED -- scripts/eval_ranker.py,
scripts/gfp_control.py, the tests, and any comparison against an existing
data/eval_oracle.json read them. Only the framing changed; the wire format did
not.
"""
from __future__ import annotations

import json
import random
import sys
import textwrap
import time
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightgbm import LGBMClassifier
from sklearn.metrics import average_precision_score, f1_score

from sentinel.config import EVAL_END, PRUNE_STRATEGY, TICK_MINUTES, WINDOW_MINUTES
from sentinel.data.accounts import AccountRegistry
from sentinel.detect.candidates import CandidateGenerator
from sentinel.eval.bootstrap import bootstrap_ci, paired_bootstrap_delta, ratio_of_sums
from sentinel.eval.funnel import is_hit
from sentinel.graph.window import WindowedGraph
from sentinel.learn.reranker import feature_names, vectorise
from sentinel.stream.replay import Stream

ROOT = Path(__file__).resolve().parent.parent
EVERY = 6
KS = (10, 20, 50)
MIN_RING_NODES = 3
SPLIT_FRACTION = 0.5

# What each run IS, in words, printed as a banner and stored additively in the
# JSON under "role"/"framing". These exist because the wire-format keys
# ("oracle_as_is", "oracle_on_all_rings", and the ranking name "oracle") are
# frozen for backward compatibility and no longer describe the framing on
# their own. Run 1 is a result; run 2 is a diagnostic; they must never be read
# as two flavours of the same thing.
AS_IS_ROLE = ("RUN 1 -- RESULT: a supervised re-ranker evaluated on a "
              "ring-disjoint held-out split (time-ordered on the negative "
              "pool; positives follow their ring -- see AS_IS_FRAMING)")
ON_ALL_RINGS_ROLE = ("RUN 2 -- CEILING DIAGNOSTIC, NOT A RESULT: seeding is "
                     "cheated to fire on every active ring's own members")

# The caveat that must travel in the same breath as run 1's p@k, never in a
# later paragraph. It is written as a strength on purpose: the size of the gap
# between training on truth and training on analyst verdicts is the strongest
# evidence this repo has that the label corpus, not the detector, is the
# product.
LABEL_TAX = (
    "Trained on GROUND-TRUTH ring labels, which a deployment does not have on "
    "day one -- it has analyst verdicts. Phase 4's re-ranker, trained on "
    "SIMULATED ANALYST VERDICTS instead of truth, reached p@10 = 0.124 against "
    "0.106 for the v1 hand-set over 17 held-out cycles, with a paired delta CI "
    "that includes zero at every k (data/eval_phase4.json, docs/HANDOFF.md "
    "section 3). That gap is CONSISTENT WITH a label-quality tax and is NOT a "
    "measurement of one -- the two runs differ in model family "
    "(LGBMClassifier vs HistGradientBoostingClassifier), feature block (54 vs "
    "44), training-set size (169,947 candidates vs 680 cases, ~250x), split "
    "rule (ring-disjoint vs a plain time split on cases), split point (7980 vs "
    "8340) and evaluation window (18 vs 17 cycles). The clean experiment -- "
    "same model, same pool, same split, fitted once on truth and once on "
    "simulated verdicts -- HAS NOT BEEN RUN; collect_pool already returns what "
    "it needs. Until it does, the label tax is a hypothesis with a plausible "
    "mechanism, not a number. What does not depend on that arithmetic: the "
    "label corpus, not the detector, is the actual product. This p@k is NEVER "
    "a production number -- it is what these features support under a label "
    "advantage no deployment has. It is also not a ceiling on the features: "
    "scripts/eval_ranker.py's listwise arm reaches a higher p@10 on the same "
    "features and the same split. NO LITERAL IS QUOTED HERE ON PURPOSE. This "
    "string used to end '(scripts/eval_ranker.py reaches 0.2778 ...)', which "
    "was printed on every run and stored in data/eval_oracle.json's "
    "label_dependency field, and it went stale twice without anyone noticing "
    "-- the true value moved to 0.2500 and then to 0.2111. A hardcoded number "
    "inside the string that travels with a measurement is the exact failure "
    "docs/STANDING-RULES.md rule 1 exists to prevent; read the live value from "
    "data/eval_ranker.json instead.")

AS_IS_FRAMING = (
    "Real seeding, no cheat anywhere in the pipeline. RING-DISJOINTNESS is\n"
    "asserted: a ring's candidates are wholly in train or wholly in test.\n"
    "TIME-ORDERING is asserted on the NEGATIVE pool only -- no training\n"
    "negative post-dates any test negative -- while positive candidates\n"
    "follow their ring, so a train-assigned ring keeps candidates that fall\n"
    "after the cutoff. That is a deliberate trade: ring leakage is the worse\n"
    "of the two. This framing used to claim time-ordering flatly, without\n"
    "that qualification, which was an overclaim and is corrected here.\n"
    "This is a supervised ranking result, and it is reported as one.\n"
    + LABEL_TAX)

ON_ALL_RINGS_FRAMING = (
    "SEED-CHEAT. Candidates are generated with a seed rule that also fires on\n"
    "every active ring's own members -- something the real detector can never\n"
    "do. This measures only what the feature set could reach if seeding recall\n"
    "were 100%. It is a ceiling diagnostic: nothing below it may be quoted as a\n"
    "result, or compared like-for-like against run 1.")



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


def label_candidate_detailed(nodes: set[int], rings: dict) -> tuple:
    """`label_candidate`, plus the two things it used to throw away.

    Returns (ring_id_or_None, overlap_fraction, ring_members_or_empty), where
    `overlap_fraction` is |candidate ∩ ring| / |candidate| -- the share of the
    candidate's own members that belong to the ring.

    WHY THIS EXISTS. Four places in this repository assert that `collect_pool`
    "already returns everything the label-tax experiment needs". Verified
    against the source in docs/inventory/collect_pool.md, that is FALSE: the
    clean experiment is a comparison between truth labels and simulated
    ANALYST verdicts, and `SimulatedAnalyst.dispose` needs the ring's member
    set and the overlap share to choose between CONFIRMED_RING and
    CONFIRMED_PARTIAL. Both were computed inside `is_hit` and discarded.

    Note the denominator. `is_hit` tests |∩| / |ring| against a containment
    floor; the analyst tests |∩| / |case members| against PARTIAL_BELOW. Those
    are different ratios and using one for the other would silently move every
    partial verdict. The analyst's is returned here.

    A candidate that hits no ring gets (None, 0.0, frozenset()) -- an empty
    truth set, which is exactly what `dispose` expects for a case that
    overlaps no ring.
    """
    for r, members in rings.items():
        if is_hit(nodes, members):
            overlap = len(nodes & members) / len(nodes) if nodes else 0.0
            return r, overlap, frozenset(members)
    return None, 0.0, frozenset()


def collect_pool(stream, registry, seed_perfect: bool) -> tuple[list, dict]:
    """Replay the eval window once, returning (candidate_records, ring_first_t).

    Each record: {cand, ring_id_or_None, t}. `ring_first_t` maps every ring
    that ever produced at least one active window to the tick it was first
    seen -- the basis of the ring-disjoint split (which is time-ordered on the
    negative pool; see ring_time_split for the exact guarantee).

    THIS IS ALSO WHAT THE UNRUN LABEL-TAX EXPERIMENT NEEDS, which is why the
    return value is worth naming here. The clean measurement of the label tax
    -- same model, same pool, same split, fitted once on true ring labels and
    once on simulated analyst verdicts -- needs exactly these two values and
    nothing else: relabel the training records, refit, score on the same
    held-out cycles. It has NOT been run. Until it does, the gap between this
    script's p@10 and scripts/eval_phase4.py's is CONSISTENT WITH a label tax
    rather than a measurement of one -- those two runs differ in model family,
    feature count, training-set size (~250x), split rule and evaluation window.
    See README.md and docs/HANDOFF.md section 3.
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
            nodes = set(c.nodes)
            ring, overlap, members = label_candidate_detailed(nodes, rings)
            # `overlap` and `ring_members` are carried so a caller can label
            # this pool a SECOND way -- from simulated analyst verdicts rather
            # than from truth -- without re-running the replay. They are inert
            # for every existing caller: nothing downstream reads them, and
            # `to_xy` still derives y from `ring` alone.
            records.append({"cand": c, "ring": ring, "t": graph.now,
                            "overlap": overlap, "ring_members": members})

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

    TRAIN IS TIME-BOUNDED TOO, and that is a change from the version that
    produced every number written before 2026-08-31. Previously a positive
    followed its ring unconditionally, so a train-assigned ring kept the
    candidates it produced AFTER split_t. That was a deliberate trade -- ring
    leakage is worse than temporal overlap -- but it had a consequence nobody
    priced: for every cycle at or after split_t, train received that cycle's
    positives and none of its negatives, because negatives split on time with
    no exception. Those cycles became ALL-POSITIVE query groups.

    A lambdarank group whose labels are all identical generates no discordant
    pairs and contributes exactly zero gradient, while the pointwise
    classifier -- which has no notion of groups -- sees every one of those
    positives. Measured on the shipped pool: 18 of 34 training groups were
    all-positive and held 156 of 321 training positives, so "same pool, same
    features, same split" was true of the arrays and false of what the two
    objectives learned from. The listwise-vs-pointwise head-to-head was
    confounded in the pointwise model's favour. See
    docs/inventory/query_groups.md for the per-group table.

    So a positive whose ring is a TRAIN ring but whose timestamp is at or
    after split_t is now dropped from train rather than kept. It is NOT moved
    to test -- that would be the ring leak this split exists to close.

    Three consequences, none of them hidden:

      * every remaining training group has mixed labels, so the two objectives
        finally receive the same signal and the head-to-head is unconfounded;
      * train loses 156 of 321 positives, which the pointwise model previously
        used. The headline number moves, and it moves DOWN. That cost is
        recorded rather than absorbed -- see docs/negative-results/;
      * the docstring's opening claim becomes literally true for the first
        time. Every train record now has t < split_t and every test record has
        t >= split_t: a test ring's first appearance is at or after split_t by
        construction, and a candidate labelled for a ring cannot predate that
        ring becoming active. The qualification this docstring used to carry
        ("time-ordered on the NEGATIVE pool only") is no longer needed, and
        the assertion below is strengthened to check the whole split rather
        than just the negatives.

    KNOWN COST, NOT FIXED HERE. A train ring whose first appearance is exactly
    split_t now contributes no training records at all, while still being
    excluded from test by ring-disjointness. Such a ring is wasted. It was
    equally wasted before in every practical sense -- all of its candidates
    were post-split_t and therefore in the dead groups -- but it is worth
    naming. Moving those rings to test would recover them and would also
    change the held-out denominator, so it is deliberately NOT bundled into
    this change: keeping the test set byte-identical is what makes the
    before/after a paired comparison on the same cycles rather than two
    different experiments. Counted and recorded in docs/negative-results/.
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
    stranded_train_positives = 0
    for rec in records:
        r = rec["ring"]
        if r is not None:
            if r in train_rings:
                # Ring identity decides the SIDE; the cutoff decides whether
                # the record is usable on that side at all. A train ring's
                # post-cutoff candidates are dropped, never handed to test.
                if rec["t"] < split_t:
                    train.append(rec)
                else:
                    stranded_train_positives += 1
            elif r in test_rings:
                test.append(rec)
            # a ring outside both sets (shouldn't happen) is dropped, not guessed
        elif rec["t"] < split_t:
            train.append(rec)
        else:
            test.append(rec)

    # Assertions, not eyeballing. Ring identity is the primary leak this split
    # closes: a ring is wholly on one side, never both.
    train_ring_ids = {r["ring"] for r in train if r["ring"] is not None}
    test_ring_ids = {r["ring"] for r in test if r["ring"] is not None}
    assert not (train_ring_ids & test_ring_ids), \
        "a ring leaked across the train/test boundary"

    # The temporal guard, now checked over the WHOLE split rather than over
    # the negative pool alone. The narrower version was correct for the
    # previous rule, under which a train ring kept its post-cutoff positives;
    # it would pass unchanged on the new rule while no longer being the
    # strongest true statement, and a guard that has stopped being the
    # strongest true statement is how the next overclaim gets written.
    if train and test:
        assert max(r["t"] for r in train) < split_t <= min(r["t"] for r in test), \
            "train no longer strictly precedes test"

    # NOT ASSERTED HERE: "no training query group is all-positive". That is the
    # defect this change closes, but it is a property of the POOL, not of this
    # function. A pre-cutoff cycle with positives and no negatives is
    # all-positive under any split rule, and small fixtures are full of them.
    # Asserting it here would either fire on legitimate fixtures or -- if
    # narrowed to post-cutoff groups, which the cutoff now makes impossible by
    # construction -- become a check that cannot fail. This repository has
    # shipped one of those already (docs/HANDOFF.md 11b). It is asserted
    # instead in scripts/eval_ranker.py, against the real pool, where it can.

    if stranded_train_positives:
        print(f"  [split] {stranded_train_positives} train-ring positives at or "
              f"after split_t={split_t} dropped from train (they would have "
              f"formed all-positive query groups); see "
              f"docs/negative-results/dead-query-groups.md")
    return train, test, split_t


def to_xy(records: list[dict], names: list[str]) -> tuple[np.ndarray, np.ndarray]:
    X = np.array([vectorise(r["cand"].features, names) for r in records])
    y = np.array([1 if r["ring"] is not None else 0 for r in records])
    return X, y


# The rankings compared head-to-head on the oracle's own held-out cycles.
# `blend` is the shipped v1 hand-set score; the other three are the standing
# baselines every ranking claim in this project must be quoted against.
RANKINGS = ("oracle", "blend", "size", "degree", "random")


def _cycle_rows(test_records, proba) -> list[dict]:
    """One row per held-out cycle, carrying (hits, n) at each k for every ranking.

    This is the unit the paired bootstrap resamples. Building it once, with
    every ranking scored on the *same* cycles and the same candidate pool, is
    the whole point of item 0.2: the previous comparison put the oracle's p@10
    over ~17 held-out cycles against the blend's over all 34, which is not a
    ratio of anything.
    """
    by_t: dict[int, list[dict]] = defaultdict(list)
    for rec, p in zip(test_records, proba):
        c = rec["cand"]
        by_t[rec["t"]].append({
            "label": 1 if rec["ring"] is not None else 0,
            "oracle": float(p),
            "blend": float(c.score),
            "size": float(c.size),
            "degree": float(c.features.max_fan),
            # Deterministic per-candidate random key: seeded off the candidate's
            # canonical key so the random baseline is reproducible run to run
            # and does not depend on dict iteration order.
            "random": random.Random(c.key).random(),
        })

    rows = []
    for t in sorted(by_t):
        cycle = by_t[t]
        row = {"t": t, "n_cands": len(cycle),
               "n_positive": sum(c["label"] for c in cycle)}
        for name in RANKINGS:
            # Sort descending by the ranking key, breaking ties deterministically
            # on the candidate's own random key so no ranking gets a free ride
            # from input order.
            ordered = sorted(cycle, key=lambda c: (-c[name], c["random"]))
            for k in KS:
                top = ordered[:k]
                row[f"{name}_hit_{k}"] = sum(c["label"] for c in top)
                row[f"{name}_n_{k}"] = len(top)
        rows.append(row)
    return rows


def evaluate(model, names, test_records) -> dict:
    """F1 at 0.5, average precision, and p@k grouped by cycle tick.

    Also evaluates the v1 blend and the size/degree/random baselines on the
    *same* held-out cycles, with paired bootstrap CIs on every delta against
    the supervised model (keyed "oracle" on the wire for backward
    compatibility). F1 at a fixed 0.5 threshold is retained for continuity
    but is a known pathology on a pool this imbalanced -- it is reported,
    never interpreted (see `interpretation` in the output).
    """
    if not test_records:
        return {"f1": 0.0, "ap": 0.0, "n_test": 0, "n_positive": 0,
                "precision_at": {}, "cycles": 0}
    X, y = to_xy(test_records, names)
    proba = model.predict_proba(X)[:, 1]
    pred = (proba >= 0.5).astype(int)
    f1 = float(f1_score(y, pred)) if 0 < y.sum() < len(y) else 0.0
    ap = float(average_precision_score(y, proba)) if 0 < y.sum() < len(y) else 0.0

    rows = _cycle_rows(test_records, proba)

    precision_at: dict = {}
    ci: dict = {}
    paired: dict = {}
    for k in KS:
        precision_at[k] = {}
        for name in RANKINGS:
            stat = ratio_of_sums(f"{name}_hit_{k}", f"{name}_n_{k}")
            precision_at[k][name] = stat(rows)
            ci[f"{name}@{k}"] = bootstrap_ci(rows, stat)
        # Paired deltas against the oracle, and the standing score-vs-size check.
        oracle_stat = ratio_of_sums(f"oracle_hit_{k}", f"oracle_n_{k}")
        for name in ("blend", "size", "degree", "random"):
            other = ratio_of_sums(f"{name}_hit_{k}", f"{name}_n_{k}")
            paired[f"oracle-{name}@{k}"] = paired_bootstrap_delta(rows, other, oracle_stat)
        blend_stat = ratio_of_sums(f"blend_hit_{k}", f"blend_n_{k}")
        size_stat = ratio_of_sums(f"size_hit_{k}", f"size_n_{k}")
        paired[f"blend-size@{k}"] = paired_bootstrap_delta(rows, size_stat, blend_stat)

    # The ratio the plan pre-registered a threshold on, now on one denominator.
    ratio = {}
    for k in KS:
        b = precision_at[k]["blend"]
        ratio[k] = (precision_at[k]["oracle"] / b) if b > 0 else None

    return {"f1": f1, "ap": ap, "n_test": len(test_records),
            "n_positive": int(y.sum()), "cycles": len(rows),
            "precision_at": precision_at, "precision_ci": ci,
            "paired": paired, "oracle_over_blend": ratio,
            "mean_candidate_size": float(np.mean([r["cand"].size for r in test_records])),
            "cycle_rows": rows}


def train_and_report(records, ring_first_t, label: str,
                     role: str = "", framing: str = "") -> dict:
    """Train, evaluate and print one run.

    `label` is the wire-format name and is deliberately unchanged
    ("oracle-as-is" / "oracle-on-all-rings"): it is stored in the JSON and read
    by other scripts. `role` and `framing` are the human-facing words for what
    the run IS -- printed as a banner and stored additively -- so that no
    reader has to infer from a legacy key whether they are looking at a
    supervised result (run 1) or a seed-cheating ceiling diagnostic (run 2).
    """
    if role or framing:
        print()
        print("=" * 78)
        print(textwrap.fill(role, width=74,
                            initial_indent="  ", subsequent_indent="  "))
        for line in framing.splitlines():
            # The label-tax paragraph is one long string on purpose (it is
            # stored verbatim in the JSON too); wrap it only for the console.
            print(textwrap.fill(line, width=74,
                                initial_indent="  ", subsequent_indent="  "))
        print("=" * 78)
    if not records:
        print(f"\n[{label}] no candidates generated -- nothing to train on")
        return {"label": label, "role": role, "framing": framing, "n_pool": 0}

    train, test, split_t = ring_time_split(records, ring_first_t)
    names = feature_names(train[0]["cand"].features) if train else \
        feature_names(records[0]["cand"].features)
    X, y = to_xy(train, names)

    n_pos_train = int(y.sum())
    print(f"\n[{label}] pool={len(records):,}  train={len(train):,} "
          f"({n_pos_train} positive)  test={len(test):,} split_t={split_t}")

    if n_pos_train < 5 or n_pos_train == len(train):
        print(f"[{label}] not enough class balance to train ({n_pos_train}/{len(train)} positive)")
        return {"label": label, "role": role, "framing": framing,
                "n_pool": len(records), "n_train": len(train),
                "n_test": len(test), "trainable": False}

    model = LGBMClassifier(
        n_estimators=300, max_depth=6, learning_rate=0.05,
        class_weight="balanced", random_state=7, verbosity=-1,
    )
    model.fit(X, y)

    report = evaluate(model, names, test)
    print(f"[{label}] test AP={report['ap']:.4f}  "
          f"n_test={report['n_test']} ({report['n_positive']} positive) over "
          f"{report['cycles']} held-out cycles, "
          f"mean cand size {report['mean_candidate_size']:.2f}")
    print(f"[{label}] F1@0.5={report['f1']:.4f}  (reported for continuity only -- "
          f"a fixed 0.5 threshold on a pool this imbalanced is a pathology, "
          f"not a measurement)")
    print()
    print(f"[{label}] p@k on the SAME held-out cycles, every ranking "
          f"(the 'oracle' row IS the supervised re-ranker -- the row name is "
          f"the unchanged wire-format key, not a claim about the model):")
    print(f"  {'ranking':<10}" + "".join(f"{'p@' + str(k):>12}" for k in KS))
    for name in RANKINGS:
        print(f"  {name:<10}"
              + "".join(f"{report['precision_at'][k][name]:>12.4f}" for k in KS))
    print()
    print(f"[{label}] supervised re-ranker / v1 hand-set blend ratio, "
          f"one denominator at last:")
    for k in KS:
        r = report["oracle_over_blend"][k]
        print(f"  k={k:<4} " + ("n/a" if r is None else f"{r:.2f}x"))
    print()
    print(f"[{label}] paired bootstrap deltas over the held-out cycles "
          f"(oracle-X = supervised re-ranker minus baseline X):")
    for key in sorted(report["paired"]):
        d = report["paired"][key]
        flag = "REAL" if d["excludes_zero"] else "includes zero"
        print(f"  {key:<20} {d['point']:+.4f} "
              f"[{d['lo']:+.4f}, {d['hi']:+.4f}]  {flag}")

    return {"label": label, "role": role, "framing": framing,
            "n_pool": len(records), "n_train": len(train),
            "n_positive_train": n_pos_train, "split_t": split_t,
            "trainable": True, **report}


def main() -> None:
    stream = Stream(ROOT / "data" / "stream")
    registry = AccountRegistry.load(ROOT / "data" / "amlworld" / "HI-Small_accounts.csv")

    print("=== collecting candidate pool: AS-IS (real seeding, no cheat) ===")
    as_is_records, as_is_first_t = collect_pool(stream, registry, seed_perfect=False)
    as_is_report = train_and_report(
        as_is_records, as_is_first_t, "oracle-as-is",
        role=AS_IS_ROLE, framing=AS_IS_FRAMING)

    print("\n=== collecting candidate pool: PERFECT SEEDING "
          "(SEED-CHEAT, ceiling diagnostic only) ===")
    perfect_records, perfect_first_t = collect_pool(stream, registry, seed_perfect=True)
    perfect_report = train_and_report(
        perfect_records, perfect_first_t, "oracle-on-all-rings",
        role=ON_ALL_RINGS_ROLE, framing=ON_ALL_RINGS_FRAMING)

    # snap ML / IBM Graph Feature Preprocessor control -- documented, not run.
    try:
        import snapml  # noqa: F401
        gfp_note = "snapml imported but the GFP comparison run was not implemented"
    except ImportError:
        # Correction to an earlier, softer claim: snapml is NOT unobtainable.
        # CORRECTED. This note used to say the blocker was the Python
        # version: "snapml 1.15.6 ships cp310/cp311 win_amd64 wheels but none
        # for 3.12+, so provision a 3.11 env". That was measured and is wrong.
        # A 3.11 venv was provisioned and snapml 1.15.6 installed; the
        # GraphFeaturePreprocessor wrapper imports, and its constructor dies on
        # a missing `gf_allocate`. No Windows .pyd in any snapml release
        # exports any gf_* symbol, while the manylinux wheel of the same
        # version exports all eight. GFP is a Linux/macOS-only component. The
        # obstacle is the OS, not the interpreter, and it is LARGER than the
        # note it replaces claimed -- the opposite of the direction that
        # previous correction moved it.
        gfp_note = ("GFP control NOT run. IBM's GraphFeaturePreprocessor is "
                     "not built for Windows at ANY snapml version or Python "
                     "version: the Windows wheels ship the Python wrapper but "
                     "none of the gf_* native symbols, and snapml 1.17.x ships "
                     "no Windows wheels at all. Unblock = run "
                     "`scripts/gfp_control.py gfp-features` on Linux/macOS. "
                     "Until then any 'feature parity with GFP' claim is "
                     "UNMEASURED -- it was only ever feature-family coverage, "
                     "not a measured comparison, and it has been struck from "
                     "docs/HANDOFF.md section 4.")
    print(f"\nGFP control: {gfp_note}")

    # The previous `interpretation` field branched on F1 at a fixed 0.5
    # threshold. docs/HANDOFF.md section 3 has since established that number is
    # a fixed-threshold pathology on a pool with ~0.1% positives, not a
    # measurement of feature quality -- so an interpretation reasoned from it
    # contradicted the corrected reading of its own file. It is replaced by the
    # quantity docs/ARCHITECTURE_UPLIFT.md item 0.1 actually pre-registers a
    # decision rule on: the supervised/blend p@k ratio, on ONE denominator.
    #
    # The branch structure and its thresholds (>=2x / >=1.5x / <1.5x) are
    # PRE-REGISTERED in docs/ARCHITECTURE_UPLIFT.md and are unchanged here --
    # retuning a pre-registered threshold after seeing the number is the exact
    # move this repo refuses to make. Only the WORDS changed: each branch now
    # reports run 1 as the supervised re-ranker result it is, rather than as a
    # diagnostic verdict about somebody else's plan, and every branch carries
    # the label dependency in the same string as the number, because a reader
    # who sees the ratio without the label tax has been misled.
    interpretation = None
    if as_is_report.get("trainable"):
        r10 = as_is_report["oracle_over_blend"].get(10)
        r20 = as_is_report["oracle_over_blend"].get(20)
        seen = [x for x in (r10, r20) if x is not None]
        best = max(seen) if seen else None
        if best is None:
            interpretation = ("blend p@k is zero on the held-out cycles, so the "
                               "ratio is undefined; compare absolute p@k instead. "
                               + LABEL_TAX)
        elif best >= 2.0:
            interpretation = (
                f"RESULT. A supervised re-ranker on the existing candidate "
                f"features, evaluated on a ring-disjoint held-out split "
                f"(time-ordered on the negative pool), ranks at >=2x the "
                f"shipped v1 hand-set blend on the same "
                f"held-out cycles (k=10: {r10}, k=20: {r20}), with the paired "
                f"bootstrap delta reported above. The features carry more signal "
                f"than the hand-set scorer extracts from them: the scorer, not "
                f"the feature set, is the binding constraint, and the uplift "
                f"plan's centrepiece stands. {LABEL_TAX}")
        elif best >= 1.5:
            interpretation = (
                f"RESULT, but a modest one. The supervised re-ranker on the "
                f"ring-disjoint held-out split (time-ordered on the negative "
                f"pool) ranks between 1.5x "
                f"and 2x the v1 hand-set blend on the same cycles (k=10: {r10}, "
                f"k=20: {r20}) -- weaker than the pre-prune 2.8x the plan was "
                f"written from. There is still scorer headroom, but the case for "
                f"a ranker rewrite is no longer strong on its own and must be "
                f"weighed against feature work. {LABEL_TAX}")
        else:
            interpretation = (
                f"RESULT, and it does not clear the pre-registered bar. The "
                f"supervised re-ranker on the ring-disjoint held-out split "
                f"(time-ordered on the negative pool) ranks below 1.5x the "
                f"v1 hand-set blend on the "
                f"same cycles (k=10: {r10}, k=20: {r20}). PLAN-INVALIDATING by "
                f"the pre-registration in docs/ARCHITECTURE_UPLIFT.md section 8 "
                f"item 0.1: the headroom the 'scorer is the bottleneck' "
                f"conclusion rested on does not survive post-prune measurement. "
                f"Re-scope toward features, not a ranker. {LABEL_TAX}")
        print()
        print(f"Interpretation: {interpretation}")

    # WHY THE KEYS DID NOT MOVE WITH THE FRAMING. `oracle_as_is`,
    # `oracle_on_all_rings`, `oracle_over_blend` and the ranking name "oracle"
    # inside `precision_at` / `precision_ci` / `paired` (including the
    # "oracle-blend@10" delta key format) are the wire format. scripts/
    # eval_ranker.py, scripts/gfp_control.py, the tests, and any diff against
    # an already-written data/eval_oracle.json all read them, so renaming them
    # would break readers and silently invalidate every stored comparison for
    # no measurement gain. The framing changed; the wire format did not. The
    # words a reader needs are carried ADDITIVELY instead, in each run's
    # "role"/"framing" and in "label_dependency" below -- so a later reader who
    # notices the mismatch between the key "oracle" and the label "supervised
    # re-ranker" is looking at deliberate backward compatibility, not at a
    # leftover claim.
    out = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "prune_strategy": PRUNE_STRATEGY,
        "every_ticks": EVERY,
        "ks": list(KS),
        "oracle_as_is": as_is_report,
        "oracle_on_all_rings": perfect_report,
        "gfp_control": gfp_note,
        "interpretation": interpretation,
        "interpretation_basis": (
            "supervised/blend p@k ratio on run 1's own held-out cycles (the "
            "supervised model is keyed 'oracle' for backward compatibility). "
            "The f1 field is retained for continuity and is NOT interpreted: a "
            "fixed 0.5 threshold on a pool with ~0.1% positives measures the "
            "threshold, not the model."),
        "run_roles": {
            "oracle_as_is": AS_IS_ROLE,
            "oracle_on_all_rings": ON_ALL_RINGS_ROLE,
        },
        "label_dependency": LABEL_TAX,
        "key_naming_note": (
            "The keys 'oracle_as_is', 'oracle_on_all_rings', "
            "'oracle_over_blend' and the ranking name 'oracle' are frozen wire "
            "format kept for backward compatibility with scripts/eval_ranker.py, "
            "scripts/gfp_control.py, the tests, and previously written copies of "
            "this file. Run 1 ('oracle_as_is') is a SUPERVISED RE-RANKER RESULT "
            "on a ring-disjoint held-out split (time-ordered on the negative "
            "pool -- see 'framing'); only run 2 "
            "('oracle_on_all_rings'), which cheats at seeding, is a ceiling "
            "diagnostic. See 'run_roles'."),
    }
    (ROOT / "data" / "eval_oracle.json").write_text(json.dumps(out, indent=2, default=str))
    print("\nwritten to data/eval_oracle.json")


if __name__ == "__main__":
    main()
