# Phase 0 inventory — index, placeholder resolution, and stop conditions

**Produced:** 2026-08-31. Phase 0 is reconnaissance. **Nothing outside
`docs/inventory/` was changed and no measurement was run.**

| document | task |
|---|---|
| [`run2_pools.md`](run2_pools.md) | 0.1 — the honest and cheated pools |
| [`collect_pool.md`](collect_pool.md) | 0.2 — `collect_pool`'s real return type |
| [`metric_literals.csv`](metric_literals.csv) | 0.3 — metric-shaped literals in prose |
| [`cycles.md`](cycles.md) | 0.4 — the evaluation-cycle machinery |
| [`query_groups.md`](query_groups.md) | 0.5 — why 16 of 34 groups are usable |

---

## Placeholder resolution

The plan's exit criterion is that every `ANGLE_BRACKET` name resolves to
something real. **Two do not, and one resolves to something that contradicts
the standing rule built on it.**

| placeholder | resolves to | status |
|---|---|---|
| `<BOOTSTRAP_FN>` | `sentinel/eval/bootstrap.py::bootstrap_ci`, `::paired_bootstrap_delta`; and `scripts/eval_ring_unit.py::_clustered` / `::interval` | **resolves, but see rule 5 below** |
| `<MEASURED_ENTRYPOINTS>` | `scripts/eval_oracle.py`, `eval_ranker.py`, `eval_phase4.py`, `eval_phase2.py`, `eval_ring_unit.py`, `eval_funnel.py`, `eval_blend_v2.py`, `eval_cost.py`, `eval_elliptic2.py`, `eval_median_gap.py`, `eval_vs_published.py`, `eval_prune_impact.py`, `ci_gates.py` | resolves |
| `<METRIC_PRINTER>` | **nothing.** There is no metric printer. Every script formats its own metrics with inline f-strings (`scripts/eval_oracle.py:475-499`, `scripts/eval_ring_unit.py:155-190`, …) | **UNRESOLVED** |
| `<NEGATIVE_RESULTS_DIR>` | **nothing.** There is no negative-results directory. Negatives are recorded as prose sections inside `docs/HANDOFF.md` (§5e, §5g), `docs/CENTREPIECE-INVALIDATED.md`, `docs/SCORE-VS-SIZE-FINDINGS.md`, and README, plus three retained `*.bak` artefacts in `data/` | **UNRESOLVED** |

Per the plan's hard stop — *"A placeholder in this plan cannot be resolved to a
real symbol"* — Phases 1A tests 1, 2, 3, 6 and 7 cannot be written as specified
until the user decides what these two should be.

---

## Standing rule 5 conflicts with the codebase

> **Rule 5.** Use ring-clustered bootstrap, never cycle-clustered.

The repository does the opposite, deliberately and with its reasoning written
down. Two different things are being conflated:

1. **`sentinel/eval/bootstrap.py` resamples cycles**, and its module docstring
   argues for it: *"The resampling unit is the cycle (one generation run), not
   the individual candidate."* For **p@k the cycle is the correct cluster** —
   p@k is defined per cycle, and a cycle's rows have no ring nesting to cluster
   on. Ring-clustering p@k is not a stricter version of this; it is not
   defined.
2. **`scripts/eval_ring_unit.py` computes both** and reports **the wider**:
   *"cycle-clustering returns a 0.0396-wide interval where ring-clustering
   returns 0.0890 — more than twice as wide. Reporting the former would be a
   confidently narrower wrong answer. Both are computed here and the WIDER is
   reported."* That is where ring-clustering belongs — the ring-unit metric,
   whose 145 trials come from only 68 distinct rings.

**Recommendation:** restate rule 5 as *"any metric whose trials are nested
within rings must be ring-clustered, and the reported interval is the wider of
the cycle- and ring-clustered intervals"*, which is what the code already does
and what Phase 1A Test 4 can then actually assert. Adopting rule 5 as literally
written would change the resampling unit of every p@k interval in the
repository, and therefore every published interval.

**Not changed. Escalated.**

---

## Notes on `metric_literals.csv`

**1,699 rows**, across README, `docs/*.md`, and prose in `sentinel/`,
`scripts/`, `tests/`. First-pass classification:

| class | count |
|---:|---:|
| CURRENT | 1,204 |
| HISTORICAL | 413 |
| DERIVED | 82 |

Top files: `docs/HANDOFF.md` (488), `README.md` (313),
`docs/SCORE-VS-SIZE-FINDINGS.md` (194), `docs/ARCHITECTURE_UPLIFT.md` (184),
`docs/CENTREPIECE-INVALIDATED.md` (110).

**The classification is a regex proposal, not a decision.** It keys on
past-tense / correction markers for HISTORICAL and on relational language
("agree", "ratio", "against the", "delta") for DERIVED, defaulting to CURRENT
otherwise. It is expected to be wrong on a minority of rows, which is why the
CSV carries the sentence. Generator:
`scratchpad/inv_literals.py` (not committed).

**This is 1,699 literals, not the 14 the plan's Phase 4 assumes.** The plan's
diagnosis — *"a number lives in 14 places, so it can be wrong in 14 places"* —
is right in kind and off by two orders of magnitude in degree. `0.2778` alone
appears 40 times.

### Three findings the inventory surfaced that need a decision, not a substitution

**(a) `scripts/eval_oracle.py:165` states a false number, in code, and writes it
into the JSON.** The `LABEL_TAX` constant ends
`"(scripts/eval_ranker.py reaches 0.2778 on the same features and the same
split)"`. `data/eval_ranker.json` reports `pointwise@10 = 0.2500`. That string
is stored in `data/eval_oracle.json` under `label_dependency` and printed on
every run. Violates rule 1.

**(b) README lines 186–197 — the correction block's own premise is false.** It
says *"`data/eval_oracle.json` itself is deliberately not re-run"*. It **was**
re-run (2026-08-31 11:47, commit `0b4debd`). The block's numbers — *"0.2778
against the corrected blend's 0.1889, a paired delta of +0.0889 [+0.0333,
+0.1500]"* — came from `--use-cache` on the stale pool. Live values from
`data/eval_oracle.json` / `data/eval_ranker.json`:

| | README says | live |
|---|---|---|
| supervised p@10 | 0.2778 | **0.2500** |
| blend p@10 | 0.1889 | 0.1889 ✓ |
| paired delta | +0.0889 [+0.0333, +0.1500] | **+0.0611 [+0.0111, +0.1167]** |
| "lead has fallen by roughly 60%" | — | **~73%** on live numbers |

A correction block containing stale numbers is worse than an uncorrected one,
because it reads as freshly verified.

**(c) README line 409 — the two-file agreement claim.** The claim is *"The two
agree exactly, to every digit."* **The claim is still TRUE; only its digits are
stale.** Both files now report `p@10 = 0.25`, CI `[0.12778, 0.37222]`, and
paired-delta-over-blend `+0.06111 [+0.01111, +0.11667]` — identical to every
digit. So Phase 4.3's prescription applies as written (replace the prose
assertion with `tests/test_two_file_agreement.py`), and the pre-interpreted
outcome *"the claim was already false"* does **not** fire.

Note that `docs/HANDOFF-NEXT.md` describes commit `58c1530` as having
*"retract[ed] the agreement claim"*. The claim is still present in README at
line 409. Either the retraction did not land in README or it landed elsewhere;
recorded, not resolved.
