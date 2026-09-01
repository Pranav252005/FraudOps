#!/usr/bin/env bash
#
# Everything in this repository that can be checked WITHOUT the AMLworld
# download. It is the honest answer to "what can I run right now", and it is
# separated from the evaluation commands for a reason: `data/` is 1.6 GB and
# untracked, so a reader who pasted the eval commands first would hit a missing
# file and conclude the repository does not run.
#
# What this does NOT do: it does not recompute any headline. The headlines live
# in results/metrics.json, which is committed, and step 3 checks that the
# committed documents are a faithful rendering of it. Recomputing them needs
# the benchmark -- see the AMLworld section of the README.
#
#   ./scripts/reproduce_clean.sh
#
set -euo pipefail

cd "$(dirname "$0")/.."

PY="${PYTHON:-python}"

echo "=============================================================="
echo " 1/4  test suite"
echo "=============================================================="
echo "The count is not asserted here; the run is the authority."
"$PY" -m pytest -q

echo
echo "=============================================================="
echo " 2/4  the four gates a green suite would not catch"
echo "=============================================================="
echo "determinism, baseline re-tie, metric regression, unsourced cost."
echo "The cost gate PASSES and prints the joint corner it does not gate on."
"$PY" scripts/ci_gates.py all

echo
echo "=============================================================="
echo " 3/4  the committed documents match a fresh render"
echo "=============================================================="
echo "README.md and docs/SUBMISSION.md are rendered from"
echo "results/metrics.json. This re-renders them and fails if the"
echo "committed files differ -- so a number cannot have been edited in."
"$PY" -m pytest tests/test_readme_render.py tests/test_prose_literals.py -q

echo
echo "=============================================================="
echo " 4/4  a case file, rendered end to end"
echo "=============================================================="
echo "An identity case file, a merchant brief, and -- if the compiled"
echo "AMLworld stream is present -- an AMLworld STR narrative. All three"
echo "verified by the same citation verifier."
"$PY" scripts/demo_case_files.py

echo
echo "=============================================================="
echo " done"
echo "=============================================================="
echo "Nothing above recomputed a headline. To do that you need the"
echo "AMLworld HI-Small download; see 'With the AMLworld benchmark' in"
echo "the README."
