"""Three-way match: Purchase Order × GRN × Invoice.

Tolerances (per spec):
  quantity  ±2%    (QTY_TOLERANCE)
  price     ±0.5%  (PRICE_TOLERANCE_BPS = 50 bps)

Price comparison uses exact integer arithmetic (cross-multiply) to avoid
floor-division rounding errors.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from fci.constants import PRICE_TOLERANCE_BPS, QTY_TOLERANCE, MatchStatus

_QTY_TOL = Decimal(QTY_TOLERANCE)


@dataclass
class MatchResult:
    status: MatchStatus
    qty_ok: bool
    price_ok: bool
    qty_diff_pct: Decimal       # actual qty deviation as a ratio
    price_diff_bps: int         # actual price deviation in basis points (floor)
    reason: str = ""


def three_way_match(
    *,
    po_qty: Decimal,
    po_unit_price_satang: int,
    grn_qty: Decimal,
    inv_qty: Decimal,
    inv_unit_price_satang: int,
) -> MatchResult:
    """Pure-function three-way match — no DB access required."""
    if po_qty == 0:
        raise ValueError("po_qty must be non-zero")
    if po_unit_price_satang <= 0:
        raise ValueError("po_unit_price_satang must be positive")

    # Qty check: |grn_qty - po_qty| / po_qty ≤ 2%
    qty_diff_pct = abs(grn_qty - po_qty) / po_qty
    qty_ok = qty_diff_pct <= _QTY_TOL

    # Price check (exact integer cross-multiply, no floor-division rounding):
    #   |inv - po| * 10_000 ≤ PRICE_TOLERANCE_BPS * po
    price_abs_diff = abs(inv_unit_price_satang - po_unit_price_satang)
    price_ok = price_abs_diff * 10_000 <= PRICE_TOLERANCE_BPS * po_unit_price_satang
    price_diff_bps = price_abs_diff * 10_000 // po_unit_price_satang  # display only

    reasons: list[str] = []
    if not qty_ok:
        reasons.append(f"qty diff {qty_diff_pct:.2%} exceeds ±{_QTY_TOL:.0%}")
    if not price_ok:
        reasons.append(f"price diff {price_diff_bps} bps exceeds ±{PRICE_TOLERANCE_BPS} bps")

    if qty_ok and price_ok:
        status = MatchStatus.MATCH
    elif qty_ok or price_ok:
        status = MatchStatus.PARTIAL
    else:
        status = MatchStatus.MISMATCH

    return MatchResult(
        status=status,
        qty_ok=qty_ok,
        price_ok=price_ok,
        qty_diff_pct=qty_diff_pct,
        price_diff_bps=price_diff_bps,
        reason="; ".join(reasons),
    )


def match_by_ids(po_id: int, grn_id: int, invoice_id: int, session) -> MatchResult:
    """DB-backed three-way match — loads PO / GRN / Invoice from the session."""
    from fci.models import GRN, Invoice, PurchaseOrder

    po = session.get(PurchaseOrder, po_id)
    grn = session.get(GRN, grn_id)
    inv = session.get(Invoice, invoice_id)

    if not (po and grn and inv):
        raise ValueError("PO, GRN, or Invoice not found")

    return three_way_match(
        po_qty=po.qty_ordered,
        po_unit_price_satang=po.unit_price_satang,
        grn_qty=grn.qty_received,
        inv_qty=inv.qty_billed,
        inv_unit_price_satang=inv.unit_price_satang,
    )
