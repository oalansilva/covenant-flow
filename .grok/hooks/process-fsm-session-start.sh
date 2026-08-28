#!/usr/bin/env bash
# Grok adapter: persist Moore page. SessionStart stdout is ignored.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PAGING="$ROOT/scripts/process-fsm/paging.py"
RAW="$(cat)"

PY=""
if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PY="$ROOT/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
fi

if [[ -n "$PY" && -f "$PAGING" ]]; then
  printf '%s' "$RAW" | "$PY" "$PAGING" --write-grok-page >/dev/null 2>&1 || true
fi
exit 0
