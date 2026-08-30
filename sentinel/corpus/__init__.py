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
`(dataset, detector_config_hash, feature_version)` and why `load` REFUSES a
mismatch rather than warning about it. The key is the safety mechanism, not
decoration.
"""
from sentinel.corpus.store import (FEATURE_VERSION, CorpusKey, CorpusMismatch,
                                   detector_config_hash, load, save)

__all__ = ["FEATURE_VERSION", "CorpusKey", "CorpusMismatch",
           "detector_config_hash", "load", "save"]
