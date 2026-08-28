#!/usr/bin/env bash
# Adapter: Grok PostToolUse/Stop -> Impeccable detector (hook.mjs).
# Never break the agent turn. Same stdin contract as .cursor/hooks/impeccable.sh.
set -u
EVENT="${1:-PostToolUse}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/.agents/skills/impeccable/scripts/hook.mjs"

export IMPECCABLE_HOOK_HARNESS=grok
export CURSOR_PROJECT_DIR="$ROOT"

if [[ ! -f "$HOOK" ]]; then
  exit 0
fi

python3 - "$EVENT" "$HOOK" <<'PY'
import json, os, subprocess, sys

event_name = sys.argv[1]
hook = sys.argv[2]
raw = sys.stdin.read()
try:
    payload = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    payload = {"raw": raw}

if not isinstance(payload, dict):
    payload = {"value": payload}

if event_name.lower() == "stop":
    payload["hook_event_name"] = "Stop"
else:
    payload["hook_event_name"] = "PostToolUse"
    if "file_path" not in payload or not payload.get("file_path"):
        for key in ("path", "filePath", "file"):
            if isinstance(payload.get(key), str) and payload[key]:
                payload["file_path"] = payload[key]
                break
        tool_input = payload.get("toolInput") or payload.get("tool_input") or payload.get("args")
        if isinstance(tool_input, dict):
            for key in ("filePath", "file_path", "path", "file"):
                value = tool_input.get(key)
                if isinstance(value, str) and value.strip():
                    payload["file_path"] = value.strip()
                    break
        files = payload.get("files") or payload.get("edits")
        if isinstance(files, list) and files:
            first = files[0]
            if isinstance(first, str):
                payload["file_path"] = first
            elif isinstance(first, dict):
                payload["file_path"] = first.get("path") or first.get("file_path") or payload.get("file_path")

try:
    subprocess.run(
        ["node", hook],
        input=json.dumps(payload).encode(),
        cwd=os.environ.get("CURSOR_PROJECT_DIR") or os.getcwd(),
        env=os.environ.copy(),
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
except Exception:
    pass
sys.exit(0)
PY
