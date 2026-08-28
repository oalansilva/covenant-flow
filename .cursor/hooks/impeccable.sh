#!/usr/bin/env bash
# Adapter: Cursor hook events -> Impeccable detector (hook.mjs).
# Never break the agent turn.
set -u
EVENT="${1:-afterFileEdit}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOOK="$ROOT/.agents/skills/impeccable/scripts/hook.mjs"

export IMPECCABLE_HOOK_HARNESS=cursor
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

if event_name == "stop":
    payload["hook_event_name"] = "Stop"
else:
    payload["hook_event_name"] = "PostToolUse"
    if "file_path" not in payload:
        for key in ("path", "filePath", "file"):
            if isinstance(payload.get(key), str) and payload[key]:
                payload["file_path"] = payload[key]
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
