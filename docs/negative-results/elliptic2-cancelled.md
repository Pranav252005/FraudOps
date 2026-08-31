# The Elliptic2 expansion was cancelled on a schema fact

**Recorded:** 2026-08-31, commit `375310a`. **Source:**
`sentinel/data/elliptic2.py`, `data/eval_elliptic2.json`,
`sentinel/corpus/store.py`.

## What was planned, and why it stopped

A second dataset was the strongest available answer to this project's
sample-size problem — the one thing that would raise `n` without resampling the
same 34 cycles harder (`docs/inventory/cycles.md`).

It was cancelled on a fact about the data, not on effort. Elliptic2 **ships its
subgraphs** in `connected_components.csv`. Sentinel **constructs** its candidate
boundaries by seed-and-expand. A candidate the dataset gave and a candidate
seed-and-expand built are different objects, and before this was noticed they
hashed to the same corpus key — so a corpus built one way and a corpus built the
other would have been served interchangeably while answering different
questions.

`candidate_provenance` was added as a fourth key field to make the two
uncollidable, and `require_poolable` now makes a caller name the question:
pooling constructed and given subgraphs is valid for a **scorer** question and
invalid for a **recall** one.

## What the repository's Elliptic2 numbers actually are

**`data/eval_elliptic2.json` has `is_sample: true`.** It is a **10-node,
8-edge fixture** with one suspicious and one licit component
(`tests/fixtures/elliptic2_sample/`). Its `precision_at_k` of 0.5 at every k is
a property of a two-component toy, not a result.

Recorded explicitly because "we evaluated on Elliptic2" is exactly the sentence
a reader would infer from that file's existence, and it would be false.

Standing rule 4 — report prevalence beside any Elliptic2 p@k — therefore
currently governs a metric that does not exist as a real result. The rule is
kept armed anyway, in `sentinel/report/metric.py`, so that the first real
Elliptic2 number cannot be published without it.

## What would reverse this

- Running the real Elliptic2 background graph through seed-and-expand,
  producing a `constructed`-provenance corpus that can be compared like-for-like
  against the AMLworld one on a **scorer** question. The schema fact does not
  forbid this; it forbids pooling the given subgraphs with the constructed ones.
- Note that a **recall** comparison across the two datasets stays invalid under
  `POOLING_VALIDITY` regardless of how much compute is spent, so that is not a
  reversal condition.
