"""FastAPI application for EA-PIP Procurement Intelligence Platform."""
from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Annotated, Literal, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Security, UploadFile
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from ea_pip.award import (
    accept_award,
    check_and_expire,
    create_award,
    reject_award,
    trigger_fallback,
)
from ea_pip.bid_portal import broadcast_qa, lock_bids_at_deadline, upload_bid_document
from ea_pip.rfx_generator import generate_rfx
from ea_pip.compliance_checker import run_compliance
from ea_pip.constants import PIP_API_KEY_ENV
from ea_pip.db import get_session, init_schema
from ea_pip.models import (
    AuditLog,
    Bid,
    EOIResponse,
    Package,
    append_audit,
)
from ea_pip.scoring_engine import (
    ScoreInput,
    aggregate_scores,
    get_evaluator_scores,
    submit_evaluation,
)
from ea_pip.supplier_registry import refresh_dbd_status, register_supplier
from ea_pip.tier1_autoselect import autoselect

logger = logging.getLogger(__name__)

# ── Authentication ────────────────────────────────────────────────────────────

_api_key_scheme = APIKeyHeader(name="X-API-Key", auto_error=True)


def _verify_api_key(x_api_key: str = Security(_api_key_scheme)) -> str:
    expected = os.environ.get(PIP_API_KEY_ENV, "")
    if not expected:
        raise HTTPException(503, f"{PIP_API_KEY_ENV} not configured on server")
    if not secrets.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(401, "Invalid API key")
    return x_api_key


def _get_evaluator_id(
    x_evaluator_id: Annotated[str, Header(alias="X-Evaluator-Id")],
) -> str:
    """Evaluator identity from header — never a self-asserted query param."""
    return x_evaluator_id


# All routes require API key authentication.
app = FastAPI(
    title="EA-PIP Procurement Intelligence Platform",
    version="0.1.0",
    dependencies=[Depends(_verify_api_key)],
)

SessionDep = Annotated[Session, Depends(get_session)]


@app.on_event("startup")
def startup() -> None:
    init_schema()


# ── Suppliers ─────────────────────────────────────────────────────────────────


class SupplierCreate(BaseModel):
    name_en: str
    tax_id: str
    contact_email: str
    name_th: str = ""
    contact_phone: str = ""
    address_en: str = ""
    address_th: str = ""

    @field_validator("tax_id")
    @classmethod
    def tax_id_thai_tin(cls, v: str) -> str:
        if not re.match(r"^\d{13}$", v):
            raise ValueError("tax_id must be exactly 13 digits (Thai TIN format)")
        return v


@app.post("/suppliers", status_code=201)
def create_supplier(body: SupplierCreate, session: SessionDep):
    try:
        supplier = register_supplier(
            name_en=body.name_en,
            tax_id=body.tax_id,
            contact_email=body.contact_email,
            actor="api",
            session=session,
            name_th=body.name_th,
            contact_phone=body.contact_phone,
            address_en=body.address_en,
            address_th=body.address_th,
        )
        session.commit()
        return {"id": supplier.id, "dbd_status": supplier.dbd_status}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/suppliers/{supplier_id}/verify")
def verify_supplier(supplier_id: int, session: SessionDep):
    try:
        supplier = refresh_dbd_status(supplier_id, actor="api", session=session)
        session.commit()
        return {"dbd_status": supplier.dbd_status, "dbd_verified_at": supplier.dbd_verified_at}
    except ValueError as exc:
        raise HTTPException(404, str(exc))


# ── Packages ──────────────────────────────────────────────────────────────────


class PackageCreate(BaseModel):
    package_no: str
    title_en: str
    title_th: str = ""
    procurement_tier: Literal["TIER2", "TIER3"]
    engineer_estimate_satang: int
    submission_deadline: datetime
    scope_en: str = Field(default="", max_length=2000)
    scope_th: str = Field(default="", max_length=2000)

    @field_validator("package_no")
    @classmethod
    def package_no_safe(cls, v: str) -> str:
        """Prevent path traversal: only alphanumerics, hyphens, underscores."""
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,98}$", v):
            raise ValueError(
                "package_no must be 1-99 characters: alphanumerics, hyphens, underscores; "
                "must start with alphanumeric"
            )
        return v


@app.post("/packages", status_code=201)
def create_package(body: PackageCreate, session: SessionDep):
    pkg = Package(
        package_no=body.package_no,
        title_en=body.title_en,
        title_th=body.title_th,
        procurement_tier=body.procurement_tier,
        engineer_estimate_satang=body.engineer_estimate_satang,
        submission_deadline=body.submission_deadline,
        scope_en=body.scope_en,
        scope_th=body.scope_th,
    )
    session.add(pkg)
    session.flush()
    append_audit(
        session,
        entity_type="package",
        entity_id=pkg.id,
        action="package_created",
        actor="api",
        payload={"package_no": body.package_no},
    )
    session.commit()
    return {"id": pkg.id, "package_no": pkg.package_no}


class QAPost(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=4000)


@app.post("/packages/{package_id}/qa")
def post_qa(package_id: int, body: QAPost, session: SessionDep):
    result = broadcast_qa(package_id, body.question, body.answer, actor="api", session=session)
    session.commit()
    return {"recipient_count": len(result.recipients), "recipients": result.recipients}


class EOISubmit(BaseModel):
    supplier_id: int
    notes: str = Field(default="", max_length=1000)


@app.post("/packages/{package_id}/eoi", status_code=201)
def submit_eoi(package_id: int, body: EOISubmit, session: SessionDep):
    pkg = session.get(Package, package_id)
    if pkg is None:
        raise HTTPException(404, f"Package {package_id} not found")
    eoi = EOIResponse(package_id=package_id, supplier_id=body.supplier_id, notes=body.notes)
    session.add(eoi)
    session.flush()
    append_audit(
        session,
        entity_type="eoi",
        entity_id=eoi.id,
        action="eoi_submitted",
        actor="api",
        payload={"package_id": package_id, "supplier_id": body.supplier_id},
    )
    session.commit()
    return {"eoi_id": eoi.id}


@app.post("/packages/{package_id}/eoi/{eoi_id}/shortlist")
def shortlist_supplier(package_id: int, eoi_id: int, session: SessionDep):
    eoi = session.get(EOIResponse, eoi_id)
    if eoi is None or eoi.package_id != package_id:
        raise HTTPException(404, "EOI not found")
    eoi.is_shortlisted = True
    append_audit(
        session,
        entity_type="eoi",
        entity_id=eoi_id,
        action="supplier_shortlisted",
        actor="api",
        payload={},
    )
    session.commit()
    return {"eoi_id": eoi_id, "is_shortlisted": True}


class RFxRequest(BaseModel):
    template: str = Field(max_length=50)  # "RFP", "RFQ", "IFB", etc.


@app.post("/packages/{package_id}/rfx", status_code=201)
def generate_package_rfx(package_id: int, body: RFxRequest, session: SessionDep):
    output_dir = os.environ.get("RFX_OUTPUT_DIR", "rfx_output")
    try:
        result = generate_rfx(
            package_id, body.template, output_dir, actor="api", session=session
        )
        session.commit()
        return {"docx_path": result.docx_path, "pdf_path": result.pdf_path}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/packages/{package_id}/lock")
def lock_bids(package_id: int, session: SessionDep):
    count = lock_bids_at_deadline(package_id, actor="api", session=session)
    session.commit()
    return {"locked_count": count}


@app.post("/packages/{package_id}/autoselect")
def tier1_autoselect(package_id: int, session: SessionDep):
    try:
        result = autoselect(package_id, actor="api", session=session)
        session.commit()
        return {
            "selected_bid_id": result.selected_bid_id,
            "bid_amount_satang": result.bid_amount_satang,
            "po_reference": result.po_reference,
        }
    except ValueError as exc:
        raise HTTPException(422, str(exc))


# ── Bids ──────────────────────────────────────────────────────────────────────


class BidCreate(BaseModel):
    package_id: int
    supplier_id: int
    bid_amount_satang: int
    bid_bond_amount_satang: int = 0


@app.post("/bids", status_code=201)
def create_bid(body: BidCreate, session: SessionDep):
    pkg = session.get(Package, body.package_id)
    if pkg is None:
        raise HTTPException(404, f"Package {body.package_id} not found")
    if datetime.now(timezone.utc) > pkg.submission_deadline:
        raise HTTPException(422, "Submission deadline has passed — bid rejected")

    bid = Bid(
        package_id=body.package_id,
        supplier_id=body.supplier_id,
        bid_amount_satang=body.bid_amount_satang,
        bid_bond_amount_satang=body.bid_bond_amount_satang,
    )
    session.add(bid)
    session.flush()
    append_audit(
        session,
        entity_type="bid",
        entity_id=bid.id,
        action="bid_submitted",
        actor="api",
        payload={"package_id": body.package_id, "supplier_id": body.supplier_id},
    )
    session.commit()
    return {"id": bid.id}


@app.post("/bids/{bid_id}/documents", status_code=201)
async def upload_document(
    bid_id: int,
    session: SessionDep,
    document_type: str = Form(...),
    key_id: str = Form(...),
    file: UploadFile = File(...),
):
    """Upload an AES-256-GCM encrypted bid document. Key loaded from BID_DOC_KEY_HEX env."""
    key_hex = os.environ.get("BID_DOC_KEY_HEX", "")
    if len(key_hex) != 64:
        raise HTTPException(503, "BID_DOC_KEY_HEX not configured (must be 64 hex chars = 32 bytes)")
    key = bytes.fromhex(key_hex)
    plaintext = await file.read()
    try:
        result = upload_bid_document(
            bid_id=bid_id,
            document_type=document_type,
            filename=file.filename or "upload",
            plaintext=plaintext,
            key=key,
            key_id=key_id,
            actor="api",
            session=session,
        )
        session.commit()
        return {"bid_document_id": result.bid_document_id, "file_sha256": result.file_sha256}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/bids/{bid_id}/compliance")
def check_compliance(bid_id: int, session: SessionDep):
    try:
        result = run_compliance(bid_id, actor="api", session=session)
        session.commit()
        return {
            "is_compliant": result.is_compliant,
            "is_alb_flagged": result.is_alb_flagged,
            "notes": result.notes,
        }
    except ValueError as exc:
        raise HTTPException(404, str(exc))


# ── Evaluations ───────────────────────────────────────────────────────────────


class EvaluationSubmit(BaseModel):
    # evaluator_id comes from X-Evaluator-Id header, not the request body
    technical_text: str = Field(max_length=8000)
    experience_score: int
    personnel_score: int
    financial_score: int


@app.post("/bids/{bid_id}/evaluate")
def evaluate_bid(
    bid_id: int,
    body: EvaluationSubmit,
    evaluator_id: Annotated[str, Depends(_get_evaluator_id)],
    session: SessionDep,
):
    try:
        ev = submit_evaluation(
            bid_id=bid_id,
            evaluator_id=evaluator_id,
            inputs=ScoreInput(
                technical_text=body.technical_text,
                experience_score=body.experience_score,
                personnel_score=body.personnel_score,
                financial_score=body.financial_score,
            ),
            actor=evaluator_id,
            session=session,
        )
        session.commit()
        return {"evaluation_id": ev.id, "is_locked": ev.is_locked}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/bids/{bid_id}/scores")
def get_scores(
    bid_id: int,
    evaluator_id: Annotated[str, Depends(_get_evaluator_id)],
    session: SessionDep,
):
    """BLIND: evaluator_id from X-Evaluator-Id header; only that evaluator's scores returned."""
    scores = get_evaluator_scores(bid_id, evaluator_id, session)
    return {
        "scores": [
            {"criterion": s.criterion, "raw_score": s.raw_score, "is_nlp_scored": s.is_nlp_scored}
            for s in scores
        ]
    }


@app.get("/packages/{package_id}/scores/aggregate")
def get_aggregate_scores(package_id: int, session: SessionDep):
    results = aggregate_scores(package_id, session)
    session.commit()
    return {
        "scores": [
            {
                "bid_id": r.bid_id,
                "evaluator_id": r.evaluator_id,
                "weighted_total": r.weighted_total,
                "is_outlier": r.is_outlier,
                "z_score": r.z_score,
            }
            for r in results
        ]
    }


# ── Awards ────────────────────────────────────────────────────────────────────


class AwardCreate(BaseModel):
    preferred_bid_id: int
    fallback_bid_id: Optional[int] = None


@app.post("/packages/{package_id}/award", status_code=201)
def create_package_award(package_id: int, body: AwardCreate, session: SessionDep):
    try:
        letter = create_award(
            package_id=package_id,
            preferred_bid_id=body.preferred_bid_id,
            actor="api",
            session=session,
            fallback_bid_id=body.fallback_bid_id,
        )
        session.commit()
        return {
            "award_id": letter.award_id,
            "letter_ref": letter.letter_ref,
            "expires_at": letter.expires_at.isoformat(),
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/awards/{award_id}/accept")
def accept(award_id: int, session: SessionDep):
    try:
        letter = accept_award(award_id, actor="api", session=session)
        session.commit()
        return {"status": letter.status}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/awards/{award_id}/reject")
def reject(award_id: int, session: SessionDep):
    try:
        letter = reject_award(award_id, actor="api", session=session)
        session.commit()
        return {"status": letter.status if letter else "REJECTED_NO_FALLBACK"}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/awards/{award_id}/fallback")
def fallback(award_id: int, session: SessionDep):
    try:
        letter = trigger_fallback(award_id, actor="api", session=session)
        session.commit()
        return {
            "award_id": letter.award_id,
            "status": letter.status,
            "letter_ref": letter.letter_ref,
        }
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/awards/{award_id}/check_expiry")
def check_expiry(award_id: int, session: SessionDep):
    try:
        expired = check_and_expire(award_id, actor="api", session=session)
        session.commit()
        return {"expired": expired}
    except ValueError as exc:
        raise HTTPException(404, str(exc))


# ── Audit log ─────────────────────────────────────────────────────────────────


@app.get("/audit_log")
def get_audit_log(
    session: SessionDep,
    entity_type: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=1000),
):
    q = session.query(AuditLog).order_by(AuditLog.id.desc())
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    entries = q.limit(limit).all()
    return {
        "entries": [
            {
                "id": e.id,
                "entity_type": e.entity_type,
                "entity_id": e.entity_id,
                "action": e.action,
                "actor": e.actor,
                "created_at": e.created_at.isoformat(),
                "entry_hash": e.entry_hash,
            }
            for e in entries
        ]
    }
