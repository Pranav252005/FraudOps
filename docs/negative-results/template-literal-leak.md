# The render system had the defect it was built to prevent

**Recorded:** 2026-09-01. **Found by:** a pre-submission read of
`README.template.md` against `results/metrics.json`, not by any test.
**Fixed in:** the same commit that records this.

## What was found

Six unmarked literals in `README.template.md` stating the supervised
re-ranker's p@10, one of them carrying an interval, all of them superseded.
`results/metrics.json` holds the current value for `supervised_p_at_10` — the
same quantity, from the same source file and the same run — and
`docs/SUBMISSION.md` printed it correctly on the same day, from the same
metrics file, through the same renderer.

The stale figure is a three-decimal rounding of a value the same template
narrates as superseded **three paragraphs earlier**, in a blockquote that
enumerates both corrections that made it stale. The exact readings:

<!-- historical: measured at commit 6253ac5, 2026-08-30 -->
The template read `0.278` (once as `0.278 [0.150, 0.417]`), a rounding of `0.2778`.
That figure was itself superseded twice.

<!-- historical: measured at commit a0cbbec, 2026-08-30 -->
`0.2778` became `0.2500` when two anti-signal blend terms were retired. The
supervised model did not change; the blend's floor rose beneath it.

<!-- historical: measured at commit 63066d1, 2026-08-31 -->
`0.2500` became the current value when the dead training query groups were
closed, which cost the training set 156 positives.

Three further literals in the same section quoted a `2.25×` ratio built from
the stale figure and Phase 4's verdict-trained number. The surrounding prose
had already withdrawn that ratio as a claim; the digits stayed.

## Why the existing checks did not catch it

Two mechanisms were in place. Both are blind to this, for different reasons.

**`tests/test_readme_render.py` compares the rendered file to the template.**
A number typed into the template renders faithfully. The test then certifies
the output as correct, because it *is* a correct rendering — of a wrong input.
The check is real and it points the wrong way: it protects the template from
the output, not the output from the template.

**`tests/test_prose_literals.py` counts unmarked literals against a ledger.**
A count cannot see staleness. Literals already inside the count do not raise
the count when the measurement behind them moves. The ratchet was working
exactly as specified, and specified the wrong property.

Both passed continuously across both corrections above.

## Why this is a negative result and not just a bug

`docs/SUBMISSION.md` §6 is titled "The methodology is enforced, not promised"
and opens with *"Most submissions claim rigour in prose. Prose does not fail a
build."* That section names this exact defect — a supervised p@10 appearing 14
times in README and going stale twice unnoticed — as the reason the rendering
system exists.

**The defect survived the fix for it, inside the document making the claim.**
That is the finding. A guard that covers the named instance of a failure but
not the failure's mechanism will be trusted more than it has earned, and it
was: the unmarked-literal count fell from 1,835 and the fall was reported as
progress on rule 1 while a stale headline sat inside the file being counted.

## The fix

`sentinel/report/literals.py::stale_literals`. For every metric id that exists
today, it collects every value that id has ever held and no longer holds — by
walking the git history of `results/metrics.json`, plus an explicit
`PRE_HISTORY_SUPERSEDED` table for values that predate the file — and reports
any that appear unmarked in prose.

Enforcement is split, and the split is stated rather than smoothed over:

| scope | enforcement | count today |
|---|---|---:|
| `*.template.md` | **hard assertion, zero permitted** | 0 |
| `docs/` narrative | ratchet against a dated ledger | 49 |

Templates carry the project's live claims and are where a human types a number
that will be presented as current. `docs/HANDOFF.md` and
`docs/CENTREPIECE-INVALIDATED.md` narrate past states by nature — the second is
*about* the run in which the figure was superseded — and marking all 49 would
mean editing documents this project deliberately preserves as session records.
Holding them to a ratchet keeps the number visible instead of implied.

Four negative controls ship with it: a planted stale literal in a template must
be caught, a marked one must be allowed, the *current* value must not be
flagged, and the git walk must return something. The last matters most — the
explicit table alone would already catch the literal that motivated the check,
so a silent degradation to the table would look identical to success.

**The check fired on its own write-up.** The paragraph in
`SUBMISSION.template.md` describing this leak quotes the stale figure, and the
assertion rejected it until the sentence was marked historical. That is the
intended behaviour, and it is the first evidence the guard reaches text written
after it existed.

## What would reverse this

A demonstration that a stale metric value can still reach a rendered document
without failing the build. Three concrete routes, none currently closed:

1. **A superseded value predating `results/metrics.json` and absent from
   `PRE_HISTORY_SUPERSEDED`.** That table is hand-maintained and covers one
   metric id. Any other id that rotted before Phase 4 is invisible to it.
2. **A stale value written at a precision the scanner does not match.**
   `METRIC_LITERAL` ignores one-decimal floats and bare integers, so a p@k
   written as "about 28%" passes untouched.
3. **A historical marker applied to a live number.** The marker is honoured on
   sight; nothing verifies that the sentence it exempts is narrating the past.
   This is the same hole standing rule 7 has — it detects deletion, not
   reversal by edit — and it is now present in two mechanisms rather than one.

Any of the three would show that the property is still a practice.
