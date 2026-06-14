# EA-CTO AI OS — n8n Automation Workflows

12 production workflows running on n8n 2.8.4 (localhost:5678).

## Workflows

| File | Schedule / Trigger | Purpose |
|------|--------------------|---------|
| w01 Morning Brief | Daily 06:30 | Aggregate EA-FCI anomalies, EA-DIS RAG, EA-LIE obligations → macOS notification |
| w02 Doc Auto-Ingest | Webhook POST /w02-doc-ingest | Ingest document into EA-DIS pipeline |
| w03 Invoice TAC Gate | Webhook POST /w03-invoice-tac | 3-way match → TAC gate → payment initiation |
| w04 AR Dunning | Daily 10:05 | Query overdue invoices → macOS notification |
| w05 LD Daily Accrual | Daily 18:00 | Retrieve LD accruals from EA-FCI → log → notification |
| w06 Tier-1 Autoselect | Webhook POST /w06-tier1-select | EA-PIP autoselect → PO handoff to EA-FCI |
| w07 Bid-Deadline Lock | Daily 08:15 | Lock EA-PIP packages with deadlines within 2h |
| w08 Obligation Sync | Webhook POST /w08-obligation-sync | Fetch EA-LIE obligations → log |
| w09 Breach Detection | Webhook POST /w09-breach | EA-LIE breach monitor → **iMessage alert** |
| w10 FIDIC Time-Bar | Daily 19:15 | Check imminent FIDIC deadlines → **iMessage if critical** |
| w11 Weekly Report | Mon 07:15 | Aggregate all 4 EA services → macOS notification |
| w12 Self-Healing | Error Trigger | Retry failed workflow ×3 → **iMessage escalation** |

## Schedule collision matrix

Heavy cron jobs never overlap (M5 memory rule):

```
06:30  W-01 Morning Brief
07:15  W-11 Weekly Report (Mondays only)
08:15  W-07 Bid Lock
10:05  W-04 AR Dunning
18:00  W-05 LD Daily
19:15  W-10 FIDIC Time-Bar
```

## Infrastructure

- **Notifications:** macOS `osascript` via n8n Code node (`child_process.execSync`)
  - Normal: `display notification` (all workflows)
  - Urgent: iMessage to `s.akarin@icloud.com` (W-09, W-10 critical, W-12 escalation)
- **Logging:** PostgreSQL `public.ea_workflow_log` (user: `postgres`, DB: `postgres`)
- **Credentials in n8n:** EA FCI API Key, EA LIE API Key, EA PIP API Key, EA DIS Token, EA Postgres, n8n API Key

## DDL

```sql
CREATE TABLE IF NOT EXISTS ea_workflow_log (
    id          SERIAL PRIMARY KEY,
    workflow_id   TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    execution_id  TEXT,
    status        TEXT NOT NULL,
    payload       JSONB,
    logged_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
GRANT INSERT, SELECT, DELETE ON TABLE ea_workflow_log TO postgres;
GRANT USAGE, SELECT ON SEQUENCE ea_workflow_log_id_seq TO postgres;
```

## Re-importing workflows

Use n8n UI: Settings → Import from file, or via the n8n API:

```bash
curl -X POST http://localhost:5678/api/v1/workflows \
  -H "X-N8N-API-KEY: <key>" \
  -H "Content-Type: application/json" \
  -d @ops/n8n/workflows/w01_w-01_morning_brief.json
```
