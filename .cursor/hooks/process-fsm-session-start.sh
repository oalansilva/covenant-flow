#!/usr/bin/env bash
# Cursor adapter: process-fsm sessionStart paging. Fire-and-forget; always emit JSON.
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PAGING="$ROOT/scripts/process-fsm/paging.py"
RAW="$(cat)"

fallback() {
  printf '%s\n' '{"additional_context":"process-fsm page\nq=None bound_card=⊥ q_git=⊥\nenabled_events: (unbound)\n---\nbound_card=⊥. Write produto deny. Não carregue playbook de release.\n---\nResolva (q, bound_card, q_git). Não invente aresta. Chat é wording; NLU ≠ δ. Overlay on-demand (portas, Drive, release).\n"}'
}

PY=""
if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PY="$ROOT/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
fi

if [[ -n "$PY" && -f "$PAGING" ]]; then
  OUT="$(printf '%s' "$RAW" | "$PY" "$PAGING" 2>/dev/null || true)"
  if printf '%s' "$OUT" | grep -q '"additional_context"'; then
    printf '%s\n' "$OUT"
    exit 0
  fi
fi

fallback
exit 0
