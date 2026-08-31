# Relaxing the builder's budget makes ring coverage worse, not better

**Recorded:** 2026-09-01. **Source:** `scripts/eval_seed_cheat_diff.py`,
`data/eval_seed_cheat_diff.json`. **Full context:**
`docs/PHASE2-SEED-CHEAT-FINDINGS.md`.

## The hypothesis this kills

Phase 2A pre-registered three explanations for why the seed cheat rescues rings
the honest seed rule reaches but the builder fails to recover. **H3** was that
the seed is fine and the builder simply stops early — that with the budget
removed, the ring is reachable and only the expansion bounds prevent it.

If H3 held, the fix would have been cheap: raise `EXPAND_HOPS`,
`EXPAND_MAX_NODES`, or lift the `EXPAND_MAX_DEGREE` hub guard.

## What was measured

A sweep over the real expansion path (`WindowedGraph.expand`, the same call the
builder makes), taking the best single honest seed per ring, against the
shipped configuration `hops=2, max_nodes=200, max_degree=50`:

| budget | R containment | R covered | C containment | C covered |
|---|---:|---:|---:|---:|
| shipped | 0.571 | 24% | 1.000 | 50% |
| no hub guard | 0.500 | 16% | 1.000 | 46% |
| more nodes (2000) | 0.571 | 24% | 1.000 | 50% |
| three hops | 0.700 | 6% | 1.000 | 12% |
| all relaxed | 0.714 | **4%** | 1.000 | **8%** |

R = the 49 rings the cheat rescues; C = the 159 seeded and recovered honestly.

**Relaxing the budget raises containment and collapses coverage.** Expansion
finds more of the ring (0.571 → 0.714) and covers fewer rings (24% → 4%). The
extra reach drags in bystanders, and the candidate then fails the Jaccard floor
in `is_hit`. Lifting the hub guard alone makes containment *fall* (0.571 →
0.500), because the node cap fills with hub neighbours instead of ring members.

The effect is symmetric: the comparison set degrades the same way (50% → 8%).
So this is a property of expansion against the Jaccard floor, not something
peculiar to rescued rings.

**H3 is refuted.** It is also refuted in the more useful direction: not "the
budget is already big enough" but "every direction the budget can move makes
this worse".

## Why this was worth measuring even though §5c already said so

`docs/HANDOFF.md` §5c ruled out all three expansion knobs by experiment, and
`sentinel/config.py` records the same trade for pruning ("expansion recovers
the ring and then buries it"). This does not overturn either — it agrees with
both.

What it adds is that the effect holds **on the specific rings the seed cheat
rescues**, which is the population where a budget increase would have had to
work for H3 to be the explanation. A general finding that budget increases
hurt on average leaves open that they help on the hard cases. They do not.

## Caveat that limits the absolute numbers

The sweep calls `graph.expand` directly, with **no pruning and no
suppression**. Both materially change `is_hit` — `sentinel/config.py` records
that `leaf2` pruning raises rings BUILT from 115 to 159 and mean Jaccard from
0.369 to 0.485. The "covered" column therefore **understates** what the real
builder achieves and is not comparable to `built_honest`. Only the R-vs-C
contrast is interpretable, since both sides omit the same stages.

## What would reverse this

- A budget setting not in the sweep that raises coverage on R above the shipped
  24%. The sweep covers hops ∈ {2,3}, max_nodes ∈ {200,2000}, and the hub guard
  on/off; a different shape — for example an adaptive node cap keyed to the
  seed's local density — is not ruled out and has not been tried.
- Re-running the sweep **with pruning applied** to each expansion. Prune is
  what makes many candidates clear the Jaccard floor, so it is possible that
  relaxed budgets plus pruning behave differently from relaxed budgets alone.
  This is the single most likely way this entry is wrong, and it is cheap to
  run.
- A change to the Jaccard floor itself. The collapse is driven by `is_hit`'s
  0.3 minimum; a different hit definition would produce different verdicts
  throughout. That floor exists because containment alone let a node-count
  baseline tie the scorer (`docs/PHASE0-FINDINGS.md`), so changing it is not
  free and would invalidate every recall number in the repository.
