"""Render README.md from README.template.md and results/metrics.json.

README.md is a BUILD ARTEFACT. Edit `README.template.md`, then run this.

    python scripts/collect_metrics.py    # re-read the eval artefacts
    python scripts/render_readme.py      # re-render

`tests/test_readme_render.py::test_the_committed_readme_matches_a_fresh_render`
fails the build if the two drift apart, which is what stops README.md from
quietly becoming a place a number can be wrong again.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.report.render import RenderError, render_file

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    try:
        out = render_file(ROOT / "README.template.md",
                          ROOT / "results" / "metrics.json",
                          ROOT / "README.md")
    except RenderError as exc:
        print(f"render failed: {exc}")
        print("\nNothing was written. A README that renders with a hole in it "
              "ships the hole, so this refuses rather than degrading.")
        return 1
    print(f"rendered {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
