"""Obligation tracker — Celery tasks with 90/60/30/7-day alerts.

Celery broker: Redis on localhost:6379.
Low concurrency (2) per M5 memory rules.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from celery import Celery

logger = logging.getLogger(__name__)

ALERT_DAYS = [90, 60, 30, 7]

celery_app = Celery(
    "lie.obligation_tracker",
    broker="redis://localhost:6379/1",
    backend="redis://localhost:6379/1",
)
celery_app.conf.update(
    worker_concurrency=2,          # M5 memory bound
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Bangkok",
    enable_utc=True,
)


@dataclass
class Obligation:
    id: str
    contract_id: str
    description: str
    due_date: date
    parties: list[str] = field(default_factory=list)
    notification_channels: list[str] = field(default_factory=list)


@dataclass
class ScheduledAlert:
    obligation_id: str
    days_before_due: int
    alert_date: date
    due_date: date


class ObligationTracker:
    """Schedule and manage contract obligation alerts."""

    def compute_alerts(self, obligation: Obligation) -> list[ScheduledAlert]:
        """Return all future alert records (does not dispatch to Celery)."""
        today = date.today()
        alerts: list[ScheduledAlert] = []
        for days in ALERT_DAYS:
            alert_date = obligation.due_date - timedelta(days=days)
            if alert_date >= today:
                alerts.append(
                    ScheduledAlert(
                        obligation_id=obligation.id,
                        days_before_due=days,
                        alert_date=alert_date,
                        due_date=obligation.due_date,
                    )
                )
        return alerts

    def schedule(self, obligation: Obligation) -> list[str]:
        """Dispatch Celery tasks for all pending alerts; return task IDs."""
        alerts = self.compute_alerts(obligation)
        task_ids: list[str] = []
        for alert in alerts:
            eta = datetime.combine(alert.alert_date, time(9, 0, 0))
            result = send_obligation_alert.apply_async(
                args=[alert.obligation_id, alert.days_before_due, obligation.contract_id],
                eta=eta,
            )
            task_ids.append(str(result.id))
            logger.info(
                "Scheduled alert: obligation=%s days_before=%s eta=%s",
                alert.obligation_id,
                alert.days_before_due,
                eta.date(),
            )
        return task_ids


@celery_app.task(name="lie.send_obligation_alert", bind=True, max_retries=3)
def send_obligation_alert(
    self,
    obligation_id: str,
    days_until_due: int,
    contract_id: str,
) -> dict:
    """Celery task: send obligation reminder notification."""
    try:
        logger.warning(
            "OBLIGATION ALERT: %s days until due — obligation=%s contract=%s",
            days_until_due,
            obligation_id,
            contract_id,
        )
        # TODO: wire to LINE / email / EA-DIS notification channel
        return {
            "obligation_id": obligation_id,
            "days_until_due": days_until_due,
            "contract_id": contract_id,
            "sent": True,
        }
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
