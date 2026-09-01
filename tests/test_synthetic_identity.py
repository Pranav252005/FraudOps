"""Phase A: the generator, and the properties the kill rule depends on.

These tests do not check that the domain is hard -- that is a measurement, and
`scripts/eval_identity_background.py` makes it. They check the structural claims
the measurement would be meaningless without.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from sentinel.generators import synthetic_identity as gen

ROOT = Path(__file__).resolve().parents[1]


class TestLeakBoundary:
    def test_application_carries_no_label(self):
        """The observable record cannot name the ground truth.

        In a generated domain the labels are written by the same code as the
        data, so the leak boundary is structural rather than statistical. A
        field added here would defeat every prevalence audit downstream.
        """
        fields = {f.name for f in dataclasses.fields(gen.Application)}
        assert fields == {"app_id", "ts", *gen.ATTRS}

    def test_truth_and_observables_are_separate_objects(self):
        w = gen.generate(seed=0, n_apps=400)
        assert w.clusters and w.applications
        assert not any(hasattr(a, "cluster") or hasattr(a, "label")
                       for a in w.applications)


class TestDeterminism:
    def test_same_seed_same_world(self):
        a = gen.generate(seed=3, n_apps=600)
        b = gen.generate(seed=3, n_apps=600)
        assert [x.attrs() for x in a.applications] == [x.attrs() for x in b.applications]
        assert a.clusters == b.clusters

    def test_different_seed_different_world(self):
        """The knob AMLworld does not have, and the reason for a second domain.

        `prereg/cycles.md` records that the AMLworld path has no run-to-run
        randomness anywhere, so "more cycles" is not a knob there. Here it is.
        """
        a = gen.generate(seed=3, n_apps=600)
        b = gen.generate(seed=4, n_apps=600)
        assert [x.attrs() for x in a.applications] != [x.attrs() for x in b.applications]


class TestAdversary:
    @pytest.mark.parametrize("rotation", gen.ROTATION_RATES)
    def test_every_hop_shares_one_and_rotates_one(self, rotation):
        """The two constraints that are the adversarial model.

        Without a shared attribute there is no cluster to find; without a
        rotated one the cluster is a clique that any single attribute spans.
        """
        import random
        rng = random.Random(11)
        vals = gen._Values(rng)
        chain = gen._rotation_chain(12, rotation, 0.0, vals, rng)
        for prev, nxt in zip(chain, chain[1:]):
            shared = [a for a in gen.ATTRS if prev[a] == nxt[a]]
            rotated = [a for a in gen.ATTRS if prev[a] != nxt[a]]
            assert shared, "a hop that shares nothing is not a cluster"
            assert rotated, "a hop that rotates nothing is a clique"

    def test_fragmentation_is_the_design(self):
        """Ends of a long chain share nothing: the finding, by construction.

        This is the property the whole domain was chosen for. In AMLworld the
        seed sees one fragment because the window broke the ring; here it is
        what the adversary built.
        """
        import random
        rng = random.Random(5)
        vals = gen._Values(rng)
        chain = gen._rotation_chain(12, 0.7, 0.0, vals, rng)
        first, last = chain[0], chain[-1]
        assert not any(first[a] == last[a] for a in gen.ATTRS)


class TestBackground:
    def test_mixture_is_over_applications_not_draws(self):
        """One office draw is worth a hundred solo draws.

        Selecting structures at the mixture weights directly put ~79% of the
        population inside offices at a nominal office weight of 0.16, which is
        not the pre-registered background. Selection is weighted by
        `LEGIT_MIX[k] / EXPECTED_SIZE[k]` for exactly this reason.
        """
        counts = {k: 0 for k in gen.LEGIT_MIX}
        total = 0
        for seed in range(6):
            w = gen.generate(seed=seed, n_apps=4000)
            for k, v in w.background["legit_structures"].items():
                counts[k] += v
                total += v
        for k, target in gen.LEGIT_MIX.items():
            share = counts[k] / total
            assert abs(share - target) < 0.12, (k, share, target)

    def test_legitimate_pan_sharing_exists(self):
        """Joint accounts. Without them a shared-PAN count names the adversary."""
        w = gen.generate(seed=1, n_apps=4000)
        fraud = w.fraudulent
        from collections import Counter
        pans = Counter(a.pan for a in w.applications)
        legit_shared = [a for a in w.applications
                        if pans[a.pan] > 1 and a.app_id not in fraud]
        assert legit_shared

    def test_hub_structures_are_present(self):
        """Offices and landlords, which are what defeat the degree baseline."""
        w = gen.generate(seed=1, n_apps=4000)
        per = w.background["per_attribute"]
        assert per["ip"]["max_multiplicity"] >= 20
        assert per["address"]["max_multiplicity"] >= 20


class TestExpectedPrecision:
    def test_ties_are_credited_their_own_rate(self):
        """A deterministic tie-break measures the tie-break, not the baseline.

        Three of the four baselines are small integers, so the top ten is
        routinely a thousand-way tie. Breaking on app_id scored
        `rare_multiplicity` at exactly 0.0000 on the primary configuration,
        which was a fact about id order rather than about the background.
        """
        from scripts.eval_identity_background import p_at_k
        scores = {i: 1 for i in range(100)}
        truth = set(range(25))
        assert p_at_k(scores, truth, 10) == pytest.approx(0.25)

    def test_strict_ordering_still_dominates_ties(self):
        from scripts.eval_identity_background import p_at_k
        scores = {0: 9, 1: 9}
        scores.update({i: 1 for i in range(2, 100)})
        assert p_at_k(scores, {0, 1}, 2) == pytest.approx(1.0)


class TestKillRuleTranscription:
    def test_thresholds_match_the_prereg(self):
        """The runner transcribes the kill rule; a silent divergence is a bug.

        The prereg is the record. If these numbers drift apart, the gate stops
        being the gate that was pre-registered.
        """
        from scripts import eval_identity_background as run
        text = (ROOT / "prereg" / "synthetic_identity_kill_rule.md").read_text(
            encoding="utf-8")
        assert "0.15" in text and "0.12" in text and "3.0x" in text
        assert set(run.ABS_THRESHOLD.values()) == {0.15, 0.12}
        assert run.LIFT_THRESHOLD == 3.0
        assert run.MIN_CONFIGS_PASSING == 18
        assert run.RARE_MAX_MULTIPLICITY == 5

    def test_primary_configuration_is_the_pre_registered_one(self):
        assert gen.PRIMARY == {"rotation_rate": 0.5, "cluster_size": 8,
                               "overlap": 0.1}
