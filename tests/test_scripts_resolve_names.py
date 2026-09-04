"""Every script's module-level names must actually be defined.

WHY THIS EXISTS. The dataset-switching work introduced `DATASET` into seven
scripts and defined it in none of them. `scripts/build_stream.py`,
`eval_funnel.py`, `eval_oracle.py`, `bench_cycle.py`, `build_queue.py`,
`diagnose_build.py` and `eval_fragmentation.py` all raised `NameError` on the
first call that touched it — including two of this project's most important
evaluations — and nobody noticed for weeks, because the compiled stream already
existed and their committed JSON outputs predate the breakage.

Nothing caught it. The scripts are not imported by the test suite (they read
multi-gigabyte CSVs and run for hours), so a plain import test is not an option
and a NameError can sit in `main()` indefinitely.

This is a static check instead: walk each script's AST and assert that every
name it *loads* is defined somewhere it could plausibly come from — a binding
in the module, an import, a builtin, or a local. It is deliberately
conservative: it reports only names that are loaded at module scope or in a
function while being bound nowhere at all, which is the exact shape of the
`DATASET` defect.

**Stated limitation.** This is not a type checker and does not attempt scope
analysis. It cannot catch a name that is bound on one branch and read on
another, or an attribute that does not exist. It catches "referenced and never
bound anywhere", which is what actually happened.
"""
from __future__ import annotations

import ast
import builtins
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = sorted((ROOT / "scripts").glob("*.py"))
BUILTINS = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__"}


def _bound_names(tree: ast.AST) -> set[str]:
    """Every name this module binds, anywhere, by any mechanism."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                out.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef)):
            out.add(node.name)
            args = getattr(node, "args", None)
            if args is not None:
                for a in (args.posonlyargs + args.args + args.kwonlyargs):
                    out.add(a.arg)
                for a in (args.vararg, args.kwarg):
                    if a is not None:
                        out.add(a.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store,
                                                                  ast.Del)):
            out.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            out.update(node.names)
        elif isinstance(node, ast.Lambda):
            a = node.args
            for x in (a.posonlyargs + a.args + a.kwonlyargs):
                out.add(x.arg)
        elif isinstance(node, (ast.comprehension,)):
            for n in ast.walk(node.target):
                if isinstance(n, ast.Name):
                    out.add(n.id)
        elif isinstance(node, ast.MatchAs) and node.name:
            out.add(node.name)
    return out


def _loaded_names(tree: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(tree)
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}


def test_the_script_list_is_not_empty():
    """A parametrised test over an empty glob passes vacuously."""
    assert len(SCRIPTS) >= 20, [p.name for p in SCRIPTS]


@pytest.mark.parametrize("path", SCRIPTS, ids=[p.name for p in SCRIPTS])
def test_every_loaded_name_is_bound_somewhere(path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    unbound = sorted(_loaded_names(tree) - _bound_names(tree) - BUILTINS)
    assert not unbound, (
        f"{path.name} loads {unbound} but binds them nowhere. This is the "
        f"`DATASET` defect: seven scripts referenced it without defining it "
        f"and raised NameError on first use, including eval_funnel.py and "
        f"eval_oracle.py, for weeks.")


def test_the_check_would_catch_the_defect_it_was_written_for():
    """The negative control. A check that cannot fail is not evidence.

    Reconstructs the exact shape of the original bug: a module that imports
    the dataset helper under one name and then uses `DATASET`.
    """
    src = (
        "from sentinel.data.datasets import active as _active_dataset\n"
        "rings = DATASET.patterns('x')\n"
    )
    tree = ast.parse(src)
    unbound = _loaded_names(tree) - _bound_names(tree) - BUILTINS
    assert "DATASET" in unbound


def test_the_check_does_not_fire_on_a_correct_module():
    """The other arm: it must accept the fixed form, or it is just a ban."""
    src = (
        "from sentinel.data.datasets import active as _active_dataset\n"
        "DATASET = _active_dataset()\n"
        "rings = DATASET.patterns('x')\n"
    )
    tree = ast.parse(src)
    assert not (_loaded_names(tree) - _bound_names(tree) - BUILTINS)
