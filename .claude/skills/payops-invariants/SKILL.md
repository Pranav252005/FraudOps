---
name: payops-invariants
description: The non-negotiable rules any change to sentinel must satisfy — measured numbers only, size baselines, conditioning banners, prevalence, bootstrap clustering, LLM out of measured paths, append-only negative results, and label unreachability. Load before editing anything under sentinel/, scripts/eval_*.py, or writing any number into README/docs. Triggers on: changing a score weight, a threshold, a config constant, a split rule, an eval script, or quoting a metric in prose.
---

# Invariants

Eight rules, all mechanised. Seven are in `docs/STANDING-RULES.md` with
their enforcement status stated honestly. The eighth was proposed in
`docs/graph-review/2026-09-04.md` §Leakage and was mechanised on 2026-09-04
(experiment L1): a static reachability walk in
`tests/test_measured_path_closure.py` and a runtime poison test in
`tests/test_label_poison.py`, wired as the `label_poison` CI gate.

Read `docs/STANDING-RULES.md` before relying on this file — it is the source of
truth and it records where enforcement is *thin*. This file is the working
checklist, not a replacement.

## The checklist

| # | rule | what it means when you are editing |
|---:|---|---|
| 1 | Never state an unmeasured number | Do not type a digit into a `*.template.md`. Numbers reach prose only through `sentinel/report/`. `sentinel/report/literals.py::stale_literals` fails the build on stale values in templates. |
| 2 | p@k always beside its size baseline | `size` reads no features. If `size` moves when you changed only a weight, **the candidate set moved** — see rule 8's corollary below. |
| 3 | Conditioning banner on every ring-unit metric | "P(ring in top-k of its own cycle \| ring was BUILT)" is not recall. Say the condition. |
| 4 | Prevalence beside any Elliptic2 p@k | |
| 5 | Cluster the bootstrap on the unit the trials nest in; where they nest in rings, report the **wider** of cycle- and ring-clustered | `Metric` refuses any `ci_method` outside the three permitted names. A bare "bootstrap" is not a reported interval. |
| 6 | `sentinel.llm` out of every measured path | `tests/test_import_boundaries.py` (runtime) + `tests/test_measured_path_closure.py` (static AST from every entry point). Both carry a negative control. |
| 7 | Record negative results; never delete them | `docs/negative-results/`. Truncation-in-place is a known gap. |
| 8 | The ground-truth label must not be reachable from the detect path | `PairAgg.laundering` is carried on every live edge and `subgraph_edges` hands the whole `PairAgg` to `motifs.detect` and `features.build`. Enforced twice: statically (no `.laundering` on any measured path outside `sentinel/graph/window.py`; no `laundering` **or** `is_laundering` anywhere in `sentinel/detect` or `sentinel/learn`) and at runtime (randomise the label on every fixture edge, demand a bit-identical fingerprint). Both carry negative controls, because a guard that cannot fail is not evidence. |

## The three failure modes this repo has actually shipped

Each of these got past a review once. Check for them by name.

**1. A metric that a feature-blind baseline can tie.**
Containment-only `is_hit` let a node-count baseline tie the real score
(`docs/PHASE0-FINDINGS.md`). Before shipping any metric change, ask: *would
`size` move?* If a change makes the headline better and `size` better by the
same amount, the detector did not improve.

**2. Relaxing the bar instead of improving the answer.**
Lowering the Jaccard floor would reclassify 88 rings as found with no detector
change. `sentinel/detect/prune.py` is the honest version of the same move.
Any pruner must be judged on **both halves at once**: Jaccard up *without*
containment down.

**3. A boundary test that cannot fail.**
Every enforcement test needs a negative control — a case that *should* trip it.
`test_measured_path_closure.py` uses `scripts/check_llm.py` for exactly this.

## The corollary that costs the most time

`suppress()` is greedy non-maximum suppression **ordered by score**, and it runs
during generation. So:

> **Any change to a score weight invalidates the candidate set, not just the
> ranking. A scorer experiment on a cached pool measures a fixed-candidate-set
> counterfactual, not the deployed system.**

`compile_corpus.py --rescore` makes a stale pool *internally consistent*, not
correct. The tell is rule 2's: `size` and `degree` read no features, so if they
move, the pool moved.

## Before you commit

```bash
python -m pytest -q
python scripts/ci_gates.py all
```

Both must be green, and `docs/STANDING-RULES.md` must still describe what the
code does. If you weakened an enforcement, say so in the table rather than
rounding it up.
