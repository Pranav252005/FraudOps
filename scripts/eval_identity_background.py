"""Phase A gate: is the synthetic-identity background hard enough to keep?

Runs the four trivial baselines named in
`prereg/synthetic_identity_kill_rule.md` over the pre-registered sweep, and
applies the kill rule to the result. If the gate fails, no later phase starts.

Refuses to run unless BOTH pre-registrations are committed and clean, by the
same mechanism `scripts/eval_label_tax.py` uses: a prereg written in the same
breath as the result it judges is not a prereg.

    python scripts/eval_identity_background.py --config primary
    python scripts/eval_identity_background.py --config sweep

What this measures is NOT the harness p@k. It is a node-level ranking over the
whole population with no seeding, no expansion and no candidates -- the
strictest form of the trivial-baseline question, and a different quantity from
anything `sentinel/report/metric.py` renders. Its intervals resample WORLDS,
which is a clustering name none of the three the `Metric` type accepts, and that
is deliberate: these numbers must not be able to masquerade as candidate-level
p@k later.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sentinel.eval.bootstrap import bootstrap_ci                     # noqa: E402
from sentinel.generators import synthetic_identity as gen            # noqa: E402

PREREG = ("prereg/synthetic_identity_generator.md",
          "prereg/synthetic_identity_kill_rule.md")

OUT = ROOT / "data" / "identity_background.json"

# The kill rule, transcribed from the prereg. Changing a number here without
# changing it there is a bug in this file.
ABS_THRESHOLD = {"degree": 0.15, "component_size": 0.15,
                 "attr_multiplicity": 0.12, "rare_multiplicity": 0.12}
LIFT_THRESHOLD = 3.0
RARE_MAX_MULTIPLICITY = 5
MIN_CONFIGS_PASSING = 18
WORLDS = 20


def require_committed_prereg() -> dict:
    """Refuse to run without committed, clean pre-registrations.

    Returns {path: sha}, stored beside the results so the order can be checked
    without taking this function's word for it.
    """
    shas = {}
    for rel in PREREG:
        if not (ROOT / rel).is_file():
            raise SystemExit(
                f"refusing to run: {rel} does not exist. The pre-registration "
                f"is written BEFORE the experiment, not alongside it.")
        log = subprocess.run(["git", "log", "-1", "--format=%H", "--", rel],
                             cwd=ROOT, capture_output=True, text=True)
        sha = log.stdout.strip()
        if log.returncode != 0 or not sha:
            raise SystemExit(
                f"refusing to run: {rel} is not committed. An uncommitted "
                f"prereg can be edited after seeing the result, which is the "
                f"entire thing a pre-registration exists to prevent.")
        dirty = subprocess.run(["git", "status", "--porcelain", "--", rel],
                               cwd=ROOT, capture_output=True, text=True)
        if dirty.stdout.strip():
            raise SystemExit(
                f"refusing to run: {rel} has uncommitted changes. Commit them "
                f"first, so the version that judged this run is the version on "
                f"record.")
        shas[rel] = sha
    return shas


# -- the baselines ----------------------------------------------------------

def baseline_scores(world) -> dict:
    """baseline name -> {app_id: score}, for the four pre-registered baselines."""
    apps = world.applications
    n = len(apps)

    adj = gen.cooccurrence(apps)
    rare_adj = gen.cooccurrence(apps, max_multiplicity=RARE_MAX_MULTIPLICITY)
    comp = gen.components(adj, n)

    value_counts = {}
    for a in gen.ATTRS:
        value_counts[a] = Counter(getattr(app, a) for app in apps)

    degree, attr_mult, rare_mult, comp_size = {}, {}, {}, {}
    for app in apps:
        i = app.app_id
        degree[i] = len(adj.get(i, ()))
        comp_size[i] = comp.get(i, 1)
        total = rare = 0
        for a in gen.ATTRS:
            c = value_counts[a][getattr(app, a)] - 1
            total += c
            if c and (c + 1) <= RARE_MAX_MULTIPLICITY:
                rare += c
        attr_mult[i] = total
        rare_mult[i] = rare

    # rare_multiplicity is also given its degree form; the counting form above
    # is the one the prereg names, and the graph form is kept for the report
    # because they disagree when one rare value is shared by three applications.
    for app in apps:
        rare_mult[app.app_id] = max(rare_mult[app.app_id],
                                    len(rare_adj.get(app.app_id, ())))

    return {"degree": degree, "attr_multiplicity": attr_mult,
            "component_size": comp_size, "rare_multiplicity": rare_mult}


def p_at_k(scores: dict, truth: set, k: int) -> float:
    """EXPECTED precision at k under uniform random tie-breaking.

    Not a detail. Three of the four baselines are small integers -- capped
    outright in `rare_multiplicity`'s case -- so the top ten is routinely a
    thousand-way tie, and any deterministic tie-break measures the tie-break
    rather than the baseline. Breaking on `app_id` scored `rare_multiplicity` at
    exactly 0.0000 on the primary configuration, which is not a fact about the
    background.

    So the tie block is credited its own positive rate rather than a sampled
    draw: exact, deterministic, and free of the sampling noise that repeating
    a random shuffle would add on top of the world-level bootstrap.
    """
    if not k:
        return 0.0
    by_score: dict = {}
    for i, s in scores.items():
        by_score.setdefault(s, []).append(i)

    hits = 0.0
    left = k
    for s in sorted(by_score, reverse=True):
        block = by_score[s]
        pos = sum(1 for i in block if i in truth)
        if len(block) <= left:
            hits += pos
            left -= len(block)
        else:
            hits += pos * (left / len(block))
            left = 0
        if not left:
            break
    return hits / k


# -- one configuration ------------------------------------------------------

def run_config(params: dict, worlds: int = WORLDS) -> dict:
    per_world = {b: [] for b in ABS_THRESHOLD}
    prevalence = []
    background = []
    for seed in range(worlds):
        w = gen.generate(seed=seed, **params)
        truth = w.fraudulent
        prevalence.append(w.prevalence())
        background.append(w.background["per_attribute"])
        scores = baseline_scores(w)
        for b, s in scores.items():
            per_world[b].append({"p10": p_at_k(s, truth, 10),
                                 "p50": p_at_k(s, truth, 50)})

    prev = sum(prevalence) / len(prevalence)
    out = {"params": params, "n_worlds": worlds, "prevalence": prev,
           "baselines": {}, "background": _mean_background(background)}

    passed = True
    for b, rows in per_world.items():
        ci10 = bootstrap_ci(rows, lambda rs: sum(r["p10"] for r in rs) / len(rs))
        ci50 = bootstrap_ci(rows, lambda rs: sum(r["p50"] for r in rs) / len(rs))
        lift = (ci10["point"] / prev) if prev else 0.0
        ok = (ci10["point"] < ABS_THRESHOLD[b]) and (lift < LIFT_THRESHOLD)
        passed &= ok
        out["baselines"][b] = {
            "p10": ci10["point"], "p10_lo": ci10["lo"], "p10_hi": ci10["hi"],
            "p50": ci50["point"], "p50_lo": ci50["lo"], "p50_hi": ci50["hi"],
            "lift_at_10": lift,
            "abs_threshold": ABS_THRESHOLD[b], "lift_threshold": LIFT_THRESHOLD,
            "ci_method": "world_clustered_bootstrap",
            "pass": ok,
        }
    out["pass"] = bool(passed)
    return out


def _mean_background(rows: list) -> dict:
    out = {}
    for a in gen.ATTRS:
        out[a] = {
            "max_multiplicity": sum(r[a]["max_multiplicity"] for r in rows) / len(rows),
            "mean_apps_per_shared_value":
                sum(r[a]["mean_apps_per_shared_value"] for r in rows) / len(rows),
        }
    return out


def describe(result: dict) -> str:
    p = result["params"]
    head = (f"rot={p['rotation_rate']} size={p['cluster_size']} "
            f"ovl={p['overlap']}  prevalence={result['prevalence']:.4f}  "
            f"{'PASS' if result['pass'] else 'TOO_EASY'}")
    lines = [head]
    for b in sorted(result["baselines"]):
        r = result["baselines"][b]
        lines.append(
            f"    {b:<18} p@10 {r['p10']:.4f} "
            f"[{r['p10_lo']:.4f}, {r['p10_hi']:.4f}] world-clustered  "
            f"lift {r['lift_at_10']:.2f}x  "
            f"{'ok' if r['pass'] else 'FAILS KILL RULE'}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", choices=("primary", "sweep"), default="primary")
    ap.add_argument("--worlds", type=int, default=WORLDS)
    args = ap.parse_args()

    shas = require_committed_prereg()
    for rel, sha in shas.items():
        print(f"pre-registration {rel} committed at {sha[:7]}")

    if args.config == "primary":
        grid = [dict(gen.PRIMARY)]
    else:
        grid = [{"rotation_rate": r, "cluster_size": c, "overlap": o}
                for r, c, o in product(gen.ROTATION_RATES, gen.CLUSTER_SIZES,
                                        gen.OVERLAPS)]

    results = []
    for params in grid:
        res = run_config(params, worlds=args.worlds)
        results.append(res)
        print(describe(res))

    primary = next(r for r in results
                   if all(r["params"][k] == v for k, v in gen.PRIMARY.items())) \
        if any(all(r["params"][k] == v for k, v in gen.PRIMARY.items())
               for r in results) else None

    n_pass = sum(1 for r in results if r["pass"])
    verdict = {
        "n_configs": len(results),
        "n_passing": n_pass,
        "min_configs_passing": MIN_CONFIGS_PASSING if args.config == "sweep" else None,
        "primary_pass": (primary or {}).get("pass"),
    }
    if args.config == "sweep":
        verdict["domain_survives"] = bool(primary and primary["pass"]
                                          and n_pass >= MIN_CONFIGS_PASSING)
    else:
        verdict["domain_survives"] = None  # the sweep decides, not this run

    payload = {"prereg": shas, "kill_rule": {
        "abs_threshold": ABS_THRESHOLD, "lift_threshold": LIFT_THRESHOLD,
        "rare_max_multiplicity": RARE_MAX_MULTIPLICITY},
        "verdict": verdict, "results": results}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n{n_pass}/{len(results)} configurations pass the kill rule")
    if args.config == "sweep":
        print(f"domain survives: {verdict['domain_survives']} "
              f"(primary must pass AND >= {MIN_CONFIGS_PASSING} of "
              f"{len(results)})")
    print(f"written to {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
