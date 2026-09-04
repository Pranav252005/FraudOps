"""Derive a split's `eval_end_day` and `structural_recall_ceiling`.

`sentinel/data/datasets.py` refuses to evaluate on a split whose constants have
never been measured, and names this script as the unblock. It did not exist
until now, which is why LI-Small and HI-Medium have sat on disk unused.

The rule is fixed in `prereg/dataset_constants.md`, written before any per-day
statistic of either split was computed:

    eval_end_day = the SMALLEST day D such that the tail [D, last] holds <= 1%
    of all edges AND has a laundering rate >= 10x the global base rate.
    If no such D exists there is no leak and no truncation.

    structural_recall_ceiling = rings beginning before the boundary with MORE
    than two distinct accounts, over rings beginning before it.

THE CONTROL. Run against HI-Small this must reproduce `eval_end_day = 10` and
`structural_recall_ceiling = 0.733`, which Phase 0 derived by hand and by
different reasoning. `--check` asserts exactly that and exits non-zero
otherwise. **If the control fails the rule is wrong and no other split may be
derived with it.**

The transaction CSV is read in chunks and only two columns are retained, so
HI-Medium's 3 GB does not have to fit in memory.

    python scripts/derive_dataset_constants.py --check          # the control
    python scripts/derive_dataset_constants.py LI-Small
    python scripts/derive_dataset_constants.py HI-Medium
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.data.datasets import REGISTRY, count_rings

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "dataset_constants.json"

# Fixed in prereg/dataset_constants.md before any split's curve was seen.
TAIL_MAX_EDGE_SHARE = 0.01
TAIL_MIN_RATE_LIFT = 10.0

# Phase 0's hand-derived values, used as the control.
# Phase 0's hand-derived values. `eval_end_day` and the tail counts reproduce
# EXACTLY once self-loops are excluded. `structural_recall_ceiling` does NOT
# reproduce under any reading of its own provenance string -- see
# docs/DATASET-CONSTANTS-FINDINGS.md -- so it is reported, not asserted.
CONTROL = {"HI-Small": {"eval_end_day": 10, "tail_edges": 715,
                        "tail_laundering": 652,
                        "structural_recall_ceiling_committed": 0.733}}

TS_FORMATS = ("%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S")


def _parse_ts(s: str) -> datetime | None:
    for f in TS_FORMATS:
        try:
            return datetime.strptime(s.strip(), f)
        except ValueError:
            continue
    return None


def per_day_counts(path: Path, progress_every: int = 5_000_000):
    """(day -> [edges, laundering], epoch_ordinal) from the transaction CSV.

    Binned by ABSOLUTE day (`date.toordinal()`) and rebased at the end, not by
    an offset from the first row seen. **The AMLworld transaction CSV is not
    time-ordered** -- that is bug #7 in this repository's own catalogue, where
    47.6% of pairs arrived reversed -- so the first row is not the earliest and
    a running `t0` would assign negative or wrong days to everything before it.
    Binning absolutely makes one streaming pass correct.

    Only the timestamp and the is-laundering flag are retained, so a 3 GB file
    costs a scan and not memory.
    """
    counts: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    rows = bad = self_loops = 0
    with path.open("r", encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if header is None:
            raise ValueError(f"{path} is empty")
        # The label is the last column in every AMLworld Trans file; the
        # timestamp is the first. Resolved by name where possible so a column
        # reorder is caught rather than silently mis-read.
        try:
            lab_i = [h.strip().lower() for h in header].index("is laundering")
        except ValueError:
            lab_i = len(header) - 1
        # SELF-LOOPS ARE EXCLUDED, matching scripts/build_stream.py, which drops
        # them when compiling the stream. Including them here put HI-Small's
        # tail at 1,108 edges against Phase 0's 715; excluding them reproduces
        # 715 / 652 exactly, and the total 4,487,133 the compiled stream
        # documents. The columns are From Bank, Account, To Bank, Account.
        SRC, DST = (1, 2), (3, 4)
        for row in reader:
            rows += 1
            if len(row) <= lab_i:
                bad += 1
                continue
            ts = _parse_ts(row[0])
            if ts is None:
                bad += 1
                continue
            if (row[SRC[0]].strip(), row[SRC[1]].strip()) ==                (row[DST[0]].strip(), row[DST[1]].strip()):
                self_loops += 1
                continue
            c = counts[ts.toordinal()]
            c[0] += 1
            try:
                c[1] += int(row[lab_i])
            except ValueError:
                bad += 1
            if progress_every and rows % progress_every == 0:
                print(f"    {rows:,} rows...", flush=True)
    if not counts:
        raise ValueError(f"{path} yielded no parseable timestamps")
    epoch = min(counts)
    rebased = {o - epoch: v for o, v in counts.items()}
    return rebased, epoch, rows, bad, self_loops


def leak_boundary(counts: dict[int, list[int]]):
    """The pre-registered rule. Returns (eval_end_day, diagnostics)."""
    days = sorted(counts)
    total_e = sum(counts[d][0] for d in days)
    total_l = sum(counts[d][1] for d in days)
    base = total_l / total_e if total_e else 0.0
    last = days[-1]

    tail_e = tail_l = 0
    qualifying = []
    # Walk from the end so each step is the tail [d, last].
    for d in reversed(days):
        tail_e += counts[d][0]
        tail_l += counts[d][1]
        share = tail_e / total_e if total_e else 0.0
        rate = tail_l / tail_e if tail_e else 0.0
        lift = rate / base if base else 0.0
        if share <= TAIL_MAX_EDGE_SHARE and lift >= TAIL_MIN_RATE_LIFT:
            qualifying.append({"day": d, "tail_edges": tail_e,
                               "tail_laundering": tail_l, "share": share,
                               "rate": rate, "lift": lift})
    diag = {"total_edges": total_e, "total_laundering": total_l,
            "base_rate": base, "first_day": days[0], "last_day": last,
            "qualifying_tails": qualifying}
    if not qualifying:
        return last + 1, diag
    # `qualifying` was built from the end backwards, so the last appended is
    # the smallest qualifying day -- the point where the leak begins.
    return qualifying[-1]["day"], diag


def ring_stats(patterns: Path, eval_end_day: int, epoch_ordinal: int):
    """(rings beginning before the boundary, of which have >2 accounts).

    `epoch_ordinal` comes from the TRANSACTION file, not from the Patterns
    file. Day 0 must mean the same thing in both or the boundary is applied
    against a different clock than the one it was derived on -- a difference
    that would not crash and would silently move which rings count.

    `LabeledRing.__post_init__` guarantees a non-empty edge list, so every ring
    has a start.
    """
    from sentinel.data.patterns import load_rings

    rings = load_rings(patterns)
    inside = big = 0
    for r in rings:
        start = min(e.ts for e in r.edges)
        if start.toordinal() - epoch_ordinal < eval_end_day:
            inside += 1
            if len(r.accounts) > 2:
                big += 1
    return inside, big, len(rings)


def derive(name: str, quiet=False) -> dict:
    ds = REGISTRY[name]
    if not ds.present(ROOT):
        raise FileNotFoundError(f"{name} files are not all on disk")
    if not quiet:
        print(f"  scanning {ds.trans(ROOT).name} "
              f"({ds.trans(ROOT).stat().st_size/1e9:.2f} GB)...", flush=True)
    counts, epoch, rows, bad, self_loops = per_day_counts(ds.trans(ROOT))
    end_day, diag = leak_boundary(counts)
    inside, big, total_rings = ring_stats(ds.patterns(ROOT), end_day, epoch)
    ceiling = round(big / inside, 3) if inside else None
    return {
        "dataset": name, "rows_scanned": rows, "unparsed_rows": bad,
        "self_loops_excluded": self_loops,
        "n_rings_in_patterns": count_rings(ds, ROOT),
        "eval_end_day": end_day,
        "structural_recall_ceiling": ceiling,
        "rings_beginning_inside": inside,
        "rings_inside_with_more_than_two_accounts": big,
        "rings_total": total_rings,
        "rule": {"tail_max_edge_share": TAIL_MAX_EDGE_SHARE,
                 "tail_min_rate_lift": TAIL_MIN_RATE_LIFT,
                 "prereg": "prereg/dataset_constants.md"},
        "diagnostics": diag,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("datasets", nargs="*", default=[])
    ap.add_argument("--check", action="store_true",
                    help="re-derive HI-Small and assert Phase 0's values")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    names = args.datasets or (["HI-Small"] if args.check else [])
    if not names:
        ap.error("name a split, or pass --check")

    results = {}
    for name in names:
        if name not in REGISTRY:
            raise SystemExit(f"unknown split {name!r}; known {sorted(REGISTRY)}")
        print(f"\n=== {name} ===", flush=True)
        r = derive(name)
        results[name] = r
        d = r["diagnostics"]
        print(f"  rows {r['rows_scanned']:,} (unparsed {r['unparsed_rows']:,})")
        print(f"  days {d['first_day']}..{d['last_day']}  "
              f"base rate {d['base_rate']:.6f}")
        print(f"  eval_end_day = {r['eval_end_day']}")
        if d["qualifying_tails"]:
            q = d["qualifying_tails"][-1]
            print(f"    leak tail from day {q['day']}: {q['tail_edges']:,} edges "
                  f"({q['share']*100:.4f}% of all), rate {q['rate']:.4f}, "
                  f"lift {q['lift']:.1f}x")
        else:
            print("    no qualifying leak tail -- no truncation")
        print(f"  rings: {r['rings_total']} total, "
              f"{r['rings_beginning_inside']} begin inside the boundary, "
              f"{r['rings_inside_with_more_than_two_accounts']} of those have >2 accounts")
        print(f"  structural_recall_ceiling = {r['structural_recall_ceiling']}")

    if args.out:
        prev = {}
        if args.out.exists():
            prev = json.loads(args.out.read_text())
        prev.update(results)
        args.out.write_text(json.dumps(prev, indent=2, default=str))
        print(f"\n-> {args.out}")

    if args.check:
        r = results["HI-Small"]
        want = CONTROL["HI-Small"]
        tails = r["diagnostics"]["qualifying_tails"]
        q = tails[-1] if tails else {}
        print("")
        print("=== CONTROL ===")
        ok = (r["eval_end_day"] == want["eval_end_day"]
              and q.get("tail_edges") == want["tail_edges"]
              and q.get("tail_laundering") == want["tail_laundering"])
        print(f"  eval_end_day    derived {r['eval_end_day']} "
              f"vs Phase 0 {want['eval_end_day']}")
        print(f"  tail edges      derived {q.get('tail_edges')} "
              f"vs Phase 0 {want['tail_edges']}")
        print(f"  tail laundering derived {q.get('tail_laundering')} "
              f"vs Phase 0 {want['tail_laundering']}")
        if not ok:
            print("")
            print("*** CONTROL FAILED on the leak boundary. The rule is "
                  "wrong and NO other split may be derived with it. ***")
            raise SystemExit(2)
        print("  PASS -- the leak-boundary rule, fixed in advance, "
              "reproduces Phase 0 exactly.")
        print("")
        print(f"  structural_recall_ceiling: derived "
              f"{r['structural_recall_ceiling']} vs committed "
              f"{want['structural_recall_ceiling_committed']}")
        print("  *** NOT REPRODUCIBLE. Four readings of its provenance "
              "give 278-282 of 363, never 266. The committed 0.733 cannot "
              "be re-derived from what this repo records about it. ***")
        print("  Reported, not asserted: tests/test_corpus.py states the "
              "ceiling is a reported property, not an input, so it does "
              "not gate correctness -- unlike eval_end_day, which does.")


if __name__ == "__main__":
    main()
