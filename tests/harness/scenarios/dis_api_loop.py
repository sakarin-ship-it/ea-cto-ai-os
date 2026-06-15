"""EA-DIS: full API lifecycle (TestClient) —
login → ingest (mocked pipeline) → search → query → list → reclassify.
"""
from __future__ import annotations

import io
import json
import sys
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

_ROOT = Path(__file__).resolve().parents[4]
for _p in [str(_ROOT / "apps/ea-dis"), str(_ROOT / "shared")]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tests.harness.generators import doc_text_for_type, random_doc_text

SCENARIO_ID = "dis_api_loop"

# Serialize concurrent iterations — app.dependency_overrides and module patches are global state
_LOCK = threading.Lock()


# ── Stateful in-memory DB mock ─────────────────────────────────────────────


class _StateDB:
    def __init__(self):
        self._store: dict[str, dict] = {}
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

            # SQLAlchemy 2.x execute / scalars interface used by dis append_audit
            def execute(self, stmt):
                mock_result = MagicMock()
                mock_result.scalars.return_value.all.return_value = []
                mock_result.scalars.return_value.first.return_value = None
                mock_result.scalar_one_or_none.return_value = None  # audit chain: no prev hash
                return mock_result

        return _S()


# ── Pipeline mock builders ─────────────────────────────────────────────────


def _make_cls_result(doc_type_str: str = "DOC-01", confidence: float = 0.92):
    """Build a ClassificationResult using the real parser to avoid import headaches."""
    from ea_dis.pipeline.classifier import _parse_classification

    return _parse_classification(
        json.dumps({"doc_type": doc_type_str, "confidence": confidence, "reason": "test"})
    )


# ── Scenario functions ─────────────────────────────────────────────────────


def setup(seed: int) -> dict:
    text = doc_text_for_type(seed, "DOC-01")
    return {
        "seed": seed,
        "doc_text": text,
        "filename": f"memo_{seed:04d}.pdf",
    }


def run(data: dict) -> dict:
    from ea_dis.api import app, _DEMO_USERS
    from ea_dis.db import get_db

    state = _StateDB()

    def _override_db():
        return state.make_session()

    results: dict = {}
    cls_result = _make_cls_result("DOC-01", 0.92)

    # RAG mock
    mock_rag_answer = MagicMock()
    mock_rag_answer.answer = "The meeting is on July 15, 2026."
    mock_rag_answer.sources = ["DOC-001 p.1"]

    mock_hits = [
        {"doc_id": 1, "chunk_index": 0, "text": data["doc_text"][:80], "score": 0.95}
    ]

    with _LOCK, \
         patch("ea_dis.pipeline.ingest.parse_file", return_value=(data["doc_text"], 1, "en")), \
         patch("ea_dis.pipeline.ingest.classify_document", return_value=cls_result), \
         patch("ea_dis.pipeline.ingest.embed_batch", side_effect=lambda chunks: [[0.1] * 1024 for _ in chunks]), \
         patch("ea_dis.rag._retrieve", return_value=mock_hits), \
         patch("ea_dis.api.answer_with_citations", return_value=mock_rag_answer):

        app.dependency_overrides[get_db] = _override_db
        try:
            from fastapi.testclient import TestClient
            with TestClient(app, raise_server_exceptions=True) as client:

                # ── Login ─────────────────────────────────────────────────
                r = client.post("/token", json={"username": "admin", "password": "changeme"})
                results["login_status"] = r.status_code
                token = r.json().get("access_token") if r.status_code == 200 else None
                results["has_token"] = bool(token)

                # Wrong password → 401
                r = client.post("/token", json={"username": "admin", "password": "WRONG"})
                results["login_bad_pw_status"] = r.status_code

                if not token:
                    return results  # can't proceed without a token

                auth = {"Authorization": f"Bearer {token}"}

                # ── Ingest (mocked pipeline) ──────────────────────────────
                file_content = data["doc_text"].encode()
                r = client.post(
                    "/ingest",
                    files={"file": (data["filename"], io.BytesIO(file_content), "application/pdf")},
                    headers=auth,
                )
                results["ingest_status"] = r.status_code
                doc_id = None
                if r.status_code == 200:
                    body = r.json()
                    doc_id = body.get("doc_id")
                    results["ingest_doc_type"] = body.get("doc_type")
                    results["ingest_doc_status"] = body.get("status")
                    results["ingest_filename"] = body.get("filename")
                    results["ingest_doc_id"] = doc_id

                # ── Ingest with no auth → 401 ─────────────────────────────
                r2 = client.post(
                    "/ingest",
                    files={"file": (data["filename"], io.BytesIO(file_content), "application/pdf")},
                )
                results["ingest_no_auth_status"] = r2.status_code

                # ── Search ────────────────────────────────────────────────
                r = client.post(
                    "/search",
                    json={"query": "meeting schedule", "top_k": 3},
                    headers=auth,
                )
                results["search_status"] = r.status_code
                if r.status_code == 200:
                    results["search_hit_count"] = len(r.json().get("hits", []))

                # ── RAG query ─────────────────────────────────────────────
                r = client.post(
                    "/query",
                    json={"question": "When is the meeting?", "top_k": 3},
                    headers=auth,
                )
                results["query_status"] = r.status_code
                if r.status_code == 200:
                    body = r.json()
                    results["query_answer"] = body.get("answer", "")
                    results["query_sources"] = body.get("sources", [])

                # ── List documents ────────────────────────────────────────
                r = client.get("/documents", headers=auth)
                results["list_docs_status"] = r.status_code
                if r.status_code == 200:
                    results["list_docs_count"] = len(r.json())

                # ── Reclassify (REVIEWER+ role; admin qualifies) ──────────
                if doc_id:
                    r = client.post(
                        f"/reclassify/{doc_id}",
                        json={"doc_type": "DOC-02"},
                        headers=auth,
                    )
                    results["reclassify_status"] = r.status_code
                    if r.status_code == 200:
                        body = r.json()
                        results["reclassify_new_type"] = body.get("new_doc_type")
                        results["reclassify_doc_status"] = body.get("status")

                # ── List obligations (empty) ──────────────────────────────
                r = client.get("/obligations", headers=auth)
                results["obligations_status"] = r.status_code

        finally:
            app.dependency_overrides.clear()

    return results


def assert_invariants(data: dict, result: dict) -> None:
    seed = data["seed"]

    # Login
    assert result.get("login_status") == 200, (
        f"seed={seed}: POST /token with correct credentials must return 200, "
        f"got {result.get('login_status')}"
    )
    assert result.get("has_token") is True, (
        f"seed={seed}: login response must contain access_token"
    )
    assert result.get("login_bad_pw_status") == 401, (
        f"seed={seed}: wrong password must return 401, "
        f"got {result.get('login_bad_pw_status')}"
    )

    # Ingest
    assert result.get("ingest_status") == 200, (
        f"seed={seed}: POST /ingest must return 200, got {result.get('ingest_status')}"
    )
    assert result.get("ingest_doc_id") is not None, (
        f"seed={seed}: ingest response must include doc_id"
    )
    assert result.get("ingest_doc_type") == "DOC-01", (
        f"seed={seed}: ingest must return mocked doc_type DOC-01, "
        f"got {result.get('ingest_doc_type')}"
    )
    assert result.get("ingest_doc_status") in ("ACTIVE", "PENDING_REVIEW"), (
        f"seed={seed}: ingest doc status must be ACTIVE or PENDING_REVIEW"
    )
    assert result.get("ingest_filename", "").endswith(".pdf"), (
        f"seed={seed}: ingest filename must have .pdf suffix"
    )
    assert result.get("ingest_no_auth_status") in (401, 403), (
        f"seed={seed}: ingest without auth must return 401/403, "
        f"got {result.get('ingest_no_auth_status')}"
    )

    # Search
    assert result.get("search_status") == 200, (
        f"seed={seed}: POST /search must return 200, got {result.get('search_status')}"
    )
    assert result.get("search_hit_count", -1) >= 1, (
        f"seed={seed}: search must return ≥1 hit (mocked)"
    )

    # RAG query
    assert result.get("query_status") == 200, (
        f"seed={seed}: POST /query must return 200, got {result.get('query_status')}"
    )
    assert result.get("query_answer"), (
        f"seed={seed}: query response must have non-empty answer"
    )

    # List documents — execute()-based select() returns [] in mock (no full ORM introspection)
    assert result.get("list_docs_status") == 200, (
        f"seed={seed}: GET /documents must return 200"
    )
    # count may be 0 because select(Document) goes through execute() not query(), which
    # returns [] in the mock. The 200 status confirms the endpoint routes correctly.
    assert isinstance(result.get("list_docs_count"), int), (
        f"seed={seed}: list_docs_count must be an integer"
    )

    # Reclassify
    assert result.get("reclassify_status") == 200, (
        f"seed={seed}: POST /reclassify must return 200, "
        f"got {result.get('reclassify_status')}"
    )
    assert result.get("reclassify_new_type") == "DOC-02", (
        f"seed={seed}: reclassified doc_type must be DOC-02"
    )
    assert result.get("reclassify_doc_status") == "ACTIVE", (
        f"seed={seed}: reclassified document must have ACTIVE status"
    )

    # Obligations endpoint
    assert result.get("obligations_status") == 200, (
        f"seed={seed}: GET /obligations must return 200"
    )
