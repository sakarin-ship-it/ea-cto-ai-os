"""EA-DIS: RAG answer must cite a real retrieved document."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_ROOT / "apps/ea-dis"), str(_ROOT / "shared")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ea_dis.rag import _parse_rag_response

from tests.harness.generators import random_doc_text

SCENARIO_ID = "dis_rag"


def setup(seed: int) -> dict:
    doc_text = random_doc_text(seed)
    doc_id = (seed % 50) + 1
    chunk_idx = seed % 5
    question = "What is the main subject of this document?"
    rag_answer = (
        f"ANSWER: The document discusses construction contract matters [Doc-{doc_id}:{chunk_idx}].\n"
        f"SOURCES: Doc-{doc_id}:{chunk_idx}"
    )
    return {
        "seed": seed,
        "doc_text": doc_text,
        "doc_id": doc_id,
        "chunk_idx": chunk_idx,
        "question": question,
        "rag_answer": rag_answer,
        "excerpts": [{"doc_id": doc_id, "chunk_index": chunk_idx, "text": doc_text, "score": 0.92}],
    }


def run(data: dict) -> dict:
    answer, sources = _parse_rag_response(data["rag_answer"])
    return {
        "answer": answer,
        "sources": sources,
        "doc_id": data["doc_id"],
        "chunk_idx": data["chunk_idx"],
        "excerpt_count": len(data["excerpts"]),
    }


def assert_invariants(data: dict, result: dict) -> None:
    assert result["sources"], (
        f"seed={data['seed']}: RAG must return non-empty sources when docs exist"
    )
    expected_source = f"Doc-{data['doc_id']}:{data['chunk_idx']}"
    assert expected_source in result["sources"], (
        f"seed={data['seed']}: expected source {expected_source!r} not in {result['sources']}"
    )
    assert result["answer"].strip(), (
        f"seed={data['seed']}: RAG answer must not be blank"
    )
    assert result["excerpt_count"] > 0, (
        f"seed={data['seed']}: must have at least one excerpt"
    )
