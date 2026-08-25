"""Account registry: who owns an account, and where the bank sits.

Two things in this file matter disproportionately to the product.

`Entity ID` links several accounts to one legal owner. That is a *shared-owner
edge* that exists in the source data rather than being inferred, which makes
the identity graph real instead of decorative.

`Bank Name` encodes a jurisdiction. Non-US banks are named "<Country> Bank #n";
US banks carry realistic American names. That gives genuine country-level
corridors without inventing geography, which is the difference between a
defensible map and a fabricated one.
"""
from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from sentinel.schema import account_key

COUNTRY_RE = re.compile(r"^(.*?)\s+Bank\s+#")

# The generator names non-US banks by country and US banks realistically, so an
# unparsed name is a US institution rather than missing data.
US = "USA"

# A handful of entities own thousands of accounts. Treating those as a clique
# would manufacture exactly the hub explosion the design warns about.
MAX_ENTITY_CLIQUE = 32

# The dataset ships this misspelling; normalise it rather than propagating it.
COUNTRY_FIXUPS = {"Crytpo": "Crypto"}

# The regex alone will happily turn "Savings Bank #12" into a country called
# "Savings". Validating against the observed set means an unexpected bank name
# falls back to USA and is counted, rather than quietly inventing a
# jurisdiction that then appears in corridor analysis as if it were real.
KNOWN_COUNTRIES = frozenset({
    "Australia", "Austria", "Belgium", "Brazil", "Canada", "China", "Croatia",
    "Crypto", "Cyprus", "Estonia", "Finland", "France", "Germany", "Greece",
    "India", "Ireland", "Israel", "Italy", "Japan", "Latvia", "Lithuania",
    "Luxembourg", "Malta", "Mexico", "Netherlands", "Portugal", "Russia",
    "Saudi Arabia", "Slovakia", "Slovenia", "Spain", "Switzerland", "UK",
})


@dataclass(slots=True)
class Account:
    key: str
    bank_id: str
    bank_name: str
    country: str
    entity_id: str
    entity_type: str


def parse_country(bank_name: str) -> str:
    m = COUNTRY_RE.match(bank_name or "")
    if not m:
        return US
    c = COUNTRY_FIXUPS.get(m.group(1).strip(), m.group(1).strip())
    return c if c in KNOWN_COUNTRIES else US


def parse_entity_type(entity_name: str) -> str:
    return (entity_name or "").rsplit("#", 1)[0].strip() or "Unknown"


class AccountRegistry:
    """Lookup from account key to owner and jurisdiction.

    Held as plain dicts rather than a dataframe: the hot path is millions of
    single-key lookups during graph construction, where a dict is far faster
    and lighter than repeated dataframe indexing.
    """

    UNKNOWN = "Unknown"

    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}
        self.by_entity: dict[str, list[str]] = defaultdict(list)
        # Names that looked like "<Word> Bank #n" but named no known country.
        self.unrecognised_banks: Counter[str] = Counter()
        # Entities too large to treat as a clique; see shared_owner_pairs.
        self.oversized_entities: int = 0

    @classmethod
    def load(cls, path: str | Path) -> "AccountRegistry":
        reg = cls()
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
            for row in csv.DictReader(fh):
                bank_id = (row.get("Bank ID") or "").strip()
                acct = (row.get("Account Number") or "").strip()
                if not bank_id or not acct:
                    continue
                key = account_key(bank_id, acct)
                if key in reg.accounts:
                    continue
                bank_name = (row.get("Bank Name") or "").strip()
                m = COUNTRY_RE.match(bank_name)
                if m:
                    raw = COUNTRY_FIXUPS.get(m.group(1).strip(), m.group(1).strip())
                    if raw not in KNOWN_COUNTRIES:
                        reg.unrecognised_banks[bank_name] += 1
                entity_id = (row.get("Entity ID") or "").strip()
                reg.accounts[key] = Account(
                    key=key,
                    bank_id=bank_id,
                    bank_name=bank_name,
                    country=parse_country(bank_name),
                    entity_id=entity_id,
                    entity_type=parse_entity_type(row.get("Entity Name") or ""),
                )
                if entity_id:
                    reg.by_entity[entity_id].append(key)
        return reg

    # -- lookups -------------------------------------------------------------

    def get(self, key: str) -> Account | None:
        return self.accounts.get(key)

    def country(self, key: str) -> str:
        a = self.accounts.get(key)
        return a.country if a else self.UNKNOWN

    def entity(self, key: str) -> str:
        a = self.accounts.get(key)
        return a.entity_id if a else self.UNKNOWN

    def summary(self) -> dict:
        return {
            "accounts": len(self.accounts),
            "entities": len(self.by_entity),
            "countries": len({a.country for a in self.accounts.values()}),
            "unrecognised_bank_names": len(self.unrecognised_banks),
        }

    def siblings(self, key: str) -> list[str]:
        """Other accounts owned by the same legal entity."""
        a = self.accounts.get(key)
        if not a or not a.entity_id:
            return []
        return [k for k in self.by_entity.get(a.entity_id, ()) if k != key]

    def shared_owner_pairs(self, keys) -> list[tuple[str, str]]:
        """Identity-graph edges induced by common ownership within `keys`.

        Entities are capped because a handful of them own thousands of accounts
        -- treating those as a clique would create exactly the hub explosion the
        design warns about, so they are skipped as connective structure.
        """
        by_ent: dict[str, list[str]] = defaultdict(list)
        for k in keys:
            a = self.accounts.get(k)
            if a and a.entity_id:
                by_ent[a.entity_id].append(k)
        out: list[tuple[str, str]] = []
        for members in by_ent.values():
            if len(members) > MAX_ENTITY_CLIQUE:
                self.oversized_entities += 1
                continue
            if len(members) > 1:
                for i in range(len(members)):
                    for j in range(i + 1, len(members)):
                        out.append((members[i], members[j]))
        return out
