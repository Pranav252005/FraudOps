"""D1: which reading of "more than two accounts visible in-window" gives 266?

`STRUCTURAL_RECALL_CEILING = 0.733` is committed with the provenance "363 of
370 rings begin inside the boundary, and 266 of those 363 have more than two
accounts visible in-window". `scripts/derive_dataset_constants.py` reproduces
the denominator exactly and gets 282 for the numerator, not 266.

This enumerates readings of that phrase and reports what each gives. It ships
nothing. **Pre-registered in `prereg/ceiling_redux.md` with the decision rule
that no reading found here may be adopted as the shipped definition, even one
that hits 266 exactly** -- searching readings for one that matches a known
target is fitting, not deriving. The shipped value comes from applying the
same definition the other two splits already use.

The negative control is R0: it must reproduce the committed derivation's
282/363, or nothing else printed here is believable.

    python scripts/probe_ceiling_readings.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.data.datasets import REGISTRY
from sentinel.data.patterns import load_rings
from sentinel.schema import split_key

ROOT = Path(__file__).resolve().parent.parent
CONSTANTS = ROOT / "data" / "dataset_constants.json"

TARGET = 266            # what Phase 0 recorded
CONTROL_NUMERATOR = 282  # what the committed derivation gets
CONTROL_DENOMINATOR = 363
WINDOW_MINUTES = 72 * 60


def _in_window_edges(ring, cutoff):
    """Edges strictly before the boundary. `cutoff` is a datetime."""
    return [e for e in ring.edges if e.ts < cutoff]


def _accounts(edges, *, bare=False, drop_self=False):
    out = set()
    for e in edges:
        if drop_self and e.src == e.dst:
            continue
        for a in (e.src, e.dst):
            out.add(split_key(a)[1] if bare else a)
    return out


def _max_covisible(edges, *, bare=False):
    """Most distinct accounts appearing together in any 72h span of `edges`.

    Sweeps each edge as the window start, which is sufficient: a maximal window
    can always be slid to begin on an edge.
    """
    if not edges:
        return 0
    ordered = sorted(edges, key=lambda e: e.ts)
    best = 0
    for i, start in enumerate(ordered):
        seen = set()
        for e in ordered[i:]:
            if (e.ts - start.ts).total_seconds() > WINDOW_MINUTES * 60:
                break
            for a in (e.src, e.dst):
                seen.add(split_key(a)[1] if bare else a)
        best = max(best, len(seen))
    return best


def main() -> None:
    ds = REGISTRY["HI-Small"]
    rec = json.loads(CONSTANTS.read_text())["HI-Small"]

    # Kill criterion 3: the boundary is the thing that gates correctness.
    if rec["eval_end_day"] != 10:
        sys.exit(f"ABORT: eval_end_day is {rec['eval_end_day']}, not 10")

    rings = load_rings(ds.patterns(ROOT))
    # Day 0 must mean the same thing as it did in the transaction scan, so the
    # epoch is taken from the same place the boundary was.
    epoch = min(r.t_start for r in rings).toordinal()
    inside = [r for r in rings
              if r.t_start.toordinal() - epoch < rec["eval_end_day"]]
    cutoff = min(r.t_start for r in rings).replace(
        hour=0, minute=0, second=0, microsecond=0)
    cutoff = cutoff.fromordinal(epoch + rec["eval_end_day"])

    print(f"rings in Patterns          : {len(rings)}")
    print(f"rings beginning inside     : {len(inside)}  "
          f"(control expects {CONTROL_DENOMINATOR})")
    if len(inside) != CONTROL_DENOMINATOR:
        sys.exit(f"ABORT (kill criterion 2): denominator is {len(inside)}, "
                 f"not {CONTROL_DENOMINATOR}; the harness has drifted")
    print(f"boundary cutoff            : {cutoff}")
    print()

    readings = {
        "R0 control: all accounts of the ring":
            lambda r: len(_accounts(r.edges)),
        "R5 accounts on in-window edges":
            lambda r: len(_accounts(_in_window_edges(r, cutoff))),
        "R6 R5, self-loop edges dropped":
            lambda r: len(_accounts(_in_window_edges(r, cutoff),
                                    drop_self=True)),
        "R7 bare account ids, banks merged":
            lambda r: len(_accounts(r.edges, bare=True)),
        "R7b R5 with bare account ids":
            lambda r: len(_accounts(_in_window_edges(r, cutoff), bare=True)),
        "R8 R5 + 72h co-visibility":
            lambda r: _max_covisible(_in_window_edges(r, cutoff)),
        "R8b R8 with bare account ids":
            lambda r: _max_covisible(_in_window_edges(r, cutoff), bare=True),
    }

    print(f"{'reading':<40}{'>2':>6}{'ceiling':>10}   vs 266")
    hits = []
    for label, fn in readings.items():
        n = sum(1 for r in inside if fn(r) > 2)
        mark = "  <-- HITS 266" if n == TARGET else f"  {n - TARGET:+d}"
        if n == TARGET:
            hits.append(label)
        print(f"{label:<40}{n:>6}{n/len(inside):>10.3f}{mark}")

    control = sum(1 for r in inside if len(_accounts(r.edges)) > 2)
    print()
    if control != CONTROL_NUMERATOR:
        sys.exit(f"ABORT (negative control): R0 gives {control}, not "
                 f"{CONTROL_NUMERATOR}; discard everything above")
    print(f"negative control OK: R0 reproduces {CONTROL_NUMERATOR}/"
          f"{CONTROL_DENOMINATOR} = {CONTROL_NUMERATOR/CONTROL_DENOMINATOR:.3f}")
    print()
    if hits:
        print(f"{len(hits)} of {len(readings)} readings hit 266: {hits}")
        print("PER prereg/ceiling_redux.md THIS DOES NOT BECOME THE SHIPPED")
        print("DEFINITION. It is a candidate explanation of what Phase 0 did,")
        print(f"found by searching {len(readings)} readings for a known target.")
    else:
        print(f"no reading of {len(readings)} reproduces 266. Combined with the "
              f"four tried on 2026-09-05, {len(readings) + 4} readings of the "
              f"provenance string fail to reconstruct the committed constant.")


if __name__ == "__main__":
    main()
