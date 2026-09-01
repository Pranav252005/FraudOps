# Phase D — the dose-response holds, and the cross-domain claim does not

**All three pre-registered predictions hold, on both overlap arms.** The
prediction that was demoted before measuring — that identity fragments *worse*
than AMLworld — is refuted at the primary configuration, and is recorded in
`docs/negative-results/identity-fragments-worse-refuted.md`.

Pre-registration: `prereg/synthetic_identity_fragmentation.md`, committed at
`8453492`, before either domain was measured. Numbers in
`data/fragmentation.json`.

## The quantity, and why it is not p@k

**Seed-reach coverage**: what a 2-hop expansion from a group's own seeds can see
of that group, under the shipped hops, node cap and hub guard.

    reach    = expand(seeds ∩ group)
    coverage = |group ∩ reach| / |group|

Not `is_hit`, not candidate containment. Those come after scoring, pruning and
suppression; the finding this phase is about happens before any of them. Groups
with no seeded member are excluded and their share is reported — with no seed
there is nothing to have coverage from, and scoring them zero would fold a
seeding failure into a reach measurement.

## Primary: the dose-response (cluster size 8)

| overlap | rotation | coverage | interval (world-clustered) | diameter |
|---|---:|---:|---|---:|
| 0.0 | 0.3 | 0.9907 | [0.9854, 0.9951] | 1.98 |
| 0.0 | 0.5 | 0.9192 | [0.9057, 0.9327] | 3.07 |
| 0.0 | 0.7 | 0.8116 | [0.7954, 0.8267] | 4.46 |
| 0.1 | 0.3 | 0.9664 | [0.9550, 0.9774] | 2.04 |
| 0.1 | 0.5 | 0.8965 | [0.8759, 0.9159] | 3.18 |
| 0.1 | 0.7 | 0.8010 | [0.7800, 0.8231] | 4.50 |

**P1 (monotone decreasing): holds** on both arms.

**P2 (the one that decides):** Δ = coverage(0.7) − coverage(0.3) is
**−0.1791 [−0.1937, −0.1645]** at overlap 0.0 and **−0.1653 [−0.1950, −0.1362]**
at overlap 0.1 — paired world-clustered bootstrap, both intervals clear of zero
by a wide margin. **Holds.**

The pairing matters: the two arms differ only in `rotation_rate`, so world 3's
background is the same background on both sides, and pairing removes
between-world variance that the prediction is not about.

**P3 (the mechanism): holds.** Mean cluster diameter rises 1.98 → 4.46 as
rotation goes 0.3 → 0.7. This is the claimed reason and it is now measured
rather than asserted: at low rotation an attribute value survives many hops, so
many members share it and the cluster is near-clique; at high rotation values
die quickly, the cluster degenerates towards a path, and a 2-hop expansion
cannot cross it.

P1, P2 and P3 all holding is the strongest available version of this result:
the direction predicted, the interval excluding zero, **and** the mechanism
behaving as the mechanism was supposed to.

## The secondary sweep says where the effect lives

Reported, not tested (overlap 0.1):

| size | rot 0.3 | rot 0.5 | rot 0.7 |
|---:|---:|---:|---:|
| 3 | 0.9890 | 0.9804 | 0.9836 |
| 5 | 0.9814 | 0.9512 | 0.9122 |
| 8 | 0.9664 | 0.8965 | 0.8010 |
| 12 | 0.9405 | 0.8065 | 0.7097 |

The effect **grows with cluster size and vanishes at size 3** — where it is not
even monotone. That is the mechanism confirming itself from a second direction:
a 3-application chain is inside two hops no matter how hard it rotates, so there
is nothing for rotation to break. Fragmentation needs a cluster long enough to
exceed the expansion radius.

Had the dose-response appeared at size 3 as well, the explanation in P3 would
have been wrong even with P1 and P2 holding.

## Secondary: the cross-domain contrast, which went the other way

Same definition, same expansion constants, both domains:

| domain | coverage | interval | clustering |
|---|---:|---|---|
| amlworld-hi-small | 0.8058 | [0.7627, 0.8499] | wider of cycle- and ring-clustered |
| synthetic-identity-v1 (primary) | 0.8965 | [0.8759, 0.9159] | world-clustered |

Reported through `stratify_by_dataset` and never pooled — `require_same_dataset`
would refuse, which is the guard Phase B added.

**At the primary configuration, identity fragments LESS than AMLworld, not
more.** The original plan predicted the opposite. Demoting that prediction to
descriptive before measuring is the only reason this is a reportable observation
rather than a failed headline.

The AMLworld interval follows Rule 5: coverage trials nest within rings, so both
clusterings were computed and the wider is reported.

Two things this does *not* license saying:

- It is not evidence that identity clusters are easier to find. Coverage is
  reach, not detection, and the two domains differ in seeded share, in cluster
  size distribution, and in whether a window is doing the fragmenting.
- It is a fact about *one dial setting*. At rotation 0.7 the identity number is
  0.8010, statistically indistinguishable from AMLworld's 0.8058, and at size 12
  with rotation 0.7 it is 0.7097 — below it. The contrast is a function of the
  adversary's parameters, which is precisely why the pre-registration refused to
  make it the test.

## What the two domains actually share

Not a number — a mechanism. In both, **the seed sees only part of the group, and
the part it sees is bounded by how far the structure has been stretched relative
to the expansion radius.** In AMLworld the stretching is done by a 72-hour
window cutting a ring's activity in half. In synthetic identity it is done by an
adversary rotating attributes so that no single value spans the cluster.

The measurement that shows this is the same measurement in both places, run
through the same primitives, and the domains are kept numerically apart by a
guard that refuses to average them.
