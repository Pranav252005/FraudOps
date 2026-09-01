# Pre-registration — the synthetic-identity generative process

**Written before `sentinel/generators/synthetic_identity.py` existed.**
`scripts/eval_identity_background.py` refuses to run unless this file and
`prereg/synthetic_identity_kill_rule.md` are committed, by the same mechanism
`scripts/eval_label_tax.py` uses.

This file fixes the *generative process*. It does not contain a single
measurement, and no number in it is a result — the numbers are parameters and
mixture weights, chosen before anything was run.

## Why a generated domain at all

The repository's `n` is 18 evaluation cycles and every interval it reports is
wide. `prereg/cycles.md` pre-registers that this cannot be fixed by generating
more cycles: the measured path is deterministic, adjacent cycles share a 72-hour
window, `EVAL_END` cannot move, and Elliptic2 was cancelled on a schema fact
(`docs/negative-results/elliptic2-cancelled.md`). Every option on that list was
rejected on principle except one — a second dataset — which was rejected on cost.

A second domain is that option, paid for.

The domain is onboarding synthetic identity, and it was chosen because the
finding this project already has is that domain's central problem rather than an
incidental one. In AMLworld the seed lands in one fragment of a ring because the
window has broken the ring; that is an artefact. In synthetic identity the
fraudster rotates attributes *so that* no single attribute links the cluster —
fragmentation is the adversary's design.

## The observable schema, and the leak boundary

An application is:

    app_id, ts (minutes), pan, phone, address, device, ip

**`Application` carries no label field.** The generator returns observables and
ground truth as two separate objects, and the feature module is forbidden to
import the truth side. This is the identity-domain analogue of Rule 6's import
boundary, and it exists because the leak risk here is categorically different
from AMLworld's: the generator writes the labels, so any feature that reads a
generator parameter is a leak by construction rather than by prevalence.

Two applications are joined by an edge when they share at least one attribute
value. The edge carries which attribute types are shared.

## Time: static, not windowed

**The graph is built in one static pass, with no window.** This reuses the path
`sentinel/eval/dataset.py` already provides for Elliptic2
(`WindowedGraph(window_minutes=10**9)`), and it is pre-registered here as a
decision rather than left as a constant somebody later tunes.

The reason is that a window would contaminate the cross-domain claim. The
adversary's strategy in this domain *includes deliberate temporal spacing*, so
fragmentation measured under a window would be partly the window's artefact —
which is precisely the AMLworld result, re-derived, rather than a contrast with
it. `WINDOW_MINUTES` is a load-bearing AMLworld constant and it does not travel.

Applications are timestamped over a 90-day span and the timestamps are emitted,
so a later windowed variant is possible; it would be a different pre-registration.

## The legitimate background

The background is the whole experiment. If it does not produce dense legitimate
attribute co-occurrence, a trivial baseline wins and nothing measured downstream
means anything. Every structure below exists to make one trivial baseline fail:

| structure | size | shares | defeats |
|---|---|---|---|
| household | 2–5 | address, ip; phone w.p. 0.6; device w.p. 0.5 | small-cluster shape |
| joint account | 2–3 | **pan**, phone, address | attribute-multiplicity: legitimate PAN sharing |
| office | 20–200 | ip subnet; address w.p. 0.7 | degree, component size |
| landlord | 5–30 | address only | multiplicity on a single attribute |
| roommates | 2–4 | address, ip | rare-attribute multiplicity |
| solo | 1 | nothing | — |

Mixture weights over applications: solo 0.34, household 0.30, office 0.16,
roommates 0.10, landlord 0.06, joint 0.04. Legitimate timestamps are uniform
over the 90-day span.

The joint-account structure is the important one and is deliberately small: it
is the only legitimate reason two applications share a PAN, and without it
`shared_pan_count` alone identifies the adversary.

## The adversarial model

A cluster of `cluster_size` applications is generated as a **rotation chain**.
The first application is fresh. Each subsequent application copies its
predecessor's attributes and then independently resamples each one with
probability `rotation_rate`, subject to two constraints that are the model:

- **at least one attribute is shared** with the predecessor — otherwise there is
  no cluster to find;
- **at least one attribute is rotated** — otherwise the cluster is a clique and
  a single attribute links the whole of it.

The consequence is the structural fact the domain exists to exhibit: application
A shares a device with B, B shares an address with C, and **A and C share
nothing**. The chain's diameter grows with `cluster_size`, and the probability
that any single attribute spans the cluster falls with `rotation_rate`.

With probability `overlap`, one attribute of a fraudulent application is drawn
from the *legitimate* value pool — a synthetic identity registering against a
real office's IP subnet or a real landlord's address. This is what stops the
adversary from living in its own disconnected corner of the value space.

Fraudulent registrations are spaced by exponential gaps with a mean of 6 days,
truncated to the 90-day span. Deliberate spacing is adversarial, not incidental.

## The sweep

Adversarial difficulty is swept, not fixed. A single fixed difficulty is one fit,
reported once.

    rotation_rate  ∈ {0.3, 0.5, 0.7}
    cluster_size   ∈ {3, 5, 8, 12}
    overlap        ∈ {0.0, 0.1, 0.2}

36 configurations. The **primary configuration**, named before running, is
`rotation_rate=0.5, cluster_size=8, overlap=0.1`. Where one number has to be
quoted, it is that one.

Fixed across the sweep: 4,000 applications per world, 90-day span, planted
clusters sized so that fraudulent applications are approximately 5% of the
population. Prevalence is emitted per world and reported beside every p@k, per
Rule 4's reasoning.

## Determinism and the resampling unit

A world is a deterministic function of `(seed, params)`, matching the discipline
of the rest of the measured path.

Unlike AMLworld, this domain **has** a randomness knob, and that is the point of
it: 20 worlds per configuration, differing only in seed. The resampling unit for
every interval in Phase A is therefore the **world**, and intervals are named
`world_clustered_bootstrap` wherever they are reported. This is a new clustering
name and it is deliberately not one of the three `sentinel/report/metric.py`
accepts, because no Phase A number is a candidate-level p@k and none of them
should be rendered as one.

## What this file does not decide

The seed rule (which applications an investigation starts from) is pre-registered
in `prereg/synthetic_identity_kill_rule.md`, because it is the parameter that
sets recall before any feature exists and it belongs beside the gate that judges
it. The feature set is Phase C and is not pre-registered here.
