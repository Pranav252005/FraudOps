# Standing rules

Seven rules this project reports under. Each one exists because it was broken
at least once, and each says where it is enforced — because a rule that nothing
checks is how the next overclaim gets written.

**Enforcement status is stated honestly, including where it is thin.** Rules 1
and 7 are only partially mechanised, and that is recorded rather than rounded up.

| # | rule | enforced by |
|---:|---|---|
| 1 | Never state a number that has not been measured | *partial, ratcheted* — `sentinel/report/` cannot invent a value; `tests/test_prose_literals.py` holds the 1,636 unmarked prose literals to a count that may fall and never rise |
| 2 | Always quote p@k beside its size baseline | `sentinel/report/metric.py`, `tests/test_standing_rules.py::TestRule2SizeBaseline` |
| 3 | Print the conditioning banner on every ring-unit metric | `sentinel/report/metric.py`, `tests/test_standing_rules.py::TestRule3ConditioningBanner` |
| 4 | Report prevalence beside any Elliptic2 p@k | `sentinel/report/metric.py`, `tests/test_standing_rules.py::TestRule4Prevalence` |
| 5 | Cluster the bootstrap on the unit the trials are nested in; where they nest in rings, report the wider of the two | `sentinel/report/metric.py`, `scripts/eval_ring_unit.py::interval`, `tests/test_standing_rules.py::TestRule5IntervalNamesItsClustering` |
| 6 | Keep `sentinel.llm` out of every measured path | `tests/test_import_boundaries.py` (runtime, subprocess, transitive) **and** `tests/test_measured_path_closure.py` (static AST walk from every `scripts/eval_*.py` and `ci_gates.py`, plus a ban on computed dynamic imports); both carry a negative control |
| 7 | Record negative results; never delete them | `docs/negative-results/`, `tests/test_standing_rules.py::TestRule7NegativeResultsAreAppendOnly` |

---

## Rule 5 was restated, and the original form was wrong

**It previously read: "Use ring-clustered bootstrap, never cycle-clustered."**
That is wrong as a universal, and adopting it literally would have changed the
resampling unit of every interval in the repository.

### Why

Two different metrics are being conflated.

**For p@k, the cycle is the correct cluster.** p@k is *defined* per generation
cycle — one query, one ranked list, one precision. Candidates within a cycle are
not independent (they come from the same window of active rings), which is why
`sentinel/eval/bootstrap.py` resamples whole cycles rather than candidates. But
p@k trials are not nested within rings at all, so there is nothing to
ring-cluster. Ring-clustering p@k is not a stricter version of the same thing;
it is undefined.

**For the ring-unit metric, the ring is the correct cluster — and the obvious
choice is the wrong one.** `scripts/eval_ring_unit.py` measures
P(ring surfaces in the top k of its own cycle | the ring was BUILT), which has
145 Bernoulli trials against the cycle unit's 18. Those 145 trials come from
only **68 distinct rings**: a ring recurs across cycles, so resampling cycles
handles within-cycle correlation and leaves repeated measures on the same ring
uncorrected.

Measured on the shipped blend:

| clustering | interval width |
|---|---:|
| cycle-clustered | 0.0396 |
| ring-clustered | **0.0890** |

**More than twice as wide.** Reporting the narrower one would be a confidently
narrower wrong answer.

### The rule, as it now stands

> **Cluster on the unit the trials are nested in. Where trials are nested within
> rings, compute both clusterings and report the WIDER interval. Every reported
> interval must name its clustering method; a bare "bootstrap" is not an
> interval that has been reported.**

The last clause is the mechanised part: `Metric` refuses any `ci_method` outside
`{cycle_clustered_bootstrap, ring_clustered_bootstrap,
wider_of_cycle_and_ring_clustered_bootstrap}`.

Note what the restatement does **not** do. It does not license picking whichever
clustering is convenient — where both are defined, the wider one is reported,
which is the direction that costs the project something.

---

## Rule 1 is only partially enforced, and by how much

`sentinel/report/` enforces rule 1 negatively: no code path in it computes,
defaults, or infers a value, so a number cannot be created by the reporting
layer. That covers numbers going *out*.

It does **not** yet cover the metric-shaped literals already sitting in prose
across README and `docs/`. The Phase 0 inventory counted **1,699** across prose
and code (`docs/inventory/metric_literals.csv`); the prose-only scanner in
`sentinel/report/literals.py` counts **1,636**. `0.2778` alone appeared 40
times, and had already gone stale twice while the sentences around it stayed
put:

<!-- historical: measured at commit unknown, 2026-08-31 -->
the supervised p@10 was written as 0.2778, was 0.2500 by the time the blend
weights were fixed, and is 0.2111 after the dead query groups were closed.
(The first of those three predates a reliable commit attribution, hence
`unknown` — an auditable admission rather than an invented sha.)

Three of those were in **code that printed them into results on every run**, and
have been removed rather than updated: `scripts/eval_oracle.py`'s `LABEL_TAX`
constant (stored verbatim in `data/eval_oracle.json`), `scripts/eval_ranker.py`'s
module docstring, and `sentinel/corpus/__init__.py`'s. In each case the
surrounding claim was true and only the digits rotted, so the digits came out
and the claim is now checked live — see `tests/test_two_file_agreement.py`.

What exists today is a **ratchet, not a property**:
`tests/test_prose_literals.py` records the count and fails if it rises, plus a
strict-xfail test for the goal state that will fail the build the day it starts
passing. Closing it properly is Phase 4 — README becomes a template rendered
from a metrics file, and the only literals left are ones carrying

    <!-- historical: measured at commit <sha|unknown>, <YYYY-MM-DD> -->

Until then, rule 1 is a practice for prose and a property only for numbers that
leave through `sentinel/report/`.

---

## Rule 7 covers deletion, not migration

The append-only test reads the git history of `docs/negative-results/` and fails
if any file was ever deleted. It does **not** yet detect a file being truncated
in place or having its conclusion reversed by edit. Several negative results
also still live only in prose inside long documents; they are listed as such in
`docs/negative-results/README.md` rather than counted as migrated.
