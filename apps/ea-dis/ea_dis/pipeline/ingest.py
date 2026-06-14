"""Document ingestion pipeline: parse → classify → chunk → embed → store.

M5 rules:
- Process ONE document at a time (no parallel model calls).
- Release the model between batches.
- bge-m3 is the only resident model; release chat model after translation/classification.
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy.orm import Session

from ea_dis.constants import DocStatus
from ea_dis.models import DocChunk, Document, append_audit
from ea_dis.pipeline.chunker import chunk_text
from ea_dis.pipeline.classifier import classify_document
from ea_dis.pipeline.embedder import embed_batch
from ea_dis.pipeline.parser import parse_file

logger = logging.getLogger(__name__)


def ingest_document(
    db: Session,
    file_path: str,
    actor: str = "system",
) -> Document:
    """Full pipeline for one document. Returns the persisted Document row."""
    path = Path(file_path)
    filename = path.name

    # 1. Parse
    text, page_count, language = parse_file(file_path)

    # 2. Classify (sequential; model released after call)
    cls = classify_document(text)

    # 3. Create DB record
    doc = Document(
        filename=filename,
        original_language=language,
        doc_type=cls.doc_type.value,
        confidence=cls.confidence,
        status=cls.status.value,
        page_count=page_count,
        raw_text=text,
    )
    db.add(doc)
    db.flush()  # get doc.id

    append_audit(
        db,
        entity_type="document",
        entity_id=str(doc.id),
        action="INGEST",
        payload={
            "filename": filename,
            "doc_type": cls.doc_type.value,
            "confidence": cls.confidence,
            "status": cls.status.value,
            "language": language,
        },
        actor=actor,
    )

    # 4. Chunk (only for ACTIVE documents; PENDING_REVIEW skips embedding)
    if cls.status == DocStatus.ACTIVE:
        _chunk_and_embed(db, doc, text)

    db.commit()
    logger.info(
        "Ingested doc=%d filename=%r type=%s confidence=%.2f status=%s",
        doc.id, filename, cls.doc_type.value, cls.confidence, cls.status.value,
    )
    return doc


def _chunk_and_embed(db: Session, doc: Document, text: str) -> None:
    chunks = chunk_text(text)
    if not chunks:
        return

    # Embed sequentially (M5: no parallel model calls)
    vectors = embed_batch(chunks)

    for idx, (chunk_text_val, vec) in enumerate(zip(chunks, vectors)):
        chunk = DocChunk(
            document_id=doc.id,
            chunk_index=idx,
            text=chunk_text_val,
            embedding=vec if any(v != 0.0 for v in vec) else None,
        )
        db.add(chunk)


def reclassify_document(
    db: Session,
    doc_id: int,
    new_doc_type: str,
    actor: str = "system",
) -> Document:
    """Manually reclassify a document (used for PENDING_REVIEW items)."""
    doc = db.get(Document, doc_id)
    if doc is None:
        raise ValueError(f"Document {doc_id} not found")

    old_type = doc.doc_type
    doc.doc_type = new_doc_type
    doc.status = DocStatus.ACTIVE.value
    doc.confidence = 1.0

    append_audit(
        db,
        entity_type="document",
        entity_id=str(doc_id),
        action="RECLASSIFY",
        payload={"old_type": old_type, "new_type": new_doc_type},
        actor=actor,
    )

    # Now embed if chunks don't exist yet
    existing_chunks = db.query(DocChunk).filter(DocChunk.document_id == doc_id).count()
    if existing_chunks == 0 and doc.raw_text:
        _chunk_and_embed(db, doc, doc.raw_text)

    db.commit()
    return doc
