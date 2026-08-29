#!/usr/bin/env bash
# Provision the IBM GFP control on Linux and run it.
#
# This exists because the control CANNOT run on Windows: snapml's Windows
# wheels ship GraphFeaturePreprocessor.py but none of the gf_* native symbols
# it calls, at every published version, and snapml 1.17.x has no Windows wheels
# at all. See scripts/gfp_control.py's docstring for the measurement.
#
# Python version constraint: snapml publishes cp39/cp310/cp311/cp312 wheels.
# 3.13+ has no build. Fedora 41+ defaults to 3.13, so this script looks for an
# older interpreter explicitly rather than trusting `python3`.
#
# numpy: snapml 1.15.6 is compiled against numpy 1.x and dies with
# "_ARRAY_API not found" on numpy 2. The pin below is not cosmetic.
#
#   ./scripts/gfp_setup_linux.sh                    # full run
#   ./scripts/gfp_setup_linux.sh --limit 2          # smoke test first
#   EXPORT_DIR=/mnt/windows/.../data/gfp_export ./scripts/gfp_setup_linux.sh
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${VENV:-$ROOT/.venv-gfp}"
EXPORT_DIR="${EXPORT_DIR:-$ROOT/data/gfp_export}"

PY=""
for cand in python3.12 python3.11 python3.10 python3.9; do
    if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then
    echo "No Python 3.9-3.12 found. snapml publishes no wheel for 3.13+." >&2
    echo "On Fedora:  sudo dnf install python3.12" >&2
    exit 1
fi
echo "using $PY ($($PY --version))"

if [ ! -d "$VENV" ]; then
    "$PY" -m venv "$VENV"
fi
"$VENV/bin/pip" install --quiet --upgrade pip
# numpy pinned BEFORE snapml so pip does not resolve to 2.x and then get
# silently kept when snapml declares no upper bound.
"$VENV/bin/pip" install --quiet "numpy<2" snapml==1.15.6 lightgbm pandas pyarrow scikit-learn

echo
"$VENV/bin/python" - <<'PY'
import numpy, snapml
from snapml import GraphFeaturePreprocessor
g = GraphFeaturePreprocessor()
p = g.get_params()
print(f"snapml {snapml.__version__}, numpy {numpy.__version__}")
print(f"GraphFeaturePreprocessor OK "
      f"(lc-cycle_len={p['lc-cycle_len']}, default tw={p['lc-cycle_tw']}s)")
PY

if [ ! -f "$EXPORT_DIR/manifest.json" ]; then
    cat >&2 <<EOF

No export at $EXPORT_DIR.

The export is ~700 MB and is gitignored, so it is NOT in the clone. Two ways:

  1. Point at the copy on the other OS's partition (dual boot):
       EXPORT_DIR=/run/media/\$USER/<windows>/Users/Pranav/Documents/PayopsAnalyst/data/gfp_export \\
         ./scripts/gfp_setup_linux.sh

  2. Regenerate it here, which needs data/stream/ and
     data/amlworld/HI-Small_accounts.csv present:
       python scripts/gfp_control.py export

  Option 1 is preferred: it guarantees byte-identical candidates rather than
  a replay that should be identical.
EOF
    exit 1
fi

echo
echo "=== stage 2: GFP features ==="
"$VENV/bin/python" "$ROOT/scripts/gfp_control.py" gfp-features \
    --export-dir "$EXPORT_DIR" "$@"

# A smoke run must not roll on into a comparison it would only be refused by.
if [ $# -gt 0 ]; then
    echo
    echo "smoke run complete. Re-run with no arguments for the real thing."
    exit 0
fi

echo
echo "=== stage 3: compare ==="
"$VENV/bin/python" "$ROOT/scripts/gfp_control.py" compare \
    --export-dir "$EXPORT_DIR"

echo
echo "Result in data/eval_gfp.json. It is small -- commit it, and the verdict"
echo "string it carries is the ONLY basis on which anything about GFP may be"
echo "written into the README or HANDOFF."
