#!/usr/bin/env bash
# Materialize .dsh/cordis.patch.yml with absolute plugin names and run dsh web --patch.
# Pin channel is install.sh --pin, not `dsh plugin add`.
# Bounce: sibling stops the live isolate, then a new tmp patch and --port bind.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PATCH_SRC="$REPO_ROOT/.dsh/cordis.patch.yml"
GUARD_JS="$REPO_ROOT/.dsh/plugin/process-fsm-guard.js"
HOOK_JS="$REPO_ROOT/.dsh/plugin/impeccable-hook.js"
LIB_JS="$SCRIPT_DIR/dsh_plugin_lib.js"
RELOAD="$SCRIPT_DIR/dsh_isolate_reload.sh"

LISTEN="${DSH_ISOLATE_LISTEN:-127.0.0.1:3080}"
SIDECAR="${DSH_ISOLATE_SIDECAR:-/tmp/covenant-flow-dsh-isolate.json}"

[[ -f "$PATCH_SRC" ]] || { echo "dsh_boot: missing $PATCH_SRC" >&2; exit 1; }
[[ -f "$GUARD_JS" ]] || { echo "dsh_boot: missing $GUARD_JS" >&2; exit 1; }
[[ -f "$HOOK_JS" ]] || { echo "dsh_boot: missing $HOOK_JS" >&2; exit 1; }
[[ -f "$LIB_JS" ]] || { echo "dsh_boot: missing $LIB_JS" >&2; exit 1; }
[[ -x "$RELOAD" || -f "$RELOAD" ]] || { echo "dsh_boot: missing $RELOAD" >&2; exit 1; }

if [[ "$LISTEN" != *:* ]]; then
  echo "dsh_boot: DSH_ISOLATE_LISTEN must be host:port, got ${LISTEN}" >&2
  exit 2
fi
HOST="${LISTEN%:*}"
PORT="${LISTEN##*:}"
if [[ -z "$HOST" || ! "$PORT" =~ ^[0-9]+$ ]]; then
  echo "dsh_boot: invalid DSH_ISOLATE_LISTEN=${LISTEN}" >&2
  exit 2
fi

DEV_ROOT="$(
  PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - "$REPO_ROOT" <<'PY'
from pathlib import Path
import sys

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "scripts" / "process-fsm"))
dev = ""
try:
    from overlay import try_load_overlay
    overlay = try_load_overlay(root, require_filled=False) or {}
    paths = overlay.get("canonical_paths") or {}
    if isinstance(paths, dict):
        dev = str(paths.get("dev") or "").strip()
except Exception:
    dev = ""
print(dev)
PY
)"

if [[ -n "$DEV_ROOT" && ! -d "$DEV_ROOT" ]]; then
  echo "dsh_boot: canonical_paths.dev is not a directory: $DEV_ROOT" >&2
  exit 1
fi

if [[ -n "$DEV_ROOT" && -d "$DEV_ROOT" ]]; then
  LAUNCH_DIR="$DEV_ROOT"
else
  LAUNCH_DIR="$REPO_ROOT"
fi

# A7 fails before the sibling so a bad canonical_paths.dev never SIGTERM the isolate.
bash "$RELOAD"

TMP_PATCH="$(mktemp "${TMPDIR:-/tmp}/covenant-flow-dsh-XXXXXX.patch.yml")"
DSH_PID=""
cleaning=0

port_has_listener() {
  python3 - "$HOST" "$PORT" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
try:
    s = socket.create_connection((host, port), 0.2)
except OSError:
    sys.exit(1)
s.close()
sys.exit(0)
PY
}

wait_listen() {
  local n=0
  while ! port_has_listener && (( n < 80 )); do
    sleep 0.1
    n=$((n + 1))
  done
  port_has_listener
}

wait_port_free() {
  local n=0
  while port_has_listener && (( n < 50 )); do
    sleep 0.1
    n=$((n + 1))
  done
  if port_has_listener; then
    return 1
  fi
  return 0
}

stop_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  if [[ -d "/proc/$pid" ]]; then
    kill -TERM "$pid" 2>/dev/null || true
  fi
  local n=0
  while [[ -d "/proc/$pid" ]] && (( n < 50 )); do
    sleep 0.1
    n=$((n + 1))
  done
  if [[ -d "/proc/$pid" ]]; then
    kill -KILL "$pid" 2>/dev/null || true
    n=0
    while [[ -d "/proc/$pid" ]] && (( n < 20 )); do
      sleep 0.1
      n=$((n + 1))
    done
  fi
}

cleanup() {
  local rc=$?
  if [[ "$cleaning" -eq 1 ]]; then
    return
  fi
  cleaning=1
  trap - EXIT INT TERM
  stop_pid "${DSH_PID:-}"
  if ! wait_port_free; then
    bash "$RELOAD" || true
    wait_port_free || true
  fi
  if port_has_listener; then
    echo "dsh_boot: listener still on ${LISTEN}; not removing tmp patch" >&2
    exit "$rc"
  fi
  rm -f "$TMP_PATCH"
  exit "$rc"
}
trap cleanup EXIT INT TERM

PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}" python3 - "$PATCH_SRC" "$GUARD_JS" "$HOOK_JS" "$TMP_PATCH" <<'PY'
from pathlib import Path
import sys

src, guard, hook, dest = (Path(p) for p in sys.argv[1:])
text = src.read_text(encoding="utf-8")
out_lines = []
for line in text.splitlines():
    stripped = line.strip()
    if stripped.startswith("name:") and "process-fsm-guard.js" in stripped:
        indent = line[: len(line) - len(line.lstrip())]
        out_lines.append(f"{indent}name: {guard}")
    elif stripped.startswith("name:") and "impeccable-hook.js" in stripped:
        indent = line[: len(line) - len(line.lstrip())]
        out_lines.append(f"{indent}name: {hook}")
    else:
        out_lines.append(line)
dest.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
PY

cd "$LAUNCH_DIR"
dsh web --patch "$TMP_PATCH" --no-open --port "$PORT" &
DSH_PID=$!

if ! wait_listen; then
  echo "dsh_boot: dsh web did not listen on ${LISTEN}" >&2
  exit 1
fi

python3 - "$SIDECAR" "$LISTEN" "$DSH_PID" "$GUARD_JS" "$LIB_JS" "$LAUNCH_DIR" "$TMP_PATCH" "$HOST" "$PORT" <<'PY'
import hashlib
import json
import os
import socket
import sys
import time
from pathlib import Path

(
    sidecar,
    listen,
    launched,
    guard,
    lib,
    launch_dir,
    patch,
    host,
    port_s,
) = sys.argv[1:]
port = int(port_s)
port_hex = f"{port:04X}"
want = socket.inet_aton(host)[::-1].hex().upper()
any4 = "00000000"
inodes = set()
try:
    lines = Path("/proc/net/tcp").read_text(encoding="ascii", errors="replace").splitlines()[1:]
except OSError:
    lines = []
for line in lines:
    parts = line.split()
    if len(parts) < 10:
        continue
    local, state, inode = parts[1], parts[3], parts[9]
    if state != "0A" or inode == "0":
        continue
    lip, lport = local.split(":")
    if lport.upper() != port_hex:
        continue
    if lip.upper() in {want, any4}:
        inodes.add(inode)
listener_pid = int(launched)
if inodes:
    for pid_dir in Path("/proc").iterdir():
        if not pid_dir.name.isdigit():
            continue
        fd_dir = pid_dir / "fd"
        try:
            for fd in fd_dir.iterdir():
                try:
                    tgt = os.readlink(fd)
                except OSError:
                    continue
                if tgt.startswith("socket:[") and tgt[8:-1] in inodes:
                    listener_pid = int(pid_dir.name)
                    break
            else:
                continue
            break
        except OSError:
            continue
payload = {
    "pid": listener_pid,
    "start_epoch": int(time.time()),
    "listen": listen,
    "guard_sha256": hashlib.sha256(Path(guard).read_bytes()).hexdigest(),
    "lib_sha256": hashlib.sha256(Path(lib).read_bytes()).hexdigest(),
    "launch_dir": launch_dir,
    "patch": patch,
}
path = Path(sidecar)
if path.exists() and path.is_dir():
    raise SystemExit(f"dsh_boot: sidecar path is a directory: {path}")
# Sidecar lives outside .dsh/ and outside git; default is /tmp for live bounce only.
path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
PY

wait "$DSH_PID" || true
exit 0
