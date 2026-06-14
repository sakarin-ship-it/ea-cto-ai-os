# EA CTO AI OS — Claude Code Rules

## Mission

Build EA-DIS, EA-FCI, EA-PIP, EA-LIE + n8n so ONE person (the CTO) runs four
departments. TARGET HARDWARE: MacBook Air M5, 16GB unified memory. Everything
must be memory-safe for ~11GB usable.

---

## ABSOLUTE RULES

1. **PRIVACY** — DOC-05 (JV IP), DOC-06 (contracts), DOC-07 (financial), DOC-09
   (PDPA) are processed ONLY by local LM Studio (`http://localhost:1234`).
   Never send their text to `api.anthropic.com` or `api.openai.com`. Cloud may
   receive only template params, non-sensitive scope briefs, and code.

2. **MONEY** — No EPC milestone payment without a CTO-signed TAC first. Money is
   integer satang only (never float).

3. **AUDIT** — Every state change appends to an immutable `audit_log` with a
   SHA-256 hash chain (no UPDATE / DELETE on audit rows).

4. **SECRETS** — Read all keys from environment variables; never hardcode.

5. **TEST** — Nothing is done until `pytest` passes AND the 20-loop harness
   passes 0 failures.

---

## M5 / 16GB MEMORY RULES (critical)

**A.** ONE chat model loaded at a time. All LM Studio calls go through
`shared/lmstudio_client.py` which requests a model, uses it, and never holds
two large models concurrently. Prefer MLX 4-bit models.

**B.** Model IDs:
- primary → `qwen3-8b` (MLX 4-bit)
- fast → `llama-3.2-3b` (MLX 4-bit)
- embeddings → `bge-m3` (small; may stay resident)

Always reference models by these IDs.

**C.** Services run NATIVELY (Homebrew), never Docker. Assume:
- PostgreSQL 16 on `localhost:5432`, database `ea_ai_os`
- Redis on `localhost:6379`

**D.** Apps lazy-load — import heavy libs only when needed; do not warm all four
apps at once. FastAPI apps must run fine individually with `uvicorn`.

**E.** Background jobs (Celery) use low concurrency (`concurrency=2`) to bound
memory.

**F.** The 20-loop harness must support `--max-concurrency` (default 2 on this
machine) and must preload exactly ONE model.

---

## Stack

- **Backend** — Python 3.11 · FastAPI · SQLAlchemy · Alembic · Celery · Redis
- **Database** — PostgreSQL 16 + pgvector; schema-per-app: `dis`, `fci`, `pip`, `lie`, `shared`
- **Frontends** — React + Tailwind (ChatGPT Codex)
- **Automation** — n8n via n8n-MCP
- **Mobile approvals** — LINE (target <60 s round-trip)

---

## Conventions

- Typed Pydantic models everywhere
- Money as integer satang; never float
- Timestamps stored UTC, displayed Asia/Bangkok
- Every external call retried with exponential backoff + timeout + structured logging
