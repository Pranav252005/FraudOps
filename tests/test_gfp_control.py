"""The GFP control's contract: it must refuse to fabricate a comparison.

The failure this guards against is not a crash. It is a session six months
from now reading "GFP control" in the repo, finding a JSON file, and quoting a
parity number that was never measured. So the tests here are mostly about what
the code REFUSES to do.

They also pin the platform finding. `docs/HANDOFF.md` section 4 said the
blocker was "no Python 3.14 build", and commit `d7dba2f` narrowed it to "snapml
is obtainable, just not on 3.14". Both are wrong: snapml's Windows wheels
contain the `GraphFeaturePreprocessor` Python wrapper but none of the `gf_*`
native symbols it calls, at every published version. If that ever changes --
IBM ships a Windows GFP build, or the project moves to Linux -- the test that
asserts the constructor fails will start failing, which is the correct way to
find out.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts import gfp_compare, gfp_control


def test_compare_refuses_without_gfp_features(tmp_path):
    """No GFP feature file means no comparison, not a default or a zero."""
    export = tmp_path / "export"
    export.mkdir()
    (export / "manifest.json").write_text("{}")
    with pytest.raises(SystemExit) as e:
        gfp_compare.compare(export_dir=export,
                            gfp_path=tmp_path / "absent.npz",
                            out=tmp_path / "out.json")
    msg = str(e.value)
    assert "no parity claim" in msg.lower()
    assert "linux" in msg.lower() or "macos" in msg.lower()


def test_compare_refuses_without_export(tmp_path):
    with pytest.raises(SystemExit) as e:
        gfp_compare.compare(export_dir=tmp_path / "nothing",
                            gfp_path=tmp_path / "absent.npz",
                            out=tmp_path / "out.json")
    assert "export" in str(e.value).lower()


def test_gfp_params_are_the_papers_not_ours():
    """The control must not be tuned to this data.

    arXiv:2402.08593's AML configuration: scatter-gather bounded at 6 h, simple
    cycles at 1 day and 10 hops. If someone widens these to make the control
    look better or worse, the comparison stops measuring GFP.
    """
    p = gfp_control.GFP_PARAMS
    assert p["scatter-gather_tw"] == 6 * 3600
    assert p["lc-cycle_tw"] == 24 * 3600
    assert p["lc-cycle_len"] == 10
    assert p["temp-cycle"] and p["fan"] and p["vertex_stats"]
    # The full published moment set, not snapml's default which drops
    # min/max/median.
    assert set(p["vertex_stats_feats"]) == set(range(11))


def test_amount_column_matches_vertex_stats_cols():
    """`vertex_stats_cols` points at the amount column of the edge layout.

    An off-by-one here would silently compute GFP's vertex statistics over
    timestamps or node ids and the comparison would still produce numbers.
    """
    assert gfp_control.EDGE_COLS.index("amount") == \
        gfp_control.GFP_PARAMS["vertex_stats_cols"][0]


def test_split_rule_matches_eval_oracle():
    """`gfp_compare.split_mask` must reproduce `ring_time_split`'s assignment.

    The two are separate implementations -- one over record dicts, one over
    arrays -- and a divergence would compare the two feature blocks on
    different splits while reporting them as the same.
    """
    import numpy as np

    from scripts.eval_oracle import ring_time_split

    rings = {1: 100, 2: 200, 3: 300, 4: 400}
    records = []
    for ring, t in ((1, 100), (2, 200), (3, 300), (4, 400)):
        records.append({"cand": None, "ring": ring, "t": t})
    for t in (150, 250, 350, 450):
        records.append({"cand": None, "ring": None, "t": t})

    train, test, split_t = ring_time_split(records, rings)
    train_ids = {(r["ring"], r["t"]) for r in train}
    test_ids = {(r["ring"], r["t"]) for r in test}

    ring_arr = np.array([r["ring"] if r["ring"] is not None else -1
                         for r in records])
    t_arr = np.array([r["t"] for r in records])
    is_train, is_test, split_t2 = gfp_compare.split_mask(ring_arr, t_arr, rings)

    assert split_t == split_t2
    got_train = {(records[i]["ring"], records[i]["t"])
                 for i in range(len(records)) if is_train[i]}
    got_test = {(records[i]["ring"], records[i]["t"])
                for i in range(len(records)) if is_test[i]}
    assert got_train == train_ids
    assert got_test == test_ids

    # The masks do not partition: dropped rows are in neither. Asserted rather
    # than left implicit, because `~is_train` used to be the test mask and any
    # caller still doing that would silently train on dropped positives.
    assert not (is_train & is_test).any()
    assert (is_train | is_test).sum() <= len(records)


@pytest.mark.skipif(importlib.util.find_spec("snapml") is None,
                    reason="snapml not installed in this interpreter")
def test_gfp_constructor_state_matches_platform():
    """Records the platform finding as an executable assertion.

    On Linux/macOS the constructor works and the control is runnable. On
    Windows it raises AttributeError on `gf_allocate`, because the wrapper
    ships without its native half. Either outcome is informative; a THIRD
    outcome means the situation changed and the docs need revisiting.
    """
    from snapml import GraphFeaturePreprocessor

    if sys.platform.startswith("win"):
        with pytest.raises(AttributeError, match="gf_allocate"):
            GraphFeaturePreprocessor()
    else:
        assert GraphFeaturePreprocessor().get_params()["lc-cycle_len"] == 10
