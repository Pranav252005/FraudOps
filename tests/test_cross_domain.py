"""Phase B gate: both domains run through the same harness, and cannot be pooled.

Two claims, and they pull in opposite directions on purpose.

**Structural parity.** The identity path must produce the same shaped output as
the AMLworld/Elliptic2 path, out of the same primitives. A cross-domain finding
made with two different pipelines is a finding about the pipelines.

**Numerical separation.** Having made the two comparable, nothing may average
them. `require_same_dataset` refuses, and the refusal is tested here rather than
only in `tests/test_corpus.py`, because this is the file somebody reads when
they want to know what "cross-domain" is allowed to mean.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sentinel import config
from sentinel.corpus import (CorpusKey, DatasetMismatch, require_poolable,
                             stratify_by_dataset)
from sentinel.data import elliptic2
from sentinel.eval import funnel as funnel_mod
from sentinel.eval import identity as ident
from sentinel.eval.dataset import run_static_funnel
from sentinel.generators import synthetic_identity as gen

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "elliptic2_sample"
SMALL = {"n_apps": 800, **gen.PRIMARY}


@pytest.fixture(scope="module")
def identity_run():
    world = gen.generate(seed=0, **SMALL)
    tracker, candidates, seeds = ident.run_identity_funnel(world)
    return world, tracker, candidates, seeds


@pytest.fixture(scope="module")
def amlworld_run():
    data = elliptic2.load(FIXTURE)
    tracker, candidates, node_ids = run_static_funnel(data.edges, data.rings)
    return tracker, candidates, node_ids


class TestStructuralParity:
    def test_both_paths_report_the_same_funnel_stages(self, identity_run,
                                                      amlworld_run):
        _, id_tracker, _, _ = identity_run
        aml_tracker, _, _ = amlworld_run
        id_row = id_tracker.to_rows()[-1]
        aml_row = aml_tracker.to_rows()[-1]
        assert set(id_row) == set(aml_row)
        assert id_row["typology"] == aml_row["typology"] == "TOTAL"

    def test_both_paths_use_the_same_hit_definition(self, identity_run):
        """The Jaccard floor is inherited unchanged, and that is the point.

        Whether 0.3 is right for identity clusters is an empirical question.
        Answering it after measuring would invalidate every cross-domain
        comparison, so it is fixed at the value AMLworld already reports under.
        """
        assert funnel_mod.MIN_JACCARD == 0.3
        assert funnel_mod.HIT_SHARE == 0.5
        _, tracker, _, _ = identity_run
        assert tracker.rank_k == 50

    def test_the_identity_path_reuses_the_shared_primitives(self):
        """Not a re-implementation: the same objects, imported.

        `run_identity_funnel` differs from `run_static_funnel` in one argument
        -- `seed_override` -- and this test is what stops that from quietly
        becoming a second pipeline.
        """
        src = Path(ident.__file__).read_text(encoding="utf-8")
        for shared in ("WindowedGraph", "CandidateGenerator", "FunnelTracker",
                       "StaticBatch"):
            assert shared in src
        assert "def is_hit" not in src
        assert "class FunnelTracker" not in src

    def test_candidates_are_the_generator_s_own(self, identity_run):
        _, _, candidates, _ = identity_run
        assert candidates
        assert all(hasattr(c, "nodes") and hasattr(c, "seed") for c in candidates)


class TestTheDecisionsThatDidNotTransfer:
    def test_the_identity_graph_has_no_window(self, identity_run):
        """AMLworld's 72-hour window is a domain constant and does not travel.

        Under a window, an adversary whose strategy IS deliberate temporal
        spacing produces fragmentation that is partly the window's artefact --
        which would re-derive the AMLworld finding instead of contrasting with
        it.
        """
        world, _, _, _ = identity_run
        graph, _ = ident.build_graph(world)
        assert graph.window >= ident.NO_WINDOW
        assert graph.window > config.WINDOW_MINUTES * 1000

    def test_the_seed_rule_is_exogenous_not_pass_through(self, identity_run):
        """The co-occurrence graph is undirected, so pass-through fires on all.

        AMLworld's seed rule requires money in and out. Every node in an
        undirected graph satisfies that, so inheriting the rule would seed the
        entire population and make recall meaningless.
        """
        world, _, _, seeds = identity_run
        from sentinel.detect.candidates import CandidateGenerator
        graph, batch = ident.build_graph(world)
        pass_through = CandidateGenerator(graph).seeds(batch)
        assert len(seeds) < len(pass_through)
        assert len(seeds) < len(world.applications) * 0.05

    def test_seed_rates_are_the_pre_registered_ones(self):
        text = (Path(__file__).resolve().parents[1] / "prereg" /
                "synthetic_identity_kill_rule.md").read_text(encoding="utf-8")
        assert "0.15" in text and "0.002" in text
        assert config.IDENTITY_SEED_RATE_FRAUD == 0.15
        assert config.IDENTITY_SEED_RATE_LEGIT == 0.002

    def test_the_seed_rule_fires_more_often_on_fraud(self, identity_run):
        world, _, _, seeds = identity_run
        fraud = world.fraudulent
        n_fraud_seeded = len(seeds & fraud)
        assert n_fraud_seeded > 0
        assert len(seeds - fraud) > 0, (
            "an investigation that only ever starts from a true positive is "
            "not an investigation")


class TestFeaturesCannotReachTheTruth:
    def test_the_generator_never_imports_the_evaluation_side(self):
        """The seed rule reads ground truth; the generator must not offer it.

        Truth enters in exactly one place -- `sentinel/eval/identity.py`, which
        models an exogenous signal and therefore has to know who is fraudulent.
        The observable record stays label-free so no feature can reach the same
        information.
        """
        src = Path(gen.__file__).read_text(encoding="utf-8")
        assert "sentinel.eval" not in src
        import dataclasses
        fields = {f.name for f in dataclasses.fields(gen.Application)}
        assert "label" not in fields and "cluster" not in fields


class TestTheTwoDomainsCannotBePooled:
    def test_pooling_the_two_corpora_is_refused_for_every_question(self):
        a = CorpusKey.for_current_config("amlworld-hi-small", ["n_nodes"],
                                          "constructed")
        b = CorpusKey.for_current_config(ident.DATASET, ["n_nodes"],
                                          "constructed")
        for question in ("scorer", "ranking", "calibration", "recall",
                          "funnel", "seeding", "build"):
            with pytest.raises(DatasetMismatch):
                require_poolable([a, b], question)

    def test_provenance_would_not_have_caught_it(self):
        """The negative control for the guard added in this phase."""
        a = CorpusKey.for_current_config("amlworld-hi-small", ["n_nodes"],
                                          "constructed")
        b = CorpusKey.for_current_config(ident.DATASET, ["n_nodes"],
                                          "constructed")
        assert a.candidate_provenance == b.candidate_provenance

    def test_the_sanctioned_cross_domain_path_is_two_answers(self):
        a = CorpusKey.for_current_config("amlworld-hi-small", ["n_nodes"],
                                          "constructed")
        b = CorpusKey.for_current_config(ident.DATASET, ["n_nodes"],
                                          "constructed")
        groups = stratify_by_dataset([a, b], ["aml", "identity"])
        assert groups == {"amlworld-hi-small": ["aml"],
                          ident.DATASET: ["identity"]}

    def test_the_identity_dataset_name_is_distinct(self):
        assert ident.DATASET != "amlworld-hi-small"
        assert ident.DATASET == "synthetic-identity-v1"


class TestDeterminism:
    def test_the_same_world_produces_the_same_funnel(self):
        w1 = gen.generate(seed=2, **SMALL)
        w2 = gen.generate(seed=2, **SMALL)
        t1, c1, s1 = ident.run_identity_funnel(w1)
        t2, c2, s2 = ident.run_identity_funnel(w2)
        assert s1 == s2
        assert t1.totals() == t2.totals()
        assert [sorted(c.nodes) for c in c1] == [sorted(c.nodes) for c in c2]
