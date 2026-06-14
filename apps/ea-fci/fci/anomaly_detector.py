"""Anomaly detection via Isolation Forest (scikit-learn).

sklearn is lazy-imported so it does not consume memory when unused (M5 rule).
Features per invoice: [amount_thb_satang, qty_billed, unit_price_satang].
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
    index: int
    is_anomaly: bool
    score: float   # raw isolation-forest score; more negative = more anomalous


def detect_anomalies(
    features: list[list[float]],
    contamination: float = 0.05,
    random_state: int = 42,
) -> list[AnomalyResult]:
    """Run Isolation Forest on a feature matrix.  Returns one result per row."""
    if not features:
        return []

    from sklearn.ensemble import IsolationForest  # lazy import

    clf = IsolationForest(
        contamination=contamination,
        random_state=random_state,
        n_estimators=100,
    )
    preds = clf.fit_predict(features)
    scores = clf.score_samples(features)

    return [
        AnomalyResult(index=i, is_anomaly=(int(p) == -1), score=float(s))
        for i, (p, s) in enumerate(zip(preds, scores))
    ]


def build_invoice_features(invoices: list) -> list[list[float]]:
    """Extract numeric feature vectors from Invoice ORM objects."""
    return [
        [
            float(inv.amount_thb_satang),
            float(inv.qty_billed),
            float(inv.unit_price_satang),
        ]
        for inv in invoices
    ]


def detect_and_flag_anomalies(session, contamination: float = 0.05) -> int:
    """Full pipeline: load unpaid invoices → detect anomalies → store flags.

    Returns the number of invoices flagged.
    Skips if fewer than 5 invoices (Isolation Forest is unreliable on tiny sets).
    """
    from fci.models import AnomalyFlag, Invoice

    invoices = session.query(Invoice).filter(Invoice.status != "PAID").all()
    if len(invoices) < 5:
        logger.info("Skipping anomaly detection — fewer than 5 invoices (%d)", len(invoices))
        return 0

    features = build_invoice_features(invoices)
    results = detect_anomalies(features, contamination=contamination)
    flagged = 0

    for inv, result in zip(invoices, results):
        if result.is_anomaly:
            flag = AnomalyFlag(
                entity_type="invoice",
                entity_id=inv.id,
                score=result.score,
                is_anomaly=True,
                features={
                    "amount_thb_satang": inv.amount_thb_satang,
                    "qty_billed": float(inv.qty_billed),
                    "unit_price_satang": inv.unit_price_satang,
                },
            )
            session.add(flag)
            flagged += 1

    session.commit()
    return flagged
