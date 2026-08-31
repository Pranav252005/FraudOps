"""Compile the candidate corpus once, so scorer experiments can query it.

`--adopt` stamps the existing unkeyed `data/ranker_pool.npz` with the key for
the CURRENT config. That is a promise the caller makes and the tool cannot
check: the file must actually have been produced under these constants. It is
offered because recompiling costs a ~55-minute replay, and refused silently
would be worse than refused loudly. What the tool CAN check it now does --
`--adopt` runs the behavioural drift check before writing, so the half of the
promise that concerns how features were computed is verified rather than taken.

`--provenance` is required and has no default. It records whether the
candidates were CONSTRUCTED by seed-and-expand or GIVEN by the dataset, and it
is folded into the digest -- so the two cannot collide on one hash while
answering different questions. There is no safe default: a caller who has not
thought about it is exactly the caller who would pick wrong.

A full compile is `scripts/eval_ranker.py` without `--use-cache`, which writes
the pool; adopt then keys it. Wiring the replay directly into this script is
deliberately not done here -- it would duplicate `collect_pool`, and the point
of the corpus is that the replay path stays single-sourced.

`--rescore` regenerates the stored blend from the stored features after a SCORE
change. It is not a shortcut around a recompile: `score()` reads only Features
attributes and every one of them is a stored column, so the blend really is
recoverable exactly. A FEATURE change is a different thing and needs the replay.

Run:  python scripts/compile_corpus.py --adopt --provenance constructed
      python scripts/compile_corpus.py --rescore
      python scripts/compile_corpus.py --show
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.corpus import (CANDIDATE_PROVENANCES, CorpusKey, CorpusMismatch,
                             load, require_consistent, rescore, save)

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "data" / "ranker_pool.npz"
CORPUS = ROOT / "data" / "corpus_amlworld_hi_small.npz"
DATASET = "amlworld-hi-small"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adopt", action="store_true",
                    help="stamp the existing unkeyed pool with the current key")
    ap.add_argument("--provenance", choices=CANDIDATE_PROVENANCES,
                    help="how the candidates came to exist: seed-and-expand "
                         "CONSTRUCTED them, or the dataset GAVE them. Required "
                         "with --adopt; no default, because the wrong one is a "
                         "corpus that answers a different question under the "
                         "same hash")
    ap.add_argument("--rescore", action="store_true",
                    help="regenerate the stored blend from the stored features "
                         "after a SCORE change (a weight, a retired term). No "
                         "replay: score() is a pure function of columns the "
                         "corpus already holds. Do NOT use after a FEATURE "
                         "change -- that needs a real recompile")
    ap.add_argument("--show", action="store_true",
                    help="print the corpus key and shape, then exit")
    args = ap.parse_args()

    if args.show:
        if not CORPUS.exists():
            print(f"no corpus at {CORPUS}. Run with --adopt.")
            return 1
        arrays, key = load(CORPUS)
        print(f"corpus {key.describe()}")
        for name in sorted(arrays):
            print(f"  {name:<14} {arrays[name].shape} {arrays[name].dtype}")
        return 0

    if args.rescore:
        if not CORPUS.exists():
            print(f"no corpus at {CORPUS}.")
            return 1
        arrays, key = load(CORPUS)
        names = [str(n) for n in arrays["names"]]
        before = arrays["test_blend"].copy()
        arrays = rescore(arrays, names)
        moved = int((before != arrays["test_blend"]).sum())
        # Rescoring is only meaningful if it makes the corpus consistent. If it
        # does not, the disagreement was never in the score and this command
        # was the wrong tool -- say so instead of writing a file that now
        # passes a check it should still be failing.
        require_consistent(arrays, names)
        save(CORPUS, key, arrays)
        print(f"rescored {CORPUS.name} from its own stored features")
        print(f"  key {key.describe()}  (unchanged: the blend is not keyed)")
        print(f"  {moved:,} of {len(before):,} test rows changed "
              f"({100*moved/len(before):.1f}%)")
        print("  drift check passes: the stored blend is now what this code "
              "would produce")

        # The pool is rescored too, and not as a convenience. It is the file
        # `--adopt` reads and the one `eval_ranker.py --use-cache` takes its
        # `blend` baseline from. Leaving it on the old score would mean the
        # corpus and its own source disagreed -- and the next `--adopt` would
        # produce a corpus that fails the drift check for a reason that has
        # nothing to do with the config it just stamped. That is the staleness
        # class this repository has already been bitten by once.
        if POOL.exists():
            blob = np.load(POOL, allow_pickle=True)
            pool = {k: blob[k] for k in blob.files}
            pnames = [str(n) for n in pool["names"]]
            pbefore = pool["test_blend"].copy()
            pool = rescore(pool, pnames)
            pmoved = int((pbefore != pool["test_blend"]).sum())
            np.savez_compressed(POOL, **pool)
            print(f"\nrescored {POOL.name} as well "
                  f"({pmoved:,} of {len(pbefore):,} test rows changed)")
            print("  it is what --adopt reads and what eval_ranker.py "
                  "--use-cache scores the\n  blend baseline from; a pool "
                  "disagreeing with its own corpus is the bug")
        else:
            print(f"\nno pool at {POOL.name}; nothing else to rescore")
        return 0

    if not args.adopt:
        ap.error("nothing to do: pass --adopt, --rescore or --show")
    if not args.provenance:
        ap.error("--adopt needs --provenance {constructed|given}: the key "
                 "cannot distinguish a seed-and-expand candidate from a "
                 "dataset-supplied subgraph unless you say which this is")

    if not POOL.exists():
        print(f"no pool at {POOL}. Run scripts/eval_ranker.py first (without "
              f"--use-cache) to compile one.")
        return 1
    blob = np.load(POOL, allow_pickle=True)
    names = [str(n) for n in blob["names"]]
    key = CorpusKey.for_current_config(DATASET, names, args.provenance)
    arrays = {k: blob[k] for k in blob.files}
    # The adopt promise has two halves. The key covers generation constants and
    # the feature schema; nothing covered how the features were COMPUTED, and a
    # corpus adopted here once turned out to have been built by different code
    # with a perfectly matching key. So the half that can be checked is checked
    # before the file is written, not after somebody quotes a number from it.
    checked = require_consistent(arrays, names)
    print(f"drift check: {checked['n_checked']} sampled rows recomputed, "
          f"0 disagreements")
    save(CORPUS, key, arrays)
    print(f"adopted {POOL.name} -> {CORPUS.name}")
    print(f"  key {key.describe()}")
    print(f"  {len(names)} features, {arrays['train_X'].shape[0]:,} train rows, "
          f"{arrays['test_X'].shape[0]:,} test rows")
    print("\nThis stamped the CURRENT config onto a file compiled earlier. If a "
          "\ngeneration constant has changed since, that promise is false and "
          "every\nnumber read from this corpus is wrong. Recompile if unsure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
