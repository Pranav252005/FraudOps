# Pre-registration — the synthetic-identity difficulty kill rule

**Written before `sentinel/generators/synthetic_identity.py` existed, and before
any baseline was run.** Committed alongside
`prereg/synthetic_identity_generator.md`; `scripts/eval_identity_background.py`
refuses to start unless both are committed and clean.

This file names the number that throws the domain out, before the number exists.

## Why this gate is worth a phase of its own

If a trivial baseline solves the generated problem, the graph engine adds
nothing and every p@k measured downstream is a property of the generator. That
failure is not hypothetical here: `docs/PHASE0-FINDINGS.md` records a bare
containment metric tying a baseline that ranks by node count, and
`sentinel/config.py`'s `EXCLUDED_FEATURES` records one column carrying 86.6% of
laundering rows against an 11.8% base rate. Both were caught by measuring the
trivial thing first.

## The seed rule, pre-registered

There is no flow in onboarding data, so AMLworld's pass-through seed rule does
not travel. The seed is **exogenous**: an application is seeded when an outside
signal fires on it — a chargeback, a manual report, a failed step-up.

    P(seed | fraudulent application) = 0.15
    P(seed | legitimate application) = 0.002

Both are pre-registered because seed generosity sets recall before any feature
exists, and a seed rule discovered during Phase B is a knob that produces
whichever number is wanted. The false-alarm rate is non-zero on purpose: an
investigation that only ever starts from true positives is not an investigation.

Phase A's baselines **do not use the seed rule** — they rank the whole
population, which is the strictest form of the trivial-baseline question. The
seed rule is fixed here so that Phase B cannot choose it after seeing Phase A.

## What Phase A measures

Node-level ranking over all applications in a world. No candidates, no
expansion, no harness — this is deliberately *not* the harness p@k and must
never be quoted as one.

    p@k = |{top-k applications by baseline score} ∩ {any planted cluster}| / k

reported at k = 10 and k = 50, beside the world's prevalence, with a
world-clustered bootstrap interval over 20 seeds per configuration.

## The four baselines

Each exists to be beaten by the background, and each has a different reason:

| baseline | score | the background structure that must defeat it |
|---|---|---|
| `degree` | distinct applications sharing ≥1 attribute value | offices (20–200 shared IP) |
| `attr_multiplicity` | Σ over attributes of (applications sharing that value − 1) | landlords, offices |
| `component_size` | size of the raw co-occurrence component | the giant legitimate component |
| `rare_multiplicity` | as above, but **only** over attribute values with global multiplicity ≤ 5 | households, roommates, joint accounts |

`rare_multiplicity` is the one that can actually win, and it is the one the plan
this was derived from did not have. Hub-shaped baselines are demolished by any
background containing an office; excluding high-multiplicity values deletes the
offices and the landlords and leaves precisely the adversary's signature. A
background that survives degree but not `rare_multiplicity` is not a hard
background — it is a background with big hubs in it.

## The kill rule

A configuration **passes** when, for all four baselines:

    p@10 point estimate  <  0.15    (degree, component_size)
    p@10 point estimate  <  0.12    (attr_multiplicity, rare_multiplicity)

**and** the lift over prevalence is under 3.0x for all four. Both clauses must
hold. The absolute floor alone is not enough — at 5% prevalence a p@10 of 0.14
is a 2.8x lift and passes, while at 1% prevalence the same 0.14 is 14x and is a
solved problem wearing a small number. The lift clause is what stops that.

Point estimates decide the gate; intervals are reported beside them and do not
decide it, because a gate adjudicated on interval edges is a gate that moves
when the resample seed does.

## The domain-level decision, fixed in advance

- **The primary configuration** (`rotation_rate=0.5, cluster_size=8,
  overlap=0.1`) must pass. If it fails, the domain is thrown out — not retuned.
- **At least 18 of the 36 configurations** must pass. Configurations that fail
  are marked `TOO_EASY` and are **excluded from every later phase**, rather than
  quietly averaged in.
- If either condition fails, Phases B–E are not started. The result is written
  to `docs/negative-results/` under Rule 7 and the submission falls back to
  AMLworld alone.

Retuning the background after seeing a failure is permitted exactly once, and
only by **committing a new version of this file with a dated amendment saying
what was changed and why**. The original thresholds stay in the file. An
undated retune is the failure this directory exists to prevent.

## Stated prior, not a measurement

The judgement going in is that this gate is roughly an even bet, and it is
recorded here so that a pass cannot later be described as expected and a failure
cannot be described as bad luck. It is a prior, it has not been measured, and
Rule 1 means it is never to be quoted as a result.
