"""Reporting contracts: the standing rules, as things the code cannot violate.

`docs/STANDING-RULES.md` states seven rules this project reports under. Four of
them are about what must travel beside a number, and all four are enforced
here rather than in review:

  rule 2  p@k carries its size baseline
  rule 3  ring-unit metrics carry their conditioning banner
  rule 4  Elliptic2 p@k carries prevalence
  rule 5  an interval names its clustering

Rule 1 -- never state a number that has not been measured -- is enforced
negatively: nothing in this package computes, defaults, or infers a value.

This package must stay importable from every measured path, so it takes no
dependency outside the standard library (rule 6, tests/test_import_boundaries.py).
"""
from sentinel.report.metric import (CI_METHODS, PREVALENCE_REQUIRED_DATASETS,
                                    Metric, MetricContractError)
from sentinel.report.store import SCHEMA_VERSION, read, write

__all__ = ["CI_METHODS", "PREVALENCE_REQUIRED_DATASETS", "Metric",
           "MetricContractError", "SCHEMA_VERSION", "read", "write"]
