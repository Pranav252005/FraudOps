# p@10 rises before it falls: the noise arm is not monotone

**Recorded:** 2026-09-01. **Source:** `data/eval_label_tax_noise.json`,
`scripts/eval_label_tax.py --arm noise`. **Pre-registered:**
`prereg/label_tax_noise.md`, which committed to recording a non-monotone
response rather than fitting around it.

## What was measured

Mislabelling a fraction `p` of true training positives as negative, p@10 on
the held-out cycles (true labels, 5 corruption seeds per point):

| p | raw p@10 | seed range |
|---:|---:|---|
| 0.00 | 0.2111 | [0.2111, 0.2111] |
| **0.05** | **0.2289** | [0.2111, 0.2444] |
| 0.10 | 0.2244 | [0.1944, 0.2500] |
| 0.20 | 0.2100 | [0.1833, 0.2333] |
| 0.40 | 0.1844 | [0.1611, 0.2056] |

**Precision rises by +0.0178 at p=0.05 before falling.** The OLS slope is
fitted over all five points regardless, as pre-registered, and the residuals
are stored.

## Why this is filed here rather than explained away

A dose-response that goes the wrong way at the first dose is the shape of a
result that has something wrong with it, and the temptation is to drop the
point, smooth the curve, or start the grid at 0.10. The pre-registration
forbade all three before the numbers existed.

## What bounds how much to read into it

**It sits inside the between-seed spread.** The rise is +0.0178 against a
spread of [0.2111, 0.2444] at that point — 0.0333 wide. A single corruption
draw at p=0.05 flips 8 of 165 positives, and which 8 plausibly matters more
than the rate does. This is consistent with draw noise.

**It appears in the control arm too**, at +0.0245 (0.2111 → 0.2356). The
control has **no wrong labels in it at all** — the flipped positives are simply
removed. So whatever produces the rise, it is not an effect of mislabelling,
and it cannot be evidence that a little label noise helps.

That second point is the one that matters, and it is only available because the
prevalence-matched control was pre-registered. Without it, "a small amount of
label noise improves precision" would have been a defensible-looking reading of
the raw column.

## What it is NOT presented as

Not evidence that label noise helps. Not a regularisation effect. Not a reason
to prefer p=0.05 to p=0. No mechanism is asserted, because none was measured.

## What would reverse this

- **More corruption seeds at p=0.05 and p=0.10.** If the rise survives 25 or 50
  draws with a spread that no longer covers it, it is real and needs a
  mechanism. The pre-registered grid used 5 and was not extended after seeing
  the result; extending it is a new experiment and needs its own
  pre-registration.
- A mechanism that predicts it in advance — for example that removing the
  hardest positives lets the model fit the majority better, which would also
  predict the effect appearing in the control arm, as it does. This is the most
  plausible candidate and it is **untested**.
- The same shape appearing at a different `k`. Only k=10 was fitted; k=20 and
  k=50 rows are stored in the output and have not been examined.
