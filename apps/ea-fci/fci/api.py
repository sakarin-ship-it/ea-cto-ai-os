"""FastAPI application for EA-FCI Financial Control & Intelligence."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from fci.db import get_session, init_schema
from fci.ld_calculator import calculate_ld
from fci.models import (
    AnomalyFlag,
    AuditLog,
    LDAccrual,
    Payment,
    PurchaseOrder,
    TACCertificate,
    append_audit,
)
from fci.tac_gate import check_tac_gate
from fci.three_way_match import match_by_ids

logger = logging.getLogger(__name__)

app = FastAPI(title="EA-FCI Financial Control & Intelligence", version="0.1.0")

SessionDep = Annotated[Session, Depends(get_session)]


@app.on_event("startup")
def startup() -> None:
    init_schema()


# ─────────────────────────────────────────────────────────────────────────────
# Purchase orders (created by EA-PIP tier-1 autoselect)
# ─────────────────────────────────────────────────────────────────────────────


class POCreate(BaseModel):
    po_number: str
    supplier: str
    total_satang: int
    currency: str = "THB"
    source: str = "EA-PIP"


@app.post("/purchase_orders", status_code=201)
def create_purchase_order(body: POCreate, session: SessionDep):
    po = PurchaseOrder(
        po_number=body.po_number,
        supplier=body.supplier,
        currency=body.currency,
        qty_ordered=Decimal("1"),
        unit_price_satang=body.total_satang,
        total_satang=body.total_satang,
        status="OPEN",
    )
    session.add(po)
    session.flush()
    append_audit(
        session,
        entity_type="purchase_order",
        entity_id=po.id,
        action="po_created",
        actor=body.source,
        payload={"po_number": body.po_number, "total_satang": body.total_satang},
    )
    session.commit()
    return {"id": po.id, "po_number": po.po_number}


# ─────────────────────────────────────────────────────────────────────────────
# Three-way match
# ─────────────────────────────────────────────────────────────────────────────


@app.post("/match/{invoice_id}")
def match_invoice(invoice_id: int, po_id: int, grn_id: int, session: SessionDep):
    try:
        result = match_by_ids(po_id=po_id, grn_id=grn_id, invoice_id=invoice_id, session=session)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    append_audit(
        session,
        entity_type="invoice",
        entity_id=invoice_id,
        action="three_way_match",
        actor="system",
        payload={"po_id": po_id, "grn_id": grn_id, "status": result.status},
    )
    session.commit()
    return {
        "status": result.status,
        "qty_ok": result.qty_ok,
        "price_ok": result.price_ok,
        "reason": result.reason,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Payment initiation (TAC gate enforced here)
# ─────────────────────────────────────────────────────────────────────────────


class PaymentInitRequest(BaseModel):
    invoice_id: int
    amount_satang: int
    approved_by: str


@app.post("/payment/initiate")
def initiate_payment(req: PaymentInitRequest, session: SessionDep):
    try:
        gate = check_tac_gate(req.invoice_id, session)
    except ValueError as exc:
        raise HTTPException(404, str(exc))

    payment = Payment(
        invoice_id=req.invoice_id,
        amount_satang=req.amount_satang,
        status="BLOCKED" if gate.blocked else "APPROVED",
        block_reason=gate.block_reason,
        approved_by=req.approved_by,
        tac_id=gate.tac_id,
    )
    session.add(payment)
    session.flush()

    append_audit(
        session,
        entity_type="payment",
        entity_id=payment.id,
        action="initiate",
        actor=req.approved_by,
        payload={"blocked": gate.blocked, "block_reason": gate.block_reason},
    )
    session.commit()

    if gate.blocked:
        return {"status": "BLOCKED", "block_reason": gate.block_reason, "payment_id": payment.id}
    return {"status": "APPROVED", "payment_id": payment.id}


# ─────────────────────────────────────────────────────────────────────────────
# TAC certificates
# ─────────────────────────────────────────────────────────────────────────────


class TACUploadRequest(BaseModel):
    po_id: int
    dis_doc_id: str
    milestone_ref: str
    signed_by: str
    cto_signature_hash: str
    valid_from: str   # ISO-8601


@app.post("/tac")
def upload_tac(req: TACUploadRequest, session: SessionDep):
    tac = TACCertificate(
        po_id=req.po_id,
        dis_doc_id=req.dis_doc_id,
        milestone_ref=req.milestone_ref,
        cto_signature_hash=req.cto_signature_hash,
        signed_by=req.signed_by,
        signed_at=datetime.now(timezone.utc),
        valid_from=datetime.fromisoformat(req.valid_from),
        is_approved=True,
    )
    session.add(tac)
    session.flush()

    append_audit(
        session,
        entity_type="tac_certificate",
        entity_id=tac.id,
        action="upload",
        actor=req.signed_by,
        payload={"po_id": req.po_id, "dis_doc_id": req.dis_doc_id},
    )
    session.commit()
    return {"tac_id": tac.id, "po_id": req.po_id}


@app.get("/tac/{po_id}")
def get_tac(po_id: int, session: SessionDep):
    tac = (
        session.query(TACCertificate)
        .filter(TACCertificate.po_id == po_id, TACCertificate.is_approved.is_(True))
        .first()
    )
    if not tac:
        raise HTTPException(404, f"No approved TAC for PO {po_id}")
    return {
        "tac_id": tac.id,
        "milestone_ref": tac.milestone_ref,
        "signed_by": tac.signed_by,
        "dis_doc_id": tac.dis_doc_id,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Liquidated damages
# ─────────────────────────────────────────────────────────────────────────────


class LDRequest(BaseModel):
    po_id: int
    contract_value_satang: int
    daily_rate_bps: int
    delay_days: int
    cap_pct: int


@app.post("/ld/calculate")
def ld_calculate(req: LDRequest, session: SessionDep):
    try:
        result = calculate_ld(
            contract_value_satang=req.contract_value_satang,
            daily_rate_bps=req.daily_rate_bps,
            delay_days=req.delay_days,
            cap_pct=req.cap_pct,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    accrual = LDAccrual(
        po_id=req.po_id,
        contract_value_satang=req.contract_value_satang,
        daily_rate_bps=req.daily_rate_bps,
        cap_pct=req.cap_pct,
        delay_days=req.delay_days,
        raw_ld_satang=result.raw_ld_satang,
        cap_satang=result.cap_satang,
        accrued_satang=result.accrued_satang,
        is_capped=result.is_capped,
        calculation_date=datetime.now(timezone.utc),
    )
    session.add(accrual)
    session.flush()

    append_audit(
        session,
        entity_type="ld_accrual",
        entity_id=accrual.id,
        action="calculate",
        actor="system",
        payload={"po_id": req.po_id, "accrued_satang": result.accrued_satang},
    )
    session.commit()
    return {
        "accrual_id": accrual.id,
        "accrued_satang": result.accrued_satang,
        "cap_satang": result.cap_satang,
        "raw_ld_satang": result.raw_ld_satang,
        "is_capped": result.is_capped,
        "daily_ld_satang": result.daily_ld_satang,
    }


# ─────────────────────────────────────────────────────────────────────────────
# FX
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/fx/{currency}")
def get_fx(currency: str, date: str | None = Query(None)):
    from fci.fx_monitor import extract_mid_rate, fetch_bot_rate

    try:
        data = fetch_bot_rate(currency.upper(), date_str=date)
        rate = extract_mid_rate(data)
        return {"currency_pair": f"{currency.upper()}THB", "rate": str(rate), "source": "BOT"}
    except Exception as exc:
        raise HTTPException(502, f"BOT API error: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Anomalies
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/anomalies")
def list_anomalies(session: SessionDep, limit: int = Query(100)):
    flags = (
        session.query(AnomalyFlag)
        .filter(AnomalyFlag.is_anomaly.is_(True))
        .limit(limit)
        .all()
    )
    return [
        {
            "id": f.id,
            "entity_type": f.entity_type,
            "entity_id": f.entity_id,
            "score": float(f.score),
            "features": f.features,
        }
        for f in flags
    ]


# ─────────────────────────────────────────────────────────────────────────────
# E-sign / ETDA Level-2
# ─────────────────────────────────────────────────────────────────────────────


class RegisterBeginRequest(BaseModel):
    actor: str


@app.post("/esign/register-begin")
def esign_register_begin(req: RegisterBeginRequest):
    from fci.esign import get_registration_options

    return get_registration_options(req.actor)


class RegisterCompleteRequest(BaseModel):
    actor: str
    credential: dict


@app.post("/esign/register-complete")
def esign_register_complete(req: RegisterCompleteRequest):
    from fci.esign import complete_registration

    ok = complete_registration(req.actor, req.credential)
    if not ok:
        raise HTTPException(400, "Registration failed or no pending challenge for this actor")
    return {"status": "registered", "actor": req.actor}


class SignBeginRequest(BaseModel):
    po_id: int
    milestone_ref: str
    dis_doc_id: str
    actor: str
    amount_display: str = ""


@app.post("/esign/sign-begin")
def esign_sign_begin(req: SignBeginRequest):
    from fci.esign import get_assertion_options

    token, options = get_assertion_options(
        req.po_id, req.milestone_ref, req.dis_doc_id, req.actor
    )
    return {
        "token": token,
        "sign_url": f"/esign/sign/{token}?amount={req.amount_display}",
        "options": options,
    }


@app.get("/esign/sign/{token}", response_class=HTMLResponse)
def esign_sign_page(token: str, amount: str = ""):
    from fci.esign import _pending_assertions, render_sign_page

    pending = _pending_assertions.get(token)
    if not pending:
        raise HTTPException(404, "Token not found or expired")
    return render_sign_page(token, pending["options"], amount_display=amount)


class SignCompleteRequest(BaseModel):
    token: str
    assertion: dict


@app.post("/esign/sign-complete")
def esign_sign_complete(req: SignCompleteRequest, session: SessionDep):
    from fci.esign import complete_assertion

    try:
        result = complete_assertion(req.token, req.assertion)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    tac = TACCertificate(
        po_id=result.po_id,
        dis_doc_id=result.dis_doc_id,
        milestone_ref=result.milestone_ref,
        cto_signature_hash=result.signature_hash,
        signed_by=result.actor,
        signed_at=datetime.fromisoformat(result.signed_at),
        valid_from=datetime.fromisoformat(result.signed_at),
        is_approved=True,
    )
    session.add(tac)
    session.flush()

    append_audit(
        session,
        entity_type="tac_certificate",
        entity_id=tac.id,
        action="esign_complete",
        actor=result.actor,
        payload={"po_id": result.po_id, "milestone_ref": result.milestone_ref},
    )
    session.commit()
    return {"status": "signed", "tac_id": tac.id, "signed_at": result.signed_at}


# ─────────────────────────────────────────────────────────────────────────────
# Audit log
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/audit_log")
def get_audit_log(
    session: SessionDep,
    entity_type: str | None = None,
    limit: int = Query(100),
):
    q = session.query(AuditLog)
    if entity_type:
        q = q.filter(AuditLog.entity_type == entity_type)
    entries = q.order_by(AuditLog.id.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "entity_type": e.entity_type,
            "entity_id": e.entity_id,
            "action": e.action,
            "actor": e.actor,
            "entry_hash": e.entry_hash,
            "created_at": e.created_at.isoformat(),
        }
        for e in entries
    ]
