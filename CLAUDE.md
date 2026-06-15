# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Mission

Build EA-DIS, EA-FCI, EA-PIP, EA-LIE + n8n so ONE person (the CTO) runs four departments on a MacBook Air M5 / 16 GB. Every decision must be memory-safe for ~11 GB usable.

---

## ABSOLUTE RULES

1. **PRIVACY** — DOC-05 (JV IP), DOC-06 (contracts), DOC-07 (financial), DOC-09 (PDPA) are processed ONLY by local LM Studio (`http://localhost:1234`). Never send their text to `api.anthropic.com` or `api.openai.com`. Cloud may receive only template params, non-sensitive scope briefs, and code.

2. **MONEY** — No EPC milestone payment without a CTO-signed TAC first. Money is integer satang only (never float).

3. **AUDIT** — Every state change appends to an immutable `audit_log` with a SHA-256 hash chain (no UPDATE / DELETE on audit rows).

4. **SECRETS** — Read all keys from environment variables; never hardcode.

5. **TEST** — Nothing is done until `pytest` passes AND the 20-loop harness passes 0 failures.

---

## M5 Memory Rules

**A.** ONE chat model loaded at a time. All LM Studio calls go through `shared/lmstudio_client.py`. Never hold two large models concurrently. Prefer MLX 4-bit.

**B.** Model IDs (always use these exact strings):
- primary → `qwen3-8b`
- fast → `llama-3.2-3b`
- embeddings → `bge-m3` (may stay resident)

**C.** Services run natively via Homebrew, never Docker:
- PostgreSQL 16 → `localhost:5432`, database `ea_ai_os`
- Redis → `localhost:6379`

**D.** Apps lazy-load heavy imports. Each FastAPI app runs standalone with `uvicorn --workers 1`.

**E.** Celery workers: `concurrency=2` (EA-FCI on db `0`, EA-LIE on db `1`).

---

## Common Commands

### Run a single app (from repo root)
```bash
PYTHONPATH=apps/ea-pip:shared  uvicorn ea_pip.api:app  --port 8003 --reload
PYTHONPATH=apps/ea-fci:shared  uvicorn fci.api:app     --port 8002 --reload
PYTHONPATH=apps/ea-dis:shared  uvicorn ea_dis.api:app  --port 8001 --reload
PYTHONPATH=apps/ea-lie:shared  uvicorn lie.api:app     --port 8004 --reload
```

`PYTHONPATH` must always include the app directory AND `shared/`.

### Start / stop everything
```bash
./scripts/start_pilot.sh   # PostgreSQL + Redis + LM Studio + n8n + all 4 uvicorn backends
./scripts/stop_pilot.sh
```

### Tests — per app
```bash
cd apps/ea-pip && PYTHONPATH=.:../../shared python3.11 -m pytest
cd apps/ea-fci && PYTHONPATH=.:../../shared python3.11 -m pytest
cd apps/ea-dis && PYTHONPATH=.:../../shared python3.11 -m pytest ea_dis/tests/
cd apps/ea-lie && PYTHONPATH=.:../../shared python3.11 -m pytest
```

Run a single test file or test:
```bash
python3.11 -m pytest ea_pip/tests/test_compliance_checker.py -k test_alb_threshold
```

### Lint
```bash
cd apps/ea-pip && ruff check .
cd apps/ea-fci && ruff check .
cd apps/ea-dis && ruff check .
cd apps/ea-lie && ruff check .
```

### 20-loop harness (required gate before merging)
```bash
# From repo root
python3.11 -m tests.harness.runner --loops 20 --max-concurrency 2

# Single scenario, fewer loops
python3.11 -m tests.harness.runner --scenario pip_api_loop --loops 3 --max-concurrency 1

# With live LM Studio preload check
python3.11 -m tests.harness.runner --preload-model
```

---

## Architecture

### Repo layout
```
shared/lmstudio_client.py   ← single LM Studio interface; ALL apps import from here
apps/
  ea-dis/ea_dis/            ← package name ea_dis (not dis — stdlib conflict)
  ea-fci/fci/               ← package name fci
  ea-pip/ea_pip/            ← package name ea_pip (not pip — package manager conflict)
  ea-lie/lie/               ← package name lie
tests/harness/              ← 20-loop scenario harness (setup/run/assert_invariants)
n8n/                        ← workflow JSON exports
scripts/                    ← start_pilot.sh / stop_pilot.sh
```

### Port assignments
| App | Port | Auth |
|-----|------|------|
| EA-DIS | 8001 | JWT Bearer (`EA_DIS_JWT_SECRET`) |
| EA-FCI | 8002 | None (internal service) |
| EA-PIP | 8003 | `X-API-Key: $PIP_API_KEY` |
| EA-LIE | 8004 | None (internal service) |

### Database schemas (all in `ea_ai_os`)
Each app owns one schema and never touches another's:
- `dis` — documents, chunks (pgvector 1024-dim), obligations, audit_log
- `fci` — purchase_orders, grn, invoices, payments, tac_certificates, ld_accruals, fx_positions, anomaly_flags, audit_log
- `pip` — suppliers, packages, eoi_responses, bids, bid_documents, evaluations, scores, awards, audit_log
- `lie` — (optional persistence; core modules are stateless)

EA-DIS requires `CREATE EXTENSION IF NOT EXISTS vector` (pgvector). Each app's `init_schema()` is called on startup and is idempotent.

### Cross-app wiring
- **EA-PIP → EA-FCI**: Tier-1 autoselect posts a PO to `$FCI_API_URL/purchase_orders` when `FCI_API_URL` is set; skips silently otherwise.
- **EA-LIE monitors EA-FCI/EA-DIS/EA-PIP**: `breach_monitor.py` listens for events and generates qwen3-8b notices + iMessage alerts (`$ALERT_IMESSAGE_RECIPIENT`).
- **n8n orchestrates all four**: 12 workflows (webhooks + cron) wire the apps together. Webhook prefix: `POST /w0N-*`.

### Session / DB dependency naming
- EA-PIP, EA-FCI: `from X.db import get_session` → `Depends(get_session)` in FastAPI routes.
- EA-DIS: `from ea_dis.db import get_db` → `Depends(get_db)`.
- Audit chain differs: PIP/FCI use `session.query(AuditLog).with_for_update().first()`; DIS uses `db.execute(select(AuditLog.hash_value)...).scalar_one_or_none()`.

---

## Key Domain Invariants

### EA-FCI — TAC gate
Milestone or equipment invoices are **BLOCKED** without an approved `TACCertificate` (`is_approved=True`). `block_reason` must be non-empty and contain `"TAC"` and `"BLOCKED"`. See `fci/tac_gate.py`.

### EA-PIP — ALB threshold
Abnormally Low Bid: `bid < ALB_THRESHOLD (0.85) * reference` — **strict `<`, not `≤`**. `reference = min(median_other_bids, engineer_estimate)`. Tier-1 autoselect requires ≥ 3 compliant, non-ALB bids.

### EA-PIP — BLIND evaluator
`evaluator_id` comes **only** from the `X-Evaluator-Id` header. Never from a query param or request body. `get_evaluator_scores()` always filters by `evaluator_id`.

### EA-DIS — Confidence gate
`classify_document()` confidence < 0.85 → status `PENDING_REVIEW`, no embedding. Only `ACTIVE` documents are chunked and embedded.

### EA-LIE — Mandatory clauses
Every generated contract must embed all 5 `##MC:XX##` tags (IR, LD, PDPA, SEC, ESIG). Score > 60 → RED → External Lawyer required; 35–60 → AMBER → Legal Counsel; < 35 → GREEN → CTO+CFO.

### BreachMonitor — sentinel
`BreachMonitor(imessage_recipient=None)` reads `$ALERT_IMESSAGE_RECIPIENT` from env. `imessage_recipient=""` (explicit empty string) suppresses sending — used in tests.

---

## Harness Test Pattern

Every scenario module in `tests/harness/scenarios/` exports three functions:
```python
SCENARIO_ID = "foo_bar"

def setup(seed: int) -> dict:    # build deterministic test data from seed
def run(data: dict) -> dict:     # exercise the code, return observable results
def assert_invariants(data, result):  # raise AssertionError on violation
```

API-loop scenarios (`*_api_loop.py`) use FastAPI `TestClient` with:
- `_StateDB` — stateful in-memory SQLAlchemy mock (assigns IDs on `flush()`, applies `created_at` defaults)
- `app.dependency_overrides[get_session]` — injects `_StateDB.make_session()`
- `threading.Lock()` — serialises iterations of the same scenario to prevent patch collisions
- `patch("X.api.init_schema")` — skips real PostgreSQL on startup
- External calls mocked: DBD API, `_lm_chat`, `subprocess.run` (iMessage), `anthropic.Anthropic`

When adding a new scenario: register it in `_SCENARIO_MODULES` inside `tests/harness/runner.py`.

---

## Stack

- **Backend** — Python 3.11 · FastAPI · SQLAlchemy 2.x · Celery · Redis
- **Database** — PostgreSQL 16 + pgvector; schema-per-app
- **Frontend** — React + Tailwind (in `src/`, served via Vite on `:5173`)
- **Automation** — n8n (localhost:5678); 12 workflows in `n8n/`
- **Alerts** — iMessage via `osascript` for urgent; macOS `display notification` for normal
