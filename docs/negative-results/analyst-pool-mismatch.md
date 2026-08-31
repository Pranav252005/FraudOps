# The "cheap and unrun" label-tax experiment is ill-posed, not unrun

**Recorded:** 2026-09-01. **Source:** `sentinel/learn/analyst.py`
(`SimulatedAnalyst.label_rate_caveat`), `docs/inventory/collect_pool.md`.

## The claim being retracted

Four places in this repository assert some version of the same thing:

- `docs/HANDOFF-NEXT.md` §3 — *"`collect_pool` already returns everything it
  needs."*
- `scripts/eval_oracle.py` line 41 and the `LABEL_TAX` constant — *"The clean
  experiment … HAS NOT BEEN RUN; collect_pool already returns what it needs."*
- `collect_pool.__doc__` — *"THIS IS ALSO WHAT THE UNRUN LABEL-TAX EXPERIMENT
  NEEDS … needs exactly these two values and nothing else."*

The named experiment is: *same model, same pool, same split, fitted once on
true ring labels and once on simulated analyst verdicts.*

**Both halves of the claim are wrong**, and they fail in different ways.

## The plumbing claim was false

Verified against the source in `docs/inventory/collect_pool.md`, `collect_pool`
returned `{cand, ring, t}` and nothing else. `SimulatedAnalyst.dispose` needs
the ring's **member set** and the **overlap share** to choose between
`CONFIRMED_RING` and `CONFIRMED_PARTIAL`; both were computed inside `is_hit`
and discarded.

That part is now fixed — `label_candidate_detailed` carries them — so this half
was a real gap and it is closed.

## The experiment itself does not survive the fix

With the plumbing in place, the arithmetic can be done before the run.
`SimulatedAnalyst.label_rate_caveat(169814, 165)` on the shipped as-is pool:

| | |
|---|---:|
| training candidates | 169,814 |
| true positives | 165 |
| expected false positives at `FALSE_CONFIRM = 0.005` | **848.2** |
| expected surviving true positives at `MISS_RATE = 0.10` | 148.5 |
| **noise share of the positive labels** | **0.851** |
| usable | **no** |

**85% of the positive labels would be manufactured.** A model trained on that
is not measuring a label tax; it is measuring the mismatch between a **per-case**
error rate and a **per-candidate** pool.

The rates are not wrong — they are calibrated for a queue of tens of cases per
cycle, which is what `scripts/eval_phase4.py` actually uses (680 training
cases). Applying them to every one of 169,814 candidates is the category error.

**An analyst labels a queue, not a pool.** "Same pool" and "simulated analyst
verdicts" cannot both be satisfied, so the experiment as specified has no
well-defined referent.

## This was foreseeable from the module's own docstring

`sentinel/learn/analyst.py` has recorded the same pathology at the case level
since it was written:

> at 3%, applied across a queue where only ~3% of cases contain a real ring,
> false confirmations *equalled* genuine ones and the label corpus was half
> noise — the re-ranker learned nothing (every permutation importance came back
> ~0.000).

The candidate-level version is the same failure two orders of magnitude worse.
It went unnoticed because the claim "collect_pool already returns what it needs"
was repeated across four files without anyone doing the multiplication.
`label_rate_caveat` now does it in one call, so the next person is stopped by
arithmetic rather than by review.

## What was done instead

Phase 3 ran a **synthetic dose-response** design that does not need the analyst
at all: corrupt a pre-registered fraction `p` of positives, measure the slope,
and control for prevalence. That has a well-defined estimand and produced a
coefficient — see `docs/PHASE3-LABEL-TAX-FINDINGS.md`.

## What would reverse this

- **The queue-realistic design**, which is the faithful successor and is
  specified but not run: label only the top-k of each training cycle with the
  simulated analyst, presume the rest negative. That is what a deployment has,
  it has a well-defined estimand, and the arithmetic above does not condemn it —
  a queue of ~50 per cycle over 16 training cycles is ~800 labelled cases, the
  same order as `eval_phase4`'s 680. If that runs and produces a sensible noise
  share, the *spirit* of the original claim is vindicated even though its
  letter is not.
- A demonstration that `FALSE_CONFIRM` should be interpreted per-*ring-bearing*
  candidate rather than per candidate, which would cut the false-positive count
  by orders of magnitude. The constant's own comment ties it to cases, so this
  would be a reinterpretation of the model rather than a correction to this
  entry.
