# Phase E — two case files, one citation contract, and a recommendation that admits what it cannot do

**Gate: passed.** `scripts/demo_case_files.py` renders an identity case file, a
merchant-facing queue brief, and an AMLworld STR narrative from the stored
queue, side by side. All three are template-generated and all three are verified
by the same verifier.

## The contract, inherited rather than reinvented

`sentinel/narrative/citation.py` requires every fact-shaped sentence to cite an
id the case file actually contains. The AMLworld narrative cites transactions
and statutes. There are no transactions in onboarding data, so the identity case
file's citable units are **applications** (`APP-00001569`) and **shared
attribute values** (`LNK-DEVICE-0003`) — but the contract, the verifier and the
raise-don't-warn behaviour are the same objects.

Regulatory ids are deliberately **not** citable on the identity side. An STR
makes claims about the law; an onboarding review recommends a KYC step and makes
none, so admitting statute ids would only create a way to prop up an unsupported
sentence with an authority that does not support it.

The negative control is tested: a fabricated `APP-99999999` citation and an
uncited numeric claim are both rejected. A verifier that cannot fail measures
nothing.

## Two things the case file refuses to say

**No confidence number.** The natural merchant-facing sentence is "part of a
known cluster, confidence 0.85". Nothing in this project has calibrated such a
probability for this population. The refusal is structural rather than
conventional — `IdentityCaseFile` has no `confidence`, `probability`, `score` or
`risk_score` field for anyone to fill in, and a test asserts their absence. The
narrative says outright that it is not estimating a likelihood.

**No applicant is called fraudulent.** The brief's subject is *shared structure
between applications*, which is what was actually observed. Whether that
structure is a synthetic-identity ring or a household sharing an address is what
the recommended review is for, and the brief has to survive being read by the
applicant it is about.

The case file also states its own non-causality in the artefact rather than in a
design document nobody rereads: it was assembled from a static pass, so links
shown may involve applications received after the one under review.

## Shared infrastructure is separated from evidence

An office IP subnet joins hundreds of unrelated people. Presenting that to a
reviewer as evidence of a ring is how a queue loses its audience, so any
attribute value held by more than five applications is reported as **shared
infrastructure** and is excluded from the escalation rule.

Five is not a new number: it is the threshold Phase A's `rare_multiplicity`
baseline used, so "rare" means the same thing in the case file and in the
measurement that judged the background. A test pins the two together.

## The recommendation, and how selective it actually is

A coded action from a closed vocabulary — `MONITOR`, `MANUAL_REVIEW`,
`REQUEST_STEP_UP_KYC` — decided by a rule over rare links, not a threshold on a
score. A score threshold would imply a calibration this domain does not have.

Measured over five worlds, and reported *with* the demo rather than after it:

| candidate group | n | escalation |
|---|---:|---|
| covers a planted cluster | 96 | `REQUEST_STEP_UP_KYC` on all 96 |
| covers no cluster | 37 | `REQUEST_STEP_UP_KYC` 22, `MANUAL_REVIEW` 13, `MONITOR` 2 |

**The rule never misses a planted cluster in this sample, and escalates 22 of 37
candidates that cover none.** It is high-recall and low-specificity, and that is
stated rather than demoed around.

This is not a surprise and it is not a defect in the rule — it is Phase A's
finding arriving where a reviewer would feel it. `rare_multiplicity` scored
**0.0000** as a detector precisely because households and roommates share three
or four rare attributes among three or four people, which is the same shape a
rotation chain makes. A triage rule built on rare attribute sharing inherits
that. What the case file can honestly do is put the evidence in front of a human
with its provenance attached; what it cannot do is make the call, and it does not
pretend to.

## What a judge can be shown

Both artefacts, from the same pipeline, with the same honesty infrastructure:

- an **AMLworld STR narrative**, 47 accounts, every sentence tracing to a
  transaction id, 147 distinct verified citations;
- an **identity case file**, applications and shared values, every sentence
  tracing to an application or a link, verified by the same code;
- a **merchant brief** over the queue, every number counted from the case files
  passed in, with an explicit refusal to quote a likelihood;
- the **escalation profile** above, which is the number a demo would normally
  omit.
