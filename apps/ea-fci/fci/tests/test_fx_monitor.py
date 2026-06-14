"""Tests for fx_monitor — BOT API parsing and satang conversion.

httpx.get is monkeypatched; no real network calls made.
"""
from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from fci.fx_monitor import convert_to_thb_satang, extract_mid_rate, fetch_bot_rate

# ─── extract_mid_rate ────────────────────────────────────────────────────────

def _bot_response(mid_rate=None, selling=None):
    row: dict = {}
    if mid_rate is not None:
        row["mid_rate"] = mid_rate
    if selling is not None:
        row["selling"] = selling
    return {"result": {"data": [row]}}


def test_extract_mid_rate_standard():
    resp = _bot_response(mid_rate="34.6500")
    assert extract_mid_rate(resp) == Decimal("34.6500")


def test_extract_mid_rate_falls_back_to_selling():
    resp = _bot_response(selling="34.8000")
    assert extract_mid_rate(resp) == Decimal("34.8000")


def test_extract_mid_rate_prefers_mid_over_selling():
    resp = _bot_response(mid_rate="34.65", selling="34.80")
    assert extract_mid_rate(resp) == Decimal("34.65")


def test_extract_mid_rate_empty_data_raises():
    with pytest.raises(ValueError, match="Empty data"):
        extract_mid_rate({"result": {"data": []}})


def test_extract_mid_rate_missing_keys_raises():
    with pytest.raises(ValueError):
        extract_mid_rate({"result": {"data": [{"period": "2026-06-14"}]}})


def test_extract_mid_rate_bad_structure_raises():
    with pytest.raises(ValueError):
        extract_mid_rate({"result": {}})


# ─── convert_to_thb_satang ───────────────────────────────────────────────────

def test_convert_100_usd_to_satang():
    """100 USD = 10_000 USD cents; at 34.65 THB/USD → 346_500 satang."""
    result = convert_to_thb_satang(10_000, Decimal("34.65"))
    assert result == 346_500


def test_convert_1_usd_cent_rounds_half_up():
    """1 USD cent at 34.655 → 34.655 satang → rounds to 35."""
    result = convert_to_thb_satang(1, Decimal("34.655"))
    assert result == 35


def test_convert_1_usd_cent_rounds_down():
    """1 USD cent at 34.400 → 34.400 satang → ROUND_HALF_UP → 34."""
    result = convert_to_thb_satang(1, Decimal("34.400"))
    assert result == 34


def test_convert_exact_integer_result():
    """1000 cents at 34.00 → 34_000 satang (exact)."""
    result = convert_to_thb_satang(1_000, Decimal("34.00"))
    assert result == 34_000


def test_convert_returns_int():
    result = convert_to_thb_satang(500, Decimal("35.1234"))
    assert isinstance(result, int)


def test_convert_zero_amount():
    result = convert_to_thb_satang(0, Decimal("34.65"))
    assert result == 0


# ─── fetch_bot_rate (network mocked) ─────────────────────────────────────────

def test_fetch_bot_rate_sends_currency_param(monkeypatch):
    import httpx

    captured: list[dict] = []

    def mock_get(url, *, params=None, headers=None, timeout=None):
        captured.append({"url": url, "params": params})
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = _bot_response(mid_rate="34.65")
        return resp

    monkeypatch.setattr(httpx, "get", mock_get)
    fetch_bot_rate("USD")

    assert len(captured) == 1
    assert captured[0]["params"]["currency_id"] == "USD"


def test_fetch_bot_rate_sends_date_params_when_provided(monkeypatch):
    import httpx

    captured: list[dict] = []

    def mock_get(url, *, params=None, headers=None, timeout=None):
        captured.append(params or {})
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = _bot_response(mid_rate="34.65")
        return resp

    monkeypatch.setattr(httpx, "get", mock_get)
    fetch_bot_rate("EUR", date_str="2026-06-14")

    p = captured[0]
    assert p["start_period"] == "2026-06-14"
    assert p["end_period"] == "2026-06-14"
    assert p["currency_id"] == "EUR"


def test_fetch_bot_rate_raises_on_http_error(monkeypatch):
    import httpx

    def mock_get(url, **kw):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock()
        )
        return resp

    monkeypatch.setattr(httpx, "get", mock_get)
    with pytest.raises(httpx.HTTPStatusError):
        fetch_bot_rate("USD")
