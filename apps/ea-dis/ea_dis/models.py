"""SQLAlchemy ORM models for schema 'dis'."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Optional

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ea_dis.db import Base

EMBEDDING_DIM = 1024  # bge-m3 output dimension


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {"schema": "dis"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    original_language: Mapped[Optional[str]] = mapped_column(String(8))
    doc_type: Mapped[Optional[str]] = mapped_column(String(16))
    confidence: Mapped[Optional[float]] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING_REVIEW")
    page_count: Mapped[Optional[int]] = mapped_column(Integer)
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    chunks: Mapped[list[DocChunk]] = relationship(
        "DocChunk", back_populates="document", cascade="all, delete-orphan"
    )
    obligations: Mapped[list[Obligation]] = relationship(
        "Obligation", back_populates="document", cascade="all, delete-orphan"
    )


class DocChunk(Base):
    __tablename__ = "doc_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunk_doc_idx"),
        {"schema": "dis"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dis.documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Optional[Any]] = mapped_column(Vector(EMBEDDING_DIM))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    document: Mapped[Document] = relationship("Document", back_populates="chunks")


class Obligation(Base):
    __tablename__ = "obligations"
    __table_args__ = {"schema": "dis"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("dis.documents.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    responsible_party: Mapped[Optional[str]] = mapped_column(String(256))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    document: Mapped[Document] = relationship("Document", back_populates="obligations")


class AuditLog(Base):
    """Append-only audit log with SHA-256 hash chain.

    No UPDATE or DELETE on rows — enforced at application layer.
    hash_value = SHA-256(entity_type + entity_id + action + payload_json + prev_hash)
    """
    __tablename__ = "audit_log"
    __table_args__ = {"schema": "dis"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor: Mapped[Optional[str]] = mapped_column(String(128))
    payload: Mapped[Optional[dict]] = mapped_column(JSONB)
    prev_hash: Mapped[Optional[str]] = mapped_column(String(64))
    hash_value: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


def compute_audit_hash(
    entity_type: str,
    entity_id: str,
    action: str,
    payload: Any,
    prev_hash: str | None,
) -> str:
    raw = json.dumps(
        {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "action": action,
            "payload": payload,
            "prev_hash": prev_hash or "",
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def append_audit(
    db,
    entity_type: str,
    entity_id: str,
    action: str,
    payload: Any = None,
    actor: str | None = None,
) -> AuditLog:
    """Append an immutable audit record linked to the previous entry."""
    from sqlalchemy import select

    last = db.execute(
        select(AuditLog.hash_value)
        .where(AuditLog.entity_type == entity_type)
        .order_by(AuditLog.id.desc())
        .limit(1)
    ).scalar_one_or_none()

    h = compute_audit_hash(entity_type, entity_id, action, payload, last)
    entry = AuditLog(
        entity_type=entity_type,
        entity_id=str(entity_id),
        action=action,
        actor=actor,
        payload=payload,
        prev_hash=last,
        hash_value=h,
    )
    db.add(entry)
    db.flush()
    return entry
