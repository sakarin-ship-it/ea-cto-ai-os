"""EA-PIP: full API lifecycle (TestClient) —
auth → supplier → package → EOI → bid → compliance → evaluate → aggregate → award → accept.
"""
from __future__ import annotations

import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_ROOT / "apps/ea-pip"), str(_ROOT / "shared")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.harness.generators import _rng

SCENARIO_ID = "pip_api_loop"

# Serialize concurrent iterations — app.dependency_overrides and os.environ are global state
_LOCK = threading.Lock()


# ── Stateful in-memory DB mock ─────────────────────────────────────────────


class _StateDB:
    """Tracks ORM objects across API requests for the PIP harness session."""

    def __init__(self):
        self._store: dict[str, dict[int, object]] = {}
        self._pending: list = []
        self._ctr = 1

    def _next_id(self) -> int:
        i = self._ctr
        self._ctr += 1
        return i

    def make_session(self):
        state = self

        class _Q:
            def __init__(self, cls_name: str):
                self._n = cls_name
                self._lim: int | None = None

            def filter(self, *_):
                return self

            def order_by(self, *_):
                return self

            def with_for_update(self):
                return self

            def limit(self, n: int):
                self._lim = n
                return self

            def desc(self):
                return self

            def delete(self):
                return 0

            def count(self):
                return len(state._store.get(self._n, {}))

            def all(self):
                items = list(state._store.get(self._n, {}).values())
                return items[: self._lim] if self._lim else items

            def first(self):
                # Supplier/Evaluation/AuditLog: always None so duplicate-checks and
                # chain-starts work correctly for a fresh lifecycle.
                if self._n in ("AuditLog", "Evaluation", "Supplier"):
                    return None
                items = list(state._store.get(self._n, {}).values())
                return items[0] if items else None

        class _S:
            def add(self, obj):
                state._pending.append(obj)

            def flush(self):
                from datetime import datetime, timezone
                now = datetime.now(timezone.utc)
                for obj in state._pending[:]:
                    if getattr(obj, "id", None) is None:
                        obj.id = state._next_id()
                    # Apply datetime column defaults (SA only applies these on real INSERT)
                    for attr in ("created_at", "updated_at", "submitted_at", "locked_at"):
                        try:
                            if getattr(obj, attr, "SENTINEL") is None:
                                setattr(obj, attr, now)
                        except Exception:
                            pass
                    cls = type(obj).__name__
                    state._store.setdefault(cls, {})[obj.id] = obj
                state._pending.clear()

            def commit(self):
                self.flush()

            def close(self):
                pass

            def get(self, cls, pk):
                return state._store.get(cls.__name__, {}).get(pk)

            def query(self, cls):
                n = cls.__name__ if hasattr(cls, "__name__") else str(cls)
                return _Q(n)

        return _S()


# ── Helper: Thai TIN ───────────────────────────────────────────────────────


def _tax_id(seed: int, idx: int) -> str:
    """Deterministic 13-digit Thai TIN from seed + index."""
    n = (seed * 1000 + idx * 100 + 1) % (10**12)
    return str(n + 10**12)  # always exactly 13 digits


# ── Scenario functions ─────────────────────────────────────────────────────


def setup(seed: int) -> dict:
    rng = _rng(seed)
    estimate = rng.randint(10_000_000_00, 50_000_000_00)
    bond_required = estimate * 5 // 100
    n_suppliers = 3

    suppliers = [
        {
            "name_en": f"Supplier {seed}-{i}",
            "tax_id": _tax_id(seed, i),
            "contact_email": f"contact{i}@supplier{seed}.test",
        }
        for i in range(n_suppliers)
    ]
    bids = [
        {
            "bid_amount_satang": int(estimate * rng.uniform(0.88, 1.15)),
            "bid_bond_amount_satang": bond_required + rng.randint(1_00, 1_000_00),
        }
        for _ in range(n_suppliers)
    ]
    return {
        "seed": seed,
        "estimate": estimate,
        "package_no": f"PKG-HARNESS-{seed:06d}",
        "suppliers": suppliers,
        "bids": bids,
    }


def run(data: dict) -> dict:
    api_key = f"harness-pip-key-{data['seed']}"

    # Lazy import after path is set up
    from ea_pip.api import app
    from ea_pip.db import get_session

    state = _StateDB()

    def _override_session():
        return state.make_session()

    headers = {"X-API-Key": api_key}
    results: dict = {}

    dbd_result = MagicMock()
    dbd_result.status.value = "ACTIVE"
    dbd_result.dbd_reg_no = "DBD-MOCK"
    dbd_result.company_name_th = "บริษัท ทดสอบ จำกัด"
    dbd_result.verified_at = datetime.now(timezone.utc)

    nlp_response = '{"score": 75}'

    env_patch = {"PIP_API_KEY": api_key}

    with _LOCK, \
         patch("ea_pip.api.init_schema"), \
         patch.dict(os.environ, env_patch), \
         patch("ea_pip.supplier_registry.verify_with_dbd", return_value=dbd_result), \
         patch("ea_pip.scoring_engine._lm_chat", return_value=nlp_response):

        app.dependency_overrides[get_session] = _override_session

        try:
            from fastapi.testclient import TestClient
            with TestClient(app, raise_server_exceptions=True) as client:

                # ── Auth guard ────────────────────────────────────────────
                r = client.post("/suppliers", json=data["suppliers"][0])
                results["auth_no_key_status"] = r.status_code  # no X-API-Key header

                r = client.post(
                    "/suppliers",
                    json=data["suppliers"][0],
                    headers={"X-API-Key": "WRONG-KEY"},
                )
                results["auth_wrong_key_status"] = r.status_code

                # ── Create suppliers ──────────────────────────────────────
                supplier_ids = []
                for sup in data["suppliers"]:
                    r = client.post("/suppliers", json=sup, headers=headers)
                    results.setdefault("supplier_statuses", []).append(r.status_code)
                    if r.status_code == 201:
                        supplier_ids.append(r.json()["id"])
                        results.setdefault("supplier_dbd_statuses", []).append(
                            r.json()["dbd_status"]
                        )
                results["supplier_ids"] = supplier_ids

                # ── Create package ────────────────────────────────────────
                deadline = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
                pkg_body = {
                    "package_no": data["package_no"],
                    "title_en": f"Harness Package {data['seed']}",
                    "title_th": "แพ็คเกจทดสอบ",
                    "procurement_tier": "TIER2",
                    "engineer_estimate_satang": data["estimate"],
                    "submission_deadline": deadline,
                    "scope_en": "Harness test scope.",
                }
                r = client.post("/packages", json=pkg_body, headers=headers)
                results["package_status"] = r.status_code
                pkg_id = r.json()["id"] if r.status_code == 201 else None
                results["package_no_returned"] = r.json().get("package_no") if r.status_code == 201 else None

                # ── EOI and shortlist ─────────────────────────────────────
                eoi_ids = []
                if pkg_id and supplier_ids:
                    for sid in supplier_ids:
                        r = client.post(
                            f"/packages/{pkg_id}/eoi",
                            json={"supplier_id": sid},
                            headers=headers,
                        )
                        results.setdefault("eoi_statuses", []).append(r.status_code)
                        if r.status_code == 201:
                            eoi_ids.append(r.json()["eoi_id"])
                    for eid in eoi_ids:
                        r = client.post(
                            f"/packages/{pkg_id}/eoi/{eid}/shortlist",
                            headers=headers,
                        )
                        results.setdefault("shortlist_statuses", []).append(r.status_code)

                # ── Submit bids ───────────────────────────────────────────
                bid_ids = []
                if pkg_id and supplier_ids:
                    for i, (sid, bid_data) in enumerate(
                        zip(supplier_ids, data["bids"])
                    ):
                        r = client.post(
                            "/bids",
                            json={
                                "package_id": pkg_id,
                                "supplier_id": sid,
                                **bid_data,
                            },
                            headers=headers,
                        )
                        results.setdefault("bid_statuses", []).append(r.status_code)
                        if r.status_code == 201:
                            bid_ids.append(r.json()["id"])
                results["bid_ids"] = bid_ids

                # ── Bid rejection: past-deadline package ──────────────────
                past_deadline = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
                r = client.post(
                    "/packages",
                    json={**pkg_body,
                          "package_no": data["package_no"] + "-EXPIRED",
                          "submission_deadline": past_deadline},
                    headers=headers,
                )
                if r.status_code == 201:
                    expired_pkg_id = r.json()["id"]
                    r2 = client.post(
                        "/bids",
                        json={
                            "package_id": expired_pkg_id,
                            "supplier_id": supplier_ids[0] if supplier_ids else 1,
                            "bid_amount_satang": data["bids"][0]["bid_amount_satang"],
                            "bid_bond_amount_satang": data["bids"][0]["bid_bond_amount_satang"],
                        },
                        headers=headers,
                    )
                    results["bid_past_deadline_status"] = r2.status_code

                # ── Compliance check ──────────────────────────────────────
                compliance_results = []
                for bid_id in bid_ids:
                    r = client.post(
                        f"/bids/{bid_id}/compliance", headers=headers
                    )
                    if r.status_code == 200:
                        body = r.json()
                        compliance_results.append({
                            "status": r.status_code,
                            "is_compliant": body["is_compliant"],
                            "is_alb_flagged": body["is_alb_flagged"],
                        })
                results["compliance"] = compliance_results

                # ── Evaluate first bid ────────────────────────────────────
                eval_result = {}
                if bid_ids:
                    r = client.post(
                        f"/bids/{bid_ids[0]}/evaluate",
                        json={
                            "technical_text": "Our methodology is sound and innovative.",
                            "experience_score": 80,
                            "personnel_score": 75,
                            "financial_score": 70,
                        },
                        headers={**headers, "X-Evaluator-Id": "eval-harness-01"},
                    )
                    eval_result["status"] = r.status_code
                    if r.status_code == 200:
                        eval_result["evaluation_id"] = r.json()["evaluation_id"]
                        eval_result["is_locked"] = r.json()["is_locked"]
                results["evaluation"] = eval_result

                # ── Get scores for evaluator ──────────────────────────────
                if bid_ids:
                    r = client.get(
                        f"/bids/{bid_ids[0]}/scores",
                        headers={**headers, "X-Evaluator-Id": "eval-harness-01"},
                    )
                    results["get_scores_status"] = r.status_code

                # ── Aggregate scores ──────────────────────────────────────
                if pkg_id:
                    r = client.get(
                        f"/packages/{pkg_id}/scores/aggregate", headers=headers
                    )
                    results["aggregate_status"] = r.status_code
                    if r.status_code == 200:
                        results["aggregate_count"] = len(r.json().get("scores", []))

                # ── Create award ──────────────────────────────────────────
                award_result = {}
                if pkg_id and bid_ids:
                    r = client.post(
                        f"/packages/{pkg_id}/award",
                        json={"preferred_bid_id": bid_ids[0]},
                        headers=headers,
                    )
                    award_result["status"] = r.status_code
                    if r.status_code == 201:
                        award_result["award_id"] = r.json()["award_id"]
                        award_result["letter_ref"] = r.json()["letter_ref"]
                results["award"] = award_result

                # ── Accept award ──────────────────────────────────────────
                accept_result = {}
                if award_result.get("award_id"):
                    r = client.post(
                        f"/awards/{award_result['award_id']}/accept",
                        headers=headers,
                    )
                    accept_result["status"] = r.status_code
                    if r.status_code == 200:
                        accept_result["award_status"] = r.json()["status"]
                results["accept"] = accept_result

                # ── Audit log ─────────────────────────────────────────────
                r = client.get("/audit_log", headers=headers)
                results["audit_log_status"] = r.status_code
                if r.status_code == 200:
                    results["audit_log_count"] = len(r.json().get("entries", []))

        finally:
            app.dependency_overrides.clear()

    return results


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    # Auth enforcement
    assert result.get("auth_no_key_status") in (401, 403, 422), (
        f"seed={seed}: missing API key must return 401/403/422, "
        f"got {result.get('auth_no_key_status')}"
    )
    assert result.get("auth_wrong_key_status") == 401, (
        f"seed={seed}: wrong API key must return 401, "
        f"got {result.get('auth_wrong_key_status')}"
    )

    # Suppliers
    sup_statuses = result.get("supplier_statuses", [])
    assert len(sup_statuses) == 3, f"seed={seed}: expected 3 supplier requests"
    assert all(s == 201 for s in sup_statuses), (
        f"seed={seed}: all supplier creates must return 201, got {sup_statuses}"
    )
    assert all(
        s == "ACTIVE" for s in result.get("supplier_dbd_statuses", [])
    ), f"seed={seed}: mocked DBD must return ACTIVE"

    # Package
    assert result.get("package_status") == 201, (
        f"seed={seed}: package create must return 201"
    )
    assert result.get("package_no_returned") == data["package_no"], (
        f"seed={seed}: package_no in response must match requested"
    )

    # EOI + shortlist
    eoi_statuses = result.get("eoi_statuses", [])
    assert len(eoi_statuses) == 3, f"seed={seed}: expected 3 EOI requests"
    assert all(s == 201 for s in eoi_statuses), (
        f"seed={seed}: all EOI submits must return 201"
    )
    shortlist_statuses = result.get("shortlist_statuses", [])
    assert all(s == 200 for s in shortlist_statuses), (
        f"seed={seed}: all shortlist ops must return 200"
    )

    # Bids within deadline
    bid_statuses = result.get("bid_statuses", [])
    assert len(bid_statuses) == 3, f"seed={seed}: expected 3 bid requests"
    assert all(s == 201 for s in bid_statuses), (
        f"seed={seed}: all bids submitted before deadline must return 201"
    )

    # Bid rejected after deadline
    assert result.get("bid_past_deadline_status") == 422, (
        f"seed={seed}: bid after deadline must return 422, "
        f"got {result.get('bid_past_deadline_status')}"
    )

    # Compliance (bids have no docs → NON_COMPLIANT, but response must be 200)
    compliance = result.get("compliance", [])
    assert len(compliance) == 3, f"seed={seed}: expected 3 compliance results"
    for c in compliance:
        assert c["status"] == 200, f"seed={seed}: compliance endpoint must return 200"
        assert isinstance(c["is_compliant"], bool), (
            f"seed={seed}: is_compliant must be bool"
        )
        assert isinstance(c["is_alb_flagged"], bool), (
            f"seed={seed}: is_alb_flagged must be bool"
        )

    # Evaluation
    ev = result.get("evaluation", {})
    assert ev.get("status") == 200, (
        f"seed={seed}: evaluate must return 200, got {ev.get('status')}"
    )
    assert ev.get("is_locked") is True, (
        f"seed={seed}: evaluation must be locked immediately after submit"
    )

    # Get scores
    assert result.get("get_scores_status") == 200, (
        f"seed={seed}: GET /bids/{{id}}/scores must return 200"
    )

    # Aggregate scores
    assert result.get("aggregate_status") == 200, (
        f"seed={seed}: aggregate scores must return 200"
    )
    assert result.get("aggregate_count", 0) >= 1, (
        f"seed={seed}: aggregate must include ≥1 score result"
    )

    # Award
    award = result.get("award", {})
    assert award.get("status") == 201, (
        f"seed={seed}: award create must return 201, got {award.get('status')}"
    )
    letter_ref = award.get("letter_ref", "")
    assert data["package_no"] in letter_ref, (
        f"seed={seed}: letter_ref {letter_ref!r} must contain package_no"
    )

    # Accept
    accept = result.get("accept", {})
    assert accept.get("status") == 200, (
        f"seed={seed}: award accept must return 200, got {accept.get('status')}"
    )
    assert accept.get("award_status") == "ACCEPTED", (
        f"seed={seed}: accepted award status must be ACCEPTED"
    )

    # Audit log — must have entries created during the lifecycle
    assert result.get("audit_log_status") == 200, (
        f"seed={seed}: GET /audit_log must return 200"
    )
    assert result.get("audit_log_count", 0) >= 5, (
        f"seed={seed}: audit log must have ≥5 entries after full lifecycle, "
        f"got {result.get('audit_log_count')}"
    )
