"""One reported metric, with the things that must travel beside it.

Every rule enforced here was previously a convention, and each one has already
been broken at least once in this repository's history:

  * a p@k quoted without its size baseline (docs/HANDOFF.md 5e -- the "size
    beats score" claim that did not survive its own CI);
  * a ring-unit number quoted without its conditioning, which reads HIGHER
    than the unconditioned p@k and is not comparable to it
    (scripts/eval_ring_unit.py's banner exists because of that);
  * a ratio quoted without the absolute values it is a ratio of, and over two
    different denominators (docs/ARCHITECTURE_UPLIFT.md item 0.2 -- the widely
    quoted "2.8x" that was not a ratio of anything);
  * an interval quoted without its clustering, when the two clusterings differ
    by more than 2x in width on this data.

A convention that has been broken is not a convention. So these are
preconditions on construction: a `Metric` that violates one cannot be built,
and therefore cannot be printed, stored, or rendered into a document. The
failure is a `MetricContractError` at the call site rather than a wrong number
in a README.

WHAT THIS DELIBERATELY DOES NOT DO. It does not compute anything. It carries
numbers that something else measured, and refuses to carry them incompletely.
`value` is never derived, defaulted, or filled in -- there is no code path in
this module that can invent a number, which is the mechanical form of standing
rule 1.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

# The resampling units this project reports over. See `docs/STANDING-RULES.md`
# rule 5 for why the choice is not free and not always "ring".
#
# `world` arrived with the second domain. Unlike AMLworld, the identity
# generator HAS a randomness knob (prereg/cycles.md records that AMLworld's
# measured path has none), so its resampling unit is the generated world.
Unit = Literal["cycle", "ring", "world"]

# Clustering methods that may appear in `ci_method`. A bare "bootstrap" is not
# admissible: the whole finding in scripts/eval_ring_unit.py is that cycle- and
# ring-clustering give materially different widths on this data, so an interval
# that does not say which one it is has not been reported.
CI_METHODS = frozenset({
    "cycle_clustered_bootstrap",
    "ring_clustered_bootstrap",
    "wider_of_cycle_and_ring_clustered_bootstrap",
    # The second domain's units. Admitted deliberately, reversing an earlier
    # decision that is recorded rather than quietly dropped: Phase D kept these
    # OUT of this set, reasoning that refusing to render identity numbers
    # through `Metric` would stop one being mistaken for a candidate-level p@k.
    # That was the wrong guard in the wrong place. What distinguishes a coverage
    # number from a p@k is `unit` and `dataset`, both of which travel with the
    # metric and are printed beside it -- while the exclusion pushed identity
    # numbers OUT of the rendered path and into hand-typed prose, which is the
    # failure rule 1 exists to prevent. The guard should make the honest path
    # easy, not closed.
    "world_clustered_bootstrap",
    "paired_world_clustered_bootstrap",
})

# Datasets for which standing rule 4 requires prevalence beside any p@k.
#
# `synthetic-identity-v1` is added because prevalence there is a GENERATOR
# PARAMETER. A number from a constructed population whose positive rate was
# chosen is uninterpretable without saying what it was chosen to be.
PREVALENCE_REQUIRED_DATASETS = frozenset({"elliptic2", "synthetic-identity-v1"})

# Units whose metrics must carry a conditioning banner. Every unit except the
# cycle: a cycle-unit p@k is measured over whatever the cycle contained, while
# ring-, cluster- and world-unit numbers in this project are all conditioned on
# something (BUILT, or "the group had at least one seeded member") that changes
# what the number means.
CONDITIONING_REQUIRED_UNITS = frozenset({"ring", "world"})


class MetricContractError(ValueError):
    """A metric was constructed without something that must travel with it."""


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) \
        and not math.isnan(x)


@dataclass(frozen=True)
class Metric:
    """A reported number and its mandatory context.

    Required of every metric:
      `id`, `value`, `n_units`, `unit`, `ci_lower`, `ci_upper`, `ci_method`.

    Required conditionally:
      `size_baseline`  -- whenever the metric is a p@k (rule 2)
      `prevalence`     -- whenever the dataset is one of
                          PREVALENCE_REQUIRED_DATASETS (rule 4)
      `conditioning`   -- whenever `unit == "ring"` (rule 3)

    `conditioning` is a POSITIONAL-CAPABLE required field for ring-unit
    metrics rather than an optional keyword with a default. That is the
    difference between a banner the caller may forget and a banner the caller
    cannot omit, and it is the specific thing standing rule 3 asks for.
    """

    id: str
    value: float
    n_units: int
    unit: Unit
    ci_lower: float
    ci_upper: float
    ci_method: str

    dataset: str = "amlworld-hi-small"
    k: int | None = None
    size_baseline: float | None = None
    prevalence: float | None = None
    conditioning: str | None = None
    # Free-form provenance. Not validated beyond being present-if-supplied,
    # because over-specifying it would push callers toward inventing values to
    # satisfy the schema -- the opposite of what this class is for.
    source: str | None = None
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.id or not isinstance(self.id, str):
            raise MetricContractError("a metric needs a stable string id")
        if not _is_number(self.value):
            raise MetricContractError(
                f"{self.id}: value must be a measured number, got "
                f"{self.value!r}. There is no default -- rule 1.")

        # --- the interval, and what produced it -----------------------------
        for name in ("ci_lower", "ci_upper"):
            if not _is_number(getattr(self, name)):
                raise MetricContractError(
                    f"{self.id}: {name} is required. A point estimate on this "
                    f"dataset moves by roughly +/-0.05 of the metric for a "
                    f"single ring; quoting one without an interval is close to "
                    f"meaningless (sentinel/eval/bootstrap.py).")
        if self.ci_lower > self.ci_upper:
            raise MetricContractError(
                f"{self.id}: ci_lower {self.ci_lower} exceeds ci_upper "
                f"{self.ci_upper}")
        if not (self.ci_lower <= self.value <= self.ci_upper):
            raise MetricContractError(
                f"{self.id}: point estimate {self.value} lies outside its own "
                f"interval [{self.ci_lower}, {self.ci_upper}]")
        if self.ci_method not in CI_METHODS:
            raise MetricContractError(
                f"{self.id}: ci_method must be one of {sorted(CI_METHODS)}, "
                f"got {self.ci_method!r}. An interval that does not name its "
                f"clustering has not been reported -- on this data the two "
                f"differ by more than 2x in width (rule 5).")

        if not isinstance(self.n_units, int) or self.n_units <= 0:
            raise MetricContractError(
                f"{self.id}: n_units must be a positive integer, got "
                f"{self.n_units!r}")
        if self.unit not in ("cycle", "ring", "world"):
            raise MetricContractError(
                f"{self.id}: unit must be 'cycle', 'ring' or 'world', got "
                f"{self.unit!r}")

        # --- rule 2: p@k carries its size baseline --------------------------
        if self.is_precision_at_k and not _is_number(self.size_baseline):
            raise MetricContractError(
                f"{self.id}: a p@k must be quoted beside its size baseline "
                f"(rule 2). Node count is the baseline this project's ranking "
                f"claims are re-tied against; a p@k without it does not say "
                f"whether the scorer beat counting nodes.")

        # --- rule 3: non-cycle units carry their conditioning ---------------
        if self.unit in CONDITIONING_REQUIRED_UNITS                 and not (self.conditioning or "").strip():
            raise MetricContractError(
                f"{self.id}: a ring-unit metric must carry its conditioning "
                f"banner (rule 3). This project's ring-unit metric conditions "
                f"on BUILT, where BIPARTITE and STACK are absent "
                f"systematically rather than at random -- so it reads HIGHER "
                f"than the unconditioned p@k and is not comparable to it.")

        # --- rule 4: prevalence beside Elliptic2 p@k ------------------------
        if self.dataset in PREVALENCE_REQUIRED_DATASETS \
                and not _is_number(self.prevalence):
            raise MetricContractError(
                f"{self.id}: dataset {self.dataset!r} requires prevalence "
                f"beside the metric (rule 4).")
        if self.prevalence is not None and not 0.0 <= self.prevalence <= 1.0:
            raise MetricContractError(
                f"{self.id}: prevalence {self.prevalence} is not a proportion")

    @property
    def is_precision_at_k(self) -> bool:
        """True when this metric is a precision-at-k.

        Keyed on `k` being set rather than on the id matching a pattern: an id
        is a label a caller chooses and can spell around, while `k` is the
        parameter that makes the number a p@k in the first place.
        """
        return self.k is not None

    @property
    def ci_width(self) -> float:
        return self.ci_upper - self.ci_lower

    def to_dict(self) -> dict:
        d = {
            "id": self.id, "value": self.value, "unit": self.unit,
            "n_units": self.n_units, "dataset": self.dataset,
            "ci_lower": self.ci_lower, "ci_upper": self.ci_upper,
            "ci_method": self.ci_method,
        }
        for name in ("k", "size_baseline", "prevalence", "conditioning",
                     "source"):
            v = getattr(self, name)
            if v is not None:
                d[name] = v
        if self.notes:
            d["notes"] = list(self.notes)
        return d

    def render(self, width: int = 78) -> str:
        """The metric as text, with everything that must travel beside it.

        There is no `render_without_banner`, no `bare()` and no `__format__`
        shortcut, on purpose: every path out of this object to a human carries
        the full context, so there is nothing to reach for when the full
        version is inconveniently long.
        """
        import textwrap

        head = f"{self.id} = {self.value:.4f}  [{self.ci_lower:.4f}, {self.ci_upper:.4f}]"
        lines = [head, f"  interval: {self.ci_method}, n={self.n_units} {self.unit}s"]
        if self.is_precision_at_k:
            lines.append(f"  k={self.k}   size baseline (node count): "
                         f"{self.size_baseline:.4f}")
        if self.prevalence is not None:
            lines.append(f"  prevalence: {self.prevalence:.6f}")
        lines.append(f"  dataset: {self.dataset}")
        if self.source:
            lines.append(f"  source: {self.source}")
        if self.conditioning:
            lines.append("  CONDITIONING -- read with the number above:")
            for para in self.conditioning.strip().splitlines():
                lines += textwrap.wrap(para, width=width - 4,
                                       initial_indent="    ",
                                       subsequent_indent="    ") or ["    "]
        for note in self.notes:
            lines += textwrap.wrap(note, width=width - 4,
                                   initial_indent="  note: ",
                                   subsequent_indent="        ")
        return "\n".join(lines)
