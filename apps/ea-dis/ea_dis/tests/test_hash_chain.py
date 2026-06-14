"""Tests: audit_log hash chain integrity."""
from __future__ import annotations

import hashlib
import json

from ea_dis.models import compute_audit_hash

# ---------------------------------------------------------------------------
# compute_audit_hash unit tests
# ---------------------------------------------------------------------------

def test_hash_is_sha256_hex():
    h = compute_audit_hash("document", "1", "INGEST", {"filename": "test.pdf"}, None)
    assert isinstance(h, str)
    assert len(h) == 64
    int(h, 16)  # must be valid hex


def test_hash_is_deterministic():
    args = ("document", "42", "RECLASSIFY", {"old": "DOC-10", "new": "DOC-06"}, "abc123")
    assert compute_audit_hash(*args) == compute_audit_hash(*args)


def test_different_payload_different_hash():
    h1 = compute_audit_hash("document", "1", "INGEST", {"filename": "a.pdf"}, None)
    h2 = compute_audit_hash("document", "1", "INGEST", {"filename": "b.pdf"}, None)
    assert h1 != h2


def test_prev_hash_changes_output():
    h1 = compute_audit_hash("document", "1", "INGEST", {}, None)
    h2 = compute_audit_hash("document", "1", "INGEST", {}, h1)
    assert h1 != h2


def test_chain_links_correctly():
    """Verify chain: hash_n = SHA256(... prev=hash_{n-1})."""
    h0 = compute_audit_hash("doc", "1", "CREATE", {}, None)
    h1 = compute_audit_hash("doc", "1", "UPDATE", {}, h0)
    h2 = compute_audit_hash("doc", "1", "DELETE", {}, h1)

    # Verify h1 by recomputing
    raw = json.dumps(
        {"entity_type": "doc", "entity_id": "1", "action": "UPDATE", "payload": {}, "prev_hash": h0},
        sort_keys=True,
        ensure_ascii=False,
    )
    expected_h1 = hashlib.sha256(raw.encode()).hexdigest()
    assert h1 == expected_h1

    # Verify h2
    raw2 = json.dumps(
        {"entity_type": "doc", "entity_id": "1", "action": "DELETE", "payload": {}, "prev_hash": h1},
        sort_keys=True,
        ensure_ascii=False,
    )
    expected_h2 = hashlib.sha256(raw2.encode()).hexdigest()
    assert h2 == expected_h2


def test_null_prev_hash_encoded_as_empty_string():
    """None prev_hash must use empty string in hash input (reproducibility)."""
    h_none = compute_audit_hash("doc", "1", "INGEST", {}, None)
    raw = json.dumps(
        {"entity_type": "doc", "entity_id": "1", "action": "INGEST", "payload": {}, "prev_hash": ""},
        sort_keys=True,
        ensure_ascii=False,
    )
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert h_none == expected


def test_entity_id_stringified():
    """entity_id is always cast to str so int and str produce same hash."""
    h_int = compute_audit_hash("document", 7, "INGEST", {}, None)
    h_str = compute_audit_hash("document", "7", "INGEST", {}, None)
    assert h_int == h_str


def test_tamper_detection_payload():
    """Changing the payload after hashing should produce a different hash — detectable."""
    original_payload = {"filename": "report.pdf", "doc_type": "DOC-03"}
    h = compute_audit_hash("document", "5", "INGEST", original_payload, None)

    tampered_payload = {"filename": "report.pdf", "doc_type": "DOC-07"}
    h_tampered = compute_audit_hash("document", "5", "INGEST", tampered_payload, None)

    assert h != h_tampered, "Tampered payload must produce a different hash"


def test_long_chain_integrity(count: int = 20):
    """Build a chain of `count` entries and verify each link."""
    hashes: list[str] = []
    prev: str | None = None
    for i in range(count):
        h = compute_audit_hash("document", str(i), "EVENT", {"seq": i}, prev)
        hashes.append(h)
        prev = h

    # Verify every link
    for i, h in enumerate(hashes):
        prev_h = hashes[i - 1] if i > 0 else None
        expected = compute_audit_hash("document", str(i), "EVENT", {"seq": i}, prev_h)
        assert h == expected, f"Chain broken at index {i}"
