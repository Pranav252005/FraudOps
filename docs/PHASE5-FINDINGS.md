# Phase 5 findings — the Elliptic2 expansion is cancelled, and why

Four things were asked of this session in order: report the cold corpus
comparison, inspect the Elliptic2 feature schema, confirm whether data access is
a blocker, and add `candidate_provenance` to the corpus key. The schema
inspection was declared the gate: if Elliptic2's features do not map onto the
normalised `Edge`, the expansion does not happen and the plan gets rewritten
rather than continued.

**It does not map. The expansion is cancelled.** The details are in §2, and the
decisive fact is one line long: Elliptic2 ships no transaction amount, only an
anonymous ordinal bin code that might or might not be one.

---

## 1. The cold corpus comparison had already reported

The task list said the four-way comparison "never reported". It had. It is
commit `31130e1`, and re-running the checks against today's artefacts
reproduces it. All four:

| # | check | result |
|---|---|---|
| 1 | key stable on recompile | **yes** — `898f4ab743f8ad7b`, identical |
| 2 | arrays bit-equal, field by field | **no** — see below |
| 3 | derived p@10 vs `eval_oracle.json` | **yes** — 0.2777777777777778, exact |
| 4 | LambdaMART deltas survive an independent replay | **yes** — -0.0167 / +0.0111 / +0.0122, exact |

**Which case obtains: key stable, arrays differ.** That was pre-registered as
the worst case and the most informative one, and it was. Every feature, label,
ring id, tick and baseline matched exactly; `train_blend` and `test_blend`
disagreed by one ULP on 36–38% of rows. The corpus adopted the commit before
had been compiled by different code, and its key matched anyway.

The pre-registered response to that case was "fix the `PYTHONHASHSEED`
determinism gate's coverage hole on the replay path". That response was aimed
at the wrong mechanism, and the session that found it said so: the difference
was not nondeterminism in the replay, it was **staleness in the stored file**.
Recomputing `score()` from the stored features matched the fresh pool and not
the old one, which is a staleness signature and not a seed signature. The fix
landed as `verify_scoring` / `require_consistent` — a behavioural check that
recomputes the v1 blend from the stored features and requires today's code to
agree exactly — rather than as a change to the determinism gate.

Verified again this session on the current artefacts:

```
[1] key stability      pool-recomputed == corpus stamped        True
[2] array equality     all 18 fields equal (corpus vs pool)     True
[3] drift check        800 sampled rows, 0 disagreements        True
```

Two things worth recording rather than glossing:

* **The standing `--adopt` caveat is not retired, and should not be.** Array
  equality failed, so `--adopt` was not validated as a mechanism. What
  happened instead is better: `--adopt` now *checks* the half of its promise
  that is checkable, running the drift check before it writes. The caveat in
  the docstring stays, because the other half — "these generation constants
  really did produce this file" — is still an unverifiable promise.
* **The stale pool was not preserved.** The task list said backups of
  `ranker_pool.npz`, the corpus and `data/eval_ranker.json` were taken. No such
  backups exist on this machine; the pool and corpus were overwritten by the
  cold replay and the adopt that followed. The finding survives in the commit
  message and in the tests (`test_verify_scoring_catches_a_one_ulp_drift`
  reconstructs the exact drift synthetically), but the stale artefact itself is
  gone and cannot be re-examined. Recorded here so nobody goes looking.

---

## 2. Elliptic2 feature schema — the gate, and it fails

A schema inspection, not an experiment. Sources: the released file schemas as
published on Kaggle, the paper (arXiv:2404.19109 §3), and the official
`preprocess_glass.py` in `MITIBMxGraph/Elliptic2`.

### 2.1 What the released files actually contain

| file | size | columns |
|---|---:|---|
| `background_edges.csv` | 82.88 GB | 98 — `clId1`, `clId2`, `txId`, `feat#1` … `feat#95` |
| `background_nodes.csv` | 5.35 GB | 44 — `clId`, `feat#1` … `feat#43` |
| `connected_components.csv` | small | `ccId`, `ccLabel` |
| `nodes.csv` | small | node → component membership |
| `edges.csv` | small | subgraph-internal edges |

This corrects `sentinel/data/elliptic2.py`, whose loader reads only `clId1` and
`clId2` from `background_edges.csv` and hardcodes `amount=1.0`. That is not
wrong as an implementation — 95 columns really are unusable, for the reason
below — but the docstring implied the file *has* only two columns, and it has
98. The loader matches the official preprocessing script, which also takes
`usecols=["clId1","clId2"]` and reads no edge feature at all.

### 2.2 Is edge volume an ordinal bin or a usable magnitude?

**An ordinal bin, and an unidentifiable one.** Two independent reasons, either
sufficient:

1. **Every feature column is a small integer bin code.** Kaggle's own column
   histograms, computed over all 196M edge rows, give the observed range of each
   edge feature: `feat#1` 0–99, `feat#2` 10–88, `feat#3` 0–99, `feat#4` 0–4,
   `feat#5`–`feat#7` 0–9. Sample rows read
   `563997622, 284528470, 50679415, 40, 68, 39, 1, 0, 0, 0`. Node features are
   the same shape, 0–99 integers. This is the paper's stated IP protection,
   confirmed empirically rather than taken on the page: *"most features were
   categorized into bins. The number of bins used varied between features. This
   process converted continuous numerical features into ordinal ones."*
2. **No column is named.** The 95 edge features are `feat#1` … `feat#95`. The
   paper says the edge features *include* transaction volume, fee and timestamp;
   it never says which index is which, and no feature dictionary is published.
   So even granting that some column is a monotone function of volume, there is
   no way to say which — and the bin edges are unpublished, so no inverse exists.

### 2.3 Can value conservation be computed on Elliptic2?

**No.** `conservation = min(inflow, outflow) / max(inflow, outflow)` is a ratio
of *sums of amounts across a candidate boundary*. It needs amounts to be
additive. Ordinal bin codes are not: `bin(a) + bin(b) ≠ bin(a + b)`, the bin
widths differ per feature and are unpublished, and no monotone relabelling
recovers additivity. There is no transformation of a 0–99 bin code that makes a
sum of them mean a sum of money.

**Is there a defensible ordinal analogue?** Something could be defined — compare
the distribution of in-edge bin codes against out-edge bin codes for a
candidate, say by median bin or by a rank statistic. It would be a legitimate
feature. **It would not be the same function**, and that is the point that
decides the plan. It is not a ratio of sums; it does not saturate at 1.0 for a
perfectly conserving ring; it has no units; and its value on a ring that
conserves exactly is not 1.0 but whatever the bin distributions happen to give.
Calling it `conservation` and letting it occupy the same column would put two
different quantities under one name.

**Therefore `feature_version` equality across the two datasets would be a lie
the hash cannot catch,** exactly as the task anticipated. `FEATURE_VERSION`
covers the schema — names, order, count — and a column named `conservation`
carrying a bin-rank statistic on one dataset and a flow ratio on the other has
an identical schema and an identical hash. **Pooling AMLworld and Elliptic2
into one corpus is invalid.**

### 2.4 Which of the three feature families survive the mapping

Of 56 `Features` fields, under the normalised `Edge` that Elliptic2 can
populate (`ts` = a fixed placeholder epoch, `amount` = 1.0, no bank, no country,
no registry):

| family | fields | survives? |
|---|---:|---|
| **structural** — topology only | 22 | **yes**, intact |
| **behavioural, amount-derived** | 16 | no — degenerate |
| **behavioural, time-derived** | 11 | no — every timestamp identical |
| **contextual** — bank, country, registry | 7 | no — no such columns exist |

The amount-derived group is the dangerous one, because **it does not crash; it
silently changes meaning.** With `amount ≡ 1.0`, `inflow` and `outflow` become
boundary *edge counts*, and `conservation` becomes the ratio of the smaller to
the larger boundary degree. That is a real quantity and a plausible-looking
number in the 0–1 range. It is a degree ratio wearing the name of a flow ratio.

The v1 blend's 13 weighted terms split the same way. Surviving:
`scatter_gather` 0.10, `gargaml` 0.09, `cycle` 0.08, `gather_scatter` 0.05,
`bipartite` 0.05, `stack` 0.05, `passthrough` 0.04 — **0.46 of the total
weight.** Lost: `temporal_cycle` 0.22, `conservation` 0.15, `fast_passthrough`
0.12, `cross_border` 0.03, `burstiness` 0.01, `round_amounts` 0.01 — **0.54.**
More than half the shipped score, including its two largest terms, does not
exist on Elliptic2.

### 2.5 The assumption that has to be written down

**Elliptic2 nodes are clusters of Bitcoin addresses, not accounts.** A cluster
is a heuristic grouping of addresses believed to share a controlling entity;
its cardinality varies by orders of magnitude, and the clustering is Elliptic's
and is not published. Any mapping onto `Edge.src` / `Edge.dst` must therefore
assume **one address cluster = one account**. That assumption is not neutral: a
"pass-through account" in AMLworld is one entity forwarding value, while a
pass-through cluster may be an exchange's entire hot-wallet infrastructure. It
was not made in this session because the mapping was cancelled first, but it
would have to be made — and stated beside every number — by anyone who resumes
this.

---

## 3. Data access is not the blocker — and never was the one being routed around

Confirmed in minutes, and the repository had already corrected itself on this
in commit `e3861a7`: Elliptic2 is **public on Kaggle**
(`ellipticco/elliptic2-data-set`, CC BY-NC-ND 4.0), not licence-gated behind
the `elliptic.co/elliptic2` request form the upstream guide points at. All five
expected files are present there.

What *is* in the way, stated plainly so it is not confused with a licence gate:

* **No Kaggle API token on this machine** (`~/.kaggle/kaggle.json` absent) and
  no `kaggle` package in `.venv311`. Both are one-time manual steps the user
  must do; `scripts/download_elliptic2.bat` refuses to run without the token
  and never prompts for credentials, which is correct.
* **68 GB free against a ~26 GB compressed requirement.** Sufficient. The
  extracted set is ~88 GB and must not be extracted; the loader streams out of
  the per-file zips.

`data/eval_elliptic2.json` remains a 10-node fixture with `"is_sample": true`,
and `tests/fixtures/elliptic2_sample/` is synthetic with an invented schema
(`clId,feat1,feat2`) that does not match the real one (`clId,feat#1…feat#43`).
Harmless as a parser fixture; misleading as a schema reference. Noted, not
changed — changing it is only worth doing if the expansion is ever revived.

**None of this was worth routing around, because §2 cancels the destination.**

---

## 4. Task 4 (funnel probe on the background graph) is cancelled

It was to be gated on §2 and §2 fails, but it is worth recording that it fails
twice over — the second reason is independent and would have stopped it anyway.

Seed-and-expand seeds on a **pass-through vertex where value conservation
holds**. Conservation cannot be computed on Elliptic2 (§2.3), so the seed
primitive has no criterion to fire on. What remains after deleting the value
test is a degree test — "has both in- and out-edges" — which on a 49M-node,
196M-edge background graph fires on a large fraction of the graph and is not a
seeding rule. The funnel's first stage, seed-reachable → seeded, would be
measuring something with no relationship to what it measures on AMLworld.

The instruction not to assume the AMLworld 49% end-to-end survival transfers was
right and is now moot: there is no comparable measurement to make. Reviving this
needs the different seed primitive already noted as out of scope for this week
— seeding on an edge-bundle cut rather than a pass-through vertex — and even
that needs a conservation-analogue across the cut, which §2.3 says does not
exist in the same form.

---

## 5. What did land

`candidate_provenance` is now the corpus key's fourth field
(`sentinel/corpus/store.py`), folded into the digest rather than merely carried
beside it — so a corpus built from shipped subgraphs and one built by
seed-and-expand cannot collide on one hash. `require_poolable` makes the caller
name the question and refuses the ones whose answer depends on where the
candidate boundary came from, with refusal as the default for any question not
explicitly listed as poolable. `stratify_by_provenance` is the alternative to
refusing: answer per stratum, never averaged into one figure.

This work is worth having even though the Elliptic2 expansion is cancelled. The
distinction it encodes — a candidate we hypothesised versus a candidate we were
handed — is not specific to Elliptic2, and the collision it closes was real
under the old key regardless of which dataset would have triggered it.

The existing corpus was restamped rather than recompiled
(`--adopt --provenance constructed`), which the drift check now backs
behaviourally. Its hash moved `898f4ab743f8ad7b` → `ac6a01d621b21c71`, which is
the field doing its job.

494 passed, 1 xfailed. All four CI gates pass.

---

## 6. The open list

Nothing here is estimated. Each item is a measurement that has not been made.

* **A conservation analogue for ordinal edge features — must measure.** Whether
  a bin-rank in/out statistic discriminates at all on Elliptic2 is unknown. It
  must not be called `conservation` if it is ever built.
* **Which `feat#` column, if any, is monotone in transaction volume — must
  measure**, and probably cannot be measured: it needs a ground-truth volume to
  correlate against, which is precisely what the binning removed.
* **Structural-only p@k on Elliptic2 — must measure**, if anyone wants the
  0.46-weight subset's standalone value. Any such number must be quoted beside
  the ~2% suspicious-subgraph prevalence, or a cross-dataset comparison against
  AMLworld means nothing.
* **The stale pool from the cold replay — unrecoverable.** Not a measurement,
  a lost artefact. See §1.
