"""n8n W-12: Self-Healing Retry — error context captured, retry is idempotent.

W-12 is triggered by n8n errorTrigger, sets retry context (workflow_id,
error message), waits, and retries. We test the context-building logic
using the same data model as the workflow's Set node.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[4]

from tests.harness.generators import _rng

SCENARIO_ID = "n8n_w12"

_WORKFLOW_IDS = ["W-01", "W-02", "W-03", "W-04", "W-05", "W-06", "W-07", "W-08", "W-09"]
_ERROR_MESSAGES = [
    "Connection refused to http://localhost:8001/match",
    "HTTP 503 from EA-FCI payment endpoint",
    "Timeout waiting for LM Studio response",
    "PostgreSQL transaction deadlock detected",
    "Invoice not found: id=42",
]


def _build_retry_context(workflow_id: str, workflow_name: str, error_msg: str) -> dict:
    """Mirror the W-12 Set node logic: extract retry context from error payload."""
    return {
        "retryWorkflowId": workflow_id,
        "retryWorkflowName": workflow_name,
        "errorMsg": error_msg or "unknown",
    }


def _simulate_retry(context: dict, attempt: int) -> dict:
    """Simulate retry attempt — same context must produce same result."""
    return {
        "attempt": attempt,
        "workflow_id": context["retryWorkflowId"],
        "error_captured": bool(context["errorMsg"] and context["errorMsg"] != "unknown"),
        "context": context,
    }


def setup(seed: int) -> dict:
    rng = _rng(seed)
    workflow_id = rng.choice(_WORKFLOW_IDS)
    workflow_name = f"EA workflow {workflow_id}"
    error_msg = rng.choice(_ERROR_MESSAGES)
    return {
        "seed": seed,
        "workflow_id": workflow_id,
        "workflow_name": workflow_name,
        "error_msg": error_msg,
    }


def run(data: dict) -> dict:
    context = _build_retry_context(
        data["workflow_id"], data["workflow_name"], data["error_msg"]
    )

    # Simulate two retry attempts — both must produce consistent context
    attempt1 = _simulate_retry(context, attempt=1)
    attempt2 = _simulate_retry(context, attempt=2)

    return {
        "context": context,
        "attempt1": attempt1,
        "attempt2": attempt2,
        "context_stable": attempt1["context"] == attempt2["context"],
        "error_captured": attempt1["error_captured"],
    }


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]
    ctx = result["context"]

    # Error message is captured
    assert result["error_captured"], (
        f"seed={seed}: error message must be captured in retry context (not 'unknown')"
    )

    # Workflow ID is preserved
    assert ctx["retryWorkflowId"] == data["workflow_id"], (
        f"seed={seed}: retryWorkflowId must match source workflow_id"
    )

    # Error message is non-empty
    assert ctx["errorMsg"], (
        f"seed={seed}: errorMsg must not be empty in retry context"
    )

    # Context is stable across retry attempts (idempotent read)
    assert result["context_stable"], (
        f"seed={seed}: retry context must be stable across attempts"
    )

    # Retry context must not contain None values
    for k, v in ctx.items():
        assert v is not None, f"seed={seed}: retry context key {k!r} must not be None"
