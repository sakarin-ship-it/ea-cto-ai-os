"""Tests for three_way_match — pure-function, no DB needed."""
from __future__ import annotations

from decimal import Decimal

import pytest

from fci.constants import MatchStatus
from fci.three_way_match import three_way_match

# Baseline PO values
PO_QTY = Decimal("100")
PO_PRICE = 1_000_000  # satang (= 10,000 THB)


def _match(grn_qty=PO_QTY, inv_price=PO_PRICE, inv_qty=PO_QTY, po_qty=PO_QTY, po_price=PO_PRICE):
    return three_way_match(
        po_qty=po_qty,
        po_unit_price_satang=po_price,
        grn_qty=grn_qty,
        inv_qty=inv_qty,
        inv_unit_price_satang=inv_price,
    )


# ─── qty ──────────────────────────────────────────────────────────────────────

def test_exact_match():
    r = _match()
    assert r.status == MatchStatus.MATCH
    assert r.qty_ok is True
    assert r.price_ok is True


def test_qty_within_tolerance_positive():
    # +1.5% — within ±2%
    r = _match(grn_qty=Decimal("101.5"))
    assert r.qty_ok is True
    assert r.status == MatchStatus.MATCH


def test_qty_within_tolerance_negative():
    # −1.9% — within ±2%
    r = _match(grn_qty=Decimal("98.1"))
    assert r.qty_ok is True


def test_qty_exactly_at_tolerance():
    # exactly +2%
    r = _match(grn_qty=Decimal("102"))
    assert r.qty_ok is True


def test_qty_outside_tolerance_positive():
    # +2.1% — outside ±2%
    r = _match(grn_qty=Decimal("102.1"))
    assert r.qty_ok is False
    assert r.status in (MatchStatus.MISMATCH, MatchStatus.PARTIAL)


def test_qty_outside_tolerance_large():
    # +3% clearly outside
    r = _match(grn_qty=Decimal("103"))
    assert r.qty_ok is False
    assert r.status in (MatchStatus.MISMATCH, MatchStatus.PARTIAL)


# ─── price ────────────────────────────────────────────────────────────────────

def test_price_within_tolerance():
    # +0.4% → 40 bps ≤ 50 bps
    r = _match(inv_price=PO_PRICE + 4_000)   # 1_004_000
    assert r.price_ok is True


def test_price_exactly_at_tolerance():
    # exactly +0.5% → 50 bps ≤ 50 bps  (boundary: allowed)
    r = _match(inv_price=PO_PRICE + 5_000)   # 1_005_000
    assert r.price_ok is True


def test_price_outside_tolerance():
    # +0.6% → 60 bps > 50 bps
    r = _match(inv_price=PO_PRICE + 6_000)   # 1_006_000
    assert r.price_ok is False
    assert r.status in (MatchStatus.MISMATCH, MatchStatus.PARTIAL)


def test_price_below_tolerance():
    # −0.4% — within
    r = _match(inv_price=PO_PRICE - 4_000)
    assert r.price_ok is True


def test_price_below_outside_tolerance():
    # −0.6% — outside
    r = _match(inv_price=PO_PRICE - 6_000)
    assert r.price_ok is False


# ─── combined mismatch ────────────────────────────────────────────────────────

def test_both_mismatch():
    r = _match(grn_qty=Decimal("110"), inv_price=PO_PRICE + 20_000)
    assert r.status == MatchStatus.MISMATCH
    assert r.qty_ok is False
    assert r.price_ok is False
    assert r.reason  # must be non-empty


def test_partial_qty_ok_price_not():
    r = _match(grn_qty=Decimal("101"), inv_price=PO_PRICE + 20_000)
    assert r.status == MatchStatus.PARTIAL
    assert r.qty_ok is True
    assert r.price_ok is False


# ─── guard rails ─────────────────────────────────────────────────────────────

def test_zero_po_qty_raises():
    with pytest.raises(ValueError, match="po_qty"):
        three_way_match(
            po_qty=Decimal("0"),
            po_unit_price_satang=1_000_000,
            grn_qty=Decimal("100"),
            inv_qty=Decimal("100"),
            inv_unit_price_satang=1_000_000,
        )


def test_negative_po_price_raises():
    with pytest.raises(ValueError, match="po_unit_price_satang"):
        three_way_match(
            po_qty=Decimal("100"),
            po_unit_price_satang=-1,
            grn_qty=Decimal("100"),
            inv_qty=Decimal("100"),
            inv_unit_price_satang=1_000_000,
        )
