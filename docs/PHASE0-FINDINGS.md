# Phase 0 — data verification findings

Both risk gates cleared. Measured on `HI-Small`, not assumed.

## Gate 1 — the pattern file parses

Format confirmed:

```
BEGIN LAUNDERING ATTEMPT - <TYPOLOGY>[:  <description>]
<transaction rows, positional schema of the main CSV, no header>
END LAUNDERING ATTEMPT - <TYPOLOGY>
```

| | |
|---|---|
| Rings parsed | **370** |
| Edges in rings | 3,209 |
| Distinct accounts in rings | 3,170 |
| Time span | 2022-09-01 → 2022-09-18 (18 days) |

Per typology:

| Typology | Rings | Edges | Accounts (min/med/max) | Trivial (≤2 accts) |
|---|---:|---:|---|---:|
| CYCLE | 54 | 287 | 2 / 4 / 12 | 14 |
| GATHER-SCATTER | 51 | 716 | 2 / 15 / 29 | 8 |
| BIPARTITE | 49 | 263 | 2 / 8 / 30 | 18 |
| FAN-OUT | 48 | 342 | 2 / 8 / 17 | 8 |
| SCATTER-GATHER | 44 | 626 | 2 / 9 / 18 | 11 |
| STACK | 43 | 466 | 2 / 15 / 45 | 12 |
| RANDOM | 41 | 191 | 2 / 4 / 12 | 13 |
| FAN-IN | 40 | 318 | 2 / 9 / 17 | 4 |
| **Total** | **370** | **3,209** | | **88** |

## Gate 2 — the labels join to the stream

**3,209 / 3,209 ring edges matched into `HI-Small_Trans.csv` — 100%.**

Ring-level ground truth is fully attachable to the data the detector sees. The
fallback plan (connected components over laundering-flagged transactions) is
not needed and is retired.

Main file profile:

| | |
|---|---|
| Rows | 5,078,344 |
| Laundering rows | 5,177 (1 in 981) |
| Distinct accounts | 515,088 |
| Distinct banks | 30,528 |
| Self-loop rows | 591,211 (**11.64%**) |

## Findings that change the design

### 1. `Payment Format` is a leak. It is excluded from scoring.

| Format | Overall | Of laundering | Lift |
|---|---:|---:|---:|
| Cheque | 36.71% | 6.26% | 0.2× |
| Credit Card | 26.06% | 3.98% | 0.2× |
| **ACH** | **11.83%** | **86.59%** | **7.3×** |
| Cash | 9.67% | 2.09% | 0.2× |
| Reinvestment | 9.47% | 0.00% | 0.0× |
| Wire | 3.38% | 0.00% | 0.0× |

86.6% of laundering is ACH against an 11.8% base rate. This is a **generator
artifact**, not a real-world property — the same class of defect as PaySim's
`amount == oldbalanceOrig` shortcut.

**Decision: `Payment Format` is excluded from all scoring features.** Using it
would inflate every reported metric while teaching the model nothing that
transfers. The exclusion is stated in the README and the field is retained for
display only. A with/without comparison will be reported to quantify what was
left on the table.

### 2. Roughly a quarter of rings are structurally unfindable

88 of 370 rings (23.8%) involve two accounts or fewer. A two-account ring has
no community structure to detect. **The ceiling on structural ring recall is
therefore ~76.2%**, before any detector quality is considered.

This is reported as a ceiling rather than buried — recall against a target that
includes undetectable instances is a misleading number in either direction.

### 3. Self-loops must be filtered

11.64% of all rows are an account paying itself (and 11 such edges appear
inside labelled rings). These are dropped from graph construction; left in,
they create spurious self-referential structure everywhere.

### 4. Cross-border is real signal — and geography needs no fabrication

`HI-Small_accounts.csv` encodes jurisdiction in the bank name: non-US banks are
`"<Country> Bank #n"`, US banks carry realistic American names (parsed as USA).
Coverage is 100% across **34 countries**.

- **329 / 370 rings (89%) span more than one country**, up to 16.
- 366 / 370 span more than one bank, up to 44.
- Account distribution: USA 38.8%, Germany 6.3%, Switzerland 4.8%, China 4.5%,
  France 4.1%, **India 3.7% (19,359 accounts)**.

The corridor view in the design document is therefore **real country-level
geography**, not a presentation mapping. The warning against fabricating an
India map stands and is now moot — no fabrication is required.

### 5. The identity graph is thin here, and that is worth saying

`Entity ID` links accounts to a shared legal owner: 38.2% of entities own more
than one account, covering 415,892 accounts. But only **17 of 370 rings (5%)**
contain a shared-owner edge.

The dual-graph design is retained — shared-identity structure is the dominant
signal on card data (device, card fingerprint, email) — but on this dataset the
**money graph carries nearly all the weight**, and scoring should not assume
otherwise.

## Bug caught, and why it is recorded

The first geography run reported 0/370 rings spanning multiple countries, which
contradicted visible evidence (a single labelled cycle hops Yuan → Swiss Franc →
Shekel → Rupee). The cause: **bank IDs are zero-padded in the transaction and
pattern files but unpadded in the accounts file**, so every registry lookup
silently missed and every account resolved to "Unknown" — one distinct value,
hence "one country".

Normalised in `account_key()`. Recorded because a silent join failure that
returns a plausible-looking answer is the single most dangerous failure mode in
this project, and the sanity check that caught it is worth keeping.

---

# Phase 0 review — defects found and fixed

Reviewed after the gates passed. The pattern file itself is structurally clean
(370 BEGIN / 370 END, zero empty blocks, zero typology mismatches, every row
exactly 11 fields), so none of these were biting on this input. They were all
latent, and all of the same shape: **producing a plausible wrong answer instead
of an error.** That is the failure mode that already cost us once, when the
zero-padding bug silently reported that no ring crosses a border.

| # | Severity | Defect | Fix |
|---|---|---|---|
| 1 | High | A nested `BEGIN` silently discarded the enclosing block. In a probe, 3 blocks became 1 ring with no diagnostic. | Parser returns a `ParseReport` counting nested begins, empty blocks, orphan rows, unmatched ends, malformed rows and typology mismatches. `load_rings(strict=True)` raises. |
| 2 | High | `account_key("")` returned `0:ACC`, colliding with the genuine bank `0`. | Absent bank id maps to a reserved `?` marker. |
| 3 | Medium | `parse_row` truncated rows with more than 11 fields, mapping values to the wrong columns while appearing to succeed. | Exact field-count check; over-long rows raise. |
| 4 | Medium | `parse_country("Savings Bank #12")` invented a country called "Savings". | Validated against `KNOWN_COUNTRIES`; unrecognised names fall back to USA and are counted in `unrecognised_banks`. |
| 5 | Medium | `LabeledRing` with no edges constructed fine, then raised from `t_start` deep inside reporting. | Invariant enforced in `__post_init__`. |
| 6 | Low-Med | The label join key formatted amounts to 2dp, collapsing `0.005` and `0.01`. | New `amount_key()` normalises the decimal instead, keeping distinct amounts distinct. |
| 7 | Low-Med | `shared_owner_pairs` silently skipped entities above the clique cap (the largest owns 7,820 accounts). | Cap named `MAX_ENTITY_CLIQUE`; skips counted in `oversized_entities`. |
| 8 | Low | Inconsistent sentinels — `country()` returned `"Unknown"`, `entity()` returned `""`. | Both use `AccountRegistry.UNKNOWN`. |
| 9 | Low | `verify_patterns.py` divided by zero on an empty ring set. | Guarded; the script now also fails loudly if the parse report is not clean. |

**32 regression tests** in `tests/test_phase0.py`, all passing. Each encodes one
of the above, plus integration tests against the real files: the pattern file
parses clean, all eight typologies are present, every ring account resolves in
the registry (the padding-bug regression at full scale), cross-border structure
exceeds 80%, no invented countries, and the 88-ring evaluation ceiling holds.
