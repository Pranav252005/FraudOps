"""The candidate corpus: compile the stream once, query it many times.

A scorer is a function on candidate feature vectors. Once candidates are built
and their features frozen, the stream holds no further information about any
scorer question -- it has been fully consumed. Re-running a 55-minute replay to
answer a ranking question therefore re-derives an artefact that did not change.

The evidence that this is exact rather than approximate: refitting from the
cached pool reproduces the stored held-out p@10 of 0.2778 [0.1500, 0.4167] to
every digit. For scorer questions the corpus IS the replay, not a stand-in.

The partition this rests on, and the line not to cross:

  * scorer / ranking / calibration / re-ranker questions depend only on the
    candidate corpus and are fully cacheable. The -39.8 point ranking loss
    lives here.
  * detection / seeding / pruning / build questions change which candidates
    exist and REQUIRE a replay. The -26.6 point BIPARTITE/STACK loss lives
    here, and no corpus can answer it.

**A known hole in that partition, found 2026-08-31 and not yet closed.** The
line above says a scorer question cannot change which candidates exist. That is
not quite true: `suppress()` is greedy non-maximum suppression ORDERED BY SCORE,
so when several overlapping views of a neighbourhood compete, the score decides
which one survives to be a candidate at all. Changing the blend weights
therefore changes the candidate SET, not only its order -- measurably, and the
tell is that the `size` baseline moved when the weights changed despite ignoring
the score entirely.

What this does and does not invalidate. A corpus remains exactly right for
comparing scorers ON THE CANDIDATE SET IT HOLDS, which is what every scorer
question here asks and what `eval_blend_v2.py` is careful to claim. It is NOT
sufficient for a question about the shipped system's candidates once the
weights have moved, because the shipped generator is now suppressing
differently from the generator that built the corpus.

The key does not catch this. `WEIGHTS` is deliberately not in
`_GENERATION_CONSTANTS` -- putting it there would discard a 55-minute compile
every time somebody tried a weight, which is the exact iteration this package
exists to make cheap -- and `verify_scoring` cannot see it either, because it
checks that the stored blend matches today's code, which rescoring makes true
while leaving the candidate set stale. **Must fix**, and until it is, treat a
corpus compiled before a weight change as answering "which scorer ranks these
candidates better", never "what would the shipped queue do".

Serving a cached corpus for a question about a detector configuration it was
not built from would be a confident wrong answer of exactly the kind this
project keeps a bug catalogue for. That is why the corpus is keyed by
`(dataset, detector_config_hash, feature_version, candidate_provenance)` and
why `load` REFUSES a mismatch rather than warning about it. The key is the
safety mechanism, not decoration.

`candidate_provenance` is the fourth field and the newest. A candidate that
seed-and-expand CONSTRUCTED and a subgraph the dataset GAVE are different
objects; before this field they hashed the same, so an Elliptic2 corpus built
from `connected_components.csv` and one built by seed-and-expand over
`background_edges.csv` would have been served interchangeably while answering
different questions. Pooling the two is valid for a scorer question and invalid
for a recall one -- and since the corpus cannot know which is being asked,
`require_poolable` makes the caller name the question and refuses on the ones
that do not survive pooling.
"""
from sentinel.corpus.store import (CANDIDATE_PROVENANCES, FEATURE_VERSION,
                                   POOLING_VALIDITY, CorpusDrift, CorpusKey,
                                   CorpusMismatch, ProvenanceMismatch,
                                   detector_config_hash, load,
                                   require_consistent, require_poolable,
                                   rescore, save,
                                   stratify_by_provenance, verify_scoring)

__all__ = ["CANDIDATE_PROVENANCES", "FEATURE_VERSION", "POOLING_VALIDITY",
           "CorpusDrift", "CorpusKey", "CorpusMismatch", "ProvenanceMismatch",
           "detector_config_hash", "load", "require_consistent",
           "require_poolable", "rescore", "save",
           "stratify_by_provenance",
           "verify_scoring"]
