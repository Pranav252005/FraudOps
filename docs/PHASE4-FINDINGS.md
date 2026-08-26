# Phase 4 findings — and the bottleneck this project had wrong

## Re-measurement after the cycle fix

`MIN_CYCLE_LEN = 3`, so mutual A↔B pairs no longer count as laundering loops.

| run | p@10 | p@20 | ring recall |
|---|---:|---:|---:|
| broken (temporal cycle firing on 91%) | 0.024 | 0.028 | 17.0% |
| merge (pre-GARG-AML) | 0.071 | 0.050 | 18.1% |
| **fixed** | **0.085** | 0.049 | 15.4% |

Best p@10 so far. Not a clean win: overall recall fell, and per typology the
picture is mixed — CYCLE improved 11% → 16%, but SCATTER-GATHER fell 52% → 29%.

Post-fix, temporal cycles fire on **0.03% of candidates** (4 of 12,689), which
is the correct behaviour — genuine three-hop loops are rare — but means the
feature contributes to ranking almost nowhere.

Prevalence measured across 12,689 candidates:

| feature | fires on |
|---|---:|
| cross-border | 60.5% |
| gather-scatter ≥ 2 | 50.1% |
| fast pass-through > 0 | 34.9% |
| gargaml > 0.3 | 28.0% |
| stack ≥ 0.5 | 16.6% |
| conservation ≥ 0.8 | 3.0% |
| scatter-gather ≥ 2 | 1.7% |
| bipartite ≥ 0.5 | 1.4% |
| **temporal cycle** | **0.03%** |

Anything firing on more than half the queue cannot discriminate much.
`gather_scatter` at width ≥ 2 and `cross_border` are close to constants.

## Phase 4, retrained without the broken feature

| ranking | p@5 | p@10 | p@20 | p@50 |
|---|---:|---:|---:|---:|
| v1 hand-set | 0.176 | 0.106 | 0.065 | 0.035 |
| learned re-ranker | 0.176 | 0.124 | 0.088 | 0.053 |
| lift | 1.00× | 1.17× | 1.36× | 1.50× |

The headline lift collapsed from **4.00× to 1.00×** at p@5. Not because the
model degraded — because **v1 improved sharply** once the broken feature stopped
dominating it (p@5 0.047 → 0.176). Absolute re-ranker performance is roughly
flat.

The model itself got better on its own terms: held-out average precision
**0.2704 against a 0.0412 base rate — 6.57×**, up from 5.27×.

Top held-out feature importances:

```
passthrough_ratio      +0.0716
gargaml                +0.0408     <- added this session
stack_score            +0.0322     <- added this session
max_fan                +0.0245
scatter_gather_width   +0.0218
outflow                +0.0200
burstiness             +0.0179
n_entities             +0.0173     <- registry context, finally used
mean_velocity          +0.0096
```

**GARG-AML and stack are the 2nd and 3rd most informative features to the
learned model**, while contributing nothing to per-typology recall under the
hand-set weights. The features carry real signal; the linear blend could not
exploit it. That is the argument for the re-ranker being the real ranking and
the linear score being an explainability layer.

## The finding that matters: generation, not ranking

A diagnostic asking, for each active ring, whether *any* candidate covers it at
all — before ranking enters:

| typology | active | **generated** | in top-50 |
|---|---:|---:|---:|
| BIPARTITE | 10 | **0 (0%)** | 0 |
| FAN-OUT | 17 | **0 (0%)** | 0 |
| RANDOM | 8 | **0 (0%)** | 0 |
| STACK | 15 | **0 (0%)** | 0 |
| FAN-IN | 15 | 8 (53%) | 0 |
| GATHER-SCATTER | 18 | 11 (61%) | 1 |
| SCATTER-GATHER | 15 | 10 (67%) | 0 |
| **Total** | **114** | **30 (26%)** | **1 (1%)** |

**Only 26% of active rings become candidates at all, and four typologies are
never generated.**

This contradicts the Phase 2 conclusion — *"the loss is in ranking, not
generation"* — that this project has been building on ever since, including the
entire justification for Phase 4.

### Why

The seed rule requires an account to be **pass-through**: money in *and* money
out within the window.

- A **FAN-OUT** is one sender and many receive-only sinks. The sender only
  sends; the sinks only receive. **Not one member is pass-through.**
- A **BIPARTITE** is senders feeding sinks with no intermediary. Same.

Neither can ever be seeded, so neither can ever be built, scored, or ranked. The
layered detectors added for exactly these shapes never saw a candidate to score.

### Why it was missed

Phase 2 measured seed recall at **78.6%** — but that was an aggregate over ring
*accounts*, dominated by the typologies that do contain pass-through members. It
averaged over entire typologies scoring zero.

The lesson is the same one the ACH leak and the size-baseline taught: **an
aggregate can be healthy while a stratum is at zero.** Every recall number in
this project should have been reported per typology from the start, at
generation as well as at ranking.

## What follows

Scoring work cannot reach a candidate that was never built, so seeding has to
widen before anything downstream improves. The obvious extension is a union of
triggers rather than one rule:

- pass-through (current) — catches the layering typologies
- **fan-out degree** — catches FAN-OUT and the source side of BIPARTITE
- **fan-in degree** — catches FAN-IN and the sink side
- velocity or dormancy break — catches behaviourally odd accounts of any shape

Each is cheap and already computed. The cost is more candidates per tick, which
is what the ranking layer exists to absorb.
