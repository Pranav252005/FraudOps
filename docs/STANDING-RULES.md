# Standing rules

Seven rules this project reports under. Each one exists because it was broken
at least once, and each says where it is enforced — because a rule that nothing
checks is how the next overclaim gets written.

**Enforcement status is stated honestly, including where it is thin.** Rules 1
and 7 are only partially mechanised, and that is recorded rather than rounded up.

| # | rule | enforced by |
|---:|---|---|
| 1 | Never state a number that has not been measured | *partial* — `sentinel/report/` cannot invent a value; the prose literal scan is not yet written |
| 2 | Always quote p@k beside its size baseline | `sentinel/report/metric.py`, `tests/test_standing_rules.py::TestRule2SizeBaseline` |
| 3 | Print the conditioning banner on every ring-unit metric | `sentinel/report/metric.py`, `tests/test_standing_rules.py::TestRule3ConditioningBanner` |
| 4 | Report prevalence beside any Elliptic2 p@k | `sentinel/report/metric.py`, `tests/test_standing_rules.py::TestRule4Prevalence` |
| 5 | Cluster the bootstrap on the unit the trials are nested in; where they nest in rings, report the wider of the two | `sentinel/report/metric.py`, `scripts/eval_ring_unit.py::interval`, `tests/test_standing_rules.py::TestRule5IntervalNamesItsClustering` |
| 6 | Keep `sentinel.llm` out of every measured path | `tests/test_import_boundaries.py` (transitive, in a subprocess, with a negative control) |
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

It does **not** cover the 1,699 metric-shaped literals already sitting in prose
across README and `docs/` (`docs/inventory/metric_literals.csv`). `0.2778` alone
appears 40 times. Two are known to be wrong right now:

- `scripts/eval_oracle.py`'s `LABEL_TAX` constant asserts
  "`scripts/eval_ranker.py` reaches 0.2778", printed every run and stored in
  `data/eval_oracle.json`. The live value is different.
- README's correction block at lines 186–197 states that
  `data/eval_oracle.json` "is deliberately not re-run". It has been re-run, and
  the block's numbers came from a cached, stale pool.

The scan that would close this is Phase 4 work and is **not written**. Until it
is, rule 1 is a practice, not a property.

---

## Rule 7 covers deletion, not migration

The append-only test reads the git history of `docs/negative-results/` and fails
if any file was ever deleted. It does **not** yet detect a file being truncated
in place or having its conclusion reversed by edit. Several negative results
also still live only in prose inside long documents; they are listed as such in
`docs/negative-results/README.md` rather than counted as migrated.
