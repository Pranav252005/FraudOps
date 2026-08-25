"""Phase 0 regression tests.

Every test here encodes a defect that was either found in review or that would
have silently corrupted ground truth. The governing principle: in this project
a wrong answer that looks plausible is far more dangerous than a crash, so the
parsers are required to *report* what they discarded rather than discard
quietly.
"""
from __future__ import annotations

import textwrap
from datetime import datetime
from pathlib import Path

import pytest

from sentinel.data.accounts import (KNOWN_COUNTRIES, AccountRegistry,
                                    parse_country, parse_entity_type)
from sentinel.data.patterns import load_rings, load_rings_with_report, parse_row
from sentinel.schema import Edge, LabeledRing, account_key, amount_key

DATA = Path(__file__).resolve().parent.parent / "data" / "amlworld"
TRANS = DATA / "HI-Small_Trans.csv"
PATTERNS = DATA / "HI-Small_Patterns.txt"
ACCOUNTS = DATA / "HI-Small_accounts.csv"

needs_data = pytest.mark.skipif(
    not PATTERNS.exists(), reason="AMLworld data not downloaded"
)


def write(tmp_path: Path, text: str) -> Path:
    p = tmp_path / "patterns.txt"
    p.write_text(textwrap.dedent(text).lstrip("\n"), encoding="utf-8")
    return p


ROW = ("2022/09/01 00:06,021174,800737690,012,80011F990,"
       "2848.96,Euro,2848.96,Euro,ACH,1")


# --------------------------------------------------------------------------
# account_key -- the zero-padding defect that silently broke every join
# --------------------------------------------------------------------------

class TestAccountKey:
    def test_zero_padding_is_normalised(self):
        """Bank ids are padded in the transaction files, unpadded in accounts.

        This is the regression test for the bug that made every registry lookup
        miss while still returning a plausible-looking answer.
        """
        assert account_key("016871", "80C28C050") == account_key("16871", "80C28C050")
        assert account_key(" 010 ", "A") == account_key("10", "A")

    def test_genuine_zero_bank_survives(self):
        assert account_key("0", "A") == "0:A"
        assert account_key("000", "A") == "0:A"

    def test_empty_bank_does_not_collide_with_bank_zero(self):
        """An absent bank id is a data error, not bank 0."""
        assert account_key("", "A") != account_key("0", "A")

    def test_distinct_banks_stay_distinct(self):
        assert account_key("10", "A") != account_key("100", "A")


# --------------------------------------------------------------------------
# amount_key -- join stability for attaching ground truth
# --------------------------------------------------------------------------

class TestAmountKey:
    def test_distinct_amounts_do_not_collide(self):
        """Rounding to 2dp merged 0.005 and 0.01 into the same join key."""
        assert amount_key("0.005") != amount_key("0.01")

    def test_same_amount_written_differently_matches(self):
        assert amount_key("2848.96") == amount_key("2848.960")
        assert amount_key("100000") == amount_key("1e5")

    def test_large_amounts_keep_precision(self):
        assert amount_key("5738987.96") == amount_key("5738987.96")
        assert amount_key("1234567890.99") != amount_key("1234567890.98")


# --------------------------------------------------------------------------
# parse_row
# --------------------------------------------------------------------------

class TestParseRow:
    def test_parses_canonical_row(self):
        e = parse_row(ROW.split(","))
        assert e.ts == datetime(2022, 9, 1, 0, 6)
        assert e.amount == 2848.96
        assert e.currency == "Euro"
        assert e.channel == "ACH"
        assert e.label == 1

    def test_rejects_extra_fields_instead_of_truncating(self):
        """A 12-field row previously parsed 'successfully' with wrong data."""
        with pytest.raises(ValueError):
            parse_row((ROW + ",EXTRA").split(","))

    def test_rejects_short_rows(self):
        with pytest.raises(ValueError):
            parse_row(ROW.split(",")[:8])

    def test_rejects_bad_timestamp(self):
        bad = ROW.split(",")
        bad[0] = "notadate"
        with pytest.raises(ValueError):
            parse_row(bad)


# --------------------------------------------------------------------------
# LabeledRing invariants
# --------------------------------------------------------------------------

class TestLabeledRing:
    def test_empty_ring_is_rejected_at_construction(self):
        """t_start used to raise deep inside reporting; fail at the boundary."""
        with pytest.raises(ValueError):
            LabeledRing(id="R", typology="CYCLE", description="", edges=[])

    def test_accounts_and_span(self):
        e1 = parse_row(ROW.split(","))
        e2 = parse_row(ROW.replace("00:06", "12:06").split(","))
        r = LabeledRing("R", "CYCLE", "", [e1, e2])
        assert len(r.accounts) == 2
        assert r.span_days == pytest.approx(0.5)
        assert r.banks == {account_key("021174", "x").split(":")[0],
                           account_key("012", "x").split(":")[0]}


# --------------------------------------------------------------------------
# Pattern file parsing -- silent loss is the enemy
# --------------------------------------------------------------------------

class TestPatternParsing:
    def test_well_formed_block(self, tmp_path):
        p = write(tmp_path, f"""
            BEGIN LAUNDERING ATTEMPT - CYCLE:  Max 10 hops
            {ROW}
            END LAUNDERING ATTEMPT - CYCLE
        """)
        rings, rep = load_rings_with_report(p)
        assert len(rings) == 1
        assert rings[0].typology == "CYCLE"
        assert rings[0].description == "Max 10 hops"
        assert rep.is_clean

    def test_block_without_description(self, tmp_path):
        p = write(tmp_path, f"""
            BEGIN LAUNDERING ATTEMPT - BIPARTITE
            {ROW}
            END LAUNDERING ATTEMPT - BIPARTITE
        """)
        rings, rep = load_rings_with_report(p)
        assert rings[0].description == ""
        assert rep.is_clean

    def test_nested_begin_is_reported_not_swallowed(self, tmp_path):
        """Previously the outer block vanished with no diagnostic at all."""
        p = write(tmp_path, f"""
            BEGIN LAUNDERING ATTEMPT - FAN-OUT:  y
            {ROW}
            BEGIN LAUNDERING ATTEMPT - STACK:  nested
            {ROW}
            END LAUNDERING ATTEMPT - STACK
        """)
        rings, rep = load_rings_with_report(p)
        assert rep.nested_begins == 1
        assert not rep.is_clean

    def test_empty_block_is_counted(self, tmp_path):
        p = write(tmp_path, """
            BEGIN LAUNDERING ATTEMPT - CYCLE:  x
            END LAUNDERING ATTEMPT - CYCLE
        """)
        rings, rep = load_rings_with_report(p)
        assert rings == []
        assert rep.empty_blocks == 1
        assert not rep.is_clean

    def test_orphan_rows_are_counted(self, tmp_path):
        p = write(tmp_path, f"""
            END LAUNDERING ATTEMPT - BIPARTITE
            {ROW}
        """)
        rings, rep = load_rings_with_report(p)
        assert rep.orphan_rows == 1
        assert rep.unmatched_ends == 1
        assert not rep.is_clean

    def test_typology_mismatch_is_counted(self, tmp_path):
        p = write(tmp_path, f"""
            BEGIN LAUNDERING ATTEMPT - CYCLE:  x
            {ROW}
            END LAUNDERING ATTEMPT - STACK
        """)
        _, rep = load_rings_with_report(p)
        assert rep.typology_mismatches == 1

    def test_malformed_row_is_counted_not_silently_dropped(self, tmp_path):
        p = write(tmp_path, f"""
            BEGIN LAUNDERING ATTEMPT - CYCLE:  x
            {ROW}
            garbage,row,too,short
            END LAUNDERING ATTEMPT - CYCLE
        """)
        rings, rep = load_rings_with_report(p)
        assert len(rings[0].edges) == 1
        assert rep.malformed_rows == 1

    def test_strict_mode_raises_on_any_anomaly(self, tmp_path):
        p = write(tmp_path, """
            BEGIN LAUNDERING ATTEMPT - CYCLE:  x
            END LAUNDERING ATTEMPT - CYCLE
        """)
        with pytest.raises(ValueError, match="empty_blocks"):
            load_rings(p, strict=True)


# --------------------------------------------------------------------------
# Country / entity parsing
# --------------------------------------------------------------------------

class TestCountryParsing:
    def test_country_bank_form(self):
        assert parse_country("Portugal Bank #4507") == "Portugal"
        assert parse_country("Saudi Arabia Bank #9") == "Saudi Arabia"

    def test_us_banks_fall_back_to_usa(self):
        assert parse_country("National Bank of Harrisburg") == "USA"
        assert parse_country("Bank of New York") == "USA"
        assert parse_country("") == "USA"

    def test_dataset_misspelling_is_normalised(self):
        assert parse_country("Crytpo Bank #1") == "Crypto"

    def test_non_country_word_is_not_invented_as_a_country(self):
        """'Savings Bank #12' must not produce a country called 'Savings'."""
        assert parse_country("Savings Bank #12") == "USA"
        assert "Savings" not in KNOWN_COUNTRIES

    def test_entity_type(self):
        assert parse_entity_type("Corporation #33520") == "Corporation"
        assert parse_entity_type("Sole Proprietorship #50438") == "Sole Proprietorship"
        assert parse_entity_type("") == "Unknown"


# --------------------------------------------------------------------------
# Integration against the real files
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rings():
    return load_rings(PATTERNS)


@pytest.fixture(scope="module")
def registry():
    return AccountRegistry.load(ACCOUNTS)


@needs_data
class TestRealData:
    def test_pattern_file_parses_cleanly(self):
        rings, rep = load_rings_with_report(PATTERNS)
        assert rep.is_clean, rep
        assert len(rings) == 370
        assert sum(len(r.edges) for r in rings) == 3209

    def test_all_eight_typologies_present(self, rings):
        assert {r.typology for r in rings} == {
            "FAN-OUT", "FAN-IN", "CYCLE", "RANDOM",
            "BIPARTITE", "STACK", "SCATTER-GATHER", "GATHER-SCATTER",
        }

    def test_every_ring_account_resolves_in_registry(self, rings, registry):
        """The padding-bug regression test, at full scale.

        A silent drop to 0% here previously produced the plausible-looking and
        completely wrong conclusion that no ring crosses a border.
        """
        accounts = set()
        for r in rings:
            accounts |= r.accounts
        missing = [a for a in accounts if registry.get(a) is None]
        assert not missing, f"{len(missing)} of {len(accounts)} unresolved"

    def test_cross_border_structure_is_present(self, rings, registry):
        multi = sum(1 for r in rings
                    if len({registry.country(a) for a in r.accounts}) > 1)
        assert multi / len(rings) > 0.8

    def test_no_invented_countries(self, registry):
        seen = {a.country for a in registry.accounts.values()}
        assert seen <= KNOWN_COUNTRIES | {"USA"}, seen - KNOWN_COUNTRIES - {"USA"}

    def test_known_evaluation_ceiling(self, rings):
        """~24% of rings have <=2 accounts and cannot be found structurally."""
        trivial = sum(1 for r in rings if len(r.accounts) <= 2)
        assert trivial == 88
        assert 0.75 < (len(rings) - trivial) / len(rings) < 0.78
