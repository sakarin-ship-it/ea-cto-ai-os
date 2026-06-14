"""FastAPI application for EA-DIS.

Endpoints:
  POST /ingest          — upload + process a document
  POST /search          — semantic search
  POST /query           — RAG question answering
  GET  /obligations     — list obligations
  POST /reclassify/{id} — manually set doc type (REVIEWER+ only)

Auth: JWT Bearer; 4 roles (ADMIN, REVIEWER, OPERATOR, VIEWER).
Privacy: enforced at pipeline level; API never exposes raw text of sensitive docs to callers.
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ea_dis.auth import (
    TokenPayload,
    create_access_token,
    get_current_user,
    require_role,
)
from ea_dis.constants import DocStatus, DocType, Role
from ea_dis.db import get_db
from ea_dis.models import Document, Obligation
from ea_dis.pipeline.ingest import ingest_document, reclassify_document
from ea_dis.rag import answer_with_citations

app = FastAPI(title="EA-DIS Document Intelligence System", version="0.1.0")

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str
    password: str


# Demo in-memory users — real deployment reads from DB / env
_DEMO_USERS: dict[str, dict] = {
    os.environ.get("EA_DIS_ADMIN_USER", "admin"): {
        "password": os.environ.get("EA_DIS_ADMIN_PASS", "changeme"),
        "role": Role.ADMIN,
    },
}


@app.post("/token")
def login(body: LoginRequest):
    user = _DEMO_USERS.get(body.username)
    if not user or user["password"] != body.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad credentials")
    token = create_access_token(body.username, user["role"])
    return {"access_token": token, "token_type": "bearer"}


# ---------------------------------------------------------------------------
# /ingest
# ---------------------------------------------------------------------------

class IngestResponse(BaseModel):
    doc_id: int
    filename: str
    doc_type: Optional[str]
    confidence: Optional[float]
    status: str
    message: str


@app.post("/ingest", response_model=IngestResponse)
def ingest(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_role(Role.OPERATOR)),
):
    suffix = os.path.splitext(file.filename or "doc.bin")[1] or ".bin"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file.file.read())
        tmp_path = tmp.name

    try:
        doc = ingest_document(db, tmp_path, actor=user.sub)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    return IngestResponse(
        doc_id=doc.id,
        filename=doc.filename,
        doc_type=doc.doc_type,
        confidence=doc.confidence,
        status=doc.status,
        message=(
            "Document queued for manual review (confidence below threshold)."
            if doc.status == DocStatus.PENDING_REVIEW.value
            else "Document ingested and indexed."
        ),
    )


# ---------------------------------------------------------------------------
# /search
# ---------------------------------------------------------------------------

class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class SearchHit(BaseModel):
    doc_id: int
    chunk_index: int
    text: str
    score: float


class SearchResponse(BaseModel):
    hits: list[SearchHit]


@app.post("/search", response_model=SearchResponse)
def search(
    body: SearchRequest,
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    from ea_dis.rag import _retrieve
    hits = _retrieve(db, body.query, top_k=body.top_k)
    return SearchResponse(hits=[SearchHit(**h) for h in hits])


# ---------------------------------------------------------------------------
# /query (RAG)
# ---------------------------------------------------------------------------

class QueryRequest(BaseModel):
    question: str
    top_k: int = 5


class QueryResponse(BaseModel):
    answer: str
    sources: list[str]


@app.post("/query", response_model=QueryResponse)
def query(
    body: QueryRequest,
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    result = answer_with_citations(db, body.question, top_k=body.top_k)
    return QueryResponse(answer=result.answer, sources=result.sources)


# ---------------------------------------------------------------------------
# /obligations
# ---------------------------------------------------------------------------

class ObligationOut(BaseModel):
    id: int
    document_id: int
    description: str
    due_date: Optional[str]
    responsible_party: Optional[str]
    status: str


@app.get("/obligations", response_model=list[ObligationOut])
def list_obligations(
    doc_id: Optional[int] = Query(None),
    ob_status: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    q = select(Obligation)
    if doc_id is not None:
        q = q.where(Obligation.document_id == doc_id)
    if ob_status:
        q = q.where(Obligation.status == ob_status)
    rows = db.execute(q).scalars().all()
    return [
        ObligationOut(
            id=ob.id,
            document_id=ob.document_id,
            description=ob.description,
            due_date=ob.due_date.isoformat() if ob.due_date else None,
            responsible_party=ob.responsible_party,
            status=ob.status,
        )
        for ob in rows
    ]


# ---------------------------------------------------------------------------
# /reclassify
# ---------------------------------------------------------------------------

class ReclassifyRequest(BaseModel):
    doc_type: str


class ReclassifyResponse(BaseModel):
    doc_id: int
    new_doc_type: str
    status: str


@app.post("/reclassify/{doc_id}", response_model=ReclassifyResponse)
def reclassify(
    doc_id: int,
    body: ReclassifyRequest,
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(require_role(Role.REVIEWER)),
):
    try:
        DocType(body.doc_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid doc_type: {body.doc_type}")

    doc = reclassify_document(db, doc_id, body.doc_type, actor=user.sub)
    return ReclassifyResponse(doc_id=doc.id, new_doc_type=doc.doc_type, status=doc.status)


# ---------------------------------------------------------------------------
# /documents (list)
# ---------------------------------------------------------------------------

class DocumentOut(BaseModel):
    id: int
    filename: str
    doc_type: Optional[str]
    confidence: Optional[float]
    status: str
    page_count: Optional[int]
    created_at: str


@app.get("/documents", response_model=list[DocumentOut])
def list_documents(
    status_filter: Optional[str] = Query(None, alias="status"),
    db: Session = Depends(get_db),
    user: TokenPayload = Depends(get_current_user),
):
    q = select(Document)
    if status_filter:
        q = q.where(Document.status == status_filter)
    docs = db.execute(q).scalars().all()
    return [
        DocumentOut(
            id=d.id,
            filename=d.filename,
            doc_type=d.doc_type,
            confidence=d.confidence,
            status=d.status,
            page_count=d.page_count,
            created_at=d.created_at.isoformat(),
        )
        for d in docs
    ]
