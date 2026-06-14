"""Award management — preferred-bidder letter, 45-day timer, 2nd-bidder fallback."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from ea_pip.constants import AWARD_VALIDITY_DAYS
from ea_pip.models import Award, Bid, Package, Supplier, append_audit


@dataclass
class AwardLetter:
    award_id: int
    letter_ref: str
    package_title_en: str
    package_title_th: str
    supplier_name_en: str
    bid_amount_satang: int
    awarded_at: datetime
    expires_at: datetime
    status: str


def create_award(
    package_id: int,
    preferred_bid_id: int,
    actor: str,
    session: Session,
    *,
    fallback_bid_id: Optional[int] = None,
) -> AwardLetter:
    """Create an award record and preferred-bidder letter with 45-day validity."""
    package = session.get(Package, package_id)
    if package is None:
        raise ValueError(f"Package {package_id} not found")

    preferred_bid = session.get(Bid, preferred_bid_id)
    if preferred_bid is None:
        raise ValueError(f"Bid {preferred_bid_id} not found")

    supplier = session.get(Supplier, preferred_bid.supplier_id)

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=AWARD_VALIDITY_DAYS)
    letter_ref = f"AWARD-{package.package_no}-{now.strftime('%Y%m%d%H%M%S')}"

    award = Award(
        package_id=package_id,
        preferred_bid_id=preferred_bid_id,
        fallback_bid_id=fallback_bid_id,
        letter_ref=letter_ref,
        awarded_at=now,
        expires_at=expires_at,
        status="PENDING_ACCEPTANCE",
    )
    session.add(award)
    session.flush()

    append_audit(
        session,
        entity_type="award",
        entity_id=award.id,
        action="award_created",
        actor=actor,
        payload={
            "package_id": package_id,
            "preferred_bid_id": preferred_bid_id,
            "fallback_bid_id": fallback_bid_id,
            "letter_ref": letter_ref,
            "expires_at": expires_at.isoformat(),
        },
    )

    return AwardLetter(
        award_id=award.id,
        letter_ref=letter_ref,
        package_title_en=package.title_en,
        package_title_th=package.title_th,
        supplier_name_en=supplier.name_en if supplier else "",
        bid_amount_satang=preferred_bid.bid_amount_satang,
        awarded_at=now,
        expires_at=expires_at,
        status="PENDING_ACCEPTANCE",
    )


def accept_award(award_id: int, actor: str, session: Session) -> AwardLetter:
    """Preferred bidder accepts the award."""
    award = session.get(Award, award_id)
    if award is None:
        raise ValueError(f"Award {award_id} not found")
    if award.status != "PENDING_ACCEPTANCE":
        raise ValueError(f"Award {award_id} is not pending acceptance (status={award.status})")

    award.status = "ACCEPTED"
    append_audit(
        session,
        entity_type="award",
        entity_id=award_id,
        action="award_accepted",
        actor=actor,
        payload={},
    )
    return _to_letter(award, session)


def reject_award(award_id: int, actor: str, session: Session) -> Optional[AwardLetter]:
    """Preferred bidder rejects; triggers fallback if registered."""
    award = session.get(Award, award_id)
    if award is None:
        raise ValueError(f"Award {award_id} not found")

    award.status = "REJECTED"
    append_audit(
        session,
        entity_type="award",
        entity_id=award_id,
        action="award_rejected",
        actor=actor,
        payload={},
    )

    if award.fallback_bid_id:
        return trigger_fallback(award_id, actor, session)
    return None


def check_and_expire(award_id: int, actor: str, session: Session) -> bool:
    """Check if 45-day timer has elapsed; mark EXPIRED and trigger fallback if so."""
    award = session.get(Award, award_id)
    if award is None:
        raise ValueError(f"Award {award_id} not found")

    now = datetime.now(timezone.utc)
    if award.status == "PENDING_ACCEPTANCE" and now >= award.expires_at:
        award.status = "EXPIRED"
        append_audit(
            session,
            entity_type="award",
            entity_id=award_id,
            action="award_expired",
            actor=actor,
            payload={"expired_at": now.isoformat()},
        )
        if award.fallback_bid_id:
            trigger_fallback(award_id, actor, session)
        return True
    return False


def trigger_fallback(award_id: int, actor: str, session: Session) -> AwardLetter:
    """Activate the 2nd-bidder (fallback) letter with a fresh 45-day window."""
    award = session.get(Award, award_id)
    if award is None:
        raise ValueError(f"Award {award_id} not found")
    if award.fallback_bid_id is None:
        raise ValueError(f"Award {award_id} has no registered fallback bidder")

    award.status = "FALLBACK_PENDING"

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=AWARD_VALIDITY_DAYS)
    award.expires_at = expires_at

    fallback_bid = session.get(Bid, award.fallback_bid_id)
    package = session.get(Package, award.package_id)
    supplier = session.get(Supplier, fallback_bid.supplier_id) if fallback_bid else None

    letter_ref = f"FALLBACK-{package.package_no}-{now.strftime('%Y%m%d%H%M%S')}"
    award.letter_ref = letter_ref

    append_audit(
        session,
        entity_type="award",
        entity_id=award_id,
        action="fallback_triggered",
        actor=actor,
        payload={
            "fallback_bid_id": award.fallback_bid_id,
            "letter_ref": letter_ref,
            "expires_at": expires_at.isoformat(),
        },
    )

    return AwardLetter(
        award_id=award_id,
        letter_ref=letter_ref,
        package_title_en=package.title_en,
        package_title_th=package.title_th,
        supplier_name_en=supplier.name_en if supplier else "",
        bid_amount_satang=fallback_bid.bid_amount_satang if fallback_bid else 0,
        awarded_at=now,
        expires_at=expires_at,
        status="FALLBACK_PENDING",
    )


def _to_letter(award: Award, session: Session) -> AwardLetter:
    package = session.get(Package, award.package_id)
    preferred_bid = session.get(Bid, award.preferred_bid_id)
    supplier = session.get(Supplier, preferred_bid.supplier_id) if preferred_bid else None
    return AwardLetter(
        award_id=award.id,
        letter_ref=award.letter_ref,
        package_title_en=package.title_en if package else "",
        package_title_th=package.title_th if package else "",
        supplier_name_en=supplier.name_en if supplier else "",
        bid_amount_satang=preferred_bid.bid_amount_satang if preferred_bid else 0,
        awarded_at=award.awarded_at,
        expires_at=award.expires_at,
        status=award.status,
    )
