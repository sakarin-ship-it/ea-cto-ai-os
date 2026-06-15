"""EA-FCI: full API lifecycle (TestClient) —
PO → GRN/Invoice pre-seed → 3-way match → payment BLOCKED (no TAC) →
TAC upload → payment APPROVED → LD calculate → audit log.
"""
from __future__ import annotations

import sys
import threading
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_ROOT / "apps/ea-fci"), str(_ROOT / "shared")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.harness.generators import _rng, ld_scenario

SCENARIO_ID = "fci_api_loop"

# Serialize concurrent iterations — app.dependency_overrides is global state
_LOCK = threading.Lock()


# ── Stateful in-memory DB mock ─────────────────────────────────────────────


class _StateDB:
    def __init__(self):
        self._store: dict[str, dict[int, object]] = {}
        self._pending: list = []
        self._ctr = 1

    def _next_id(self) -> int:
        i = self._ctr
        self._ctr += 1
        return i

    def seed_obj(self, obj, obj_id: int) -> None:
        """Directly insert a pre-built ORM object into the store."""
        obj.id = obj_id
        cls = type(obj).__name__
        self._store.setdefault(cls, {})[obj_id] = obj
        if obj_id >= self._ctr:
            self._ctr = obj_id + 1

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
                # AuditLog: always None (fresh chain)
                if self._n == "AuditLog":
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
                    for attr in ("created_at", "updated_at"):
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


# ── Scenario functions ─────────────────────────────────────────────────────


def setup(seed: int) -> dict:
    rng = _rng(seed)
    qty = rng.randint(10, 500)
    unit_price = rng.randint(10_000_00, 5_000_000_00)
    total_satang = qty * unit_price
    ld = ld_scenario(seed)
    return {
        "seed": seed,
        "po_number": f"PO-HARNESS-{seed:06d}",
        "supplier_name": f"Harness Supplier {seed}",
        "qty": qty,
        "unit_price_satang": unit_price,
        "total_satang": total_satang,
        "ld_contract_satang": ld.contract_value_satang,
        "ld_rate_bps": ld.daily_rate_bps,
        "ld_delay_days": ld.delay_days,
        "ld_cap_pct": ld.cap_pct,
    }


def run(data: dict) -> dict:
    from fci.api import app
    from fci.db import get_session

    state = _StateDB()

    # Pre-seed GRN and Invoice using MagicMock — no API endpoints exist for these.
    # The /purchase_orders endpoint always creates PO with qty_ordered=Decimal("1") and
    # unit_price_satang=total_satang, so GRN and Invoice must match those values for MATCH.
    grn = MagicMock()
    grn.id = 1
    grn.po_id = 1
    grn.qty_received = Decimal("1")           # matches PO.qty_ordered set by API
    state._store.setdefault("GRN", {})[1] = grn
    state._ctr = 2  # next auto-id starts at 2

    invoice = MagicMock()
    invoice.id = 1
    invoice.po_id = 1
    invoice.grn_id = 1
    invoice.qty_billed = Decimal("1")         # matches PO.qty_ordered
    invoice.unit_price_satang = data["total_satang"]  # matches PO.unit_price_satang
    invoice.amount_thb_satang = data["total_satang"]
    invoice.is_milestone = True
    invoice.is_equipment = False
    invoice.has_chinese_content = False
    state._store.setdefault("Invoice", {})[1] = invoice

    results: dict = {}

    def _override_session():
        return state.make_session()

    with _LOCK, patch("fci.api.init_schema"):
        app.dependency_overrides[get_session] = _override_session
        try:
            from fastapi.testclient import TestClient
            with TestClient(app, raise_server_exceptions=True) as client:

                # ── Create PO ────────────────────────────────────────────
                r = client.post(
                    "/purchase_orders",
                    json={
                        "po_number": data["po_number"],
                        "supplier": data["supplier_name"],
                        "total_satang": data["total_satang"],
                        "currency": "THB",
                        "source": "EA-PIP",
                    },
                )
                results["po_status"] = r.status_code
                po_id = r.json().get("id") if r.status_code == 201 else None
                results["po_id"] = po_id

                # ── Three-way match (use actual PO id from API response) ──
                r = client.post(
                    f"/match/1?po_id={po_id or 1}&grn_id=1",
                )
                results["match_status"] = r.status_code
                if r.status_code == 200:
                    results["match_result"] = r.json()["status"]

                # ── Payment BLOCKED (milestone invoice, no TAC yet) ───────
                r = client.post(
                    "/payment/initiate",
                    json={
                        "invoice_id": 1,
                        "amount_satang": data["total_satang"],
                        "approved_by": "cto@harness.test",
                    },
                )
                results["payment_no_tac_status"] = r.status_code
                if r.status_code == 200:
                    body = r.json()
                    results["payment_no_tac_blocked"] = body.get("status") == "BLOCKED"
                    results["payment_no_tac_block_reason"] = body.get("block_reason", "")

                # ── Upload TAC ────────────────────────────────────────────
                r = client.post(
                    "/tac",
                    json={
                        "po_id": 1,
                        "dis_doc_id": f"DOC-06-{data['seed']}",
                        "milestone_ref": "MS-001",
                        "signed_by": "cto@harness.test",
                        "cto_signature_hash": "a" * 64,
                        "valid_from": datetime.now(timezone.utc).isoformat(),
                    },
                )
                results["tac_status"] = r.status_code
                results["tac_id"] = r.json().get("tac_id") if r.status_code == 200 else None

                # ── Payment APPROVED (TAC now present) ────────────────────
                r = client.post(
                    "/payment/initiate",
                    json={
                        "invoice_id": 1,
                        "amount_satang": data["total_satang"],
                        "approved_by": "cto@harness.test",
                    },
                )
                results["payment_with_tac_status"] = r.status_code
                if r.status_code == 200:
                    body = r.json()
                    results["payment_with_tac_approved"] = body.get("status") == "APPROVED"

                # ── LD calculation ────────────────────────────────────────
                r = client.post(
                    "/ld/calculate",
                    json={
                        "po_id": 1,
                        "contract_value_satang": data["ld_contract_satang"],
                        "daily_rate_bps": data["ld_rate_bps"],
                        "delay_days": data["ld_delay_days"],
                        "cap_pct": data["ld_cap_pct"],
                    },
                )
                results["ld_status"] = r.status_code
                if r.status_code == 200:
                    body = r.json()
                    results["ld_accrued"] = body["accrued_satang"]
                    results["ld_cap"] = body["cap_satang"]
                    results["ld_raw"] = body["raw_ld_satang"]
                    results["ld_is_capped"] = body["is_capped"]

                # ── Audit log ─────────────────────────────────────────────
                r = client.get("/audit_log")
                results["audit_log_status"] = r.status_code
                if r.status_code == 200:
                    results["audit_log_count"] = len(r.json())

                # ── Get TAC ───────────────────────────────────────────────
                r = client.get("/tac/1")
                results["get_tac_status"] = r.status_code
                if r.status_code == 200:
                    results["get_tac_milestone_ref"] = r.json().get("milestone_ref")

        finally:
            app.dependency_overrides.clear()

    return results


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    # PO creation
    assert result.get("po_status") == 201, (
        f"seed={seed}: POST /purchase_orders must return 201, "
        f"got {result.get('po_status')}"
    )

    # Three-way match: exact match → MATCH
    assert result.get("match_status") == 200, (
        f"seed={seed}: POST /match must return 200, got {result.get('match_status')}"
    )
    assert result.get("match_result") == "MATCH", (
        f"seed={seed}: exact-match inputs must produce MATCH, "
        f"got {result.get('match_result')}"
    )

    # Payment without TAC → BLOCKED
    assert result.get("payment_no_tac_status") == 200, (
        f"seed={seed}: payment initiate must return 200, "
        f"got {result.get('payment_no_tac_status')}"
    )
    assert result.get("payment_no_tac_blocked") is True, (
        f"seed={seed}: milestone invoice without TAC must be BLOCKED"
    )
    block_reason = result.get("payment_no_tac_block_reason", "")
    assert "TAC" in block_reason and "BLOCKED" in block_reason, (
        f"seed={seed}: block_reason must contain 'TAC' and 'BLOCKED', got {block_reason!r}"
    )

    # TAC upload
    assert result.get("tac_status") == 200, (
        f"seed={seed}: POST /tac must return 200, got {result.get('tac_status')}"
    )
    assert result.get("tac_id") is not None, (
        f"seed={seed}: tac_id must be returned after TAC upload"
    )

    # Payment with TAC → APPROVED
    assert result.get("payment_with_tac_status") == 200, (
        f"seed={seed}: payment initiate with TAC must return 200"
    )
    assert result.get("payment_with_tac_approved") is True, (
        f"seed={seed}: milestone invoice with approved TAC must be APPROVED"
    )

    # LD calculation
    assert result.get("ld_status") == 200, (
        f"seed={seed}: POST /ld/calculate must return 200, got {result.get('ld_status')}"
    )
    accrued = result.get("ld_accrued", -1)
    cap = result.get("ld_cap", -1)
    raw = result.get("ld_raw", -1)
    assert isinstance(accrued, int), f"seed={seed}: accrued_satang must be int"
    assert isinstance(cap, int), f"seed={seed}: cap_satang must be int"
    assert accrued >= 0, f"seed={seed}: accrued LD must be non-negative"
    assert accrued <= cap, (
        f"seed={seed}: accrued {accrued} must not exceed cap {cap}"
    )
    if raw > cap:
        assert result.get("ld_is_capped") is True, (
            f"seed={seed}: raw_ld {raw} > cap {cap} → is_capped must be True"
        )
    else:
        assert result.get("ld_is_capped") is False, (
            f"seed={seed}: raw_ld {raw} <= cap {cap} → is_capped must be False"
        )

    # Audit log
    assert result.get("audit_log_status") == 200, (
        f"seed={seed}: GET /audit_log must return 200"
    )
    assert result.get("audit_log_count", 0) >= 3, (
        f"seed={seed}: audit log must have ≥3 entries, "
        f"got {result.get('audit_log_count')}"
    )

    # Get TAC
    assert result.get("get_tac_status") == 200, (
        f"seed={seed}: GET /tac/1 must return 200, got {result.get('get_tac_status')}"
    )
    assert result.get("get_tac_milestone_ref") == "MS-001", (
        f"seed={seed}: milestone_ref must round-trip correctly"
    )
