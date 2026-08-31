# Phase 0.1 — Inventory of the run-2 artifacts

**Produced:** 2026-08-31. **Method:** read of `scripts/eval_oracle.py`,
`scripts/eval_ranker.py`, `data/eval_oracle.json`, `data/ranker_pool.npz`,
`data/eval_oracle_postblendfix.log`. No code changed, no run performed.

## Headline: only ONE of the two pools is persisted

The plan's task 0.1 assumes both pools exist on disk. **They do not.**

| | honest ("as-is") seeding | cheated ("perfect") seeding |
|---|---|---|
| Produced by | `scripts/eval_oracle.collect_pool(..., seed_perfect=False)` | `scripts/eval_oracle.collect_pool(..., seed_perfect=True)` |
| Persisted to disk? | **Yes**, `data/ranker_pool.npz` (59.3 MB, written 2026-08-31 11:55) | **No. Nowhere.** |
| Written by | `scripts/eval_ranker.py` (line 180 calls `collect_pool(..., seed_perfect=False)`) | — |
| Retained in `eval_oracle.py`? | in-memory only (`as_is_records`) | in-memory only (`perfect_records`) |
| Rows | 346,554 candidates over 34 generation runs | 365,011 candidates over 34 generation runs |
| Train / test | 169,970 (321 pos) / 176,584 (163 pos) | 177,701 (2,776 pos) / 187,310 (1,330 pos) |
| `split_t` | 7980 | 7980 |
| Held-out cycles | 18 | 18 |

`scripts/eval_oracle.py` writes **only aggregates** to `data/eval_oracle.json`:
per-run reports plus `cycle_rows` (one row per held-out cycle carrying
`{name}_hit_{k}` / `{name}_n_{k}` counts). There is **no per-candidate and no
per-ring record** in that file for either arm. Both pools are discarded when the
process exits.

## Schemas

### Honest pool — `data/ranker_pool.npz`

18 arrays. Ring identity is present and is a first-class column.

| array | shape | dtype | notes |
|---|---|---|---|
| `names` | (54,) | `<U24` | feature names |
| `split_t` | () | int32 | 7980 |
| `train_X` / `test_X` | (169970, 54) / (176584, 54) | float64 | features |
| `train_y` / `test_y` | (169970,) / (176584,) | int32 | 1 iff the candidate is a hit for some active ring |
| `train_t` / `test_t` | (…,) | int64 | generation-cycle tick |
| `train_ring` / `test_ring` | (…,) | int64 | **the join key.** Ground-truth ring id, `-1` for negatives |
| `train_blend` / `test_blend` | (…,) | float64 | shipped v1 hand-set score |
| `train_size`, `train_degree`, `train_rnd` (+ test) | (…,) | float64 | standing baselines |

### Cheated pool — in-memory only

`collect_pool` returns `list[dict]` where each record is
`{"cand": Candidate, "ring": int | None, "t": int}`, plus
`ring_first_t: dict[int, int]`. Same shape for both arms; the only difference is
the `seed_override` passed to `CandidateGenerator.generate`.

## The join key

**`ring` — the integer ground-truth ring id assigned in
`scripts/build_stream.py` and carried on `Stream.ring`.**

It **is stable across the two pools.** Both arms are produced in one process
from the same `Stream` and the same `AccountRegistry`; `active_rings()` and
`label_candidate()` read the identical `stream.ring` array in both. Ring 42 in
the honest pool is ring 42 in the cheated pool. There are 370 ring ids
(`RING-00001`…`RING-00370` in `data/stream/meta.json`), of which 363 begin
inside the evaluable window (`EVAL_END_DAY = 10`).

So the plan's first pre-interpreted outcome — *"if run 2's two pools do not
share a stable ring key → Phase 2 is impossible"* — **does not fire.** The key
is stable. The obstacle is persistence, not keying.

## Same underlying cycles, or separate runs?

**Same underlying stream, same tick schedule, same 34 generation runs.**
`main()` calls `collect_pool` twice against one `Stream` object, with
`TICK_MINUTES=60`, `EVERY=6`, `end=EVAL_END`. Both arms report `34 runs` in
`data/eval_oracle_postblendfix.log` (lines 8 and 86) and both produce
`split_t = 7980` and 18 held-out cycles. The cycle ticks are therefore
identical between arms and a per-cycle join is also valid.

The **candidate sets differ**, and by design: the cheat adds every active ring's
own members to the seed set, which changes what `generate()` emits, which
changes what `suppress()` keeps. 346,554 vs 365,011 candidates.

## What this means for Phase 2

Phase 2A is **feasible but is not "a read of existing data"**, contrary to
`docs/CENTREPIECE-INVALIDATED.md` ("run 2 already generates both pools, so
diffing which rings the cheat rescues is a read of data that exists") and
`docs/HANDOFF-NEXT.md` §2 ("Cheap to settle").

To build the four-field record the plan specifies, three of the four fields are
not derivable from anything on disk:

| field | available today? |
|---|---|
| `recovered_honest` | **Yes** — derivable from `data/ranker_pool.npz`: a ring is recovered iff it appears in `train_ring`/`test_ring` |
| `recovered_cheat` | **No** — the cheated pool is not persisted |
| `seeded_honest` | **No** — `collect_pool` never records the seed set. `gen.seeds(b)` is computed and discarded |
| `seeded_cheat` | **No** — same, and the override set is discarded too |

**Required to unblock Phase 2A:** a new script that replays the window twice
recording, per (cycle, ring): the seed set ∩ ring, the built-candidate set, and
the ring membership. Measured cost from the existing log: **393 s** for the
honest arm and **417 s** for the cheated arm, so **~14 minutes of replay** plus
the cost of the extra per-ring bookkeeping. That is affordable on this laptop —
it is a moderate job, not a large one, and it is **not** free.

Recommendation: have that script *also* write both pools to `.npz` with the
ring column, so this inventory never has to be re-derived.
