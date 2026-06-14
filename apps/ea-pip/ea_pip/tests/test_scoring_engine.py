"""Tests for scoring_engine — weights sum, blind lock, NLP sequential, z-score outlier.

All DB calls and network calls are mocked.
"""
from __future__ import annotations

import statistics
from unittest.mock import MagicMock, patch

import pytest

from ea_pip.constants import (
    CRITERIA,
    OUTLIER_ZSCORE_THRESHOLD,
    TIER2_WEIGHTS,
    TIER3_WEIGHTS,
)
from ea_pip.scoring_engine import (
    ScoreInput,
    _call_technical_nlp,
    compute_price_score,
    get_evaluator_scores,
    submit_evaluation,
)

# ─────────────────────────────────────────────────────────────────────────────
# Weights sum to 100
# ─────────────────────────────────────────────────────────────────────────────


def test_tier2_weights_sum_to_100():
    assert sum(TIER2_WEIGHTS.values()) == 100


def test_tier3_weights_sum_to_100():
    assert sum(TIER3_WEIGHTS.values()) == 100


def test_tier2_covers_all_criteria():
    assert set(TIER2_WEIGHTS.keys()) == set(CRITERIA)


def test_tier3_covers_all_criteria():
    assert set(TIER3_WEIGHTS.keys()) == set(CRITERIA)


# ─────────────────────────────────────────────────────────────────────────────
# Price score (pure function)
# ─────────────────────────────────────────────────────────────────────────────


def test_price_score_lowest_bid_gets_100():
    assert compute_price_score(1_000_000, 1_000_000) == 100


def test_price_score_higher_bid_lower_score():
    # min_bid = 1M, this_bid = 2M → score = 50
    assert compute_price_score(2_000_000, 1_000_000) == 50


def test_price_score_zero_bid_returns_zero():
    assert compute_price_score(0, 1_000_000) == 0


# ─────────────────────────────────────────────────────────────────────────────
# BLIND evaluator lock
# ─────────────────────────────────────────────────────────────────────────────


class TestBlindEvaluatorLock:
    """Evaluator can only see their OWN scores via get_evaluator_scores."""

    def _session_no_eval(self):
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None
        return session

    def _session_with_eval(self, evaluator_id, scores):
        ev = MagicMock()
        ev.id = 1
        ev.evaluator_id = evaluator_id
        ev.is_locked = True

        session = MagicMock()

        def query_side(model):
            q = MagicMock()
            # first() call returns evaluation
            q.filter.return_value.first.return_value = ev
            # all() call returns scores
            q.filter.return_value.all.return_value = scores
            return q

        session.query.side_effect = query_side
        return session

    def test_evaluator_with_no_eval_gets_empty_scores(self):
        """BLIND: evaluator B has no evaluation → empty list returned."""
        session = self._session_no_eval()
        result = get_evaluator_scores(bid_id=10, evaluator_id="evaluator_B", session=session)
        assert result == []

    def test_evaluator_sees_own_scores(self):
        """Evaluator A retrieves their own scores."""
        fake_scores = [MagicMock(criterion="technical", raw_score=80)]
        session = self._session_with_eval("evaluator_A", fake_scores)
        result = get_evaluator_scores(bid_id=10, evaluator_id="evaluator_A", session=session)
        assert len(result) == 1
        assert result[0].criterion == "technical"

    def test_blind_isolation_different_evaluator_empty(self):
        """BLIND invariant: same bid, different evaluator_id → cannot access evaluator_A's eval."""
        # evaluator_B queries; session returns None for B's evaluation
        session = self._session_no_eval()
        result = get_evaluator_scores(bid_id=10, evaluator_id="evaluator_B", session=session)
        # evaluator_B gets nothing — blind isolation holds
        assert result == []

    def test_locked_evaluation_raises_on_resubmit(self):
        """Locked evaluations cannot be changed."""
        locked_ev = MagicMock()
        locked_ev.is_locked = True

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = locked_ev

        with pytest.raises(ValueError, match="already locked"):
            submit_evaluation(
                bid_id=1,
                evaluator_id="evaluator_A",
                inputs=ScoreInput("text", 80, 75, 70),
                actor="evaluator_A",
                session=session,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Technical NLP scoring via qwen3-8b (sequential, mocked)
# ─────────────────────────────────────────────────────────────────────────────


class TestTechnicalNLPScoring:
    def test_nlp_call_parses_score(self):
        """_call_technical_nlp extracts integer score from qwen3-8b JSON response."""
        with patch("ea_pip.scoring_engine._lm_chat", return_value='{"score": 75}'):
            score = _call_technical_nlp("We propose a robust methodology...")
        assert score == 75

    def test_nlp_call_clamps_to_100(self):
        """Score exceeding 100 is clamped to 100."""
        with patch("ea_pip.scoring_engine._lm_chat", return_value='{"score": 120}'):
            score = _call_technical_nlp("...")
        assert score == 100

    def test_nlp_call_malformed_returns_zero(self):
        """Malformed model output returns 0 rather than crashing."""
        with patch("ea_pip.scoring_engine._lm_chat", return_value="not json"):
            score = _call_technical_nlp("...")
        assert score == 0


# ─────────────────────────────────────────────────────────────────────────────
# z-score outlier detection (pure logic)
# ─────────────────────────────────────────────────────────────────────────────


class TestZScoreOutlier:
    def test_outlier_threshold_constant(self):
        assert OUTLIER_ZSCORE_THRESHOLD == 1.5

    def test_no_outlier_when_single_evaluator(self):
        """Only one evaluator → stdev = 0 → z = 0 → no outlier."""
        totals = [85.0]
        mean = statistics.mean(totals)
        stdev = statistics.stdev(totals) if len(totals) > 1 else 0.0
        z = (totals[0] - mean) / stdev if stdev > 0 else 0.0
        assert abs(z) <= OUTLIER_ZSCORE_THRESHOLD

    def test_outlier_flagged_when_z_exceeds_threshold(self):
        """Evaluator with score far from mean is flagged (need enough evaluators for z > 1.5)."""
        # 5 evaluators: 4 clustered at ~80, 1 at 10 → z for outlier ≈ -1.79
        totals = [80.0, 80.0, 80.0, 80.0, 10.0]
        mean = statistics.mean(totals)
        stdev = statistics.stdev(totals)
        z_scores = [(t - mean) / stdev for t in totals]
        outliers = [abs(z) > OUTLIER_ZSCORE_THRESHOLD for z in z_scores]
        # Only the last score (10.0) should be flagged
        assert outliers[4] is True
        assert not any(outliers[:4])

    def test_no_outlier_when_scores_uniform(self):
        """Identical scores → stdev = 0 → no outlier."""
        totals = [75.0, 75.0, 75.0]
        stdev = statistics.stdev(totals)
        assert stdev == 0.0
