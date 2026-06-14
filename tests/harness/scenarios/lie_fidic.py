"""EA-LIE: FIDIC timebar alert never missed — safety net for imminent deadlines."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT / "apps/ea-lie") not in sys.path:
    sys.path.insert(0, str(_ROOT / "apps/ea-lie"))

from lie.fidic_timebar import ALERT_THRESHOLDS, FIDICEdition, FIDICTimebar

from tests.harness.generators import FIDICEventData, fidic_event_near_timebar

SCENARIO_ID = "lie_fidic"

_EDITION_MAP = {
    "RED_1999": FIDICEdition.RED_1999,
    "YELLOW_1999": FIDICEdition.YELLOW_1999,
    "RED_2017": FIDICEdition.RED_2017,
    "SILVER_1999": FIDICEdition.SILVER_1999,
}


def setup(seed: int) -> dict:
    ev = fidic_event_near_timebar(seed)
    today = date(2026, 6, 14)
    deadline_date = ev.trigger_date + timedelta(days=28 if ev.clause in ("20.1", "2.5", "8.4", "20.2.1") else 84)
    days_remaining = (deadline_date - today).days
    return {
        "seed": seed,
        "edition_key": ev.edition_key,
        "clause": ev.clause,
        "trigger_date": ev.trigger_date.isoformat(),
        "contract_id": ev.contract_id,
        "days_remaining": days_remaining,
        "deadline_date": deadline_date.isoformat(),
    }


def run(data: dict) -> dict:
    today = date(2026, 6, 14)
    edition = _EDITION_MAP.get(data["edition_key"], FIDICEdition.RED_1999)
    tb = FIDICTimebar(edition)

    trigger = date.fromisoformat(data["trigger_date"])
    deadline_obj = tb.create_deadline(data["clause"], trigger, contract_id=data["contract_id"])

    if deadline_obj is None:
        # Clause not found in this edition — use RED_1999 fallback
        tb2 = FIDICTimebar(FIDICEdition.RED_1999)
        clause = tb2.all_clauses()[0]
        deadline_obj = tb2.create_deadline(clause, trigger, contract_id=data["contract_id"])

    if deadline_obj is None:
        return {"alert_count": 0, "days_before_values": [], "is_missed": True, "deadline_date": data["deadline_date"]}

    alerts = tb.schedule_all_alerts(deadline_obj, reference_date=today)
    missed = deadline_obj.missed(today)
    days_remaining = deadline_obj.days_remaining(today)

    return {
        "alert_count": len(alerts),
        "days_before_values": [a.days_before for a in alerts],
        "is_missed": missed,
        "days_remaining": days_remaining,
        "deadline_date": deadline_obj.deadline_date.isoformat(),
    }


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]
    days = result["days_remaining"]

    if result["is_missed"]:
        # Missed deadline → no future alerts (past events don't need alerts)
        # The invariant is: schedule_all_alerts returns [] for missed deadlines
        assert result["alert_count"] == 0, (
            f"seed={seed}: missed deadline must have 0 alerts, got {result['alert_count']}"
        )
    else:
        # Non-missed deadline → at least 1 alert must always be produced
        assert result["alert_count"] >= 1, (
            f"seed={seed}: non-missed deadline with {days} days remaining "
            f"must produce >=1 alert (safety net). Got 0 alerts."
        )

        # If deadline is far enough (>14 days), all 3 thresholds must be present
        if days > max(ALERT_THRESHOLDS):
            for threshold in ALERT_THRESHOLDS:
                assert threshold in result["days_before_values"], (
                    f"seed={seed}: {threshold}-day alert missing for deadline with "
                    f"{days} days remaining. Got: {result['days_before_values']}"
                )
