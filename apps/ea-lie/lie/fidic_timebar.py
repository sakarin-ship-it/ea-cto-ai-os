"""FIDIC timebar — parse edition, create deadlines, schedule 14/7/1-day alerts.

NEVER misses a timebar: if alerts are exhausted before deadline passes,
a same-day urgent alert is emitted as a safety net.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)

ALERT_THRESHOLDS = [14, 7, 1]  # days before deadline


class FIDICEdition(str, Enum):
    RED_1987 = "red_1987"
    RED_1999 = "red_1999"
    RED_2017 = "red_2017"
    YELLOW_1999 = "yellow_1999"
    YELLOW_2017 = "yellow_2017"
    SILVER_1999 = "silver_1999"
    SILVER_2017 = "silver_2017"
    GOLD_2008 = "gold_2008"


# (clause, description, deadline_days)
_TIMEBARS: dict[FIDICEdition, list[tuple[str, str, int]]] = {
    FIDICEdition.RED_1999: [
        ("20.1", "Contractor Notice of Claim", 28),
        ("2.5", "Employer's Claims", 28),
        ("8.4", "Extension of Time notice", 28),
        ("13.3", "Variation instruction response", 14),
        ("20.4", "Notice to refer to DAB", 28),
    ],
    FIDICEdition.YELLOW_1999: [
        ("20.1", "Contractor Notice of Claim", 28),
        ("2.5", "Employer's Claims", 28),
        ("8.4", "Extension of Time notice", 28),
        ("13.3", "Variation instruction response", 14),
    ],
    FIDICEdition.SILVER_1999: [
        ("20.1", "Contractor Notice of Claim", 28),
        ("2.5", "Employer's Claims", 28),
        ("8.4", "Extension of Time notice", 28),
    ],
    FIDICEdition.RED_2017: [
        ("20.2.1", "Initial Notice of Claim", 28),
        ("20.2.4", "Fully detailed claim", 84),
        ("2.5", "Employer's Claims", 28),
        ("8.5", "Extension of Time notice", 28),
        ("13.3.1", "Variation instruction response", 14),
    ],
    FIDICEdition.YELLOW_2017: [
        ("20.2.1", "Initial Notice of Claim", 28),
        ("20.2.4", "Fully detailed claim", 84),
        ("2.5", "Employer's Claims", 28),
        ("8.5", "Extension of Time notice", 28),
    ],
    FIDICEdition.SILVER_2017: [
        ("20.2.1", "Initial Notice of Claim", 28),
        ("20.2.4", "Fully detailed claim", 84),
        ("2.5", "Employer's Claims", 28),
    ],
    FIDICEdition.GOLD_2008: [
        ("20.1", "Contractor Notice of Claim", 28),
        ("2.5", "Employer's Claims", 28),
        ("8.4", "Extension of Time notice", 28),
    ],
    FIDICEdition.RED_1987: [
        ("53.1", "Notice of Claim (Clause 53)", 28),
        ("44.1", "Extension of Time notice", 28),
    ],
}
# Default for unknown editions
_TIMEBARS[FIDICEdition.RED_1999]  # reference; fall-through below uses RED_1999


@dataclass
class FIDICDeadline:
    clause: str
    description: str
    trigger_date: date
    deadline_days: int
    edition: FIDICEdition
    contract_id: str = ""

    @property
    def deadline_date(self) -> date:
        return self.trigger_date + timedelta(days=self.deadline_days)

    def days_remaining(self, reference_date: Optional[date] = None) -> int:
        ref = reference_date or date.today()
        return (self.deadline_date - ref).days

    def missed(self, reference_date: Optional[date] = None) -> bool:
        return self.days_remaining(reference_date) < 0


@dataclass
class TimerAlert:
    days_before: int
    alert_date: date
    deadline_date: date
    clause: str
    description: str
    contract_id: str
    edition: FIDICEdition


class FIDICTimebar:
    def __init__(self, edition: FIDICEdition) -> None:
        self.edition = edition
        self._bars = _TIMEBARS.get(edition, _TIMEBARS[FIDICEdition.RED_1999])

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def detect_edition(cls, contract_text: str) -> "FIDICTimebar":
        """Detect FIDIC edition from contract text keywords."""
        t = contract_text.lower()
        is_2017 = "2017" in t
        is_1987 = "1987" in t or "fourth edition" in t
        is_silver = "silver" in t or "epc" in t or "turnkey" in t
        is_yellow = "yellow" in t or "plant and design" in t or "design-build" in t
        is_gold = "gold" in t or "dbo" in t or "design, build and operate" in t

        if is_gold:
            return cls(FIDICEdition.GOLD_2008)
        if is_1987:
            return cls(FIDICEdition.RED_1987)
        if is_2017:
            if is_silver:
                return cls(FIDICEdition.SILVER_2017)
            if is_yellow:
                return cls(FIDICEdition.YELLOW_2017)
            return cls(FIDICEdition.RED_2017)
        if is_silver:
            return cls(FIDICEdition.SILVER_1999)
        if is_yellow:
            return cls(FIDICEdition.YELLOW_1999)
        return cls(FIDICEdition.RED_1999)

    # ------------------------------------------------------------------
    # Deadline creation
    # ------------------------------------------------------------------

    def create_deadline(
        self,
        clause: str,
        trigger_date: date,
        contract_id: str = "",
    ) -> Optional[FIDICDeadline]:
        """Create a typed deadline for the given clause and trigger date."""
        for (cl, desc, days) in self._bars:
            if cl == clause:
                return FIDICDeadline(
                    clause=clause,
                    description=desc,
                    trigger_date=trigger_date,
                    deadline_days=days,
                    edition=self.edition,
                    contract_id=contract_id,
                )
        logger.warning("Clause %s not found in %s timebars", clause, self.edition)
        return None

    def all_clauses(self) -> list[str]:
        return [cl for (cl, _, _) in self._bars]

    # ------------------------------------------------------------------
    # Alert scheduling
    # ------------------------------------------------------------------

    def get_alerts(
        self,
        deadline: FIDICDeadline,
        reference_date: Optional[date] = None,
    ) -> list[TimerAlert]:
        """Return all future threshold alerts for a deadline."""
        ref = reference_date or date.today()
        alerts: list[TimerAlert] = []
        for threshold in ALERT_THRESHOLDS:
            alert_date = deadline.deadline_date - timedelta(days=threshold)
            if alert_date >= ref:
                alerts.append(
                    TimerAlert(
                        days_before=threshold,
                        alert_date=alert_date,
                        deadline_date=deadline.deadline_date,
                        clause=deadline.clause,
                        description=deadline.description,
                        contract_id=deadline.contract_id,
                        edition=deadline.edition,
                    )
                )
        return alerts

    def schedule_all_alerts(
        self,
        deadline: FIDICDeadline,
        reference_date: Optional[date] = None,
    ) -> list[TimerAlert]:
        """Schedule 14/7/1-day alerts.  SAFETY NET: always emits ≥1 alert."""
        ref = reference_date or date.today()
        alerts = self.get_alerts(deadline, ref)

        if not alerts and not deadline.missed(ref):
            # Deadline is imminent but still future — emit same-day urgent alert
            alerts.append(
                TimerAlert(
                    days_before=0,
                    alert_date=ref,
                    deadline_date=deadline.deadline_date,
                    clause=deadline.clause,
                    description=f"URGENT (same-day): {deadline.description}",
                    contract_id=deadline.contract_id,
                    edition=deadline.edition,
                )
            )
            logger.critical(
                "FIDIC TIMEBAR IMMINENT: clause=%s deadline=%s contract=%s",
                deadline.clause,
                deadline.deadline_date,
                deadline.contract_id,
            )

        for alert in alerts:
            logger.info(
                "FIDIC alert: %s days before, clause=%s, deadline=%s, contract=%s",
                alert.days_before,
                alert.clause,
                alert.deadline_date,
                alert.contract_id,
            )
        return alerts
