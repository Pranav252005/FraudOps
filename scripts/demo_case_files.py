"""Phase E: the two case files, side by side, out of the same machinery.

Renders an identity case file and narrative, the merchant-facing queue brief,
and -- when the compiled AMLworld stream is present -- an AMLworld case file and
STR narrative, so the two can be read against each other.

    python scripts/demo_case_files.py
    python scripts/demo_case_files.py --out data/case_demo.json

Both narratives are produced by a template path and verified by the SAME
verifier (`sentinel.narrative.citation`), against each domain's own citable
ids: transactions and statutes on one side, applications and shared attribute
values on the other. Verification failure raises in both.

It also measures the one thing about the recommendation worth knowing before
anybody demos it: how often the coded action escalates a candidate that does
NOT cover a planted cluster. A recommendation that escalates everything is a
recommendation that says nothing, and that number belongs beside the demo
rather than in a footnote after it.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sentinel.data.datasets import active_stream_dir
from sentinel.cases.identity_case import build_identity_case_file      # noqa: E402
from sentinel.detect import identity_features as IF                    # noqa: E402
from sentinel.eval import identity as ident                            # noqa: E402
from sentinel.eval.funnel import is_hit                                # noqa: E402
from sentinel.generators import synthetic_identity as gen              # noqa: E402
from sentinel.narrative.identity_brief import (case_narrative_verified,
                                                merchant_brief_verified)  # noqa: E402

OUT = ROOT / "data" / "case_demo.json"
RUN_ID = "phase-e-demo"
GENERATED_AT = "2026-09-01T00:00:00+00:00"     # fixed, so the demo is diffable


def identity_case_files(world, limit: int | None = None):
    _, candidates, _ = ident.run_identity_funnel(world)
    apps = {a.app_id: a for a in world.applications}
    counts = IF.population_counts(world.applications)
    graph, _ = ident.build_graph(world)
    members, _ = ident.cluster_membership(world)

    files, covers = [], []
    for i, c in enumerate(candidates if limit is None else candidates[:limit]):
        nodes = set(c.nodes)
        features = IF.build(nodes, graph, apps, counts)
        files.append(build_identity_case_file(
            case_id=f"IDC-{world.params['seed']:03d}-{i:04d}", nodes=nodes,
            seed=c.seed, apps=apps, population_counts=counts,
            features=features.vector(), run_id=RUN_ID,
            generated_at=GENERATED_AT))
        covers.append(any(is_hit(nodes, m) for m in members.values()))
    return files, covers


def escalation_profile(worlds: int = 5) -> dict:
    """How the coded action falls on candidates that do and do not cover a
    planted cluster.

    Not a detection metric and not reported as one -- the action is a triage
    rule over observable structure, and this says how selective that rule is.
    """
    counts = Counter()
    for seed in range(worlds):
        world = gen.generate(seed=seed, **gen.PRIMARY)
        files, covers = identity_case_files(world)
        for cf, hit in zip(files, covers):
            counts[("covers_cluster" if hit else "no_cluster",
                    cf.recommendation)] += 1
    out: dict = {}
    for (group, action), n in counts.items():
        out.setdefault(group, {})[action] = n
    for group, actions in out.items():
        total = sum(actions.values())
        actions["_total"] = total
    return out


def amlworld_case_file():
    """The AMLworld side, if the compiled stream and a stored queue are here."""
    stream_dir = active_stream_dir(ROOT)
    queue = ROOT / "data" / "queue"
    if not (stream_dir / "edges.parquet").exists() or not queue.exists():
        return None, None
    from sentinel.cases.evidence import build_case_file
    from sentinel.cases.store import CaseStore
    from sentinel.narrative.str_narrative import generate_and_verify
    from sentinel.stream.replay import Stream
    from sentinel import config

    cases = CaseStore(queue).load().all()
    if not cases:
        return None, None
    stream = Stream(stream_dir)
    case = max(cases, key=lambda c: len(c.members))
    cf = build_case_file(case, stream, window_minutes=config.WINDOW_MINUTES,
                          run_id=RUN_ID)
    text, result = generate_and_verify(cf)
    return cf, (text, result)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    world = gen.generate(seed=args.seed, **gen.PRIMARY)
    files, covers = identity_case_files(world)
    biggest = max(files, key=lambda cf: len(cf.applications))
    narrative, verification = case_narrative_verified(biggest)
    brief, brief_verification = merchant_brief_verified(files[:8])

    print("=" * 72)
    print("IDENTITY CASE FILE  (synthetic-identity-v1)")
    print("=" * 72)
    print(narrative)
    print(f"\ncitations verified: {verification['ok']}, "
          f"{len(verification['cited_ids'])} distinct ids")

    print("\n" + "=" * 72)
    print("MERCHANT QUEUE BRIEF")
    print("=" * 72)
    print(brief)
    print(f"\ncitations verified: {brief_verification['ok']}")

    payload = {
        "run_id": RUN_ID,
        "identity": {
            "case_file": biggest.to_dict(),
            "narrative": narrative,
            "verification": verification,
            "merchant_brief": brief,
            "merchant_brief_verification": brief_verification,
            "escalation_profile": escalation_profile(),
        },
    }

    aml_cf, aml_narrative = amlworld_case_file()
    if aml_cf is not None:
        text, result = aml_narrative
        print("\n" + "=" * 72)
        print("AMLWORLD CASE FILE  (amlworld-hi-small)")
        print("=" * 72)
        print(text[:2000])
        print(f"\ncitations verified: {result.ok}, "
              f"{len(result.cited_ids)} distinct ids")
        payload["amlworld"] = {"case_file": aml_cf.to_dict(),
                                "narrative": text,
                                "verification": result.to_dict()}
    else:
        print("\n(amlworld side skipped: no compiled stream or stored queue)")
        payload["amlworld"] = None

    print("\n" + "=" * 72)
    print("ESCALATION PROFILE  (how selective the coded action is)")
    print("=" * 72)
    for group, actions in sorted(payload["identity"]["escalation_profile"].items()):
        total = actions["_total"]
        parts = ", ".join(f"{a} {n}" for a, n in sorted(actions.items())
                          if a != "_total")
        print(f"  {group:<16} n={total:<4} {parts}")

    # Resolved before use: `--out data/case_demo.json` is the form the README
    # documents, and a relative path has no `relative_to(ROOT)` -- which used
    # to crash AFTER every case file had already been rendered and printed, so
    # the script did all its work and then exited non-zero.
    out = Path(args.out)
    out = out if out.is_absolute() else (Path.cwd() / out)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        shown = out.resolve().relative_to(ROOT)
    except ValueError:
        shown = out.resolve()
    print(f"\nwritten to {shown}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
