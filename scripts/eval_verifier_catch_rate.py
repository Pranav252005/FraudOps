"""The guardrail's catch rate, by fault class -- Phase 5 item 3, substituted.

WHAT THIS REPLACES, AND WHY THE SUBSTITUTION IS STATED RATHER THAN QUIET.
docs/NEXT_PHASE_PLAN.md Phase 5 item 3 says to publish the LLM draft rejection
rate from data/draft_ledger.jsonl as a first-class metric. **That file does not
exist on this machine and never has**: OPENROUTER_API_KEY is unset, so the LLM
path has never run, so the ledger has zero observations. Publishing a rejection
rate over zero drafts would be a number with no measurement behind it, which is
the one thing this repository's standing rule 1 exists to forbid.

So the item is done differently, and the difference matters: this measures the
**verifier**, not the model. It injects faults of known class into real
narratives at a known rate and counts what the verifier catches. That is a
property of the guardrail, is deterministic, needs no API key, and is
reproducible by anyone with the compiled stream -- none of which is true of a
rejection rate over live model output.

WHAT IT IS NOT. It is not evidence about how often a model would produce a bad
draft. Nothing here estimates that, and the output says so in its own verdict
field.

THE EXPECTED RESULT IS A FAILURE, AND IT IS PRE-REGISTERED. Two of the three
fault classes are exactly what the verifier implements, so it should catch them
at 1.0. The third -- attribution, where a real id is cited for a claim it does
not support -- is predicted at **0.0**, per prereg/citation_recall.md, and is
demonstrated case by case in tests/test_citation_adversarial.py. A guardrail
whose measured catch rate is 1.0 everywhere would mean the fault injector is
broken, not that the guardrail is perfect.

    python scripts/eval_verifier_catch_rate.py
    python scripts/eval_verifier_catch_rate.py --limit 50

Writes data/eval_verifier_catch_rate.json.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sentinel.data.datasets import active_stream_dir
from sentinel.cases.evidence import build_case_file
from sentinel.cases.store import CaseStore
from sentinel.config import WINDOW_MINUTES
from sentinel.eval.bootstrap import bootstrap_ci
from sentinel.narrative.citation import CITATION, split_sentences, verify
from sentinel.narrative.str_narrative import generate_and_verify

OUT = ROOT / "data" / "eval_verifier_catch_rate.json"
CASES = ROOT / "data" / "cases"
STREAM = active_stream_dir(ROOT)

RUN_ID = "verifier-catch-rate"
SEED = 7

# Fault classes. The first two are what the verifier implements; the third is
# the hole predicted in prereg/citation_recall.md before this file existed.
FABRICATED_ID = "fabricated_id"
STRIPPED_CITATION = "stripped_citation"
ATTRIBUTION = "attribution"
CLASSES = (FABRICATED_ID, STRIPPED_CITATION, ATTRIBUTION)

PREREG_CATCH = {FABRICATED_ID: 1.0, STRIPPED_CITATION: 1.0, ATTRIBUTION: 0.0}

# A sentence worth corrupting has a citation and a number in it. Picking one
# without a number would make the stripped-citation arm trivially uncatchable
# for a reason unrelated to the verifier -- FACT_SIGNAL would not fire, so the
# sentence would be scene-setting and correctly need no citation.
_HAS_NUMBER = re.compile(r"\d")


def _corruptible(narrative: str) -> list[str]:
    return [s for s in split_sentences(narrative)
            if CITATION.search(s) and _HAS_NUMBER.search(s)]


def inject(narrative: str, kind: str, rng: random.Random) -> str | None:
    """Return `narrative` with exactly one fault of class `kind`, or None if
    the narrative has no sentence this class can be applied to."""
    targets = _corruptible(narrative)
    if not targets:
        return None
    s = rng.choice(targets)

    if kind == FABRICATED_ID:
        # Replace the first citation with an id no case file can contain.
        return narrative.replace(s, CITATION.sub("[TXN-99999999]", s, count=1), 1)

    if kind == STRIPPED_CITATION:
        # Remove every citation from the fact-bearing LINE, not just from the
        # sentence fragment.
        #
        # WHY THE LINE. Operating on the fragment measured the injector rather
        # than the verifier, and it did so for 26 of 1,360 cases -- a catch
        # rate of 0.9809 against a pre-registration of 1.0, which read as "the
        # verifier misses 2% of uncited claims" and was not that at all. The
        # filing-clock note cites the same statute TWICE in one line;
        # `split_sentences` cuts it at the comma-free clause boundary, so
        # stripping the chosen fragment left the second citation standing, the
        # line was still correctly sourced, and the verifier was RIGHT not to
        # flag it. A fault that was never injected is not a fault the guardrail
        # missed. Found by reproducing a failing case rather than by trusting
        # the aggregate.
        line = next((ln for ln in narrative.splitlines() if s in ln), None)
        if line is None:
            return None
        stripped = CITATION.sub("", line).replace("  ", " ").rstrip()
        # Post-condition: the fault must actually be present. If the line still
        # carries a citation, nothing was injected and this trial is
        # INAPPLICABLE -- it must not be scored as a miss.
        if CITATION.search(stripped):
            return None
        return narrative.replace(line, stripped, 1)

    if kind == ATTRIBUTION:
        # Keep the citation. Change the claim. Every digit run in the PROSE is
        # multiplied by 1000, so an amount, a count and a date all become false
        # while the cited id stays real and stays attached.
        #
        # DIGITS INSIDE A CITATION ARE OFF LIMITS, and the guard has to be the
        # citation's span rather than a lookbehind. The lookbehind `(?<![\[\w.])`
        # only protected a digit run sitting immediately after `[`. In
        # `[RBI-PA-DIRECTIONS-2025-PARA-13i]` the run `2025` is preceded by a
        # hyphen, so it was rewritten to `2025000` and the citation became an
        # id no case file holds. The verifier then caught it -- as a FABRICATED
        # ID, which is a different fault class and one it does implement.
        #
        # That is how the attribution arm came to read 0.0282 [0.0199, 0.0377]
        # against a pre-registration of exactly 0.0, with an interval excluding
        # zero. The guardrail had not caught a single attribution fault; the
        # injector had been quietly emitting a fault of the wrong class in
        # about 3% of cases. Third defect of this shape in one measurement:
        # each time the injector failed to inject what it claimed, and each
        # time the aggregate looked plausible.
        spans = [m.span() for m in CITATION.finditer(s)]

        def blow_up(m):
            if any(a <= m.start() < b for a, b in spans):
                return m.group(0)         # inside a citation: leave it alone
            return str(int(m.group(0)) * 1000)

        corrupted = re.sub(r"(?<![\[\w.])\d+(?![\w\]])", blow_up, s)
        if corrupted == s:
            return None
        # Post-condition, same principle as the stripped-citation arm: the
        # citations must be untouched, or this is not an attribution fault.
        if CITATION.findall(corrupted) != CITATION.findall(s):
            return None
        return narrative.replace(s, corrupted, 1)

    raise ValueError(kind)


def measure_one(case, stream, rng) -> dict | None:
    cf = build_case_file(case, stream, WINDOW_MINUTES, RUN_ID,
                         purpose="regulatory_reporting")
    if not cf.transactions:
        return None
    narrative, clean = generate_and_verify(cf)
    valid = cf.valid_citation_ids()
    if not clean.ok:                      # cannot happen: generate_and_verify raises
        return None

    row = {"case_id": case.id}
    for kind in CLASSES:
        corrupted = inject(narrative, kind, rng)
        if corrupted is None:
            row[kind] = None              # not applicable to this narrative
            continue
        # 1.0 == the verifier caught the injected fault, 0.0 == it passed.
        row[kind] = 0.0 if verify(corrupted, valid).ok else 1.0
    return row


def _rate(rows, kind):
    vals = [r[kind] for r in rows if r.get(kind) is not None]
    return sum(vals) / len(vals) if vals else 0.0


LEDGER_PATH = ROOT / "data" / "draft_ledger.jsonl"

# Outcomes in which a model actually returned text. An `llm_unavailable` row is
# a call that never happened, not a draft the verifier passed, so counting it
# would flatter any rate computed over this denominator.
_ATTEMPTED = {"llm_filed", "llm_rejected_uncited", "llm_rejected_unverifiable"}


def _drafts_attempted() -> int:
    """Read from the ledger rather than asserted.

    Returns 0 when the ledger does not exist, which is the current state and is
    a MEASUREMENT of it -- the file is written only by the console, and no
    console session has ever requested a drafted narrative. It is deliberately
    derived instead of typed: a hardcoded 0 here would be a number with nothing
    behind it, which is the one thing standing rule 1 forbids, and it would
    keep reading 0 after somebody configured a key.
    """
    if not LEDGER_PATH.exists():
        return 0
    n = 0
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            if json.loads(line).get("outcome") in _ATTEMPTED:
                n += 1
        except json.JSONDecodeError:
            continue
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    if not (STREAM / "edges.parquet").exists():
        print(f"missing {STREAM}/edges.parquet -- run scripts/build_stream.py")
        return 1
    if not (CASES / "cases.jsonl").exists():
        print(f"missing {CASES}/cases.jsonl -- run scripts/build_queue.py")
        return 1

    from sentinel.stream.replay import Stream
    stream = Stream(STREAM)
    cases = list(CaseStore(CASES).load().all())
    n_in_store = len(cases)
    if args.limit:
        cases = cases[:args.limit]

    rng = random.Random(SEED)
    t0 = time.time()
    rows = []
    for i, c in enumerate(cases):
        r = measure_one(c, stream, rng)
        if r is not None:
            rows.append(r)
        if (i + 1) % 200 == 0:
            print(f"  {i + 1}/{len(cases)} cases", flush=True)

    if not rows:
        print("no narrative was corruptible; nothing to report")
        return 1

    ci = {k: bootstrap_ci(rows, lambda rs, k=k: _rate(rs, k)) for k in CLASSES}
    applicable = {k: sum(1 for r in rows if r.get(k) is not None) for k in CLASSES}

    # The injector must be able to produce a fault the verifier catches AND a
    # fault it misses. If every class came back identical the harness would be
    # measuring itself.
    rates = {k: ci[k]["point"] for k in CLASSES}
    injector_discriminates = len(set(round(v, 6) for v in rates.values())) > 1

    payload = {
        "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "seconds": round(time.time() - t0, 1),
        "seed": SEED,
        "n_cases": len(rows),
        # Provenance, for the reason recorded in
        # docs/negative-results/citation-recall-measures-the-template.md: a
        # sibling script wrote a 30-case smoke test that read as a
        # full-population result, because nothing in the artefact said
        # otherwise. Same schema, plausible numbers, wrong by +0.13.
        "n_cases_in_store": n_in_store,
        "limit": args.limit,
        "is_full_population": args.limit is None or args.limit >= n_in_store,
        # Machine-readable, so a template cannot quote the catch rate as a
        # model rejection rate. The prose note below says the same thing, but
        # prose cannot be asserted on.
        "draft_ledger_exists": LEDGER_PATH.exists(),
        "llm_drafts_attempted": _drafts_attempted(),
        "ci_method": "case_clustered_bootstrap",
        "clustering_note": (
            "One case is one trial and appears once. Trials are not nested "
            "within rings or cycles, so rule 5's wider-of-two does not apply."),
        "what_this_is_not": (
            "This measures the VERIFIER against injected faults, not a model. "
            "data/draft_ledger.jsonl does not exist -- OPENROUTER_API_KEY is "
            "unset and the LLM path has never run -- so no rejection rate over "
            "real drafts exists and none is reported here."),
        "prereg_catch_rate": PREREG_CATCH,
        "prereg_source": "prereg/citation_recall.md",
        "n_applicable": applicable,
        "catch_rate": {k: {kk: round(vv, 4) if isinstance(vv, float) else vv
                           for kk, vv in ci[k].items()} for k in CLASSES},
        "injector_discriminates": injector_discriminates,
        "verdict": (
            f"Implemented checks: fabricated id {rates[FABRICATED_ID]:.4f}, "
            f"stripped citation {rates[STRIPPED_CITATION]:.4f}. "
            f"ATTRIBUTION: {rates[ATTRIBUTION]:.4f} -- a real id cited for a "
            f"claim it does not support passes. The guardrail enforces that "
            f"every sentence is SOURCED, not that any sentence is TRUE, and "
            f"the gap between those is this number."
            + ("" if injector_discriminates else
               " WARNING: every class scored identically, so the injector may "
               "be measuring itself rather than the verifier. Do not quote.")),
        "rows": rows,
    }
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"\n{len(rows)} cases in {payload['seconds']}s, seed {SEED}")
    for k in CLASSES:
        c = ci[k]
        print(f"  {k:20s} catch {c['point']:.4f} [{c['lo']:.4f}, {c['hi']:.4f}]"
              f"  applicable to {applicable[k]} cases  prereg {PREREG_CATCH[k]}")
    print(f"\ninjector discriminates between classes: {injector_discriminates}")
    print("\n" + payload["verdict"])
    print(f"\nwrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
