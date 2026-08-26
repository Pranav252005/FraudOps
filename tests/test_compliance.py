"""Tests for the DPDP purpose-limitation module: retention math and access
scoping as enforceable properties, not just documentation."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sentinel.compliance.purpose import (ACCESS_SCOPES, RETENTION_DAYS,
                                         Purpose, can_access, is_expired,
                                         retention_until)


class TestRetention:
    def test_retention_until_adds_the_configured_days(self):
        opened = datetime(2024, 1, 1, tzinfo=timezone.utc)
        until = retention_until(Purpose.FRAUD_INVESTIGATION, opened)
        assert (until - opened).days == RETENTION_DAYS[Purpose.FRAUD_INVESTIGATION]

    def test_regulatory_reporting_has_the_longest_floor(self):
        """STR filings are the AML-recordkeeping-bound purpose and should
        outlast a purely internal investigation that never escalated."""
        assert (RETENTION_DAYS[Purpose.REGULATORY_REPORTING]
                >= RETENTION_DAYS[Purpose.FRAUD_INVESTIGATION])

    def test_is_expired_false_before_the_floor(self):
        opened = datetime.now(timezone.utc) - timedelta(days=10)
        assert not is_expired(Purpose.FRAUD_INVESTIGATION, opened)

    def test_is_expired_true_after_the_floor(self):
        opened = datetime.now(timezone.utc) - timedelta(
            days=RETENTION_DAYS[Purpose.MODEL_TRAINING] + 1)
        assert is_expired(Purpose.MODEL_TRAINING, opened)

    def test_every_purpose_has_a_retention_floor(self):
        for p in Purpose:
            assert p in RETENTION_DAYS


class TestAccessScoping:
    def test_compliance_can_access_both_investigation_and_reporting(self):
        assert can_access(Purpose.FRAUD_INVESTIGATION, "compliance")
        assert can_access(Purpose.REGULATORY_REPORTING, "compliance")

    def test_ml_engineering_cannot_access_investigation_data(self):
        assert not can_access(Purpose.FRAUD_INVESTIGATION, "ml_engineering")

    def test_unknown_role_is_denied_by_default(self):
        assert not can_access(Purpose.REGULATORY_REPORTING, "marketing")

    def test_every_purpose_has_a_defined_scope(self):
        for p in Purpose:
            assert p in ACCESS_SCOPES
            assert ACCESS_SCOPES[p]  # non-empty
