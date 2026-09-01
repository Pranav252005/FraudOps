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

# --- Candidate pruning ------------------------------------------------------

# Expansion recovers the ring and then buries it. Measured over 230 seeded
# rings (scripts/diagnose_build.py): mean containment is 0.85 but 88 of them
# (38%) are rejected because the ~17-node neighbourhood around a ~7-node ring
# puts Jaccard under the 0.3 hit floor. Pruning the expansion by-products is
# the honest fix -- it tightens the candidate rather than lowering the bar.
#
# `leaf2` was chosen by measurement, not taste (scripts/sweep_prune.py):
#
#   strategy        BUILT  FOUND   cont   jacc   cand
#   none              115    203  0.846  0.369   17.0
#   leaf2             159    190  0.743  0.485    8.2
#   kcore2            144    148  0.568  0.445    4.4
#   near_or_linked    159    190  0.743  0.485    8.2
#
# leaf2 improves BUILT for *every* typology (BIPARTITE 0->6, STACK 2->9,
# GATHER-SCATTER 23->31) and, unlike kcore2, does not dismantle FAN shapes
# whose sinks are legitimately degree-1. near_or_linked is indistinguishable
# from leaf2 on this data, so the simpler rule wins.
#
# The cost is real and is not hidden: containment falls 0.846 -> 0.743 and 13
# rings that were reachable stop clearing the containment floor. The trade is
# +44 built against -13 found.
PRUNE_STRATEGY = "leaf2"

# --- Features excluded on purpose -------------------------------------------

# 86.6% of laundering rows are ACH against an 11.8% base rate -- a 7.3x lift
# from one column, and a generator artifact rather than a real signal. Using it
# would inflate every reported metric while teaching nothing that transfers.
EXCLUDED_FEATURES = frozenset({"channel"})


# --- Synthetic identity (second domain) -------------------------------------

# The exogenous seed signal: a chargeback, a manual report, a failed step-up.
# PRE-REGISTERED in prereg/synthetic_identity_kill_rule.md before the generator
# existed, because seed generosity sets recall before a single feature does --
# a seed rule chosen after seeing a funnel is a knob that produces whichever
# number is wanted.
#
# The legitimate rate is non-zero on purpose. An investigation that only ever
# starts from a true positive is not an investigation, and false-alarm seeds are
# what make expansion's precision cost visible.
IDENTITY_SEED_RATE_FRAUD = 0.15
IDENTITY_SEED_RATE_LEGIT = 0.002

# There is no window in this domain. The graph is built in one static pass, for
# the reason argued in sentinel/eval/identity.py: the adversary's strategy
# includes deliberate temporal spacing, so a window would make fragmentation
# partly its own artefact. WINDOW_MINUTES above is an AMLworld constant and does
# not travel.
