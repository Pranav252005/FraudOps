# Sentinel — submission

**A fraud-ring investigation engine measured on two domains, and a record of
everything that went wrong while measuring it.**

This document is **rendered** from [`results/metrics.json`](../results/metrics.json)
by `scripts/render_docs.py`. No number in it is typed. That is not a
presentation choice — it is the fix for a defect this project shipped three
times, described in §6.

---

## 1. The headline, with everything that must travel beside it

**What ships today** is a hand-set scoring function over candidate subgraphs
built by seed-and-expand. Measured over {{count:n_generation_cycles}}
generation cycles on {{count:n_rings_seen}} ground-truth rings of the AMLworld
`HI-Small` benchmark:

| | p@10 | p@20 | p@50 |
|---|---:|---:|---:|
| **shipped scorer** | **{{metric:shipped_score_p_at_10}}** | {{metric:shipped_score_p_at_20}} | {{metric:shipped_score_p_at_50}} |
| size (node count) — the standing baseline | {{metric:shipped_size_p_at_10}} | {{metric:shipped_size_p_at_20}} | {{metric:shipped_size_p_at_50}} |
| random | {{metric:shipped_random_p_at_10}} | {{metric:shipped_random_p_at_20}} | {{metric:shipped_random_p_at_50}} |

**p@10 = {{metric_ci:shipped_score_p_at_10}}**, against a size baseline of
{{metric:shipped_size_p_at_10}}, over n = {{count:n_generation_cycles}}
cycle-clustered bootstrap resamples. Ring recall
{{count_pct:ring_recall_score}}.

**Paired against node count**, which is the bar every ranking claim here is
held to: {{signed:shipped_score_over_size_delta_at_10}}
{{ci_signed:shipped_score_over_size_delta_at_10}} at k=10, excluding zero.
At k=100 it is {{signed:shipped_score_over_size_delta_at_100}}
{{ci_signed:shipped_score_over_size_delta_at_100}} — **not distinguishable
from the baseline.** The accurate claim is *"the score beats node count where
the alert budget lives, and ties with it at a depth no analyst reaches"*.

### Conditioning, stated with the number rather than after it

- A candidate counts as a hit at ≥ {{count_pct:hit_share}} of a ring **and**
  Jaccard ≥ {{count:min_jaccard}}. Containment alone lets a node-count baseline
  tie the scorer.
- p@k is counted over **candidates**, so a cycle emitting three surviving
  candidates for one ring pays three times for one detection. The distinct-ring
  reading is lower for every ranking.
- The largest loss in the pipeline is at **{{count:funnel_largest_loss_stage}}**:
  {{count_pct:funnel_seeded_recall}} of active rings are seeded,
  {{count_pct:funnel_built_recall}} are built, {{count_pct:funnel_ranked_recall}}
  are ranked into the top 50.

### The number that is NOT the headline

A supervised re-ranker on the same features reaches
{{metric_ci:supervised_p_at_10}} at k=10 on a ring-disjoint held-out split of
{{count:n_held_out_cycles}} cycles. **It is not quoted as a result** for two
reasons, both measured:

1. It trains on ground-truth ring labels, which no deployment has on day one.
2. Against the shipped blend its paired delta is
   {{signed:supervised_over_blend_delta_at_10}}
   {{ci_signed:supervised_over_blend_delta_at_10}} — **includes zero.**

---

## 2. The pre-registered rule that would have invalidated the conclusion

Written in `docs/ARCHITECTURE_UPLIFT.md` §8 item 0.1 **before** the measurement:

> I expect oracle p@10 to fall somewhat but the oracle/blend ratio to stay
> ≥ 2×. **If the ratio collapses below ~1.5×, §1 is wrong and should be
> re-scoped toward features before a week is spent on the ranker.**

The rule was encoded as a branch in `scripts/eval_oracle.py` before it ran, so
the verdict is selected by the script rather than chosen by hand.

**Measured: {{count:oracle_over_blend_ratio_at_10_NO_INTERVAL}}× at k=10 and
{{count:oracle_over_blend_ratio_at_20_NO_INTERVAL}}× at k=20** — both below the
kill line. (Those two figures are ratios of point estimates and
`scripts/eval_oracle.py` stores no interval for them. The `NO_INTERVAL` in
their identifiers is deliberate: they cannot be published as metrics here
because the contract in `sentinel/report/metric.py` refuses a value without an
interval, so they are carried as counts with the absence in the name.)

---

## 3. The retraction published when the rule fired

**The centrepiece of the plan was cancelled by its own rule.**
Full text: [`docs/CENTREPIECE-INVALIDATED.md`](CENTREPIECE-INVALIDATED.md) and
[`docs/negative-results/centrepiece-invalidated.md`](negative-results/centrepiece-invalidated.md).

The cause is not the model getting worse. Two hand-set blend terms were
measured as anti-signal and retired; **the floor rose rather than the ceiling
falling**, and most of the headroom the plan rested on turned out to be a
measurement of two backwards weights.

**A second pre-registration fired later, in the opposite direction.** §8 item
1.3 predicted the listwise-vs-pointwise interval would still include zero. It
now excludes zero at every k — {{signed:lambdamart_over_pointwise_delta_at_10}}
{{ci_signed:lambdamart_over_pointwise_delta_at_10}} at k=10 — because a
training confound was removed. That is a **failed** pre-registration reported
as such, and it still does not license shipping the listwise model: the gain
was bought by deleting 156 training positives and both absolute numbers fell.
[`docs/negative-results/lambdamart-reversal.md`](negative-results/lambdamart-reversal.md).

---

## 4. What the measurement actually found

Four results survive, and none is the one the plan was built on.

### The bottleneck is seeding, not scoring

Same scorer, same harness, same {{count:n_held_out_cycles}} cycles — only the
seed rule differs. With seeding cheated to fire on every active ring's own
members:

**{{ratio_ci:seeding_prize_blend_ratio_at_10}}** at k=10 for the shipped
scorer. The scorer prize over the same pool is
{{count:oracle_over_blend_ratio_at_10_NO_INTERVAL}}× — **below the seeding
interval's lower bound.**

A baseline that reads no features at all collects
{{ratio_ci:seeding_prize_size_ratio_at_10}}, essentially the whole prize, which
is the strongest evidence that this is about the pool *containing* the rings
rather than ranking them.

> **CEILING DIAGNOSTIC.** The cheat seeds on ring members, which the real
> detector can never do. This is headroom, not an achievable score.

### And the mechanism is now named

Of {{count:n_active_rings}} active rings, {{count:n_rings_seeded_honestly}} are
seeded honestly — but {{count:n_rings_rescued_by_cheat}} of them are not
recovered, and are rescued by the cheat. **51% of those have their ring split
across two or more components of its own induced subgraph inside the window,
against 5.7% of the rings that are recovered.** The seed is present and
stranded in one fragment.

Relaxing every expansion knob makes this **worse**, not better — coverage falls
from 24% to 4% as the budget is loosened, because the extra reach drags in
bystanders until the Jaccard floor rejects the candidate.
[`docs/PHASE2-SEED-CHEAT-FINDINGS.md`](PHASE2-SEED-CHEAT-FINDINGS.md).

### The label tax is a coefficient, not a hypothesis

Pre-registered in `prereg/label_tax_noise.md` before the runner existed; the
runner refuses to start without a committed prereg and records the sha it ran
against.

**Δ p@10 = {{signed:label_tax_noise_slope_per_0_1}}
{{ci_signed:label_tax_noise_slope_per_0_1}} per 0.1 increase in the
positive-label flip rate**, n = {{count:n_held_out_cycles}} cycles.

**And it is not prevalence drift.** The prevalence-matched control — same count
of correct positives, the flipped rows absent rather than present-and-wrong —
shows no resolvable effect. The cost is paid for label *quality*.

Separately, and never averaged with it: **Δ p@10 =
{{signed:label_tax_budget_slope_per_halving}}
{{ci_signed:label_tax_budget_slope_per_halving}} per halving of the label
budget.** [`docs/PHASE3-LABEL-TAX-FINDINGS.md`](PHASE3-LABEL-TAX-FINDINGS.md).

### The engine generalises; the claim that motivated the generalisation does not

A second domain — **synthetic identity in onboarding data** — was added because
`prereg/cycles.md` had already established that `n` cannot be raised by
generating more AMLworld cycles, and a second dataset was the only rejected
option rejected on cost rather than on principle.

**It had to survive a kill rule committed before the generator existed.** Four
trivial baselines, any of which solving the problem would have thrown the domain
out: degree, attribute multiplicity, component size, and rare-attribute
multiplicity. {{count:n_identity_configs_passing}} of
{{count:n_identity_configs}} configurations pass against a pre-registered floor
of {{count:n_identity_configs_required}}; the rest are marked `TOO_EASY` and
excluded from every later phase.

**The same harness runs both domains.** `WindowedGraph`, `CandidateGenerator`,
`FunnelTracker` and `is_hit` are the same objects, and the identity path adds no
second implementation of any of them. Three things did not transfer and are
argued where they are decided: no window (this adversary spaces registrations
deliberately, so a window would make fragmentation its own artefact), an
exogenous seed rule (the co-occurrence graph is undirected, so pass-through
would seed the entire population), and the Jaccard floor inherited **unchanged**
so the two domains stay comparable.

**The pre-registered prediction was a dose-response, and it holds.** Seed-reach
coverage — what a 2-hop expansion from a group's own seeds can see of it —
falls monotonically as the adversary's rotation rises:

**{{signed:identity_coverage_delta_rotation}}
{{ci_signed:identity_coverage_delta_rotation}}** for
coverage(rotation 0.7) − coverage(rotation 0.3), paired on the same worlds. The
mechanism holds too: cluster diameter rises with rotation, and the effect
vanishes at cluster size 3, where a chain fits inside two hops however hard it
rotates.

**The cross-domain claim is refuted.** Measured on the same definition,
identity coverage is {{metric_ci:identity_seed_reach_coverage}} against
AMLworld's {{metric_ci:amlworld_seed_reach_coverage}} — it fragments *less*,
not more, which is the opposite of the prediction the domain was proposed on.
That prediction was demoted to secondary-descriptive **before** measuring, on
the grounds that the identity domain's difficulty is a dial this project sets;
it is recorded in
[`identity-fragments-worse-refuted`](negative-results/identity-fragments-worse-refuted.md)
rather than absorbed.

The two numbers are reported side by side and never pooled.
`require_same_dataset` refuses — a guard added in this work after
`candidate_provenance`, which looked like the cross-domain guard, was found to
agree with itself across two domains that both construct their candidates.

[`docs/PHASEA-IDENTITY-BACKGROUND.md`](PHASEA-IDENTITY-BACKGROUND.md),
[`docs/PHASED-FRAGMENTATION.md`](PHASED-FRAGMENTATION.md).

---

## 5. The negative-results index

[`docs/negative-results/`](negative-results/) — **append-only, enforced against
git history.** Every entry names the measurement that would reverse it, which
is checked by a test; a negative result without a reversal condition is an
opinion.

| entry | what it records |
|---|---|
| [centrepiece-invalidated](negative-results/centrepiece-invalidated.md) | The plan's centrepiece missed its own pre-registered bar. |
| [lambdamart-not-shippable](negative-results/lambdamart-not-shippable.md) | Kept unedited, with a pointer to its own reversal. |
| [lambdamart-reversal](negative-results/lambdamart-reversal.md) | Removing a confound flipped that verdict — and cost the supervised model its lead over the blend. |
| [dead-query-groups](negative-results/dead-query-groups.md) | 18 of 34 training query groups were all-positive; 156 of 321 positives contributed no gradient. |
| [builder-budget-refuted](negative-results/builder-budget-refuted.md) | Every expansion knob makes coverage worse. |
| [analyst-pool-mismatch](negative-results/analyst-pool-mismatch.md) | An experiment four files called "cheap and unrun" is **ill-posed**. |
| [label-noise-non-monotone](negative-results/label-noise-non-monotone.md) | p@10 rises before it falls; recorded, bounded, not spun. |
| [gfp-parity-unmeasured](negative-results/gfp-parity-unmeasured.md) | Every parity claim with IBM's GFP was struck. |
| [inert-seed-sweep](negative-results/inert-seed-sweep.md) | A five-seed sweep was one fit reported five times. |
| [median-amount-features](negative-results/median-amount-features.md) | Closing a coverage gap did not help. |
| [elliptic2-cancelled](negative-results/elliptic2-cancelled.md) | The second dataset was cancelled on a schema fact. |
| [template-literal-leak](negative-results/template-literal-leak.md) | The rendering system in §6 had, in its own template, the defect it was built to prevent. |
| [identity-fragments-worse-refuted](negative-results/identity-fragments-worse-refuted.md) | The prediction that motivated the second domain went the other way. The dose-response inside it held. |

---

## 6. The methodology is enforced, not promised

**This is the part worth looking at.** Most submissions claim rigour in prose.
Prose does not fail a build.

[`docs/STANDING-RULES.md`](STANDING-RULES.md) states seven rules. Four of them
are **constructor preconditions** in [`sentinel/report/metric.py`](../sentinel/report/metric.py):
a p@k without its size baseline, a ring-unit metric without its conditioning
banner, an Elliptic2 metric without prevalence, or an interval that does not
name its clustering **cannot be constructed**, and therefore cannot be printed,
stored, or rendered into a document.

| rule | enforced by |
|---|---|
| 1 · never state an unmeasured number | nothing in `sentinel/report/` can compute a value; a ledgered ratchet on prose literals |
| 2 · p@k carries its size baseline | `tests/test_standing_rules.py::TestRule2SizeBaseline` |
| 3 · ring-unit carries its conditioning | `tests/test_standing_rules.py::TestRule3ConditioningBanner` |
| 4 · Elliptic2 carries prevalence | `tests/test_standing_rules.py::TestRule4Prevalence` |
| 5 · intervals name their clustering | `tests/test_standing_rules.py::TestRule5IntervalNamesItsClustering` |
| 6 · `sentinel.llm` out of measured paths | `tests/test_import_boundaries.py` (runtime) **and** `tests/test_measured_path_closure.py` (static AST walk from every entry point) |
| 7 · negative results are append-only | `tests/test_standing_rules.py::TestRule7NegativeResultsAreAppendOnly`, read from git history |

**Rule 5 was rewritten because it was wrong.** It originally read "use
ring-clustered bootstrap, never cycle-clustered". For p@k that is wrong — the
trials are not nested within rings and the cycle *is* the correct cluster. It
now reads: cluster on the unit the trials nest in, report the wider where both
are defined, and always name the method. The measurement behind the
restatement: on the ring-unit metric, cycle-clustering returns a 0.0396-wide
interval where ring-clustering returns 0.0890.

### The defect this document's own format exists to fix

<!-- historical: measured at commit unknown, 2026-08-31 -->
`0.2778` appeared **14 times** in README and was wrong twice over: the
supervised p@10 moved when two inverted blend weights were retired, and again
when the dead query groups were closed. **Nobody edited README either time**,
because nothing failed when it went stale.

README and this file are now rendered from `results/metrics.json`. Rendering
**fails** on a missing id or a null required field rather than leaving a hole,
there is no escape-hatch verb that would emit a bare number, and a test asserts
the committed files match a fresh render. Unmarked metric literals in prose
fell from 1,835 to {{count:n_prose_literals}} repository-wide, held by a ledger
in which every increase must carry a date, a commit and a reason.

**And that was not enough, which is the more useful half of this section.** The
render check compares the rendered file to the template. It is blind in exactly
one direction: a number typed into the *template* renders faithfully and is
certified correct by a passing test.

<!-- historical: measured at commit 6253ac5, 2026-08-30 -->
Six unmarked instances of `0.278` — a
superseded reading of the same `supervised_p_at_10` this section is about,
which is {{metric:supervised_p_at_10}} — survived that way, further down the
same file than a blockquote narrating both of the corrections that made them
stale. The ratchet did not see them either: it counts literals, and six
literals already in the count do not raise it when the measurement behind them
moves. **A count cannot detect staleness.**

The fix is a third check, and it is a property rather than a count:
`sentinel/report/literals.py::stale_literals` walks the git history of
`results/metrics.json`, collects every value each live metric id has held and
no longer holds, and fails the build when one appears unmarked in a template.
Values that predate the metrics file are declared explicitly, because git
cannot reach them. `tests/test_prose_literals.py` enforces zero in templates
and holds `docs/` — session records and findings documents, which narrate past
states by nature — to a ratchet of its own.
[`docs/negative-results/template-literal-leak.md`](negative-results/template-literal-leak.md).

### The guard that was assumed to exist, and did not

Adding a second domain exposed one. `require_poolable` compared
`candidate_provenance` and nothing else — and seed-and-expand candidates are
`constructed` in *every* domain, so it would have found one shared value and
pooled two domains sharing no feature space. The separator was always `dataset`
and nothing looked at it. `require_same_dataset` now refuses before the question
is even considered, and `tests/test_corpus.py` carries the negative control
asserting the two keys agree on provenance — so the fix cannot be mistaken for a
fix to something else.

---

## 7. What this is not

- **Not a deployment.** Trained and evaluated on one synthetic benchmark and
  one generated one.
- **Not a supervised result.** What ships trains on nothing. The supervised
  number exists, is reported, and does not clear the shipped scorer.
- **Not comparable to published transaction-level F1.** Different unit,
  different population.
- **Not verified against IBM's Graph Feature Preprocessor.** Every parity claim
  was struck; the comparison needs Linux and has never been run.
- **Not measured at adequate `n` on AMLworld.** {{count:n_held_out_cycles}}
  held-out cycles. The intervals are wide and every one of them is printed.
- **Not a claim that the second domain resembles real onboarding data.** It is
  generated, its prevalence is a parameter, and its difficulty is a dial. What
  it buys is a randomness knob AMLworld does not have and an adversary whose
  strength can be swept — not external validity.
- **Not causal on the identity side.** That path is a static full-graph pass, so
  every feature sees applications that arrived after the one under review. No
  identity number is a claim about what was detectable at the time.
- **Not a calibrated identity risk score.** The case file has no confidence
  field to fill in, and the merchant brief refuses to quote a likelihood,
  because none has been calibrated for that population.

`n` was **not** raised by generating more cycles, and the decision is
pre-registered in [`prereg/cycles.md`](../prereg/cycles.md): the pipeline is
fully deterministic, so re-running produces byte-identical output, and the only
cheap way to add cycles produces correlated observations — a narrower interval
with no more information behind it.

It was raised instead by paying for the one option that file rejected on cost
rather than principle: a second domain with genuine independence between draws.
That does not repair the AMLworld intervals, and it is not offered as doing so.

---

## Reproducing

```
python scripts/eval_phase2.py          # the shipped queue
python scripts/eval_oracle.py          # both seeding arms
python scripts/eval_seed_cheat_diff.py # which rings the cheat rescues
python scripts/eval_label_tax.py --arm noise
python scripts/eval_label_tax.py --arm budget
python scripts/collect_metrics.py      # -> results/metrics.json
python scripts/render_docs.py          # -> README.md, docs/SUBMISSION.md
python -m pytest && python scripts/ci_gates.py all
```
