"""Tests: RAG citation format parsing."""
from __future__ import annotations

from ea_dis.rag import _parse_rag_response

# ---------------------------------------------------------------------------
# Citation format tests
# ---------------------------------------------------------------------------

def test_parse_answer_and_sources():
    raw = (
        "ANSWER: The contract value is THB 150M [Doc-42:0] as stated in the service agreement [Doc-42:1].\n"
        "SOURCES: Doc-42:0, Doc-42:1"
    )
    answer, sources = _parse_rag_response(raw)
    assert "150M" in answer
    assert "Doc-42:0" in sources
    assert "Doc-42:1" in sources


def test_parse_single_source():
    raw = "ANSWER: The due date is 30 June 2026 [Doc-7:2].\nSOURCES: Doc-7:2"
    answer, sources = _parse_rag_response(raw)
    assert sources == ["Doc-7:2"]
    assert "30 June 2026" in answer


def test_parse_no_sources_section():
    raw = "ANSWER: Insufficient information in the retrieved documents."
    answer, sources = _parse_rag_response(raw)
    assert "Insufficient" in answer
    assert sources == []


def test_parse_multiple_sources_comma_separated():
    raw = (
        "ANSWER: Details found across multiple documents [Doc-1:0] [Doc-2:3].\n"
        "SOURCES: Doc-1:0, Doc-2:3, Doc-5:1"
    )
    answer, sources = _parse_rag_response(raw)
    assert len(sources) == 3
    assert "Doc-1:0" in sources
    assert "Doc-5:1" in sources


def test_parse_answer_without_prefix():
    """If model omits ANSWER: prefix, full raw is returned as answer."""
    raw = "The total amount is THB 2.5M.\nSOURCES: Doc-3:0"
    answer, sources = _parse_rag_response(raw)
    assert "2.5M" in answer


def test_parse_sources_preserves_doc_chunk_format():
    """Citation format must be Doc-ID:chunk_index."""
    raw = "ANSWER: See clause 5 [Doc-99:12].\nSOURCES: Doc-99:12"
    _, sources = _parse_rag_response(raw)
    assert sources[0] == "Doc-99:12"


def test_parse_empty_sources_list():
    raw = "ANSWER: No relevant information found.\nSOURCES: "
    answer, sources = _parse_rag_response(raw)
    assert sources == []
    assert "No relevant" in answer


def test_parse_sources_stripped():
    raw = "ANSWER: Result.\nSOURCES:  Doc-1:0 ,  Doc-2:1 "
    _, sources = _parse_rag_response(raw)
    assert sources == ["Doc-1:0", "Doc-2:1"]


def test_answer_inline_citations_preserved():
    raw = (
        "ANSWER: Clause 3 [Doc-10:2] states liquidated damages apply.\n"
        "SOURCES: Doc-10:2"
    )
    answer, _ = _parse_rag_response(raw)
    assert "[Doc-10:2]" in answer
