#!/usr/bin/env bash
# M5 Pilot — start all services and app backends
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PIDS="$REPO/.pids"
LOGS="$REPO/logs/pilot"
SHARED="$REPO/shared"
PY=python3.11

mkdir -p "$PIDS" "$LOGS"

log()  { echo "[pilot] $*"; }
warn() { echo "[pilot] WARN: $*" >&2; }

# ── 1. Infrastructure (brew services are idempotent) ───────────────────────
log "postgresql@16..."
brew services start postgresql@16 2>/dev/null || true

log "redis..."
brew services start redis 2>/dev/null || true

# ── 2. LM Studio inference server ─────────────────────────────────────────
LMS_PID="$PIDS/lmstudio.pid"
if [ -f "$LMS_PID" ] && kill -0 "$(cat "$LMS_PID")" 2>/dev/null; then
  log "LM Studio already running (pid $(cat "$LMS_PID"))"
elif command -v lms >/dev/null 2>&1; then
  log "Starting LM Studio on :1234 (max-concurrent-models=1, ttl=600s)..."
  # --ttl 600 → unload model after 10 min idle; saves ~4 GB when inactive
  lms server start --port 1234 --ttl 600 &
  echo $! > "$LMS_PID"
else
  warn "lms CLI not found — start LM Studio manually on port 1234 before running workloads"
fi

# ── 3. n8n ─────────────────────────────────────────────────────────────────
N8N_PID="$PIDS/n8n.pid"
N8N_CMD=""
if command -v n8n >/dev/null 2>&1; then
  N8N_CMD="n8n"
elif [ -f "$REPO/node_modules/.bin/n8n" ]; then
  N8N_CMD="$REPO/node_modules/.bin/n8n"
fi

if [ -f "$N8N_PID" ] && kill -0 "$(cat "$N8N_PID")" 2>/dev/null; then
  log "n8n already running (pid $(cat "$N8N_PID"))"
elif [ -n "$N8N_CMD" ]; then
  log "Starting n8n (user folder: $REPO/n8n)..."
  N8N_USER_FOLDER="$REPO/n8n" nohup "$N8N_CMD" start \
    > "$LOGS/n8n.log" 2>&1 &
  echo $! > "$N8N_PID"
else
  warn "n8n not found — install with: npm install -g n8n"
fi

# ── 4. App backends (uvicorn workers=1 each, low memory) ──────────────────
start_backend() {
  local name="$1" app_dir="$2" module="$3" port="$4"
  local pid_file="$PIDS/${name}.pid"

  # Resolve <pkg>/<submodule>.py from "pkg.submodule:app"
  local api_file="$app_dir/$(echo "$module" | cut -d: -f1 | tr '.' '/').py"
  if [ ! -f "$api_file" ]; then
    warn "$name: $api_file not found — skipping"
    return
  fi

  if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
    log "$name already running (pid $(cat "$pid_file"))"
    return
  fi

  log "Starting $name on :$port..."
  PYTHONPATH="$app_dir:$SHARED" nohup "$PY" -m uvicorn "$module" \
    --host 127.0.0.1 --port "$port" --workers 1 \
    > "$LOGS/${name}.log" 2>&1 &
  echo $! > "$pid_file"
}

start_backend ea-dis "$REPO/apps/ea-dis" "ea_dis.api:app" 8001
start_backend ea-fci "$REPO/apps/ea-fci" "fci.api:app"   8002
start_backend ea-pip "$REPO/apps/ea-pip" "ea_pip.api:app" 8003
start_backend ea-lie "$REPO/apps/ea-lie" "lie.api:app"    8004

# ── 5. Memory summary ──────────────────────────────────────────────────────
echo ""
PAGE=$(sysctl -n hw.pagesize)
TOTAL=$(sysctl -n hw.memsize)
VM=$(vm_stat)
FREE_P=$(printf '%s' "$VM" | awk '/^Pages free:/{print $NF}' | tr -d '.')
SPEC_P=$(printf '%s' "$VM" | awk '/^Pages speculative:/{print $NF}' | tr -d '.')
FREE_P=${FREE_P:-0}; SPEC_P=${SPEC_P:-0}
AVAIL_B=$(( (FREE_P + SPEC_P) * PAGE ))
USED_B=$(( TOTAL - AVAIL_B ))

gb() { printf "%.1f" "$(echo "scale=3; $1 / 1073741824" | bc)"; }
printf "[pilot] Memory: %s GB used / %s GB total  (%s GB free)\n" \
  "$(gb "$USED_B")" "$(gb "$TOTAL")" "$(gb "$AVAIL_B")"

AVAIL_MB=$(( AVAIL_B / 1048576 ))
if [ "$AVAIL_MB" -lt 2048 ]; then
  warn "Less than 2 GB free — close unused apps or let LM Studio TTL unload the model"
fi

echo ""
log "Pilot up. Logs → $LOGS   PIDs → $PIDS"
