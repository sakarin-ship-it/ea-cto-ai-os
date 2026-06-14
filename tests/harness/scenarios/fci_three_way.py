"""EA-FCI: three-way match + TAC gate — no pay without TAC, integer satang."""
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
from fci.tac_gate import TACResult, check_tac_gate
from fci.three_way_match import three_way_match

from tests.harness.generators import three_way_exact_match, three_way_milestone_no_tac

SCENARIO_ID = "fci_three_way"


def _mock_session(is_milestone: bool, is_equipment: bool, has_approved_tac: bool, po_id: int = 1):
    invoice = MagicMock()
    invoice.is_milestone = is_milestone
    invoice.is_equipment = is_equipment
    invoice.po_id = po_id

    tac = None
    if has_approved_tac:
        tac = MagicMock()
        tac.id = 42
        tac.is_approved = True

    session = MagicMock()
    session.get.return_value = invoice
    session.query.return_value.filter.return_value.first.return_value = tac
    return session


def setup(seed: int) -> dict:
    # Alternate between milestone-no-TAC (must block) and exact-match with varied milestone flag
    if seed % 3 == 0:
        data = three_way_milestone_no_tac(seed)
        scenario_type = "milestone_no_tac"
    elif seed % 3 == 1:
        data = three_way_exact_match(seed, is_milestone=True)
        data.has_approved_tac = True
        scenario_type = "milestone_with_tac"
    else:
        data = three_way_exact_match(seed, is_milestone=False)
        data.has_approved_tac = True
        scenario_type = "regular_invoice"

    return {
        "seed": seed,
        "scenario_type": scenario_type,
        "po_qty": str(data.po_qty),
        "po_unit_price_satang": data.po_unit_price_satang,
        "grn_qty": str(data.grn_qty),
        "inv_qty": str(data.inv_qty),
        "inv_unit_price_satang": data.inv_unit_price_satang,
        "is_milestone": data.is_milestone,
        "has_approved_tac": data.has_approved_tac,
    }


def run(data: dict) -> dict:
    match_result = three_way_match(
        po_qty=Decimal(data["po_qty"]),
        po_unit_price_satang=data["po_unit_price_satang"],
        grn_qty=Decimal(data["grn_qty"]),
        inv_qty=Decimal(data["inv_qty"]),
        inv_unit_price_satang=data["inv_unit_price_satang"],
    )

    session = _mock_session(
        is_milestone=data["is_milestone"],
        is_equipment=False,
        has_approved_tac=data["has_approved_tac"],
    )
    tac_result = check_tac_gate(invoice_id=1, session=session)

    return {
        "match_status": match_result.status.value,
        "qty_ok": match_result.qty_ok,
        "price_ok": match_result.price_ok,
        "tac_blocked": tac_result.blocked,
        "block_reason": tac_result.block_reason,
        "tac_id": tac_result.tac_id,
        "po_unit_price_satang": data["po_unit_price_satang"],
        "inv_unit_price_satang": data["inv_unit_price_satang"],
    }


def assert_invariants(data: dict, result: dict) -> None:
    # All prices must be integers (satang)
    assert isinstance(result["po_unit_price_satang"], int), (
        f"seed={data['seed']}: po_unit_price_satang must be int"
    )
    assert isinstance(result["inv_unit_price_satang"], int), (
        f"seed={data['seed']}: inv_unit_price_satang must be int"
    )

    # Exact-match data → always MATCH
    assert result["match_status"] == MatchStatus.MATCH.value, (
        f"seed={data['seed']}: exact inputs must produce MATCH, got {result['match_status']}"
    )

    st = data["scenario_type"]
    if st == "milestone_no_tac":
        # Core invariant: milestone without approved TAC MUST be blocked
        assert result["tac_blocked"] is True, (
            f"seed={data['seed']}: milestone with no TAC must be BLOCKED"
        )
        assert result["block_reason"], (
            f"seed={data['seed']}: block_reason must be non-empty when blocked"
        )
        assert "TAC" in result["block_reason"], (
            f"seed={data['seed']}: block_reason must mention 'TAC'"
        )
        assert "BLOCKED" in result["block_reason"], (
            f"seed={data['seed']}: block_reason must contain 'BLOCKED'"
        )

    elif st == "milestone_with_tac":
        assert result["tac_blocked"] is False, (
            f"seed={data['seed']}: milestone with approved TAC must NOT be blocked"
        )
        assert result["tac_id"] == 42, (
            f"seed={data['seed']}: tac_id must match approved TAC"
        )

    else:  # regular_invoice
        assert result["tac_blocked"] is False, (
            f"seed={data['seed']}: regular invoice must never be TAC-blocked"
        )
