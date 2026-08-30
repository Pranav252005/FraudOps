"""The cost model, and the two claims it is allowed to make.

The interesting assertions are that the break-even precision is derived
correctly and that the module refuses to launder a guess: `unsourced()` must
name every input still resting on a placeholder, and `optimal_k` must return
None rather than the least-bad depth when nothing is net-positive.
"""
from __future__ import annotations

import math

import pytest

from sentinel.economics.cost import (ADVERSE_DIRECTION, CostModel,
                                     evaluate_queue, joint_adverse, optimal_k,
                                     sensitivity)


@pytest.fixture
def model() -> CostModel:
    return CostModel(analyst_minutes_per_case=60.0,
                     analyst_cost_per_hour=1000.0,
                     value_at_risk_per_ring=100_000.0,
                     recovery_rate=0.5,
                     analyst_false_approval_rate=0.0,
                     harm_per_wrong_action=0.0)


def test_review_cost_is_time_times_rate(model):
    assert model.review_cost == 1000.0


def test_break_even_precision_matches_the_closed_form(model):
    # benefit = 100_000 * 0.5 = 50_000; review = 1_000; harm = 0
    # p* = (1000 + 0) / (50000 + 0) = 0.02
    assert model.break_even_precision() == pytest.approx(0.02)


def test_net_benefit_is_zero_at_the_break_even_point(model):
    assert model.net_benefit_per_case(
        model.break_even_precision()) == pytest.approx(0.0, abs=1e-9)


def test_residual_harm_raises_the_break_even(model):
    with_harm = CostModel(**{**model.__dict__,
                             "analyst_false_approval_rate": 0.10,
                             "harm_per_wrong_action": 50_000.0})
    assert with_harm.break_even_precision() > model.break_even_precision()


def test_no_upside_never_breaks_even():
    """A queue with nothing to gain must report inf, not 1.0 -- 1.0 would
    imply a perfect detector would be enough."""
    barren = CostModel(value_at_risk_per_ring=0.0, recovery_rate=0.0,
                       analyst_false_approval_rate=0.0,
                       harm_per_wrong_action=0.0)
    assert math.isinf(barren.break_even_precision())


def test_precision_outside_zero_one_is_rejected(model):
    with pytest.raises(ValueError):
        model.net_benefit_per_case(1.4)


# --- provenance --------------------------------------------------------------

def test_defaults_are_reported_as_unsourced():
    """Every default is a placeholder and the model must say so."""
    assert len(CostModel().unsourced()) == 6


def test_recording_a_source_clears_it():
    m = CostModel(sources={"analyst_cost_per_hour": "internal ops estimate"})
    assert "analyst_cost_per_hour" not in m.unsourced()


# --- queue evaluation ---------------------------------------------------------

def test_optimal_k_maximises_total_not_per_case_benefit(model):
    # p@10 is higher, but the top 50 is worth more in total.
    p_at_k = {10: 0.10, 20: 0.08, 50: 0.06}
    points = {p.k: p for p in evaluate_queue(p_at_k, model)}
    assert points[10].net_benefit_per_case > points[50].net_benefit_per_case
    assert optimal_k(p_at_k, model) == 50


def test_optimal_k_is_none_when_no_depth_pays(model):
    """'Work the top 10, it loses least' is not a recommendation."""
    below = model.break_even_precision() / 2
    assert optimal_k({10: below, 20: below}, model) is None


def test_above_break_even_flag_tracks_the_threshold(model):
    p = model.break_even_precision()
    points = {q.k: q for q in evaluate_queue({10: p * 2, 20: p / 2}, model)}
    assert points[10].above_break_even is True
    assert points[20].above_break_even is False


# --- sensitivity --------------------------------------------------------------

def test_sensitivity_moves_break_even_in_the_expected_direction(model):
    result = sensitivity(model, factors=(0.5, 1.0, 2.0))
    # A more expensive analyst raises the bar; a more valuable ring lowers it.
    rate = result["analyst_cost_per_hour"]
    assert rate[0.5] < rate[1.0] < rate[2.0]
    value = result["value_at_risk_per_ring"]
    assert value[0.5] > value[1.0] > value[2.0]


def test_sensitivity_does_not_push_a_probability_above_one(model):
    result = sensitivity(model, factors=(4.0,))
    # recovery_rate 0.5 * 4 would be 2.0; it must be clamped.
    clamped = CostModel(**{**model.__dict__, "recovery_rate": 1.0})
    assert result["recovery_rate"][4.0] == pytest.approx(
        clamped.break_even_precision())


# --- the inversion ------------------------------------------------------------

def test_required_value_at_risk_inverts_the_break_even(model):
    """At the break-even precision, the required exposure is exactly the
    modelled one -- the two directions must agree."""
    p = model.break_even_precision()
    assert model.required_value_at_risk(p) == pytest.approx(
        model.value_at_risk_per_ring)


def test_higher_precision_needs_less_exposure_to_pay(model):
    assert (model.required_value_at_risk(0.10)
            < model.required_value_at_risk(0.02))


def test_zero_precision_never_pays_at_any_exposure(model):
    assert math.isinf(model.required_value_at_risk(0.0))


# --- the joint stress ---------------------------------------------------------

def test_joint_adverse_moves_every_input_the_wrong_way(model):
    """One-at-a-time sensitivity understates the risk; this is the corner."""
    worst = joint_adverse(model, factor=2.0)
    for name, direction in ADVERSE_DIRECTION.items():
        base, moved = getattr(model, name), getattr(worst, name)
        if base == 0.0:
            # A zeroed input has no adverse direction to move in; the fixture
            # zeroes the false-approval terms deliberately.
            assert moved == 0.0, name
        elif direction == "up":
            assert moved > base, name
        else:
            assert moved < base, name


def test_joint_adverse_is_worse_than_any_single_input(model):
    """The joint corner must dominate every one-at-a-time perturbation."""
    joint = joint_adverse(model, factor=2.0).break_even_precision()
    singles = sensitivity(model, factors=(0.5, 2.0))
    for name, row in singles.items():
        assert joint >= max(row.values()), name


def test_joint_adverse_rejects_a_factor_below_one(model):
    with pytest.raises(ValueError):
        joint_adverse(model, factor=0.5)


def test_joint_adverse_compounds_each_derived_quantity_twice():
    """Review cost, benefit and residual harm are each a product of two
    adversely-moved inputs, so a x2 on the inputs is x4 on the quantity.

    The `model` fixture zeroes the harm terms, which would hide exactly this;
    this case uses non-zero ones on purpose.
    """
    m = CostModel(analyst_minutes_per_case=60.0,
                  analyst_cost_per_hour=1000.0,
                  value_at_risk_per_ring=100_000.0,
                  recovery_rate=0.4,
                  analyst_false_approval_rate=0.05,
                  harm_per_wrong_action=20_000.0)
    worst = joint_adverse(m, factor=2.0)
    assert worst.review_cost == pytest.approx(m.review_cost * 4)
    assert worst.benefit_per_true_positive == pytest.approx(
        m.benefit_per_true_positive / 4)
    assert worst.harm_per_false_positive == pytest.approx(
        m.harm_per_false_positive * 4)


def test_joint_adverse_clamps_a_probability_it_pushes_upward():
    """`analyst_false_approval_rate` moves up; a large factor must not take it
    past 1.0 and produce a nonsense expected harm."""
    m = CostModel(analyst_false_approval_rate=0.5)
    assert joint_adverse(m, factor=8.0).analyst_false_approval_rate == 1.0
