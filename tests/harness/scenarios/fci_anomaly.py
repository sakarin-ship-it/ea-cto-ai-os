"""EA-FCI: anomaly detector always flags the planted outlier."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]
if str(_ROOT / "apps/ea-fci") not in sys.path:
    sys.path.insert(0, str(_ROOT / "apps/ea-fci"))

from fci.anomaly_detector import AnomalyResult, detect_anomalies

from tests.harness.generators import anomaly_feature_matrix

SCENARIO_ID = "fci_anomaly"

_N_NORMAL = 20  # ensures IsolationForest has enough data


def setup(seed: int) -> dict:
    features = anomaly_feature_matrix(seed, n_normal=_N_NORMAL)
    return {
        "seed": seed,
        "features": features,
        "outlier_index": 0,
        "n_total": len(features),
    }


def run(data: dict) -> dict:
    results = detect_anomalies(
        data["features"],
        contamination=0.10,   # 10% contamination to ensure outlier is caught
        random_state=data["seed"] % 1000,
    )
    return {
        "results_count": len(results),
        "outlier_is_anomaly": results[0].is_anomaly if results else None,
        "outlier_score": results[0].score if results else None,
        "any_anomaly": any(r.is_anomaly for r in results),
        "indices": [r.index for r in results],
    }


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    # Result count matches input count
    assert result["results_count"] == data["n_total"], (
        f"seed={seed}: expected {data['n_total']} results, got {result['results_count']}"
    )

    # Indices are correct (0-based)
    assert result["indices"] == list(range(data["n_total"])), (
        f"seed={seed}: anomaly result indices must be sequential 0..n-1"
    )

    # The planted outlier at index 0 must be flagged
    assert result["outlier_is_anomaly"] is True, (
        f"seed={seed}: planted outlier at index 0 must be flagged as anomaly. "
        f"score={result['outlier_score']}"
    )

    # At least one anomaly must be found
    assert result["any_anomaly"], (
        f"seed={seed}: detect_anomalies must find at least one anomaly in the matrix"
    )
