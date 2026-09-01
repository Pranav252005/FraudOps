# Phase C — the identity features, and what the leak gate actually caught

**Gate: passed, on both arms.** Relabelling invariance holds exactly, and no
feature reaches the pre-registered leak threshold. Numbers in
`data/identity_features.json`; the pre-registration is
`prereg/synthetic_identity_features.md`, committed at `9bdb65a` before the
feature module existed.

## The gate the plan asked for was replaced, and why

The planned gate was "no single feature above p@10 0.20". Magnitude does not
distinguish a leak from a signal — it would discard a good feature and keep a
subtle leak. In a generated domain the generator writes the labels, so a leak is
a feature that reads a *generator parameter* rather than the observable record.
That is a structural property, so the gate tests it as one:

**Arm 1, structural.** Compute every feature vector, permute the ground-truth
cluster assignment — a real reassignment of applications to clusters, not a
renaming of ids — recompute, and demand bit-identical values. It passes exactly,
and it is asserted as a property in `tests/test_identity_features.py` as well as
measured by the runner. Alongside it, `build`'s signature takes nodes, graph and
applications and is never handed a `World`, so the truth is not in scope to be
read by accident, and an AST check on the module's imports enforces that rather
than a substring scan over its prose.

**Arm 2, measured.** Per-feature AUC over candidates, with a leak declared at
AUC ≥ 0.99 — near-deterministic separation from one column being what a
generator artefact looks like. Nothing tripped it. The most discriminative
single feature is `n_link_attributes`, well short of the threshold.

## The exclusion was predicted before it was measured, and the prediction held

The pre-registration named the decision rule in advance: an attribute whose
legitimate maximum multiplicity is bounded by a *structure size in the
generator* cannot be used, because separating on it is the generator's
construction rather than a fact about onboarding data. It also named which
attributes it expected that to catch.

The measured ceilings, over 20 worlds:

| attribute | legitimate max | fraudulent max | |
|---|---:|---:|---|
| pan | 3 | 8 | **excluded** — bounded by the joint-account structure |
| phone | 5 | 8 | **excluded** — bounded by household size |
| device | 5 | 8 | **excluded** — bounded by household size |
| address | 197 | 29 | kept — landlords and offices give it a heavy legitimate tail |
| ip | 197 | 194 | kept — office subnets, same reason |

Three attributes have a legitimate ceiling *below* the fraudulent one, and for
each the ceiling is exactly a structure size the generator chose. "PAN shared by
more than three applications" would have been a near-perfect fraud rule in this
world and a useless one in a real queue, where a PAN legitimately appears on many
applications. This is the same failure `EXCLUDED_FEATURES` catches for AMLworld,
where one column carried 86.6% of laundering rows against an 11.8% base rate.

Note that `max_pan_fanout` scored 0.8710 — high, but nowhere near the leak
threshold. **Arm 2 would not have caught it.** The exclusion rule did, because it
reasons about how the value came to exist rather than about how well it
separates. That is the argument for pre-registering a rule instead of a number.

The excluded columns are still computed and still stored in `to_dict`; only
`vector` drops them. A column that vanishes from the record cannot be checked
against the numbers that justified removing it.

## A feature family that is flat, and what that tells us

`n_components` and `largest_component_share` are **constant across every
candidate**: AUC exactly 0.5000, because expansion returns a connected node set
by construction. A candidate cannot be internally fragmented.

That is not a bug in the features — it is the discovery that **fragmentation is
not a candidate property at all**. It is a relation between a ground-truth
cluster and what the seed actually reached, which is Phase D's measurement and
cannot be phrased as a column in this table. The columns stay so that the
flatness is visible in the AUC output rather than quietly absent from it.

## The determinism bug the invariance test caught

`link_type_entropy` and `mean_fanout` summed floats in set-iteration order, so
their last bit depended on node ids. The index-invariance test found it by
shifting every id by 10,000 and getting `1.761877739507081` against
`1.7618777395070813`.

This is the same class of defect the repository already catalogues for
`dominant_entity_type`, where `max(set(types), ...)` returned a different
"dominant" entity type under a different `PYTHONHASHSEED` and the case file
stated a confident fact decided by a hash seed. Both sums now iterate `ATTRS` and
`sorted(nodes)` in fixed order.

## What did not survive the port

Everything built on flow: `passthrough_ratio`, `conservation`, `mean_velocity`,
`layer_depth`, `churn`, `burstiness`, and the whole boundary inflow/outflow
family. Onboarding applications have no amounts and no direction, so those
features are not weak here — they are undefined. A test asserts none of them was
ported by name.

What travels is the graph-structural family, rewritten rather than imported
because the AMLworld version reads `PairAgg` amounts that do not exist in this
domain. The replacement set is roughly thirty features in six families:
candidate structure, fragmentation, attribute multiplicity, rotation, attribute
fan-out, and temporal.

## Two things reported and not gated on

**Candidate positivity is high.** A large majority of generated candidates cover
a planted cluster under `is_hit`. That is a real property of this domain — the
seed lands in a chain that is nearly isolated from the legitimate background — and
it means a p@k measured here is not comparable to AMLworld's without saying so.
The exact figure is in `data/identity_features.json` and is Phase D's business,
not this phase's.

**The static pass is non-causal.** Every feature sees the whole population,
including registrations later than the seed. This was pre-registered as a stated
limitation rather than papered over with a per-feature temporal exclusion, which
would have implied the rest of the pipeline is causal. No number from this domain
is a claim about what could have been detected at the moment of the seed's
registration.
