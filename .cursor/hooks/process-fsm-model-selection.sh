#!/usr/bin/env bash
set -u
PROCESS_MODELS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PROCESS_MODELS_CLIENT="${1:-cursor}"
PROCESS_MODELS_RESULT="$(python3 "$PROCESS_MODELS_ROOT/scripts/process-fsm/model_selection_adapter.py" --client "$PROCESS_MODELS_CLIENT" 2>/dev/null)" || {
  printf '%s\n' '{"permission":"deny","decision":"deny","reason":"model_selection deny: resolver unavailable; no fallback"}'
  exit 0
}
printf '%s\n' "$PROCESS_MODELS_RESULT"
