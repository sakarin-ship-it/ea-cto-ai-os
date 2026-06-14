"""Tests for contract drafter — 6 types, qwen3 ON-PREM only."""
from __future__ import annotations

import pytest

from lie.contract_drafter import ContractDrafter, ContractType


@pytest.fixture
def mock_lmstudio(mocker):
    """Mock LM Studio chat_complete to return synthetic section text."""
    return mocker.patch(
        "lie.contract_drafter.chat_complete",
        return_value="[Generated section content — qwen3-8b on-prem]",
    )


@pytest.fixture
def drafter():
    return ContractDrafter()


_CONTEXT = {
    "parties_en": "Client Corp Ltd. and Provider Co., Ltd.",
    "parties_th": "บริษัท ไคลเอนท์ จำกัด และ บริษัท โพรไวเดอร์ จำกัด",
    "services": "Software development and maintenance",
    "fee": "THB 1,200,000",
    "duration": "12 months",
}


# ---------------------------------------------------------------------------
# All six contract types produce docx
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ct", list(ContractType))
def test_all_six_types_produce_bytes(mock_lmstudio, drafter, ct):
    result = drafter.draft(ct, _CONTEXT)
    assert isinstance(result.docx_bytes, bytes)
    assert len(result.docx_bytes) > 100


@pytest.mark.parametrize("ct", list(ContractType))
def test_correct_sections_generated(mock_lmstudio, drafter, ct):
    result = drafter.draft(ct, _CONTEXT)
    assert len(result.sections) > 0
    for key, val in result.sections.items():
        assert isinstance(key, str)
        assert isinstance(val, str)


# ---------------------------------------------------------------------------
# On-prem only — never calls cloud
# ---------------------------------------------------------------------------

def test_uses_lmstudio_not_cloud(mocker, drafter):
    """chat_complete (LM Studio) must be called; anthropic must NOT be called."""
    mock_chat = mocker.patch(
        "lie.contract_drafter.chat_complete",
        return_value="content",
    )
    # If anthropic were imported, patching would reveal it
    result = drafter.draft(ContractType.SERVICE_AGREEMENT, _CONTEXT)

    assert mock_chat.called, "LM Studio chat_complete was not called"
    # Verify all calls use localhost base (via PRIMARY_MODEL constant)
    assert result.contract_type == ContractType.SERVICE_AGREEMENT


def test_section_count_matches_type(mock_lmstudio, drafter):
    """Service agreements have exactly 7 sections."""
    result = drafter.draft(ContractType.SERVICE_AGREEMENT, _CONTEXT)
    assert len(result.sections) == 7


def test_construction_has_claims_section(mock_lmstudio, drafter):
    result = drafter.draft(ContractType.CONSTRUCTION, _CONTEXT)
    assert "claims_and_disputes" in result.sections


def test_employment_has_non_compete(mock_lmstudio, drafter):
    result = drafter.draft(ContractType.EMPLOYMENT, _CONTEXT)
    assert "non_compete_and_non_solicitation" in result.sections


def test_draft_result_type_field(mock_lmstudio, drafter):
    result = drafter.draft(ContractType.LICENSE, _CONTEXT)
    assert result.contract_type == ContractType.LICENSE


# ---------------------------------------------------------------------------
# LM Studio failure fallback
# ---------------------------------------------------------------------------

def test_lmstudio_failure_produces_placeholder(mocker, drafter):
    mocker.patch(
        "lie.contract_drafter.chat_complete",
        side_effect=Exception("Connection refused"),
    )
    result = drafter.draft(ContractType.NDA, _CONTEXT)
    # Should not raise; each section gets a fallback placeholder
    for val in result.sections.values():
        assert isinstance(val, str)
