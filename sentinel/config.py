"""Tuning constants, and the evaluation boundary with its justification.

Values here are measured from the data in Phase 0/1, not guessed. Where a
constant exists to avoid a defect in the dataset, the reason is written down --
a future reader who "fixes" one of these by widening it will silently reintroduce
a leak.
"""
from __future__ import annotations

MINUTES_PER_DAY = 1440

# --- Evaluation boundary ----------------------------------------------------

# Days 0-9 carry 99.98% of all edges. Days 10-17 carry 715 edges, of which 652
# are laundering -- 91%. Evaluating across the full span would make "timestamp
# after day 10" a near-perfect classifier on its own, which is a property of the
# generator rather than of fraud.
#
# So the evaluable stream ends here. 363 of 370 rings begin inside it.
EVAL_END_DAY = 10
EVAL_END = EVAL_END_DAY * MINUTES_PER_DAY

# 266 of the 363 evaluable rings have more than two accounts visible inside the
# window. A two-account ring has no community structure to detect, so this is
# the hard ceiling on structural ring recall before detector quality enters.
STRUCTURAL_RECALL_CEILING = 0.733

# --- Replay -----------------------------------------------------------------

TICK_MINUTES = 60

# The full stream is 17.7 days but only ~10 are dense. A 72h window is wide
# enough to contain a multi-day layering chain and narrow enough that ordinary
# traffic has not buried it. The design document's original 30 days would never
# expire anything on a dataset this short.
WINDOW_MINUTES = 72 * 60

# --- Candidate generation ---------------------------------------------------

EXPAND_HOPS = 2
EXPAND_MAX_NODES = 200

# Hub guard. Nodes above this counterparty count are included in a neighbourhood
# but never traversed *through*, because expanding across a hub drags in an
# unrelated crowd and produces the giant cluster that discredits the queue.
EXPAND_MAX_DEGREE = 50

# --- Features excluded on purpose -------------------------------------------

# 86.6% of laundering rows are ACH against an 11.8% base rate -- a 7.3x lift
# from one column, and a generator artifact rather than a real signal. Using it
# would inflate every reported metric while teaching nothing that transfers.
EXCLUDED_FEATURES = frozenset({"channel"})
