"""Render every `*.template.md` against results/metrics.json.

The rendered files are BUILD ARTEFACTS. Edit the template, then run:

    python scripts/collect_metrics.py    # re-read the eval artefacts
    python scripts/render_docs.py        # re-render everything

`tests/test_readme_render.py` fails the build if a rendered file drifts from a
fresh render of its template, which is what stops these files from quietly
becoming places a number can be wrong again.

Nothing is written if ANY template fails to render. A partial render would
leave some files fresh and some stale, which is a worse state than either.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.report.render import RenderError, render_file

ROOT = Path(__file__).resolve().parent.parent
METRICS = ROOT / "results" / "metrics.json"


def templates() -> list[Path]:
    found = sorted(ROOT.glob("*.template.md"))
    found += sorted((ROOT / "docs").rglob("*.template.md"))
    return found


def main() -> int:
    if not METRICS.exists():
        print(f"missing {METRICS.relative_to(ROOT)}; "
              f"run scripts/collect_metrics.py first")
        return 1

    found = templates()
    if not found:
        print("no *.template.md files found")
        return 1

    # Render everything to memory first, so one failure does not leave half
    # the documentation regenerated and half stale.
    from sentinel.report.render import render_text
    from sentinel.report.store import read
    import json

    payload = json.loads(METRICS.read_text(encoding="utf-8"))
    metrics = read(METRICS)
    counts = payload.get("counts", {})

    staged: list[tuple[Path, str]] = []
    for t in found:
        out = t.with_name(t.name.replace(".template.md", ".md"))
        try:
            render_text(t.read_text(encoding="utf-8"), metrics, counts)
        except RenderError as exc:
            print(f"render failed for {t.relative_to(ROOT)}:\n  {exc}")
            print("\nNothing was written. A document that renders with a hole "
                  "in it ships the hole, so this refuses rather than "
                  "degrading.")
            return 1
        staged.append((t, out))

    for t, out in staged:
        render_file(t, METRICS, out)
        print(f"rendered {out.relative_to(ROOT)}  <- {t.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
