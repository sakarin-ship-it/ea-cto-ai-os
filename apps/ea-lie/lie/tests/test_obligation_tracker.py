"""Tests for obligation tracker — 90/60/30/7-day alert schedule."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from lie.obligation_tracker import ALERT_DAYS, Obligation, ObligationTracker


@pytest.fixture
def tracker():
    return ObligationTracker()


def _obligation(due_in_days: int = 100) -> Obligation:
    return Obligation(
        id="OBL-TEST-001",
        contract_id="CTR-001",
        description="Payment milestone due",
        due_date=date.today() + timedelta(days=due_in_days),
        parties=["Party A", "Party B"],
        notification_channels=["line", "email"],
    )


# ---------------------------------------------------------------------------
# Alert schedule completeness
# ---------------------------------------------------------------------------

def test_all_four_alert_days_scheduled(tracker):
    """90, 60, 30, and 7-day alerts must all be computed for a far-future obligation."""
    alerts = tracker.compute_alerts(_obligation(due_in_days=100))
    scheduled_days = {a.days_before_due for a in alerts}
    assert scheduled_days == {90, 60, 30, 7}, (
        f"Expected {{90, 60, 30, 7}}, got {scheduled_days}"
    )


def test_alert_days_constant():
    assert set(ALERT_DAYS) == {90, 60, 30, 7}


def test_alert_dates_correct(tracker):
    due = date.today() + timedelta(days=100)
    ob = Obligation(
        id="OBL-DATE-001",
        contract_id="CTR-002",
        description="Test",
        due_date=due,
    )
    alerts = tracker.compute_alerts(ob)
    for alert in alerts:
        expected = due - timedelta(days=alert.days_before_due)
        assert alert.alert_date == expected


# ---------------------------------------------------------------------------
# Partial schedule (obligation due soon)
# ---------------------------------------------------------------------------

def test_only_7_day_alert_when_due_in_10_days(tracker):
    """Only alerts whose alert_date ≥ today should be included."""
    alerts = tracker.compute_alerts(_obligation(due_in_days=10))
    scheduled_days = {a.days_before_due for a in alerts}
    assert scheduled_days == {7}


def test_no_alerts_when_overdue(tracker):
    """No alerts for an obligation already past its due date."""
    ob = Obligation(
        id="OBL-PAST",
        contract_id="CTR-000",
        description="Already overdue",
        due_date=date.today() - timedelta(days=1),
    )
    alerts = tracker.compute_alerts(ob)
    assert alerts == []


def test_obligation_due_exactly_90_days_out(tracker):
    """When due in exactly 90 days, 90-day alert should be today."""
    alerts = tracker.compute_alerts(_obligation(due_in_days=90))
    days = {a.days_before_due for a in alerts}
    assert 90 in days
    ninety_day_alert = next(a for a in alerts if a.days_before_due == 90)
    assert ninety_day_alert.alert_date == date.today()


# ---------------------------------------------------------------------------
# Model integrity
# ---------------------------------------------------------------------------

def test_alert_obligation_id_matches(tracker):
    ob = _obligation()
    alerts = tracker.compute_alerts(ob)
    for alert in alerts:
        assert alert.obligation_id == ob.id


def test_alert_due_date_matches(tracker):
    ob = _obligation(due_in_days=100)
    alerts = tracker.compute_alerts(ob)
    for alert in alerts:
        assert alert.due_date == ob.due_date
