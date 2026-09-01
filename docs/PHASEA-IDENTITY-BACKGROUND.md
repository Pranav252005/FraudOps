# Phase A — the synthetic-identity background passes its own kill rule

**What was pre-registered:** `prereg/synthetic_identity_generator.md` (the
generative process) and `prereg/synthetic_identity_kill_rule.md` (the gate),
both committed at `49f9f08`, before `sentinel/generators/synthetic_identity.py`
existed and before any baseline had been run.
`scripts/eval_identity_background.py` refuses to start otherwise.

**Verdict: the domain survives.** 25 of 36 configurations pass, against a
pre-registered floor of 18, and the primary configuration passes. Phase B may
start. The 11 that fail are marked `TOO_EASY` and are excluded from every later
phase rather than averaged in.

## The gate

Node-level ranking over the whole population — no seeding, no expansion, no
candidates. **This is not the harness p@k and must never be quoted as one.**
Its intervals resample *worlds* (20 seeds per configuration) and are named
`world_clustered_bootstrap`, which is deliberately not one of the three
clusterings `sentinel/report/metric.py` accepts, so these numbers cannot later
be mistaken for candidate-level ones.

Precision at k is the **expected** precision under uniform random tie-breaking.
That is not a detail: three of the four baselines are small integers, so the top
ten is routinely a thousand-way tie, and the first implementation — breaking
ties on `app_id` — scored `rare_multiplicity` at exactly 0.0000 on the primary
configuration. That was a fact about id order, not about the background.

## Primary configuration (rotation 0.5, cluster size 8, overlap 0.1)

Prevalence 0.0500. Thresholds are the pre-registered ones: absolute p@10 floor,
**and** lift under 3.0x; both clauses must hold.

| baseline | p@10 | interval (world-clustered) | lift | threshold | |
|---|---:|---|---:|---:|---|
| `degree` | 0.1056 | — | 2.12x | 0.15 | ok |
| `attr_multiplicity` | 0.0000 | — | 0.00x | 0.12 | ok |
| `component_size` | — | — | — | 0.15 | ok |
| `rare_multiplicity` | 0.0000 | — | 0.00x | 0.12 | ok |

Per-baseline intervals and every configuration's numbers are in
`data/identity_background.json`; the dashes above are numbers this document
declines to duplicate rather than numbers that were not measured — Rule 1's
prose problem is what `docs/inventory/metric_literals.csv` counts, and this file
does not add to it.

## Why the background holds

The best fraudulent application ranks **174th** by degree on the primary
configuration, with a median fraudulent rank of 1239 out of 4000. The
applications above it are offices: 20–200 employees on one IP subnet, which is a
legitimate structure with a hundred times a fraud cluster's degree.

`rare_multiplicity` — the baseline that deletes attribute values held by more
than five applications, and so deletes the offices and landlords with them — was
expected to be the dangerous one, and it is the one that scores zero. The
structures that beat it are households and roommates: four attributes shared
among three or four people is a denser rare-value signature than a rotation
chain's two.

## A finding that runs against the model's intent, recorded rather than fixed

**`overlap` makes the adversary *more* visible, not less.** Every one of the 11
`TOO_EASY` configurations fails on `degree`, and all but one sit at
`overlap=0.2`; degree p@10 rises monotonically in overlap at every rotation rate
and every cluster size.

The mechanism is that the steal pool is dominated by high-multiplicity values —
office IP subnets and landlord addresses are offered to it far more often than a
household's — so "steal a legitimate value" is in practice "attach to a hub",
and attaching to a hub is exactly what a degree baseline detects. Overlap was
intended as camouflage. It is currently a beacon.

**It is not being fixed in Phase A.** The gate passed, so no retune is required,
and retuning after seeing the results is the failure `prereg/` exists to
prevent. The correct model — stealing in proportion to a value's frequency in
the *structure* population rather than uniformly from offered values — would
make `overlap` do what the prereg says it does, and it is written down here so
that whoever changes it does so as a dated amendment under the kill rule's
one-retune clause, with this paragraph as the reason.

Until then, the `overlap=0.2` column is excluded from Phases B–E by the gate,
which means the domain is being evaluated on the arm where overlap is either
absent or mild — a narrower claim than the sweep was designed to support, and
the narrowing is on the record.

## What Phase A did not decide

The seed rule is pre-registered (P(seed | fraud) = 0.15, P(seed | legitimate) =
0.002) but is **not used by any Phase A baseline**, which rank the whole
population. It is fixed in advance so that Phase B cannot choose it after seeing
these results, since seed generosity sets recall before a single feature exists.
