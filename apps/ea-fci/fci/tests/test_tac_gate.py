"""Tests for tac_gate — proves no milestone/equipment payment without valid TAC.

All DB calls are mocked; no live database required.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from fci.tac_gate import check_tac_gate


def _mock_invoice(is_milestone: bool = False, is_equipment: bool = False, po_id: int = 1):
    inv = MagicMock()
    inv.is_milestone = is_milestone
    inv.is_equipment = is_equipment
    inv.po_id = po_id
    return inv


def _mock_session(invoice, tac=None):
    session = MagicMock()
    session.get.return_value = invoice
    session.query.return_value.filter.return_value.first.return_value = tac
    return session


def _approved_tac(tac_id: int = 99):
    tac = MagicMock()
    tac.id = tac_id
    tac.is_approved = True
    return tac


# ─────────────────────────────────────────────────────────────────────────────
# Key invariant: no milestone payment without TAC
# ─────────────────────────────────────────────────────────────────────────────

def test_milestone_payment_blocked_when_no_tac():
    """Core spec invariant: milestone invoice with no TAC → BLOCKED."""
    session = _mock_session(_mock_invoice(is_milestone=True), tac=None)
    result = check_tac_gate(invoice_id=1, session=session)

    assert result.blocked is True
    assert result.tac_id is None


def test_milestone_block_reason_is_explicit():
    """block_reason must mention TAC and be non-empty."""
    session = _mock_session(_mock_invoice(is_milestone=True), tac=None)
    result = check_tac_gate(invoice_id=1, session=session)

    assert result.block_reason, "block_reason must not be empty"
    assert "TAC" in result.block_reason
    assert "BLOCKED" in result.block_reason


def test_equipment_payment_blocked_when_no_tac():
    """Equipment invoices also require a TAC."""
    session = _mock_session(_mock_invoice(is_equipment=True), tac=None)
    result = check_tac_gate(invoice_id=2, session=session)

    assert result.blocked is True
    assert result.block_reason
    assert "equipment" in result.block_reason.lower()


def test_equipment_block_reason_explicit():
    session = _mock_session(_mock_invoice(is_equipment=True), tac=None)
    result = check_tac_gate(invoice_id=2, session=session)
    assert "TAC" in result.block_reason


# ─────────────────────────────────────────────────────────────────────────────
# Allowed paths
# ─────────────────────────────────────────────────────────────────────────────

def test_regular_invoice_not_blocked():
    """Non-milestone, non-equipment invoice must pass without any TAC."""
    session = _mock_session(_mock_invoice(is_milestone=False, is_equipment=False))
    # tac query should NOT be called — but even if it returns None, must pass
    session.query.return_value.filter.return_value.first.return_value = None
    result = check_tac_gate(invoice_id=3, session=session)

    assert result.blocked is False
    assert result.block_reason == ""


def test_milestone_allowed_with_approved_tac():
    """Milestone invoice passes when an approved TAC exists for the PO."""
    tac = _approved_tac(tac_id=42)
    session = _mock_session(_mock_invoice(is_milestone=True, po_id=7), tac=tac)
    result = check_tac_gate(invoice_id=4, session=session)

    assert result.blocked is False
    assert result.tac_id == 42
    assert result.block_reason == ""


def test_equipment_allowed_with_approved_tac():
    """Equipment invoice passes when an approved TAC exists."""
    tac = _approved_tac(tac_id=55)
    session = _mock_session(_mock_invoice(is_equipment=True, po_id=8), tac=tac)
    result = check_tac_gate(invoice_id=5, session=session)

    assert result.blocked is False
    assert result.tac_id == 55


def test_both_milestone_and_equipment_blocked_without_tac():
    """Invoice with both flags still requires TAC."""
    session = _mock_session(_mock_invoice(is_milestone=True, is_equipment=True), tac=None)
    result = check_tac_gate(invoice_id=6, session=session)
    assert result.blocked is True


# ─────────────────────────────────────────────────────────────────────────────
# Error handling
# ─────────────────────────────────────────────────────────────────────────────

def test_missing_invoice_raises():
    session = MagicMock()
    session.get.return_value = None
    with pytest.raises(ValueError, match="not found"):
        check_tac_gate(invoice_id=999, session=session)
