"""Tests for anomaly_detector (Isolation Forest).

sklearn is required. Tests use deterministic random_state=42.
"""
from __future__ import annotations

from fci.anomaly_detector import AnomalyResult, detect_anomalies

# ─── basic contract ───────────────────────────────────────────────────────────

def test_empty_features_returns_empty():
    assert detect_anomalies([]) == []


def test_returns_one_result_per_row():
    features = [[float(i), float(i), float(i)] for i in range(20)]
    results = detect_anomalies(features, contamination=0.05)
    assert len(results) == 20


def test_result_fields_typed_correctly():
    features = [[100.0, 200.0, 300.0]] * 20
    results = detect_anomalies(features, contamination=0.05)
    for r in results:
        assert isinstance(r, AnomalyResult)
        assert isinstance(r.index, int)
        assert isinstance(r.is_anomaly, bool)
        assert isinstance(r.score, float)


def test_index_matches_row_position():
    features = [[float(i)] * 3 for i in range(15)]
    results = detect_anomalies(features, contamination=0.05)
    for i, r in enumerate(results):
        assert r.index == i


# ─── obvious outlier detection ────────────────────────────────────────────────

def test_obvious_anomalies_flagged():
    """18 tight-cluster rows + 2 extreme outliers → outliers flagged."""
    normal = [[100.0, 100.0, 100.0]] * 18
    outliers = [[1_000_000_000.0, 1_000_000_000.0, 1_000_000_000.0]] * 2
    results = detect_anomalies(normal + outliers, contamination=0.1, random_state=42)

    assert results[-1].is_anomaly is True, "Last row (outlier) must be flagged"
    assert results[-2].is_anomaly is True, "Second-to-last row (outlier) must be flagged"


def test_obvious_anomalies_have_lower_score():
    """Anomalous rows should have more negative scores than normal rows."""
    normal = [[100.0, 100.0, 100.0]] * 18
    outliers = [[1_000_000_000.0, 1_000_000_000.0, 1_000_000_000.0]] * 2
    results = detect_anomalies(normal + outliers, contamination=0.1, random_state=42)

    normal_scores = [r.score for r in results[:18]]
    outlier_scores = [r.score for r in results[18:]]
    assert max(outlier_scores) < min(normal_scores)


# ─── contamination behaviour ─────────────────────────────────────────────────

def test_contamination_bounds_anomaly_count():
    """IsolationForest flags approximately contamination% of rows."""
    n = 100
    features = [[float(i), float(i * 2), float(i * 3)] for i in range(n)]
    contamination = 0.1
    results = detect_anomalies(features, contamination=contamination, random_state=42)
    flagged = sum(1 for r in results if r.is_anomaly)
    # sklearn guarantees exactly floor(n * contamination) = 10 for fit_predict
    assert flagged == int(n * contamination)


# ─── single row edge case ─────────────────────────────────────────────────────

def test_single_row_does_not_crash():
    """One-row feature matrix should not raise (IsolationForest handles it)."""
    results = detect_anomalies([[1.0, 2.0, 3.0]], contamination=0.5)
    assert len(results) == 1
