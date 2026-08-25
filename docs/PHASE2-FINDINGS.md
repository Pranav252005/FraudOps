# Phase 2 — detection: findings and first measured results

Phase 2 was designed against measurements rather than the design document, and
two of those measurements overturned parts of it.

## Finding 1 — the dataset has no seasonality, so hour-of-week baselines are dead

Hourly volume across the evaluation window is flat: 178k edges every hour, except
hour 0 at 385k (a generator day-boundary artifact). Ratio max/min = 2.18, and
entirely explained by that one bucket.

The predecessor system's core claim was per-slice baselines keyed on
`(weekday, hour)`. On 10 days of data that yields at most 1–2 samples per key,
**and there is no diurnal pattern to learn anyway**. Porting `BaselineStore`
verbatim would have been cargo-culting a component whose premise this data does
not satisfy. It is not used.

## Finding 2 — value conservation is a ring-level property, not a node trigger

Measured as a per-account seed trigger across the evaluation window:

| Trigger | Accounts | % pop | Ring recall | Precision | Lift |
|---|---:|---:|---:|---:|---:|
| all active | 422,656 | 100% | 100% | 0.63% | 1.0× |
| pass-through (in>0 and out>0) | 167,258 | 39.6% | **78.6%** | 1.25% | 2.0× |
| degree ≥ 3 | 277,043 | 65.5% | 84.0% | 0.81% | 1.3× |
| conservation ≥ 0.90 | 4,066 | 1.0% | **3.9%** | 2.53% | 4.0× |
| pass-through ∧ cons ≥ 0.90 ∧ deg ≥ 3 | 3,979 | 0.9% | 3.1% | 2.06% | 3.3× |

The design document leaned on conservation as a primary signal. At the account
level it has good lift but almost no recall, because **laundering accounts do
not individually conserve — the ring conserves as a whole.** Conservation moved
to ring-level scoring, computed across the candidate's boundary. It is never
used for seeding.

Pass-through is the best cheap trigger: 78.6% recall at 2.0× lift. It is not
selective, and it is not meant to be — selectivity comes from structure and
scoring, not from the seed.

## Finding 3 — community detection is the wrong primary tool here

Leiden on the real 280,800-pair window (day 6 snapshot), 244,221 nodes:

| Config | Time | Max community | Ring coverage | **Workable** (≤60 nodes) |
|---|---:|---:|---:|---:|
| no hub cut, res 1.0 | 6.3s | 16,848 | 78.1% | **1.8%** |
| no hub cut, res 3.0 | 6.6s | 6,986 | 81.6% | 0.9% |
| hub>50, res 3.0 | 7.0s | 4,385 | 81.6% | 1.8% |
| hub>30, res 3.0 | 6.5s | 4,716 | 79.8% | 1.8% |

Coverage is good; **workability is not**. Nearly every covered ring lands inside
a 4,000–8,000 node community. Hub suppression at four thresholds barely moves it.
Rings here are small structures embedded in a large, largely unstructured graph —
there is no modular structure for Leiden to find.

Seed-and-expand, same window, expanding from a **single** ring member:

| Config | Neighbourhood median | p90 | Ring recall (median) | ≥80% recovered |
|---|---:|---:|---:|---:|
| 1 hop | 4 | 10 | 0.33 | 18% |
| **2 hops, maxdeg 50** | **14** | **34** | **1.00** | **67%** |
| 3 hops, maxdeg 20 | 33 | 91 | 1.00 | 73% |

Two-hop expansion recovers a **median 100%** of the ring, and **99% of
neighbourhoods are ≤60 nodes** — case-sized. Against Leiden's 1–2% workable,
this is decisive. 78% of rings are fully internally connected in the window.

**Leiden is dropped as the primary generator.** It remains the documented path
for platform-scale graphs where genuine communities exist; it is not used here,
and the reason is measured rather than asserted.

## The evaluation metric had a bug, and it mattered

First results showed `score` at p@10 = 0.138 — tied exactly by a `size` baseline
that simply ranks candidates by node count.

The cause was the hit definition. Containment-at-50% rewards bulk: a 158-node
candidate trivially contains half of a 4-account ring. The metric was measuring
candidate size as much as candidate quality.

Fixed by requiring **Jaccard ≥ 0.3** as well as 50% containment. Under the
corrected metric the `size` baseline collapses to **0.000** while the score
holds — confirming both that the fix was necessary and that the score is doing
real work.

Had this not been caught, the headline number would have been roughly double its
honest value and substantially an artifact.

## Results

34 generation runs over 10 days, 259 ground-truth rings (≥3 accounts) seen.

**Strict (Jaccard ≥ 0.3) — the honest metric**

| ranking | p@10 | p@20 | p@50 | p@100 | ring recall |
|---|---:|---:|---:|---:|---:|
| **score** | **0.068** | **0.049** | **0.026** | **0.023** | **18.1%** |
| size | 0.000 | 0.000 | 0.001 | 0.003 | 2.3% |
| degree | 0.000 | 0.001 | 0.005 | 0.006 | 2.7% |
| random | 0.003 | 0.006 | 0.003 | 0.004 | 4.6% |

**Loose (containment only) — retained to expose the confound**

| ranking | p@10 | p@20 | p@50 | p@100 |
|---|---:|---:|---:|---:|
| score | 0.138 | 0.109 | 0.069 | 0.058 |
| size | 0.138 | 0.099 | 0.078 | 0.061 |

**Per-typology recall** (loose, since strict counts are small)

| Typology | Seen | Found | Recall |
|---|---:|---:|---:|
| SCATTER-GATHER | 31 | 17 | 55% |
| GATHER-SCATTER | 38 | 14 | 37% |
| FAN-IN | 30 | 10 | 33% |
| FAN-OUT | 36 | 11 | 31% |
| CYCLE | 37 | 11 | 30% |
| RANDOM | 26 | 6 | 23% |
| BIPARTITE | 31 | 4 | 13% |
| STACK | 30 | 2 | **7%** |

The shapes with dedicated detectors do best. `STACK` and `BIPARTITE` — the
multi-layer typologies — have no dedicated motif and perform worst. That is a
blind spot, published rather than hidden.

## Honest assessment

**The pipeline works end to end and the score beats every baseline decisively
under the corrected metric.** Ring recall is 3.9× random; `size` and `degree`
are eliminated entirely.

**The absolute numbers are not good enough to ship as a queue.** p@20 = 0.049
means an analyst works twenty cases to find one ring. Ring recall of 18.1% sits
against a structural ceiling of 73.3%, so roughly a quarter of what is reachable
is being reached.

This is the unsupervised v1 floor with hand-set weights and no tuning, which is
what the architecture predicted it would be. It is the baseline the learned
re-ranker has to beat, not the finished product.

## The most promising next fix

Deduplication removed only **23 of 14,001** candidates in a single tick. Exact
member-set matching almost never fires, because expansions from adjacent seeds
produce overlapping-but-distinct sets. The top-20 is therefore likely to contain
many near-duplicates of the same neighbourhood, wasting queue slots that the
precision metric then counts as misses.

Merging candidates by **Jaccard overlap** before ranking — the correlation logic
already planned for the case layer — is the highest-expected-value change
available, and should raise p@k without touching the score at all.

Second: dedicated `STACK` and `BIPARTITE` motifs, which are the two worst
typologies and the two with no detector.

## Test coverage

29 Phase 2 tests, 81 across the project, all passing. Motif detectors are
verified against hand-built graphs whose shape is known exactly — fan-out,
fan-in, 2-cycle, 4-cycle, acyclic chain, scatter-gather, and the A→S→A case that
must register as a cycle rather than a scatter-gather. Scoring is tested for
boundedness, contribution-sum consistency, and that a ring-shaped candidate
outranks a chain. One test asserts `channel` can never enter the feature set,
so the 7.3× ACH leak stays excluded by construction.
