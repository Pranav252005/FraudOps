"""Phase 4 -- README is rendered, and the rendering is checked.

The point of templating README is not tidiness. A number lived in 1,835 places
across this repository, so it could be wrong in 1,835 places, and `0.2778`
appeared 14 times in README while being wrong twice over. Nobody edited it
either time, because nothing failed when it went stale.

These tests are what fails.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sentinel.report import Metric, MetricContractError
from sentinel.report.literals import MARKER, scan
from sentinel.report.render import (PLACEHOLDER, RenderError, render_file,
                                    render_text)
from sentinel.report.store import read

TEMPLATE = ROOT / "README.template.md"
RENDERED = ROOT / "README.md"
SUBMISSION_TEMPLATE = ROOT / "docs" / "SUBMISSION.template.md"
SUBMISSION = ROOT / "docs" / "SUBMISSION.md"
METRICS = ROOT / "results" / "metrics.json"

needs_metrics = pytest.mark.skipif(
    not METRICS.exists() or not TEMPLATE.exists(),
    reason="needs README.template.md and results/metrics.json")


@pytest.fixture(scope="module")
def metrics():
    return read(METRICS)


@pytest.fixture(scope="module")
def counts():
    return json.loads(METRICS.read_text(encoding="utf-8")).get("counts", {})


@needs_metrics
class TestRenderCompleteness:

    def test_the_template_renders_with_no_unresolved_placeholders(
            self, metrics, counts):
        out = render_text(TEMPLATE.read_text(encoding="utf-8"), metrics, counts)
        assert "{{" not in out and "}}" not in out

    def test_every_placeholder_id_exists(self, metrics, counts):
        text = TEMPLATE.read_text(encoding="utf-8")
        missing = []
        for m in PLACEHOLDER.finditer(text):
            verb, mid = m.group("verb"), m.group("id")
            pool = counts if verb.startswith("count") else metrics
            if mid not in pool:
                missing.append(f"{{{{{verb}:{mid}}}}}")
        assert not missing, f"template references unknown ids: {missing}"

    def test_the_template_actually_uses_placeholders(self):
        """A template with no placeholders would pass every test above while
        being a plain file with the same stale numbers in it."""
        text = TEMPLATE.read_text(encoding="utf-8")
        assert len(PLACEHOLDER.findall(text)) >= 40


@needs_metrics
class TestRenderStrictness:
    """Rendering must FAIL rather than warn, degrade, or leave a hole."""

    def test_an_unknown_id_raises(self, metrics, counts):
        with pytest.raises(RenderError, match="does not"):
            render_text("{{metric:no_such_metric}}", metrics, counts)

    def test_an_unknown_verb_raises(self, metrics, counts):
        with pytest.raises(RenderError, match="unknown placeholder verb"):
            render_text("{{wobble:supervised_p_at_10}}", metrics, counts)

    def test_an_unknown_count_raises(self, metrics, counts):
        with pytest.raises(RenderError, match="counts"):
            render_text("{{count:no_such_count}}", metrics, counts)

    def test_a_missing_baseline_raises_rather_than_rendering_blank(self):
        """The plan's requirement: rendering fails if a referenced metric lacks
        a required field. A metric with no `k` has no size baseline, and asking
        for one must be an error rather than an empty string."""
        m = Metric(id="ap", value=0.22, n_units=18, unit="cycle",
                   ci_lower=0.1, ci_upper=0.3,
                   ci_method="cycle_clustered_bootstrap")
        with pytest.raises(RenderError, match="size_baseline"):
            render_text("{{baseline:ap}}", {"ap": m}, {})

    def test_a_missing_prevalence_raises(self):
        m = Metric(id="ap", value=0.22, n_units=18, unit="cycle",
                   ci_lower=0.1, ci_upper=0.3,
                   ci_method="cycle_clustered_bootstrap")
        with pytest.raises(RenderError, match="prevalence"):
            render_text("{{prevalence:ap}}", {"ap": m}, {})

    def test_there_is_no_raw_escape_hatch(self, metrics, counts):
        """A verb that emitted a bare number would let a writer bypass rule 2
        while still passing the literal scan -- which would make the scan worse
        than useless, because it would certify the file as clean."""
        for verb in ("raw", "bare", "value", "plain", "unsafe"):
            with pytest.raises(RenderError):
                render_text(f"{{{{{verb}:supervised_p_at_10}}}}",
                            metrics, counts)

    def test_a_metrics_file_missing_a_required_field_fails_on_load(
            self, tmp_path):
        payload = json.loads(METRICS.read_text(encoding="utf-8"))
        mid = "supervised_p_at_10"
        del payload["metrics"][mid]["size_baseline"]
        p = tmp_path / "metrics.json"
        p.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(MetricContractError, match="size baseline"):
            read(p)


@needs_metrics
class TestIdempotence:

    def test_rendering_twice_produces_identical_output(
            self, metrics, counts, tmp_path):
        a = render_text(TEMPLATE.read_text(encoding="utf-8"), metrics, counts)
        b = render_text(TEMPLATE.read_text(encoding="utf-8"), metrics, counts)
        assert a == b

    def test_the_committed_readme_matches_a_fresh_render(self, tmp_path):
        """README.md must not drift from its template.

        This is the test that makes the whole scheme work. Without it somebody
        edits README.md directly, the edit survives until the next render, and
        the file is once again a place where a number can be wrong.
        """
        fresh = render_file(TEMPLATE, METRICS, tmp_path / "README.md")
        got = fresh.read_text(encoding="utf-8").splitlines()
        have = RENDERED.read_text(encoding="utf-8").splitlines()
        # The banner carries a generation timestamp, which differs by design.
        got = [ln for ln in got if not ln.startswith("<!-- metrics:")]
        have = [ln for ln in have if not ln.startswith("<!-- metrics:")]
        assert got == have, (
            "README.md differs from a fresh render of README.template.md. "
            "Edit the template and re-run scripts/render_docs.py; never "
            "edit README.md directly.")

    def test_the_rendered_readme_says_it_is_generated(self):
        first = RENDERED.read_text(encoding="utf-8").splitlines()[0]
        assert "GENERATED" in first and "DO NOT EDIT" in first


@needs_metrics
class TestHistoricalMarkers:
    """Every exempt literal must carry a marker with a commit and a date."""

    def test_every_exemption_is_backed_by_a_well_formed_marker(self):
        text = TEMPLATE.read_text(encoding="utf-8")
        markers = MARKER.findall(text)
        exempt = [(ln, lit) for ln, lit, ex in scan(TEMPLATE) if ex]
        if exempt:
            assert markers, (
                "literals are exempt but no well-formed marker exists; the "
                "exemption must come from a marker, not from anything else")
        for commit, date in markers:
            assert commit == "unknown" or len(commit) >= 7, commit
            assert date == "unknown" or len(date) == 10, date

    def test_a_marker_without_a_commit_does_not_exempt(self, tmp_path):
        doc = tmp_path / "d.md"
        doc.write_text("<!-- historical -->\nIt reached 0.2500.\n",
                       encoding="utf-8")
        assert not any(ex for _, _, ex in scan(doc))

    def test_the_template_has_fewer_literals_than_it_started_with(self):
        """The ratchet, applied to the file the exercise is about.

        README carried 313 unmarked metric literals before Phase 4. The
        conversion is incomplete by design -- the remaining ones are in prose
        sections that are not results -- but it must not go backwards.
        """
        unmarked = sum(1 for _, _, ex in scan(TEMPLATE) if not ex)
        assert unmarked <= 200, (
            f"README.template.md has {unmarked} unmarked metric literals, up "
            f"from the 196 recorded when Phase 4 landed.")


@needs_metrics
class TestTheMetricsFileIsTheSourceOfTruth:

    def test_every_metric_carries_its_interval_and_clustering(self, metrics):
        for mid, m in metrics.items():
            assert m.ci_method, mid
            assert m.ci_lower <= m.value <= m.ci_upper, mid

    def test_every_p_at_k_carries_a_size_baseline(self, metrics):
        for mid, m in metrics.items():
            if m.is_precision_at_k:
                assert m.size_baseline is not None, mid

    def test_every_conditioned_unit_metric_carries_its_banner(self, metrics):
        """Every unit except the cycle conditions on something.

        This used to require the substring "BUILT" of every ring-unit metric,
        which was right while the ring-unit p@k was the only one. A second
        ring-unit metric now exists -- seed-reach coverage, conditioned on the
        group having been SEEDED rather than BUILT -- so the general form is
        that the banner names the event, and the BUILT check stays pinned to
        the metric it was written for, below.
        """
        conditioned = [m for m in metrics.values() if m.unit in ("ring", "world")]
        assert conditioned, "expected at least one conditioned-unit metric"
        for m in conditioned:
            assert m.conditioning and m.conditioning.strip(), m.id
            assert "|" in m.conditioning, (
                f"{m.id}: a conditioning banner must name what it is "
                f"conditioned ON, not merely carry prose")

    def test_the_ring_unit_metric_still_names_BUILT(self, metrics):
        """The specific banner rule 3 exists for: the ring-unit p@k reads
        HIGHER than the unconditioned p@k because it cannot see the build
        stage, where BIPARTITE and STACK are lost systematically."""
        surfaced = [m for mid, m in metrics.items()
                    if mid.startswith("ring_unit_")]
        assert surfaced, "the ring-unit surfaced metrics are expected to exist"
        for m in surfaced:
            assert "BUILT" in m.conditioning, m.id

    def test_the_seed_cheat_metrics_carry_their_ceiling_banner(self, metrics):
        """Run 2 is a diagnostic. Anything derived from it must say so at the
        point of use, not in a paragraph somewhere else."""
        for mid, m in metrics.items():
            if mid.startswith("seeding_prize_"):
                assert m.conditioning and "CEILING" in m.conditioning, mid

    def test_ratios_carry_the_absolute_values_they_are_a_ratio_of(self, metrics):
        """This project shipped a '2.8x' that was not a ratio of anything,
        because its halves had different denominators."""
        for mid, m in metrics.items():
            if "ratio" in mid:
                joined = " ".join(m.notes)
                assert "->" in joined or "minus" in joined, (
                    f"{mid} is a ratio with no absolute values in its notes")

    def test_the_two_label_tax_arms_are_separate_metrics(self, metrics):
        """Never averaged, so never stored as one number."""
        assert "label_tax_noise_slope_per_0_1" in metrics
        assert "label_tax_budget_slope_per_halving" in metrics
        for mid in ("label_tax", "label_tax_combined", "label_tax_slope"):
            assert mid not in metrics, f"{mid} conflates two estimands"


@needs_metrics
class TestTheSubmissionArtifact:
    """Phase 5. The buildathon-facing write-up is rendered like everything
    else, so it cannot go stale the way README did."""

    def test_it_is_generated_from_a_template(self):
        assert SUBMISSION_TEMPLATE.is_file()
        first = SUBMISSION.read_text(encoding="utf-8").splitlines()[0]
        assert "GENERATED" in first and "DO NOT EDIT" in first

    def test_it_matches_a_fresh_render(self, tmp_path):
        fresh = render_file(SUBMISSION_TEMPLATE, METRICS,
                            tmp_path / "SUBMISSION.md")
        got = [ln for ln in fresh.read_text(encoding="utf-8").splitlines()
               if not ln.startswith("<!-- metrics:")]
        have = [ln for ln in SUBMISSION.read_text(encoding="utf-8").splitlines()
                if not ln.startswith("<!-- metrics:")]
        assert got == have, (
            "docs/SUBMISSION.md differs from a fresh render. Run "
            "scripts/collect_metrics.py then scripts/render_docs.py.")

    def test_it_links_every_negative_result(self):
        """The index must be complete, or 'negative results are recorded'
        becomes a claim about a subset somebody chose."""
        text = SUBMISSION.read_text(encoding="utf-8")
        entries = sorted(p.stem for p in (ROOT / "docs" / "negative-results")
                         .glob("*.md") if p.name != "README.md")
        missing = [e for e in entries if e not in text]
        assert not missing, f"submission does not link: {missing}"

    def test_it_links_the_standing_rules_tests(self):
        """Item 5 of the plan: the test file is the evidence that the
        methodology is enforced rather than promised."""
        text = SUBMISSION.read_text(encoding="utf-8")
        for path in ("docs/STANDING-RULES.md",
                     "tests/test_standing_rules.py",
                     "tests/test_import_boundaries.py",
                     "tests/test_measured_path_closure.py"):
            assert path.rsplit("/", 1)[-1] in text, path

    def test_it_names_the_pre_registration_that_fired(self):
        text = SUBMISSION.read_text(encoding="utf-8")
        assert "ARCHITECTURE_UPLIFT.md" in text
        assert "1.5" in text and "kill line" in text.lower()

    def test_it_carries_the_ceiling_banner_on_the_seed_cheat(self):
        """The seeding prize is the most quotable number here and the most
        misquotable. Its diagnostic status must be adjacent to it."""
        text = SUBMISSION.read_text(encoding="utf-8")
        i = text.find("seeding")
        assert i >= 0
        assert "CEILING DIAGNOSTIC" in text

    def test_it_states_what_the_work_is_not(self):
        text = SUBMISSION.read_text(encoding="utf-8")
        assert "What this is not" in text
        for claim in ("Not a deployment", "Not a supervised result",
                      "Not measured at adequate"):
            assert claim in text, claim
