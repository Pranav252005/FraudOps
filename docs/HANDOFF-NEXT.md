# Where this session got to

**Date:** 2026-08-31. Branch `upgrades/reranker-funnel-negatives-positioning`,
**9 commits on top of `0f1d635`, unpushed.** 514 passing + 1 xfailed, 0 skipped.
All four CI gates pass.

## The headline: the centrepiece is dead, by its own pre-registered rule

Full write-up in **`docs/CENTREPIECE-INVALIDATED.md`** — read that first.

The oracle/blend ratio came back **1.32× / 1.42× / 1.31×** against a
pre-registration (§8 item 0.1) that expected ≥ 2× and named ≤ 1.5× as the kill
line. `scripts/eval_oracle.py` selected the "PLAN-INVALIDATING" branch itself.

The cause is not the oracle getting worse — it is unchanged. `a0cbbec` deleted
two inverted blend weights and **the floor rose**: blend p@10 0.0500 → 0.1889.
The 5.33× headroom was largely a measurement of two backwards weights.

The perfect-seeding arm says the same thing from the other side: with seeding
cheated, the ratio is **1.18× / 1.13× / 1.22×** and the k=20 interval includes
zero. The same blend gains **~2.2×** at k=10 from the seed cheat alone
(0.1889 → 0.4111) versus 1.32× from replacing the scorer with a true-label
model. **The scorer was never the binding constraint.**

## The methodological finding, which outlives the numbers

`data/eval_ranker.json` had **mixed provenance**: a post-fix blend column on a
pre-fix candidate set. `compile_corpus.py --rescore` regenerates the stored
blend from stored features and rescores `ranker_pool.npz` too — but it cannot
regenerate candidates, and `suppress()` is greedy non-maximum suppression
**ordered by score**. The score participates in generation, so **rescoring makes
a stale pool internally consistent rather than repairing it.**

**Consequence for all future scorer work: any change to the weights invalidates
the candidate set, not just the ranking. A scorer experiment that reuses a
cached pool is measuring a fixed-candidate-set counterfactual, not the deployed
system.** The tell to check every time: `size` and `degree` read no features, so
if they move, the candidate set moved.

## Still open / not done

1. **GFP parity — BLOCKED, not skipped.** Independently verified: **zero
   `gf_*` symbols in any Windows `.pyd`** across all six binaries in snapml
   1.15.6. The blocker is the OS, not the interpreter, so the suggested
   workarounds (venv on 3.11/3.12, subprocess boundary) cannot work. **No WSL and
   no Docker on this machine.** Unblocking needs WSL/Docker installed (admin +
   reboot — not done unilaterally) or a Linux box, then
   `scripts/gfp_control.py gfp-features`. **No parity claim may enter the repo
   until that head-to-head exists.**
2. **The §5b tension is unresolved.** §5b measures seeding at 89% of active
   rings; run 2 says the seed cheat is worth 2.2×. Both cannot be simple.
   Likely "seeded at all" ≠ "seeded with a member set the builder can grow into
   the ring", which would put the loss at *build*. **Cheap to settle** — run 2
   already generates both pools; diff which rings the cheat rescues.
3. **The label tax is still a hypothesis, not a number.** The clean experiment
   (same model, same pool, same split, fitted once on truth and once on
   simulated verdicts) has still not been run. `collect_pool` already returns
   everything it needs.
4. **README not fully refreshed.** It already carries a correct correction block
   for the 0.0500 → 0.1889 blend change, but it still quotes **0.2778** as the
   supervised headline in several places. The clean number is **0.2500**.
   Not touched this session for budget reasons. `data/eval_oracle.json` is now
   authoritative.

## Superseded artefacts, deliberately retained

- `data/eval_oracle.PREBLENDFIX.json.bak` — the pre-fix oracle file.
- `data/eval_ranker.MIXEDPROVENANCE.json.bak` — the mixed-provenance ranker file.
- `data/ranker_pool.PREFIX.npz.bak` — the stale pool.

Kept because in each case the stale artefact is the evidence for the finding.

## Verification state

- `python -m pytest -q` → **514 passed, 1 xfailed**, 0 skipped.
- `python scripts/ci_gates.py all` → determinism, re-tie, regression, cost all
  **PASS**.
- `tests/test_corpus.py` caught the pool staleness exactly as designed (refit
  0.2778 vs stored 0.2500) and is green again after re-adopting the regenerated
  pool — drift check 2000 sampled rows, **0 disagreements**.
