"""Tests for review engine — score thresholds, RAG, reviewer assignment."""
from __future__ import annotations

import json

from lie.review_engine import (
    RAGStatus,
    ReviewEngine,
    ReviewerLevel,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_findings(**overrides):
    base = {
        "has_injunctive_relief": True,
        "has_liquidated_damages": True,
        "ld_amount_thb": 15_000_000,
        "has_pdpa_reference": True,
        "has_sec_carveout": True,
        "has_esignature": True,
        "governing_law": "Thailand",
        "problematic_clauses": [],
        "missing_standard_clauses": [],
        "risk_factors": [],
    }
    base.update(overrides)
    return json.dumps(base)


# ---------------------------------------------------------------------------
# Score threshold tests — CRITICAL
# ---------------------------------------------------------------------------

def test_perfect_contract_score_below_35_green_cto_cfo(mocker):
    """All mandatory clauses present → GREEN → CTO+CFO reviewer."""
    mocker.patch(
        "lie.review_engine.chat_complete",
        return_value=_mock_findings(),
    )
    engine = ReviewEngine()
    result = engine.review_text("Full compliant contract text")

    assert result.score < 35, f"Expected score<35, got {result.score}"
    assert result.rag == RAGStatus.GREEN
    assert result.reviewer_level == ReviewerLevel.CTO_CFO
    assert result.gaps == []


def test_two_missing_clauses_score_35_to_60_amber_legal_counsel(mocker):
    """Missing 2 mandatory clauses + 1 risk factor → AMBER → Legal Counsel."""
    mocker.patch(
        "lie.review_engine.chat_complete",
        return_value=_mock_findings(
            has_injunctive_relief=False,
            has_liquidated_damages=False,
            ld_amount_thb=None,
            risk_factors=["Vague termination clause"],
        ),
    )
    engine = ReviewEngine()
    result = engine.review_text("Partial contract")

    # 2 × 20 + 1 × 5 = 45
    assert 35 <= result.score <= 60, f"Expected 35≤score≤60, got {result.score}"
    assert result.rag == RAGStatus.AMBER
    assert result.reviewer_level == ReviewerLevel.LEGAL_COUNSEL
    assert any("Injunctive" in g for g in result.gaps)
    assert any("Liquidated" in g for g in result.gaps)


def test_four_missing_clauses_score_above_60_red_external_lawyer(mocker):
    """Missing 4 mandatory clauses → RED → External Lawyer."""
    mocker.patch(
        "lie.review_engine.chat_complete",
        return_value=_mock_findings(
            has_injunctive_relief=False,
            has_liquidated_damages=False,
            ld_amount_thb=None,
            has_pdpa_reference=False,
            has_sec_carveout=False,
            problematic_clauses=["Unlimited liability", "No dispute resolution"],
            risk_factors=["No governing law", "Unreasonable indemnity"],
        ),
    )
    engine = ReviewEngine()
    result = engine.review_text("Deficient contract")

    assert result.score > 60, f"Expected score>60, got {result.score}"
    assert result.rag == RAGStatus.RED
    assert result.reviewer_level == ReviewerLevel.EXTERNAL_LAWYER


def test_ld_amount_below_10m_adds_penalty(mocker):
    """LD clause present but amount < THB 10M → +10 penalty points."""
    mocker.patch(
        "lie.review_engine.chat_complete",
        return_value=_mock_findings(ld_amount_thb=5_000_000),
    )
    engine = ReviewEngine()
    result = engine.review_text("Contract with low LD")

    assert any("10,000,000" in g for g in result.gaps), "Expected LD gap in gaps list"
    assert result.score >= 10


def test_score_capped_at_100(mocker):
    """Score never exceeds 100 even with many issues."""
    mocker.patch(
        "lie.review_engine.chat_complete",
        return_value=_mock_findings(
            has_injunctive_relief=False,
            has_liquidated_damages=False,
            has_pdpa_reference=False,
            has_sec_carveout=False,
            has_esignature=False,
            problematic_clauses=["A", "B", "C", "D", "E", "F"],
            risk_factors=["R1", "R2", "R3", "R4", "R5", "R6", "R7"],
        ),
    )
    engine = ReviewEngine()
    result = engine.review_text("Terrible contract")
    assert result.score == 100


# ---------------------------------------------------------------------------
# Mandatory clause tags bypass extraction check
# ---------------------------------------------------------------------------

def test_mandatory_tag_in_text_counts_as_present(mocker):
    """If the doc contains ##MC:IR## tag the injunctive relief gap is not raised,
    even if qwen3 extraction says has_injunctive_relief=False."""
    mocker.patch(
        "lie.review_engine.chat_complete",
        return_value=_mock_findings(has_injunctive_relief=False),
    )
    engine = ReviewEngine()
    text_with_tag = "Contract text ##MC:IR## some other content"
    result = engine.review_text(text_with_tag)

    ir_gaps = [g for g in result.gaps if "Injunctive" in g]
    assert ir_gaps == [], "Tag in text should satisfy injunctive relief requirement"


# ---------------------------------------------------------------------------
# Result structure
# ---------------------------------------------------------------------------

def test_review_result_has_summary(mocker):
    mocker.patch("lie.review_engine.chat_complete", return_value=_mock_findings())
    engine = ReviewEngine()
    result = engine.review_text("x")
    assert isinstance(result.summary, str)
    assert len(result.summary) > 0


def test_is_critical_flag(mocker):
    mocker.patch(
        "lie.review_engine.chat_complete",
        return_value=_mock_findings(
            has_injunctive_relief=False,
            has_liquidated_damages=False,
            has_pdpa_reference=False,
            has_sec_carveout=False,
        ),
    )
    engine = ReviewEngine()
    result = engine.review_text("bad contract")
    assert result.is_critical is True
