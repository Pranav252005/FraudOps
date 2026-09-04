# Pre-registration — B1, shape-directed fragment linking

**Written 2026-09-04, before `sentinel/detect/link.py` existed.** Item **B1** in
[`docs/EXPERIMENT-QUEUE.md`](../docs/EXPERIMENT-QUEUE.md).

## The measured problem this targets

`docs/PHASE2-SEED-CHEAT-FINDINGS.md` §H2 is the strongest result in the
repository:

> **51% of rescued rings are split across two or more components of their own
> induced subgraph, against 5.7% of recovered rings.** The honest seed sits in
> one fragment; the rest of the ring is not reachable through ring edges at
> all, only through unrelated intermediaries.

Three things are already ruled out and must not be re-tried:

- **Widening seeding** — `HANDOFF.md` §5b, and re-confirmed today by S1's
  ceiling decomposition. Firing on more accounts does not help a ring whose
  seed is already present but stranded.
- **More builder budget** — §H3, and it fails *backwards*: relaxing every knob
  raises containment 0.571 → 0.714 while collapsing coverage 24% → 4%, because
  the extra reach drags in bystanders and the candidate fails the Jaccard floor.
- **Lowering the Jaccard floor** — bug #8's rule, and standing.

What is left is the direction §H2 names and explicitly declines to recommend
without its own pre-registration: **candidate assembly across disconnected
fragments of the same ring.** `suppress()` removes near-duplicates; nothing
joins two candidates that are different fragments of one structure.

## The mechanism, and where it comes from

From BlazingAML ([arXiv:2604.12241](https://arxiv.org/abs/2604.12241)): build
patterns by **set intersection and difference** rather than by expanding a
neighbourhood and searching inside it. A scatter-gather is found by
intersecting the out-neighbours of A with the in-neighbours of B — the shape is
*constructed*, not hoped for.

**The mechanism only. Not the code, and no comparison to their results.** No
parity claim against a surveyed project enters this repo without a head-to-head
on this machine (queue item X1), and none is made here.

Lifted from nodes to candidates: two candidates `C1` and `C2` are two ends of
one structure when the **bridge**

    X = out_neighbours(C1) ∩ in_neighbours(C2)

is non-empty, small, and temporally ordered — every edge `C1 → X` precedes some
edge `X → C2`. That is a *witness*, not a proximity score. Two candidates that
merely sit near each other in the graph do not qualify; two candidates joined
by a narrow, time-ordered set of intermediaries do.

§H2 says the fragments are reachable "only through unrelated intermediaries",
which is exactly what `X` is.

### The merged candidate excludes the bridge, and that is deliberate

`merged = C1 ∪ C2`, **not** `C1 ∪ C2 ∪ X`.

The intermediaries are the *evidence* that the fragments belong together; they
are not claimed to be ring members. §H2 calls them unrelated. Excluding them
also happens to be the Jaccard-friendly choice, and that alignment is stated
rather than left as a coincidence a reader might suspect was reverse-engineered:
including a 3-node bridge in an 11-node merge would cost roughly a fifth of the
union for nodes the ground truth does not contain.

The consequence is that a merged candidate is **disconnected** in the induced
subgraph. That is correct — the ring itself is disconnected in this window,
which is the entire finding — but it means the case file must show two
components and say why they are one case. Flagged as a presentation
consequence, not solved here.

### Merged candidates are emitted *in addition to*, never instead of

Linking may only add. If a merge is spurious, the originals are still there and
the scorer can prefer them. This makes attribution clean at the cost of pool
growth, and pool growth is itself measured (candidates per cycle is reported
per arm).

### Bounds, fixed in advance

| bound | value | why |
|---|---:|---|
| candidates considered per cycle | top **200** by score | pairwise witness search is quadratic; 200 is the depth a queue could plausibly be worked to |
| bridge size `\|X\|` | ≤ **3** | a wide bridge is a hub, not a link |
| merged size | ≤ **40** nodes | above this it is a cluster, not a case |
| both fragments | ≥ `MIN_NODES` | a 2-node fragment has no structure to attribute |

## Arms

Two, one replay, paired per cycle:

| arm | |
|---|---|
| `shipped` | no linking |
| `link` | + shape-directed merges under the bounds above |

And one **null control**, because the whole risk here is that any pool growth
raises built-recall regardless of the criterion:

| arm | |
|---|---|
| `link_random` | + the same *number* of merges per cycle, formed between randomly chosen candidate pairs meeting the size bounds but **with no bridge witness required** |

If `link` does not beat `link_random`, the witness earned nothing and the gain
is pool growth.

## Pre-registered expectations

| quantity | prediction |
|---|---|
| built-recall, `link` − `shipped` | **+2 to +8 rings** of 259 |
| the typologies that gain | **BIPARTITE and STACK** (16% and 30% built today, both "build-destroyed") |
| p@10, `link` − `shipped`, paired CI | **includes zero** |
| p@20, paired CI | includes zero |
| `link` − `link_random` on built-recall | **positive**; this is the attribution question |
| score − size under `link` | still **CI-clear** at k=10 |
| candidates per cycle | up **less than 10%** |

**Containment and Jaccard are reported together, per the standing requirement.**
Linking grows candidates and candidate size is a measured confound; a table
showing containment alone would be the same mistake bug #8 was.

**I expect built-recall to rise and p@k not to move.** A merged candidate has to
outrank ~15,000 others to enter the top 10, and merging does not make a
candidate score better — it makes it *bigger*, which the scorer does not
directly reward.

## Kill criteria

1. **`link` − `link_random` on built-recall is ≤ 0.** The witness bought
   nothing; the gain, if any, is pool growth. Report as a refutation of the
   mechanism, not as a positive result with a caveat.
2. **p@10 falls with a CI excluding zero.** Linking is buying built-recall with
   ranking quality. **Report this as the headline, not a footnote** — a
   built-recall gain that costs the queue its precision is a loss for the
   product.
3. **score − size stops being CI-clear at k=10 under `link`.** Not shippable
   regardless of recall. Bug #8's rule applied to a generation change.
4. **Mean Jaccard of merged candidates against the rings they cover is lower
   than the best unmerged candidate's for those same rings.** Then linking
   dilutes rather than assembles, and it is doing the thing §H3 refuted by a
   different route.
5. **Witness pairs per cycle exceed 20,000**, making the run infeasible. Report
   as a cost finding and re-scope the bounds before re-running — do not
   silently loosen them mid-experiment.

## What would reverse the conclusion

- A different bridge definition. Undirected bridges, or bridges of size > 3,
  are not tested here and nothing is claimed about them.
- The interaction with `suppress()`. Merged candidates enter the same
  score-ordered NMS, so a merge that scores well can suppress its own parents.
  **This is a known confound and it is not controlled for**, because
  score-ordered suppression confounds every generation change in this
  repository (review §2b, queued as B3). B3 should be run before any *scorer*
  conclusion is drawn from this experiment; a *generation* conclusion —
  built-recall — is less exposed to it, because built is a boolean OR over the
  whole emitted pool rather than a property of the top-k.
