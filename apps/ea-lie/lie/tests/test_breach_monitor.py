"""Tests for breach monitor — EA-FCI/EA-DIS/EA-PIP events → notice + iMessage."""
from __future__ import annotations

import pytest

from lie.breach_monitor import BreachEvent, BreachMonitor, BreachResponse, EventSource


@pytest.fixture
def monitor():
    return BreachMonitor(imessage_recipient="+66894999908")


@pytest.fixture
def sample_event():
    return BreachEvent(
        source=EventSource.EA_FCI,
        contract_id="CTR-EPC-2026-001",
        event_type="PAYMENT_DEFAULT",
        description="Milestone payment M3 not received by contractual due date 2026-05-31.",
        evidence_urls=[
            "https://internal.ea/evidence/payment-log-001.pdf",
            "https://internal.ea/evidence/bank-statement.pdf",
        ],
    )


# ---------------------------------------------------------------------------
# Notice generation
# ---------------------------------------------------------------------------

def test_notice_generated_for_ea_fci_event(mocker, monitor, sample_event):
    mocker.patch(
        "lie.breach_monitor.chat_complete",
        return_value="Formal breach notice: Payment default on CTR-EPC-2026-001...",
    )
    mocker.patch("lie.breach_monitor.subprocess.run").return_value.returncode = 0

    result = monitor.process_event(sample_event)

    assert result.notice_generated is True
    assert len(result.notice_text) > 0


def test_evidence_summary_contains_urls(mocker, monitor, sample_event):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice text")
    mocker.patch("lie.breach_monitor.subprocess.run").return_value.returncode = 0

    result = monitor.process_event(sample_event)

    assert "evidence/payment-log-001.pdf" in result.evidence_summary
    assert "evidence/bank-statement.pdf" in result.evidence_summary


def test_evidence_summary_contains_contract_id(mocker, monitor, sample_event):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice text")
    mocker.patch("lie.breach_monitor.subprocess.run").return_value.returncode = 0

    result = monitor.process_event(sample_event)
    assert sample_event.contract_id in result.evidence_summary


# ---------------------------------------------------------------------------
# iMessage notification
# ---------------------------------------------------------------------------

def test_alert_sent_when_recipient_set(mocker, monitor, sample_event):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice")
    mock_run = mocker.patch("lie.breach_monitor.subprocess.run")
    mock_run.return_value.returncode = 0

    result = monitor.process_event(sample_event)
    assert result.alert_sent is True
    mock_run.assert_called_once()


def test_alert_not_sent_when_no_recipient(mocker, sample_event):
    monitor_no_recipient = BreachMonitor(imessage_recipient="")
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice")

    result = monitor_no_recipient.process_event(sample_event)
    assert result.alert_sent is False


def test_alert_failure_does_not_raise(mocker, monitor, sample_event):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice")
    mocker.patch("lie.breach_monitor.subprocess.run", side_effect=Exception("osascript error"))

    result = monitor.process_event(sample_event)
    assert result.alert_sent is False
    assert result.contract_id == sample_event.contract_id


def test_alert_false_on_nonzero_returncode(mocker, monitor, sample_event):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice")
    mock_run = mocker.patch("lie.breach_monitor.subprocess.run")
    mock_run.return_value.returncode = 1
    mock_run.return_value.stderr = b"Messages app not responding"

    result = monitor.process_event(sample_event)
    assert result.alert_sent is False


# ---------------------------------------------------------------------------
# All three event sources
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", list(EventSource))
def test_all_event_sources_processed(mocker, source):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice")
    mocker.patch("lie.breach_monitor.subprocess.run").return_value.returncode = 0

    mon = BreachMonitor(imessage_recipient="+66894999908")
    event = BreachEvent(
        source=source,
        contract_id="CTR-001",
        event_type="TEST",
        description="Test event",
    )
    result = mon.process_event(event)
    assert isinstance(result, BreachResponse)
    assert result.contract_id == "CTR-001"


# ---------------------------------------------------------------------------
# BreachEvent model
# ---------------------------------------------------------------------------

def test_breach_event_auto_timestamp():
    event = BreachEvent(
        source=EventSource.EA_DIS,
        contract_id="CTR-002",
        event_type="DELAY",
        description="Completion delayed.",
    )
    assert event.timestamp is not None
    assert event.timestamp.tzinfo is not None  # UTC-aware


def test_notice_failed_when_lmstudio_down(mocker, monitor, sample_event):
    mocker.patch(
        "lie.breach_monitor.chat_complete",
        side_effect=Exception("Connection refused"),
    )
    mocker.patch("lie.breach_monitor.subprocess.run").return_value.returncode = 0

    result = monitor.process_event(sample_event)
    assert result.notice_generated is False
    assert result.contract_id == sample_event.contract_id


def test_recipient_read_from_env(mocker, monkeypatch, sample_event):
    monkeypatch.setenv("ALERT_IMESSAGE_RECIPIENT", "+66894999908")
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice")
    mock_run = mocker.patch("lie.breach_monitor.subprocess.run")
    mock_run.return_value.returncode = 0

    mon = BreachMonitor()  # no explicit recipient — must read from env
    result = mon.process_event(sample_event)
    assert result.alert_sent is True
