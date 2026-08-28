#!/usr/bin/env bash
# Grok thin wrapper: same Guard as Cursor (relative to this JSON directory).
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec "$ROOT/.cursor/hooks/process-fsm-guard.sh"
