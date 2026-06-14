"""EA-DIS: classify + confidence-gate + sovereignty + hash-chain invariants."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_ROOT / "apps/ea-dis"), str(_ROOT / "shared")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ea_dis.constants import CONFIDENCE_THRESHOLD, SENSITIVE_DOC_TYPES, DocStatus, DocType
from ea_dis.models import compute_audit_hash
from ea_dis.pipeline.classifier import _parse_classification

from tests.harness.generators import doc_text_for_type, random_doc_text

SCENARIO_ID = "dis_classify"

# Ordered list of (doc_type, confidence) pairs cycled by seed
_VARIANTS = [
    ("DOC-01", 0.92), ("DOC-05", 0.91), ("DOC-06", 0.88), ("DOC-07", 0.90),
    ("DOC-09", 0.87), ("DOC-02", 0.70), ("DOC-03", 0.55), ("DOC-10", 0.30),
    ("DOC-04", 0.95), ("DOC-08", 0.85),
]


def setup(seed: int) -> dict:
    idx = seed % len(_VARIANTS)
    doc_type_str, confidence = _VARIANTS[idx]
    text = random_doc_text(seed)
    classify_response = json.dumps({"doc_type": doc_type_str, "confidence": confidence, "reason": "test"})
    return {
        "seed": seed,
        "text": text,
        "expected_doc_type": doc_type_str,
        "expected_confidence": confidence,
        "classify_response": classify_response,
    }


def run(data: dict) -> dict:
    classify_json = json.loads(data["classify_response"])
    doc_type_str = classify_json["doc_type"]
    confidence = float(classify_json["confidence"])

    result = _parse_classification(json.dumps(classify_json))

    # Hash-chain: compute two sequential entries
    h1 = compute_audit_hash("document", "1", "CLASSIFIED", {"doc_type": doc_type_str}, None)
    h2 = compute_audit_hash("document", "1", "RECLASSIFIED", {"doc_type": doc_type_str}, h1)
    h2_tampered = compute_audit_hash("document", "1", "RECLASSIFIED", {"doc_type": "DOC-99"}, h1)

    return {
        "doc_type": result.doc_type.value,
        "confidence": result.confidence,
        "status": result.status.value,
        "is_sensitive": result.is_sensitive,
        "hash1": h1,
        "hash2": h2,
        "hash2_tampered": h2_tampered,
    }


def assert_invariants(data: dict, result: dict) -> None:
    confidence = result["confidence"]
    status = result["status"]

    # Confidence gate
    if confidence < CONFIDENCE_THRESHOLD:
        assert status == DocStatus.PENDING_REVIEW.value, (
            f"seed={data['seed']}: confidence={confidence} < threshold → "
            f"expected PENDING_REVIEW, got {status}"
        )
    else:
        assert status == DocStatus.ACTIVE.value, (
            f"seed={data['seed']}: confidence={confidence} >= threshold → "
            f"expected ACTIVE, got {status}"
        )

    # Sovereignty / sensitivity
    try:
        dt = DocType(result["doc_type"])
    except ValueError:
        dt = DocType.DOC_10
    if dt in SENSITIVE_DOC_TYPES:
        assert result["is_sensitive"], (
            f"seed={data['seed']}: {result['doc_type']} must be is_sensitive=True"
        )

    # Hash-chain integrity
    h1, h2, h2_t = result["hash1"], result["hash2"], result["hash2_tampered"]
    assert len(h1) == 64, "hash1 must be 64-char hex SHA-256"
    assert len(h2) == 64, "hash2 must be 64-char hex SHA-256"
    assert h2 != h2_t, f"seed={data['seed']}: tampered hash must differ from valid hash"
    assert h1 != h2, f"seed={data['seed']}: consecutive hashes must differ"
