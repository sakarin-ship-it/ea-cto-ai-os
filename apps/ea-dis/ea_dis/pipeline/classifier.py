"""Document classifier: routes text to DOC-01..DOC-10 via lmstudio_client.

Privacy: sensitive doc types (DOC-05/06/07/09) are only processed on-prem.
Confidence gate: if confidence < 0.85 → status = PENDING_REVIEW.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

from ea_dis.constants import CONFIDENCE_THRESHOLD, SENSITIVE_DOC_TYPES, DocStatus, DocType

logger = logging.getLogger(__name__)

_SHARED = Path(__file__).resolve().parents[4] / "shared"
if str(_SHARED) not in sys.path:
    sys.path.insert(0, str(_SHARED))

from lmstudio_client import PRIMARY_MODEL, chat_complete  # noqa: E402

_CLASSIFY_SYSTEM = """\
You are a document classifier for a Thai/international engineering company.
Classify documents into exactly one of these categories:

DOC-01: General correspondence (emails, letters, memos)
DOC-02: Board minutes or resolutions
DOC-03: Project reports or progress updates
DOC-04: Technical specifications or engineering drawings
DOC-05: JV agreements, IP assignments, or joint-venture contracts
DOC-06: Commercial contracts (EPC, construction, service agreements)
DOC-07: Financial documents (invoices, bank statements, financial reports)
DOC-08: HR documents (employment contracts, payroll, staff records)
DOC-09: PDPA / personal data documents (consent forms, data processing records)
DOC-10: Other or unclassified documents

Return ONLY valid JSON:
{"doc_type": "DOC-XX", "confidence": 0.0-1.0, "reason": "brief reason"}"""


class ClassificationResult:
    def __init__(self, doc_type: DocType, confidence: float, reason: str) -> None:
        self.doc_type = doc_type
        self.confidence = confidence
        self.reason = reason
        self.status = (
            DocStatus.PENDING_REVIEW
            if confidence < CONFIDENCE_THRESHOLD
            else DocStatus.ACTIVE
        )
        self.is_sensitive = doc_type in SENSITIVE_DOC_TYPES

    def __repr__(self) -> str:
        return (
            f"ClassificationResult(doc_type={self.doc_type}, "
            f"confidence={self.confidence:.2f}, status={self.status})"
        )


def classify_document(text: str) -> ClassificationResult:
    """Classify document text; returns ClassificationResult.

    Uses qwen3-8b on-prem only (privacy boundary: text never leaves localhost).
    """
    sample = text[:4000]
    prompt = f"Classify this document:\n\n{sample}"
    try:
        raw = chat_complete(prompt, system=_CLASSIFY_SYSTEM, model=PRIMARY_MODEL, max_tokens=256)
        return _parse_classification(raw)
    except Exception as exc:
        logger.error("Classification failed: %s", exc)
        return ClassificationResult(DocType.DOC_10, 0.0, f"error: {exc}")


def _parse_classification(raw: str) -> ClassificationResult:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return ClassificationResult(DocType.DOC_10, 0.0, "no JSON in response")
    try:
        data = json.loads(m.group())
        doc_type_str = str(data.get("doc_type", "DOC-10")).upper()
        confidence = float(data.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
        reason = str(data.get("reason", ""))
        try:
            doc_type = DocType(doc_type_str)
        except ValueError:
            doc_type = DocType.DOC_10
        return ClassificationResult(doc_type, confidence, reason)
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.warning("Classification parse error: %s — raw: %r", exc, raw[:200])
        return ClassificationResult(DocType.DOC_10, 0.0, "parse error")
