"""Compliance checker — completeness, bid-bond, and ALB flag.

Pure helpers (compute_alb_reference, is_alb) are exposed for unit testing.
run_compliance() coordinates all checks and persists results.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy.orm import Session

from ea_pip.constants import ALB_THRESHOLD, BID_BOND_PCT, REQUIRED_DOCUMENTS
from ea_pip.models import Bid, BidDocument, Package, append_audit

# ── Pure ALB helpers (no DB required) ────────────────────────────────────────


def compute_alb_reference(
    other_bid_amounts: list[int],
    engineer_estimate_satang: int,
) -> tuple[Optional[int], int]:
    """Compute (median_satang, reference_satang) for ALB threshold.

    reference = min(median_of_other_bids, engineer_estimate).
    If no other bids, reference = engineer_estimate.
    """
    if other_bid_amounts:
        amounts = sorted(other_bid_amounts)
        n = len(amounts)
        mid = n // 2
        median: Optional[int] = amounts[mid] if n % 2 else (amounts[mid - 1] + amounts[mid]) // 2
    else:
        median = None

    reference = (
        min(median, engineer_estimate_satang)
        if median is not None
        else engineer_estimate_satang
    )
    return median, reference


def is_alb(bid_amount_satang: int, reference_satang: int) -> bool:
    """Return True if bid is abnormally low: bid < ALB_THRESHOLD * reference (strict <)."""
    threshold = int(Decimal(str(reference_satang)) * Decimal(str(ALB_THRESHOLD)))
    return bid_amount_satang < threshold


# ── DB-backed checks ──────────────────────────────────────────────────────────


def _check_completeness(bid_id: int, session: Session) -> tuple[bool, str]:
    docs = session.query(BidDocument).filter(BidDocument.bid_id == bid_id).all()
    categories = {d.document_type for d in docs}
    missing = [r for r in REQUIRED_DOCUMENTS if r not in categories]
    if missing:
        return False, f"Missing required documents: {', '.join(missing)}"
    return True, ""


def _check_bid_bond(bid: Bid, package: Package) -> tuple[bool, str]:
    required = int(Decimal(str(package.engineer_estimate_satang)) * Decimal(str(BID_BOND_PCT)))
    if bid.bid_bond_amount_satang < required:
        return False, (
            f"Bid bond {bid.bid_bond_amount_satang} satang < "
            f"required {required} satang ({int(BID_BOND_PCT * 100)}% of estimate)"
        )
    return True, ""


def _fetch_other_bid_amounts(bid: Bid, session: Session) -> list[int]:
    return [
        b.bid_amount_satang
        for b in session.query(Bid)
        .filter(
            Bid.package_id == bid.package_id,
            Bid.id != bid.id,
            Bid.status.in_(["SUBMITTED", "COMPLIANT", "ALB_FLAGGED"]),
        )
        .all()
    ]


# ── Main entry point ──────────────────────────────────────────────────────────


@dataclass
class ComplianceResult:
    bid_id: int
    is_compliant: bool
    is_alb_flagged: bool
    notes: str
    median_bid_satang: Optional[int]
    reference_satang: int


def run_compliance(bid_id: int, actor: str, session: Session) -> ComplianceResult:
    """Run all compliance checks for a bid and persist the result."""
    bid = session.get(Bid, bid_id)
    if bid is None:
        raise ValueError(f"Bid {bid_id} not found")
    package = session.get(Package, bid.package_id)

    notes_parts: list[str] = []

    complete, note = _check_completeness(bid_id, session)
    if not complete:
        notes_parts.append(note)

    bond_ok, note = _check_bid_bond(bid, package)
    if not bond_ok:
        notes_parts.append(note)

    other_amounts = _fetch_other_bid_amounts(bid, session)
    median, reference = compute_alb_reference(other_amounts, package.engineer_estimate_satang)
    alb_flagged = is_alb(bid.bid_amount_satang, reference)
    if alb_flagged:
        notes_parts.append(
            f"ALB: bid {bid.bid_amount_satang} < "
            f"{int(ALB_THRESHOLD * 100)}% of reference {reference} satang"
        )

    is_compliant = complete and bond_ok
    notes = "; ".join(notes_parts) if notes_parts else "COMPLIANT"

    bid.is_compliant = is_compliant
    bid.is_alb_flagged = alb_flagged
    bid.compliance_notes = notes
    if alb_flagged and is_compliant:
        bid.status = "ALB_FLAGGED"
    elif is_compliant:
        bid.status = "COMPLIANT"
    else:
        bid.status = "NON_COMPLIANT"

    append_audit(
        session,
        entity_type="bid",
        entity_id=bid_id,
        action="compliance_check",
        actor=actor,
        payload={
            "is_compliant": is_compliant,
            "is_alb_flagged": alb_flagged,
            "notes": notes,
            "reference_satang": reference,
        },
    )

    return ComplianceResult(
        bid_id=bid_id,
        is_compliant=is_compliant,
        is_alb_flagged=alb_flagged,
        notes=notes,
        median_bid_satang=median,
        reference_satang=reference,
    )
