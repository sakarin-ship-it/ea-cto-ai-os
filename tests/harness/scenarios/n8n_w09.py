"""n8n W-09: Breach Detection + Response — correct notice invariants.

W-09 calls EA-LIE's breach_monitor endpoint. We test the underlying
BreachMonitor.process_event() invariants: notice generated, non-empty,
evidence summary contains contract_id, LINE skip is safe.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_ROOT / "apps/ea-lie"), str(_ROOT / "shared")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from lie.breach_monitor import BreachEvent, BreachMonitor, EventSource

from tests.harness.generators import breach_event

SCENARIO_ID = "n8n_w09"

_SOURCE_MAP = {
    "EA-FCI": EventSource.EA_FCI,
    "EA-DIS": EventSource.EA_DIS,
    "EA-PIP": EventSource.EA_PIP,
}

_NOTICE_TEMPLATE = (
    "FORMAL BREACH NOTICE\n\n"
    "Dear Sir/Madam,\n\n"
    "This letter serves as formal notification of a breach of contract "
    "under Contract ID {contract_id}. The breach involves {event_type}.\n\n"
    "Required remediation within 14 days. All rights reserved per CCC Art.213."
)


def setup(seed: int) -> dict:
    ev = breach_event(seed)
    notice_text = _NOTICE_TEMPLATE.format(
        contract_id=ev.contract_id,
        event_type=ev.event_type,
    )
    return {
        "seed": seed,
        "contract_id": ev.contract_id,
        "event_type": ev.event_type,
        "description": ev.description,
        "source": ev.source,
        "notice_text": notice_text,
    }


def run(data: dict) -> dict:
    monitor = BreachMonitor(line_token="")  # no LINE token → skip network call
    event = BreachEvent(
        source=_SOURCE_MAP[data["source"]],
        contract_id=data["contract_id"],
        event_type=data["event_type"],
        description=data["description"],
    )

    # Mock qwen3 call to return our synthetic notice
    with patch("lie.breach_monitor.chat_complete", return_value=data["notice_text"]):
        response = monitor.process_event(event, obligations=[])

    return {
        "notice_text": response.notice_text,
        "evidence_summary": response.evidence_summary,
        "line_sent": response.line_sent,
        "notice_generated": response.notice_generated,
        "contract_id": response.contract_id,
    }


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    # Notice must be generated and non-empty
    assert result["notice_generated"], (
        f"seed={seed}: notice_generated must be True"
    )
    assert result["notice_text"].strip(), (
        f"seed={seed}: notice_text must not be blank"
    )
    assert not result["notice_text"].startswith("[FAILED"), (
        f"seed={seed}: notice_text must not start with [FAILED"
    )

    # Evidence summary must contain contract ID
    assert data["contract_id"] in result["evidence_summary"], (
        f"seed={seed}: evidence_summary must contain contract_id={data['contract_id']!r}"
    )
    assert result["contract_id"] == data["contract_id"], (
        f"seed={seed}: response.contract_id mismatch"
    )

    # LINE not sent (no token) — must be False, not an error
    assert result["line_sent"] is False, (
        f"seed={seed}: line_sent must be False when no token is set"
    )
