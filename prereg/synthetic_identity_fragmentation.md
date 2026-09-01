# Pre-registration — the fragmentation dose-response

**Written before `scripts/eval_fragmentation.py` existed and before any coverage
number was computed in either domain.** The runner refuses to start unless this
file is committed and clean.

## Why the prediction is a dose-response and not a cross-domain contrast

The plan's prediction was that synthetic identity would show *worse*
fragmentation than AMLworld. As written that is not cleanly falsifiable: the
identity domain's difficulty is a dial this project sets, so "worse than
AMLworld" can be produced or destroyed by choosing `rotation_rate`. A comparison
between 18 AMLworld cycles and a knob is not a test.

**What is earnable is the dose-response inside the domain.** If fragmentation is
the adversary's design rather than an artefact, then turning up the adversary's
rotation must make it worse, monotonically, with everything else held fixed.
That is a prediction the data can refuse.

The cross-domain contrast is kept, demoted to **secondary and descriptive**, and
measured with the *same* definition on both sides so that the two numbers are at
least the same quantity.

## The quantity

**Seed-reach coverage.** For one ground-truth group (an identity cluster, or an
AMLworld ring) that has at least one seeded member:

    reach     = graph.expand(seeds ∩ group, hops=2, max_nodes=200, max_degree=50)
    coverage  = |group ∩ reach| / |group|

Deliberately *not* `is_hit` and not candidate containment. This asks what the
investigation can **see** from where it started, before scoring, pruning,
suppression or ranking touch anything — which is the thing the original finding
was about. Expansion parameters are the shipped ones, hub guard included.

Groups with no seeded member are **excluded** and their share is reported: with
no seed there is nothing to have coverage from, and scoring them zero would mix
a seeding failure into a reach measurement.

Reported beside it, as the mechanism:

- **cluster diameter** — longest shortest path inside the group's induced
  co-occurrence subgraph;
- **induced components** — how many pieces the group falls into on its own edges.

## The predictions, in order

**P1 (primary, directional).** In the identity domain at `cluster_size=8`, mean
seed-reach coverage is **monotonically decreasing** in `rotation_rate` across
{0.3, 0.5, 0.7}:

    coverage(0.3) > coverage(0.5) > coverage(0.7)

**P2 (primary, interval).** The contrast Δ = coverage(0.7) − coverage(0.3) is
**negative, with a 95% world-clustered bootstrap interval excluding zero.**

P2 is the one that decides. P1 without P2 is a shape with no evidence behind it;
P2 without P1 is a difference that is not a dose-response.

**P3 (mechanism).** Mean cluster diameter is **monotonically increasing** in
`rotation_rate`. This is the *reason* the project claims P1 happens: at low
rotation an attribute value survives many hops, so many members share it and the
cluster is close to a clique; at high rotation values die quickly and the cluster
degenerates towards a path, which a 2-hop expansion cannot cross.

**If P1 and P2 hold but P3 fails, the prediction survives and the explanation
does not**, and it will be written up that way rather than quietly re-narrated.

## The grid

`overlap ∈ {0.0, 0.1}` only. `overlap=0.2` at `cluster_size=8` was marked
`TOO_EASY` by Phase A's kill rule and is excluded from every later phase; using
it here would be exactly the retune-after-seeing that `prereg/` exists to stop.

20 worlds per configuration. `cluster_size=8` fixed for the primary contrast;
{3, 5, 12} reported as a secondary sweep, not as a test.

## The secondary contrast, and its stated limits

AMLworld coverage is measured on the same definition, over the compiled stream,
per generation cycle, and is reported **beside** the identity number via
`stratify_by_dataset` — never pooled, which `require_same_dataset` now enforces.

Its interval follows Rule 5: AMLworld coverage trials nest within rings, so both
cycle-clustered and ring-clustered intervals are computed and **the wider one is
reported**.

Three limits are stated in advance rather than discovered:

1. The identity side's difficulty is a chosen parameter. A difference in either
   direction is a fact about the configuration as much as about the domains.
2. The identity path is a static full-graph pass with no window; AMLworld's is a
   72-hour sliding window. That difference is the *subject* — AMLworld's
   fragmentation is the window's doing and identity's is the adversary's — but it
   also means the two numbers are not a controlled comparison.
3. `n` on the AMLworld side is what it has always been. This does not fix that.

So the secondary arm may report a difference and may not claim a cause.

## What failure means

If P2 fails — Δ non-negative, or an interval spanning zero — the pre-registration
has failed. The result goes to `docs/negative-results/` under Rule 7, the claim
that fragmentation is the adversary's design is **not** made, and the submission
says the domain reproduced the harness but not the finding.

No configuration will be added, removed or re-tuned in response to the outcome.
