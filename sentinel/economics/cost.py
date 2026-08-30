"""What a review costs, what a miss costs, and the precision at which the
queue starts paying for itself.

**The headline output is a break-even precision, not a rupee figure.** That is
a deliberate choice and it is the whole design. Absolute expected-loss numbers
require knowing the value at risk behind an average ring, which nobody
building on a public benchmark actually knows -- quoting one would be the same
category of error as this project's bug #8, a confident number resting on an
assumption nobody checked. A break-even threshold is derived from the *ratios*
between costs, is far more stable than any of its inputs, and answers the
question an ops lead actually asks: *is working this queue worth the analyst
time it consumes?*

**Why the false-positive cost here is mostly labour.** In a system that
auto-actions, a false positive freezes a legitimate merchant's payouts and the
cost is customer harm. Sentinel's actions are human-gated and enumerated
(`sentinel/escalation.py`), so a false positive is normally absorbed by an
analyst dismissing it -- the gate converts merchant harm into labour cost.
That is a real architectural property and it is worth saying out loud, but it
is not total: analysts approve some share of bad recommendations, so the
residual harm term stays in the model with an explicit error rate rather than
being assumed to zero.

**Every default here is a placeholder and is labelled as one.** `sources`
records where each figure came from, and `unsourced()` lists the ones still
resting on nothing. A cost model whose provenance is not visible is worse than
no cost model, because it launders a guess into a decision.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

# Placeholder marker for an input that has not yet been grounded in a source.
UNSOURCED = "PLACEHOLDER -- not yet grounded in a measured or cited figure"


@dataclass(frozen=True)
class CostModel:
    """Costs in a single currency unit. Ratios are what matter, not the unit.

    The defaults are illustrative and every one of them is unsourced. They
    exist so the machinery is runnable and testable, not so they can be
    quoted. Replace them, and record where each came from in `sources`.
    """

    # --- cost of reviewing one case -----------------------------------------
    analyst_minutes_per_case: float = 45.0
    analyst_cost_per_hour: float = 1500.0

    # --- benefit of catching a real ring ------------------------------------
    # Exposure behind one confirmed ring, and the share of it actually
    # prevented by acting. Recovery is well below 1.0 because detection
    # happens mid-flow: the money already moved is usually gone, and what an
    # intervention protects is the remaining flow.
    value_at_risk_per_ring: float = 1_200_000.0
    recovery_rate: float = 0.35

    # --- residual harm on a false positive ----------------------------------
    # The share of false positives where a human approves an action against a
    # legitimate account, and what that costs in merchant harm and remediation.
    # The human gate makes this small; it does not make it zero.
    analyst_false_approval_rate: float = 0.05
    harm_per_wrong_action: float = 25_000.0

    sources: dict = field(default_factory=dict)

    # --- derived -------------------------------------------------------------

    @property
    def review_cost(self) -> float:
        """Analyst cost of working one case, true or false."""
        return self.analyst_cost_per_hour * (self.analyst_minutes_per_case / 60.0)

    @property
    def benefit_per_true_positive(self) -> float:
        return self.value_at_risk_per_ring * self.recovery_rate

    @property
    def harm_per_false_positive(self) -> float:
        """Expected residual harm from one false positive, after the gate."""
        return self.analyst_false_approval_rate * self.harm_per_wrong_action

    def net_benefit_per_case(self, precision: float) -> float:
        """Expected value of reviewing one case at the given precision.

        Positive means the review pays for itself in expectation.
        """
        _check_precision(precision)
        return (precision * self.benefit_per_true_positive
                - self.review_cost
                - (1.0 - precision) * self.harm_per_false_positive)

    def break_even_precision(self) -> float:
        """The precision at which reviewing a case breaks even.

        Solving `net_benefit_per_case(p) == 0`:

            p * B = R + (1 - p) * H
            p     = (R + H) / (B + H)

        where B is the benefit of a true positive, R the review cost and H the
        residual harm of a false positive. Returns `inf` when the denominator
        is zero -- a queue with no upside never breaks even, and reporting
        that as 1.0 would imply a perfect detector would suffice.
        """
        numerator = self.review_cost + self.harm_per_false_positive
        denominator = self.benefit_per_true_positive + self.harm_per_false_positive
        if denominator <= 0:
            return float("inf")
        return numerator / denominator

    def required_value_at_risk(self, precision: float) -> float:
        """The exposure per ring at which a queue of this precision breaks even.

        This is `break_even_precision` inverted, and it is the more useful
        direction. The break-even precision depends on `value_at_risk_per_ring`,
        which is the least knowable input in the model; this instead *solves*
        for it, turning "here are some placeholder rupee figures" into a claim
        that stands on its own:

            working the top k pays as long as the average confirmed ring has
            more than X at risk

        Nobody has to accept an assumed ring value to check that. They only
        have to decide whether X is plausible, which is a question an ops lead
        can actually answer.

        Solving `net_benefit_per_case(p) == 0` for the value:

            p * V * r = R + (1 - p) * H   =>   V = (R + (1-p) H) / (p r)

        Returns `inf` at zero precision or zero recovery -- no exposure makes
        a queue that never finds anything worth working.
        """
        _check_precision(precision)
        denominator = precision * self.recovery_rate
        if denominator <= 0:
            return float("inf")
        return (self.review_cost
                + (1.0 - precision) * self.harm_per_false_positive) / denominator

    def unsourced(self) -> list[str]:
        """Inputs with no recorded provenance. Print this next to any result."""
        fields = ("analyst_minutes_per_case", "analyst_cost_per_hour",
                  "value_at_risk_per_ring", "recovery_rate",
                  "analyst_false_approval_rate", "harm_per_wrong_action")
        return [f for f in fields
                if not self.sources.get(f) or self.sources[f] == UNSOURCED]

    def to_dict(self) -> dict:
        return {
            "analyst_minutes_per_case": self.analyst_minutes_per_case,
            "analyst_cost_per_hour": self.analyst_cost_per_hour,
            "value_at_risk_per_ring": self.value_at_risk_per_ring,
            "recovery_rate": self.recovery_rate,
            "analyst_false_approval_rate": self.analyst_false_approval_rate,
            "harm_per_wrong_action": self.harm_per_wrong_action,
            "review_cost": self.review_cost,
            "benefit_per_true_positive": self.benefit_per_true_positive,
            "harm_per_false_positive": self.harm_per_false_positive,
            "break_even_precision": self.break_even_precision(),
            "sources": dict(self.sources),
            "unsourced": self.unsourced(),
        }


def _check_precision(p: float) -> None:
    if not 0.0 <= p <= 1.0:
        raise ValueError(f"precision must be in [0, 1], got {p!r}")


# --- queue-level evaluation --------------------------------------------------

@dataclass
class QueuePoint:
    k: int
    precision: float
    net_benefit_per_case: float
    total_net_benefit: float
    above_break_even: bool

    def to_dict(self) -> dict:
        return {"k": self.k, "precision": self.precision,
                "net_benefit_per_case": self.net_benefit_per_case,
                "total_net_benefit": self.total_net_benefit,
                "above_break_even": self.above_break_even}


def evaluate_queue(precision_at_k: dict[int, float],
                   model: CostModel) -> list[QueuePoint]:
    """Cost-evaluate a queue from its measured precision at each depth.

    `precision_at_k[k]` is precision over the *top k*, which is what
    `scripts/eval_phase2.py` reports. Total net benefit is therefore
    `k * net_benefit_per_case(p@k)` -- the value of working the whole top k,
    not of the k-th case alone.
    """
    points = []
    for k in sorted(precision_at_k):
        p = precision_at_k[k]
        per_case = model.net_benefit_per_case(p)
        points.append(QueuePoint(k=k, precision=p,
                                 net_benefit_per_case=per_case,
                                 total_net_benefit=per_case * k,
                                 above_break_even=per_case > 0))
    return points


def optimal_k(precision_at_k: dict[int, float],
              model: CostModel) -> int | None:
    """The queue depth with the highest total net benefit.

    Returns None when no depth is net-positive, rather than the
    least-bad depth. "Work the top 10, it loses least" is not a
    recommendation, and returning a number there would read as one.
    """
    points = [p for p in evaluate_queue(precision_at_k, model)
              if p.total_net_benefit > 0]
    if not points:
        return None
    return max(points, key=lambda p: p.total_net_benefit).k


# --- sensitivity --------------------------------------------------------------

def sensitivity(model: CostModel, factors=(0.5, 1.0, 2.0)) -> dict:
    """How far the break-even precision moves when each input is scaled.

    The inputs are uncertain, so a single break-even number is a point
    estimate of a quantity nobody has measured. This is the honest companion
    to it: if the break-even holds across an order of magnitude of an input,
    the conclusion does not depend on that input's exact value.
    """
    varied = ("analyst_minutes_per_case", "analyst_cost_per_hour",
              "value_at_risk_per_ring", "recovery_rate",
              "analyst_false_approval_rate", "harm_per_wrong_action")
    out: dict[str, dict[float, float]] = {}
    for name in varied:
        base = getattr(model, name)
        row = {}
        for factor in factors:
            value = base * factor
            # recovery_rate is a probability; scaling past 1.0 is meaningless.
            if name in ("recovery_rate", "analyst_false_approval_rate"):
                value = min(1.0, value)
            row[factor] = replace(model, **{name: value}).break_even_precision()
        out[name] = row
    return out


# The six inputs `sensitivity` varies, and the direction that makes each one
# worse for the queue: costs up, benefits down.
ADVERSE_DIRECTION = {
    "analyst_minutes_per_case": "up",
    "analyst_cost_per_hour": "up",
    "value_at_risk_per_ring": "down",
    "recovery_rate": "down",
    "analyst_false_approval_rate": "up",
    "harm_per_wrong_action": "up",
}


def joint_adverse(model: CostModel, factor: float = 2.0) -> CostModel:
    """All six inputs moved the wrong way at once.

    `sensitivity` moves one input at a time, which understates the risk: the
    inputs are placeholders, so there is no reason their errors would be
    independent or offsetting. This is the pessimistic corner of the box --
    review costs doubled, benefit halved, false-positive harm doubled -- and
    it is the stress the break-even should be quoted against when someone
    asks what happens if the guesses are all wrong together.
    """
    if factor < 1.0:
        raise ValueError("factor is a severity multiplier and must be >= 1.0")
    changes = {}
    for name, direction in ADVERSE_DIRECTION.items():
        base = getattr(model, name)
        value = base * factor if direction == "up" else base / factor
        # Only an upward move can push a probability past 1.0; dividing one
        # never can, so the clamp is scoped to the direction that needs it.
        if direction == "up" and name in ("recovery_rate",
                                          "analyst_false_approval_rate"):
            value = min(1.0, value)
        changes[name] = value
    return replace(model, **changes)
