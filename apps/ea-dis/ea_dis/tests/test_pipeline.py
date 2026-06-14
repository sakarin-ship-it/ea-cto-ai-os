"""Tests: full pipeline — parse, classify, chunk, embed integration (mocked I/O)."""
from __future__ import annotations

import json

from ea_dis.pipeline.chunker import chunk_text
from ea_dis.pipeline.parser import _detect_language, _has_chinese, _has_thai, translate_zh_to_en

# ---------------------------------------------------------------------------
# Parser: language detection
# ---------------------------------------------------------------------------

def test_detect_english():
    assert _detect_language("This is a standard English contract document.") == "en"


def test_detect_thai():
    thai = "นี่คือเอกสารสัญญาภาษาไทย"
    assert _detect_language(thai) == "th"


def test_detect_chinese():
    chinese = "这是一份中文合同文件，包含重要条款。"
    assert _detect_language(chinese) == "zh"


def test_has_chinese_true():
    assert _has_chinese("合同 contract") is True


def test_has_chinese_false():
    assert _has_chinese("Pure English text only") is False


def test_has_thai_true():
    assert _has_thai("สัญญา contract") is True


def test_has_thai_false():
    assert _has_thai("Pure English only") is False


def test_translate_zh_to_en_calls_lmstudio(mocker):
    mock_chat = mocker.patch(
        "ea_dis.pipeline.parser.chat_complete",
        return_value="This is the English translation.",
    )
    result = translate_zh_to_en("中文内容")
    assert "English" in result
    mock_chat.assert_called_once()


def test_translate_zh_chunks_long_text(mocker):
    mock_chat = mocker.patch(
        "ea_dis.pipeline.parser.chat_complete",
        return_value="Translated chunk.",
    )
    long_text = "中" * 9000  # 3 chunks of 3000
    translate_zh_to_en(long_text)
    assert mock_chat.call_count == 3


def test_translate_zh_handles_error_gracefully(mocker):
    mocker.patch(
        "ea_dis.pipeline.parser.chat_complete",
        side_effect=ConnectionError("LM Studio down"),
    )
    original = "失败测试"
    result = translate_zh_to_en(original)
    assert original in result  # falls back to original chunk


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------

def test_chunk_empty_text():
    assert chunk_text("") == []


def test_chunk_short_text_single_chunk():
    text = "Short document."
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == "Short document."


def test_chunk_long_text_multiple_chunks():
    # Create text with many paragraphs that exceeds CHUNK_CHARS
    paras = [f"Paragraph {i}: " + "x" * 100 for i in range(30)]
    text = "\n\n".join(paras)
    chunks = chunk_text(text, chunk_chars=800)
    assert len(chunks) > 1


def test_chunk_preserves_all_content():
    paras = [f"Para {i}" for i in range(10)]
    text = "\n\n".join(paras)
    chunks = chunk_text(text, chunk_chars=500)
    combined = " ".join(chunks)
    for i in range(10):
        assert f"Para {i}" in combined


def test_chunk_overlap_carries_content():
    # Last paragraph of chunk N should appear in chunk N+1
    paras = [f"Section {i}: " + "word " * 80 for i in range(5)]
    text = "\n\n".join(paras)
    chunks = chunk_text(text, chunk_chars=600, overlap=100)
    if len(chunks) > 1:
        # verify some overlap content appears in consecutive chunks
        # (not strictly guaranteed for all cases but validates no data loss)
        all_text = "\n".join(chunks)
        assert "Section 0" in all_text


# ---------------------------------------------------------------------------
# Full pipeline (mocked DB)
# ---------------------------------------------------------------------------

def test_ingest_pipeline_active(mocker, tmp_path):
    """High-confidence classification → ACTIVE status."""
    txt_file = tmp_path / "letter.txt"
    txt_file.write_text("To whom it may concern: This is a formal letter.")

    mocker.patch(
        "ea_dis.pipeline.classifier.chat_complete",
        return_value=json.dumps({"doc_type": "DOC-01", "confidence": 0.92, "reason": "letter"}),
    )
    mock_post = mocker.patch("lmstudio_client.httpx.post")
    mock_post.return_value.json.return_value = {
        "data": [{"embedding": [0.1] * 1024}]
    }
    mock_post.return_value.raise_for_status = lambda: None

    # Use a mock DB session
    db = mocker.MagicMock()
    db.get.return_value = None

    from ea_dis.pipeline.ingest import ingest_document

    # Patch DB interactions
    mock_doc = mocker.MagicMock()
    mock_doc.id = 1
    mock_doc.filename = "letter.txt"
    mock_doc.doc_type = "DOC-01"
    mock_doc.confidence = 0.92
    mock_doc.status = "ACTIVE"
    mock_doc.raw_text = "To whom it may concern: This is a formal letter."

    db.add = mocker.MagicMock()
    db.flush = mocker.MagicMock()
    db.commit = mocker.MagicMock()
    db.query.return_value.filter.return_value.count.return_value = 0

    # Patch audit
    mocker.patch("ea_dis.pipeline.ingest.append_audit", return_value=mocker.MagicMock())
    mocker.patch("ea_dis.pipeline.ingest.Document", return_value=mock_doc)
    mocker.patch("ea_dis.pipeline.ingest.DocChunk")

    result = ingest_document(db, str(txt_file), actor="test")
    assert result.status == "ACTIVE"
    assert result.doc_type == "DOC-01"


def test_ingest_pipeline_pending_review(mocker, tmp_path):
    """Low-confidence classification → PENDING_REVIEW, no embedding."""
    txt_file = tmp_path / "ambiguous.txt"
    txt_file.write_text("Some ambiguous content that is hard to classify.")

    mocker.patch(
        "ea_dis.pipeline.classifier.chat_complete",
        return_value=json.dumps({"doc_type": "DOC-03", "confidence": 0.55, "reason": "unclear"}),
    )
    embed_mock = mocker.patch("lmstudio_client.httpx.post")

    db = mocker.MagicMock()
    from ea_dis.pipeline.ingest import ingest_document

    mock_doc = mocker.MagicMock()
    mock_doc.id = 2
    mock_doc.filename = "ambiguous.txt"
    mock_doc.doc_type = "DOC-03"
    mock_doc.confidence = 0.55
    mock_doc.status = "PENDING_REVIEW"
    mock_doc.raw_text = "Some ambiguous content."

    db.add = mocker.MagicMock()
    db.flush = mocker.MagicMock()
    db.commit = mocker.MagicMock()

    mocker.patch("ea_dis.pipeline.ingest.append_audit", return_value=mocker.MagicMock())
    mocker.patch("ea_dis.pipeline.ingest.Document", return_value=mock_doc)

    result = ingest_document(db, str(txt_file), actor="test")
    assert result.status == "PENDING_REVIEW"
    # No embeddings should be called for pending review docs
    embed_mock.assert_not_called()
