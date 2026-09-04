# B1 — fragment linking does not assemble unreachable rings, and its apparent win is mostly size

**Pre-registered in [`prereg/fragment_linking.md`](../prereg/fragment_linking.md)**
before `sentinel/detect/link.py` existed. Run 2026-09-04, 34 cycles, 480 s,
`scripts/eval_fragment_link.py` → `data/eval_fragment_link.json`.
Cycle-clustered paired bootstrap. 1,788 merges over 34 cycles (mean 52.6/cycle,
0.52% pool growth, 0.13 s/cycle).

## Headline

**Kill criterion 1 fired. Built-recall is 161 in all three arms — linking added
zero rings.** The mechanism does not do the thing B1 was proposed to do.

**A large, unpredicted p@k gain appeared — and most of it is available to a
ranker that reads no features.** Under `link` the score's margin over the size
baseline collapses: CI-clear at k=10 only, includes zero at k=20 and k=50, and
the point estimate goes *negative* at k=50. That is bug #8's pattern.

**Distinct rings surfaced in the top 50 fell, 58 → 55.**

**Verdict: refuted as scoped. Do not ship.**

## 1. The arms

| arm | mean pool | built | ranked@50 | p@10 | p@20 | p@50 |
|---|---:|---:|---:|---:|---:|---:|
| `shipped` | 10,193 | **161** | **58** | 0.2912 | 0.1574 | 0.0759 |
| `link` | 10,245 | **161** | **55** | 0.3353 | 0.2279 | 0.1288 |
| `link_random` (null) | 10,245 | **161** | 53 | 0.2882 | 0.1676 | 0.0771 |

Paired deltas on score p@k:

| | k=10 | k=20 | k=50 |
|---|---|---|---|
| link − shipped | +0.0441 [−0.003, +0.088] | **+0.0706 [+0.038, +0.115]** | **+0.0529 [+0.028, +0.084]** |
| link − link_random | **+0.0471 [+0.006, +0.091]** | **+0.0603 [+0.029, +0.101]** | **+0.0518 [+0.028, +0.081]** |
| link_random − shipped | −0.0029 [−0.021, +0.018] | +0.0103 [+0.003, +0.019] | +0.0012 [−0.003, +0.006] |

Read alone, that table looks like a win: `link` beats both the shipped arm and
its own null, CI-clear, at k=20 and k=50. **It is not, and §3 is why.**

## 2. Kill criterion 1 fired: no ring was newly reached

`built` is **161 in every arm**, including the random null. Linking did not put
a single additional ring inside a covering candidate.

This is not a marginal miss. B1's entire premise —
`PHASE2-SEED-CHEAT-FINDINGS.md` §H2, that 51% of cheat-rescued rings are split
across components and the seed is present but stranded — implies that joining
fragments should *reach* rings that no single candidate covers. It did not
reach one.

Note the criterion could not have distinguished much anyway: with `link_random`
also at 161, `link ≤ link_random` was going to hold on a saturated metric. The
comparison was better-posed than the number turned out to allow, and that is
recorded rather than glossed.

**What actually happened** is visible in the p@k table: the rings covered are
the *same* rings, but merged candidates **rank higher**, so more of them land in
the top k. Fragment linking is behaving as a **ranking** intervention, not a
generation one.

## 3. Why the p@k gain does not count: the size baseline moves with it

Standing rule 2 — quote p@k beside its size baseline — is what catches this.

| arm | k | score | **size** | score − size | 95% CI | |
|---|---:|---:|---:|---:|---|---|
| shipped | 10 | 0.2912 | 0.0882 | +0.2029 | [+0.1353, +0.2676] | clear |
| shipped | 20 | 0.1574 | 0.0676 | +0.0897 | [+0.0529, +0.1235] | clear |
| shipped | 50 | 0.0759 | 0.0488 | +0.0271 | [+0.0112, +0.0418] | clear |
| **link** | 10 | 0.3353 | 0.2059 | +0.1294 | [+0.0235, +0.2206] | clear |
| **link** | 20 | 0.2279 | 0.1824 | +0.0456 | [−0.0324, +0.1059] | **includes zero** |
| **link** | 50 | 0.1288 | **0.1341** | **−0.0053** | [−0.0412, +0.0229] | **includes zero, size ahead** |
| link_random | 50 | 0.0771 | 0.0553 | +0.0218 | [+0.0065, +0.0365] | clear |

**The size baseline nearly triples at k=50 under linking, 0.0488 → 0.1341.**
Merged candidates are bigger *and* better, so node count becomes a far stronger
predictor and the score's margin collapses from CI-clear at every k to CI-clear
at k=10 only.

This is exactly bug #8, and exactly what `HANDOFF.md` §5d/§5e recorded when
pruning shipped: a real generation improvement that is mostly available to a
trivial ranker. The correct reading is **not** "p@20 improved 45%". It is: the
score's advantage over counting nodes did not survive the change.

### My kill criterion was written too narrowly, and the script said "not fired"

Kill criterion 3 reads: *"score − size stops being CI-clear at k=10 under
link."* At k=10 it stays clear, so `scripts/eval_fragment_link.py` printed
**"3. score-size under link clear -> not fired"**.

**That is a false negative and the fault is in the pre-registration, not the
code.** Bug #8's rule is not a k=10 rule; it is a rule about the score earning
its place, and it must be read at every k that is reported. Read properly, the
criterion fires at k=20 and k=50.

Recorded here rather than quietly re-read, because a kill criterion that is
narrower than the rule it encodes will keep producing comfortable answers.
**Any future kill criterion that references the size baseline must quantify over
every reported k.**

## 4. Kill criterion 4 fired on the letter, and its interpretation was wrong

| | n | mean containment | mean Jaccard |
|---|---:|---:|---:|
| best **merged** candidate per covered ring | 291 | **0.7852** | 0.2099 |
| best **unmerged** candidate per covered ring | 2,424 | 0.3851 | **0.2235** |

Criterion 4 said: *"If mean Jaccard of merged candidates is lower than the best
unmerged candidate's, linking dilutes rather than assembles."* Jaccard is lower
(0.2099 vs 0.2235), so it fires.

**But the containment column refutes the interpretation attached to it.**
Containment *doubles* — merged candidates capture 78.5% of a ring against 38.5%
for the best unmerged one. Linking is assembling, precisely as intended, at a
Jaccard cost of 0.014.

So the mechanism works at the level it was designed for. It just does not
convert that into a ring that was not already covered, or into a margin over
the size baseline.

**Caveat, stated because the numbers are not over identical sets:** the two rows
have different n (291 vs 2,424) because merged candidates exist for only some
ring-cycle pairs. This is a comparison of best-available quality, not a paired
per-ring comparison.

## 5. Distinct rings surfaced fell

`ranked@50` — distinct rings covered by something in the top 50 — went
**58 → 55** under `link` (and 53 under the null).

At the same time p@50 rose 0.0759 → 0.1288. Both are true, and together they
say the top 50 became **more redundant**: more slots hold a hit, covering fewer
distinct rings. Per typology, `link` loses a ring in CYCLE, FAN-IN,
GATHER-SCATTER and RANDOM, and gains one in SCATTER-GATHER.

For a console whose unit of investigation is the ring, **distinct rings
surfaced is the more product-relevant number of the two**, and it went down.
Quoting the p@50 gain without it would be the misleading half of a true
statement — the same failure mode S1/S2 produced this morning with "+14 built,
+0 ranked".

## 6. Against the pre-registration

| predicted | observed | |
|---|---|---|
| built-recall +2 to +8 rings | **+0** | **MISSED** |
| BIPARTITE and STACK the beneficiaries | neither moved at all | **MISSED** |
| p@10 CI includes zero | it does (+0.0441 [−0.003, +0.088]) | hit |
| p@20 CI includes zero | **it does not — +0.0706 [+0.038, +0.115]** | **MISSED** |
| link − link_random positive on built | 161 vs 161, not positive | **MISSED** |
| score − size CI-clear under link | **only at k=10** | **MISSED** |
| pool growth < 10% | 0.52% | hit |

**Four of seven predictions missed, and the two central ones are wrong in
opposite directions**: I predicted a generation gain with no ranking effect, and
got no generation gain with a large ranking effect that then failed the size
check.

That is a worse score than either earlier experiment today, and it is the most
informative thing on this page. The mechanism does something real — containment
doubles — but not the thing it was proposed to do, and the metric it does move
does not survive its own baseline.

## 7. What is NOT claimed, and what should happen next

**The p@k gain is a post-hoc finding.** It was not predicted; it emerged. Under
this project's own rules it is a *hypothesis*, not a result, and it must not be
quoted as a B1 win. What it licenses is a **new pre-registration**: "does
linking improve ranking, measured with a size-stratified baseline that cannot be
won by making candidates bigger?" That is a different experiment with a
different control, and B3 (score-free suppression) should precede it, because
merged candidates are appended to a score-ordered pool.

**Not shipped.** Linking stays behind `find_links`, unused by
`CandidateGenerator`, until the ranking hypothesis has been pre-registered and
tested against a baseline the size effect cannot win.

**No claim about BlazingAML.** The mechanism was taken; the head-to-head has not
been run; nothing here says anything about their reported results (queue item
X1).
