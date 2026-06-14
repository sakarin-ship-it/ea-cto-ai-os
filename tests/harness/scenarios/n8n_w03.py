"""n8n W-03: Invoice TAC Gate — idempotent + gated (logic layer test).

W-03 orchestrates: 3-way match → TAC check → payment initiation.
We test the underlying business logic invariants that W-03 enforces.
Idempotency: same invoice inputs → same outcome on every call.
Gating: milestone without approved TAC → blocked, never reaches payment.
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_ROOT / "apps/ea-fci"), str(_ROOT / "shared")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from fci.constants import MatchStatus
from fci.tac_gate import check_tac_gate
from fci.three_way_match import three_way_match

from tests.harness.generators import three_way_exact_match, three_way_milestone_no_tac

SCENARIO_ID = "n8n_w03"


def _w03_logic(po_qty, po_price, grn_qty, inv_qty, inv_price, is_milestone, has_tac):
    """Simulate W-03 workflow logic: match → TAC → pay/block outcome."""
    match_result = three_way_match(
        po_qty=po_qty,
        po_unit_price_satang=po_price,
        grn_qty=grn_qty,
        inv_qty=inv_qty,
        inv_unit_price_satang=inv_price,
    )

    if match_result.status != MatchStatus.MATCH:
        return {"w03_status": "match_failed", "match_status": match_result.status.value,
                "tac_blocked": None, "block_reason": ""}

    invoice = MagicMock()
    invoice.is_milestone = is_milestone
    invoice.is_equipment = False
    invoice.po_id = 1

    tac = None
    if has_tac:
        tac = MagicMock()
        tac.id = 99
        tac.is_approved = True

    session = MagicMock()
    session.get.return_value = invoice
    session.query.return_value.filter.return_value.first.return_value = tac

    tac_result = check_tac_gate(invoice_id=1, session=session)

    if tac_result.blocked:
        return {"w03_status": "tac_blocked", "match_status": match_result.status.value,
                "tac_blocked": True, "block_reason": tac_result.block_reason}

    return {"w03_status": "payment_initiated", "match_status": match_result.status.value,
            "tac_blocked": False, "block_reason": ""}


def setup(seed: int) -> dict:
    scenario_type = ["milestone_no_tac", "milestone_with_tac", "regular_invoice"][seed % 3]

    if scenario_type == "milestone_no_tac":
        d = three_way_milestone_no_tac(seed)
    elif scenario_type == "milestone_with_tac":
        d = three_way_exact_match(seed, is_milestone=True)
        d.has_approved_tac = True
    else:
        d = three_way_exact_match(seed, is_milestone=False)
        d.has_approved_tac = True

    return {
        "seed": seed,
        "scenario_type": scenario_type,
        "po_qty": str(d.po_qty),
        "po_unit_price_satang": d.po_unit_price_satang,
        "grn_qty": str(d.grn_qty),
        "inv_qty": str(d.inv_qty),
        "inv_unit_price_satang": d.inv_unit_price_satang,
        "is_milestone": d.is_milestone,
        "has_approved_tac": d.has_approved_tac,
    }


def run(data: dict) -> dict:
    kwargs = dict(
        po_qty=Decimal(data["po_qty"]),
        po_price=data["po_unit_price_satang"],
        grn_qty=Decimal(data["grn_qty"]),
        inv_qty=Decimal(data["inv_qty"]),
        inv_price=data["inv_unit_price_satang"],
        is_milestone=data["is_milestone"],
        has_tac=data["has_approved_tac"],
    )

    # Run twice to verify idempotency
    outcome1 = _w03_logic(**kwargs)
    outcome2 = _w03_logic(**kwargs)

    return {
        "outcome1": outcome1,
        "outcome2": outcome2,
        "idempotent": outcome1 == outcome2,
        "scenario_type": data["scenario_type"],
    }


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    # Idempotency: same inputs → same outcome
    assert result["idempotent"], (
        f"seed={seed}: W-03 logic is not idempotent — "
        f"outcome1={result['outcome1']} outcome2={result['outcome2']}"
    )

    o = result["outcome1"]
    st = result["scenario_type"]

    if st == "milestone_no_tac":
        # Must be gated — never reaches payment
        assert o["w03_status"] == "tac_blocked", (
            f"seed={seed}: milestone without TAC must result in tac_blocked, got {o['w03_status']}"
        )
        assert o["tac_blocked"] is True
        assert "TAC" in o["block_reason"]
        assert "BLOCKED" in o["block_reason"]

    elif st == "milestone_with_tac":
        assert o["w03_status"] == "payment_initiated", (
            f"seed={seed}: milestone with approved TAC → payment_initiated, got {o['w03_status']}"
        )
        assert o["tac_blocked"] is False

    else:  # regular_invoice
        assert o["w03_status"] == "payment_initiated", (
            f"seed={seed}: regular invoice → payment_initiated, got {o['w03_status']}"
        )
        assert o["tac_blocked"] is False
