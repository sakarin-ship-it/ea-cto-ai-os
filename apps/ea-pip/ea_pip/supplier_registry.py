"""Supplier registry — DBD API verification and supplier management."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from ea_pip.constants import DBD_API_BASE, DBDStatus
from ea_pip.models import Supplier, append_audit


@dataclass
class DBDVerificationResult:
    tax_id: str
    dbd_reg_no: str
    company_name_th: str
    status: DBDStatus
    verified_at: datetime


# Thai status text → DBDStatus enum
# Source: openapi.dbd.go.th / OrganizationJuristicStatus field
_STATUS_MAP: dict[str, DBDStatus] = {
    "ยังดำเนินกิจการอยู่": DBDStatus.ACTIVE,
    "เลิก": DBDStatus.REVOKED,
    "เสร็จชำระบัญชี": DBDStatus.REVOKED,   # liquidation completed
    "ร้าง": DBDStatus.SUSPENDED,             # dormant / abandoned
}


def _parse_dbd_status(raw: str) -> DBDStatus:
    return _STATUS_MAP.get(raw.strip(), DBDStatus.UNKNOWN)


def verify_with_dbd(tax_id: str) -> DBDVerificationResult:
    """Call the public DBD open-data API. No API key required.

    Endpoint: GET https://openapi.dbd.go.th/api/v1/juristic_person/{juristicID}
    The 13-digit Thai TIN is the same as the juristic ID for registered companies.
    """
    response = httpx.get(
        f"{DBD_API_BASE}/juristic_person/{tax_id}",
        timeout=15.0,
    )
    response.raise_for_status()
    data = response.json()

    items = data.get("data", [])
    if not items:
        # status code 1004 = no data found for this TIN
        return DBDVerificationResult(
            tax_id=tax_id,
            dbd_reg_no="",
            company_name_th="",
            status=DBDStatus.UNKNOWN,
            verified_at=datetime.now(timezone.utc),
        )

    person = items[0].get("cd:OrganizationJuristicPerson", {})
    raw_status = person.get("cd:OrganizationJuristicStatus", "")

    return DBDVerificationResult(
        tax_id=tax_id,
        dbd_reg_no=person.get("cd:OrganizationJuristicID", ""),
        company_name_th=person.get("cd:OrganizationJuristicNameTH", ""),
        status=_parse_dbd_status(raw_status),
        verified_at=datetime.now(timezone.utc),
    )


def register_supplier(
    name_en: str,
    tax_id: str,
    contact_email: str,
    actor: str,
    session: Session,
    *,
    name_th: str = "",
    contact_phone: str = "",
    address_en: str = "",
    address_th: str = "",
) -> Supplier:
    """Register a new supplier and perform DBD verification."""
    existing = session.query(Supplier).filter(Supplier.tax_id == tax_id).first()
    if existing:
        raise ValueError(f"Supplier with tax_id {tax_id} already registered")

    try:
        result = verify_with_dbd(tax_id)
        dbd_status = result.status.value
        dbd_reg_no = result.dbd_reg_no
        if not name_th:
            name_th = result.company_name_th
        dbd_verified_at = result.verified_at
    except Exception:
        dbd_status = DBDStatus.UNKNOWN.value
        dbd_reg_no = ""
        dbd_verified_at = None

    supplier = Supplier(
        name_en=name_en,
        name_th=name_th,
        tax_id=tax_id,
        dbd_reg_no=dbd_reg_no,
        dbd_status=dbd_status,
        dbd_verified_at=dbd_verified_at,
        contact_email=contact_email,
        contact_phone=contact_phone,
        address_en=address_en,
        address_th=address_th,
    )
    session.add(supplier)
    session.flush()

    append_audit(
        session,
        entity_type="supplier",
        entity_id=supplier.id,
        action="supplier_registered",
        actor=actor,
        payload={"tax_id": tax_id, "dbd_status": dbd_status},
    )
    return supplier


def refresh_dbd_status(supplier_id: int, actor: str, session: Session) -> Supplier:
    """Re-verify an existing supplier against the DBD API."""
    supplier = session.get(Supplier, supplier_id)
    if supplier is None:
        raise ValueError(f"Supplier {supplier_id} not found")

    result = verify_with_dbd(supplier.tax_id)
    supplier.dbd_status = result.status.value
    supplier.dbd_reg_no = result.dbd_reg_no
    supplier.dbd_verified_at = result.verified_at

    append_audit(
        session,
        entity_type="supplier",
        entity_id=supplier_id,
        action="dbd_status_refreshed",
        actor=actor,
        payload={"dbd_status": result.status.value},
    )
    return supplier
