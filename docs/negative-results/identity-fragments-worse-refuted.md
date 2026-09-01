# "Synthetic identity fragments worse than AMLworld" — refuted

**Measured:** 2026-09-01, Phase D, against
`prereg/synthetic_identity_fragmentation.md` (committed `8453492`, before either
domain was measured). Numbers in `data/fragmentation.json`.

## The claim

The proposal for the second domain rested on a prediction, stated plainly:
synthetic identity would show **lower seed coverage** and **higher
fragmentation** than AMLworld at equivalent cluster sizes, because in AMLworld
fragmentation is an artefact of the 72-hour window while in synthetic identity
it is the adversary's design.

That was to be the headline: *we found this by accident on transaction data,
then went to the domain where it is the whole problem.*

## What was measured

Seed-reach coverage — what a 2-hop expansion from a group's own seeds can see of
that group — under the shipped expansion constants, computed identically in both
domains and never pooled.

| domain | coverage | interval | clustering |
|---|---:|---|---|
| amlworld-hi-small | 0.8058 | [0.7627, 0.8499] | wider of cycle- and ring-clustered |
| synthetic-identity-v1, primary config | 0.8965 | [0.8759, 0.9159] | world-clustered |

**The identity domain fragments LESS, not more.** The intervals do not overlap.
The direction is the opposite of the one predicted.

## Why this is recorded rather than absorbed

The prediction was demoted from primary to secondary-descriptive **before
measuring**, in the pre-registration, on the grounds that the identity domain's
difficulty is a dial this project sets and a comparison between 18 AMLworld
cycles and a knob is not a test. That demotion is the only reason this is an
observation rather than a failed headline — and it would be dishonest to let the
demotion quietly erase the claim that motivated the whole domain.

The claim was made. It did not survive. Both facts belong on the record.

## What survived instead

The dose-response inside the domain, which was the primary prediction and
which holds on every arm: coverage falls monotonically in `rotation_rate`
(Δ = −0.1791 [−0.1937, −0.1645] at overlap 0.0), and the mechanism behind it —
cluster diameter rising with rotation — holds too.

So the defensible statement is **not** "identity fragments worse than
laundering". It is: *fragmentation in this domain is under the adversary's
control, and turning the adversary up makes it monotonically worse.* That is a
claim about a mechanism rather than a league table, and it is the one the data
supports.

## What would reverse this

A cross-domain contrast that is actually controlled: matched group-size
distributions, matched seeded share, and matched expansion radius relative to
group diameter, measured on both sides. Under those controls the ordering may
well flip — at `rotation_rate=0.7` the identity number is 0.8010, already
statistically indistinguishable from AMLworld's 0.8058, and at cluster size 12
with rotation 0.7 it falls to 0.7097, below it.

That measurement has not been made, and until it is, neither ordering is a
finding about the domains rather than about the parameters.
