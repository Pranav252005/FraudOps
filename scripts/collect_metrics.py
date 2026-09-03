"""Phase 4.1 -- gather every reported number into one file, under contract.

A number currently lives in 1,835 places across README and docs/, so it can be
wrong in 1,835 places. `0.2778` alone appears 14 times in README and has been
wrong twice over: the supervised p@10 moved to 0.2500 when two inverted blend
weights were retired, and to 0.2111 when the dead query groups were closed.
Nobody edited the README either time.

This reads the eval artefacts and emits `results/metrics.json` through
`sentinel.report.write`, which accepts only `Metric` objects -- and a `Metric`
cannot be constructed without its interval, its clustering, its size baseline
where it is a p@k, and its conditioning where it is ring-unit. So the constraint
"a number without its context cannot be published" is a type, not a convention.

THIS SCRIPT COMPUTES NOTHING. Every value is read from an artefact written by
the script that measured it. If a number is missing here, the fix is to run the
measurement, never to fill it in.

Run:  python scripts/collect_metrics.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.eval.bootstrap import bootstrap_ci, ratio_of_sums
from sentinel.report import Metric, write

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "results" / "metrics.json"

CYCLE = "cycle_clustered_bootstrap"
WIDER = "wider_of_cycle_and_ring_clustered_bootstrap"

# The conditioning that must travel with the ring-unit metric, taken from the
# script that produces it rather than restated here.
RING_UNIT_CONDITIONING = (
    "P(ring in top 10 of its cycle | the ring was BUILT). It cannot see the "
    "26.6 points lost at the build stage, where BIPARTITE and STACK are lost "
    "systematically rather than at random, so it reads HIGHER than the "
    "unconditioned p@k and is not comparable to it. p@k with its size "
    "baseline remains the reported number.")

WORLD = "world_clustered_bootstrap"
PAIRED_WORLD = "paired_world_clustered_bootstrap"

# The conditioning that must travel with every seed-reach coverage number, in
# either domain: a group with no seeded member is EXCLUDED, not scored zero.
COVERAGE_CONDITIONING = (
    "P(group members reachable | the group had at least one seeded member). "
    "Groups no seed landed in are excluded rather than scored zero, so this "
    "cannot see what seeding lost -- it measures reach, not detection, and is "
    "not comparable to a p@k.")

SEED_CHEAT_CONDITIONING = (
    "CEILING DIAGNOSTIC, not a result. The cheat arm seeds on every active "
    "ring's own members, which the real detector can never do. This is the "
    "headroom behind the seed rule, not an achievable score.")


def _load(rel: str):
    path = ROOT / rel
    if not path.exists():
        raise SystemExit(f"missing {rel}; run the measurement that writes it")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    oracle = _load("data/eval_oracle.json")
    ranker = _load("data/eval_ranker.json")
    prize = _load("data/eval_seeding_prize.json")
    ring_unit = _load("data/eval_ring_unit.json")
    noise = _load("data/eval_label_tax_noise.json")
    budget = _load("data/eval_label_tax_budget.json")
    diff = _load("data/eval_seed_cheat_diff.json")

    arm = oracle["oracle_as_is"]
    n_cycles = arm["cycles"]
    metrics: list[Metric] = []

    def pk(name: str, wire: str, k: int) -> Metric:
        """One p@k from run 1, with the size baseline the rule requires."""
        ci = arm["precision_ci"][f"{wire}@{k}"]
        return Metric(
            id=f"{name}_p_at_{k}", value=arm["precision_at"][str(k)][wire],
            k=k, size_baseline=arm["precision_at"][str(k)]["size"],
            n_units=n_cycles, unit="cycle",
            ci_lower=ci["lo"], ci_upper=ci["hi"], ci_method=CYCLE,
            source="data/eval_oracle.json (run 1, as-is seeding)")

    for k in (10, 20, 50):
        metrics.append(pk("supervised", "oracle", k))
        metrics.append(pk("blend", "blend", k))
        metrics.append(pk("size", "size", k))

    # Paired deltas. `k` is set, so the size baseline is required here too --
    # a delta at depth k is still a claim about depth k and is still quoted
    # against what counting nodes achieves there.
    for other, label in (("blend", "supervised_over_blend"),
                         ("random", "supervised_over_random"),
                         ("size", "supervised_over_size")):
        for k in (10, 20, 50):
            d = arm["paired"][f"oracle-{other}@{k}"]
            metrics.append(Metric(
                id=f"{label}_delta_at_{k}", value=d["point"], k=k,
                size_baseline=arm["precision_at"][str(k)]["size"],
                n_units=n_cycles, unit="cycle",
                ci_lower=d["lo"], ci_upper=d["hi"], ci_method=CYCLE,
                source="data/eval_oracle.json paired bootstrap",
                notes=(f"supervised {d['b']:.4f} minus {other} {d['a']:.4f}",
                       "excludes zero" if d["excludes_zero"]
                       else "INCLUDES ZERO")))

    # LambdaMART against the pointwise model it would replace.
    for k in (10, 20, 50):
        d = ranker["head_to_head_vs_pointwise"][f"lambdamart-pointwise@{k}"]
        metrics.append(Metric(
            id=f"lambdamart_over_pointwise_delta_at_{k}", value=d["point"],
            k=k, size_baseline=ranker["precision_at"][str(k)]["size"],
            n_units=ranker["n_cycles"], unit="cycle",
            ci_lower=d["lo"], ci_upper=d["hi"], ci_method=CYCLE,
            source="data/eval_ranker.json head_to_head_vs_pointwise",
            notes=(f"lambdamart {d['b']:.4f} minus pointwise {d['a']:.4f}",
                   "excludes zero" if d["excludes_zero"] else "INCLUDES ZERO")))
        metrics.append(Metric(
            id=f"lambdamart_p_at_{k}",
            value=ranker["precision_at"][str(k)]["lambdamart"], k=k,
            size_baseline=ranker["precision_at"][str(k)]["size"],
            n_units=ranker["n_cycles"], unit="cycle",
            ci_lower=ranker["precision_ci"][f"lambdamart@{k}"]["lo"],
            ci_upper=ranker["precision_ci"][f"lambdamart@{k}"]["hi"],
            ci_method=CYCLE, source="data/eval_ranker.json"))

    # Distinct-ring p@k: the same ranking counted once per RING rather than
    # once per candidate. Carried because the candidate-level denominator
    # inflates every level in the table -- a cycle emitting three surviving
    # candidates for one ring pays three times for one detection -- and the
    # size of that inflation is a number, not an adjective.
    for name, wire in (("pointwise", "pointwise"), ("blend", "blend"),
                       ("size", "size")):
        v = ranker["distinct_ring_precision_at"]["10"][wire]
        ci = ranker["distinct_ring_precision_ci"][f"{wire}@10"]
        metrics.append(Metric(
            id=f"distinct_ring_{name}_p_at_10", value=v, k=10,
            size_baseline=ranker["distinct_ring_precision_at"]["10"]["size"],
            n_units=ranker["n_cycles"], unit="cycle",
            ci_lower=ci["lo"], ci_upper=ci["hi"], ci_method=CYCLE,
            source="data/eval_ranker.json distinct_ring_precision_at",
            notes=("counted once per ring; the candidate-level figure is "
                   "higher because duplicate candidates for one ring each "
                   "score a hit",)))

    # The seeding prize. A ratio must carry the absolute values it is a ratio
    # of -- this project has already published a "2.8x" that was not a ratio of
    # anything, because its two halves had different denominators.
    for rank in ("blend", "oracle", "size"):
        p = prize["prize"][f"{rank}@10"]
        metrics.append(Metric(
            id=f"seeding_prize_{rank}_ratio_at_10", value=p["ratio"],
            n_units=p["n_cycles"], unit="cycle",
            ci_lower=p["ratio_lo"], ci_upper=p["ratio_hi"], ci_method=CYCLE,
            source="data/eval_seeding_prize.json",
            conditioning=SEED_CHEAT_CONDITIONING,
            notes=(f"as-is p@10 {p['as_is']:.4f} -> cheat p@10 "
                   f"{p['cheat']:.4f}",
                   f"paired delta {p['delta']:+.4f} "
                   f"[{p['delta_lo']:+.4f}, {p['delta_hi']:+.4f}]")))

    # The ring-unit metric: unit="ring", so the banner is mandatory.
    for name in ("supervised", "blend", "size"):
        r = ring_unit["rankings"][name]
        metrics.append(Metric(
            id=f"ring_unit_{name}_surfaced_at_10", value=r["point"],
            n_units=r["n_rings"], unit="ring",
            ci_lower=r["lo"], ci_upper=r["hi"], ci_method=WIDER,
            conditioning=RING_UNIT_CONDITIONING,
            source="data/eval_ring_unit.json",
            notes=(f"{r['n_trials']} ring-trials from {r['n_rings']} distinct "
                   f"rings across {r['n_cycles']} cycles",
                   f"cycle-clustered width {r['cycle_clustered']['width']:.4f} "
                   f"vs ring-clustered {r['ring_clustered']['width']:.4f}; "
                   f"the wider is reported")))

    # Label tax, both arms, never combined.
    nf = noise["fit"]
    metrics.append(Metric(
        id="label_tax_noise_slope_per_0_1",
        value=nf["label_tax_slope_per_0.1"],
        n_units=noise["n_cycles"], unit="cycle",
        ci_lower=nf["label_tax_slope_ci"]["lo"] * 0.1,
        ci_upper=nf["label_tax_slope_ci"]["hi"] * 0.1,
        ci_method=CYCLE, source="data/eval_label_tax_noise.json",
        notes=("delta p@10 per 0.1 increase in the positive-label flip rate",
               "raw minus prevalence-matched control; the control alone "
               "includes zero, so this is not prevalence drift",
               f"pre-registered at {noise['prereg']} commit "
               f"{noise['prereg_commit'][:7]}")))
    bf = budget["fit"]
    metrics.append(Metric(
        id="label_tax_budget_slope_per_halving",
        value=-bf["slope_per_halving"],
        n_units=budget["n_cycles"], unit="cycle",
        ci_lower=-bf["slope_ci"]["hi"], ci_upper=-bf["slope_ci"]["lo"],
        ci_method=CYCLE, source="data/eval_label_tax_budget.json",
        notes=("delta p@10 per halving of the label budget; negated so the "
               "sign reads as a cost",
               "NOT comparable to the noise arm and never to be averaged "
               "with it -- different interventions, separate preregistrations",
               f"pre-registered at {budget['prereg']} commit "
               f"{budget['prereg_commit'][:7]}")))

    # The SHIPPED scorer over all 34 cycles (scripts/eval_phase2.py). This is a
    # different experiment from run 1 above -- all 34 cycles rather than 18
    # held out, no supervised model anywhere in it -- and the two are kept
    # under distinct id prefixes so a template cannot accidentally quote one
    # where it means the other. That confusion is exactly what produced the
    # "2.8x" that was not a ratio of anything (uplift plan item 0.2).
    phase2 = _load("data/eval_phase2.json")
    n34 = phase2["runs"]
    # eval_phase2 stores no interval on the LEVELS, only on score-minus-size.
    # The levels are therefore bootstrapped here from its stored `cycle_rows`,
    # with the same estimator and the same resampling unit the rest of the
    # repository uses.
    #
    # An earlier version of this file instead derived the level's interval as
    # `size + delta_CI`. That was wrong and is recorded rather than quietly
    # replaced: score = size + delta, so the variance of the level includes the
    # variance of `size`, and an interval built from the delta alone omits it.
    # It would have been too NARROW, while carrying a note claiming it was
    # conservative -- an unmeasured claim about an unmeasured interval, which
    # is precisely what rule 1 forbids.
    rows34 = phase2["cycle_rows"]
    for k in (10, 20, 50, 100):
        for name, wire in (("shipped_score", "score"), ("shipped_size", "size"),
                           ("shipped_degree", "degree"),
                           ("shipped_random", "random")):
            stat = ratio_of_sums(f"{wire}_hit_{k}", f"{wire}_n_{k}")
            ci = bootstrap_ci(rows34, stat)
            metrics.append(Metric(
                id=f"{name}_p_at_{k}", value=ci["point"], k=k,
                size_baseline=phase2["precision"]["size"][str(k)],
                n_units=ci["n_units"], unit="cycle",
                ci_lower=ci["lo"], ci_upper=ci["hi"], ci_method=CYCLE,
                source="data/eval_phase2.json cycle_rows, bootstrapped here",
                notes=("shipped v1 hand-set scorer over all 34 generation "
                       "cycles -- a DIFFERENT experiment from run 1's 18 "
                       "held-out cycles, and not comparable to it",)))
        d = phase2["score_minus_size"][str(k)]
        metrics.append(Metric(
            id=f"shipped_score_over_size_delta_at_{k}", value=d["point"], k=k,
            size_baseline=phase2["precision"]["size"][str(k)],
            n_units=d["n_units"], unit="cycle",
            ci_lower=d["lo"], ci_upper=d["hi"], ci_method=CYCLE,
            source="data/eval_phase2.json score_minus_size",
            notes=(f"score {d['b']:.4f} minus size {d['a']:.4f}",
                   "excludes zero" if d["excludes_zero"] else "INCLUDES ZERO")))

    # --- the second domain ---------------------------------------------------
    # Read from the artefacts the identity measurements wrote, exactly as
    # everything above is. Nothing here computes.
    frag = _load("data/fragmentation.json")
    background = _load("data/identity_background.json")
    features = _load("data/identity_features.json")

    primary = next(r for r in frag["primary"]
                   if r["params"]["rotation_rate"] == 0.5
                   and r["params"]["overlap"] == 0.1)
    identity_prevalence = next(
        r["prevalence"] for r in background["results"]
        if all(r["params"][k] == v for k, v in
               {"rotation_rate": 0.5, "cluster_size": 8, "overlap": 0.1}.items()))

    cov = primary["coverage"]
    metrics.append(Metric(
        id="identity_seed_reach_coverage", value=cov["point"],
        n_units=primary["n_worlds"], unit="world",
        ci_lower=cov["lo"], ci_upper=cov["hi"], ci_method=WORLD,
        dataset="synthetic-identity-v1", prevalence=identity_prevalence,
        conditioning=COVERAGE_CONDITIONING,
        source="data/fragmentation.json primary, rotation 0.5 / size 8 / overlap 0.1",
        notes=("seed-reach coverage under the shipped expansion constants",
               "NOT a p@k and not comparable to one")))

    delta = frag["predictions"]["overlap=0.1"]["P2_delta"]
    metrics.append(Metric(
        id="identity_coverage_delta_rotation", value=delta["point"],
        n_units=delta["n_pairs"], unit="world",
        ci_lower=delta["lo"], ci_upper=delta["hi"], ci_method=PAIRED_WORLD,
        dataset="synthetic-identity-v1", prevalence=identity_prevalence,
        conditioning=COVERAGE_CONDITIONING,
        source="data/fragmentation.json predictions, overlap=0.1",
        notes=("coverage(rotation 0.7) - coverage(rotation 0.3), paired on the "
               "same worlds",
               "the pre-registered P2, which decides")))

    aml = frag["amlworld"]["coverage"]
    metrics.append(Metric(
        id="amlworld_seed_reach_coverage", value=aml["point"],
        n_units=frag["amlworld"]["n_rings"], unit="ring",
        ci_lower=aml["lo"], ci_upper=aml["hi"], ci_method=WIDER,
        conditioning=COVERAGE_CONDITIONING,
        source="data/fragmentation.json amlworld",
        notes=("the same quantity as identity_seed_reach_coverage, measured on "
               "the same definition -- reported beside it, never pooled",)))

    # --- citation recall, as metrics rather than prose ---------------------
    #
    # These are the first numbers the narrative layer has ever reported. They
    # go through `Metric` for one specific reason: `unit="case"` is in
    # CONDITIONING_REQUIRED_UNITS, so none of them can be constructed without
    # the banner saying they were measured on the TEMPLATE path. The LLM path
    # has drafted nothing, so a citation figure quoted without that banner is a
    # claim about a model that has never run.
    cite = _load("data/eval_citation_recall.json")
    CITATION_CONDITIONING = (
        "Measured on the DETERMINISTIC TEMPLATE path, which cites by "
        "construction. The drafted path has attempted zero drafts (no key "
        "configured), so this is a property of the template and NOT a "
        "measurement of any model's sourcing. `member_recall` is 1.0 with a "
        "zero-width interval because the template emits every member account, "
        "and `precision` is 1.0 because the verifier hard-fails anything else "
        "-- both are tautological and neither is evidence of quality.")
    if not cite["is_full_population"]:
        raise SystemExit(
            "data/eval_citation_recall.json is a partial run "
            f"({cite['n_cases_scored']} of {cite['n_cases_in_store']} cases). "
            "Re-run scripts/eval_citation_recall.py without --limit. A smoke "
            "test must not reach results/metrics.json.")
    for key in ("evidence_recall", "txn_recall", "member_recall", "precision"):
        c = cite["metrics"][key]
        metrics.append(Metric(
            id=f"citation_{key}", value=c["point"],
            n_units=c["n_units"], unit="case",
            ci_lower=c["lo"], ci_upper=c["hi"],
            ci_method="case_clustered_bootstrap",
            conditioning=CITATION_CONDITIONING,
            source="data/eval_citation_recall.json"))

    # --- the guardrail's catch rate, by fault class ------------------------
    #
    # Phase 5 item 3 asked for the LLM draft REJECTION rate. That number does
    # not exist and cannot be manufactured: no key is configured, the ledger
    # has zero rows, and a rate over an empty denominator reported as 0.0 reads
    # as "the model never erred". The item is answered with a different
    # measurement and the substitution is recorded rather than quiet -- this
    # measures the VERIFIER against injected faults of known class, which is
    # deterministic, needs no key, and is reproducible by a reviewer.
    #
    # The interesting number is the one that is BAD. attribution ~ 0 is the
    # verifier's demonstrated blind spot, predicted in prereg/citation_recall.md
    # before it was measured.
    verifier = _load("data/eval_verifier_catch_rate.json")
    if not verifier["is_full_population"]:
        raise SystemExit(
            "data/eval_verifier_catch_rate.json is a partial run "
            f"({verifier['n_cases']} of {verifier['n_cases_in_store']} cases). "
            "Re-run scripts/eval_verifier_catch_rate.py without --limit.")
    VERIFIER_CONDITIONING = (
        "Catch rate of the CITATION VERIFIER against faults injected into "
        "template narratives at a known rate. It is NOT a model rejection "
        "rate: the drafted path has attempted zero drafts, no key is "
        "configured, and data/draft_ledger.jsonl does not exist. "
        "`fabricated_id` and `stripped_citation` are the two checks the "
        "verifier implements, so ~1.0 there is the floor, not an achievement; "
        "`attribution` is the blind spot and is the number that matters.")
    for cls in ("fabricated_id", "stripped_citation", "attribution"):
        c = verifier["catch_rate"][cls]
        metrics.append(Metric(
            id=f"verifier_catch_rate_{cls}", value=c["point"],
            n_units=c["n_units"], unit="case",
            ci_lower=c["lo"], ci_upper=c["hi"],
            ci_method="case_clustered_bootstrap",
            conditioning=VERIFIER_CONDITIONING,
            source="data/eval_verifier_catch_rate.json"))

    # --- citation precision and recall on the STR narrative ----------------
    written = write(OUT, metrics, generated_by="scripts/collect_metrics.py")

    # Counts that README quotes as facts but which are not intervals, so they
    # are stored beside the metrics rather than as Metric objects. Keeping them
    # out of `metrics` is deliberate: a count is not an estimate and giving it
    # a fake interval to satisfy the schema would be the exact move this file
    # exists to prevent.
    payload = json.loads(written.read_text(encoding="utf-8"))
    payload["counts"] = {
        "n_held_out_cycles": n_cycles,
        "n_train": arm["n_train"],
        "n_train_positive": arm["n_positive_train"],
        "n_test": arm["n_test"],
        "n_test_positive": arm["n_positive"],
        "split_t": arm["split_t"],
        "n_active_rings": diff["n_rings"],
        "n_rings_seeded_honestly": sum(
            n for c, n in diff["cells"].items() if c[0] == "1"),
        "n_rings_rescued_by_cheat": len(diff["R"]),
        "n_train_query_groups": ranker["train_group_diagnostics"]["n_groups"],
        "n_all_positive_groups": ranker["train_group_diagnostics"][
            "all_positive_groups"],
        "n_generation_cycles": phase2["runs"],
        "n_rings_seen": phase2["rings_seen"],
        "hit_share": phase2["hit_share"],
        "min_jaccard": phase2["min_jaccard"],
        "n_identity_configs": background["verdict"]["n_configs"],
        "n_identity_configs_passing": background["verdict"]["n_passing"],
        "n_identity_configs_required": background["verdict"][
            "min_configs_passing"],
        "n_identity_features": len(features["auc"]),
        "n_identity_features_excluded": len(features["excluded"]),
        "n_identity_candidates_scored": features["n_candidates"],
        "identity_relabelling_invariant": features["verdict"][
            "arm1_relabelling_invariant"],
        "n_identity_features_tripping_leak_auc": len(
            features["verdict"]["arm2_features_tripping_leak_auc"]),
        "ring_recall_score": round(phase2["ring_recall"]["score"], 4),
        "ring_recall_size": round(phase2["ring_recall"]["size"], 4),
    }
    # Funnel stage losses, as points. Counts rather than estimates: they are
    # exact over the rings observed, so they carry no interval and are stored
    # here rather than as Metric objects.
    funnel = _load("data/funnel.json")
    total = next(r for r in funnel["funnel_by_typology"]
                 if r["typology"] == "TOTAL")
    payload["counts"].update({
        "funnel_seeded_recall": round(total["seeded_recall"], 4),
        "funnel_built_recall": round(total["built_recall"], 4),
        "funnel_ranked_recall": round(total["ranked_recall"], 4),
        "funnel_largest_loss_stage": funnel["largest_loss_stage"],
        # The quantity the centrepiece was pre-registered on. It is a ratio of
        # two point estimates and `scripts/eval_oracle.py` stores no interval
        # for it, so it CANNOT be a Metric -- the constructor would reject it,
        # correctly. It is carried as a count with the absence written into the
        # name, so a template quoting it cannot do so without saying what is
        # missing.
        "oracle_over_blend_ratio_at_10_NO_INTERVAL": round(
            arm["oracle_over_blend"]["10"], 2),
        "oracle_over_blend_ratio_at_20_NO_INTERVAL": round(
            arm["oracle_over_blend"]["20"], 2),
    })

    # --- the cost model's negative result ---------------------------------
    #
    # Carried as counts rather than Metrics, and deliberately: a break-even
    # precision is a deterministic inversion of the cost model, not a sampled
    # estimate, so it has no interval and giving it a fake one to satisfy the
    # schema is exactly the move this file exists to prevent.
    #
    # EVERY KEY NAMES ITS STRESS FACTOR. The joint break-even was previously a
    # typed literal in README (1.8382) while this script's own artefact
    # reported 0.0864, because the two are different stresses -- x10 and x2 --
    # and the factor was not travelling with the number. A key called
    # `joint_break_even` with no factor in its name is a number a template can
    # quote without saying what it conditions on, so no such key is emitted.
    cost = _load("data/eval_cost.json")
    sweep = cost["joint_adverse_sweep"]
    payload["counts"].update({
        "cost_break_even_precision": cost["break_even_precision"],
        "cost_n_unsourced_inputs": cost["n_unsourced_inputs"],
        "cost_joint_break_even_at_x2": sweep["2.0"]["break_even_precision"],
        "cost_joint_break_even_at_x10": sweep["10.0"]["break_even_precision"],
        "cost_depths_that_pay_at_x2": sweep["2.0"]["depths_that_pay"],
        "cost_depths_that_pay_at_x10": sweep["10.0"]["depths_that_pay"],
        "cost_joint_x10_break_even_exceeds_one": sweep["10.0"][
            "exceeds_one_so_unreachable"],
        "cost_optimal_k": cost["cost_optimal_k"],
    })

    payload["counts"].update({
        "llm_drafts_attempted": verifier["llm_drafts_attempted"],
        "draft_ledger_exists": verifier["draft_ledger_exists"],
        "verifier_injector_discriminates": verifier["injector_discriminates"],
        "verifier_n_cases": verifier["n_cases"],
    })

    citation = _load("data/eval_citation_recall.json")
    payload["counts"].update({
        "citation_n_cases_scored": citation["n_cases_scored"],
        "citation_is_full_population": citation["is_full_population"],
        "citation_kill_criterion_fired": citation["kill_criterion_fired"],
        "citation_member_recall_is_degenerate": citation[
            "member_recall_is_degenerate"],
    })

    # The repository's own unmarked-literal count, so the document that reports
    # the ratchet is itself subject to it. Measured, not typed -- which is the
    # whole point being made.
    from sentinel.report.literals import count_unmarked
    payload["counts"]["n_prose_literals"] = count_unmarked(ROOT)[0]
    written.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(f"wrote {len(metrics)} metrics and "
          f"{len(payload['counts'])} counts to {OUT.relative_to(ROOT)}")
    for m in metrics[:3]:
        print()
        print(m.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
