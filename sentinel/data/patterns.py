"""Parser for the AMLworld ground-truth pattern file.

The file is a sequence of blocks:

    BEGIN LAUNDERING ATTEMPT - <TYPOLOGY>[:  <description>]
    <transaction row>
    ...
    END LAUNDERING ATTEMPT - <TYPOLOGY>

Rows carry the same positional schema as the main transactions CSV but without
a header. This file is the reason ring-level precision and recall are
reportable at all -- it labels the *group*, not just the transaction.

Everything the parser cannot use is counted in a `ParseReport` rather than
dropped quietly. Ground truth completeness is the foundation every reported
metric stands on, so a silent loss here would corrupt all of them at once while
still producing plausible-looking output.
"""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sentinel.schema import Edge, LabeledRing, account_key

BEGIN = re.compile(r"^BEGIN LAUNDERING ATTEMPT\s*-\s*([A-Z][A-Z\-]*)\s*(?::\s*(.*))?$")
END = re.compile(r"^END LAUNDERING ATTEMPT\s*-\s*([A-Z][A-Z\-]*)\s*$")

TS_FORMAT = "%Y/%m/%d %H:%M"

# Positional schema of a transaction row, shared with HI-Small_Trans.csv.
COLUMNS = [
    "Timestamp", "From Bank", "Account", "To Bank", "Account.1",
    "Amount Received", "Receiving Currency", "Amount Paid", "Payment Currency",
    "Payment Format", "Is Laundering",
]
N_COLUMNS = len(COLUMNS)


@dataclass
class ParseReport:
    """What the parser saw, including everything it could not use."""

    blocks_begun: int = 0
    blocks_closed: int = 0
    rings_emitted: int = 0
    edges_emitted: int = 0
    empty_blocks: int = 0
    nested_begins: int = 0
    unmatched_ends: int = 0
    unclosed_at_eof: int = 0
    orphan_rows: int = 0
    malformed_rows: int = 0
    typology_mismatches: int = 0
    typologies: Counter = field(default_factory=Counter)

    @property
    def anomalies(self) -> dict[str, int]:
        names = ("empty_blocks", "nested_begins", "unmatched_ends",
                 "unclosed_at_eof", "orphan_rows", "malformed_rows",
                 "typology_mismatches")
        return {n: getattr(self, n) for n in names if getattr(self, n)}

    @property
    def is_clean(self) -> bool:
        return not self.anomalies

    def __str__(self) -> str:
        if self.is_clean:
            return (f"clean: {self.rings_emitted} rings, "
                    f"{self.edges_emitted} edges")
        return (f"{self.rings_emitted} rings, {self.edges_emitted} edges; "
                f"anomalies: {self.anomalies}")


def parse_row(fields: list[str]) -> Edge:
    """One CSV row -> one normalised Edge.

    `Amount Received` is what the destination gets in `Receiving Currency`;
    `Amount Paid` is what the source sent in `Payment Currency`. They differ
    whenever the hop crosses a currency.

    Rejects rows whose field count is not exactly the schema width. Truncating
    a longer row parses "successfully" while mapping values to the wrong
    columns, which is the worst available outcome.
    """
    if len(fields) != N_COLUMNS:
        raise ValueError(f"expected {N_COLUMNS} fields, got {len(fields)}")

    (ts, from_bank, acct_from, to_bank, acct_to,
     amt_recv, cur_recv, amt_paid, cur_paid, fmt, label) = fields

    return Edge(
        ts=datetime.strptime(ts.strip(), TS_FORMAT),
        src=account_key(from_bank, acct_from),
        dst=account_key(to_bank, acct_to),
        amount=float(amt_recv),
        currency=cur_recv.strip(),
        channel=fmt.strip(),
        amount_src=float(amt_paid),
        currency_src=cur_paid.strip(),
        label=int(label),
    )


def load_rings_with_report(path: str | Path) -> tuple[list[LabeledRing], ParseReport]:
    """Parse the pattern file, returning the rings and a record of what was lost."""
    rings: list[LabeledRing] = []
    rep = ParseReport()

    typology: str | None = None
    description = ""
    rows: list[list[str]] = []

    def flush(closing: str | None) -> None:
        nonlocal typology, description, rows
        if typology is None:
            return
        if closing is not None and closing != typology:
            rep.typology_mismatches += 1
        if not rows:
            rep.empty_blocks += 1
        else:
            edges = []
            for r in rows:
                try:
                    edges.append(parse_row(r))
                except (ValueError, IndexError):
                    rep.malformed_rows += 1
            if edges:
                rep.rings_emitted += 1
                rep.edges_emitted += len(edges)
                rep.typologies[typology] += 1
                rings.append(LabeledRing(
                    id=f"RING-{rep.rings_emitted:05d}",
                    typology=typology,
                    description=description,
                    edges=edges,
                ))
            else:
                rep.empty_blocks += 1
        typology, description, rows = None, "", []

    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        for line in fh:
            line = line.rstrip("\r\n")
            if not line.strip():
                continue

            m = BEGIN.match(line)
            if m:
                if typology is not None:
                    # A block opened inside another one. Close the outer block
                    # so its rows survive, and record that it happened.
                    rep.nested_begins += 1
                    flush(None)
                rep.blocks_begun += 1
                typology = m.group(1)
                description = (m.group(2) or "").strip()
                rows = []
                continue

            e = END.match(line)
            if e:
                rep.blocks_closed += 1
                if typology is None:
                    rep.unmatched_ends += 1
                else:
                    flush(e.group(1))
                continue

            if typology is None:
                rep.orphan_rows += 1
                continue

            parsed = next(csv.reader([line]), None)
            if parsed is None:
                rep.malformed_rows += 1
            else:
                rows.append(parsed)

    if typology is not None:
        rep.unclosed_at_eof += 1
        flush(None)

    return rings, rep


def load_rings(path: str | Path, strict: bool = False) -> list[LabeledRing]:
    """Parse the pattern file.

    With `strict=True` any anomaly raises. Use it wherever the completeness of
    ground truth is a precondition -- notably the evaluation harness, where a
    partially-parsed label set silently changes every metric.
    """
    rings, rep = load_rings_with_report(path)
    if strict and not rep.is_clean:
        raise ValueError(f"pattern file {path} parsed with anomalies: {rep.anomalies}")
    return rings


def describe(rings: list[LabeledRing]) -> dict:
    """Summary statistics used by the Phase 0 verification report."""
    by_typ: dict[str, list[LabeledRing]] = defaultdict(list)
    for r in rings:
        by_typ[r.typology].append(r)

    accounts: set[str] = set()
    edge_total = self_loops = cross_currency = 0
    for r in rings:
        accounts |= r.accounts
        edge_total += len(r.edges)
        for e in r.edges:
            if e.src == e.dst:
                self_loops += 1
            if e.cross_currency:
                cross_currency += 1

    typ_rows = []
    for typ, group in sorted(by_typ.items(), key=lambda kv: -len(kv[1])):
        sizes = sorted(len(r.accounts) for r in group)
        edges = sorted(len(r.edges) for r in group)
        typ_rows.append({
            "typology": typ,
            "n_rings": len(group),
            "n_edges": sum(edges),
            "accounts_min": sizes[0],
            "accounts_med": sizes[len(sizes) // 2],
            "accounts_max": sizes[-1],
            "edges_med": edges[len(edges) // 2],
            # A ring of 2 accounts has no community structure to find. Counting
            # these up front is what keeps the recall claim honest later.
            "trivial": sum(1 for s in sizes if s <= 2),
        })

    return {
        "n_rings": len(rings),
        "n_edges": edge_total,
        "n_accounts": len(accounts),
        "self_loops": self_loops,
        "cross_currency_edges": cross_currency,
        "currencies": sorted({e.currency for r in rings for e in r.edges}),
        "channels": dict(Counter(e.channel for r in rings for e in r.edges)),
        "t_min": min((r.t_start for r in rings), default=None),
        "t_max": max((r.t_end for r in rings), default=None),
        "by_typology": typ_rows,
    }
