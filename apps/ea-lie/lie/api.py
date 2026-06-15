"""FastAPI application for EA-LIE Legal Intelligence Engine."""
from __future__ import annotations

import base64
import logging
import os
from datetime import date
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="EA-LIE Legal Intelligence Engine", version="0.1.0")

_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


# ─────────────────────────────────────────────────────────────────────────────
# NDA
# ─────────────────────────────────────────────────────────────────────────────


class NDARequest(BaseModel):
    nda_type: str                           # unilateral | mutual | employee | vendor
    disclosing_party: str
    receiving_party: str
    purpose: str
    duration_years: int
    confidentiality_period_years: int = 3
    governing_law: str = "Thailand"


@app.post("/nda")
def generate_nda(req: NDARequest):
    """Generate bilingual EN/TH NDA docx.
    Optional clauses selected by Claude API (non-sensitive params only).
    Returns docx file download.
    """
    from lie.nda_generator import NDAGenerator, NDAParams, NDAType

    try:
        nda_type = NDAType(req.nda_type)
    except ValueError:
        raise HTTPException(400, f"Unknown nda_type '{req.nda_type}'. "
                            f"Valid: {[e.value for e in NDAType]}")

    params = NDAParams(
        nda_type=nda_type,
        disclosing_party=req.disclosing_party,
        receiving_party=req.receiving_party,
        purpose=req.purpose,
        duration_years=req.duration_years,
        confidentiality_period_years=req.confidentiality_period_years,
        governing_law=req.governing_law,
    )
    try:
        docx_bytes = NDAGenerator().generate(params)
    except Exception as exc:
        logger.error("NDA generation failed: %s", exc)
        raise HTTPException(500, f"NDA generation failed: {exc}")

    filename = f"NDA_{nda_type.value}_{req.disclosing_party[:20].replace(' ','_')}.docx"
    return Response(
        content=docx_bytes,
        media_type=_DOCX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Contract drafting (qwen3-8b on-prem — all content stays local)
# ─────────────────────────────────────────────────────────────────────────────


class DraftRequest(BaseModel):
    contract_type: str          # nda | service_agreement | employment | license | construction | partnership
    context: dict[str, Any]    # parties, dates, amounts, scope — all sensitive, never cloud


@app.post("/contract/draft")
def draft_contract(req: DraftRequest):
    """Draft a contract using qwen3-8b on-prem (privacy rule: all content stays local).
    Returns docx file download.
    """
    from lie.contract_drafter import ContractDrafter, ContractType

    try:
        ct = ContractType(req.contract_type)
    except ValueError:
        raise HTTPException(400, f"Unknown contract_type '{req.contract_type}'. "
                            f"Valid: {[e.value for e in ContractType]}")

    try:
        result = ContractDrafter().draft(ct, req.context)
    except Exception as exc:
        logger.error("Contract draft failed: %s", exc)
        raise HTTPException(500, f"Contract draft failed: {exc}")

    filename = f"DRAFT_{ct.value}.docx"
    return Response(
        content=result.docx_bytes,
        media_type=_DOCX_MIME,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Contract review (qwen3-8b on-prem extraction + playbook scoring)
# ─────────────────────────────────────────────────────────────────────────────


class ReviewRequest(BaseModel):
    text: str               # extracted contract text; sensitive — never leaves this machine
    document_path: str = "" # server-side path (optional; ignored if text is provided)


class ReviewResponse(BaseModel):
    score: int
    rag: str
    reviewer_level: str
    gaps: list[str]
    findings: dict[str, Any]
    summary: str


@app.post("/contract/review", response_model=ReviewResponse)
def review_contract(req: ReviewRequest):
    """Review contract text against the Thai-law playbook.
    Score 0-100 (higher = more risk).  RAG + reviewer assignment returned.
    """
    from lie.review_engine import ReviewEngine

    llamaparse_key = os.getenv("LLAMAPARSE_API_KEY", "")
    engine = ReviewEngine(llamaparse_api_key=llamaparse_key)

    try:
        if req.text:
            result = engine.review_text(req.text)
        elif req.document_path:
            result = engine.review(req.document_path)
        else:
            raise HTTPException(400, "Provide 'text' or 'document_path'")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Contract review failed: %s", exc)
        raise HTTPException(500, f"Review failed: {exc}")

    return ReviewResponse(
        score=result.score,
        rag=result.rag.value,
        reviewer_level=result.reviewer_level.value,
        gaps=result.gaps,
        findings=result.findings,
        summary=result.summary,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Redline (tracked-style changes + mandatory AI-DRAFT watermark)
# ─────────────────────────────────────────────────────────────────────────────


class ChangeItem(BaseModel):
    original_text: str
    revised_text: str
    reason: str = ""
    clause_ref: str = ""


class RedlineRequest(BaseModel):
    original_docx_b64: str      # base64-encoded original docx
    changes: list[ChangeItem]


@app.post("/contract/redline")
def generate_redline(req: RedlineRequest):
    """Apply tracked-style changes to a docx and add the mandatory AI-DRAFT watermark.
    Input docx must be base64-encoded.  Returns redlined docx file download.
    """
    from lie.redline_generator import RedlineChange, RedlineGenerator

    try:
        original_bytes = base64.b64decode(req.original_docx_b64)
    except Exception:
        raise HTTPException(400, "original_docx_b64 is not valid base64")

    changes = [
        RedlineChange(
            original_text=c.original_text,
            revised_text=c.revised_text,
            reason=c.reason,
            clause_ref=c.clause_ref,
        )
        for c in req.changes
    ]

    try:
        result_bytes = RedlineGenerator().generate(original_bytes, changes)
    except Exception as exc:
        logger.error("Redline failed: %s", exc)
        raise HTTPException(500, f"Redline generation failed: {exc}")

    return Response(
        content=result_bytes,
        media_type=_DOCX_MIME,
        headers={"Content-Disposition": 'attachment; filename="REDLINE_AI_DRAFT.docx"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# FIDIC timebar
# ─────────────────────────────────────────────────────────────────────────────


@app.get("/fidic/editions")
def list_fidic_editions():
    """Return all supported FIDIC editions."""
    from lie.fidic_timebar import FIDICEdition

    return {"editions": [e.value for e in FIDICEdition]}


class FIDICDetectRequest(BaseModel):
    text: str


@app.post("/fidic/detect")
def detect_fidic_edition(req: FIDICDetectRequest):
    """Detect FIDIC edition from contract text keywords."""
    from lie.fidic_timebar import FIDICTimebar

    tb = FIDICTimebar.detect_edition(req.text)
    return {"edition": tb.edition.value, "clauses": tb.all_clauses()}


class FIDICDeadlineRequest(BaseModel):
    edition: str
    clause: str
    trigger_date: date
    contract_id: str = ""


@app.post("/fidic/deadline")
def create_fidic_deadline(req: FIDICDeadlineRequest):
    """Create a FIDIC deadline and return scheduled 14/7/1-day alerts.
    Safety net: always returns ≥1 alert (same-day if deadline is imminent).
    """
    from lie.fidic_timebar import FIDICEdition, FIDICTimebar

    try:
        edition = FIDICEdition(req.edition)
    except ValueError:
        raise HTTPException(400, f"Unknown edition '{req.edition}'")

    tb = FIDICTimebar(edition)
    deadline = tb.create_deadline(req.clause, req.trigger_date, req.contract_id)
    if deadline is None:
        raise HTTPException(
            404,
            f"Clause '{req.clause}' not found in {edition.value}. "
            f"Valid clauses: {tb.all_clauses()}",
        )

    alerts = tb.schedule_all_alerts(deadline)
    return {
        "clause": deadline.clause,
        "description": deadline.description,
        "edition": edition.value,
        "trigger_date": deadline.trigger_date.isoformat(),
        "deadline_date": deadline.deadline_date.isoformat(),
        "days_remaining": deadline.days_remaining(),
        "missed": deadline.missed(),
        "alerts": [
            {
                "days_before": a.days_before,
                "alert_date": a.alert_date.isoformat(),
                "description": a.description,
            }
            for a in alerts
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Obligation tracker
# ─────────────────────────────────────────────────────────────────────────────


class ObligationRequest(BaseModel):
    id: str
    contract_id: str
    description: str
    due_date: date
    parties: list[str] = []
    notification_channels: list[str] = []
    dispatch: bool = False      # False → compute only; True → dispatch to Celery


@app.post("/obligation/schedule")
def schedule_obligation(req: ObligationRequest):
    """Compute 90/60/30/7-day obligation alerts.
    Set dispatch=true to enqueue them in Celery (requires Redis).
    """
    from lie.obligation_tracker import Obligation, ObligationTracker

    obligation = Obligation(
        id=req.id,
        contract_id=req.contract_id,
        description=req.description,
        due_date=req.due_date,
        parties=req.parties,
        notification_channels=req.notification_channels,
    )
    tracker = ObligationTracker()

    if req.dispatch:
        try:
            task_ids = tracker.schedule(obligation)
        except Exception as exc:
            logger.error("Celery dispatch failed: %s", exc)
            raise HTTPException(503, f"Celery dispatch failed (Redis up?): {exc}")
        return {"obligation_id": req.id, "dispatched": True, "task_ids": task_ids}

    alerts = tracker.compute_alerts(obligation)
    return {
        "obligation_id": req.id,
        "dispatched": False,
        "alerts": [
            {
                "days_before_due": a.days_before_due,
                "alert_date": a.alert_date.isoformat(),
                "due_date": a.due_date.isoformat(),
            }
            for a in alerts
        ],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Breach monitor
# ─────────────────────────────────────────────────────────────────────────────


class BreachEventRequest(BaseModel):
    source: str                             # EA-FCI | EA-DIS | EA-PIP
    contract_id: str
    event_type: str
    description: str
    evidence_urls: list[str] = []
    obligations: list[dict[str, Any]] = []  # optional context for the notice


@app.post("/breach/event")
def report_breach_event(req: BreachEventRequest):
    """Generate a formal breach notice via qwen3-8b and send LINE alert.
    LINE_NOTIFY_TOKEN env var required for LINE delivery (skipped if unset).
    """
    from lie.breach_monitor import BreachEvent, BreachMonitor, EventSource

    try:
        source = EventSource(req.source)
    except ValueError:
        raise HTTPException(400, f"Unknown source '{req.source}'. "
                            f"Valid: {[e.value for e in EventSource]}")

    event = BreachEvent(
        source=source,
        contract_id=req.contract_id,
        event_type=req.event_type,
        description=req.description,
        evidence_urls=req.evidence_urls,
    )

    monitor = BreachMonitor()  # reads ALERT_IMESSAGE_RECIPIENT from env

    try:
        response = monitor.process_event(event, req.obligations)
    except Exception as exc:
        logger.error("Breach monitor failed: %s", exc)
        raise HTTPException(500, f"Breach processing failed: {exc}")

    return {
        "contract_id": response.contract_id,
        "notice_text": response.notice_text,
        "evidence_summary": response.evidence_summary,
        "alert_sent": response.alert_sent,
        "notice_generated": response.notice_generated,
    }
