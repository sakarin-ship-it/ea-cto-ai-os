"""Supplier registry — DBD API verification and supplier management."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from ea_pip.constants import DBD_API_BASE, DBD_API_KEY_ENV, DBDStatus
from ea_pip.models import Supplier, append_audit


@dataclass
class DBDVerificationResult:
    tax_id: str
    dbd_reg_no: str
    company_name_th: str
    status: DBDStatus
    verified_at: datetime


def verify_with_dbd(tax_id: str) -> DBDVerificationResult:
    """Call Thailand DBD open-data API to verify supplier registration status."""
    api_key = os.getenv(DBD_API_KEY_ENV, "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    response = httpx.get(
        f"{DBD_API_BASE}/company/search",
        params={"taxId": tax_id},
        headers=headers,
        timeout=15.0,
    )
    response.raise_for_status()
    data = response.json()

    # DBD API response shape: {"juristicId": "...", "juristicNameTh": "...", "status": "..."}
    item = data.get("data", {}) or {}
    raw_status = str(item.get("status", "UNKNOWN")).upper()

    try:
        dbd_status = DBDStatus(raw_status)
    except ValueError:
        dbd_status = DBDStatus.UNKNOWN

    return DBDVerificationResult(
        tax_id=tax_id,
        dbd_reg_no=str(item.get("juristicId", "")),
        company_name_th=str(item.get("juristicNameTh", "")),
        status=dbd_status,
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
