"""Tests for tier1_autoselect — >=3 compliant bids, lowest-price selection, PO ref.

All DB calls are mocked.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from ea_pip.constants import MIN_COMPLIANT_BIDS_TIER1
from ea_pip.tier1_autoselect import autoselect

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_bid(bid_id, supplier_id, amount_satang):
    bid = MagicMock()
    bid.id = bid_id
    bid.supplier_id = supplier_id
    bid.bid_amount_satang = amount_satang
    bid.is_compliant = True
    bid.is_alb_flagged = False
    return bid


def _make_package(package_id="PKG-0001"):
    pkg = MagicMock()
    pkg.id = 1
    pkg.package_no = package_id
    return pkg


def _make_session(package, eligible_bids):
    session = MagicMock()
    session.get.return_value = package

    q = MagicMock()
    session.query.return_value = q

    # Bid query: .filter(...all conditions in one call...).all()
    q.filter.return_value.all.return_value = eligible_bids
    # AuditLog query: .filter(...).order_by(...).with_for_update().first()
    q.filter.return_value.order_by.return_value.with_for_update.return_value.first.return_value = None

    session.add = MagicMock()
    session.flush = MagicMock()
    return session


# ── Minimum bid count invariant ────────────────────────────────────────────────


def test_min_compliant_bids_constant():
    assert MIN_COMPLIANT_BIDS_TIER1 == 3


def test_zero_bids_raises():
    pkg = _make_package()
    session = _make_session(pkg, [])
    with pytest.raises(ValueError, match=r">= 3"):
        autoselect(package_id=1, actor="test", session=session)


def test_one_bid_raises():
    pkg = _make_package()
    bids = [_make_bid(1, 10, 5_000_000)]
    session = _make_session(pkg, bids)
    with pytest.raises(ValueError, match=r">= 3"):
        autoselect(package_id=1, actor="test", session=session)


def test_two_bids_raises():
    pkg = _make_package()
    bids = [_make_bid(1, 10, 5_000_000), _make_bid(2, 11, 6_000_000)]
    session = _make_session(pkg, bids)
    with pytest.raises(ValueError, match=r"found 2"):
        autoselect(package_id=1, actor="test", session=session)


# ── Successful selection ───────────────────────────────────────────────────────


def test_exactly_three_compliant_bids_succeeds():
    pkg = _make_package()
    bids = [
        _make_bid(1, 10, 9_000_000),
        _make_bid(2, 11, 8_000_000),
        _make_bid(3, 12, 7_000_000),
    ]
    session = _make_session(pkg, bids)
    result = autoselect(package_id=1, actor="test", session=session)
    assert result.selected_bid_id == 3  # lowest price
    assert result.bid_amount_satang == 7_000_000


def test_selects_lowest_price_not_first_submitted(self=None):
    """Winner is the cheapest bid, not the first in the list."""
    pkg = _make_package()
    bids = [
        _make_bid(1, 10, 10_000_000),  # highest
        _make_bid(2, 11, 6_000_000),   # lowest → should win
        _make_bid(3, 12, 8_000_000),
    ]
    session = _make_session(pkg, bids)
    result = autoselect(package_id=1, actor="test", session=session)
    assert result.selected_bid_id == 2
    assert result.bid_amount_satang == 6_000_000


def test_po_reference_format():
    """PO reference includes package number and winning bid id."""
    pkg = _make_package("PKG-0042")
    bids = [
        _make_bid(5, 10, 5_000_000),
        _make_bid(6, 11, 4_000_000),
        _make_bid(7, 12, 6_000_000),
    ]
    session = _make_session(pkg, bids)
    result = autoselect(package_id=1, actor="test", session=session)
    assert "PKG-0042" in result.po_reference
    assert str(result.selected_bid_id).zfill(6) in result.po_reference


def test_compliant_bid_count_returned():
    pkg = _make_package()
    bids = [_make_bid(i, i + 10, (i + 1) * 1_000_000) for i in range(5)]
    session = _make_session(pkg, bids)
    result = autoselect(package_id=1, actor="test", session=session)
    assert result.compliant_bid_count == 5


def test_missing_package_raises():
    session = MagicMock()
    session.get.return_value = None
    with pytest.raises(ValueError, match="not found"):
        autoselect(package_id=999, actor="test", session=session)


# ── EA-FCI integration ────────────────────────────────────────────────────────


def test_fci_po_id_empty_when_fci_url_not_set():
    """Without FCI_API_URL configured, fci_po_id is '' and no HTTP call is made."""
    pkg = _make_package()
    bids = [_make_bid(i, i + 10, (i + 1) * 1_000_000) for i in range(3)]
    session = _make_session(pkg, bids)
    result = autoselect(package_id=1, actor="test", session=session)
    assert result.fci_po_id == ""


def test_fci_po_created_when_url_configured():
    """When FCI_API_URL is set, _create_fci_po is called and its response id stored."""
    pkg = _make_package()
    bids = [_make_bid(i, i + 10, (i + 1) * 1_000_000) for i in range(3)]
    session = _make_session(pkg, bids)

    fake_resp = MagicMock()
    fake_resp.json.return_value = {"id": 99}
    fake_resp.raise_for_status = MagicMock()

    with patch.dict("os.environ", {"FCI_API_URL": "http://fci:8001"}):
        with patch("ea_pip.tier1_autoselect.httpx.post", return_value=fake_resp) as mock_post:
            result = autoselect(package_id=1, actor="test", session=session)

    assert result.fci_po_id == "99"
    mock_post.assert_called_once()
    call_url = mock_post.call_args[0][0]
    assert "/purchase_orders" in call_url
    payload = mock_post.call_args[1]["json"]
    assert payload["po_number"] == result.po_reference
    assert payload["total_satang"] == result.bid_amount_satang
    assert payload["source"] == "EA-PIP"
