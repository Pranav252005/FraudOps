"""Phase 3's harness, including the test that gates everything else.

The plan is explicit that the null arm reproducing the headline is a regression
test on the WHOLE harness: pool loading, the fit, the per-cycle grouping and
the metric. If it fails, nothing else in the phase is trustworthy and no
coefficient from it may be quoted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.eval_label_tax import (BUDGET_GRID, NOISE_GRID, PREREG, SEEDS,
                                    budget_arm, cycle_rows, noise_arm, ols,
                                    p_at, required_n,
                                    require_committed_prereg)

POOL = ROOT / "data" / "ranker_pool.npz"
ORACLE = ROOT / "data" / "eval_oracle.json"
needs_pool = pytest.mark.skipif(
    not POOL.exists() or not ORACLE.exists(),
    reason="needs data/ranker_pool.npz and data/eval_oracle.json")


class TestThePreregGate:
    """The runner must refuse to start without a committed pre-registration."""

    def test_both_arms_name_a_prereg_that_exists(self):
        for arm, rel in PREREG.items():
            assert (ROOT / rel).is_file(), f"{arm}: {rel} missing"

    def test_both_preregs_are_committed(self):
        for arm in PREREG:
            sha = require_committed_prereg(arm)
            assert len(sha) == 40, arm

    def test_an_unknown_arm_has_no_prereg_and_cannot_run(self):
        with pytest.raises(KeyError):
            require_committed_prereg("does_not_exist")


class TestOls:
    def test_recovers_a_known_line(self):
        slope, intercept, resid = ols([0, 1, 2, 3], [1, 3, 5, 7])
        assert slope == pytest.approx(2.0)
        assert intercept == pytest.approx(1.0)
        assert all(abs(r) < 1e-12 for r in resid)

    def test_residuals_expose_curvature(self):
        _, _, resid = ols([0, 1, 2, 3], [0, 1, 4, 9])
        assert max(abs(r) for r in resid) > 0.5

    def test_a_flat_response_gives_a_zero_slope(self):
        slope, _, _ = ols([0, 0.1, 0.2, 0.4], [0.2, 0.2, 0.2, 0.2])
        assert slope == pytest.approx(0.0)


class TestRequiredN:
    def test_scales_as_one_over_root_n(self):
        """Halving the effect quadruples the cycles needed."""
        assert required_n(0.1, 0.05) == 18 * 4
        assert required_n(0.1, 0.025) == 18 * 16

    def test_a_null_effect_has_no_resolving_n(self):
        assert required_n(0.1, 0.0) is None


class TestGrids:
    def test_the_grids_match_the_preregistrations(self):
        """The grid is pre-registered; changing it after seeing results is the
        move the prereg exists to prevent, so it is asserted here too."""
        assert NOISE_GRID == (0.0, 0.05, 0.10, 0.20, 0.40)
        assert BUDGET_GRID == (1.0, 0.5, 0.25, 0.1)
        assert len(SEEDS) == 5

    def test_the_noise_grid_starts_at_zero(self):
        """The null arm must be IN the grid, or the regression check below has
        nothing to compare against."""
        assert NOISE_GRID[0] == 0.0

    def test_the_budget_grid_starts_at_one(self):
        assert BUDGET_GRID[0] == 1.0


@needs_pool
class TestTheNullArmReproducesTheBaseline:
    """THE gate. A harness that cannot reproduce the stored number is not
    measuring a label tax; it is measuring itself."""

    @pytest.fixture(scope="class")
    @classmethod
    def pool(cls):
        from scripts.eval_label_tax import load_pool
        return load_pool()

    def test_p_at_k_matches_the_stored_oracle_exactly(self, pool):
        from scripts.eval_label_tax import fit_and_score
        score = fit_and_score(pool["Xtr"], pool["ytr"], pool["Xte"])
        rows = cycle_rows(score, pool["yte"], pool["tte"])
        stored = json.loads(ORACLE.read_text(encoding="utf-8"))
        want = stored["oracle_as_is"]["precision_at"]
        for k in (10, 20, 50):
            assert p_at(rows, k) == want[str(k)]["oracle"], (
                f"p@{k}: harness gives {p_at(rows, k)!r}, "
                f"data/eval_oracle.json stores {want[str(k)]['oracle']!r}. "
                f"Nothing in Phase 3 is trustworthy until this matches.")

    def test_the_noise_arm_at_p_zero_flips_nothing(self, pool):
        out = noise_arm(pool, 0.0, seed=11)
        assert out["n_flipped"] == 0
        assert out["raw"]["n_positive"] == out["control"]["n_positive"]
        assert out["raw"]["n_train"] == out["control"]["n_train"]
        # and both arms coincide with the baseline
        assert out["raw"]["p_at"][10] == out["control"]["p_at"][10]

    def test_the_budget_arm_at_f_one_keeps_everything(self, pool):
        out = budget_arm(pool, 1.0, seed=11)
        assert out["n_train"] == len(pool["ytr"])
        assert out["n_positive"] == int(pool["ytr"].sum())


@needs_pool
class TestTheCorruptionIsWhatItClaims:

    @pytest.fixture(scope="class")
    @classmethod
    def pool(cls):
        from scripts.eval_label_tax import load_pool
        return load_pool()

    @pytest.mark.parametrize("p", [0.05, 0.10, 0.20, 0.40])
    def test_corruption_is_applied_at_the_stated_rate(self, pool, p):
        """The fraction of positives actually flipped is p, not approximately p.

        Flipping is by exact count rather than by per-row coin flip precisely
        so this is an equality: with 165 positives, a Bernoulli draw at p=0.05
        would land anywhere from 3 to 15 and the grid would stop meaning what
        it says.
        """
        out = noise_arm(pool, p, seed=11)
        n_pos = int(pool["ytr"].sum())
        assert out["n_flipped"] == int(round(p * n_pos))
        assert out["raw"]["n_positive"] == n_pos - out["n_flipped"]

    def test_corruption_moves_positives_to_negative_only(self, pool):
        """One direction. A flip that created positives would be a different
        experiment with a different confound."""
        out = noise_arm(pool, 0.40, seed=11)
        assert out["raw"]["n_positive"] < int(pool["ytr"].sum())
        assert out["raw"]["n_train"] == len(pool["ytr"])

    def test_corruption_is_seeded_and_reproducible(self, pool):
        a = noise_arm(pool, 0.20, seed=11)
        b = noise_arm(pool, 0.20, seed=11)
        assert a["raw"]["p_at"][10] == b["raw"]["p_at"][10]

    def test_different_seeds_select_different_positives(self, pool):
        """Guards against a seed that is not wired through. If two seeds gave
        identical results the five repetitions would be one repetition reported
        five times -- the exact defect commit 8c17994 caught elsewhere."""
        a = noise_arm(pool, 0.40, seed=11)
        b = noise_arm(pool, 0.40, seed=55)
        assert a["raw"]["p_at"][10] != b["raw"]["p_at"][10] or \
            a["control"]["p_at"][10] != b["control"]["p_at"][10]

    def test_the_control_holds_the_positive_count_equal_to_raw(self, pool):
        """The prevalence control's whole job. If these diverge, `raw - control`
        is not isolating noise from prevalence."""
        for p in (0.05, 0.20, 0.40):
            out = noise_arm(pool, p, seed=11)
            assert out["raw"]["n_positive"] == out["control"]["n_positive"]
            assert out["control"]["n_train"] < out["raw"]["n_train"]

    def test_the_control_prevalence_matches_raw_closely(self, pool):
        """Pre-registered as within a factor of ~1.0004 at p=0.4."""
        out = noise_arm(pool, 0.40, seed=11)
        ratio = out["control"]["prevalence"] / out["raw"]["prevalence"]
        assert 1.0 <= ratio < 1.001, ratio

    def test_prevalence_is_reported_at_every_point(self, pool):
        out = noise_arm(pool, 0.20, seed=11)
        for arm in ("raw", "control"):
            assert 0.0 < out[arm]["prevalence"] < 1.0


@needs_pool
class TestTheBudgetArm:

    @pytest.fixture(scope="class")
    @classmethod
    def pool(cls):
        from scripts.eval_label_tax import load_pool
        return load_pool()

    @pytest.mark.parametrize("f", [0.5, 0.25, 0.1])
    def test_the_retained_fraction_is_f(self, pool, f):
        out = budget_arm(pool, f, seed=11)
        assert out["n_train"] == int(round(f * len(pool["ytr"])))

    def test_subsampling_is_seeded(self, pool):
        a = budget_arm(pool, 0.25, seed=11)
        b = budget_arm(pool, 0.25, seed=11)
        assert a["p_at"][10] == b["p_at"][10]

    def test_the_subsample_is_uniform_not_stratified(self, pool):
        """Pre-registered as uniform. A stratified draw would preserve the
        positive count and measure something else entirely."""
        f = 0.1
        out = budget_arm(pool, f, seed=11)
        n_pos = int(pool["ytr"].sum())
        # Roughly f * n_pos positives retained, not all of them.
        assert out["n_positive"] < n_pos
        assert abs(out["n_positive"] - f * n_pos) < 4 * (f * n_pos) ** 0.5 + 3


class TestReportedResults:
    """Checks against whatever the arms have actually written."""

    @pytest.mark.parametrize("arm", ["noise", "budget"])
    def test_the_result_records_its_prereg_commit(self, arm):
        path = ROOT / "data" / f"eval_label_tax_{arm}.json"
        if not path.exists():
            pytest.skip(f"{path.name} not produced yet")
        out = json.loads(path.read_text(encoding="utf-8"))
        assert out["prereg"] == PREREG[arm]
        assert len(out["prereg_commit"]) == 40
        assert out["evaluation_labels"] == "true"
        assert out["ci_method"] == "cycle_clustered_bootstrap"

    @pytest.mark.parametrize("arm", ["noise", "budget"])
    def test_every_point_reports_prevalence(self, arm):
        """Rule 4 discipline, applied beyond the dataset that mandates it."""
        path = ROOT / "data" / f"eval_label_tax_{arm}.json"
        if not path.exists():
            pytest.skip(f"{path.name} not produced yet")
        out = json.loads(path.read_text(encoding="utf-8"))
        for x, point in out["points"].items():
            keys = [k for k in point if k.startswith("prevalence")]
            assert keys, f"{arm} point {x} reports no prevalence"

    def test_monotonicity_is_recorded_not_enforced(self):
        """A non-monotone response is a finding, not a bug. The runner must
        RECORD it; this test must never assert monotonicity itself."""
        path = ROOT / "data" / "eval_label_tax_noise.json"
        if not path.exists():
            pytest.skip("noise arm not produced yet")
        out = json.loads(path.read_text(encoding="utf-8"))
        assert "monotone_in_p" in out["fit"]
        assert isinstance(out["fit"]["monotone_in_p"], bool)
