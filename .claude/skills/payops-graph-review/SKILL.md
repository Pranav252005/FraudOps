---
name: payops-graph-review
description: Review checklist for the three places sentinel's numbers can go wrong — candidate-graph construction (seeding, expansion, pruning, suppression, motifs), label-leakage control (seed cheat, split hygiene, label reachability), and evaluation methodology (is_hit thresholds, bootstrap clustering, multiplicity). Includes the prior-art table of comparable public work. Use when reviewing or changing sentinel/detect/, sentinel/eval/, sentinel/graph/, or any split rule.
---

# Graph-pipeline review checklist

Run these questions against a diff. Each one has bitten this repository or a
comparable published system.

## A. Candidate-graph construction

1. **Does the seed rule reach the typology at all?** The pass-through rule
   (money in *and* out in the window) structurally cannot seed BIPARTITE,
   FAN-OUT, RANDOM or STACK. That is a recall ceiling, not a scoring problem,
   and no amount of ranking work touches it. A second seed predicate is the
   only fix — check `sentinel/eval/funnel.py`'s per-typology table before
   claiming otherwise.
2. **Is expansion budget being confused with the fix?** Measured: relaxing
   hops/max_nodes/max_degree raises containment and *collapses* coverage,
   because extra reach drags in bystanders and the candidate fails the Jaccard
   floor. Symmetric across rescued and recovered rings, so it is a property of
   expansion against the floor. See `docs/PHASE2-SEED-CHEAT-FINDINGS.md` H3.
3. **Is the ring fragmented rather than unreached?** 51% of rings rescued by
   the seed cheat are split across ≥2 components of their *own* induced
   subgraph inside the 72h window, against 5.7% of recovered ones. The honest
   seed lands in one fragment. Anything proposed for "more seeds" or "more
   budget" is answering the wrong question.
4. **Does the change make `suppress()` more score-dependent?** Suppression is
   greedy NMS ordered by score and runs during generation, so the score
   participates in which candidates exist. Anything that increases that
   coupling makes every future scorer A/B harder to interpret.
5. **Are motif counts order-dependent when a cap binds?** `find_cycles` stops
   at `MAX_CYCLES = 200` in `nx.simple_cycles` enumeration order, so on a dense
   subgraph `n_cycles`, `max_cycle_len` and `nodes_in_cycles` depend on
   enumeration order rather than on the graph. Deterministic across runs is not
   the same as unbiased.
6. **Is a temporal bound applied consistently?** Scatter-gather is bounded at
   6h (`SCATTER_GATHER_WINDOW_MINUTES`), matching GFP, and the unbounded count
   is kept alongside so the difference is measurable. Cycles have a temporal
   *validity* test but no window — a cycle spread over 72h counts the same as
   one closed in an afternoon. Same argument, not yet applied.

## B. Label-leakage control

1. **Is the label reachable from the detect path?** `PairAgg.laundering` rides
   on every live edge; `subgraph_edges` returns the whole `PairAgg` to
   `motifs.detect` and `features.build`. Nothing reads it today and nothing
   prevents it. The idiomatic fix here is rule 6's shape: a static
   attribute-access scan from every measured entry point, plus a runtime
   **poison test** — randomise `.laundering` on every edge and assert every
   candidate key, score and rank is bit-identical.
2. **Does the split leak positives forward?** `ring_time_split` is ring-disjoint
   and time-ordered **on the negative pool only**; a train-assigned ring keeps
   the candidates it produced after `split_t`. This is documented as a
   deliberate trade, and it is the right trade — but the standard technique for
   it is a **purge-and-embargo** split (drop records within a gap either side
   of the boundary), which buys back time-ordering on the positives at a known
   cost in training rows.
3. **Is the "cheat" arm clearly quarantined?** `seed_override` exists only for
   `scripts/eval_oracle.py` and the real path always calls `self.seeds(batch)`.
   Any new diagnostic that takes ground truth must be equally explicit at the
   call site and equally absent from `sentinel/detect/`.
4. **Is a supervised comparison confounded on more than one axis?** The
   run-1 vs Phase-4 "2×" differed on feature count, training-set size (~250×),
   split rule, split point *and* evaluation window. Any one could carry the
   whole effect. A comparison that changes more than one axis measures nothing.

## C. Evaluation methodology

1. **Does the interval name its clustering?** Rule 5. Cycle for p@k; ring where
   trials nest in rings; the **wider** of the two where both are defined.
2. **Are `is_hit`'s thresholds reported as free parameters?** `HIT_SHARE = 0.5`
   and `MIN_JACCARD = 0.3` determine every headline in the repo and no
   sensitivity curve is published. The cheapest defence against "you tuned the
   threshold" is a small grid — p@10 and built-recall over
   `hit_share ∈ {0.4,0.5,0.6} × min_jaccard ∈ {0.2,0.3,0.4}` — reported once as
   a band beside the headline.
3. **Is the comparison count tracked?** Many phases × many metrics, all with
   95% intervals, and no family-wise accounting. `prereg/` distinguishes
   pre-registered from post-hoc; the count of post-hoc comparisons behind a
   surprising result belongs beside it.
4. **Is Monte Carlo error in the bootstrap itself acknowledged?** Every call
   uses `seed=7`, `n_resamples=2000`. Re-running one headline at a second seed
   and at 10,000 resamples costs minutes and closes the question permanently.
5. **Is the denominator the same on both sides?** A p@10 over 17 held-out
   cycles compared against one over all 34 from a different script is two
   denominators. This shipped once.

## Prior art worth reading against

| work | what to take from it |
|---|---|
| [IBM/Multi-GNN](https://github.com/IBM/Multi-GNN) — AAAI'24 / NeurIPS'23 | The reference GNN baselines on AMLworld and the split protocol the AMLworld papers use. Useful as the "what a learned model gets" ceiling beside the oracle. |
| [B-Deprez/GARG-AML](https://github.com/B-Deprez/GARG-AML) ([paper](https://arxiv.org/abs/2506.04292)) | Second-order neighbourhood adjacency-block density as a single interpretable per-node score. Already partly mirrored in `detect/layers.py`. **It is also a candidate second seed predicate** — it scores every node, including ones with no pass-through. |
| [BlazingAML](https://arxiv.org/abs/2604.12241) | Patterns as compositions of neighbourhood-expansion + set-intersection + set-difference stages, with temporal break conditions and degree-ordered set operations. Directly relevant to the fragment-assembly problem: a scatter-gather is found by intersecting in- and out-neighbour sets rather than by expanding a neighbourhood and searching it. Reports GFP-identical F1 at 210–333× the speed. |
| [aidotse/AMLGentex](https://github.com/aidotse/AMLGentex) | A controllable AMLworld-style generator. Lets a claim be tested at a chosen ring size / fragmentation rate instead of only at HI-Small's. Relevant to the window-vs-ring-size hypothesis. |
| [IBM/AMLSim](https://github.com/IBM/AMLSim) | The older generator; useful mainly as a second dataset for the cross-domain test. |
| ["When Graph Structure Becomes a Liability"](https://arxiv.org/abs/2604.19514) | Argues transductive splits on Elliptic overstate GNN benefit under temporal shift. Read before any Elliptic2 headline. |
| [Elliptic2](https://arxiv.org/abs/2404.19109) | The subgraph-level framing this project's `eval/dataset.py` static path targets. |

**Do not quote a parity claim against any of these until the head-to-head has
actually been run on this machine.** `docs/HANDOFF-NEXT.md` §1 records that the
GFP comparison is blocked on the OS, not skipped, and that no parity claim may
enter the repo until it exists. The same standard applies to everything in this
table.
