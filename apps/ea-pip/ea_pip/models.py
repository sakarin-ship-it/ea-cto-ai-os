"""SQLAlchemy ORM models for schema `pip`.

audit_log is append-only with SHA-256 hash chain (no UPDATE/DELETE on audit rows).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ea_pip.db import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Supplier registry
# ─────────────────────────────────────────────────────────────────────────────


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = {"schema": "pip"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name_en: Mapped[str] = mapped_column(String(500))
    name_th: Mapped[str] = mapped_column(String(500), default="")
    tax_id: Mapped[str] = mapped_column(String(20), unique=True)
    dbd_reg_no: Mapped[str] = mapped_column(String(50), default="")
    dbd_status: Mapped[str] = mapped_column(String(20), default="UNKNOWN")
    dbd_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    contact_email: Mapped[str] = mapped_column(String(255), default="")
    contact_phone: Mapped[str] = mapped_column(String(50), default="")
    address_en: Mapped[str] = mapped_column(Text, default="")
    address_th: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    eoi_responses: Mapped[list["EOIResponse"]] = relationship(back_populates="supplier")
    bids: Mapped[list["Bid"]] = relationship(back_populates="supplier")


# ─────────────────────────────────────────────────────────────────────────────
# Procurement packages
# ─────────────────────────────────────────────────────────────────────────────


class Package(Base):
    __tablename__ = "packages"
    __table_args__ = {"schema": "pip"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    package_no: Mapped[str] = mapped_column(String(100), unique=True)
    title_en: Mapped[str] = mapped_column(String(500))
    title_th: Mapped[str] = mapped_column(String(500), default="")
    procurement_tier: Mapped[str] = mapped_column(String(10))  # TIER2 / TIER3
    engineer_estimate_satang: Mapped[int] = mapped_column(BigInteger)
    submission_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    scope_en: Mapped[str] = mapped_column(Text, default="")
    scope_th: Mapped[str] = mapped_column(Text, default="")
    rfx_docx_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rfx_pdf_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    eoi_responses: Mapped[list["EOIResponse"]] = relationship(back_populates="package")
    bids: Mapped[list["Bid"]] = relationship(back_populates="package")
    awards: Mapped[list["Award"]] = relationship(back_populates="package")


# ─────────────────────────────────────────────────────────────────────────────
# EOI responses (Expression of Interest / shortlisting)
# ─────────────────────────────────────────────────────────────────────────────


class EOIResponse(Base):
    __tablename__ = "eoi_responses"
    __table_args__ = {"schema": "pip"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("pip.packages.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("pip.suppliers.id"))
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    is_shortlisted: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    package: Mapped["Package"] = relationship(back_populates="eoi_responses")
    supplier: Mapped["Supplier"] = relationship(back_populates="eoi_responses")


# ─────────────────────────────────────────────────────────────────────────────
# Bids
# ─────────────────────────────────────────────────────────────────────────────


class Bid(Base):
    __tablename__ = "bids"
    __table_args__ = {"schema": "pip"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("pip.packages.id"))
    supplier_id: Mapped[int] = mapped_column(ForeignKey("pip.suppliers.id"))
    bid_amount_satang: Mapped[int] = mapped_column(BigInteger)
    bid_bond_amount_satang: Mapped[int] = mapped_column(BigInteger, default=0)
    is_compliant: Mapped[bool] = mapped_column(Boolean, default=False)
    compliance_notes: Mapped[str] = mapped_column(Text, default="")
    is_alb_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="SUBMITTED")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    package: Mapped["Package"] = relationship(back_populates="bids")
    supplier: Mapped["Supplier"] = relationship(back_populates="bids")
    documents: Mapped[list["BidDocument"]] = relationship(back_populates="bid")
    evaluations: Mapped[list["Evaluation"]] = relationship(back_populates="bid")


# ─────────────────────────────────────────────────────────────────────────────
# Bid documents (AES-256-GCM encrypted)
# ─────────────────────────────────────────────────────────────────────────────


class BidDocument(Base):
    __tablename__ = "bid_documents"
    __table_args__ = {"schema": "pip"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bid_id: Mapped[int] = mapped_column(ForeignKey("pip.bids.id"))
    document_type: Mapped[str] = mapped_column(String(100))   # e.g. "technical_proposal"
    filename: Mapped[str] = mapped_column(String(500))
    encrypted_data: Mapped[bytes] = mapped_column(LargeBinary)
    iv: Mapped[bytes] = mapped_column(LargeBinary)             # AES-GCM nonce (12 bytes)
    tag: Mapped[bytes] = mapped_column(LargeBinary)            # AES-GCM auth tag (16 bytes)
    key_id: Mapped[str] = mapped_column(String(100))           # key reference for KMS
    file_sha256: Mapped[str] = mapped_column(String(64))       # SHA-256 of plaintext
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    bid: Mapped["Bid"] = relationship(back_populates="documents")


# ─────────────────────────────────────────────────────────────────────────────
# Evaluations (BLIND: one row per evaluator per bid)
# ─────────────────────────────────────────────────────────────────────────────


class Evaluation(Base):
    __tablename__ = "evaluations"
    __table_args__ = {"schema": "pip"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    bid_id: Mapped[int] = mapped_column(ForeignKey("pip.bids.id"))
    evaluator_id: Mapped[str] = mapped_column(String(255))
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    bid: Mapped["Bid"] = relationship(back_populates="evaluations")
    scores: Mapped[list["Score"]] = relationship(back_populates="evaluation")


# ─────────────────────────────────────────────────────────────────────────────
# Scores (per criterion per evaluation)
# ─────────────────────────────────────────────────────────────────────────────


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = {"schema": "pip"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    evaluation_id: Mapped[int] = mapped_column(ForeignKey("pip.evaluations.id"))
    criterion: Mapped[str] = mapped_column(String(50))         # technical/experience/…
    raw_score: Mapped[int] = mapped_column(Integer)            # 0–100
    is_nlp_scored: Mapped[bool] = mapped_column(Boolean, default=False)
    z_score: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    evaluation: Mapped["Evaluation"] = relationship(back_populates="scores")


# ─────────────────────────────────────────────────────────────────────────────
# Awards
# ─────────────────────────────────────────────────────────────────────────────


class Award(Base):
    __tablename__ = "awards"
    __table_args__ = {"schema": "pip"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    package_id: Mapped[int] = mapped_column(ForeignKey("pip.packages.id"))
    preferred_bid_id: Mapped[int] = mapped_column(ForeignKey("pip.bids.id"))
    fallback_bid_id: Mapped[int | None] = mapped_column(
        ForeignKey("pip.bids.id"), nullable=True
    )
    letter_ref: Mapped[str] = mapped_column(String(200))
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="PENDING_ACCEPTANCE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    package: Mapped["Package"] = relationship(back_populates="awards")
    preferred_bid: Mapped["Bid"] = relationship(foreign_keys=[preferred_bid_id])
    fallback_bid: Mapped["Bid | None"] = relationship(foreign_keys=[fallback_bid_id])


# ─────────────────────────────────────────────────────────────────────────────
# Audit log — append-only, SHA-256 hash-chained
# ─────────────────────────────────────────────────────────────────────────────


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "pip"}

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
        .with_for_update()  # serialise concurrent inserts to the same chain
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
    session.flush()

    entry.entry_hash = _compute_hash(
        entry.id, entity_type, entity_id, action, actor, payload, prev_hash
    )
    return entry
