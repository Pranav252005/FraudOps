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
    candidate corpus and are fully cacheable. The -43.6 point ranking loss
    lives here.
  * detection / seeding / pruning / build questions change which candidates
    exist and REQUIRE a replay. The -26.3 point BIPARTITE/STACK loss lives
    here, and no corpus can answer it.

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
                                   require_consistent, require_poolable, save,
                                   stratify_by_provenance, verify_scoring)

__all__ = ["CANDIDATE_PROVENANCES", "FEATURE_VERSION", "POOLING_VALIDITY",
           "CorpusDrift", "CorpusKey", "CorpusMismatch", "ProvenanceMismatch",
           "detector_config_hash", "load", "require_consistent",
           "require_poolable", "save", "stratify_by_provenance",
           "verify_scoring"]
