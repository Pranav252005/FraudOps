"""Compile the candidate corpus once, so scorer experiments can query it.

`--adopt` stamps the existing unkeyed `data/ranker_pool.npz` with the key for
the CURRENT config. That is a promise the caller makes and the tool cannot
check: the file must actually have been produced under these constants. It is
offered because recompiling costs a ~55-minute replay, and refused silently
would be worse than refused loudly.

A full compile is `scripts/eval_ranker.py` without `--use-cache`, which writes
the pool; adopt then keys it. Wiring the replay directly into this script is
deliberately not done here -- it would duplicate `collect_pool`, and the point
of the corpus is that the replay path stays single-sourced.

Run:  python scripts/compile_corpus.py --adopt
      python scripts/compile_corpus.py --show
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sentinel.corpus import CorpusKey, CorpusMismatch, load, save

ROOT = Path(__file__).resolve().parent.parent
POOL = ROOT / "data" / "ranker_pool.npz"
CORPUS = ROOT / "data" / "corpus_amlworld_hi_small.npz"
DATASET = "amlworld-hi-small"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--adopt", action="store_true",
                    help="stamp the existing unkeyed pool with the current key")
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

    if not args.adopt:
        ap.error("nothing to do: pass --adopt or --show")

    if not POOL.exists():
        print(f"no pool at {POOL}. Run scripts/eval_ranker.py first (without "
              f"--use-cache) to compile one.")
        return 1
    blob = np.load(POOL, allow_pickle=True)
    names = [str(n) for n in blob["names"]]
    key = CorpusKey.for_current_config(DATASET, names)
    arrays = {k: blob[k] for k in blob.files}
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
