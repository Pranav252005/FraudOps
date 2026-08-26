"""DPDP Act 2023 purpose limitation, applied to the case store.

Quoted provisions (Digital Personal Data Protection Act, 2023, No. 22 of 2023,
11 August 2023 -- the enacted text, not a paraphrase):

  * Section 4(1): "A person may process the personal data of a Data Principal
    only in accordance with the provisions of this Act and for a lawful
    purpose -- (a) for which the Data Principal has given her consent; or
    (b) for certain legitimate uses."
  * Section 7(d) ("certain legitimate uses"): processing is lawful without
    consent "for fulfilling any obligation under any law for the time being
    in force in India on any person to disclose any information to the State
    or any of its instrumentalities". This is the provision that makes STR
    generation the right output artifact for a payment aggregator: filing a
    Suspicious Transaction Report with FIU-IND under PMLA is exactly such an
    obligation, so a case record built toward that filing does not need the
    data principal's consent to exist.
  * Section 8(7): a Data Fiduciary shall, "unless retention is necessary for
    compliance with any law for the time being in force," (a) "erase personal
    data, upon the Data Principal withdrawing her consent or as soon as it is
    reasonable to assume that the specified purpose is no longer being
    served, whichever is earlier."
  * Section 8(8): the specified purpose is deemed no longer served once the
    Data Principal has neither approached the Data Fiduciary for its
    performance nor exercised her rights, "for such time period as may be
    prescribed" (the DPDP Rules set the actual clock; none had been notified
    at the time this was written, so no specific number is quoted from them).

This module's job is to make purpose, retention and access properties an
actual case record carries, not something described only in the README.

Where a number below is *inferred* rather than quoted from statute, it is
labelled as such in the comment next to it -- the Act's own retention clock
under s.8(8) is left to rules not yet notified, so the floor used here comes
from PMLA/RBI recordkeeping practice and FinCEN's own SAR guidance (which
states supporting SAR documentation must be kept "for five years"), not from
a DPDP-specific number.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum


class Purpose(str, Enum):
    FRAUD_INVESTIGATION = "fraud_investigation"
    REGULATORY_REPORTING = "regulatory_reporting"    # STR/SAR filing to FIU-IND
    MODEL_TRAINING = "model_training"                 # label corpus, re-ranker


# DPDP s.8(7): erase unless retention is necessary for compliance with law.
# These are the retention ceilings applied here -- inferred operational
# defaults grounded in PMLA/RBI recordkeeping obligations and FinCEN's
# 5-year SAR-documentation floor, not a number quoted verbatim from the DPDP
# Act or its (not-yet-notified) rules. Flagged as inference, per instruction.
RETENTION_DAYS: dict[Purpose, int] = {
    # Inferred from PMLA/RBI KYC recordkeeping practice and FinCEN's SAR
    # guidance, both of which set a five-year floor for AML records --
    # not a figure quoted from the DPDP Act itself.
    Purpose.REGULATORY_REPORTING: 5 * 365,
    # Inferred operational default for an open fraud investigation with no
    # regulatory filing yet triggered; not a quoted statutory figure.
    Purpose.FRAUD_INVESTIGATION: 2 * 365,
    # Inferred operational default for a disposed case retained as training
    # data; not a quoted statutory figure.
    Purpose.MODEL_TRAINING: 3 * 365,
}

# DPDP purpose limitation applied as access scoping: who may read a case
# record processed for a given purpose. A case opened only for internal
# fraud investigation is not automatically visible to a "model training"
# consumer, and vice versa -- each purpose carries its own scope.
ACCESS_SCOPES: dict[Purpose, frozenset[str]] = {
    Purpose.FRAUD_INVESTIGATION: frozenset({"fraud_ops", "compliance"}),
    Purpose.REGULATORY_REPORTING: frozenset({"compliance", "fiu_ind_liaison"}),
    Purpose.MODEL_TRAINING: frozenset({"ml_engineering"}),
}


def retention_until(purpose: Purpose, opened_at: datetime) -> datetime:
    return opened_at + timedelta(days=RETENTION_DAYS[purpose])


def is_expired(purpose: Purpose, opened_at: datetime, now: datetime | None = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return now >= retention_until(purpose, opened_at)


def can_access(purpose: Purpose, role: str) -> bool:
    return role in ACCESS_SCOPES.get(purpose, frozenset())
