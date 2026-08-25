"""The normalised shapes every data source is adapted into.

Nothing downstream of the adapters knows which dataset it is reading. That is
the whole point: the graph builder, the detector and the case layer are written
against `Edge`, and a new source becomes a new adapter rather than a rewrite.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from datetime import datetime


# Account identity in AMLworld is (bank, account) -- the account id alone is not
# guaranteed unique across banks, and collapsing them would silently merge
# unrelated entities into one node.
#
# Bank ids are zero-padded to a fixed width in the transaction and pattern files
# but stored unpadded in the accounts file, so "016871" and "16871" are the same
# institution. Normalising here is what makes the two sources join at all --
# without it every registry lookup silently misses and every account looks like
# it has no owner and no country.
def account_key(bank: str, account: str) -> str:
    b = bank.strip()
    # An absent bank id is a data error. Mapping it to "0" would silently merge
    # it with the genuine bank 0, so it gets its own reserved marker instead.
    if not b:
        return f"?:{account.strip()}"
    return f"{b.lstrip('0') or '0'}:{account.strip()}"


def amount_key(value) -> str:
    """Canonical string for an amount, used to join labels onto the stream.

    Formatting to 2dp collapsed 0.005 and 0.01 onto the same key. Normalising
    the decimal instead keeps distinct amounts distinct while still matching
    "2848.96" to "2848.960".
    """
    d = Decimal(str(value)).normalize()
    # normalize() renders small/large magnitudes in scientific notation, which
    # would make equal amounts compare unequal as strings.
    return format(d, "f")


def split_key(key: str) -> tuple[str, str]:
    bank, _, account = key.partition(":")
    return bank, account


@dataclass(slots=True)
class Edge:
    """One directed movement of value between two entities."""

    ts: datetime
    src: str                  # account_key
    dst: str                  # account_key
    amount: float             # in `currency`
    currency: str
    channel: str = ""         # ACH, Cheque, Credit Card, Wire, ...
    amount_src: float = 0.0   # amount paid, before any FX
    currency_src: str = ""
    label: int = 0            # source's own ground-truth flag, if any
    meta: dict = field(default_factory=dict)

    @property
    def src_bank(self) -> str:
        return split_key(self.src)[0]

    @property
    def dst_bank(self) -> str:
        return split_key(self.dst)[0]

    @property
    def cross_bank(self) -> bool:
        return self.src_bank != self.dst_bank

    @property
    def cross_currency(self) -> bool:
        return bool(self.currency_src) and self.currency_src != self.currency


@dataclass(slots=True)
class LabeledRing:
    """A ground-truth laundering pattern: the evaluation unit.

    This is what makes ring-level precision and recall reportable at all. Most
    public fraud datasets label transactions; this one labels the group.
    """

    id: str
    typology: str             # FAN-OUT, CYCLE, SCATTER-GATHER, ...
    description: str          # e.g. "Max 10 hops"
    edges: list[Edge]

    def __post_init__(self) -> None:
        # Enforced here rather than in the reporting code: an edgeless ring has
        # no time span and no members, and every downstream consumer assumes
        # otherwise.
        if not self.edges:
            raise ValueError(f"ring {self.id} has no edges")

    @property
    def accounts(self) -> set[str]:
        out: set[str] = set()
        for e in self.edges:
            out.add(e.src)
            out.add(e.dst)
        return out

    @property
    def banks(self) -> set[str]:
        return {split_key(a)[0] for a in self.accounts}

    @property
    def t_start(self) -> datetime:
        return min(e.ts for e in self.edges)

    @property
    def t_end(self) -> datetime:
        return max(e.ts for e in self.edges)

    @property
    def span_days(self) -> float:
        return (self.t_end - self.t_start).total_seconds() / 86400.0

    @property
    def currencies(self) -> set[str]:
        return {e.currency for e in self.edges}

    def summary(self) -> dict:
        return {
            "id": self.id,
            "typology": self.typology,
            "description": self.description,
            "n_edges": len(self.edges),
            "n_accounts": len(self.accounts),
            "n_banks": len(self.banks),
            "span_days": round(self.span_days, 2),
            "currencies": sorted(self.currencies),
        }
