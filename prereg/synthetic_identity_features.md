# Pre-registration — the identity feature set, its exclusions, and its leak gate

**Written before `sentinel/detect/identity_features.py` existed and before any
feature was scored.** `scripts/eval_identity_features.py` refuses to run unless
this file is committed and clean, as `scripts/eval_label_tax.py` and
`scripts/eval_identity_background.py` do.

## Why the plan's gate was replaced

The gate this phase was supposed to run was "no single feature may achieve
p@10 > 0.20 alone". It is replaced, and the reason is stated here rather than
discovered later.

**Magnitude does not distinguish a leak from a signal.** A threshold on how good
a feature is will throw out a good feature and keep a subtle leak. In a
*generated* domain the leak risk is categorically different from AMLworld's: the
generator writes the labels, so a leak is any feature whose value is a function
of a generator parameter rather than of the observable record. That is a
structural property and it is testable as one.

So the gate has a structural arm that cannot be argued with, and a measured arm
that looks for the signature of a leak rather than for a large number.

## Arm 1 — structural, and it is the one that matters

**Relabelling invariance.** Feature vectors are computed, the ground-truth
cluster assignment is then permuted arbitrarily, and the feature vectors are
recomputed. **Every value must be bit-identical.** A feature that moves when
only the labels moved is reading the labels.

This is exact, not statistical, and it is the identity-domain analogue of
Rule 6's import boundary: `sentinel/generators/synthetic_identity.py` keeps
`Application` label-free, `sentinel/eval/identity.py` is the only module allowed
to see `World.clusters`, and the feature module may not import either the
`World` type or the evaluation side.

**Signature containment.** The feature builder takes a candidate's node set, the
graph, and the observable applications. It is never handed a `World`, so the
truth is not in scope to be read by accident.

## Arm 2 — measured: perfect separation is the leak signature

Per-feature AUC over candidates, where a candidate is positive when `is_hit`
says it covers a planted cluster.

    Any single feature with AUC >= 0.99 is treated as a leak.

Near-deterministic separation from one column is what a generator artefact looks
like; it is not what a real signal looks like. A feature that trips this is
**excluded, with its numbers written down**, exactly as `channel` was excluded
from AMLworld for carrying 86.6% of laundering rows against an 11.8% base rate.

Reported beside it, and **not gated on**: whether the full set beats its own best
single feature. A set that does not is one feature plus noise, which is worth
knowing and is not a leak.

## The exclusion this phase expects to make, named in advance

`max_pan_fanout` — the largest global multiplicity of any member's PAN.

In the generator, legitimate PAN sharing is bounded at 3 by the joint-account
structure, while a rotation chain can retain one PAN across up to `cluster_size`
hops. "PAN shared by more than three applications" is therefore close to a
deterministic fraud indicator **by the generator's own construction**, and it
would inflate every downstream number while teaching nothing that transfers to
real onboarding data, where a PAN can appear on many legitimate applications.

The same argument applies to `max_phone_fanout` and `max_device_fanout`, whose
legitimate ceilings are set by household and joint-account sizes. It does **not**
apply to `max_address_fanout` or `max_ip_fanout`, which have landlords and
offices behind them and so have heavy legitimate tails.

The decision rule is pre-registered rather than the outcome: **any attribute
whose legitimate maximum multiplicity is bounded by a structure size in the
generator is excluded, and the measured legitimate and fraudulent maxima are
reported for all five attributes** so that a reader can check the reasoning
rather than take it on trust.

## What is NOT excluded, and the limitation that replaces it

The plan called for excluding features that use applications registered *after*
the seed's registration date. That exclusion is **not made**, because it would
misdescribe what the pipeline does.

The identity path is a **static full-graph pass** with no window, pre-registered
in `prereg/synthetic_identity_generator.md`. It is therefore non-causal by
design: every feature sees the whole population, including registrations later
than the seed. Adding a per-feature temporal exclusion would imply the rest of
the pipeline is causal, which it is not.

So the limitation is stated instead of being papered over: **no number from this
domain is a claim about what could have been detected at the time of the seed's
registration.** A causal variant would be a different pre-registration with a
different pipeline, and it is not this one.

Two observable columns are nonetheless forbidden as feature inputs, because they
are generator bookkeeping rather than data:

- `app_id` — an index. It is shuffled after construction so it carries no
  signal, but a feature reading an index is a bug waiting for the shuffle to be
  removed.
- absolute `ts` — the 90-day span is a generator parameter. Differences between
  timestamps are data; a position inside a chosen span is not.

## The feature families

Roughly thirty features, in six families. The count is not a target and the list
may lose members to the gate; what is fixed here is the *kind* of thing each
family measures, before any of them was scored.

| family | measures | why it exists in this domain |
|---|---|---|
| candidate structure | size, density, degree, boundary | inherited from AMLworld, the only part that survives |
| **fragmentation** | internal components, largest-component share, diameter | the adversary's design, and Phase D's subject |
| attribute multiplicity | which attributes link members, and how many | the onboarding analogue of flow |
| **rotation** | spanning-attribute share, open-triangle ratio, link-type entropy | no single attribute spans a rotated cluster |
| attribute fan-out | global multiplicity of each member's values | separates a shared office IP from a shared device |
| temporal | span, mean gap, burst index | deliberate spacing is adversarial |

Everything from AMLworld with `passthrough`, `conservation`, `velocity`,
`burstiness`, `layer`, `amount` or `flow` in its name is **dead here**: there is
no flow in onboarding data and no amounts to be conserved. They are not being
ported, and the eight that survive are the graph-structural ones.

## What a failure means

If the structural arm fails, the feature set is wrong and is fixed before
anything is measured — a failure there is a bug, not a result.

If the measured arm trips on a feature that the exclusion rule above does not
already cover, that feature is excluded, the numbers go in the write-up, and the
gate is re-run. If more than five features trip it, the *background* is
implicated rather than the features, and Phase A's kill rule is re-opened under
its one-amendment clause.
