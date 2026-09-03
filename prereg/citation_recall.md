# Pre-registration — citation recall, and the verifier's blind spot

**Written 2026-09-03, before `scripts/eval_citation_recall.py` existed.**
Committed before the run, per this project's standing practice: a threshold
chosen after seeing the number is not a threshold.

This is item 2 of Phase 5 in [`docs/NEXT_PHASE_PLAN.md`](../docs/NEXT_PHASE_PLAN.md),
and it closes §7.2 of `docs/ARCHITECTURE_UPLIFT.md`, which named this
measurement and never built it.

## What is being measured, and why one half of it is trivial

The STR narrative is generated under a citation contract
(`sentinel/narrative/citation.py`): every fact-shaped sentence must carry an
inline `[ID]` resolving to something the case file actually contains, and a
failure is a hard failure, never a warning.

**Citation precision** — of the ids cited, the fraction that resolve to case
file evidence — is therefore **1.0 by construction**. The verifier refuses to
return a narrative for which it is not. Measuring it is worth doing exactly once
so the number exists and is labelled as tautological, and it must never be
quoted as evidence of narrative quality. It is evidence that the verifier runs.

**Citation recall** is the one that is not guaranteed and has never been
measured: of the case file's own material evidence, how much does the narrative
actually cite? A narrative that describes a 19-account ring and cites three
transactions is under-sourced. Nothing in the repository currently notices.

### The definition, fixed here so it cannot be chosen to flatter

The case file's material evidence units are its **transactions** and its
**member accounts** — the two things `valid_citation_ids()` draws from that are
case-specific. The case id and the regulatory instruments are excluded: the case
id is not evidence about the world, and the statutes are a fixed closed set
identical across every case, so including them would inflate recall by a
constant that has nothing to do with the narrative.

    txn_recall    = |cited txn ids    ∩ case txn ids|    / |case txn ids|
    member_recall = |cited member keys ∩ case member keys| / |case member keys|
    evidence_recall = |cited (txn ∪ member)| / |case (txn ∪ member)|

Reported per case, then aggregated. `evidence_recall` is the headline.

### Clustering

One case is one trial and each case appears once, so the resampling unit is the
**case**. Standing rule 5 requires the interval to name its clustering:
`case_clustered_bootstrap`. There is no second clustering to compute here —
trials are not nested in rings or cycles — so the "report the wider of two" half
of rule 5 does not apply and the reason is recorded rather than left implicit.

## Pre-registered expectations

| quantity | prediction |
|---|---:|
| citation precision | **exactly 1.0**, and if it is not, the verifier has a defect and that is the finding |
| **evidence_recall** | **0.40 – 0.80** |
| txn_recall | 0.15 – 0.60 — lower than member recall, because a case file can carry hundreds of transactions and a narrative cites a handful per section |
| member_recall | 0.60 – 1.00 — the narrative enumerates roles, so most members should appear |
| verification failures over the sampled population | **0**, since this is the template path and it raises on failure |

I expect `txn_recall` to be **low and to be the honest bad news on this page** —
the narrative is structured around roles and typology, not around the ledger.

## The kill criterion, and it is a kill criterion for the MEASURE

**If `evidence_recall` comes back at or above 0.95, do not report it as a good
result. Check the measure first.**

A template that emits one sentence per fact makes recall trivially 1.0, and the
number would then be measuring the template's verbosity rather than the
narrative's sourcing — the same pathology as a fixed-0.5-threshold F1 on a pool
with 0.1% positives, and the same pathology as a verifier whose input could not
fail it. This project has shipped that class of number twice and caught it
twice.

If it fires, the honest report is "this measure is degenerate on the template
path and only becomes informative on the LLM path", and it is recorded as such
rather than published as 0.98.

## The second half: the verifier's blind spot, stated as a prediction

The verifier checks two things: that a fact-shaped sentence carries a citation,
and that the cited id exists in the case file. **It does not check that the
cited id supports the claim.**

**Prediction: a narrative that cites a real transaction id for a claim that
transaction does not support will PASS verification.** For example, attributing
an amount to a transaction that carries a different amount, or asserting a
cross-border hop citing a transaction that is domestic.

I am predicting this fails to be caught, and building the adversarial suite to
demonstrate it, because a named hole is worth more than a clean pass. If the
verifier *does* catch it, the prediction is wrong and that is a better outcome
that must be reported as a surprise rather than quietly claimed as intended.

The adversarial suite must also carry a **positive control** — an
attribution-corrupted narrative that the verifier *does* catch, via one of the
two checks it really implements — so the suite cannot be a set of tests that
pass for the wrong reason.

## What would reverse the conclusions here

- A recall figure measured on the LLM path rather than the template path. The
  template's recall is a property of the template; the contract exists for
  drafted text.
- A verifier extended to claim-tuple checking (does the cited transaction
  actually carry the amount, direction and timestamp the sentence asserts),
  which would close the blind spot and make the adversarial suite fail.
