"""Rule 6, from the ENTRY POINTS rather than from a hand-listed module set.

`tests/test_import_boundaries.py` already checks that eleven named modules do
not transitively pull in `sentinel.llm`, by importing each in a subprocess and
reading `sys.modules`. That is a strong check and it stays. It has one gap: it
tests the modules somebody remembered to list. A script that reaches
`sentinel.llm` through a module nobody added to `BOUNDARIES` passes it.

This file closes that gap from the other end. It starts at every script that
produces a reported number and walks the import graph statically, so the
question answered is "can this entry point reach the LLM", not "does this
module I thought of reach it".

WHY STATIC AND NOT RUNTIME. The runtime check cannot be run over these entry
points: importing `scripts/eval_oracle.py` executes nothing harmful, but the
scripts are also the things that take 15 minutes and need `data/`. A static
walk needs neither, so it can cover all of them on every commit. The two checks
are complementary and neither replaces the other -- static analysis sees
conditional and function-local imports that a single runtime import may not
execute, and the runtime check sees dependencies that only a real import
resolves.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FORBIDDEN = "sentinel.llm"

# Every script that writes a number this project reports. Derived by listing
# scripts/eval_*.py plus the CI gates, then removing the ones that are
# explicitly not measured paths -- each removal justified inline, because an
# unexplained exclusion is how a measured path quietly leaves the list.
MEASURED_ENTRYPOINTS = sorted(
    p for p in (ROOT / "scripts").glob("*.py")
    if (p.name.startswith("eval_") or p.name == "ci_gates.py")
)

# `scripts/check_llm.py` is deliberately absent: it exists to exercise the LLM
# client and is not a measured path. It is used below as the NEGATIVE CONTROL,
# because a boundary test that cannot fail is not evidence -- this project has
# shipped one of those (docs/HANDOFF.md 11b).
NEGATIVE_CONTROL = ROOT / "scripts" / "check_llm.py"


def _first_party_imports(path: Path) -> set[str]:
    """Module names imported by `path`, restricted to this project's packages.

    Uses `ast` rather than a grep so that aliased imports (`import sentinel.llm
    as x`), function-local imports, and imports inside `try`/`if` blocks are all
    caught -- a grep for the literal string would miss the first and a grep for
    the module name would miss nothing but would also match comments.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:            # relative import
                continue
            if node.module:
                found.add(node.module)
                # `from sentinel import llm` names the submodule in `names`.
                for alias in node.names:
                    found.add(f"{node.module}.{alias.name}")
    return {m for m in found if m.split(".")[0] in ("sentinel", "scripts")}


def _module_path(module: str) -> Path | None:
    base = ROOT / Path(*module.split("."))
    for cand in (base.with_suffix(".py"), base / "__init__.py"):
        if cand.is_file():
            return cand
    return None


def _closure(entry: Path) -> set[str]:
    """Every first-party module reachable from `entry`, transitively."""
    seen: set[str] = set()
    stack = list(_first_party_imports(entry))
    while stack:
        mod = stack.pop()
        if mod in seen:
            continue
        seen.add(mod)
        path = _module_path(mod)
        if path is not None:
            stack.extend(_first_party_imports(path) - seen)
    return seen


def test_the_entrypoint_list_is_not_empty():
    """A parametrised test over an empty list passes vacuously."""
    assert len(MEASURED_ENTRYPOINTS) >= 8, MEASURED_ENTRYPOINTS


@pytest.mark.parametrize("entry", MEASURED_ENTRYPOINTS,
                         ids=[p.name for p in MEASURED_ENTRYPOINTS])
def test_no_measured_entrypoint_can_reach_the_llm(entry):
    reachable = _closure(entry)
    bad = sorted(m for m in reachable
                 if m == FORBIDDEN or m.startswith(FORBIDDEN + "."))
    assert not bad, (
        f"{entry.name} can reach {bad} through its import graph. A "
        f"non-deterministic component inside a measured path contaminates "
        f"every interval that path reports. See docs/STANDING-RULES.md rule 6.")


def test_the_walk_would_actually_catch_a_violation():
    """The negative control. Pointed at a script that genuinely does import it.

    Without this, a bug in `_first_party_imports` that returned the empty set
    would make every assertion above pass while checking nothing.
    """
    assert NEGATIVE_CONTROL.is_file(), NEGATIVE_CONTROL
    reachable = _closure(NEGATIVE_CONTROL)
    assert any(m == FORBIDDEN or m.startswith(FORBIDDEN + ".")
               for m in reachable), sorted(reachable)


def test_the_walk_resolves_more_than_one_hop():
    """Transitivity, asserted rather than assumed.

    A one-hop implementation would pass every test above on a codebase where
    no entry point imports the LLM directly -- which is exactly this codebase.
    So the closure must be shown to reach something no entry point imports
    itself.
    """
    entry = ROOT / "scripts" / "eval_oracle.py"
    direct = _first_party_imports(entry)
    closure = _closure(entry)
    assert closure - direct, "the closure found nothing beyond direct imports"
    assert "sentinel.detect.features" in closure
    assert "sentinel.detect.features" not in direct


@pytest.mark.parametrize("entry", MEASURED_ENTRYPOINTS,
                         ids=[p.name for p in MEASURED_ENTRYPOINTS])
def test_no_measured_path_imports_a_computed_module_name(entry):
    """Dynamic imports defeat the static walk, so they are banned outright.

    `importlib.import_module(name)` where `name` is not a literal makes the
    import graph undecidable: the closure above would report a path clean while
    it loads anything at runtime. A literal argument is fine -- it is still
    statically visible -- so only the computed case is refused.
    """
    paths = [entry] + [p for m in _closure(entry)
                       if (p := _module_path(m)) is not None]
    offenders = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = (fn.attr if isinstance(fn, ast.Attribute)
                    else fn.id if isinstance(fn, ast.Name) else None)
            if name not in ("import_module", "__import__"):
                continue
            if node.args and not isinstance(node.args[0], ast.Constant):
                offenders.append(
                    f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, (
        f"computed dynamic import on a measured path: {offenders}. The import "
        f"graph is no longer statically decidable, so rule 6 cannot be "
        f"checked for this entry point.")


# ---------------------------------------------------------------------------
# Rule 8 (proposed): the ground-truth label is not reachable from the detector
# ---------------------------------------------------------------------------
#
# `PairAgg.laundering` is a per-pair count of ground-truth laundering edges. It
# is incremented on every insert and decremented on every expiry, so it rides
# on the live graph -- and `WindowedGraph.subgraph_edges` returns the whole
# aggregate, which `CandidateGenerator.generate` hands to `motifs.detect` and
# `features.build`. Nothing reads it today. Nothing stopped it either, which is
# the same shape of unguarded surface that rule 6 exists for.
#
# WHAT THIS HALF CATCHES AND WHAT IT DOES NOT. A static walk sees a literal
# attribute access and a `getattr` with a constant name. It CANNOT see
# `getattr(agg, "laun" + "dering")`, an alias bound at runtime, or a read
# through `vars()` / `asdict()`. That is not a hole to be apologised for, it is
# the reason `tests/test_label_poison.py` exists: the poison test randomises the
# label and asserts the pipeline's output is bit-identical, which no rename can
# defeat. The two halves are complementary in exactly the way the static and
# runtime import checks above are, and neither replaces the other.

LABEL_ATTR = "laundering"

# `is_laundering` is deliberately NOT in this set at the closure level. It is
# the labelled *column* on the compiled stream, and two callers must read it
# legitimately: `WindowedGraph.add_batch`, which maintains the counter, and the
# evaluation scripts, which need ground truth to score against. Banning it
# repo-wide would ban evaluation. It IS banned inside `sentinel/detect` and
# `sentinel/learn` by the narrower test below, which is where reading it would
# actually be a leak.

# The single module allowed to touch the counter: the graph owns it. Kept as an
# explicit set rather than a path prefix so that widening it is a visible line
# in a diff and has to be argued for in review.
LABEL_OWNERS = frozenset({"sentinel/graph/window.py"})

# Packages that must never see a label under any name. These are the detector
# and the ranker -- everything whose output is a measured number about
# candidates. Evaluation is excluded on purpose; scoring against truth is its
# job.
LABEL_FREE_PACKAGES = ("sentinel/detect/", "sentinel/learn/")


def _label_reads(path: Path, names: frozenset[str]) -> list[str]:
    """Every syntactic reference to a label field in `path`, as 'file:line'.

    Matches attribute access (`agg.laundering`), bare names (the field
    declaration, and any local shadowing it), and `getattr` with a constant
    name -- the three forms that are statically decidable.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(ROOT).as_posix()
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in names:
            out.append(f"{rel}:{node.lineno} ({node.attr})")
        elif isinstance(node, ast.Name) and node.id in names:
            out.append(f"{rel}:{node.lineno} ({node.id})")
        elif (isinstance(node, ast.Call)
              and isinstance(node.func, ast.Name) and node.func.id == "getattr"
              and len(node.args) > 1
              and isinstance(node.args[1], ast.Constant)
              and node.args[1].value in names):
            out.append(f"{rel}:{node.lineno} (getattr {node.args[1].value})")
    return out


def _closure_paths(entry: Path) -> list[Path]:
    return [entry] + [p for m in _closure(entry)
                      if (p := _module_path(m)) is not None]


@pytest.mark.parametrize("entry", MEASURED_ENTRYPOINTS,
                         ids=[p.name for p in MEASURED_ENTRYPOINTS])
def test_no_measured_entrypoint_reads_the_pair_label(entry):
    """`PairAgg.laundering` is unreachable from every measured entry point."""
    offenders: list[str] = []
    for path in _closure_paths(entry):
        if path.relative_to(ROOT).as_posix() in LABEL_OWNERS:
            continue
        offenders += _label_reads(path, frozenset({LABEL_ATTR}))
    assert not offenders, (
        f"{entry.name} can reach the ground-truth label at {offenders}. A "
        f"feature computed from `PairAgg.laundering` is a perfect detector "
        f"with a green test suite. See docs/EXPERIMENT-QUEUE.md L1 and "
        f".claude/skills/payops-invariants/SKILL.md rule 8.")


def test_the_detector_and_ranker_see_no_label_under_any_name():
    """Narrower and stricter: `sentinel/detect` and `sentinel/learn` may not
    mention `laundering` OR `is_laundering`.

    The closure test above cannot ban `is_laundering` globally, because
    `add_batch` and every eval script read it legitimately. Here it can be
    banned outright, because nothing in these two packages has any business
    knowing the answer.
    """
    names = frozenset({LABEL_ATTR, "is_" + LABEL_ATTR})
    offenders: list[str] = []
    checked = 0
    for pkg in LABEL_FREE_PACKAGES:
        for path in sorted((ROOT / pkg).glob("*.py")):
            checked += 1
            offenders += _label_reads(path, names)
    assert checked >= 8, f"only {checked} modules scanned; glob is wrong"
    assert not offenders, (
        f"the detector or ranker references a ground-truth label: {offenders}")


def test_the_label_walk_would_actually_catch_a_violation():
    """The negative control. A check that cannot fail is not evidence.

    `tests/test_phase1.py` asserts on `agg.laundering` directly -- it is the
    one place in the repository that legitimately reads the counter, because
    its job is to verify the counter is maintained. That makes it the natural
    positive sample for the detector.
    """
    control = ROOT / "tests" / "test_phase1.py"
    assert control.is_file(), control
    found = _label_reads(control, frozenset({LABEL_ATTR}))
    assert found, (
        "the label walk found nothing in a file that demonstrably reads "
        "`agg.laundering`; the detector is broken and every assertion above "
        "is passing vacuously")


def test_the_owner_allowlist_is_load_bearing_and_minimal():
    """Two things at once, because an allowlist has two failure modes.

    Too wide: it silently exempts a module that should be checked. Asserting
    the exact contents makes any widening a reviewed line in a diff.

    Dead: if the owner did not actually read the label, the exemption would be
    protecting nothing, and a reader would wrongly believe it was doing work.
    """
    assert LABEL_OWNERS == frozenset({"sentinel/graph/window.py"})
    owner = ROOT / "sentinel" / "graph" / "window.py"
    assert _label_reads(owner, frozenset({LABEL_ATTR})), (
        "the allowlisted owner does not read the label, so the exemption is "
        "dead weight and should be deleted")


def test_the_label_closure_actually_covers_the_graph_module():
    """Transitivity for this walk specifically.

    The parametrised test above passes trivially if the closure never reaches
    `sentinel.graph.window` at all -- in which case it is checking nothing
    about the module that owns the label. Assert the reach directly.
    """
    entry = ROOT / "scripts" / "eval_funnel.py"
    assert "sentinel.graph.window" in _closure(entry)
