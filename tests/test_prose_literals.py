"""Rule 1 for prose: a ratchet now, an assertion after Phase 4.

The goal state is that no metric-shaped literal appears in README or docs/
except ones explicitly marked as historical narration. That is Phase 4 work --
README becomes a template rendered from a metrics file -- and it is not done.

So this file ships two tests that do different jobs:

  * `test_no_unmarked_metric_literals_in_prose` is the GOAL. It is marked
    xfail, so it does not block the build, and `strict=True`, so it will fail
    the build the day it starts passing and nobody has removed the marker.
  * `test_the_unmarked_literal_count_never_increases` is the RATCHET, and it
    passes today. It is the part that does real work in the meantime: the
    count may fall, never rise.

A baseline recorded and enforced is worth more than a goal asserted and
skipped. The count is the honest measure of how far rule 1 is from being a
property rather than a practice.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.report.literals import (MARKER, count_unmarked, prose_files,
                                      scan)

# The ledger. Every entry is a deliberate change to the allowed count, with the
# reason it moved. Measured by `sentinel.report.literals.count_unmarked`.
#
# The ratchet's job is to make an increase VISIBLE AND JUSTIFIED, not
# impossible. Writing up a new measurement legitimately adds literals -- those
# numbers exist and were measured today. What the ratchet stops is literals
# accumulating without anyone noticing, and numbers surviving in prose after the
# measurement behind them has moved. A raise that cannot state its cause in one
# line is the case this is designed to catch.
#
# Append, never edit in place.
LEDGER = [
    ("2026-08-31", "63066d1", 1636,
     "baseline at first measurement"),
    ("2026-09-01", "phase-2a", 1730,
     "+94: docs/PHASE2-SEED-CHEAT-FINDINGS.md (68) and "
     "docs/negative-results/builder-budget-refuted.md (26), both written up "
     "from measurements taken the same day. Not marked historical, because "
     "they are current: the marker asserts a number narrates a PAST state, "
     "and using it to silence the scanner on live numbers would be a lie that "
     "the scanner itself cannot detect."),
    ("2026-09-01", "phase-3", 1835,
     "+105: docs/PHASE3-LABEL-TAX-FINDINGS.md and two negative-results "
     "entries (analyst-pool-mismatch, label-noise-non-monotone), all from the "
     "label-tax arms run the same day against pre-registrations committed at "
     "a4eee6e. Same reasoning as the previous entry -- these are current "
     "measurements, so the historical marker does not apply to them."),
    ("2026-09-01", "phase-4", 1700,
     "-135, the first fall. README became a template rendered from "
     "results/metrics.json, so its own count went 313 -> 196: headline "
     "literals became placeholders, superseded ones got historical markers "
     "with a commit and a date, and README.md is no longer scanned at all "
     "because it is now a build artefact whose numbers cannot be wrong by "
     "hand. Also excludes the fixed phrase '95% CI', where the number names "
     "the confidence level rather than measuring anything."),
    ("2026-09-01", "phase-5", 1708,
     "+8: docs/SUBMISSION.template.md, the buildathon write-up. It is itself "
     "rendered from results/metrics.json, so its 8 remaining literals are "
     "narration of past states rather than live values."),
    ("2026-09-01", "phase-A-identity", 1718,
     "+10: docs/PHASEA-IDENTITY-BACKGROUND.md, the synthetic-identity "
     "background gate written up from the sweep run the same day against "
     "pre-registrations committed at 49f9f08. Current measurements, so the "
     "historical marker does not apply; the per-configuration numbers stay in "
     "data/identity_background.json rather than being copied into prose, "
     "which is why this is ten literals and not a hundred."),
    ("2026-09-01", "phase-C-identity", 1722,
     "+4: docs/PHASEC-IDENTITY-FEATURES.md, the identity feature gate. The "
     "attribute-ceiling table is the exclusion's evidence and its six numbers "
     "are the argument, not decoration; the per-feature AUC table stays in "
     "data/identity_features.json rather than in prose. Current measurements, "
     "so the historical marker does not apply."),
    ("2026-09-01", "phase-D-fragmentation", 1779,
     "+57: docs/PHASED-FRAGMENTATION.md and "
     "docs/negative-results/identity-fragments-worse-refuted.md, both from the "
     "coverage measurement run the same day against a pre-registration "
     "committed at 8453492. The dose-response tables ARE the result -- six "
     "coverage points with intervals, twelve sweep points, and the two-domain "
     "contrast -- so these literals are the argument rather than narration. "
     "Current measurements, so the historical marker does not apply."),
    ("2026-09-01", "phase-E-case-files", 1780,
     "+1: docs/PHASEE-CASE-FILES.md. The escalation profile is counted in "
     "whole candidates rather than rates, and the one metric-shaped literal is "
     "rare_multiplicity's 0.0000 from Phase A -- quoted because the point of "
     "the paragraph is that the triage rule inherits that exact result."),
    ("2026-09-01", "readme-pivot-section", 1784,
     "+4: README.template.md gains a reviewer-facing section explaining why a "
     "second domain was added. Its four literals are quotations of numbers "
     "measured elsewhere in the repo -- the 0.510/0.057 component-split shares "
     "from PHASE2-SEED-CHEAT-FINDINGS, the 91% laundering share behind "
     "EVAL_END in config.py, and max_pan_fanout's AUC from "
     "data/identity_features.json -- each quoted because it is the evidence "
     "for the sentence around it. Placeholders are used everywhere a metric "
     "id exists."),
    ("2026-09-01", "template-literal-leak", 1776,
     "-8 net, and the composition matters more than the number. OUT: six "
     "unmarked `0.278` and three `2.25x` in README.template.md, all stale "
     "readings of supervised_p_at_10 or ratios built from one -- bound to "
     "placeholders, and the leak recorded in "
     "docs/negative-results/template-literal-leak.md. IN: the case-file "
     "excerpt on the first screen, whose temporal_cycle_coverage=0.043 is the "
     "case's own feature value and is the point of the WHY line -- an analyst "
     "who cannot see what caused the classification can only disagree with "
     "the score. Baseline lowered from 1784 so the ratchet keeps biting."),
    ("2026-09-03", "next-phase-plan", 1868,
     "+92, all in docs/NEXT_PHASE_PLAN.md, a planning document that must be "
     "handed verbatim to a fresh session and therefore has to restate the "
     "measured state rather than link to it -- a plan whose reader has to "
     "open four other files to learn what it is planning from is a plan that "
     "gets acted on from memory. Every literal in it is quoted from "
     "results/metrics.json, data/funnel.json or a named negative-results "
     "entry, and the document says in its own first paragraph that "
     "results/metrics.json is the authority for any number appearing in "
     "prose. The pre-registered ranges in its phase table are predictions, "
     "not measurements, and are labelled as such where they appear."),
    ("2026-09-03", "phase-0-reconcile", 1878,
     "+10, from the four in-place annotations that close the stale claims "
     "NEXT_PHASE_PLAN section 0 tabled: HANDOFF-NEXT item 2 and "
     "CENTREPIECE-INVALIDATED both called the seed-cheat diff 'cheap to "
     "settle, a read of data that exists' and both were wrong twice over, "
     "HANDOFF 5f framed the remaining task as a BIPARTITE/STACK build "
     "problem, and README open problem 3 said the same. Each annotation "
     "quotes the 0.510-against-0.057 component-split shares because that "
     "contrast IS the correction -- a superseding note that does not carry "
     "the number it supersedes on cannot be checked. Stale-narrative count "
     "held at 50 and templates stayed at zero across the change."),
    ("2026-09-03", "what-broke", 1895,
     "+17, from docs/WHAT-BROKE.template.md, the Failure Recovery artefact. "
     "Every LIVE number in it is a placeholder -- the file contains no typed "
     "p@k, no typed interval and no typed ratio, and the render fails rather "
     "than leaving a hole. The 17 counted literals are all values that are "
     "not metrics and cannot go stale: the magnitudes in the catastrophic "
     "cancellation case (0.09 against 6,948,663.08), the benchmark leak rates "
     "(7.3x, 86.6%, 11.8%, 91%), the disk sizes on the Elliptic2 download, "
     "and counts like 156 of 321 positives. Stale-value count in the new "
     "template is ZERO, which is the assertion rather than the ratchet, and "
     "the stale-narrative total held at 50."),
    ("2026-09-03", "phase-5-narrative", 1896,
     "+1 net, from three offsetting changes. ADDED: '1.5x' in "
     "docs/PITCH.template.md, the PRE-REGISTERED kill threshold the "
     "supervised-oracle arm was tested against -- a decision rule fixed "
     "before the measurement, not a measurement, so it cannot go stale the "
     "way a p@k can. REMOVED: the typed '1.8382' in the live sentence of "
     "docs/WHAT-BROKE.template.md, which is now a placeholder rendered from "
     "results/metrics.json. RE-ADDED: the same figure inside the blockquote "
     "recording that the sentence used to omit its stress factor. That one is "
     "deliberately NOT given a historical marker -- the marker asserts a "
     "number narrates a PAST state, and 1.8382 is the CURRENT x10 break-even; "
     "what was wrong was the missing factor, not the value, and marking a "
     "live number historical to quiet the scanner would be the lie the "
     "scanner cannot detect. Every actual metric in PITCH is a placeholder, "
     "so the pitch cannot be read aloud with a stale number in it."),
    ("2026-09-03", "phase-5-citation-negative", 1909,
     "+13, from docs/negative-results/citation-recall-measures-the-template.md. "
     "All thirteen are measurements taken the same day over all 1,360 cases "
     "against a pre-registration committed at 4cdbb22: the four recall "
     "figures with their intervals, the four-band size stratification that is "
     "the actual finding, the -0.5218 slope, and the 0.8797 the 30-case smoke "
     "test reported before the population run replaced it with 0.7494. Not "
     "marked historical, for the reason the 2026-09-01 entries give: the "
     "marker asserts a number narrates a PAST state, and these are current. "
     "The one figure that IS historical -- the superseded smoke-test value -- "
     "is quoted inside a sentence that says it was superseded and by how "
     "much, which is the form a superseding note has to take to be checkable."),
    ("2026-09-03", "phase-5-verifier-catch-rate", 1917,
     "+8, from the fault-injector entry in docs/WHAT-BROKE.template.md. The "
     "eight are the two SUPERSEDED catch rates with their intervals (0.9809 "
     "[0.9735, 0.9875] for stripped_citation, 0.0282 [0.0199, 0.0377] for "
     "attribution) and the corrected 0.0000. They are quoted because a "
     "correction that does not state the number it supersedes cannot be "
     "checked -- the whole point of the entry is that BOTH intervals excluded "
     "their pre-registered value, which is what exposed the injector. Not "
     "given historical markers: the marker must sit on the immediately "
     "preceding non-blank line and these live inside a table row, where that "
     "anchor would attach to a different row and drift. The live catch rates "
     "are placeholders rendered from results/metrics.json."),
    ("2026-09-04", "graph-review", 1927,
     "+10: docs/graph-review/2026-09-04.md (8) and docs/EXPERIMENT-QUEUE.md "
     "(2). The eight are values the review quotes back from measurements that "
     "are still current -- the two rule-5 interval widths, the H2 "
     "fragmentation shares, the size-baseline seeding ratio, the "
     "all-positive-group cost, and BlazingAML's published speedup, which is "
     "someone else's number and cannot go stale here. Quoted rather than "
     "referenced because a review that says 'see the other document' for "
     "every figure cannot be checked against the code it reviews. Not marked "
     "historical: the marker asserts a number narrates a PAST state, and "
     "these narrate the present."),
    ("2026-09-04", "M1-threshold-band", 2025,
     "+98: docs/THRESHOLD-BAND.md (86) and the M1 entry in "
     "docs/EXPERIMENT-LEDGER.md (12). The ledger entry is append-only by "
     "construction and quotes the run's own headline figures, which is what "
     "makes it auditable against data/eval_threshold_band.json; a ledger that "
     "said 'see the other file' for every number could not be checked. "
     "The document is the pre-registered is_hit sensitivity "
     "grid. Nearly all of it is one results table -- nine cells x score "
     "p@10, size p@10, the paired delta, its interval, p@20 and ring recall "
     "-- plus the six-row table scoring the run against its own "
     "pre-registration. These are the measurement, not prose about it. "
     "Rendering seventy-odd grid cells through results/metrics.json would "
     "mean seventy-odd metric ids for a table read once, which trades a "
     "ratchet increase for a worse artifact; the same judgement was made for "
     "every earlier findings document (phase-2a +94, phase-3 +105). The "
     "authoritative copy is data/eval_threshold_band.json and the document "
     "names it."),
    ("2026-09-04", "S1-S2-seed-predicate", 2083,
     "+58: docs/SEED-PREDICATE-FINDINGS.md and the S1/S2 ledger entry. Same "
     "judgement as the M1 entry above: the bulk is the arms table (four arms "
     "x seeds, extra, seeded, built, ranked, three p@k), the per-typology "
     "built table, and the mechanism figures that make the refutation "
     "checkable -- 98.6% cleanliness saturation, 83 saturated accounts "
     "against a 1,585 budget. A refutation whose numbers live only in an "
     "untracked JSON cannot be audited, and the authoritative copy is named "
     "in the document."),
]

BASELINE_UNMARKED = LEDGER[-1][2]


def test_the_unmarked_literal_count_never_increases():
    total, per_file = count_unmarked(ROOT)
    assert total <= BASELINE_UNMARKED, (
        f"unmarked metric literals rose from {BASELINE_UNMARKED} to {total}. "
        f"Every one is a number that can go stale independently of the "
        f"measurement it came from -- which has already happened twice to "
        f"0.2778 (see docs/STANDING-RULES.md rule 1). Per file: "
        f"{dict(sorted(per_file.items(), key=lambda kv: -kv[1])[:5])}")


def test_the_ledger_is_append_only_and_every_entry_gives_a_reason():
    """The ledger is the audit trail; without these it is just a number.

    Each entry must carry a date, a commit or tag, a count, and a reason long
    enough to be a sentence. A raise that cannot say why in one line is exactly
    what the ratchet exists to surface.
    """
    assert LEDGER, "the ledger may not be emptied"
    for date, ref, count, reason in LEDGER:
        assert len(date) == 10 and date[4] == "-", date
        assert ref, date
        assert isinstance(count, int) and count >= 0, date
        assert len(reason) > 20, f"{date}: reason too thin to audit: {reason!r}"
    dates = [e[0] for e in LEDGER]
    assert dates == sorted(dates), "ledger entries must be in date order"


def test_the_baseline_is_not_stale_by_a_wide_margin():
    """Keeps the ratchet tight.

    A baseline left far above the actual count stops being a ratchet -- it
    permits a large regression before firing. If the real count has dropped
    well below the recorded baseline, the baseline should be lowered in the
    same commit that dropped it.
    """
    total, _ = count_unmarked(ROOT)
    assert total >= BASELINE_UNMARKED - 50, (
        f"count is {total}, baseline is {BASELINE_UNMARKED}: lower "
        f"BASELINE_UNMARKED to {total} so the ratchet keeps biting.")


@pytest.mark.xfail(strict=True, reason=(
    "Phase 4 has not run: README is not yet a template rendered from "
    "results/metrics.json, so 1,636 literals remain unmarked. Strict, so this "
    "fails the build when it starts passing and the xfail is left behind."))
def test_no_unmarked_metric_literals_in_prose():
    total, per_file = count_unmarked(ROOT)
    assert total == 0, per_file


def test_the_scanner_finds_the_literals_it_is_supposed_to():
    """The negative control: a scanner that matched nothing would pass the
    ratchet forever.

    It watches README.template.md, not README.md. Since Phase 4 the latter is
    a build artefact rendered from the former, so its numbers are correct by
    construction and cannot be fixed by editing -- an edit is overwritten on
    the next render. The template is where a human can introduce a stale
    number, so the template is what is scanned.
    """
    total, per_file = count_unmarked(ROOT)
    assert total > 0
    assert "README.template.md" in per_file
    assert "README.md" not in per_file, (
        "README.md is generated; scanning it would double-count every literal "
        "and would flag rendered values nobody can edit")


def test_the_historical_marker_actually_exempts(tmp_path):
    """The exemption must work, or Phase 4 has no way to keep true history."""
    doc = tmp_path / "d.md"
    doc.write_text(
        "<!-- historical: measured at commit 0b4debd, 2026-08-31 -->\n"
        "The pointwise model reached 0.2500 before the split fix.\n",
        encoding="utf-8")
    assert all(exempt for _, _, exempt in scan(doc))

    doc.write_text("The pointwise model reaches 0.2500.\n", encoding="utf-8")
    assert not any(exempt for _, _, exempt in scan(doc))


@pytest.mark.parametrize("marker", [
    "<!-- historical -->",
    "<!-- historical: 2026-08-31 -->",
    "<!-- historical: measured at commit 0b4debd -->",
    "<!-- historical: measured at commit zzzzzzz, 2026-08-31 -->",
])
def test_a_marker_without_a_commit_and_a_date_does_not_exempt(tmp_path, marker):
    """Phase 4.3 requires both. A marker that carries neither is a way to
    silence the scanner without recording anything."""
    doc = tmp_path / "d.md"
    doc.write_text(f"{marker}\nIt reached 0.2500.\n", encoding="utf-8")
    assert not any(exempt for _, _, exempt in scan(doc))


def test_unknown_is_an_acceptable_commit():
    """An auditable admission beats an invented sha.

    The inventory found literals whose producing commit cannot be established
    from history. Forcing a sha there would mean inventing one.
    """
    assert MARKER.search(
        "<!-- historical: measured at commit unknown, 2026-08-31 -->")


def test_the_inventory_csv_is_not_scanned():
    """It is the output of counting literals; counting it would be circular."""
    assert not any("inventory" in p.parts for p in prose_files(ROOT))


def test_the_reported_literal_count_is_not_stale():
    """`results/metrics.json` reports the repository's own literal count, and
    `docs/SUBMISSION.md` renders it. A self-reported count that can drift is
    the exact defect this whole mechanism exists to catch, so it is checked.

    This does couple documentation edits to `scripts/collect_metrics.py`. That
    coupling is the point: if a doc changes and the reported count is not
    refreshed, the submission is quoting a stale number about staleness.
    """
    import json

    metrics = ROOT / "results" / "metrics.json"
    if not metrics.exists():
        pytest.skip("results/metrics.json not built")
    stored = json.loads(metrics.read_text(encoding="utf-8"))["counts"].get(
        "n_prose_literals")
    if stored is None:
        pytest.skip("n_prose_literals not recorded")
    live, _ = count_unmarked(ROOT)
    assert stored == live, (
        f"results/metrics.json reports {stored} prose literals; the live count "
        f"is {live}. Re-run `python scripts/collect_metrics.py && python "
        f"scripts/render_docs.py`.")


def test_generated_documents_are_not_scanned():
    """A rendered file's numbers are correct by construction and cannot be
    fixed by editing, since an edit is overwritten on the next render. Scanning
    them would double-count and would flag values nobody can act on."""
    # Compared as paths, not basenames: docs/negative-results/README.md is a
    # different file from the root README.md and is legitimately scanned, so a
    # basename check would fail on it for the wrong reason.
    scanned = {p.resolve() for p in prose_files(ROOT)}
    for generated in (ROOT / "README.md", ROOT / "docs" / "SUBMISSION.md"):
        template = generated.with_name(
            generated.name.replace(".md", ".template.md"))
        if template.is_file():
            assert generated.resolve() not in scanned, (
                f"{generated.name} is generated from {template.name} and must "
                f"not be scanned")


# ==========================================================================
# The superseded-value check -- rule 1 as a property, where it can be one
# ==========================================================================
#
# The ratchet above counts literals. It cannot see staleness, because a literal
# that was already counted does not raise the count when the measurement behind
# it moves. That is how six unmarked `0.278` -- a superseded reading of
# `supervised_p_at_10` -- survived in README.template.md while every test
# passed, inside the document whose SUBMISSION.md section 6 claims the render
# system prevents exactly this.
#
# See docs/negative-results/template-literal-leak.md.

def _live_metric_values() -> dict[str, float]:
    import json
    payload = json.loads(
        (ROOT / "results" / "metrics.json").read_text(encoding="utf-8"))
    return {k: v["value"] for k, v in payload["metrics"].items()}


def _requires_metrics():
    if not (ROOT / "results" / "metrics.json").exists():
        pytest.skip("results/metrics.json not built")


# The narrative half of the repository: session records and findings documents,
# which narrate past states by nature. `docs/HANDOFF.md` describes itself as
# the session record; `docs/CENTREPIECE-INVALIDATED.md` is *about* the run in
# which the number was 0.2500. Marking every one of them would mean editing
# documents this project deliberately leaves alone as historical records.
#
# So they get a ratchet rather than an assertion, and the number is stated
# rather than implied -- the same honesty the standing rules apply to rule 1
# itself, which is recorded as "partial" rather than rounded up.
#
# Append, never edit in place.
STALE_IN_NARRATIVE_LEDGER = [
    ("2026-09-01", "template-literal-leak", 49,
     "baseline at first measurement. 49 unmarked superseded readings of "
     "supervised_p_at_10 across docs/, concentrated in HANDOFF.md (19) and "
     "ARCHITECTURE_UPLIFT.md (12), both of which are session records. The "
     "TEMPLATES are held at zero by the assertion below; this number exists "
     "so the narrative half cannot grow quietly while the enforced half "
     "looks clean."),
    ("2026-09-03", "next-phase-plan", 50,
     "+1, and it is a collision rather than a stale reading. "
     "docs/NEXT_PHASE_PLAN.md quotes lambdamart_p_at_10 = 0.2778, which is "
     "LIVE for that id and simultaneously a superseded value of "
     "supervised_p_at_10; the checker matches on the digits, not the id, so "
     "it fires. Marking it historical would be false -- the sentence narrates "
     "the present -- so it is ledgered instead. The document's other "
     "superseded figures (supervised p@10 0.2500 and the 1.32x ratio) were "
     "moved out of a table and carry the historical marker. This is a named "
     "limit of the mechanism, not a defect in the document."),
]

STALE_NARRATIVE_BASELINE = STALE_IN_NARRATIVE_LEDGER[-1][2]


def test_no_superseded_metric_value_survives_unmarked_in_a_template():
    """The assertion, not a ratchet. Templates carry the project's live claims.

    A template is where a human types a number that will be presented as
    current. Zero is the only defensible count there, and unlike the goal in
    `test_no_unmarked_metric_literals_in_prose` this one is reachable today --
    it forbids stale values, not all values.
    """
    _requires_metrics()
    from sentinel.report.literals import stale_literals

    hits = [h for h in stale_literals(ROOT, _live_metric_values())
            if h[0].endswith(".template.md")]
    assert not hits, (
        "a template states a value that a live metric id used to hold and no "
        "longer does:\n" + "\n".join(
            f"  {path}:{line} -- {literal!r} is a superseded value of "
            f"{sorted(ids)}" for path, line, literal, ids in hits) +
        "\n\nBind it to a placeholder, or mark it "
        "<!-- historical: measured at commit <sha>, <YYYY-MM-DD> --> if the "
        "sentence is narrating a past state. Rendering faithfully is not the "
        "same as being right: the render check compares output to template "
        "and cannot see a number typed into the template itself.")


def test_stale_values_in_the_narrative_documents_never_increase():
    """The ratchet for docs/, where narration of past states is the point."""
    _requires_metrics()
    from collections import Counter

    from sentinel.report.literals import stale_literals

    hits = [h for h in stale_literals(ROOT, _live_metric_values())
            if not h[0].endswith(".template.md")]
    assert len(hits) <= STALE_NARRATIVE_BASELINE, (
        f"unmarked superseded values in docs/ rose from "
        f"{STALE_NARRATIVE_BASELINE} to {len(hits)}. Per file: "
        f"{dict(Counter(h[0] for h in hits).most_common(5))}")


def test_the_narrative_ledger_is_append_only_and_gives_reasons():
    assert STALE_IN_NARRATIVE_LEDGER, "the ledger may not be emptied"
    for date, ref, count, reason in STALE_IN_NARRATIVE_LEDGER:
        assert len(date) == 10 and date[4] == "-", date
        assert ref, date
        assert isinstance(count, int) and count >= 0, date
        assert len(reason) > 20, f"{date}: reason too thin to audit: {reason!r}"
    dates = [e[0] for e in STALE_IN_NARRATIVE_LEDGER]
    assert dates == sorted(dates), "ledger entries must be in date order"


# --------------------------------------------------------------------------
# negative controls -- a check that cannot fail measures nothing
# --------------------------------------------------------------------------

def test_the_check_fires_on_a_planted_superseded_literal(tmp_path,
                                                         monkeypatch):
    """The control this project's own doctrine requires.

    A planted `0.278` in a template must be caught. Without this, the
    assertion above would pass forever the day the scanner stopped matching.
    """
    from sentinel.report import literals as lit

    tmpl = tmp_path / "X.template.md"
    tmpl.write_text("The model reaches 0.278 on held-out data.\n",
                    encoding="utf-8")
    monkeypatch.setattr(lit, "prose_files", lambda root: [tmpl])

    hits = lit.stale_literals(tmp_path, {"supervised_p_at_10": 0.2111},
                              use_git=False)
    assert hits, "the planted superseded literal was not caught"
    assert hits[0][2] == "0.278"
    assert hits[0][3] == {"supervised_p_at_10"}


def test_a_marked_superseded_literal_is_allowed(tmp_path, monkeypatch):
    """Narrating a past state is the marker's entire purpose.

    README.template.md's correction blockquote quotes 0.2778 and 0.2500 on
    purpose. If the check flagged those it would be pressuring the project to
    delete its own history, which is the opposite of standing rule 7.
    """
    from sentinel.report import literals as lit

    tmpl = tmp_path / "X.template.md"
    tmpl.write_text(
        "<!-- historical: measured at commit 0b4debd, 2026-08-31 -->\n"
        "It read 0.278 before the dead query groups were closed.\n",
        encoding="utf-8")
    monkeypatch.setattr(lit, "prose_files", lambda root: [tmpl])

    assert not lit.stale_literals(tmp_path, {"supervised_p_at_10": 0.2111},
                                  use_git=False)


def test_the_current_value_is_not_treated_as_superseded(tmp_path, monkeypatch):
    """The check forbids stale values, not all values.

    Quoting the CURRENT number is a different risk -- one the count ratchet
    already tracks -- and conflating the two would make this check fire on
    every correct sentence in the repository.
    """
    from sentinel.report import literals as lit

    tmpl = tmp_path / "X.template.md"
    tmpl.write_text("The model reaches 0.2111 on held-out data.\n",
                    encoding="utf-8")
    monkeypatch.setattr(lit, "prose_files", lambda root: [tmpl])

    assert not lit.stale_literals(tmp_path, {"supervised_p_at_10": 0.2111},
                                  use_git=False)


def test_the_pre_history_ledger_names_a_commit_and_a_reason():
    """Every declared superseded value must be auditable.

    `unknown` is an acceptable commit for the same reason the historical
    marker accepts it -- an admission beats an invented sha -- but a bare value
    with no reason is a number somebody could add to silence the check.
    """
    from sentinel.report.literals import PRE_HISTORY_SUPERSEDED

    assert PRE_HISTORY_SUPERSEDED, "the pre-history ledger may not be emptied"
    for mid, entries in PRE_HISTORY_SUPERSEDED.items():
        assert entries, mid
        for literal, commit, why in entries:
            assert literal[0].isdigit(), literal
            assert commit == "unknown" or len(commit) >= 7, (mid, commit)
            assert len(why) > 20, f"{mid}/{literal}: reason too thin: {why!r}"


def test_git_history_is_actually_walked():
    """The live half must do work, or the check is only its explicit ledger.

    Without this, `superseded_values` could silently degrade to reading
    PRE_HISTORY_SUPERSEDED alone -- for instance if the subprocess call started
    failing -- and nothing would notice, because the explicit ledger already
    catches the literal that motivated the check.
    """
    _requires_metrics()
    import subprocess

    from sentinel.report.literals import _metrics_at_commit

    log = subprocess.run(["git", "log", "--format=%H", "-1", "--",
                          "results/metrics.json"],
                         cwd=ROOT, capture_output=True, text=True)
    if log.returncode != 0 or not log.stdout.strip():
        pytest.skip("no git history for results/metrics.json")

    at_head = _metrics_at_commit(ROOT, log.stdout.split()[0])
    assert at_head, (
        "walking git history for results/metrics.json returned nothing. The "
        "check has silently degraded to its explicit ledger.")
    assert "supervised_p_at_10" in at_head
