#!/usr/bin/env bash
# Cursor adapter: process-fsm subagentStop destape. Fail-open; always emit JSON.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STOP="$ROOT/scripts/process-fsm/subagent_stop.py"
RAW="$(cat)"

fallback() {
  printf '%s\n' '{}'
}

PY=""
if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PY="$ROOT/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
fi

if [[ -n "$PY" && -f "$STOP" ]]; then
  OUT="$(printf '%s' "$RAW" | PROCESS_FSM_ROOT="$ROOT" "$PY" "$STOP" 2>/dev/null || true)"
  if printf '%s' "$OUT" | grep -q '{'; then
    printf '%s\n' "$OUT"
    exit 0
  fi
fi

fallback
exit 0
