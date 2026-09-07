#!/usr/bin/env bash
# Stop the dsh isolate on DSH_ISOLATE_LISTEN, or --check sidecar vs live listener.
# Occupant = /proc/<pid>/cmdline contains token dsh AND subcommand web.
# Classification does not use comm, ss process name, or basename of the first argument.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LISTEN="${DSH_ISOLATE_LISTEN:-127.0.0.1:3080}"
SIDECAR="${DSH_ISOLATE_SIDECAR:-/tmp/covenant-flow-dsh-isolate.json}"
GUARD_JS="$REPO_ROOT/.dsh/plugin/process-fsm-guard.js"
LIB_JS="$SCRIPT_DIR/dsh_plugin_lib.js"

MODE="stop"
if [[ "${1:-}" == "--check" ]]; then
  MODE="check"
elif [[ -n "${1:-}" ]]; then
  echo "dsh_isolate_reload: unknown arg: $1" >&2
  exit 2
fi

if [[ "$LISTEN" != *:* ]]; then
  echo "dsh_isolate_reload: DSH_ISOLATE_LISTEN must be host:port, got ${LISTEN}" >&2
  exit 2
fi
HOST="${LISTEN%:*}"
PORT="${LISTEN##*:}"
if [[ -z "$HOST" || ! "$PORT" =~ ^[0-9]+$ ]]; then
  echo "dsh_isolate_reload: invalid DSH_ISOLATE_LISTEN=${LISTEN}" >&2
  exit 2
fi

# Prints one PID per line. Classification uses cmdline only, never comm or ss process name.
list_listener_pids() {
  python3 - "$HOST" "$PORT" <<'PY'
import os
import socket
import sys
from pathlib import Path

host, port_s = sys.argv[1], sys.argv[2]
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
if not inodes:
    sys.exit(0)
found = []
proc = Path("/proc")
for pid_dir in proc.iterdir():
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
                found.append(pid_dir.name)
                break
    except OSError:
        continue
print("\n".join(found))
PY
}

cmdline_of() {
  local pid="$1"
  python3 - "$pid" <<'PY'
import sys
from pathlib import Path

raw = Path("/proc") / sys.argv[1] / "cmdline"
try:
    data = raw.read_bytes()
except OSError:
    sys.exit(1)
sys.stdout.write(data.replace(b"\0", b" ").decode("utf-8", "replace"))
PY
}

is_dsh_web_cmdline() {
  python3 - "$1" <<'PY'
import sys
cmd = sys.argv[1]
parts = cmd.split()
has_dsh = any("dsh" in part for part in parts)
has_web = any(part == "web" for part in parts)
sys.exit(0 if has_dsh and has_web else 1)
PY
}

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

if [[ "$MODE" == "check" ]]; then
  if ! port_has_listener; then
    echo "dsh_isolate_reload --check: no listener on ${LISTEN}" >&2
    exit 1
  fi
  if [[ ! -f "$SIDECAR" ]]; then
    echo "dsh_isolate_reload --check: missing sidecar ${SIDECAR}" >&2
    exit 1
  fi
  mapfile -t PIDS < <(list_listener_pids)
  if [[ "${#PIDS[@]}" -eq 0 ]]; then
    echo "dsh_isolate_reload --check: listener on ${LISTEN} but no /proc pid" >&2
    exit 1
  fi
  python3 - "$SIDECAR" "$GUARD_JS" "$LIB_JS" "${PIDS[@]}" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

sidecar_path = Path(sys.argv[1])
guard = Path(sys.argv[2])
lib = Path(sys.argv[3])
listener_pids = {int(p) for p in sys.argv[4:]}
try:
    data = json.loads(sidecar_path.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as exc:
    sys.stderr.write(f"dsh_isolate_reload --check: sidecar unreadable: {exc}\n")
    sys.exit(1)
try:
    sidecar_pid = int(data.get("pid"))
except (TypeError, ValueError):
    sys.stderr.write("dsh_isolate_reload --check: sidecar pid missing\n")
    sys.exit(1)
if sidecar_pid not in listener_pids:
    sys.stderr.write(
        f"dsh_isolate_reload --check: sidecar pid={sidecar_pid} is not listener {sorted(listener_pids)}\n"
    )
    sys.exit(1)
if not guard.is_file() or not lib.is_file():
    sys.stderr.write("dsh_isolate_reload --check: guard or lib blob missing on disk\n")
    sys.exit(1)
want_guard = hashlib.sha256(guard.read_bytes()).hexdigest()
want_lib = hashlib.sha256(lib.read_bytes()).hexdigest()
got_guard = str(data.get("guard_sha256") or "").strip().lower()
got_lib = str(data.get("lib_sha256") or "").strip().lower()
if got_guard != want_guard or got_lib != want_lib:
    sys.stderr.write("dsh_isolate_reload --check: SHA mismatch vs disk (pin morto)\n")
    sys.exit(1)
sys.exit(0)
PY
  exit $?
fi

mapfile -t PIDS < <(list_listener_pids)
if [[ "${#PIDS[@]}" -eq 0 ]]; then
  if port_has_listener; then
    echo "dsh_isolate_reload: ${LISTEN} busy but occupant pid unreadable" >&2
    exit 1
  fi
  exit 0
fi

fail_closed=0
for pid in "${PIDS[@]}"; do
  cmd="$(cmdline_of "$pid" || true)"
  if ! is_dsh_web_cmdline "$cmd"; then
    echo "dsh_isolate_reload: occupant pid=${pid} cmdline=${cmd} lacks dsh+web" >&2
    fail_closed=1
  fi
done
if [[ "$fail_closed" -ne 0 ]]; then
  exit 1
fi

for pid in "${PIDS[@]}"; do
  stop_pid "$pid"
done
if ! wait_port_free; then
  echo "dsh_isolate_reload: ${LISTEN} still listening after SIGTERM/SIGKILL" >&2
  exit 1
fi
exit 0
