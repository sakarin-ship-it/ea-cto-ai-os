"""Scoring engine — 5-criterion evaluation, qwen3-8b NLP (sequential), blind lock, z-score.

M5 RULE: technical NLP scoring via qwen3-8b is ALWAYS sequential — never parallel model calls.
BLIND: get_evaluator_scores() enforces isolation — evaluators can only read their own scores.
"""
from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

# shared/lmstudio_client.py must be on PYTHONPATH (added by conftest.py for tests;
# set PYTHONPATH=shared when running uvicorn in production).
from lmstudio_client import chat_complete as _lm_chat

from ea_pip.constants import (
    CRITERIA,
    OUTLIER_ZSCORE_THRESHOLD,
    TECHNICAL_MODEL,
    TIER2_WEIGHTS,
    TIER3_WEIGHTS,
)
from ea_pip.models import Bid, Evaluation, Package, Score, append_audit

# ── Technical NLP scoring (qwen3-8b via lmstudio_client, sequential) ─────────


def _call_technical_nlp(technical_text: str) -> int:
    """Score technical proposal via qwen3-8b. MUST be called sequentially, never in parallel.

    Routes through shared/lmstudio_client.py per CLAUDE.md Rule A.
    """
    system = (
        "You are a procurement technical evaluator. "
        "Score the technical proposal 0-100 on clarity, completeness, "
        "methodology, and innovation. "
        'Respond ONLY with JSON: {"score": <integer 0-100>}'
    )
    raw = _lm_chat(technical_text[:4000], system=system, model=TECHNICAL_MODEL, max_tokens=20)
    try:
        return max(0, min(100, int(json.loads(raw)["score"])))
    except (KeyError, ValueError, json.JSONDecodeError):
        return 0


# ── Price score (pure, no DB) ─────────────────────────────────────────────────


def compute_price_score(bid_amount_satang: int, min_bid_satang: int) -> int:
    """Inverse price score: lowest bid = 100. Returns 0 if bid_amount is 0."""
    if bid_amount_satang <= 0:
        return 0
    return round(100 * min_bid_satang / bid_amount_satang)


def _resolve_min_bid(bid: Bid, session: Session) -> int:
    compliant = (
        session.query(Bid)
        .filter(Bid.package_id == bid.package_id, Bid.is_compliant.is_(True))
        .all()
    )
    amounts = [b.bid_amount_satang for b in compliant] or [bid.bid_amount_satang]
    return min(amounts)


# ── Evaluation submission ─────────────────────────────────────────────────────


@dataclass
class ScoreInput:
    technical_text: str    # raw text for qwen3-8b NLP scoring
    experience_score: int  # 0-100 manual score
    personnel_score: int   # 0-100 manual score
    financial_score: int   # 0-100 manual score


@dataclass
class WeightedScore:
    bid_id: int
    evaluator_id: str
    criterion_scores: dict[str, int]
    weighted_total: float
    is_outlier: bool
    z_score: Optional[float]


def submit_evaluation(
    bid_id: int,
    evaluator_id: str,
    inputs: ScoreInput,
    actor: str,
    session: Session,
) -> Evaluation:
    """Submit and lock an evaluator's scores. Technical criterion scored via qwen3-8b."""
    existing = (
        session.query(Evaluation)
        .filter(Evaluation.bid_id == bid_id, Evaluation.evaluator_id == evaluator_id)
        .first()
    )
    if existing and existing.is_locked:
        raise ValueError(
            f"Evaluation already locked for evaluator '{evaluator_id}' on bid {bid_id}"
        )

    if existing is None:
        evaluation = Evaluation(bid_id=bid_id, evaluator_id=evaluator_id)
        session.add(evaluation)
        session.flush()
    else:
        evaluation = existing
        # Remove prior scores before re-scoring
        session.query(Score).filter(Score.evaluation_id == evaluation.id).delete()

    bid = session.get(Bid, bid_id)
    package = session.get(Package, bid.package_id)

    # Price score — automatic inverse scoring
    min_bid = _resolve_min_bid(bid, session)
    price_score = compute_price_score(bid.bid_amount_satang, min_bid)

    # Technical score — qwen3-8b sequential (M5 rule enforced at call site)
    tech_score = _call_technical_nlp(inputs.technical_text)

    criterion_values: dict[str, int] = {
        "technical": tech_score,
        "experience": inputs.experience_score,
        "personnel": inputs.personnel_score,
        "financial": inputs.financial_score,
        "price": price_score,
    }

    for criterion in CRITERIA:
        session.add(
            Score(
                evaluation_id=evaluation.id,
                criterion=criterion,
                raw_score=criterion_values[criterion],
                is_nlp_scored=(criterion == "technical"),
            )
        )

    evaluation.is_locked = True
    evaluation.locked_at = datetime.now(timezone.utc)

    append_audit(
        session,
        entity_type="evaluation",
        entity_id=evaluation.id,
        action="evaluation_submitted",
        actor=actor,
        payload={
            "bid_id": bid_id,
            "evaluator_id": evaluator_id,
            "criteria": criterion_values,
            "weights_tier": package.procurement_tier,
        },
    )
    return evaluation


# ── BLIND read — evaluator may only access their own scores ───────────────────


def get_evaluator_scores(bid_id: int, evaluator_id: str, session: Session) -> list[Score]:
    """BLIND enforcement: returns only *this* evaluator's scores for the bid.

    It is impossible to access another evaluator's scores through this function.
    Aggregate view is available only via aggregate_scores() once all evals are locked.
    """
    evaluation = (
        session.query(Evaluation)
        .filter(Evaluation.bid_id == bid_id, Evaluation.evaluator_id == evaluator_id)
        .first()
    )
    if evaluation is None:
        return []
    return session.query(Score).filter(Score.evaluation_id == evaluation.id).all()


# ── Aggregate + z-score outlier detection ────────────────────────────────────


def aggregate_scores(package_id: int, session: Session) -> list[WeightedScore]:
    """Compute weighted totals and z-score outlier flags across all locked evaluations."""
    package = session.get(Package, package_id)
    weights = TIER2_WEIGHTS if package.procurement_tier == "TIER2" else TIER3_WEIGHTS

    compliant_bids = (
        session.query(Bid)
        .filter(Bid.package_id == package_id, Bid.is_compliant.is_(True))
        .all()
    )

    results: list[WeightedScore] = []

    for bid in compliant_bids:
        locked_evals = (
            session.query(Evaluation)
            .filter(Evaluation.bid_id == bid.id, Evaluation.is_locked.is_(True))
            .all()
        )
        if not locked_evals:
            continue

        eval_data: list[tuple[Evaluation, float, dict[str, int]]] = []
        for ev in locked_evals:
            score_rows = session.query(Score).filter(Score.evaluation_id == ev.id).all()
            score_map = {s.criterion: s.raw_score for s in score_rows}
            total = sum(weights.get(c, 0) * score_map.get(c, 0) / 100 for c in CRITERIA)
            eval_data.append((ev, total, score_map))

        totals = [t for _, t, _ in eval_data]
        mean_t = statistics.mean(totals) if totals else 0.0
        stdev_t = statistics.stdev(totals) if len(totals) > 1 else 0.0

        for ev, total, score_map in eval_data:
            z = (total - mean_t) / stdev_t if stdev_t > 0 else 0.0
            is_outlier = abs(z) > OUTLIER_ZSCORE_THRESHOLD

            for score_row in session.query(Score).filter(Score.evaluation_id == ev.id).all():
                score_row.z_score = z
                score_row.is_outlier = is_outlier

            results.append(
                WeightedScore(
                    bid_id=bid.id,
                    evaluator_id=ev.evaluator_id,
                    criterion_scores=score_map,
                    weighted_total=total,
                    is_outlier=is_outlier,
                    z_score=z if stdev_t > 0 else None,
                )
            )

    return results
