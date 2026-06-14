"""EA-PIP: tier-1 autoselect — >=3 bids, selects lowest price."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_ROOT / "apps/ea-pip"), str(_ROOT / "shared")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ea_pip.tier1_autoselect import Tier1SelectionResult, autoselect

from tests.harness.generators import BidData, bid_set_tier1

SCENARIO_ID = "pip_tier1"


def _mock_bid(b: BidData):
    m = MagicMock()
    m.id = b.bid_id
    m.supplier_id = b.supplier_id
    m.bid_amount_satang = b.amount_satang
    m.is_compliant = b.is_compliant
    m.is_alb_flagged = b.is_alb_flagged
    m.package_id = 1
    return m


def _mock_session(bids: list[BidData], estimate: int, package_no: str = "PKG-001"):
    mock_bids = [_mock_bid(b) for b in bids if b.is_compliant and not b.is_alb_flagged]

    pkg = MagicMock()
    pkg.id = 1
    pkg.package_no = package_no
    pkg.engineer_estimate_satang = estimate

    supplier = MagicMock()
    supplier.name_en = "Test Supplier Co., Ltd."

    session = MagicMock()
    session.get.side_effect = lambda cls, pk: pkg if pk == 1 else supplier
    session.add = MagicMock()
    session.flush = MagicMock()

    # Bid query: session.query(Bid).filter(...).all() → mock_bids
    q = session.query.return_value
    q.filter.return_value.all.return_value = mock_bids
    # AuditLog query in append_audit:
    #   session.query(AuditLog).filter(...).order_by(...).with_for_update().first() → None
    # This means "no previous audit entry" → prev_hash = "0"*64 (valid string)
    q.filter.return_value.order_by.return_value.with_for_update.return_value.first.return_value = None

    return session, mock_bids


def setup(seed: int) -> dict:
    count = 3 + (seed % 3)  # 3–5 bids
    estimate, bids = bid_set_tier1(seed, count=count)
    lowest_amount = min(b.amount_satang for b in bids if b.is_compliant and not b.is_alb_flagged)
    return {
        "seed": seed,
        "estimate": estimate,
        "bids": [{"bid_id": b.bid_id, "supplier_id": b.supplier_id,
                  "amount_satang": b.amount_satang, "is_compliant": b.is_compliant,
                  "is_alb_flagged": b.is_alb_flagged} for b in bids],
        "compliant_count": sum(1 for b in bids if b.is_compliant and not b.is_alb_flagged),
        "lowest_amount": lowest_amount,
        "package_no": f"PKG-{seed:04d}",
    }


def run(data: dict) -> dict:
    bids = [BidData(
        bid_id=b["bid_id"],
        supplier_id=b["supplier_id"],
        amount_satang=b["amount_satang"],
        bond_amount_satang=0,
        is_compliant=b["is_compliant"],
        is_alb_flagged=b["is_alb_flagged"],
    ) for b in data["bids"]]
    estimate = data["estimate"]
    package_no = data["package_no"]

    session, mock_bids = _mock_session(bids, estimate, package_no)
    result = autoselect(package_id=1, actor="harness", session=session)

    return {
        "selected_bid_id": result.selected_bid_id,
        "bid_amount_satang": result.bid_amount_satang,
        "compliant_bid_count": result.compliant_bid_count,
        "po_reference": result.po_reference,
        "fci_po_id": result.fci_po_id,
    }


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    # Must have >= 3 compliant bids
    assert result["compliant_bid_count"] >= 3, (
        f"seed={seed}: compliant_bid_count={result['compliant_bid_count']} < 3"
    )

    # Selected bid must be the lowest price
    assert result["bid_amount_satang"] == data["lowest_amount"], (
        f"seed={seed}: selected amount {result['bid_amount_satang']} != "
        f"lowest {data['lowest_amount']}"
    )

    # PO reference must contain package number
    assert data["package_no"] in result["po_reference"], (
        f"seed={seed}: po_reference {result['po_reference']!r} must contain package_no"
    )

    # No FCI URL set → fci_po_id is empty string (not None, not missing)
    assert result["fci_po_id"] == "", (
        f"seed={seed}: fci_po_id must be '' when FCI_API_URL not set"
    )
