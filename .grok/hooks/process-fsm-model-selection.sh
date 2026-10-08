#!/usr/bin/env bash
set -u
PROCESS_MODELS_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
exec "$PROCESS_MODELS_ROOT/.cursor/hooks/process-fsm-model-selection.sh" grok
