"""The standing rules of docs/STANDING-RULES.md, as tests that fail loudly.

This file is the answer to a fair objection: most projects claim methodological
rigour in prose, and prose does not fail a build. Each rule below is either an
executable check or an explicit, recorded admission that it is not yet one.

Coverage map -- kept honest, including where it is thin:

  rule 1  never state an unmeasured number   -- partially: enforced negatively
                                                (nothing in sentinel/report
                                                computes a value) and by the
                                                literal scan, which is not yet
                                                written (Phase 4)
  rule 2  p@k carries its size baseline      -- ENFORCED here
  rule 3  ring-unit carries its conditioning -- ENFORCED here
  rule 4  Elliptic2 p@k carries prevalence   -- ENFORCED here
  rule 5  intervals name their clustering    -- ENFORCED here
  rule 6  sentinel.llm out of measured paths -- tests/test_import_boundaries.py
  rule 7  negative results are append-only   -- ENFORCED here, over git history
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.report import Metric, MetricContractError

ROOT = Path(__file__).resolve().parent.parent
NEGATIVES = ROOT / "docs" / "negative-results"


def _ok(**overrides) -> dict:
    """A metric that satisfies every rule, for tests to break one field of."""
    base = dict(id="p_at_10_amlworld", value=0.25, n_units=18, unit="cycle",
                ci_lower=0.1278, ci_upper=0.3722,
                ci_method="cycle_clustered_bootstrap",
                dataset="amlworld-hi-small", k=10, size_baseline=0.0444)
    base.update(overrides)
    return base


class TestRule2SizeBaseline:
    """A p@k must be quoted beside the baseline it is re-tied against."""

    def test_a_p_at_k_without_its_size_baseline_cannot_be_built(self):
        with pytest.raises(MetricContractError, match="size baseline"):
            Metric(**_ok(size_baseline=None))

    @pytest.mark.parametrize("k", [5, 10, 20, 50])
    def test_the_rule_holds_at_every_k(self, k):
        with pytest.raises(MetricContractError, match="size baseline"):
            Metric(**_ok(k=k, size_baseline=None))
        m = Metric(**_ok(k=k, size_baseline=0.0444))
        assert "size baseline" in m.render()

    def test_a_non_p_at_k_metric_does_not_require_one(self):
        """The rule is about p@k, not about every number.

        Asserted so the constraint cannot quietly generalise into "every
        metric needs a size baseline", which would push callers toward
        inventing one to get past the constructor.
        """
        m = Metric(**_ok(id="ap_amlworld", k=None, size_baseline=None))
        assert m.is_precision_at_k is False


class TestRule3ConditioningBanner:
    """A ring-unit metric cannot be rendered without its conditioning."""

    def test_a_ring_unit_metric_without_a_banner_raises(self):
        with pytest.raises(MetricContractError, match="conditioning"):
            Metric(**_ok(unit="ring", n_units=68, conditioning=None))

    def test_whitespace_is_not_a_banner(self):
        with pytest.raises(MetricContractError, match="conditioning"):
            Metric(**_ok(unit="ring", n_units=68, conditioning="   \n  "))

    def test_the_banner_reaches_every_rendering_path(self):
        """There must be no way out of the object that drops the banner.

        The failure this guards against is not "somebody forgot" -- it is
        "somebody reached for the short version because the full one was
        inconvenient". So the assertion is that no short version exists.
        """
        banner = ("P(ring in top 10 | BUILT). Cannot see the 26.6 points lost "
                  "at the build stage.")
        m = Metric(**_ok(unit="ring", n_units=68, conditioning=banner))
        assert "CONDITIONING" in m.render()
        assert "BUILT" in m.render()
        assert m.to_dict()["conditioning"] == banner
        for shortcut in ("bare", "render_without_banner", "short", "__format__"):
            assert not hasattr(type(m), shortcut) or shortcut == "__format__"

    def test_cycle_unit_metrics_do_not_require_one(self):
        assert Metric(**_ok(unit="cycle")).conditioning is None


class TestRule4Prevalence:
    """Any Elliptic2 p@k carries prevalence."""

    def test_elliptic2_without_prevalence_raises(self):
        with pytest.raises(MetricContractError, match="prevalence"):
            Metric(**_ok(dataset="elliptic2", prevalence=None))

    def test_elliptic2_with_prevalence_is_accepted_and_renders_it(self):
        m = Metric(**_ok(dataset="elliptic2", prevalence=0.0021))
        assert "prevalence" in m.render()

    def test_prevalence_must_be_a_proportion(self):
        with pytest.raises(MetricContractError, match="proportion"):
            Metric(**_ok(dataset="elliptic2", prevalence=2.5))


class TestRule5IntervalNamesItsClustering:
    """On this data the two clusterings differ by more than 2x in width, so an
    interval that does not say which it is has not been reported.

    NOTE the restatement. An earlier form of this rule read "use ring-clustered
    bootstrap, never cycle-clustered". That is wrong for p@k, whose trials are
    not nested within rings -- the cycle IS the correct cluster there, and
    `sentinel/eval/bootstrap.py` argues for it explicitly. The rule now says:
    cluster on the unit the trials are nested in, and where trials are nested
    in rings, report the WIDER of the two. See docs/STANDING-RULES.md rule 5.
    """

    def test_an_unnamed_clustering_is_refused(self):
        with pytest.raises(MetricContractError, match="clustering"):
            Metric(**_ok(ci_method="bootstrap"))

    def test_a_point_outside_its_own_interval_is_refused(self):
        with pytest.raises(MetricContractError, match="outside its own interval"):
            Metric(**_ok(value=0.9))

    def test_an_interval_is_not_optional(self):
        with pytest.raises(MetricContractError, match="ci_lower is required"):
            Metric(**_ok(ci_lower=None))

    def test_ring_clustering_is_wider_on_the_shipped_ring_unit_fixture(self):
        """The measurement the restated rule rests on, reproduced.

        Built so one ring contributes many correlated trials: resampling
        cycles leaves that repetition uncorrected and returns a narrower
        interval than resampling rings. If this ever comes back equal, the
        fixture has stopped exercising the thing rule 5 is about.
        """
        from scripts.eval_ring_unit import interval, _mean

        rows = []
        for cycle in range(12):
            # one dominant ring, always surfacing, seen in every cycle
            rows.append((cycle, 0, 1))
            rows.append((cycle, 0, 1))
            rows.append((cycle, 0, 1))
            # a long tail of one-off rings that never surface
            rows.append((cycle, 100 + cycle, 0))

        ci = interval(rows, _mean(2))
        assert ci["ring_clustered"]["width"] > ci["cycle_clustered"]["width"], ci
        # and the reported interval is the wider one, not either in particular
        assert ci["lo"] <= ci["ring_clustered"]["lo"]
        assert ci["hi"] >= ci["ring_clustered"]["hi"]


class TestRule1TheWriterCannotPublishAnIncompleteNumber:
    """Rule 1 is enforced in the writer, not by convention at the call site.

    Phase 4 turns README into a template rendered from a metrics file. The
    guarantee that makes that safe is not that callers are careful -- it is
    that the only type the writer accepts cannot be constructed incompletely.
    """

    def test_round_trip_preserves_every_mandatory_field(self, tmp_path):
        from sentinel.report import read, write

        metrics = [
            Metric(**_ok()),
            Metric(**_ok(id="ring_surfaced_at_10", unit="ring", n_units=68,
                         k=None, size_baseline=None,
                         ci_method="wider_of_cycle_and_ring_clustered_bootstrap",
                         conditioning="P(ring in top 10 | BUILT).")),
        ]
        path = write(tmp_path / "metrics.json", metrics,
                     generated_by="tests/test_standing_rules.py")
        back = read(path)
        assert set(back) == {"p_at_10_amlworld", "ring_surfaced_at_10"}
        assert back["p_at_10_amlworld"].size_baseline == 0.0444
        assert back["ring_surfaced_at_10"].conditioning.startswith("P(ring")

    def test_a_hand_edited_file_fails_on_read_not_on_render(self, tmp_path):
        """The failure must land at load time.

        A metrics file edited into an invalid state -- the exact thing a
        deadline invites -- has to fail before it can reach a document. Reading
        goes back through the constructor for this reason.
        """
        import json

        from sentinel.report import read, write

        path = write(tmp_path / "metrics.json", [Metric(**_ok())],
                     generated_by="tests/test_standing_rules.py")
        payload = json.loads(path.read_text(encoding="utf-8"))
        del payload["metrics"]["p_at_10_amlworld"]["size_baseline"]
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(MetricContractError, match="size baseline"):
            read(path)

    def test_duplicate_ids_are_refused(self, tmp_path):
        from sentinel.report import write

        with pytest.raises(MetricContractError, match="duplicate metric ids"):
            write(tmp_path / "metrics.json", [Metric(**_ok()), Metric(**_ok())],
                  generated_by="tests/test_standing_rules.py")

    def test_the_file_records_what_produced_it(self, tmp_path):
        import json

        from sentinel.report import write

        path = write(tmp_path / "metrics.json", [Metric(**_ok())],
                     generated_by="scripts/eval_oracle.py")
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["generated_by"] == "scripts/eval_oracle.py"
        assert payload["commit"]          # a sha, or the literal "unknown"
        assert payload["generated_at"]

    def test_nothing_in_the_reporting_layer_can_invent_a_value(self):
        """The mechanical form of rule 1, asserted as a property of the source.

        `value` must have no default and no computed fallback anywhere in
        sentinel/report. If a default is ever added, a caller who forgot to
        measure something gets a number instead of an error.
        """
        import dataclasses

        fields = {f.name: f for f in dataclasses.fields(Metric)}
        for required in ("value", "ci_lower", "ci_upper", "n_units",
                         "ci_method", "unit", "id"):
            f = fields[required]
            assert f.default is dataclasses.MISSING, \
                f"{required} acquired a default; rule 1 depends on it not having one"
            assert f.default_factory is dataclasses.MISSING, required


class TestRule7NegativeResultsAreAppendOnly:
    """Nothing in docs/negative-results/ has ever been deleted or truncated."""

    def test_the_directory_exists_and_has_an_index(self):
        assert NEGATIVES.is_dir(), (
            "docs/negative-results/ is the recorded home for results that did "
            "not go the way the plan expected. Rule 7 has no meaning without "
            "a place it applies to.")
        assert (NEGATIVES / "README.md").is_file()

    def test_no_file_has_ever_been_deleted_from_the_directory(self):
        out = subprocess.run(
            ["git", "log", "--diff-filter=D", "--name-only", "--format=",
             "--", "docs/negative-results"],
            cwd=ROOT, capture_output=True, text=True)
        if out.returncode != 0:
            pytest.skip("git history unavailable")
        deleted = sorted({line.strip() for line in out.stdout.splitlines()
                          if line.strip()})
        assert not deleted, (
            f"negative results were deleted: {deleted}. Rule 7 exists because "
            f"the cheapest way to make a project look successful is to stop "
            f"recording the things that did not work.")

    def test_every_recorded_negative_names_what_would_reverse_it(self):
        """A negative result that cannot be reversed is an opinion.

        Each entry must say what measurement would overturn it, so a later
        reader can tell a measured null from a discouraged guess.
        """
        missing = []
        for path in sorted(NEGATIVES.glob("*.md")):
            if path.name == "README.md":
                continue
            text = path.read_text(encoding="utf-8").lower()
            if "what would reverse this" not in text:
                missing.append(path.name)
        assert not missing, (
            f"negative results with no reversal condition: {missing}")
