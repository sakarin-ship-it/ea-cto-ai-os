"""Tests for FIDIC timebar — NEVER miss a timebar."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from lie.fidic_timebar import (
    ALERT_THRESHOLDS,
    FIDICEdition,
    FIDICTimebar,
)

# ---------------------------------------------------------------------------
# CRITICAL: 14 / 7 / 1 day alerts always scheduled
# ---------------------------------------------------------------------------

def test_all_three_alert_thresholds_scheduled_for_future_deadline():
    """14-day, 7-day, and 1-day alerts must ALL be scheduled when deadline is future."""
    tb = FIDICTimebar(FIDICEdition.RED_1999)
    trigger = date.today()
    deadline = tb.create_deadline("20.1", trigger, contract_id="FIDIC-TEST-001")
    assert deadline is not None

    alerts = tb.schedule_all_alerts(deadline)
    days_scheduled = {a.days_before for a in alerts}

    assert 14 in days_scheduled, "14-day alert missing"
    assert 7 in days_scheduled, "7-day alert missing"
    assert 1 in days_scheduled, "1-day alert missing"


def test_safety_net_alert_when_deadline_imminent():
    """If all threshold dates are past but deadline is still future, emit same-day alert."""
    tb = FIDICTimebar(FIDICEdition.RED_1999)
    # Deadline in 1 day from tomorrow → deadline_days=1, trigger=today
    # Use a custom deadline where deadline_date = today + 0 days (edge of missed)
    trigger = date.today() - timedelta(days=27)  # 28-day clause → deadline tomorrow
    deadline = tb.create_deadline("20.1", trigger, "FIDIC-IMMINENT-001")
    assert deadline is not None

    # All threshold dates (14, 7, 1 days before) are in the past when ref = deadline itself
    alerts = tb.schedule_all_alerts(deadline, reference_date=deadline.deadline_date)

    # Either normal alerts exist OR the safety-net 0-day alert fires
    assert len(alerts) > 0, "No alerts scheduled — timebar MISSED!"


def test_timebar_never_missed_clause_20_1():
    """Regression: clause 20.1 deadline 28 days from today must generate ≥3 alerts."""
    tb = FIDICTimebar(FIDICEdition.RED_1999)
    deadline = tb.create_deadline("20.1", date.today())
    assert deadline is not None
    alerts = tb.schedule_all_alerts(deadline)
    assert len(alerts) >= 3


# ---------------------------------------------------------------------------
# Edition detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("FIDIC Conditions of Contract for Construction 1999 Red Book", FIDICEdition.RED_1999),
    ("FIDIC Red Book 2017 First Edition", FIDICEdition.RED_2017),
    ("FIDIC Yellow Book Plant and Design-Build 1999", FIDICEdition.YELLOW_1999),
    ("FIDIC Yellow Book 2017 Second Edition", FIDICEdition.YELLOW_2017),
    ("FIDIC Silver Book EPC Turnkey 1999", FIDICEdition.SILVER_1999),
    ("FIDIC Silver Book 2017 EPC Turnkey", FIDICEdition.SILVER_2017),
    ("FIDIC Gold Book DBO 2008", FIDICEdition.GOLD_2008),
    ("FIDIC Fourth Edition 1987", FIDICEdition.RED_1987),
    ("Standard Construction Contract", FIDICEdition.RED_1999),  # default
])
def test_edition_detection(text, expected):
    tb = FIDICTimebar.detect_edition(text)
    assert tb.edition == expected, (
        f"Detected {tb.edition!r} for text '{text}', expected {expected!r}"
    )


# ---------------------------------------------------------------------------
# Deadline model
# ---------------------------------------------------------------------------

def test_deadline_date_calculation():
    tb = FIDICTimebar(FIDICEdition.RED_1999)
    trigger = date(2026, 6, 1)
    deadline = tb.create_deadline("20.1", trigger)
    assert deadline.deadline_date == date(2026, 6, 29)  # 28 days later


def test_missed_flag():
    tb = FIDICTimebar(FIDICEdition.RED_1999)
    past_trigger = date(2020, 1, 1)
    deadline = tb.create_deadline("20.1", past_trigger)
    assert deadline.missed()


def test_not_missed_future():
    tb = FIDICTimebar(FIDICEdition.RED_1999)
    deadline = tb.create_deadline("20.1", date.today())
    assert not deadline.missed()


def test_unknown_clause_returns_none():
    tb = FIDICTimebar(FIDICEdition.RED_1999)
    result = tb.create_deadline("99.99", date.today())
    assert result is None


# ---------------------------------------------------------------------------
# Alert thresholds constant
# ---------------------------------------------------------------------------

def test_alert_thresholds_include_14_7_1():
    assert set(ALERT_THRESHOLDS) >= {14, 7, 1}


# ---------------------------------------------------------------------------
# Multi-edition clause coverage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("edition,clause", [
    (FIDICEdition.RED_1999, "20.1"),
    (FIDICEdition.RED_2017, "20.2.1"),
    (FIDICEdition.RED_2017, "20.2.4"),
    (FIDICEdition.YELLOW_1999, "20.1"),
    (FIDICEdition.SILVER_1999, "20.1"),
    (FIDICEdition.GOLD_2008, "20.1"),
])
def test_editions_support_notice_of_claim(edition, clause):
    tb = FIDICTimebar(edition)
    deadline = tb.create_deadline(clause, date.today())
    assert deadline is not None, f"{edition} should support clause {clause}"
    alerts = tb.schedule_all_alerts(deadline)
    assert len(alerts) > 0, f"No alerts for {edition} clause {clause}"
