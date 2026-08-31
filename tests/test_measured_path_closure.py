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
