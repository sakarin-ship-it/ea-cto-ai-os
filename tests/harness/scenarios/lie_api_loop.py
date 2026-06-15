"""EA-LIE: full API lifecycle (TestClient) —
FIDIC editions/detect/deadline → obligation schedule → contract review →
breach event → NDA generate → contract redline.

No database. External calls mocked: LM Studio (chat_complete) + Claude API (anthropic).
"""
from __future__ import annotations

import base64
import io
import json
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_ROOT / "apps/ea-lie"), str(_ROOT / "shared")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.harness.generators import (
    contract_text_with_all_clauses,
    fidic_event_near_timebar,
)

SCENARIO_ID = "lie_api_loop"

# Serialize concurrent iterations — module-level patches are global state
_LOCK = threading.Lock()

# 3 review scenarios cycled by seed
_REVIEW_SCENARIOS = [
    # (findings_overrides, use_clause_tags, expected_rag)
    ({}, True, "GREEN"),       # all clauses present → low score → GREEN
    ({"has_injunctive_relief": False, "has_pdpa_reference": False}, False, "AMBER"),
    ({
        "has_injunctive_relief": False,
        "has_liquidated_damages": False,
        "has_pdpa_reference": False,
        "has_sec_carveout": False,
        "has_esignature": False,
    }, False, "RED"),
]

_PLAIN_CONTRACT = (
    "EPC CONTRACT\n\nThis agreement sets out terms for engineering, procurement, "
    "and construction. Payment is due within 30 days of invoice."
)


def _findings_json(**overrides) -> str:
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


def _make_docx_b64() -> str:
    """Build a minimal docx and return as base64 string."""
    from docx import Document as DocxDoc

    doc = DocxDoc()
    doc.add_paragraph("Original clause text.")
    buf = io.BytesIO()
    doc.save(buf)
    return base64.b64encode(buf.getvalue()).decode()


def setup(seed: int) -> dict:
    ev = fidic_event_near_timebar(seed)
    scenario_idx = seed % len(_REVIEW_SCENARIOS)
    overrides, use_tags, expected_rag = _REVIEW_SCENARIOS[scenario_idx]
    contract_text = (
        contract_text_with_all_clauses(seed) if use_tags else _PLAIN_CONTRACT
    )
    return {
        "seed": seed,
        # Generator uses uppercase keys (e.g. "RED_1999"); FIDICEdition enum values are lowercase
        "fidic_edition": ev.edition_key.lower(),
        "fidic_clause": ev.clause,
        "fidic_trigger": ev.trigger_date.isoformat(),
        "fidic_contract_id": ev.contract_id,
        "contract_text": contract_text,
        "review_findings_json": _findings_json(**overrides),
        "expected_rag": expected_rag,
        "breach_contract_id": f"CTR-EPC-{seed:04d}",
        "obligation_id": f"OBL-{seed:04d}",
    }


def run(data: dict) -> dict:
    from lie.api import app

    results: dict = {}

    findings_json = data["review_findings_json"]
    breach_notice = (
        f"Formal notice of payment default under clause 14.6 for contract "
        f"{data['breach_contract_id']}. Cure period: 14 days."
    )
    docx_b64 = _make_docx_b64()

    mock_claude_client = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text='["TRADE_SECRET", "NON_SOLICITATION"]')]
    mock_claude_client.messages.create.return_value = mock_msg

    mock_proc = type("P", (), {"returncode": 0, "stderr": b""})()
    with _LOCK, \
         patch("lie.review_engine.chat_complete", return_value=findings_json), \
         patch("lie.breach_monitor.chat_complete", return_value=breach_notice), \
         patch("lie.breach_monitor.subprocess.run", return_value=mock_proc), \
         patch("lie.obligation_tracker.subprocess.run", return_value=mock_proc), \
         patch("lie.nda_generator.anthropic.Anthropic", return_value=mock_claude_client):

        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=True) as client:

            # ── FIDIC editions ────────────────────────────────────────────
            r = client.get("/fidic/editions")
            results["fidic_editions_status"] = r.status_code
            if r.status_code == 200:
                results["fidic_editions_count"] = len(r.json().get("editions", []))

            # ── FIDIC detect ──────────────────────────────────────────────
            r = client.post(
                "/fidic/detect",
                json={"text": "FIDIC General Conditions of Contract RED Book 1999 clause 20.1"},
            )
            results["fidic_detect_status"] = r.status_code
            if r.status_code == 200:
                results["fidic_detect_edition"] = r.json().get("edition")

            # ── FIDIC deadline ────────────────────────────────────────────
            r = client.post(
                "/fidic/deadline",
                json={
                    "edition": data["fidic_edition"],
                    "clause": data["fidic_clause"],
                    "trigger_date": data["fidic_trigger"],
                    "contract_id": data["fidic_contract_id"],
                },
            )
            results["fidic_deadline_status"] = r.status_code
            if r.status_code == 200:
                body = r.json()
                results["fidic_alert_count"] = len(body.get("alerts", []))
                results["fidic_missed"] = body.get("missed", False)
            else:
                results["fidic_alert_count"] = 0
                results["fidic_missed"] = None

            # ── Obligation schedule (compute, no Celery) ──────────────────
            r = client.post(
                "/obligation/schedule",
                json={
                    "id": data["obligation_id"],
                    "contract_id": data["breach_contract_id"],
                    "description": "Deliver Phase 1 milestone",
                    "due_date": "2030-12-31",
                    "parties": ["Contractor Ltd."],
                    "notification_channels": ["email"],
                    "dispatch": False,
                },
            )
            results["obligation_status"] = r.status_code
            if r.status_code == 200:
                results["obligation_alert_count"] = len(r.json().get("alerts", []))

            # ── Contract review (mocked qwen3-8b) ─────────────────────────
            r = client.post(
                "/contract/review",
                json={"text": data["contract_text"]},
            )
            results["review_status"] = r.status_code
            if r.status_code == 200:
                body = r.json()
                results["review_score"] = body["score"]
                results["review_rag"] = body["rag"]
                results["review_reviewer"] = body["reviewer_level"]

            # ── Breach event (mocked qwen3-8b, no iMessage) ───────────────
            r = client.post(
                "/breach/event",
                json={
                    "source": "EA-FCI",
                    "contract_id": data["breach_contract_id"],
                    "event_type": "PAYMENT_DEFAULT",
                    "description": "Contractor failed to pay milestone invoice.",
                    "evidence_urls": [],
                },
            )
            results["breach_status"] = r.status_code
            if r.status_code == 200:
                body = r.json()
                results["breach_notice_generated"] = body.get("notice_generated")
                results["breach_alert_sent"] = body.get("alert_sent")

            # ── NDA generate (mocked Claude API) ──────────────────────────
            r = client.post(
                "/nda",
                json={
                    "nda_type": "mutual",
                    "disclosing_party": "Thai Partner Co. Ltd.",
                    "receiving_party": "Foreign Investor Ltd.",
                    "purpose": "Joint venture due diligence",
                    "duration_years": 3,
                },
            )
            results["nda_status"] = r.status_code
            results["nda_content_type"] = r.headers.get("content-type", "")
            results["nda_content_length"] = len(r.content)

            # ── Contract redline (no external deps) ───────────────────────
            r = client.post(
                "/contract/redline",
                json={
                    "original_docx_b64": docx_b64,
                    "changes": [
                        {
                            "original_text": "Original clause text.",
                            "revised_text": "Revised clause text with updated legal terms.",
                            "reason": "Legal review update",
                            "clause_ref": "Article 1",
                        }
                    ],
                },
            )
            results["redline_status"] = r.status_code
            results["redline_content_type"] = r.headers.get("content-type", "")
            results["redline_content_length"] = len(r.content)

    return results


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    # FIDIC editions
    assert result.get("fidic_editions_status") == 200, (
        f"seed={seed}: GET /fidic/editions must return 200"
    )
    assert result.get("fidic_editions_count", 0) >= 4, (
        f"seed={seed}: must have ≥4 FIDIC editions"
    )

    # FIDIC detect
    assert result.get("fidic_detect_status") == 200, (
        f"seed={seed}: POST /fidic/detect must return 200"
    )
    assert result.get("fidic_detect_edition"), (
        f"seed={seed}: /fidic/detect must return an edition"
    )

    # FIDIC deadline — 200 (clause found), 404 (clause absent), or 400 (bad edition string)
    deadline_status = result.get("fidic_deadline_status")
    assert deadline_status in (200, 404, 400), (
        f"seed={seed}: /fidic/deadline must return 200/404/400, got {deadline_status}"
    )
    if deadline_status == 200 and not result.get("fidic_missed"):
        # non-missed deadline must produce ≥1 alert
        assert result.get("fidic_alert_count", 0) >= 1, (
            f"seed={seed}: non-missed FIDIC deadline must generate ≥1 alert"
        )

    # Obligation schedule
    assert result.get("obligation_status") == 200, (
        f"seed={seed}: POST /obligation/schedule must return 200, "
        f"got {result.get('obligation_status')}"
    )
    assert result.get("obligation_alert_count", 0) >= 1, (
        f"seed={seed}: obligation with 2030-12-31 due date must have ≥1 future alert"
    )

    # Contract review
    assert result.get("review_status") == 200, (
        f"seed={seed}: POST /contract/review must return 200, "
        f"got {result.get('review_status')}"
    )
    score = result.get("review_score", -1)
    assert 0 <= score <= 100, (
        f"seed={seed}: review score {score} must be in [0, 100]"
    )
    rag = result.get("review_rag")
    reviewer = result.get("review_reviewer")
    if score < 35:
        assert rag == "GREEN", f"seed={seed}: score {score} < 35 → GREEN, got {rag}"
        assert reviewer == "CTO_CFO", f"seed={seed}: score {score} → CTO_CFO"
    elif score <= 60:
        assert rag == "AMBER", f"seed={seed}: score {score} ∈ [35,60] → AMBER, got {rag}"
        assert reviewer == "LEGAL_COUNSEL", f"seed={seed}: → LEGAL_COUNSEL"
    else:
        assert rag == "RED", f"seed={seed}: score {score} > 60 → RED, got {rag}"
        assert reviewer == "EXTERNAL_LAWYER", f"seed={seed}: → EXTERNAL_LAWYER"

    # Expected RAG must match the scenario design
    assert rag == data["expected_rag"], (
        f"seed={seed}: expected rag={data['expected_rag']}, got {rag} (score={score})"
    )

    # Breach event
    assert result.get("breach_status") == 200, (
        f"seed={seed}: POST /breach/event must return 200, "
        f"got {result.get('breach_status')}"
    )
    assert result.get("breach_notice_generated") is True, (
        f"seed={seed}: breach notice must be generated (notice_generated=True)"
    )
    # subprocess.run is mocked; alert_sent=True when ALERT_IMESSAGE_RECIPIENT is configured
    assert isinstance(result.get("breach_alert_sent"), bool), (
        f"seed={seed}: alert_sent must be a bool"
    )

    # NDA
    assert result.get("nda_status") == 200, (
        f"seed={seed}: POST /nda must return 200, got {result.get('nda_status')}"
    )
    assert "wordprocessingml" in result.get("nda_content_type", ""), (
        f"seed={seed}: NDA must return docx content-type, "
        f"got {result.get('nda_content_type')!r}"
    )
    assert result.get("nda_content_length", 0) > 500, (
        f"seed={seed}: NDA docx must be non-trivial (>500 bytes)"
    )

    # Redline
    assert result.get("redline_status") == 200, (
        f"seed={seed}: POST /contract/redline must return 200, "
        f"got {result.get('redline_status')}"
    )
    assert "wordprocessingml" in result.get("redline_content_type", ""), (
        f"seed={seed}: redline must return docx content-type"
    )
    assert result.get("redline_content_length", 0) > 500, (
        f"seed={seed}: redlined docx must be non-trivial (>500 bytes)"
    )
