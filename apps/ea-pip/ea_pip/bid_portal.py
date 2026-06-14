"""Bid portal — AES-256-GCM upload, hard deadline lock, Q&A broadcast."""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

from ea_pip.constants import MAX_UPLOAD_BYTES
from ea_pip.models import Bid, BidDocument, EOIResponse, Package, append_audit

# ── Encryption helpers ────────────────────────────────────────────────────────


def encrypt_document(plaintext: bytes, key: bytes) -> tuple[bytes, bytes, bytes]:
    """AES-256-GCM encrypt. Returns (ciphertext, nonce, tag). Key must be 32 bytes."""
    if len(key) != 32:
        raise ValueError("AES-256 requires a 32-byte key")
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ct_with_tag = aesgcm.encrypt(nonce, plaintext, None)
    ciphertext, tag = ct_with_tag[:-16], ct_with_tag[-16:]
    return ciphertext, nonce, tag


def decrypt_document(ciphertext: bytes, nonce: bytes, tag: bytes, key: bytes) -> bytes:
    """AES-256-GCM decrypt. Raises cryptography.exceptions.InvalidTag on tampering."""
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext + tag, None)


# ── Bid submission ────────────────────────────────────────────────────────────


@dataclass
class UploadResult:
    bid_document_id: int
    file_sha256: str
    document_type: str


def upload_bid_document(
    bid_id: int,
    document_type: str,
    filename: str,
    plaintext: bytes,
    key: bytes,
    key_id: str,
    actor: str,
    session: Session,
) -> UploadResult:
    """Encrypt and store a bid document. Rejects upload if deadline has passed."""
    bid = session.get(Bid, bid_id)
    if bid is None:
        raise ValueError(f"Bid {bid_id} not found")

    package = session.get(Package, bid.package_id)
    now = datetime.now(timezone.utc)

    if now > package.submission_deadline:
        raise ValueError(
            f"Submission deadline {package.submission_deadline.isoformat()} has passed — "
            "upload rejected (hard deadline lock)"
        )

    if len(plaintext) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"Document size {len(plaintext)} bytes exceeds maximum "
            f"{MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
        )

    file_sha256 = hashlib.sha256(plaintext).hexdigest()
    ciphertext, nonce, tag = encrypt_document(plaintext, key)

    doc = BidDocument(
        bid_id=bid_id,
        document_type=document_type,
        filename=filename,
        encrypted_data=ciphertext,
        iv=nonce,
        tag=tag,
        key_id=key_id,
        file_sha256=file_sha256,
    )
    session.add(doc)
    session.flush()

    append_audit(
        session,
        entity_type="bid_document",
        entity_id=doc.id,
        action="document_uploaded",
        actor=actor,
        payload={
            "bid_id": bid_id,
            "document_type": document_type,
            "filename": filename,
            "file_sha256": file_sha256,
        },
    )

    return UploadResult(
        bid_document_id=doc.id,
        file_sha256=file_sha256,
        document_type=document_type,
    )


def lock_bids_at_deadline(package_id: int, actor: str, session: Session) -> int:
    """Lock all submitted bids once the deadline passes. Returns count locked."""
    package = session.get(Package, package_id)
    now = datetime.now(timezone.utc)
    if now <= package.submission_deadline:
        return 0

    bids = (
        session.query(Bid)
        .filter(Bid.package_id == package_id, Bid.locked_at.is_(None))
        .all()
    )
    for bid in bids:
        bid.locked_at = now

    append_audit(
        session,
        entity_type="package",
        entity_id=package_id,
        action="bids_locked_at_deadline",
        actor=actor,
        payload={"locked_count": len(bids), "deadline": package.submission_deadline.isoformat()},
    )
    return len(bids)


# ── Q&A broadcast ─────────────────────────────────────────────────────────────


@dataclass
class QABroadcast:
    package_id: int
    question: str
    answer: str
    recipients: list[str]  # contact emails of shortlisted suppliers


def broadcast_qa(
    package_id: int,
    question: str,
    answer: str,
    actor: str,
    session: Session,
) -> QABroadcast:
    """Record a Q&A and return the list of shortlisted supplier emails to notify."""
    shortlisted = (
        session.query(EOIResponse)
        .filter(
            EOIResponse.package_id == package_id,
            EOIResponse.is_shortlisted.is_(True),
        )
        .all()
    )
    from ea_pip.models import Supplier

    recipients = []
    for eoi in shortlisted:
        supplier = session.get(Supplier, eoi.supplier_id)
        if supplier and supplier.contact_email:
            recipients.append(supplier.contact_email)

    append_audit(
        session,
        entity_type="package",
        entity_id=package_id,
        action="qa_broadcast",
        actor=actor,
        payload={
            "question": question,
            "answer": answer,
            "recipient_count": len(recipients),
        },
    )

    return QABroadcast(
        package_id=package_id,
        question=question,
        answer=answer,
        recipients=recipients,
    )
