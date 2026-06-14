"""Tests for NDA generator.

CRITICAL assertion: every NDA type must embed ALL five mandatory clause tags.
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from lie.clauses import ALL_MANDATORY_CLAUSES
from lie.nda_generator import NDAGenerator, NDAParams, NDAType
from lie.tests.conftest import extract_all_text

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_claude(mocker):
    """Mock Claude API to return a fixed optional clause selection."""
    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[MagicMock(text=json.dumps(["RETURN_OF_INFORMATION", "TRADE_SECRET"]))]
    )
    return mock_client


@pytest.fixture
def generator(mock_claude):
    return NDAGenerator(anthropic_client=mock_claude)


def _make_params(nda_type: NDAType) -> NDAParams:
    return NDAParams(
        nda_type=nda_type,
        disclosing_party="Acme Engineering Co., Ltd.",
        receiving_party="Beta Systems Corp.",
        purpose="Evaluation of potential joint venture in renewable energy sector",
        duration_years=2,
        confidentiality_period_years=3,
    )


# ---------------------------------------------------------------------------
# CRITICAL: mandatory clause presence
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nda_type", list(NDAType))
def test_all_mandatory_clauses_present_in_every_nda_type(generator, nda_type):
    """Every NDA type must embed every mandatory clause tag — no exceptions."""
    docx_bytes = generator.generate(_make_params(nda_type))
    text = extract_all_text(docx_bytes)

    for clause in ALL_MANDATORY_CLAUSES:
        assert clause.tag in text, (
            f"Mandatory clause {clause.id} ({clause.tag}) is MISSING from "
            f"{nda_type.value} NDA.  This is a blocking compliance failure."
        )


def test_mandatory_clause_count(generator):
    """Sanity: exactly 5 mandatory clauses defined."""
    assert len(ALL_MANDATORY_CLAUSES) == 5


# ---------------------------------------------------------------------------
# Bilingual content
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("nda_type", list(NDAType))
def test_bilingual_titles_present(generator, nda_type):
    docx_bytes = generator.generate(_make_params(nda_type))
    text = extract_all_text(docx_bytes)
    assert "NON-DISCLOSURE AGREEMENT" in text
    assert "ข้อตกลงการรักษาความลับ" in text


def test_thai_mandatory_clause_text_present(generator):
    docx_bytes = generator.generate(_make_params(NDAType.MUTUAL))
    text = extract_all_text(docx_bytes)
    # Spot-check Thai text from mandatory clauses
    assert "มาตรา 213" in text or "Section 213" in text  # injunctive relief
    assert "10,000,000" in text  # LD amount
    assert "PDPA" in text or "พ.ศ. 2562" in text  # PDPA reference


# ---------------------------------------------------------------------------
# Claude API only receives non-sensitive params
# ---------------------------------------------------------------------------

def test_claude_called_with_non_sensitive_params_only(mock_claude, generator):
    """Party names must NOT appear in the Claude API prompt."""
    params = _make_params(NDAType.UNILATERAL)
    generator.generate(params)

    call_kwargs = mock_claude.messages.create.call_args
    prompt_text = str(call_kwargs)
    assert "Acme Engineering Co., Ltd." not in prompt_text
    assert "Beta Systems Corp." not in prompt_text


# ---------------------------------------------------------------------------
# Output format
# ---------------------------------------------------------------------------

def test_generate_returns_bytes(generator):
    result = generator.generate(_make_params(NDAType.MUTUAL))
    assert isinstance(result, bytes)
    assert len(result) > 100  # non-trivial docx


def test_claude_api_failure_still_generates_nda(mocker):
    """Fallback to default clauses when Claude API errors; doc still valid."""
    mock_client = MagicMock()
    mock_client.messages.create.side_effect = Exception("network error")
    gen = NDAGenerator(anthropic_client=mock_client)

    docx_bytes = gen.generate(_make_params(NDAType.MUTUAL))
    text = extract_all_text(docx_bytes)

    for clause in ALL_MANDATORY_CLAUSES:
        assert clause.tag in text, f"Mandatory clause {clause.id} missing after API failure"
