"""Tier-1 auto-select — >=3 compliant non-ALB bids → lowest price → PO → EA-FCI."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

import httpx
from sqlalchemy.orm import Session

from ea_pip.constants import MIN_COMPLIANT_BIDS_TIER1
from ea_pip.models import Bid, Package, Supplier, append_audit

logger = logging.getLogger(__name__)

FCI_API_URL_ENV = "FCI_API_URL"
FCI_API_KEY_ENV = "FCI_API_KEY"


@dataclass
class Tier1SelectionResult:
    selected_bid_id: int
    supplier_id: int
    bid_amount_satang: int
    compliant_bid_count: int
    po_reference: str
    fci_po_id: str  # empty string if FCI_API_URL not configured


def _create_fci_po(po_ref: str, supplier_name: str, bid_amount_satang: int) -> str:
    """POST to EA-FCI /purchase_orders to complete the PIP→FCI handoff.

    Returns the EA-FCI PO id as a string, or "" if FCI_API_URL is not set.
    When FCI_API_URL is absent a warning is logged and the PO reference is
    recorded in the PIP audit log only — no HTTP call is made.
    """
    fci_url = os.environ.get(FCI_API_URL_ENV, "")
    if not fci_url:
        logger.warning(
            "FCI_API_URL not set — PO %s recorded in PIP audit only, not forwarded to EA-FCI",
            po_ref,
        )
        return ""

    api_key = os.environ.get(FCI_API_KEY_ENV, "")
    headers = {"X-API-Key": api_key} if api_key else {}

    resp = httpx.post(
        f"{fci_url.rstrip('/')}/purchase_orders",
        json={
            "po_number": po_ref,
            "supplier": supplier_name,
            "total_satang": bid_amount_satang,
            "source": "EA-PIP",
        },
        headers=headers,
        timeout=15.0,
    )
    resp.raise_for_status()
    return str(resp.json()["id"])


def autoselect(package_id: int, actor: str, session: Session) -> Tier1SelectionResult:
    """Auto-select lowest compliant bid. Requires >= MIN_COMPLIANT_BIDS_TIER1 eligible bids.

    Eligible = is_compliant=True AND is_alb_flagged=False.
    Raises ValueError if the minimum bid count is not met.
    Creates a PO in EA-FCI via HTTP when FCI_API_URL is configured.
    """
    package = session.get(Package, package_id)
    if package is None:
        raise ValueError(f"Package {package_id} not found")

    eligible = (
        session.query(Bid)
        .filter(
            Bid.package_id == package_id,
            Bid.is_compliant.is_(True),
            Bid.is_alb_flagged.is_(False),
        )
        .all()
    )

    if len(eligible) < MIN_COMPLIANT_BIDS_TIER1:
        raise ValueError(
            f"Tier-1 autoselect requires >= {MIN_COMPLIANT_BIDS_TIER1} compliant bids; "
            f"found {len(eligible)}"
        )

    winning_bid = min(eligible, key=lambda b: b.bid_amount_satang)
    po_ref = f"PO-{package.package_no}-{winning_bid.id:06d}"

    supplier = session.get(Supplier, winning_bid.supplier_id)
    supplier_name = supplier.name_en if supplier else ""

    fci_po_id = _create_fci_po(po_ref, supplier_name, winning_bid.bid_amount_satang)

    append_audit(
        session,
        entity_type="package",
        entity_id=package_id,
        action="tier1_autoselect",
        actor=actor,
        payload={
            "winning_bid_id": winning_bid.id,
            "supplier_id": winning_bid.supplier_id,
            "bid_amount_satang": winning_bid.bid_amount_satang,
            "compliant_count": len(eligible),
            "po_reference": po_ref,
            "fci_po_id": fci_po_id,
        },
    )

    return Tier1SelectionResult(
        selected_bid_id=winning_bid.id,
        supplier_id=winning_bid.supplier_id,
        bid_amount_satang=winning_bid.bid_amount_satang,
        compliant_bid_count=len(eligible),
        po_reference=po_ref,
        fci_po_id=fci_po_id,
    )
