"""Ring-level surfacing, reported as a SECONDARY estimator beside p@k.

The cycle is the unit information retrieval hands you, because a query is a
natural independence draw. The thing under test here is not a queue but a
scorer -- a function on candidate subgraphs -- so collapsing every scoring
decision in a cycle into one p@10 and averaging 18 of those discards most of
the discriminative events in the one place the project is sample-starved.

This measures P(ring surfaces in the top k of its own cycle | the ring was
BUILT), which has 145 Bernoulli trials against the cycle unit's 18.

THE CLUSTERING IS THE WHOLE METHOD, and the obvious choice is wrong. Those 145
trials come from only 68 distinct rings: a ring recurs across cycles, so
resampling cycles handles within-cycle correlation and leaves repeated measures
on the same ring uncorrected. Measured on the shipped blend, cycle-clustering
returns a 0.0396-wide interval where ring-clustering returns 0.0890 -- more
than twice as wide. Reporting the former would be a confidently narrower wrong
answer. Both are computed here and the WIDER is reported.

What this metric structurally cannot see, printed with every number for the
same reason `CostModel.unsourced()` prints its placeholders: it conditions on
BUILT, and BIPARTITE and STACK are absent from the built set systematically
rather than at random. The 26.3 points lost at the build stage are invisible
here, and the conditioning flatters every ranker it scores.

p@k with its size baseline remains the reported number. This is the faster
instrument, and the rule is that a faster instrument may decide how quickly you
learn, never what is true.

Run:  python scripts/eval_ring_unit.py
"""
from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lightgbm import LGBMClassifier

from sentinel.corpus import (CorpusKey, load, require_consistent,
                             require_poolable)

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "data" / "corpus_amlworld_hi_small.npz"
OUT = ROOT / "data" / "eval_ring_unit.json"
DATASET = "amlworld-hi-small"
# Sentinel builds its own candidate boundaries by seed-and-expand. Stated as a
# constant rather than inferred, because the alternative -- a dataset that
# SHIPS its subgraphs -- produces a different object under an otherwise
# identical config, and this is the field that keeps the two apart.
PROVENANCE = "constructed"
# What is being asked of the corpus. `require_poolable` refuses a question it
# has no validity entry for, so this string is load-bearing: it is the point at
# which "may these corpora be pooled" gets a real answer instead of a default.
QUESTION = "scorer"
K = 10
N_RESAMPLES = 2000
SEED = 7

BANNER = """\
CONDITIONING -- read with every number below.
  This is P(ring in top %d of its cycle | the ring was BUILT).
  It cannot see the 26.3 points lost at the build stage, where BIPARTITE
  (16%% built) and STACK (30%% built) are lost systematically, not at random.
  It therefore reads HIGHER than the unconditioned p@k and is not comparable
  to it. p@k with its size baseline remains the reported number."""


def trials(rank_by, tte, ring, cycles) -> list[tuple[int, int, int]]:
    """One (cycle, ring, surfaced) row per BUILT (ring, cycle) pair."""
    out = []
    for t in cycles:
        idx = np.flatnonzero(tte == t)
        order = idx[np.argsort(-rank_by[idx], kind="stable")][:K]
        top = set(ring[order][ring[order] >= 0].tolist())
        for r in sorted(set(ring[idx][ring[idx] >= 0].tolist())):
            out.append((int(t), int(r), 1 if r in top else 0))
    return out


def _clustered(rows, key_index, value, n_resamples=N_RESAMPLES, seed=SEED):
    """Cluster bootstrap: resample whole clusters, pool their member trials."""
    keys = sorted({r[key_index] for r in rows})
    groups = {k: [r for r in rows if r[key_index] == k] for k in keys}
    rng = random.Random(seed)
    draws = []
    for _ in range(n_resamples):
        sample = [x for _ in keys for x in groups[keys[rng.randrange(len(keys))]]]
        draws.append(value(sample) if sample else 0.0)
    draws.sort()
    lo = draws[int(0.025 * n_resamples)]
    hi = draws[min(int(0.975 * n_resamples), n_resamples - 1)]
    return lo, hi


def interval(rows, value) -> dict:
    """The conservative interval: widest of cycle- and ring-clustered."""
    point = value(rows)
    lo_c, hi_c = _clustered(rows, 0, value)
    lo_r, hi_r = _clustered(rows, 1, value)
    return {"point": point,
            "lo": min(lo_c, lo_r), "hi": max(hi_c, hi_r),
            "cycle_clustered": {"lo": lo_c, "hi": hi_c, "width": hi_c - lo_c},
            "ring_clustered": {"lo": lo_r, "hi": hi_r, "width": hi_r - lo_r},
            "n_trials": len(rows),
            "n_rings": len({r[1] for r in rows}),
            "n_cycles": len({r[0] for r in rows})}


def _mean(i):
    return lambda rows: sum(r[i] for r in rows) / len(rows) if rows else 0.0


def main() -> int:
    t0 = time.time()
    arrays, key = load(CORPUS, expect=CorpusKey.for_current_config(
        DATASET, [str(n) for n in np.load(CORPUS, allow_pickle=True)["names"]],
        PROVENANCE))
    provenance = require_poolable([key], QUESTION)
    print(f"corpus {key.describe()}  (no replay: the stream holds no further "
          f"information about a scorer question)")
    print(f"candidate provenance: {provenance} -- a {QUESTION} question, so "
          f"pooling across provenance would be permitted; only one is loaded")

    # The key proves no generation CONSTANT changed. It cannot prove no
    # feature COMPUTATION changed -- the first corpus adopted here was stale in
    # exactly that way and its key matched. So the blend is recomputed from the
    # stored features and must agree with today's code, exactly.
    names = [str(n) for n in arrays["names"]]
    checked = require_consistent(arrays, names)
    print(f"scoring consistency: {checked['n_checked']} sampled rows recomputed, "
          f"0 disagreements -- the corpus is what this code would build today")

    model = LGBMClassifier(n_estimators=300, max_depth=6, learning_rate=0.05,
                           class_weight="balanced", random_state=SEED,
                           verbosity=-1)
    model.fit(arrays["train_X"], arrays["train_y"])
    score = model.predict_proba(arrays["test_X"])[:, 1]

    tte, ring, blend = arrays["test_t"], arrays["test_ring"], arrays["test_blend"]
    size = arrays["test_size"]
    cycles = sorted(set(tte.tolist()))

    rows = {"supervised": trials(score, tte, ring, cycles),
            "blend": trials(blend, tte, ring, cycles),
            "size": trials(size, tte, ring, cycles)}

    print()
    print(BANNER % K)
    r0 = rows["supervised"]
    print(f"\n{len(r0)} ring-trials from {len({r[1] for r in r0})} distinct "
          f"rings across {len({r[0] for r in r0})} held-out cycles.")
    print("Reported interval is the WIDER of cycle- and ring-clustered; a ring "
          "recurs\nacross cycles, so cycle-clustering alone is anticonservative.\n")

    out = {"measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "corpus_key": key.to_dict(), "k": K,
           "question": QUESTION, "candidate_provenance": provenance,
           "conditioning": "P(ring in top k | BUILT); blind to the 26.3-point "
                           "build-stage loss, which is systematic not random",
           "rankings": {}, "paired": {}}

    for name, rs in rows.items():
        ci = interval(rs, _mean(2))
        out["rankings"][name] = ci
        print(f"  {name:<11} P(surfaced|built) {ci['point']:.4f} "
              f"[{ci['lo']:.4f}, {ci['hi']:.4f}]  width {ci['hi']-ci['lo']:.4f}"
              f"   (cycle-clust {ci['cycle_clustered']['width']:.4f} / "
              f"ring-clust {ci['ring_clustered']['width']:.4f})")

    # The delta is what decides an experiment, so it carries the same treatment.
    paired = [(a[0], a[1], a[2], b[2])
              for a, b in zip(rows["supervised"], rows["blend"])]
    assert all(a[0] == b[0] and a[1] == b[1]
               for a, b in zip(rows["supervised"], rows["blend"])), \
        "paired rows must align on (cycle, ring)"
    delta = lambda rs: (sum(r[2] for r in rs) - sum(r[3] for r in rs)) / len(rs)
    d = interval(paired, delta)
    d["excludes_zero"] = d["lo"] > 0 or d["hi"] < 0
    out["paired"]["supervised_minus_blend"] = d
    print(f"\n  supervised - blend  {d['point']:+.4f} [{d['lo']:+.4f}, "
          f"{d['hi']:+.4f}]  width {d['hi']-d['lo']:.4f}  "
          f"{'EXCLUDES zero' if d['excludes_zero'] else 'includes zero'}")

    out["seconds"] = round(time.time() - t0, 2)
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"\nwrote {OUT.name} in {out['seconds']}s "
          f"(the same question cost a ~55-minute replay before)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
