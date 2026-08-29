#!/usr/bin/env bash
# Materialize .dsh/cordis.patch.yml with absolute plugin names and exec dsh web --patch.
# Pin channel is install.sh --pin, not `dsh plugin add`.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PATCH_SRC="$REPO_ROOT/.dsh/cordis.patch.yml"
GUARD_JS="$REPO_ROOT/.dsh/plugin/process-fsm-guard.js"
HOOK_JS="$REPO_ROOT/.dsh/plugin/impeccable-hook.js"

[[ -f "$PATCH_SRC" ]] || { echo "dsh_boot: missing $PATCH_SRC" >&2; exit 1; }
[[ -f "$GUARD_JS" ]] || { echo "dsh_boot: missing $GUARD_JS" >&2; exit 1; }
[[ -f "$HOOK_JS" ]] || { echo "dsh_boot: missing $HOOK_JS" >&2; exit 1; }

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

TMP_PATCH="$(mktemp "${TMPDIR:-/tmp}/covenant-flow-dsh-XXXXXX.patch.yml")"
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

cleanup() { rm -f "$TMP_PATCH"; }
trap cleanup EXIT

cd "$LAUNCH_DIR"
dsh web --patch "$TMP_PATCH"
