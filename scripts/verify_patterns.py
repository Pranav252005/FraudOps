"""Phase 0 risk gate: prove the ground-truth pattern file parses and is usable.

Everything the evaluation story depends on is asserted here. If this script is
red, ring-level precision and recall are not reportable and the fallback plan
(connected components over laundering-flagged transactions) is required.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.data.patterns import describe, load_rings_with_report

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sentinel.data.datasets import active as _active_dataset

#: The AMLworld split in play. Defaults to HI-Small; override with
#: SENTINEL_DATASET so this can sanity-check a newly downloaded split.
DATASET = _active_dataset()
PATH = DATASET.patterns(ROOT)

rings, report = load_rings_with_report(PATH)
if not report.is_clean:
    print(f"!! PARSE ANOMALIES: {report.anomalies}")
    print("   ground-truth completeness is a precondition for every metric")
    raise SystemExit(1)
print(f"parse report        {report}")
d = describe(rings)

print(f"rings parsed        {d['n_rings']:,}")
print(f"edges in rings      {d['n_edges']:,}")
print(f"distinct accounts   {d['n_accounts']:,}")
print(f"time span           {d['t_min']}  ->  {d['t_max']}")
print(f"self-loop edges     {d['self_loops']:,}")
pct = 100*d["cross_currency_edges"]/d["n_edges"] if d["n_edges"] else 0.0
print(f"cross-currency      {d['cross_currency_edges']:,}  ({pct:.1f}% of ring edges)")
print(f"currencies          {len(d['currencies'])}")
print(f"channels            {d['channels']}")
print()
hdr = f"{'typology':<16}{'rings':>7}{'edges':>8}{'acct min':>10}{'med':>6}{'max':>6}{'edge med':>10}{'trivial<=2':>12}"
print(hdr)
print("-" * len(hdr))
for r in d["by_typology"]:
    print(f"{r['typology']:<16}{r['n_rings']:>7,}{r['n_edges']:>8,}"
          f"{r['accounts_min']:>10}{r['accounts_med']:>6}{r['accounts_max']:>6}"
          f"{r['edges_med']:>10}{r['trivial']:>12,}")

total_trivial = sum(r["trivial"] for r in d["by_typology"])
print("-" * len(hdr))
print(f"{'TOTAL':<16}{d['n_rings']:>7,}{d['n_edges']:>8,}{'':>32}{total_trivial:>12,}")
print()
print(f"structurally findable (>2 accounts): {d['n_rings']-total_trivial:,} "
      f"({100*(d['n_rings']-total_trivial)/d['n_rings']:.1f}%)")

out = Path(__file__).resolve().parent.parent / "data" / "patterns_profile.json"
out.write_text(json.dumps(d, indent=2, default=str), encoding="utf-8")
print(f"\nprofile written to {out.relative_to(out.parent.parent)}")
