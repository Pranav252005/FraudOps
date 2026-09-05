"""No script may write a result to a path that ignores which split produced it.

WHY THIS EXISTS. `scripts/build_stream.py` wrote to a hardcoded `data/stream`
while reading `DATASET.trans()`, which honours `SENTINEL_DATASET`. Compiling
HI-Medium would have overwritten HI-Small's compiled stream in place, and 27
files read that path unconditionally — every evaluation would then have read
HI-Medium's edges while reporting them under HI-Small's name. No crash.

The same hazard existed one layer out: 30 scripts wrote `data/<name>.json`
with no reference to the split, so running any of them under a second dataset
would have overwritten a committed result of the first. `eval_phase2.py` was
fixed individually when HI-Medium was first evaluated; this closes the rest and
stops it coming back.

The rule: a result path is built with `active_result_path` (or
`Dataset.result_path`), never by concatenating a literal filename onto
`data/`.

**One deliberate exemption.** `dataset_constants.json` aggregates every split
into a single registry on purpose — `derive_dataset_constants.py` merges into
it — so it must NOT be per-split. It is named here rather than silently
skipped, because an unexplained exemption is how the next one gets added.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted((ROOT / "scripts").glob("*.py"))

#: Cross-split by design. See the module docstring.
EXEMPT = {"dataset_constants.json"}

#: `ROOT / "data" / "something.json"` as an AST shape, rather than a regex over
#: source, so a reformatted or line-wrapped expression is still caught.
DATA_DIR_NAMES = {"data"}


def _literal_data_paths(tree: ast.AST) -> list[tuple[int, str]]:
    """Every `<anything> / "data" / "<file>.json|csv"` division chain."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        # right-hand side must be a literal result filename
        rhs = node.right
        if not (isinstance(rhs, ast.Constant) and isinstance(rhs.value, str)):
            continue
        if not re.fullmatch(r"[\w\-]+\.(json|csv)", rhs.value):
            continue
        # left-hand side must itself end in / "data"
        lhs = node.left
        if (isinstance(lhs, ast.BinOp) and isinstance(lhs.op, ast.Div)
                and isinstance(lhs.right, ast.Constant)
                and lhs.right.value in DATA_DIR_NAMES):
            found.append((node.lineno, rhs.value))
    return found


def test_the_script_list_is_not_empty():
    assert len(SCRIPTS) >= 20, [p.name for p in SCRIPTS]


@pytest.mark.parametrize("path", SCRIPTS, ids=[p.name for p in SCRIPTS])
def test_no_script_hardcodes_a_result_path(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    offenders = [(ln, fn) for ln, fn in _literal_data_paths(tree)
                 if fn not in EXEMPT]
    assert not offenders, (
        f"{path.name} builds a result path from a literal filename at "
        f"{offenders}. Use active_result_path(ROOT, <filename>) so running "
        f"under SENTINEL_DATASET=<other split> cannot overwrite HI-Small's "
        f"committed result and report one split's numbers under another's "
        f"filename.")


def test_the_exemption_is_exactly_the_cross_split_registry():
    """An allowlist has two failure modes: too wide, and dead.

    Asserting its contents makes any widening a reviewed line in a diff, and
    asserting that the exempt file is still built the exempt way stops the
    entry outliving its reason.
    """
    assert EXEMPT == {"dataset_constants.json"}
    src = (ROOT / "scripts" / "derive_dataset_constants.py")
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))
    assert any(fn == "dataset_constants.json"
               for _, fn in _literal_data_paths(tree)), (
        "the exemption is dead -- derive_dataset_constants.py no longer builds "
        "that path literally, so the entry should be deleted")


def test_the_check_would_catch_the_defect_it_was_written_for():
    """The negative control. Reconstructs the exact original shape."""
    tree = ast.parse('OUT = ROOT / "data" / "eval_phase2.json"\n')
    assert _literal_data_paths(tree) == [(1, "eval_phase2.json")]


def test_the_check_accepts_the_fixed_form():
    """The other arm: it must not fire on the correct call, or it is a ban."""
    tree = ast.parse('OUT = active_result_path(ROOT, "eval_phase2.json")\n')
    assert _literal_data_paths(tree) == []


def test_reading_a_result_is_covered_too():
    """Reads matter as much as writes.

    `eval_cost.py` reads eval_phase2.json for its precision and
    `eval_seeding_prize.py` reads eval_oracle.json. Under a second split those
    must read that split's result, not HI-Small's, or the cost model would be
    conditioned on one dataset while claiming another.
    """
    for name in ("eval_cost.py", "eval_seeding_prize.py"):
        src = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "active_result_path" in src, name
