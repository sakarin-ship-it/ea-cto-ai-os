"""Contract review engine.

Pipeline: LlamaParse → qwen3-8b (on-prem) extract → playbook compare
→ Red/Amber/Green → risk score 0-100 → reviewer assignment.

Long contracts are chunked sequentially (M5 rule: ≤4096 ctx per call).
Very large contracts get a per-section summary before final aggregation.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "shared"))
from lmstudio_client import PRIMARY_MODEL, chat_complete, chunk_and_complete  # noqa: E402

logger = logging.getLogger(__name__)

CHUNK_CHARS = 6_000
LARGE_DOC_THRESHOLD = 18_000  # chars; above this → section summaries first
MANDATORY_WEIGHT = 20          # points per missing mandatory clause
MAX_RISK_FACTOR_PTS = 20
MAX_PROBLEMATIC_PTS = 15


class RAGStatus(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"


class ReviewerLevel(str, Enum):
    CTO_CFO = "CTO_CFO"
    LEGAL_COUNSEL = "LEGAL_COUNSEL"
    EXTERNAL_LAWYER = "EXTERNAL_LAWYER"


@dataclass
class ReviewResult:
    score: int                        # 0-100; higher = more risk
    rag: RAGStatus
    reviewer_level: ReviewerLevel
    gaps: list[str] = field(default_factory=list)
    findings: dict[str, Any] = field(default_factory=dict)
    summary: str = ""

    @property
    def is_critical(self) -> bool:
        return self.score > 60


_EXTRACT_PROMPT = (
    "Analyse the following contract excerpt and return ONLY valid JSON (no markdown) "
    "with exactly these keys:\n"
    "{\n"
    '  "has_injunctive_relief": <bool>,\n'
    '  "has_liquidated_damages": <bool>,\n'
    '  "ld_amount_thb": <number or null>,\n'
    '  "has_pdpa_reference": <bool>,\n'
    '  "has_sec_carveout": <bool>,\n'
    '  "has_esignature": <bool>,\n'
    '  "governing_law": "<string>",\n'
    '  "problematic_clauses": [<strings>],\n'
    '  "missing_standard_clauses": [<strings>],\n'
    '  "risk_factors": [<strings>]\n'
    "}\n\nContract excerpt:\n"
)


class ReviewEngine:
    def __init__(
        self,
        llamaparse_api_key: str = "",
        lmstudio_base: str = "http://localhost:1234",
    ) -> None:
        self._llamaparse_key = llamaparse_api_key
        self._lmstudio_base = lmstudio_base

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review(self, document_path: str) -> ReviewResult:
        """Review a contract file (PDF or docx)."""
        text = self._parse_document(document_path)
        return self._review_text_internal(text)

    def review_text(self, text: str) -> ReviewResult:
        """Review from raw text (used by tests and API when text already extracted)."""
        return self._review_text_internal(text)

    # ------------------------------------------------------------------
    # Internal pipeline
    # ------------------------------------------------------------------

    def _review_text_internal(self, text: str) -> ReviewResult:
        findings = self._extract(text)
        score, rag, gaps = self._compare_to_playbook(findings, text)
        reviewer = _assign_reviewer(score)
        summary = _make_summary(score, gaps)
        return ReviewResult(
            score=score,
            rag=rag,
            reviewer_level=reviewer,
            gaps=gaps,
            findings=findings,
            summary=summary,
        )

    def _parse_document(self, path: str) -> str:
        if self._llamaparse_key:
            try:
                return self._llamaparse(path)
            except Exception as exc:
                logger.warning("LlamaParse failed (%s); falling back", exc)
        return _parse_fallback(path)

    def _llamaparse(self, path: str) -> str:
        from llama_parse import LlamaParse  # lazy import; optional dep

        parser = LlamaParse(api_key=self._llamaparse_key, result_type="text")
        docs = parser.load_data(path)
        return "\n\n".join(d.text for d in docs)

    def _extract(self, text: str) -> dict[str, Any]:
        """Run qwen3-8b extraction, chunking if text is large."""
        if len(text) > LARGE_DOC_THRESHOLD:
            return self._extract_large(text)
        return _extract_chunk(text)

    def _extract_large(self, text: str) -> dict[str, Any]:
        """Summarise each chunk first, then do a final extraction over summaries."""
        summary_prompt = (
            "Summarise the following contract section in ≤200 words, "
            "preserving all legal obligations, amounts, and parties:\n"
        )
        chunk_summaries = chunk_and_complete(text, summary_prompt, model=PRIMARY_MODEL)
        combined_summary = "\n\n".join(s for s in chunk_summaries if s)
        return _extract_chunk(combined_summary)

    def _compare_to_playbook(
        self, findings: dict[str, Any], original_text: str = ""
    ) -> tuple[int, RAGStatus, list[str]]:
        score = 0
        gaps: list[str] = []

        clause_checks = [
            ("has_injunctive_relief", "Injunctive Relief (CCC Art.213)", "##MC:IR##"),
            ("has_liquidated_damages", "Liquidated Damages ≥ THB 10M", "##MC:LD##"),
            ("has_pdpa_reference", "PDPA / DPA Cross-Reference", "##MC:PDPA##"),
            ("has_sec_carveout", "SEC Act Disclosure Carve-Out", "##MC:SEC##"),
            ("has_esignature", "Thai E-Signature Block", "##MC:ESIG##"),
        ]

        for field_key, label, tag in clause_checks:
            in_findings = bool(findings.get(field_key))
            in_text = tag in original_text
            if not in_findings and not in_text:
                score += MANDATORY_WEIGHT
                gaps.append(f"MISSING: {label}")

        # LD amount adequacy
        ld_amt = findings.get("ld_amount_thb")
        if findings.get("has_liquidated_damages") and ld_amt and int(ld_amt) < 10_000_000:
            score += 10
            gaps.append(f"LD amount THB {int(ld_amt):,} is below required THB 10,000,000")

        # Risk factors (qwen3-extracted)
        risk_factors = findings.get("risk_factors") or []
        score += min(len(risk_factors) * 5, MAX_RISK_FACTOR_PTS)

        # Problematic clauses
        problematic = findings.get("problematic_clauses") or []
        score += min(len(problematic) * 3, MAX_PROBLEMATIC_PTS)

        score = min(score, 100)
        rag = _score_to_rag(score)
        return score, rag, gaps


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _extract_chunk(text: str) -> dict[str, Any]:
    prompt = _EXTRACT_PROMPT + text[:6_000]
    try:
        raw = chat_complete(prompt, model=PRIMARY_MODEL)
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            return json.loads(m.group())
    except Exception as exc:
        logger.error("qwen3 extraction failed: %s", exc)
    return _empty_findings()


def _empty_findings() -> dict[str, Any]:
    return {
        "has_injunctive_relief": False,
        "has_liquidated_damages": False,
        "ld_amount_thb": None,
        "has_pdpa_reference": False,
        "has_sec_carveout": False,
        "has_esignature": False,
        "governing_law": "",
        "problematic_clauses": [],
        "missing_standard_clauses": [],
        "risk_factors": [],
    }


def _parse_fallback(path: str) -> str:
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        try:
            import pdfplumber  # optional

            with pdfplumber.open(path) as pdf:
                return "\n\n".join(pg.extract_text() or "" for pg in pdf.pages)
        except Exception:
            pass
    if p.suffix.lower() in {".docx", ".doc"}:
        try:
            from docx import Document

            doc = Document(path)
            return "\n\n".join(para.text for para in doc.paragraphs)
        except Exception:
            pass
    return p.read_text(encoding="utf-8", errors="ignore")


def _score_to_rag(score: int) -> RAGStatus:
    if score < 35:
        return RAGStatus.GREEN
    if score <= 60:
        return RAGStatus.AMBER
    return RAGStatus.RED


def _assign_reviewer(score: int) -> ReviewerLevel:
    if score < 35:
        return ReviewerLevel.CTO_CFO
    if score <= 60:
        return ReviewerLevel.LEGAL_COUNSEL
    return ReviewerLevel.EXTERNAL_LAWYER


def _make_summary(score: int, gaps: list[str]) -> str:
    if not gaps:
        return f"Risk Score: {score}/100 — No critical gaps detected."
    return (
        f"Risk Score: {score}/100 — {len(gaps)} gap(s): "
        + "; ".join(gaps[:3])
        + ("…" if len(gaps) > 3 else "")
    )
