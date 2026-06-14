"""End-to-end integration: classify → 3-way match → TAC gate → outcome.

Exercises EA-DIS (classify), EA-FCI (match + TAC), and EA-LIE (FIDIC alert)
in a single pipeline, verifying all cross-system invariants hold together.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[4]
for _p in [
    str(_ROOT / "apps/ea-dis"),
    str(_ROOT / "apps/ea-fci"),
    str(_ROOT / "apps/ea-lie"),
    str(_ROOT / "shared"),
]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ea_dis.constants import CONFIDENCE_THRESHOLD, DocStatus, DocType
from ea_dis.models import compute_audit_hash
from ea_dis.pipeline.classifier import _parse_classification
from fci.constants import MatchStatus
from fci.tac_gate import check_tac_gate
from fci.three_way_match import three_way_match
from lie.fidic_timebar import FIDICEdition, FIDICTimebar

from tests.harness.generators import (
    fidic_event_near_timebar,
    three_way_milestone_no_tac,
    three_way_exact_match,
)

SCENARIO_ID = "integration"

_TODAY = date(2026, 6, 14)


def setup(seed: int) -> dict:
    # EA-DIS: classify a contract document
    classify_json = json.dumps({
        "doc_type": "DOC-06",
        "confidence": 0.91,
        "reason": "EPC contract",
    })

    # EA-FCI: milestone invoice — blocked without TAC
    tw = three_way_milestone_no_tac(seed)

    # EA-LIE: FIDIC event near time-bar
    ev = fidic_event_near_timebar(seed)

    return {
        "seed": seed,
        "classify_json": classify_json,
        "po_qty": str(tw.po_qty),
        "po_unit_price_satang": tw.po_unit_price_satang,
        "grn_qty": str(tw.grn_qty),
        "inv_qty": str(tw.inv_qty),
        "inv_unit_price_satang": tw.inv_unit_price_satang,
        "fidic_edition": ev.edition_key,
        "fidic_clause": ev.clause,
        "fidic_trigger": ev.trigger_date.isoformat(),
        "fidic_contract_id": ev.contract_id,
    }


def _get_fidic_edition(key: str):
    m = {
        "RED_1999": FIDICEdition.RED_1999,
        "YELLOW_1999": FIDICEdition.YELLOW_1999,
        "RED_2017": FIDICEdition.RED_2017,
        "SILVER_1999": FIDICEdition.SILVER_1999,
    }
    return m.get(key, FIDICEdition.RED_1999)


def run(data: dict) -> dict:
    # Step 1 — EA-DIS classify
    classify_result = _parse_classification(data["classify_json"])
    h = compute_audit_hash("document", "1", "CLASSIFIED", {"doc_type": classify_result.doc_type.value}, None)

    # Step 2 — EA-FCI three-way match
    match_result = three_way_match(
        po_qty=Decimal(data["po_qty"]),
        po_unit_price_satang=data["po_unit_price_satang"],
        grn_qty=Decimal(data["grn_qty"]),
        inv_qty=Decimal(data["inv_qty"]),
        inv_unit_price_satang=data["inv_unit_price_satang"],
    )

    # Step 3 — EA-FCI TAC gate (milestone, no TAC)
    invoice = MagicMock()
    invoice.is_milestone = True
    invoice.is_equipment = False
    invoice.po_id = 1
    session = MagicMock()
    session.get.return_value = invoice
    session.query.return_value.filter.return_value.first.return_value = None  # no TAC
    tac_result = check_tac_gate(invoice_id=1, session=session)

    # Step 4 — EA-LIE FIDIC alert
    edition = _get_fidic_edition(data["fidic_edition"])
    tb = FIDICTimebar(edition)
    trigger = date.fromisoformat(data["fidic_trigger"])
    deadline = tb.create_deadline(data["fidic_clause"], trigger, data["fidic_contract_id"])
    if deadline is None:
        tb2 = FIDICTimebar(FIDICEdition.RED_1999)
        deadline = tb2.create_deadline(tb2.all_clauses()[0], trigger, data["fidic_contract_id"])
    alerts = tb.schedule_all_alerts(deadline, reference_date=_TODAY) if deadline else []

    return {
        "classify_doc_type": classify_result.doc_type.value,
        "classify_status": classify_result.status.value,
        "classify_is_sensitive": classify_result.is_sensitive,
        "audit_hash_len": len(h),
        "match_status": match_result.status.value,
        "tac_blocked": tac_result.blocked,
        "block_reason_has_tac": "TAC" in tac_result.block_reason if tac_result.block_reason else False,
        "fidic_alert_count": len(alerts),
        "fidic_deadline_missed": deadline.missed(_TODAY) if deadline else None,
    }


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    # EA-DIS: DOC-06 is sensitive, confidence 0.91 ≥ 0.85 → ACTIVE
    assert result["classify_doc_type"] == "DOC-06", f"seed={seed}: expected DOC-06"
    assert result["classify_status"] == DocStatus.ACTIVE.value, f"seed={seed}: expected ACTIVE"
    assert result["classify_is_sensitive"] is True, f"seed={seed}: DOC-06 must be sensitive"
    assert result["audit_hash_len"] == 64, f"seed={seed}: audit hash must be 64 chars"

    # EA-FCI: exact match → MATCH; milestone no TAC → blocked
    assert result["match_status"] == MatchStatus.MATCH.value, (
        f"seed={seed}: exact match inputs must produce MATCH"
    )
    assert result["tac_blocked"] is True, (
        f"seed={seed}: milestone without TAC must be blocked"
    )
    assert result["block_reason_has_tac"], (
        f"seed={seed}: block_reason must mention 'TAC'"
    )

    # EA-LIE: non-missed deadline must have ≥1 alert
    if not result["fidic_deadline_missed"]:
        assert result["fidic_alert_count"] >= 1, (
            f"seed={seed}: non-missed FIDIC deadline must produce ≥1 alert"
        )
