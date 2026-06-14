"""Celery worker for EA-FCI background tasks.

concurrency=2 enforced for M5 16GB memory safety.
Beat schedule: FX rate fetch daily at 09:00 Bangkok; anomaly detection hourly.
"""
from __future__ import annotations

import logging

from celery import Celery
from celery.schedules import crontab

logger = logging.getLogger(__name__)

celery_app = Celery("fci", broker="redis://localhost:6379/0")
celery_app.conf.update(
    worker_concurrency=2,
    timezone="Asia/Bangkok",
    enable_utc=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
)

celery_app.conf.beat_schedule = {
    "fetch-fx-rates-daily": {
        "task": "fci.worker.fetch_fx_rates_task",
        "schedule": crontab(hour=9, minute=0),
    },
    "anomaly-detection-hourly": {
        "task": "fci.worker.anomaly_detection_task",
        "schedule": 3600.0,
    },
}


@celery_app.task(name="fci.worker.fetch_fx_rates_task")
def fetch_fx_rates_task() -> dict:
    """Fetch BOT daily average rates for major currencies and store them."""
    from fci.db import SessionLocal
    from fci.fx_monitor import fetch_and_store_rate

    currencies = ["USD", "EUR", "CNY", "JPY", "SGD"]
    session = SessionLocal()
    results: dict[str, str] = {}
    try:
        for currency in currencies:
            try:
                fetch_and_store_rate(currency, session)
                results[currency] = "ok"
            except Exception as exc:
                logger.error("FX fetch failed for %s: %s", currency, exc)
                results[currency] = f"error: {exc}"
        session.commit()
    finally:
        session.close()
    return results


@celery_app.task(name="fci.worker.anomaly_detection_task")
def anomaly_detection_task() -> int:
    """Detect anomalous invoices and store AnomalyFlag records."""
    from fci.anomaly_detector import detect_and_flag_anomalies
    from fci.db import SessionLocal

    session = SessionLocal()
    try:
        count = detect_and_flag_anomalies(session)
        logger.info("Anomaly detection: %d invoices flagged", count)
        return count
    finally:
        session.close()
