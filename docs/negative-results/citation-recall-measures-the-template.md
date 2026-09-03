# Citation recall measures the template's enumeration cap, not its sourcing

**Recorded:** 2026-09-03. **Pre-registered:** `prereg/citation_recall.md`,
committed at `4cdbb22` before `scripts/eval_citation_recall.py` existed.
**Measured over:** all 1,360 cases in the store, 1,253.8 s.
**Artefact:** `data/eval_citation_recall.json`.

## What was predicted, and what came back

| quantity | pre-registered | measured (1,360 cases) | verdict |
|---|---|---|---|
| citation precision | exactly 1.0, tautological | **1.0000** [1.0000, 1.0000] | as predicted, and worthless as evidence |
| **evidence_recall** (headline) | 0.40 – 0.80 | **0.7494** [0.7411, 0.7575] | inside the band |
| txn_recall | 0.15 – 0.60 | **0.6886** [0.6790, 0.6983] | **above the band — prediction wrong** |
| member_recall | 0.60 – 1.00 | **1.0000** [1.0000, 1.0000] | inside, and degenerate |
| verification failures | 0 | **0** of 1,360 | as predicted |

Interval method: `case_clustered_bootstrap`, 2,000 resamples. One case is one
trial and appears once, so the case is the resampling unit; rule 5's
"report the wider of two clusterings" has nothing to range over, because these
trials are not nested in rings or cycles.

## Why the headline landing inside its band is not a pass

**The headline is inside the pre-registered band and the measure is still
mostly an artefact.** That is the finding, and it is not what the
pre-registration was built to catch.

The decisive evidence is the size stratification, which was **not** in the
pre-registration and was added when the first numbers looked too good:

| case size (txns) | cases | median txns | txn_recall | member_recall |
|---|---:|---:|---:|---:|
| 0 – 20 | 155 | 15 | **1.0000** | 1.0000 |
| 21 – 50 | 622 | 35 | 0.7394 | 1.0000 |
| 51 – 150 | 508 | 74 | 0.5626 | 1.0000 |
| 151+ | 75 | 183 | **0.4782** | 1.0000 |

`txn_recall` falls by **-0.5218** from the smallest band to the largest. A
genuine sourcing property would be roughly flat in case size. This is the
signature of a fixed enumeration prefix: `_what` cites the first 5 transactions
in its header and then one sentence each for the first 20, and `_who` cites up
to 3 evidence transactions per member, so a small case is cited exhaustively and
a large one cannot be. **The number tracks how big the case is, not how well
the narrative sources it.**

`member_recall` is worse: **1.0000 with a zero-width interval across all 1,360
cases.** `_where` emits every member account id unconditionally, so the
component cannot vary and therefore cannot measure. It is tautological in
exactly the way precision is, and it inflates the headline, which is a weighted
mix of it and `txn_recall`.

## The kill criterion did not fire, and it should have

The pre-registered rule was **"`evidence_recall` >= 0.95 means the measure is
degenerate."** The measured headline is 0.7494. **The rule did not fire, and the
thing it was written to catch is present anyway.**

The rule was specified as a **threshold on a headline** when the pathology it
describes — "a template that emits one sentence per fact makes recall trivially
1.0" — is a statement about **shape**. A composite that averages a
by-construction-1.0 component with a size-determined one lands in the middle and
sails under the bar. The diagnostic that actually caught it is the slope across
size bands, and a zero-width-interval check on each component.

This is the same class as the five checks already catalogued in
[`../WHAT-BROKE.md`](../WHAT-BROKE.md) as incapable of failing, with one
difference worth keeping: this one **could** have fired, it simply was not
aimed at the right statistic. A threshold on the wrong quantity is not a weaker
version of a kill rule — it is a kill rule that reports "did not fire" while the
condition holds.

## A second defect, found on the way

The first run of this measurement used `--limit 30` against a 1,360-case store
and wrote `data/eval_citation_recall.json` with **no field recording that it was
partial**: same schema, same keys, plausible numbers. It reported
`evidence_recall` **0.8797** — outside the pre-registered band, in the
flattering direction — because the first 30 cases in store insertion order are
the earliest and smallest.

The population run reads **0.7494**. The smoke test was wrong by **+0.13** on
the headline and would have been quoted as a population figure.

Now: the artefact carries `n_cases_in_store`, `limit` and `is_full_population`;
the console banners a partial run; and `scripts/collect_metrics.py` **refuses**
to publish a partial artefact rather than passing it through. The symmetric
guard was added to `data/eval_narrative_path.json` in the same commit, because
guarding one artefact and not the other leaves the hole where nobody is looking.

## What this does NOT say

- It does **not** say the narrative is badly sourced. It says this measurement
  cannot tell you either way, because it is dominated by case size.
- It does **not** say the citation contract is decorative. The contract holds:
  0 verification failures in 1,360 cases, and precision is 1.0 because the
  verifier refuses anything else.
- It does **not** measure any model. The drafted path attempted **0 drafts**
  (`data/eval_narrative_path.json`); every figure here is the deterministic
  template.

## What would reverse this

- **A recall figure measured on the LLM path.** The template's recall is a
  property of the template. The citation contract exists for *drafted* text, and
  drafted text is the only place recall could measure sourcing judgment. This
  needs an `OPENROUTER_API_KEY`, which is not configured here.
- **A size-normalised definition** — recall against the transactions a narrative
  of bounded length *could* cite, rather than against every transaction in the
  case file. That would remove the size confound and make the number a statement
  about selection quality. It would also need its own pre-registration, because
  choosing the normaliser after seeing this table is choosing the answer.
- **Removing the enumeration caps** in `sentinel/narrative/str_narrative.py` so
  the template cites every transaction. That would drive `txn_recall` to 1.0 and
  prove the point rather than fix it: a narrative that lists 183 transactions
  one per sentence is not better sourced, it is unreadable, and the metric
  rewarding it is the defect.
- **A flat slope across size bands** on any future revision of this measure.
  That, not a high headline, is what would make it informative.
