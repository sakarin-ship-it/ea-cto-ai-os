"""Document ingestion for EA-FCI.

M5 rule: call qwen3-8b OCR/summary ONLY when the document contains Chinese
characters or is a scanned PDF (no extractable text layer).  All other
documents use a pure-Python extraction path (pdfplumber) with no model call.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# CJK Unified Ideographs block (U+4E00–U+9FFF)
_CJK_START = 0x4E00
_CJK_END = 0x9FFF


def has_chinese_content(text: str) -> bool:
    """True if *text* contains any CJK Unified Ideograph characters."""
    return any(_CJK_START <= ord(c) <= _CJK_END for c in text)


def extract_pdf_text(file_path: str) -> str:
    """Extract text from a PDF via pdfplumber (pure Python, no model)."""
    import pdfplumber  # lazy import

    pages: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            if t.strip():
                pages.append(t)
    return "\n".join(pages)


def is_scanned(file_path: str) -> bool:
    """Return True when no text can be extracted (likely a scanned image PDF)."""
    return not extract_pdf_text(file_path).strip()


@dataclass
class IngestResult:
    text: str
    summary: str | None    # set only when model was called
    used_model: bool
    filename: str


def ingest_document(file_path: str, filename: str) -> IngestResult:
    """Ingest a document.

    Calls qwen3-8b only for Chinese or scanned content; otherwise pure-Python.
    """
    text = extract_pdf_text(file_path)
    scanned = not text.strip()
    chinese = has_chinese_content(text)
    needs_model = chinese or scanned

    summary: str | None = None
    if needs_model:
        try:
            from lmstudio_client import PRIMARY_MODEL, chat_complete  # noqa: PLC0415

            prompt_text = text.strip() if text.strip() else f"[Scanned document: {filename}]"
            summary = chat_complete(
                f"Extract key financial fields (invoice number, date, total amount, "
                f"currency, supplier) from this document and return as JSON:\n\n"
                f"{prompt_text[:4000]}",
                model=PRIMARY_MODEL,
            )
        except Exception as exc:
            logger.error("OCR/summary call failed for %s: %s", filename, exc)

    return IngestResult(text=text, summary=summary, used_model=needs_model, filename=filename)
