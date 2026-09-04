"""The dataset registry, and the three things it has to guarantee.

Parameterising the split is the easy half. The half that matters is that
several constants in `sentinel/config.py` are MEASUREMENTS OF HI-Small rather
than settings -- `EVAL_END_DAY` is a leak boundary derived from where that
generator run's edge density collapses, and `STRUCTURAL_RECALL_CEILING` is a
ring-size count. Carrying either onto another split would not crash. It would
leak or silently discard data, and every interval downstream would be wrong.

So this pins:

  1. HI-Small's numbers did not move when the indirection went in. The whole
     change is worthless if it altered the shipped result.
  2. An underived split RAISES, and a derived one does not. Both arms, because
     a refusal that cannot fire is not a refusal.
  3. No entry point hardcodes a split filename any more, so a new script cannot
     quietly reintroduce the coupling this file exists to remove.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from sentinel.data.datasets import (Dataset, DEFAULT, ENV_VAR, REGISTRY,
                                    DatasetNotDerived, active, count_rings)

ROOT = Path(__file__).resolve().parent.parent


class TestHiSmallDidNotMove:
    """The regression arm. These are the values that were hardcoded in
    sentinel/config.py before the registry existed."""

    def test_the_default_split_is_still_hi_small(self):
        assert DEFAULT == "HI-Small"
        assert active({}).name == "HI-Small"

    def test_the_leak_boundary_is_unchanged(self):
        assert REGISTRY["HI-Small"].require_eval_end_day() == 10

    def test_the_structural_ceiling_is_unchanged(self):
        assert REGISTRY["HI-Small"].require_structural_recall_ceiling() == 0.733

    def test_config_still_exposes_the_same_values(self):
        from sentinel import config
        assert config.EVAL_END_DAY == 10
        assert config.STRUCTURAL_RECALL_CEILING == 0.733
        assert config.EVAL_END == 10 * config.MINUTES_PER_DAY


class TestTheRefusalHasBothArms:

    def test_an_underived_split_refuses_with_the_command_to_fix_it(self):
        """Asserted against a SYNTHETIC split, not a registered one.

        This test used to name LI-Small and HI-Medium, and it broke the moment
        they were derived on 2026-09-05 -- a test that fails because the
        project made progress is a test pinned to the wrong thing. The property
        worth keeping is that an underived split refuses AND says how to fix
        itself; that property is about the mechanism, not about which splits
        happen to be characterised today.
        """
        d = Dataset(name="Fake-Split", corpus_key="amlworld-fake")
        with pytest.raises(DatasetNotDerived) as exc:
            d.require_eval_end_day()
        msg = str(exc.value)
        # The message has to carry the remedy, or it is just an error.
        assert "derive_dataset_constants.py" in msg
        assert "Fake-Split" in msg
        with pytest.raises(DatasetNotDerived):
            d.require_structural_recall_ceiling()

    def test_every_registered_split_is_now_derived(self):
        """The complement, and the thing that actually changed today.

        Both halves matter: the mechanism must refuse an underived split, and
        the registry must no longer contain one. If a future split is added
        without constants this fails loudly rather than waiting for an
        evaluation to be run against a borrowed boundary.
        """
        for name, d in REGISTRY.items():
            assert d.require_eval_end_day() is not None, name
            assert d.require_structural_recall_ceiling() is not None, name

    def test_hi_medium_does_not_borrow_hi_smalls_boundary(self):
        """The concrete reason this module refuses to default.

        HI-Medium's leak begins on day 16. Carrying HI-Small's 10 across would
        have silently discarded six days of good data with nothing crashing,
        which is exactly the failure the refusal exists to prevent.
        """
        assert REGISTRY["HI-Medium"].require_eval_end_day() == 16
        assert REGISTRY["HI-Small"].require_eval_end_day() == 10

    def test_a_derived_split_does_not_refuse(self):
        """The other arm. Without it, a registry where EVERY split raised
        would pass the test above."""
        assert REGISTRY["HI-Small"].require_eval_end_day() == 10

    def test_an_unknown_split_is_refused_by_name(self):
        with pytest.raises(KeyError):
            active({ENV_VAR: "HI-Enormous"})

    def test_selecting_a_known_split_works(self):
        assert active({ENV_VAR: "LI-Small"}).name == "LI-Small"


class TestNothingHardcodesASplitFilename:
    """Guards the coupling this module removed.

    A grep-shaped test rather than an import-shaped one, because the failure it
    prevents is a NEW script written next month that types the filename again.
    Nothing would break; it would just silently keep reading HI-Small while the
    environment said otherwise -- and it would agree with itself, which is the
    worst kind of wrong here.
    """

    PATTERN = re.compile(r'"(?:HI|LI)-(?:Small|Medium|Large)_'
                         r'(?:Trans\.csv|accounts\.csv|Patterns\.txt)"')

    def _offenders(self) -> list[str]:
        out = []
        for p in list((ROOT / "scripts").glob("*.py")) + \
                 list((ROOT / "sentinel").rglob("*.py")):
            if "__pycache__" in p.parts:
                continue
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if line.lstrip().startswith("#"):
                    continue            # prose about the data is fine
                if self.PATTERN.search(line):
                    out.append(f"{p.relative_to(ROOT)}:{i}")
        return out

    def test_no_entry_point_types_a_split_filename(self):
        offenders = self._offenders()
        assert not offenders, (
            "these lines hardcode an AMLworld split filename instead of using "
            "DATASET.trans/accounts/patterns(ROOT): " + ", ".join(offenders) +
            ". A hardcoded path ignores SENTINEL_DATASET silently -- the "
            "script keeps reading HI-Small while every other part of the run "
            "believes it is on another split.")

    def test_the_pattern_actually_matches_something(self):
        """Negative control: a grep test whose regex matches nothing passes
        vacuously forever."""
        assert self.PATTERN.search('x = RAW / "HI-Small_Trans.csv"')
        assert not self.PATTERN.search('x = DATASET.trans(ROOT)')


class TestRingCountsComeFromTheFiles:
    """Counted, never typed -- rule 1 applied to the one number that would
    otherwise be tempting to write down per split."""

    def test_ring_counts_are_read_from_disk_when_present(self):
        present = [d for d in REGISTRY.values() if d.present(ROOT)]
        if not present:
            pytest.skip("no AMLworld split downloaded")
        for d in present:
            n = count_rings(d, ROOT)
            assert n > 0
        names = {d.name for d in present}
        if {"HI-Small", "LI-Small"} <= names:
            # The reason LI-Small is a replication check and NOT a sample-size
            # fix: it has FEWER labelled rings, so it widens intervals.
            assert (count_rings(REGISTRY["LI-Small"], ROOT)
                    < count_rings(REGISTRY["HI-Small"], ROOT))

    def test_a_missing_split_says_how_to_fetch_it(self):
        from sentinel.data.datasets import Dataset
        ghost = Dataset(name="HI-Nonexistent", corpus_key="amlworld-ghost")
        with pytest.raises(FileNotFoundError) as exc:
            count_rings(ghost, ROOT)
        assert "download_amlworld" in str(exc.value)
