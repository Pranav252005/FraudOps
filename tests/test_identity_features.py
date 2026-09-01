"""Phase C: the identity features, and the leak boundary they are built behind.

The gate that matters here is structural. `scripts/eval_identity_features.py`
measures per-feature AUC as a second arm, but the claim that no feature reads
the generator is a property, and these tests are where it is asserted as one.
"""
from __future__ import annotations

import random
from dataclasses import fields
from pathlib import Path

import pytest

from sentinel.detect import identity_features as IF
from sentinel.eval import identity as ident
from sentinel.generators import synthetic_identity as gen

ROOT = Path(__file__).resolve().parents[1]
SMALL = {"n_apps": 600, **gen.PRIMARY}


@pytest.fixture(scope="module")
def scene():
    world = gen.generate(seed=7, **SMALL)
    _, candidates, _ = ident.run_identity_funnel(world)
    graph, _ = ident.build_graph(world)
    apps = {a.app_id: a for a in world.applications}
    counts = IF.population_counts(world.applications)
    return world, candidates, graph, apps, counts


def _vectors(candidates, graph, apps, counts):
    return [IF.build(c.nodes, graph, apps, counts).to_dict() for c in candidates]


class TestTheLeakBoundary:
    def test_the_builder_is_never_handed_the_truth(self):
        """`build` takes nodes, graph and applications. Not a World.

        The truth is not in scope to be read by accident, which is a stronger
        statement than "no feature currently reads it".
        """
        import inspect
        params = list(inspect.signature(IF.build).parameters)
        assert params == ["nodes", "graph", "apps", "global_counts"]

    def test_the_module_cannot_reach_the_evaluation_side(self):
        """Checked on the IMPORTS, not on the prose.

        A substring scan over the source would be satisfied by renaming a
        comment, and would fail on a docstring that merely explains why the
        World is out of scope. The AST is the claim.
        """
        import ast
        tree = ast.parse(Path(IF.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported |= {a.name for a in node.names}
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")
                imported |= {f"{node.module}.{a.name}" for a in node.names}
        assert not any(m.startswith("sentinel.eval") for m in imported)
        assert not any(m.endswith(".World") or m == "World" for m in imported)
        assert imported & {"sentinel.generators.synthetic_identity.ATTRS"}

    def test_relabelling_the_truth_changes_nothing(self, scene):
        """Arm 1 of the pre-registered gate, as a property.

        Applications are reassigned to different clusters -- a real
        reassignment, not a renaming of ids -- and every feature value must
        come back bit-identical. A feature that moves when only the labels
        moved is reading the labels.
        """
        world, candidates, graph, apps, counts = scene
        before = _vectors(candidates, graph, apps, counts)

        rng = random.Random("relabel")
        ids = [i for c in world.clusters for i in c]
        rng.shuffle(ids)
        at, permuted = 0, []
        for c in world.clusters:
            permuted.append(set(ids[at:at + len(c)]))
            at += len(c)
        world.clusters = permuted

        assert _vectors(candidates, graph, apps, counts) == before


class TestForbiddenInputs:
    def test_no_feature_reads_an_application_index(self, scene):
        """`app_id` is an index. It is shuffled, so it carries nothing today --
        which is exactly why a feature reading it would go unnoticed."""
        world, candidates, graph, apps, counts = scene
        before = _vectors(candidates, graph, apps, counts)

        shift = 10_000
        shifted_apps = {i + shift: type(a)(app_id=a.app_id + shift, ts=a.ts,
                                            **{k: getattr(a, k) for k in gen.ATTRS})
                        for i, a in apps.items()}
        shifted = [IF.build({n + shift for n in c.nodes}, _ShiftedGraph(graph, shift),
                             shifted_apps, counts).to_dict() for c in candidates]
        assert shifted == before

    def test_no_feature_reads_an_absolute_timestamp(self, scene):
        """The 90-day span is a generator parameter. Differences are data; a
        position inside a chosen span is not."""
        world, candidates, graph, apps, counts = scene
        before = _vectors(candidates, graph, apps, counts)

        shift = 5000
        moved = {i: type(a)(app_id=a.app_id, ts=a.ts + shift,
                            **{k: getattr(a, k) for k in gen.ATTRS})
                 for i, a in apps.items()}
        assert _vectors(candidates, graph, moved, counts) == before

    def test_the_forbidden_list_says_what_it_forbids(self):
        assert IF.FORBIDDEN_INPUTS == {"app_id", "ts_absolute"}


class _ShiftedGraph:
    """A graph view with node ids offset, for the index-invariance test only."""

    def __init__(self, graph, shift):
        self._g, self._s = graph, shift

    def neighbours(self, node):
        return {v + self._s for v in self._g.neighbours(node - self._s)}


class TestTheExclusions:
    def test_the_excluded_features_are_the_ones_the_rule_names(self):
        """Attributes whose legitimate ceiling is a generator structure size.

        pan is bounded at 3 by joint accounts; phone and device at 5 by
        households. address and ip have landlords and offices behind them, so
        their legitimate tails are heavy and they are kept. Measured numbers
        are in data/identity_features.json.
        """
        assert IF.EXCLUDED_FEATURES_IDENTITY == {
            "max_pan_fanout", "max_phone_fanout", "max_device_fanout"}

    def test_excluded_columns_survive_in_the_record(self, scene):
        """A column that vanishes cannot be checked against the numbers that
        justified removing it, so `to_dict` keeps them and `vector` drops
        them."""
        world, candidates, graph, apps, counts = scene
        f = IF.build(candidates[0].nodes, graph, apps, counts)
        assert IF.EXCLUDED_FEATURES_IDENTITY <= set(f.to_dict())
        assert not (IF.EXCLUDED_FEATURES_IDENTITY & set(f.vector()))

    def test_feature_names_are_the_scorer_s_view(self):
        names = IF.feature_names()
        assert names == sorted(names)
        assert not (set(names) & IF.EXCLUDED_FEATURES_IDENTITY)


class TestWhatDidNotSurviveTheDomainChange:
    def test_no_flow_feature_was_ported(self):
        """Onboarding applications have no amounts and no direction, so these
        are not weak here -- they are undefined."""
        names = {f.name for f in fields(IF.IdentityFeatures)}
        for dead in ("passthrough", "conservation", "velocity", "layer",
                     "amount", "inflow", "outflow", "churn", "burstiness"):
            assert not any(dead in n for n in names), dead

    def test_the_fragmentation_family_is_present_even_though_it_is_flat(self):
        """`n_components` is constant across candidates and that is a finding.

        Expansion returns a connected node set by construction, so a candidate
        cannot be internally fragmented -- fragmentation is a property of the
        ground-truth cluster against what the seed reached, which is Phase D's
        measurement and not a feature. The columns stay so the flatness is
        visible in the AUC table rather than absent from it.
        """
        names = {f.name for f in fields(IF.IdentityFeatures)}
        assert {"n_components", "largest_component_share"} <= names


class TestGateTranscription:
    def test_thresholds_match_the_prereg(self):
        from scripts import eval_identity_features as run
        text = (ROOT / "prereg" / "synthetic_identity_features.md").read_text(
            encoding="utf-8")
        assert "0.99" in text
        assert run.LEAK_AUC == 0.99
        assert run.MAX_TRIPPING_FEATURES == 5

    def test_auc_is_symmetric_and_credits_ties(self):
        from scripts.eval_identity_features import auc
        assert auc([1, 2, 3, 4], [0, 0, 1, 1]) == pytest.approx(1.0)
        assert auc([1, 1, 1, 1], [0, 0, 1, 1]) == pytest.approx(0.5)
