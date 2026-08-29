"""Guards on the listwise-ranker experiment's setup (scripts/eval_ranker.py).

The size-blind feature subset is the mechanism by which the size re-tie is
avoided *by construction* rather than patched after the fact. That guarantee
holds only while every feature is deliberately classified, so the classification
is asserted here: a feature added later that nobody classifies must fail the
build rather than default into the size-blind set.
"""
from __future__ import annotations

from sentinel.detect.features import Features
from sentinel.learn.reranker import feature_names

from scripts.eval_ranker import EXTENSIVE, INTENSIVE, _partition


def test_every_feature_is_classified_intensive_or_extensive():
    names = feature_names(Features())
    unclassified = [n for n in names
                    if n not in INTENSIVE and n not in EXTENSIVE]
    assert unclassified == [], (
        f"unclassified features: {unclassified}. Add each to INTENSIVE or "
        f"EXTENSIVE in scripts/eval_ranker.py -- letting one default into the "
        f"size-blind subset would silently break the only property that subset "
        f"exists to guarantee.")


def test_the_two_sets_do_not_overlap():
    assert not (INTENSIVE & EXTENSIVE)


def test_partition_raises_on_an_unknown_feature():
    import pytest
    with pytest.raises(AssertionError):
        _partition(["conservation", "a_feature_nobody_classified"])


def test_the_size_blind_subset_excludes_every_obvious_size_proxy():
    """Named explicitly, so a future edit that moves one is a visible diff."""
    for name in ("n_nodes", "n_edges", "n_txns", "total_amount", "inflow",
                 "outflow", "internal", "max_fan", "fan_in_count",
                 "fan_out_count", "n_banks", "n_entities"):
        assert name not in INTENSIVE, f"{name} is not size-blind"
