# Phase B — one harness, two domains, and a guard that was not there

**Gate: passed.** `tests/test_cross_domain.py` runs both domains through the
same primitives and asserts they cannot be pooled. The full suite is green.

## The bug this phase opened with

The plan for this phase assumed `candidate_provenance` was the cross-domain
guard — the field added so that Elliptic2's shipped subgraphs could not collide
with seed-and-expand candidates. It is not, and the failure is silent.

`require_poolable` compared exactly one thing: the set of provenances. Both
domains construct their candidates by seed-and-expand, so both are
`constructed`, so the check finds one shared value, returns it, and pools two
domains that share no feature space, no unit of observation and no adversary.
The separator was always `dataset`, and nothing looked at it.

`require_same_dataset` now refuses first, **before the question is looked up**,
because unlike provenance there is no question that survives it. A scorer pooled
across provenance is still one function on one feature space; a scorer pooled
across datasets is a function on `passthrough_ratio` and a function on attribute
rotation averaged into a number describing neither. The sanctioned path is
`stratify_by_dataset`: answer once per domain and put the answers side by side,
which is what a cross-domain claim is made of anyway.

`tests/test_corpus.py` carries the negative control — a test asserting that the
two keys agree on provenance, so the fix cannot later be mistaken for a fix to
something else.

One test was rewritten rather than deleted.
`test_pooling_across_provenance_is_allowed_for_a_scorer_question` used to spell
its two sides as different *datasets*, which read as a licence to pool across
domains. It never was one: the case that field exists for is Elliptic2's shipped
components against a seed-and-expand pass over Elliptic2's own background edges
— same dataset, different provenance. The test now says that, which is both a
truer statement of the original intent and compatible with the new guard.

## What transferred without modification

`WindowedGraph`, `CandidateGenerator`, `FunnelTracker`, `is_hit`, the funnel
stages, the bootstrap, and `StaticBatch`. `sentinel/eval/identity.py` imports
all of them and re-implements none; a test asserts it defines neither `is_hit`
nor a second `FunnelTracker`, because the moment it does, the cross-domain
finding becomes a finding about two pipelines.

`run_identity_funnel` differs from `run_static_funnel` in one argument.

## The three decisions that did not transfer

**No window.** The graph is built in one static pass, reusing the idiom
`sentinel/eval/dataset.py` opened for Elliptic2. `WINDOW_MINUTES` is an AMLworld
constant. Keeping it would have made fragmentation partly the window's own
artefact in a domain whose adversary *deliberately spaces registrations* —
re-deriving the AMLworld result instead of contrasting with it, which is the
entire point of the second domain.

**The seed rule is exogenous, and had to be invented.** AMLworld seeds on
pass-through — money in and out — and onboarding data has no flow. Worse, the
co-occurrence graph is undirected, so *every* application is a pass-through
account: inheriting the rule would have seeded the whole population and made
recall meaningless. A test asserts the exogenous rule fires on strictly fewer
applications than the inherited one would. The rates were pre-registered before
the generator existed, because seed generosity sets recall before a single
feature exists.

**The Jaccard floor is inherited unchanged at 0.3.** Whether 0.3 is right for
identity clusters is an empirical question. Answering it after measuring would
invalidate every cross-domain comparison, so it stays at the value AMLworld
already reports under, and the choice is asserted in a test rather than left to
a constant nobody re-reads.

## Where ground truth is allowed to enter

In one place: the seed rule. An exogenous signal is *correlated with* fraud by
definition — that is what makes it a signal — so modelling it requires knowing
who is fraudulent. It lives in the evaluation harness, and the generator keeps
`Application` label-free so that no feature can reach the same information by a
different route. The asymmetry is tested from both sides.

## The corpus key is deliberately over-strict here, and this is the notice

An identity corpus keyed by `for_current_config` folds in AMLworld's generation
constants — `WINDOW_MINUTES`, `PRUNE_STRATEGY`, `EVAL_END` — none of which the
identity path reads. Changing one of them will therefore invalidate an identity
corpus that it did not actually affect.

That is the safe direction of wrong: it fails loudly at load and costs a
recompile, where the alternative — making the digest domain-aware — would
invalidate every *existing* AMLworld corpus and discard a 55-minute compile to
fix a problem nobody has yet. Revisit it when identity corpora become expensive
enough to be worth caching, which is Phase C's problem, not this one.

## What is deliberately not reported here

The identity funnel runs and produces stage recalls. **They are not in this
document**, because Phase D pre-registers a prediction about exactly those
numbers and it has not been written yet. Quoting them now would make the
prediction retrospective, which is the one thing `prereg/` exists to prevent.

They are cheap to reproduce — `run_identity_funnel` on a generated world — and
that is where they should be read from until D is registered.
