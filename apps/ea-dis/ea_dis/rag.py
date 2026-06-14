"""RAG: answer_with_citations() using qwen3-8b on-prem + bge-m3 retrieval."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from ea_dis.pipeline.embedder import embed_text

logger = logging.getLogger(__name__)

_SHARED = Path(__file__).resolve().parents[3] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from lmstudio_client import PRIMARY_MODEL, chat_complete  # noqa: E402

_RAG_SYSTEM = """\
You are a document analyst for an engineering company. Answer the user's question
based ONLY on the provided document excerpts. For every factual claim cite the
source as [Doc-ID:chunk_index]. If the excerpts do not contain enough information
say "Insufficient information in the retrieved documents."

Format your response as:
ANSWER: <your answer with inline citations [Doc-ID:chunk_index]>
SOURCES: <comma-separated list of Doc-ID:chunk_index references used>"""

TOP_K = 5


class CitedAnswer:
    def __init__(self, answer: str, sources: list[str], excerpts: list[dict]) -> None:
        self.answer = answer
        self.sources = sources
        self.excerpts = excerpts  # list of {doc_id, chunk_index, text}

    def __repr__(self) -> str:
        return f"CitedAnswer(sources={self.sources!r})"


def answer_with_citations(db: Session, question: str, top_k: int = TOP_K) -> CitedAnswer:
    """Retrieve relevant chunks, then answer with qwen3-8b with inline citations."""
    excerpts = _retrieve(db, question, top_k)
    if not excerpts:
        return CitedAnswer(
            answer="Insufficient information in the retrieved documents.",
            sources=[],
            excerpts=[],
        )

    context_parts = [
        f"[Doc-{e['doc_id']}:{e['chunk_index']}]\n{e['text']}"
        for e in excerpts
    ]
    context = "\n\n---\n\n".join(context_parts)
    prompt = f"Document excerpts:\n\n{context}\n\nQuestion: {question}"

    try:
        raw = chat_complete(prompt, system=_RAG_SYSTEM, model=PRIMARY_MODEL, max_tokens=1024)
        answer, sources = _parse_rag_response(raw)
    except Exception as exc:
        logger.error("RAG query failed: %s", exc)
        answer = "Query failed due to a model error."
        sources = []

    return CitedAnswer(answer=answer, sources=sources, excerpts=excerpts)


def _retrieve(db: Session, query: str, top_k: int) -> list[dict]:
    """Cosine similarity search over doc_chunks using pgvector."""
    try:
        q_vec = embed_text(query)
    except Exception as exc:
        logger.error("Query embedding failed: %s", exc)
        return []

    rows = db.execute(
        text(
            """
            SELECT c.document_id, c.chunk_index, c.text,
                   1 - (c.embedding <=> CAST(:vec AS vector)) AS score
            FROM dis.doc_chunks c
            WHERE c.embedding IS NOT NULL
            ORDER BY c.embedding <=> CAST(:vec AS vector)
            LIMIT :k
            """
        ),
        {"vec": str(q_vec), "k": top_k},
    ).fetchall()

    return [
        {"doc_id": r[0], "chunk_index": r[1], "text": r[2], "score": float(r[3])}
        for r in rows
    ]


def _parse_rag_response(raw: str) -> tuple[str, list[str]]:
    answer = raw
    sources: list[str] = []

    lines = raw.splitlines()
    answer_lines: list[str] = []
    source_lines: list[str] = []

    in_sources = False
    for line in lines:
        if line.startswith("ANSWER:"):
            answer_lines.append(line[len("ANSWER:"):].strip())
        elif line.startswith("SOURCES:"):
            in_sources = True
            source_lines.append(line[len("SOURCES:"):].strip())
        elif in_sources:
            source_lines.append(line.strip())
        else:
            answer_lines.append(line)

    if answer_lines:
        answer = "\n".join(answer_lines).strip()
    if source_lines:
        raw_src = " ".join(source_lines)
        sources = [s.strip() for s in raw_src.split(",") if s.strip()]

    return answer, sources
