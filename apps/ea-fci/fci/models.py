"""SQLAlchemy ORM models for schema `fci`.

All monetary values stored as integer satang (never float).
audit_log is append-only with SHA-256 hash chain (no UPDATE/DELETE on audit rows).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from fci.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Core financial tables
# ─────────────────────────────────────────────────────────────────────────────


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"
    __table_args__ = {"schema": "fci"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    po_number: Mapped[str] = mapped_column(String(100), unique=True)
    supplier: Mapped[str] = mapped_column(String(255))
    currency: Mapped[str] = mapped_column(String(3), default="THB")
    qty_ordered: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price_satang: Mapped[int] = mapped_column(BigInteger)  # satang per unit
    total_satang: Mapped[int] = mapped_column(BigInteger)       # qty * unit_price_satang
    is_milestone: Mapped[bool] = mapped_column(Boolean, default=False)
    is_equipment: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    invoices: Mapped[list["Invoice"]] = relationship(back_populates="po")
    grns: Mapped[list["GRN"]] = relationship(back_populates="po")
    tac_certificates: Mapped[list["TACCertificate"]] = relationship(back_populates="po")
    ld_accruals: Mapped[list["LDAccrual"]] = relationship(back_populates="po")


class GRN(Base):
    __tablename__ = "grn"
    __table_args__ = {"schema": "fci"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("fci.purchase_orders.id"))
    qty_received: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    received_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    inspector: Mapped[str] = mapped_column(String(255))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    po: Mapped["PurchaseOrder"] = relationship(back_populates="grns")
    invoices: Mapped[list["Invoice"]] = relationship(back_populates="grn")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = {"schema": "fci"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("fci.purchase_orders.id"))
    grn_id: Mapped[int | None] = mapped_column(ForeignKey("fci.grn.id"), nullable=True)
    invoice_number: Mapped[str] = mapped_column(String(100), unique=True)
    invoice_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    supplier_ref: Mapped[str] = mapped_column(String(255), default="")
    currency: Mapped[str] = mapped_column(String(3), default="THB")
    qty_billed: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit_price_satang: Mapped[int] = mapped_column(BigInteger)
    amount_satang: Mapped[int] = mapped_column(BigInteger)      # in invoice-currency minor units
    amount_thb_satang: Mapped[int] = mapped_column(BigInteger)  # THB satang equivalent
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    is_milestone: Mapped[bool] = mapped_column(Boolean, default=False)
    is_equipment: Mapped[bool] = mapped_column(Boolean, default=False)
    has_chinese_content: Mapped[bool] = mapped_column(Boolean, default=False)
    dis_doc_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    po: Mapped["PurchaseOrder"] = relationship(back_populates="invoices")
    grn: Mapped["GRN | None"] = relationship(back_populates="invoices")
    payments: Mapped[list["Payment"]] = relationship(back_populates="invoice")


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = {"schema": "fci"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("fci.invoices.id"))
    amount_satang: Mapped[int] = mapped_column(BigInteger)
    payment_date: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    tac_id: Mapped[int | None] = mapped_column(
        ForeignKey("fci.tac_certificates.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    block_reason: Mapped[str] = mapped_column(Text, default="")
    approved_by: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    invoice: Mapped["Invoice"] = relationship(back_populates="payments")
    tac: Mapped["TACCertificate | None"] = relationship()


class TACCertificate(Base):
    __tablename__ = "tac_certificates"
    __table_args__ = {"schema": "fci"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("fci.purchase_orders.id"))
    dis_doc_id: Mapped[str] = mapped_column(String(50))       # EA-DIS DOC-06 document ID
    milestone_ref: Mapped[str] = mapped_column(String(255))
    cto_signature_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 of signed payload
    signed_by: Mapped[str] = mapped_column(String(255))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    po: Mapped["PurchaseOrder"] = relationship(back_populates="tac_certificates")


class LDAccrual(Base):
    __tablename__ = "ld_accruals"
    __table_args__ = {"schema": "fci"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    po_id: Mapped[int] = mapped_column(ForeignKey("fci.purchase_orders.id"))
    contract_value_satang: Mapped[int] = mapped_column(BigInteger)
    daily_rate_bps: Mapped[int] = mapped_column(Integer)  # basis points per day
    cap_pct: Mapped[int] = mapped_column(Integer)          # cap as integer percent
    delay_days: Mapped[int] = mapped_column(Integer)
    raw_ld_satang: Mapped[int] = mapped_column(BigInteger)
    cap_satang: Mapped[int] = mapped_column(BigInteger)
    accrued_satang: Mapped[int] = mapped_column(BigInteger)
    is_capped: Mapped[bool] = mapped_column(Boolean)
    calculation_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    po: Mapped["PurchaseOrder"] = relationship(back_populates="ld_accruals")


class FXPosition(Base):
    __tablename__ = "fx_positions"
    __table_args__ = {"schema": "fci"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    currency_pair: Mapped[str] = mapped_column(String(10))    # e.g. "USDTHB"
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 6))     # THB per foreign major unit
    source: Mapped[str] = mapped_column(String(20), default="BOT")
    rate_date: Mapped[str] = mapped_column(String(10))         # YYYY-MM-DD
    amount_foreign_minor: Mapped[int] = mapped_column(BigInteger)  # foreign minor units (cents)
    amount_thb_satang: Mapped[int] = mapped_column(BigInteger)     # THB satang equivalent
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AnomalyFlag(Base):
    __tablename__ = "anomaly_flags"
    __table_args__ = {"schema": "fci"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(BigInteger)
    score: Mapped[float] = mapped_column(Numeric(10, 6))
    is_anomaly: Mapped[bool] = mapped_column(Boolean)
    features: Mapped[dict] = mapped_column(JSON)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ─────────────────────────────────────────────────────────────────────────────
# Audit log — append-only, SHA-256 hash-chained (no UPDATE / DELETE)
# ─────────────────────────────────────────────────────────────────────────────


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "fci"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[int] = mapped_column(BigInteger)
    action: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict] = mapped_column(JSON)
    prev_hash: Mapped[str] = mapped_column(String(64))
    entry_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


def _compute_hash(
    entry_id: int,
    entity_type: str,
    entity_id: int,
    action: str,
    actor: str,
    payload: dict,
    prev_hash: str,
) -> str:
    data = json.dumps(
        {
            "id": entry_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "actor": actor,
            "payload": payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
    )
    return hashlib.sha256(data.encode()).hexdigest()


def append_audit(
    session,
    *,
    entity_type: str,
    entity_id: int,
    action: str,
    actor: str,
    payload: dict[str, Any],
) -> AuditLog:
    """Append an immutable audit entry with SHA-256 hash chain link."""
    last = (
        session.query(AuditLog)
        .filter(AuditLog.entity_type == entity_type)
        .order_by(AuditLog.id.desc())
        .first()
    )
    prev_hash = last.entry_hash if last else "0" * 64

    entry = AuditLog(
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor=actor,
        payload=payload,
        prev_hash=prev_hash,
        entry_hash="",
    )
    session.add(entry)
    session.flush()  # assign primary key

    entry.entry_hash = _compute_hash(
        entry.id, entity_type, entity_id, action, actor, payload, prev_hash
    )
    return entry
