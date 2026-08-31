# Why the score did not beat node count, and what fixed it

Open problem 1 in the README, from the day the prune landed:

> **The scorer no longer clearly beats a node-count baseline.** Post-pruning,
> the score's margin over `size` has collapsed to statistical noise at
> k = 10, 20 and 50, and at k = 100 size wins significantly.

That was right, and its own guess at the mechanism was close but pointed the
wrong way:

> Pruning normalised candidate size (mean 17 to 8.2 nodes), so node count went
> from an anti-signal to a real one and **the hand-set weights are not
> exploiting the tighter candidates.**

The weights were not failing to exploit size. **Two of them were exploiting it
backwards.** Everything below is `scripts/eval_blend_v2.py`, reading the
compiled corpus — a scorer question, so it costs seconds rather than a replay.

---

## 1. The obvious explanation is false

The first thing to rule out is that the blend had quietly reinvented node count,
in which case "indistinguishable from size" would be a tautology rather than a
finding.

    Spearman(v1 blend, size)          -0.0988
    within-cycle median                -0.0818   (range -0.2176 .. -0.0492)

It is *negatively* rank-correlated with size, in every held-out cycle. And the
blend's rank, residualised on size's rank within cycle, still scores AUC 0.6719
against the label — so the blend carried real signal that size does not carry.

A scorer that carries independent signal, and still loses to the thing it is
independent of, is a more interesting object than a redundant one.

## 2. Per-term sign, with size held exactly constant

`size` is itself predictive (AUC 0.7104), so any term correlated with size
inherits an apparent signal it does not own. The controlled version stratifies
on the **41 distinct node counts** and pools — size is a small integer with
heavy ties, so quantile strata collapse on it and exact strata are both easier
and stricter. 23 strata carry both classes.

| term | v1 weight | fires on | raw AUC | **AUC, size fixed** | ρ(size) | verdict |
|---|---:|---:|---:|---:|---:|---|
| temporal_cycle | 0.22 | 0.0% | 0.6005 | 0.5529 | +0.03 | positive |
| conservation | 0.15 | 86.9% | 0.5028 | 0.5446 | −0.01 | positive |
| fast_passthrough | 0.12 | 11.2% | 0.5815 | 0.5501 | +0.16 | positive |
| scatter_gather | 0.10 | 1.8% | 0.5954 | 0.5260 | +0.14 | null |
| **gargaml** | **0.09** | **100.0%** | 0.3577 | **0.4534** | **−0.50** | **INVERTED** |
| cycle | 0.08 | 0.0% | 0.6066 | 0.5533 | +0.03 | positive |
| gather_scatter | 0.05 | 28.5% | 0.6292 | 0.5104 | +0.58 | null |
| bipartite | 0.05 | 9.9% | 0.5175 | 0.4752 | +0.42 | null |
| **stack** | **0.05** | **99.6%** | 0.3601 | **0.4552** | **−0.50** | **INVERTED** |
| passthrough | 0.04 | 100.0% | 0.5548 | 0.5579 | −0.69 | positive |
| cross_border | 0.03 | 47.2% | 0.7964 | 0.7036 | +0.18 | positive |
| burstiness | 0.01 | 100.0% | 0.5466 | 0.3264 | +0.71 | INVERTED |
| round_amounts | 0.01 | 0.0% | 0.4999 | 0.4999 | +0.01 | null |
| *size (itself)* | — | — | **0.7104** | — | — | — |

Three things fall out.

**`gargaml` and `stack` are inverted, and they are the problem.** Both are
near-saturated across nearly every candidate — `gargaml` fires on 100% with
mean 0.915, `stack` on 99.6% with mean 0.910. A term that is almost always ~0.91
contributes almost nothing but its *variance* to a ranking, and their variance
is an inverse proxy for size (ρ = −0.495 and −0.499). Post-pruning, size became
a genuine positive signal, so 0.14 of the weight was ordering the queue by
smallness. The inversion is not merely a size artefact: with node count held
exactly constant they still score 0.4534 and 0.4552, below 0.5 on their own
terms.

**The strongest term carries the smallest weight.** `cross_border` scores 0.7036
with size fixed — on its own, roughly as discriminative as the size baseline —
against a hand-set weight of 0.03. Flagged rather than exploited; see §5.

**The rarest terms are the precise ones.** `temporal_cycle` and `cycle` fire on
under 0.1% of candidates. At k=10 that rarity is a virtue, and it was being
drowned: 0.14 of weight moving smoothly across every candidate swamps 0.30 of
weight that is zero on 99.9% of them.

## 3. The fix is a removal, not a model

`gargaml` and `stack` zeroed, the remaining eleven weights renormalised. No
fitting. 18 held-out cycles, ring-disjoint split.

| ranking | p@10 | p@20 | p@50 | p@100 |
|---|---:|---:|---:|---:|
| v1 (retired terms restored) | 0.0500 | 0.0389 | 0.0244 | 0.0144 |
| **shipped (terms retired)** | **0.1889** | **0.1000** | **0.0467** | **0.0244** |
| nnls fit on train | 0.1944 | 0.1028 | 0.0478 | 0.0267 |
| size | 0.0444 | 0.0444 | 0.0256 | 0.0183 |
| degree | 0.0167 | 0.0389 | 0.0278 | 0.0200 |
| random | 0.0000 | 0.0000 | 0.0000 | 0.0000 |

Paired delta against the size baseline, cycle-clustered bootstrap, 2000
resamples. The ship criterion is the repo's existing one: the delta versus
`size` must exclude zero at **both** k=10 and k=20.

| k | v1 − size | shipped − size |
|---:|---|---|
| 10 | +0.0056 [−0.0167, +0.0278] — includes zero | **+0.1444 [+0.0556, +0.2444]** |
| 20 | −0.0056 [−0.0278, +0.0167] — includes zero | **+0.0556 [+0.0167, +0.1000]** |
| 50 | −0.0011 [−0.0133, +0.0111] — includes zero | **+0.0211 [+0.0078, +0.0367]** |
| 100 | −0.0039 [−0.0106, +0.0017] — includes zero | **+0.0061 [+0.0011, +0.0122]** |

**Ship criterion: NOT met by v1, met by the removal, at every k including
k=100 — the depth where size used to win.**

### The fitted control, which is why the shipped fix is a removal

A non-negative least-squares fit of all thirteen weights on the training split
reaches +0.1500 [+0.0722, +0.2389] at k=10. That point estimate sits *inside*
the removal's interval. The fit charges the full label tax — it needs
ring-labelled training candidates, which a deployment does not have — and buys
nothing measurable for it. It is reported because it was run and it is the
honest control, not because it won. A test asserts this relationship, so if the
fit ever does pull clear the justification for shipping the simpler thing fails
loudly.

Notably the fit independently agrees about the diagnosis: it drives `gargaml`
and `stack` to exactly zero on its own.

## 4. Robustness

* **Not one lucky cycle.** Per-cycle hits@10, shipped vs size:
  `[0,0,0,0,0,0,0,0,2,6,1,2,6,5,6,3,1,2]` vs
  `[0,0,0,0,0,0,0,0,0,1,0,0,1,1,1,1,2,1]` — better in 9 of 18 cycles, worse in
  1, tied in 8 (eight of those ties are cycles where both find nothing).
* **Stable under resampling the training rings.** 30 refits on ring-bootstrapped
  training sets: median p@10 0.1944, range [0.1667, 0.2111]; 30 of 30 beat the
  size baseline.
* **Does not depend on `cross_border`.** Zeroing it too and renormalising gives
  +0.1889 [+0.0944, +0.3000] at k=10 — slightly *better*. The result does not
  rest on the one feature most likely to be a generator artefact.
* **Confirmed on the independent CI fixture.** The regression gate's mini
  fixture, a different graph entirely, moved p@10 0.1000 → 0.2000, p@20
  0.0500 → 0.1167, p@50 0.0533 → 0.1000, ring recall 0.1818 → 0.2500.
* **`burstiness` was left alone.** It measures as inverted (0.3264) but carries
  weight 0.01, and dropping it changes p@10, p@20 and p@50 by exactly nothing.
  Recorded, not acted on: a change that moves no number should not be shipped
  as though it did.

## 5. On the shipped 34-cycle design

Sections 1-4 are the held-out ranker design, which isolates the ranking effect
on a fixed candidate set. The README's headline table is a different
measurement: a full replay over 34 generation cycles, 259 rings. Re-run after
the retirement (`scripts/eval_phase2.py`, ~6 minutes):

| ranking | p@10 | p@20 | p@50 | p@100 | ring recall |
|---|---:|---:|---:|---:|---:|
| **score** | **0.291** | **0.157** | **0.076** | 0.041 | **23.9%** (62 rings) |
| size | 0.094 | 0.074 | 0.051 | 0.035 | 18.5% (48) |
| degree | 0.065 | 0.072 | 0.049 | 0.035 | 16.6% (43) |
| random | 0.000 | 0.004 | 0.004 | 0.002 | 5.4% (14) |

Score minus size, paired bootstrap over the same 34 cycles:

| k | delta | 95% CI | verdict |
|---:|---:|---|---|
| 10 | **+0.1971** | [+0.1235, +0.2676] | **excludes zero** |
| 20 | **+0.0838** | [+0.0471, +0.1176] | **excludes zero** |
| 50 | **+0.0253** | [+0.0088, +0.0412] | **excludes zero** |
| 100 | +0.0056 | [−0.0032, +0.0135] | includes zero |

Before the retirement the same four rows read +0.009 [−0.027, +0.041],
+0.006 [−0.021, +0.031], −0.007 [−0.019, +0.005] and −0.009 [−0.016, −0.002].

**Open problem 1 is closed at k=10, 20 and 50, and downgraded at k=100.** At
k=100 size no longer wins; the two are now indistinguishable. "The score beats
node count where the alert budget lives, and ties with it at a depth no analyst
reaches" is the accurate statement, and it is not the same as "the score wins
everywhere."

`eval_phase2.py` now retains per-cycle rows and computes that paired delta
itself. It previously stored only running totals, which meant the headline
table structurally could not carry an interval -- the comparison it exists to
support had to be eyeballed.

### The gain is larger here than in section 3, and the reason matters

The held-out measurement gives +0.1444 at k=10; this one gives +0.1971. The
difference is not noise and not a better result -- it is a **different effect
being included**, and it is worth stating because it means this is not a pure
re-ranking.

`suppress()` in `sentinel/detect/merge.py` is greedy non-maximum suppression
**ordered by score**. When several overlapping views of the same neighbourhood
compete, the highest-scoring one survives and absorbs the rest. So the score
does not only order the queue; it decides which candidate exists to be ordered.

Two consequences, both visible in the numbers:

* The candidate set changed. Per-cycle counts moved slightly (run 1: 15,496 to
  15,494), and 8,473 candidates were suppressed across the run.
* **The size baseline moved too**, 0.0882 to 0.0941 at k=10, despite `size`
  being a ranking that ignores the score entirely. That is the tell. A pure
  re-ranking cannot move its own baseline.

The paired comparison within each run is still valid -- score and size are
ranked over the identical candidate set in every cycle. But the improvement
reported here is the JOINT effect of better ranking and better survivor
selection, and only section 3's +0.1444 is the ranking effect alone. Anyone
attributing the whole 0.097 to 0.291 move to "better weights" is over-claiming;
roughly three quarters of it is ranking and the remainder is which candidates
survived suppression. **Decomposing that split exactly is not done here and is
a "must measure".**

## 6. What this is not

**It is not a claim about GARG-AML.** `gargaml` implements a published method.
What is measured here is that on AMLworld HI-Small, after this project's prune
strategy, that term does not discriminate ring membership and its variance is
an inverse size proxy. A different dataset, or this one without the prune,
could easily read differently.

**The terms are zeroed, not deleted.** The case file still shows an analyst the
GARG-AML and stack readings as evidence; they no longer drive the rank. Losing
them from the case file would be a regression even though the ranking improved,
and a test enforces that they stay in the contribution breakdown.

**`cross_border` is not being exploited, on purpose.** At AUC 0.7036 with size
fixed it is the strongest single term measured here, on 0.035 of the weight —
and it has the exact smell of `channel`, the feature this project already
excluded for being a generator artefact (86.6% of laundering rows ACH against
an 11.8% base rate). AMLworld injects its typologies, and "the injected rings
cross borders" is the kind of thing a generator decides rather than the world.
Raising its weight is not on the list until it has been checked against a real
dataset. **Must measure.**

**It is measured on the ring-disjoint held-out split, not on a time split.**
Train and test cycles overlap; only the rings are disjoint. That is README open
problem 2, and this result inherits it rather than fixing it. It is the same
design the supervised re-ranker figures use, so those remain comparable.

**It does not close the ranking loss.** The funnel's −39.8 points at the ranking
stage was never going to be fixed by two weights. The supervised re-ranker still
reaches p@10 0.2778 on the oracle design against this blend's 0.1889, so a
learned scorer remains ahead of a hand-set one — it just now leads a scorer that
beats its baseline rather than one that does not.


---

## 7. What this opened

**The corpus key has a hole, and this change found it.** `sentinel/corpus/`
partitions questions into "scorer questions, fully cacheable" and "generation
questions, need a replay", and puts the blend on the cacheable side. That is
wrong at the edges: `suppress()` orders by score, so the weights help decide
which candidates exist. `WEIGHTS` is not in `_GENERATION_CONSTANTS` (putting it
there would discard a 55-minute compile for every weight tried) and
`verify_scoring` cannot see it either, because rescoring makes the stored blend
agree with today's code while leaving the candidate set stale.

Nothing measured here is wrong because of it — section 3 compares rankings on a
fixed candidate set and says so, and section 5 is a fresh replay. But the corpus
now in `data/` holds a candidate set selected under the OLD weights, and must
not be used to answer "what would the shipped queue do". **Must fix.**

**`data/eval_oracle.json` is stale and was deliberately not re-run.** Its
supervised p@10 of 0.2778 comes from a replay under the old weights, and
re-running it would desync it from the corpus that
`test_corpus_refit_reproduces_the_stored_held_out_p_at_10` checks against.
What can be said without it, from `scripts/eval_ranker.py --use-cache` on the
shared pool: the pointwise model reaches 0.2778 against the corrected blend's
0.1889, a paired delta of **+0.0889 [+0.0333, +0.1500]**. That delta was
+0.2278 against the uncorrected blend. **The supervised model's lead over the
hand-set score has fallen by roughly 60%** — it is still real and still excludes
zero, but the label-tax argument is now carrying a much smaller number than it
was, and the README says so where it makes the claim.

**The re-tie check now passes for the blend itself.** `eval_ranker.py`'s
"does anything beat node count?" gate marked `blend` *not shippable* before and
marks it **SHIPPABLE** now. That is an independent confirmation on a different
statistic from section 5's.

**Open, in priority order.**

* **The corpus/NMS hole above. Must fix.**
* **Re-run `eval_oracle.py` under the corrected weights** and restate the label
  tax on a consistent pool. Must measure.
* **Decompose the 34-cycle gain** into ranking versus survivor selection. The
  bounds are +0.144 (ranking alone, fixed candidate set) and +0.197 (joint), so
  the split is roughly three quarters / one quarter — but that is arithmetic on
  two different designs, not a measurement. Must measure.
* **`cross_border`.** Strongest single term measured (AUC 0.7036 with size held
  constant) on 0.035 of the weight, and deliberately not exploited: it has the
  same signature as `channel`, already excluded as a generator artefact. Check
  against a real dataset before touching its weight. Must measure.
* **The k=100 tie.** Size no longer wins there, but the score does not win
  either.
* **`burstiness`** measures as inverted (AUC 0.3264) but moves no number at
  weight 0.01. Recorded, not acted on.
