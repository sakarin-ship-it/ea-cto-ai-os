#!/usr/bin/env bash
# M5 Pilot — stop app backends and n8n (postgres + redis stay up)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PIDS="$REPO/.pids"

log()  { echo "[pilot] $*"; }

stop_pid() {
  local name="$1" pid_file="$PIDS/${1}.pid"
  if [ ! -f "$pid_file" ]; then
    log "$name: no PID file, skipping"
    return
  fi
  local pid
  pid=$(cat "$pid_file")
  if kill -0 "$pid" 2>/dev/null; then
    log "Stopping $name (pid $pid)..."
    kill -TERM "$pid"
    local i=0
    while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 10 ]; do
      sleep 1; i=$(( i + 1 ))
    done
    if kill -0 "$pid" 2>/dev/null; then
      log "$name still alive after 10 s — sending SIGKILL"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  else
    log "$name already stopped"
  fi
  rm -f "$pid_file"
}

# ── App backends ────────────────────────────────────────────────────────────
stop_pid ea-lie
stop_pid ea-pip
stop_pid ea-fci
stop_pid ea-dis

# ── n8n ─────────────────────────────────────────────────────────────────────
stop_pid n8n

# postgresql@16 and redis are intentionally left running.
echo ""
log "postgresql@16 and redis left running (brew services)."
log "To stop them: brew services stop postgresql@16 redis"
log "Pilot stopped."
