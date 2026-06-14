"""Document parser: PDF / DOCX + EasyOCR (Thai) + qwen3 ZH→EN translation.

M5 rule: process one document at a time; release model after translation.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

_SHARED = Path(__file__).resolve().parents[4] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from lmstudio_client import PRIMARY_MODEL, chat_complete  # noqa: E402

_ZH_TRANSLATE_SYSTEM = (
    "You are a professional translator. "
    "Translate the following Chinese text to English accurately. "
    "Return only the translated text, no commentary."
)

_ZH_CHARS = frozenset(
    chr(c) for r in [(0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0xF900, 0xFAFF)] for c in range(*r)
)


def _has_chinese(text: str) -> bool:
    return any(ch in _ZH_CHARS for ch in text)


def _has_thai(text: str) -> bool:
    return any("฀" <= ch <= "๿" for ch in text)


def parse_pdf(path: str) -> tuple[str, int]:
    """Return (text, page_count). Uses pdfplumber; falls back to EasyOCR for Thai."""
    import pdfplumber  # lazy

    pages_text: list[str] = []
    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            text = page.extract_text() or ""
            if not text.strip() or _has_thai(text):
                text = _ocr_page(page, text)
            pages_text.append(text)
    return "\n\n".join(pages_text), page_count


def _ocr_page(page, existing_text: str) -> str:
    """Run EasyOCR on a pdfplumber page image when pdfplumber text is poor."""
    try:
        import easyocr  # lazy; optional dep
        import numpy as np

        img = page.to_image(resolution=200).original
        reader = easyocr.Reader(["th", "en"], gpu=False, verbose=False)
        result = reader.readtext(np.array(img), detail=0)
        ocr_text = " ".join(result)
        return ocr_text if ocr_text.strip() else existing_text
    except Exception as exc:
        logger.warning("EasyOCR unavailable (%s), using pdfplumber text", exc)
        return existing_text


def parse_docx(path: str) -> tuple[str, int]:
    """Return (text, page_count≈para_count). Uses python-docx."""
    from docx import Document  # lazy

    doc = Document(path)
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs), len(paragraphs)


def parse_file(path: str) -> tuple[str, int, str]:
    """Parse any supported file.

    Returns (text, page_count, detected_language).
    language: 'th' | 'zh' | 'en' | 'mixed'
    """
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".pdf":
        text, pages = parse_pdf(path)
    elif suffix in {".docx", ".doc"}:
        text, pages = parse_docx(path)
    else:
        text = p.read_text(encoding="utf-8", errors="ignore")
        pages = text.count("\n\n") + 1

    lang = _detect_language(text)

    if lang in ("zh", "mixed") and _has_chinese(text):
        text = translate_zh_to_en(text)
        lang = "zh"

    return text, pages, lang


def _detect_language(text: str) -> str:
    sample = text[:2000]
    has_zh = _has_chinese(sample)
    has_th = _has_thai(sample)
    if has_zh and has_th:
        return "mixed"
    if has_zh:
        return "zh"
    if has_th:
        return "th"
    return "en"


def translate_zh_to_en(text: str) -> str:
    """Translate Chinese text to English via qwen3-8b (on-prem, sequential chunks)."""
    chunk_size = 3000
    chunks = [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
    translated: list[str] = []
    for chunk in chunks:
        try:
            result = chat_complete(
                chunk,
                system=_ZH_TRANSLATE_SYSTEM,
                model=PRIMARY_MODEL,
                max_tokens=4096,
            )
            translated.append(result)
        except Exception as exc:
            logger.error("Translation chunk failed: %s", exc)
            translated.append(chunk)
    return "\n\n".join(translated)
