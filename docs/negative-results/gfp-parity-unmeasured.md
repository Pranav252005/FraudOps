# Every "feature parity with IBM's GFP" claim was struck

**Recorded:** 2026-08-31. **Status:** BLOCKED, not skipped, and not fixable on
this machine. **Source:** `docs/HANDOFF.md` §4, `scripts/gfp_control.py`,
`tests/test_gfp_control.py::test_gfp_constructor_state_matches_platform`.

## What was claimed, and struck

The repository claimed feature parity with IBM's Graph Feature Preprocessor
(ICAIF 2024) — the most important external comparison available to it. **That
claim was never a measured comparison.** It was feature-family coverage: a
reading of which feature *kinds* both systems compute. It has been struck from
`docs/HANDOFF.md` §4 rather than softened.

## Why it cannot be measured here

Independently verified: **zero `gf_*` symbols in any Windows `.pyd`** across all
six binaries in snapml 1.15.6, while the manylinux wheel of the same version
exports all eight. `GraphFeaturePreprocessor`'s Python wrapper imports fine and
its constructor dies on a missing `gf_allocate`.

The blocker is **the operating system, not the Python version**. This corrects
an earlier diagnosis that said the opposite — that snapml shipped no wheels for
Python 3.12+ and a 3.11 environment would unblock it. A 3.11 venv was
provisioned, snapml 1.15.6 installed, and the failure reproduced. **The
obstacle is larger than the note it replaced claimed**, which is the opposite of
the direction a correction usually moves.

The suggested workarounds therefore cannot work: a venv on 3.11/3.12 does not
help, and neither does a subprocess boundary, because there is no native code
to call on either side of it. There is **no WSL and no Docker on this machine**,
and installing either needs admin plus a reboot.

The platform finding is recorded as an executable assertion so it cannot rot
silently.

## What would reverse this

Running `scripts/gfp_control.py gfp-features` on Linux or macOS, then
`scripts/gfp_compare.py`, producing a head-to-head of the two feature blocks on
the same split. That is the only thing that reverses it. **No parity claim may
enter the repository until that head-to-head exists.**
