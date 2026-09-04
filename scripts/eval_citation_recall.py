"""Citation precision and recall on the STR narrative -- Phase 5 item 2.

PRE-REGISTERED at prereg/citation_recall.md, committed before this file
existed. Read that first; the definitions and the kill criterion are fixed
there and are not restated here in a form that could drift from them.

WHY PRECISION IS NOT A RESULT. The verifier hard-fails any narrative containing
a citation to an id the case file does not hold, so precision over any narrative
that was returned at all is 1.0 BY CONSTRUCTION. It is computed here so the
number exists and is labelled tautological. It is evidence that the verifier
ran, and evidence of nothing else.

Recall is the quantity that is not guaranteed and has never been measured:
of the case file's own material evidence -- its transactions and its member
accounts -- how much does the narrative actually cite?

    python scripts/eval_citation_recall.py
    python scripts/eval_citation_recall.py --limit 50     # smoke test

Writes data/eval_citation_recall.json.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sentinel.data.datasets import active_stream_dir
from sentinel.cases.evidence import REGULATORY_CITATIONS, build_case_file
from sentinel.cases.store import CaseStore
from sentinel.config import WINDOW_MINUTES
from sentinel.eval.bootstrap import bootstrap_ci
from sentinel.narrative.citation import NarrativeVerificationError, verify
from sentinel.narrative.str_narrative import generate_and_verify

OUT = ROOT / "data" / "eval_citation_recall.json"
CASES = ROOT / "data" / "cases"
STREAM = active_stream_dir(ROOT)

RUN_ID = "citation-recall"

# From the pre-registration, so a later reader can see whether the prediction
# was met without opening a second file. NOT used to decide anything at
# runtime -- a script that branches on its own prereg is a script that can be
# made to agree with it.
PREREG = {
    "evidence_recall": [0.40, 0.80],
    "txn_recall": [0.15, 0.60],
    "member_recall": [0.60, 1.00],
    "precision": "exactly 1.0, by construction",
    "kill_criterion": (
        "evidence_recall >= 0.95 means the measure is degenerate on the "
        "template path -- it is measuring verbosity, not sourcing -- and must "
        "be reported as such rather than published as a good number."),
    "source": "prereg/citation_recall.md",
}


def measure_one(case, stream) -> dict | None:
    """Citation precision and recall for one case, or None if it has no
    citable evidence at all (a case file with no transactions cannot be
    under-sourced, and scoring it 0.0 would fold an evidence-assembly gap
    into a narrative measurement)."""
    cf = build_case_file(case, stream, WINDOW_MINUTES, RUN_ID,
                         purpose="regulatory_reporting")

    case_txns = {t.txn_id for t in cf.transactions}
    case_members = {m.account for m in cf.members}
    material = case_txns | case_members
    if not material:
        return None

    try:
        narrative, result = generate_and_verify(cf)
    except NarrativeVerificationError as exc:
        # The template path raises on failure by contract. If this fires the
        # finding is the failure, not the recall -- so it is recorded rather
        # than skipped.
        return {"case_id": case.id, "verification_failed": True,
                "failures": exc.result.failures[:5]}

    cited = set(result.cited_ids)
    valid = cf.valid_citation_ids()

    # Precision over the ids actually cited. Tautologically 1.0 -- see the
    # module docstring -- and computed anyway so the tautology is visible.
    precision = len(cited & valid) / len(cited) if cited else 1.0

    return {
        "case_id": case.id,
        "verification_failed": False,
        "n_txns": len(case_txns),
        "n_members": len(case_members),
        "n_cited": len(cited),
        # Statutes are excluded from every recall denominator: they are a
        # fixed closed set identical across cases, so counting them would add
        # a constant unrelated to how well this narrative sources this case.
        "n_cited_regulatory": len(cited & set(REGULATORY_CITATIONS)),
        "precision": precision,
        "txn_recall": len(cited & case_txns) / len(case_txns) if case_txns else None,
        "member_recall": (len(cited & case_members) / len(case_members)
                          if case_members else None),
        "evidence_recall": len(cited & material) / len(material),
        "narrative_chars": len(narrative),
    }


def _mean(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return sum(vals) / len(vals) if vals else 0.0


# The template's enumeration caps, read off sentinel/narrative/str_narrative.py
# rather than guessed: `_what` cites the first 5 transactions in its header and
# then one sentence each for the first 20, and `_who` cites up to 3 evidence
# transactions per member. So a case with few transactions is cited almost
# exhaustively and a case with many is not.
TEMPLATE_TXN_CAP = 20

SIZE_BANDS = ((0, 20), (21, 50), (51, 150), (151, 10 ** 9))


def stratify(rows) -> list[dict]:
    """Recall by case size -- the diagnostic that separates SOURCING from
    VERBOSITY, and the reason the headline alone cannot be trusted.

    If recall is a property of how well the narrative sources its case, it
    should be roughly flat in case size. If it is an artefact of the template
    enumerating a fixed prefix, it must FALL as the case grows, because the
    numerator is capped and the denominator is not. The two hypotheses make
    opposite predictions and this table separates them.
    """
    out = []
    for lo, hi in SIZE_BANDS:
        band = [r for r in rows if lo <= r["n_txns"] <= hi]
        if not band:
            continue
        out.append({
            "band": f"{lo}-{hi}" if hi < 10 ** 9 else f"{lo}+",
            "n_cases": len(band),
            "median_n_txns": sorted(r["n_txns"] for r in band)[len(band) // 2],
            "evidence_recall": round(_mean(band, "evidence_recall"), 4),
            "txn_recall": round(_mean(band, "txn_recall"), 4),
            "member_recall": round(_mean(band, "member_recall"), 4),
        })
    return out


def aggregate(ok, skipped, failed, seconds, n_in_store, limit) -> dict:
    # One case is one trial and each case appears once, so the case IS the
    # cluster. Rule 5's "report the wider of two clusterings" does not apply:
    # these trials are not nested within rings or cycles, so there is no
    # second clustering that is even defined. Recorded rather than implied.
    ci = {k: bootstrap_ci(ok, lambda rs, k=k: _mean(rs, k))
          for k in ("evidence_recall", "txn_recall", "member_recall", "precision")}
    bands = stratify(ok)

    headline = ci["evidence_recall"]["point"]
    # The literal pre-registered rule.
    degenerate_headline = headline >= 0.95
    # The rule the pre-registration SHOULD have carried: a component pinned at
    # 1.0 with a zero-width interval is degenerate on its own terms whatever
    # the headline does, because a quantity that cannot vary cannot measure.
    degenerate_member = (ci["member_recall"]["point"] >= 0.9999
                         and ci["member_recall"]["hi"] - ci["member_recall"]["lo"] < 1e-9)
    # The decisive diagnostic: does recall fall with case size?
    slope_note = None
    if len(bands) >= 2:
        first, last = bands[0]["txn_recall"], bands[-1]["txn_recall"]
        slope_note = round(last - first, 4)

    return {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": round(seconds, 1),
        # PROVENANCE, and it is here because its absence already produced a
        # wrong answer. The first run of this script used --limit 30 against a
        # 1,360-case store and wrote a file that read as a full-population
        # result: same schema, same fields, plausible numbers, and nothing in
        # the artefact recording that 1,330 cases were never looked at. That
        # is this project's characteristic defect exactly -- a computation that
        # completes, returns the right type in the right range, and is wrong --
        # and it was written during Phase 5, by the work packaging the bug
        # catalogue. A partial run is now labelled in the file, not in a memory.
        "n_cases_in_store": n_in_store,
        "limit": limit,
        "is_full_population": limit is None or limit >= n_in_store,
        "population_note": (
            "SMOKE TEST -- scored the first %d of %d cases in store insertion "
            "order, which is generation order, so this is the earliest cycles "
            "and not a random sample. Not quotable as a population figure."
            % (limit, n_in_store)) if (limit is not None
                                       and limit < n_in_store) else
            "Full population: every case in the store was scored.",
        "n_cases_scored": len(ok),
        "n_cases_skipped_no_evidence": skipped,
        "n_verification_failures": len(failed),
        "verification_failures": failed[:10],
        "ci_method": "case_clustered_bootstrap",
        "clustering_note": (
            "One case is one trial and appears once, so the case is the "
            "resampling unit. Rule 5's wider-of-two does not apply: these "
            "trials are not nested within rings or cycles, so no second "
            "clustering is defined."),
        "precision_is_tautological": (
            "The verifier hard-fails any narrative citing an id the case file "
            "does not hold, so precision over a returned narrative is 1.0 by "
            "construction. It is evidence the verifier ran, not evidence of "
            "narrative quality, and must never be quoted as the latter."),
        "prereg": PREREG,
        "metrics": {k: {kk: round(vv, 4) if isinstance(vv, float) else vv
                        for kk, vv in v.items()} for k, v in ci.items()},
        "by_case_size": bands,
        "template_txn_cap": TEMPLATE_TXN_CAP,
        "txn_recall_delta_largest_minus_smallest_band": slope_note,
        "medians": {
            "n_txns": sorted(r["n_txns"] for r in ok)[len(ok) // 2],
            "n_members": sorted(r["n_members"] for r in ok)[len(ok) // 2],
            "n_cited": sorted(r["n_cited"] for r in ok)[len(ok) // 2],
        },
        "kill_criterion_fired": degenerate_headline,
        "member_recall_is_degenerate": degenerate_member,
        "verdict": _verdict(degenerate_headline, degenerate_member, slope_note),
        "rows": ok,
    }


def _verdict(degenerate_headline, degenerate_member, slope) -> str:
    parts = []
    if degenerate_headline:
        parts.append(
            "HEADLINE DEGENERATE: evidence_recall >= 0.95, so this measures "
            "how many facts the template emits rather than how well it "
            "sources them. The pre-registered kill criterion fired as "
            "written.")
    if degenerate_member:
        parts.append(
            "member_recall IS DEGENERATE: pinned at 1.0 with a zero-width "
            "interval across every case. The template emits one sentence per "
            "member, so this component cannot vary and therefore cannot "
            "measure anything. It must not be quoted as a result, and the "
            "headline is inflated by it.")
    if slope is not None and slope <= -0.15:
        parts.append(
            f"TEMPLATE-CAP ARTEFACT CONFIRMED: txn_recall falls by {slope:+.4f} "
            "from the smallest case band to the largest. Recall tracks the "
            "template's fixed enumeration prefix, not sourcing quality -- a "
            "genuine sourcing property would be roughly flat in case size.")
    elif slope is not None:
        parts.append(
            f"txn_recall changes by {slope:+.4f} across case-size bands, which "
            "is not the steep fall a fixed enumeration cap would produce.")
    return " ".join(parts) if parts else (
        "Informative: the template does not cite everything, so recall "
        "measures sourcing rather than verbosity.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="measure only the first N cases (smoke test)")
    ap.add_argument("--from-json", action="store_true",
                    help="recompute the aggregates from the per-case rows "
                         "already in the output file, without re-measuring. "
                         "The rows are the measurement; everything else is "
                         "arithmetic over them.")
    args = ap.parse_args()

    if args.from_json:
        if not OUT.exists():
            print(f"missing {OUT.relative_to(ROOT)}; run without --from-json first")
            return 1
        prev = json.loads(OUT.read_text(encoding="utf-8"))
        payload = aggregate(prev["rows"], prev["n_cases_skipped_no_evidence"],
                            prev.get("verification_failures", []),
                            prev["seconds"],
                            # Provenance is carried forward, never re-derived.
                            # Recomputing aggregates must not be able to launder
                            # a partial run into a full-population one.
                            prev.get("n_cases_in_store", len(prev["rows"])),
                            prev.get("limit"))
        payload["recomputed_from_rows_at"] = payload["measured_at"]
        payload["measured_at"] = prev["measured_at"]
        OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        _report(payload)
        return 0

    if not (STREAM / "edges.parquet").exists():
        print(f"missing {STREAM}/edges.parquet -- run scripts/build_stream.py")
        return 1
    if not (CASES / "cases.jsonl").exists():
        print(f"missing {CASES}/cases.jsonl -- run scripts/build_queue.py")
        return 1

    from sentinel.stream.replay import Stream
    stream = Stream(STREAM)
    store = CaseStore(CASES).load()
    cases = list(store.all())
    n_in_store = len(cases)
    if args.limit:
        cases = cases[:args.limit]

    t0 = time.time()
    rows, skipped = [], 0
    for i, c in enumerate(cases):
        r = measure_one(c, stream)
        if r is None:
            skipped += 1
            continue
        rows.append(r)
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(cases)} cases", flush=True)

    failed = [r for r in rows if r["verification_failed"]]
    ok = [r for r in rows if not r["verification_failed"]]
    if not ok:
        print("no case produced a verified narrative; nothing to report")
        return 1

    payload = aggregate(ok, skipped, failed, time.time() - t0,
                        n_in_store, args.limit)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _report(payload)
    return 0


def _report(payload) -> None:
    if not payload["is_full_population"]:
        print("")
        print("*** SMOKE TEST: %s of %s cases scored, in generation order. "
              "NOT a population figure -- re-run without --limit before "
              "quoting anything from this. ***"
              % (payload["limit"], payload["n_cases_in_store"]))
    print(f"\nscored {payload['n_cases_scored']} cases in {payload['seconds']}s "
          f"({payload['n_cases_skipped_no_evidence']} skipped, "
          f"{payload['n_verification_failures']} verification failures)")
    for k in ("evidence_recall", "txn_recall", "member_recall", "precision"):
        c = payload["metrics"][k]
        pre = PREREG.get(k)
        band = f"  prereg {pre}" if isinstance(pre, list) else "  (tautological)"
        print(f"  {k:18s} {c['point']:.4f} [{c['lo']:.4f}, {c['hi']:.4f}]"
              f"  n={c['n_units']} cases{band}")

    print("\n  recall by case size -- flat means sourcing, falling means the "
          "template's enumeration cap:")
    print(f"  {'band':>10s} {'cases':>6s} {'med txns':>9s} "
          f"{'txn_rec':>8s} {'mem_rec':>8s} {'evid_rec':>9s}")
    for b in payload["by_case_size"]:
        print(f"  {b['band']:>10s} {b['n_cases']:>6d} {b['median_n_txns']:>9d} "
              f"{b['txn_recall']:>8.4f} {b['member_recall']:>8.4f} "
              f"{b['evidence_recall']:>9.4f}")

    m = payload["medians"]
    print(f"\n  median case: {m['n_txns']} txns, {m['n_members']} members, "
          f"{m['n_cited']} distinct citations")
    print(f"\nKILL CRITERION (headline >= 0.95) "
          f"{'FIRED' if payload['kill_criterion_fired'] else 'did not fire'}")
    print(f"member_recall degenerate: {payload['member_recall_is_degenerate']}")
    print("\n" + payload["verdict"])
    print(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    raise SystemExit(main())
