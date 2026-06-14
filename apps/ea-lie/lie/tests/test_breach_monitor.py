"""Tests for breach monitor — EA-FCI/EA-DIS/EA-PIP events → notice + LINE."""
from __future__ import annotations

import pytest

from lie.breach_monitor import BreachEvent, BreachMonitor, BreachResponse, EventSource


@pytest.fixture
def monitor():
    return BreachMonitor(line_token="test_token_abc")


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
    mock_post = mocker.patch("lie.breach_monitor.httpx.post")
    mock_post.return_value.status_code = 200

    result = monitor.process_event(sample_event)

    assert result.notice_generated is True
    assert len(result.notice_text) > 0


def test_evidence_summary_contains_urls(mocker, monitor, sample_event):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice text")
    mocker.patch("lie.breach_monitor.httpx.post").return_value.status_code = 200

    result = monitor.process_event(sample_event)

    assert "evidence/payment-log-001.pdf" in result.evidence_summary
    assert "evidence/bank-statement.pdf" in result.evidence_summary


def test_evidence_summary_contains_contract_id(mocker, monitor, sample_event):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice text")
    mocker.patch("lie.breach_monitor.httpx.post").return_value.status_code = 200

    result = monitor.process_event(sample_event)
    assert sample_event.contract_id in result.evidence_summary


# ---------------------------------------------------------------------------
# LINE notification
# ---------------------------------------------------------------------------

def test_line_sent_when_token_set(mocker, monitor, sample_event):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice")
    mock_post = mocker.patch("lie.breach_monitor.httpx.post")
    mock_post.return_value.status_code = 200

    result = monitor.process_event(sample_event)
    assert result.line_sent is True
    mock_post.assert_called_once()


def test_line_not_sent_when_no_token(mocker, sample_event):
    monitor_no_token = BreachMonitor(line_token="")
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice")

    result = monitor_no_token.process_event(sample_event)
    assert result.line_sent is False


def test_line_failure_does_not_raise(mocker, monitor, sample_event):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice")
    mocker.patch("lie.breach_monitor.httpx.post", side_effect=Exception("network error"))

    result = monitor.process_event(sample_event)
    assert result.line_sent is False
    assert result.contract_id == sample_event.contract_id


# ---------------------------------------------------------------------------
# All three event sources
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source", list(EventSource))
def test_all_event_sources_processed(mocker, source):
    mocker.patch("lie.breach_monitor.chat_complete", return_value="Notice")
    mocker.patch("lie.breach_monitor.httpx.post").return_value.status_code = 200

    mon = BreachMonitor(line_token="tok")
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
    mocker.patch("lie.breach_monitor.httpx.post").return_value.status_code = 200

    result = monitor.process_event(sample_event)
    assert result.notice_generated is False
    assert result.contract_id == sample_event.contract_id
