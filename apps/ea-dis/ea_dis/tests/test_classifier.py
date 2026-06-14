"""Tests: classification routing and confidence gate."""
from __future__ import annotations

import json

import pytest

from ea_dis.constants import CONFIDENCE_THRESHOLD, DocStatus, DocType
from ea_dis.pipeline.classifier import (
    _parse_classification,
    classify_document,
)

# ---------------------------------------------------------------------------
# _parse_classification unit tests
# ---------------------------------------------------------------------------

def _make_raw(doc_type: str, confidence: float, reason: str = "test") -> str:
    return json.dumps({"doc_type": doc_type, "confidence": confidence, "reason": reason})


def test_parse_doc01_high_confidence():
    result = _parse_classification(_make_raw("DOC-01", 0.92))
    assert result.doc_type == DocType.DOC_01
    assert result.confidence == pytest.approx(0.92)
    assert result.status == DocStatus.ACTIVE


def test_parse_doc06_contract_sensitive():
    result = _parse_classification(_make_raw("DOC-06", 0.95))
    assert result.doc_type == DocType.DOC_06
    assert result.is_sensitive is True
    assert result.status == DocStatus.ACTIVE


def test_parse_doc09_pdpa_sensitive():
    result = _parse_classification(_make_raw("DOC-09", 0.88))
    assert result.doc_type == DocType.DOC_09
    assert result.is_sensitive is True


def test_parse_doc05_jv_ip_sensitive():
    result = _parse_classification(_make_raw("DOC-05", 0.91))
    assert result.doc_type == DocType.DOC_05
    assert result.is_sensitive is True


def test_parse_doc07_financial_sensitive():
    result = _parse_classification(_make_raw("DOC-07", 0.89))
    assert result.doc_type == DocType.DOC_07
    assert result.is_sensitive is True


def test_parse_doc08_hr_not_sensitive():
    result = _parse_classification(_make_raw("DOC-08", 0.90))
    assert result.doc_type == DocType.DOC_08
    assert result.is_sensitive is False


# ---------------------------------------------------------------------------
# Confidence gate tests
# ---------------------------------------------------------------------------

def test_confidence_below_threshold_gives_pending_review():
    result = _parse_classification(_make_raw("DOC-03", 0.70))
    assert result.status == DocStatus.PENDING_REVIEW
    assert result.doc_type == DocType.DOC_03


def test_confidence_exactly_at_threshold_is_active():
    result = _parse_classification(_make_raw("DOC-04", CONFIDENCE_THRESHOLD))
    assert result.status == DocStatus.ACTIVE


def test_confidence_just_below_threshold_is_pending():
    just_below = CONFIDENCE_THRESHOLD - 0.001
    result = _parse_classification(_make_raw("DOC-02", just_below))
    assert result.status == DocStatus.PENDING_REVIEW


def test_confidence_zero_gives_pending_review():
    result = _parse_classification(_make_raw("DOC-01", 0.0))
    assert result.status == DocStatus.PENDING_REVIEW


# ---------------------------------------------------------------------------
# Sensitive doc type routing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("doc_type", ["DOC-05", "DOC-06", "DOC-07", "DOC-09"])
def test_sensitive_doc_types_flagged(doc_type):
    result = _parse_classification(_make_raw(doc_type, 0.95))
    assert result.is_sensitive is True, f"{doc_type} must be flagged sensitive"


@pytest.mark.parametrize("doc_type", ["DOC-01", "DOC-02", "DOC-03", "DOC-04", "DOC-08", "DOC-10"])
def test_non_sensitive_doc_types_not_flagged(doc_type):
    result = _parse_classification(_make_raw(doc_type, 0.95))
    assert result.is_sensitive is False, f"{doc_type} must NOT be flagged sensitive"


# ---------------------------------------------------------------------------
# Malformed JSON handling
# ---------------------------------------------------------------------------

def test_invalid_json_defaults_to_doc10_zero_confidence():
    result = _parse_classification("not json at all")
    assert result.doc_type == DocType.DOC_10
    assert result.confidence == pytest.approx(0.0)
    assert result.status == DocStatus.PENDING_REVIEW


def test_unknown_doc_type_defaults_to_doc10():
    raw = json.dumps({"doc_type": "DOC-99", "confidence": 0.99, "reason": "unknown"})
    result = _parse_classification(raw)
    assert result.doc_type == DocType.DOC_10


def test_missing_confidence_defaults_zero():
    raw = json.dumps({"doc_type": "DOC-01", "reason": "no conf key"})
    result = _parse_classification(raw)
    assert result.confidence == pytest.approx(0.0)
    assert result.status == DocStatus.PENDING_REVIEW


def test_confidence_clamped_above_one():
    raw = json.dumps({"doc_type": "DOC-01", "confidence": 1.5, "reason": "overflow"})
    result = _parse_classification(raw)
    assert result.confidence == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# classify_document integration (mocked lmstudio)
# ---------------------------------------------------------------------------

def test_classify_document_routes_to_contract(mocker):
    mocker.patch(
        "ea_dis.pipeline.classifier.chat_complete",
        return_value=_make_raw("DOC-06", 0.93, "contains contract terms"),
    )
    result = classify_document("Contract text mentioning EPC agreement")
    assert result.doc_type == DocType.DOC_06
    assert result.is_sensitive is True
    assert result.status == DocStatus.ACTIVE


def test_classify_document_low_confidence_pending(mocker):
    mocker.patch(
        "ea_dis.pipeline.classifier.chat_complete",
        return_value=_make_raw("DOC-03", 0.60, "ambiguous content"),
    )
    result = classify_document("Some ambiguous document")
    assert result.status == DocStatus.PENDING_REVIEW
    assert result.doc_type == DocType.DOC_03


def test_classify_document_lmstudio_error_defaults_doc10(mocker):
    mocker.patch(
        "ea_dis.pipeline.classifier.chat_complete",
        side_effect=ConnectionError("LM Studio unavailable"),
    )
    result = classify_document("Any text")
    assert result.doc_type == DocType.DOC_10
    assert result.confidence == pytest.approx(0.0)
    assert result.status == DocStatus.PENDING_REVIEW
