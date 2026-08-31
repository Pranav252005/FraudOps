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
            "Edit the template and re-run scripts/render_readme.py; never "
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

    def test_every_ring_unit_metric_carries_its_banner(self, metrics):
        ring = [m for m in metrics.values() if m.unit == "ring"]
        assert ring, "expected at least one ring-unit metric"
        for m in ring:
            assert m.conditioning and "BUILT" in m.conditioning, m.id

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
