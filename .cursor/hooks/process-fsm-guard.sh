#!/usr/bin/env bash
# Cursor adapter: process-fsm Guard Write. Always emit JSON (failClosed on Write).
set -u
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
GUARD="$ROOT/scripts/process-fsm/guard.py"
RAW="$(cat)"

emit() {
  printf '%s\n' "$1"
}

fallback() {
  # Decision 12: prefix-match without PyYAML (stdlib json + git only).
  PROCESS_FSM_RAW="$RAW" PROCESS_FSM_ROOT="$ROOT" python3 - <<'PY' 2>/dev/null || true
import json, os, re, subprocess, sys

raw = os.environ.get("PROCESS_FSM_RAW") or ""
try:
    payload = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    payload = {}
if not isinstance(payload, dict):
    payload = {}

cwd = str(
    payload.get("cwd")
    or payload.get("workspaceRoot")
    or payload.get("directory")
    or payload.get("worktree")
    or os.getcwd()
)
tool = str(payload.get("tool_name") or payload.get("toolName") or payload.get("tool") or "")

def _as_dict(raw):
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}

data = _as_dict(payload.get("tool_input"))
if not data:
    data = _as_dict(payload.get("toolInput"))
if not data:
    data = _as_dict(payload.get("args"))
paths = []
for key in ("path", "file_path", "file", "target_file", "target_notebook", "filePath"):
    value = data.get(key)
    if isinstance(value, str) and value.strip():
        paths.append(value.strip())
        break
patch = data.get("patchText") if isinstance(data.get("patchText"), str) else ""
if not patch:
    patch = data.get("patch_text") if isinstance(data.get("patch_text"), str) else ""
if patch:
    for line in patch.splitlines():
        stripped = line.strip()
        for marker in (
            "*** Add File:",
            "*** Update File:",
            "*** Delete File:",
            "*** Move to:",
            "*** Move File:",
        ):
            if stripped.startswith(marker):
                found = stripped[len(marker):].strip()
                if found and found not in paths:
                    paths.append(found)
                break
path = paths[0] if paths else None
command = payload.get("command") if isinstance(payload.get("command"), str) else ""
if not command:
    nested = data.get("command")
    command = nested if isinstance(nested, str) else ""
def _overlay_board(root):
    path = os.path.join(root, ".covenant-flow", "overlay.yaml")
    if not os.path.isfile(path):
        return "", [], [], []
    text = open(path, encoding="utf-8").read()
    field = ""
    m = re.search(r"status_field_id:\s*[\"']?([^\"'\s]+)", text)
    if m:
        field = m.group(1)
    options = re.findall(r":\s*[\"']?([0-9a-f]{8})[\"']?\s*$", text, re.M)
    def _globs(key):
        block = re.search(rf"{key}:\n((?:\s+-\s+.+\n)*)", text)
        if not block:
            return []
        return [ln.split("-", 1)[1].strip().rstrip("*").rstrip("/") + "/" for ln in block.group(1).splitlines() if ln.strip()]
    return field, options, _globs("product_globs"), _globs("design_globs")

ov_field, ov_options, ov_product, ov_design = _overlay_board(os.environ.get("PROCESS_FSM_ROOT") or cwd)
if "item-edit" in command and (
    (ov_field and ov_field in command)
    or "updateProjectV2ItemFieldValue" in command
    or "--single-select-option-id" in command
    or any(x in command for x in ov_options)
):
    msg = "process-fsm-guard deny reason=status_item_edit. Use process_event."
    print(json.dumps({"permission": "deny", "decision": "deny", "agent_message": msg, "user_message": msg, "reason": msg}))
    sys.exit(0)
if "updateProjectV2ItemFieldValue" in command:
    msg = "process-fsm-guard deny reason=status_item_edit. Use process_event."
    print(json.dumps({"permission": "deny", "decision": "deny", "agent_message": msg, "user_message": msg, "reason": msg}))
    sys.exit(0)
# Card #631: deny sidecar only on mutation, not mere citation.
sys.path.insert(0, os.path.join(os.environ.get("PROCESS_FSM_ROOT", ""), "scripts", "process-fsm"))
try:
    from board_status import is_sidecar_path as _is_sidecar_path
    from board_status import sidecar_mutation_in_command as _sidecar_mut
except Exception:
    def _is_sidecar_path(p):
        return bool(p) and str(p).replace("\\", "/").endswith(".design-digest")
    def _sidecar_mut(c):
        return False
if _sidecar_mut(command) or any(_is_sidecar_path(p) for p in paths):
    msg = "process-fsm-guard deny reason=sidecar"
    print(json.dumps({"permission": "deny", "decision": "deny", "agent_message": msg, "user_message": msg, "reason": msg}))
    sys.exit(0)
if path is None and command:
    import os as _os
    non_redir = re.search(r"(?:sed\s+-i|perl\s+-i|\bcp\s+|\bmv\s+|\binstall\s+)", command)
    targets = []
    for m in re.finditer(r"(?:\d*)?(>>|>)\s*([^\s|;<>&]+)", command):
        t = m.group(2).strip().strip("'\"")
        if t.startswith("&"):
            continue
        targets.append(t)
    for m in re.finditer(r"\btee(?:\s+-a)?\s+([^\s|;<>&]+)", command):
        targets.append(m.group(1).strip().strip("'\""))
    def allowlisted(t):
        if t == "/dev/null":
            return True
        if t == "/tmp" or t.startswith("/tmp/"):
            real_t = _os.path.realpath(t)
            real_c = _os.path.realpath(cwd)
            if real_t == real_c or real_t.startswith(real_c + _os.sep):
                return False
            return True
        return False
    if (targets and all(allowlisted(t) for t in targets) and not non_redir) or (not targets and not non_redir):
        path = None
    else:
        product_hit = None
        for t in targets:
            if allowlisted(t):
                continue
            prefixes = tuple(ov_product + ov_design)
            if any(t.startswith(p) or f"/{p}" in f"/{t}" for p in prefixes):
                product_hit = t
                break
        if product_hit:
            path = product_hit
        elif non_redir or any(not allowlisted(t) for t in targets):
            joined = "|".join(re.escape(p.rstrip("/")) for p in (ov_product + ov_design) if p) or "never-match"
            match = re.search(
                rf"((?:/(?:[\w.-]+))*/(?:{joined})/[^\s'\"|;<>&]+|"
                rf"(?:{joined})/[^\s'\"|;<>&]+)",
                command,
            )
            if match:
                path = match.group(1)
                if path.startswith("./"):
                    path = path[2:]
if path and path not in paths:
    paths.append(path)
if not paths:
    if tool in ("write", "edit", "apply_patch"):
        msg = "process-fsm-guard deny reason=empty_path. write/edit/apply_patch (file_path or filePath) and str_replace_editor mutate (create/str_replace/insert path) require an extractable path."
        print(json.dumps({"permission": "deny", "decision": "deny", "agent_message": msg, "user_message": msg, "reason": msg}))
        sys.exit(0)
    print(json.dumps({"permission": "allow", "decision": "allow", "reason": ""}))
    sys.exit(0)

def _posix(p):
    text = p.replace("\\", "/")
    if text.startswith("./"):
        text = text[2:]
    for prefix in ov_product + ov_design:
        marker = "/" + prefix
        idx = text.find(marker)
        if idx != -1:
            text = text[idx + 1 :]
            break
    return text

normalized = [_posix(p) for p in paths]
if any(item.endswith(".design-digest") for item in normalized):
    msg = "process-fsm-guard deny reason=sidecar"
    print(json.dumps({"permission": "deny", "decision": "deny", "agent_message": msg, "user_message": msg, "reason": msg}))
    sys.exit(0)
if not ov_product and not ov_design:
    msg = "process-fsm-guard deny reason=overlay"
    print(json.dumps({"permission": "deny", "decision": "deny", "agent_message": msg, "user_message": msg, "reason": msg}))
    sys.exit(0)
is_product = any(any(item.startswith(p) for p in ov_product) for item in normalized)
is_design = any(any(item.startswith(p) for p in ov_design) for item in normalized)
anchor = next(
    (p for p, item in zip(paths, normalized) if any(item.startswith(pref) for pref in ov_product)),
    paths[0],
)
target = anchor if os.path.isabs(anchor) else os.path.join(cwd, anchor)
git_dir = target if os.path.isdir(target) else os.path.dirname(target) or cwd
while git_dir and not os.path.isdir(git_dir):
    parent = os.path.dirname(git_dir)
    if parent == git_dir:
        git_dir = cwd
        break
    git_dir = parent
env = os.environ.copy()
for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE"):
    env.pop(key, None)
try:
    proc = subprocess.run(
        ["git", "-C", git_dir, "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, timeout=5, env=env, check=False,
    )
    branch = (proc.stdout or "").strip()
except (OSError, subprocess.TimeoutExpired):
    branch = ""
card = bool(re.match(r"^card-\d+(?:-.*)?$", branch or ""))
msg = "process-fsm-guard deny reason=fail_closed (python fallback)"
if is_product:
    print(json.dumps({"permission": "deny", "decision": "deny", "agent_message": msg, "user_message": msg, "reason": msg}))
elif is_design and card:
    print(json.dumps({"permission": "allow", "decision": "allow", "reason": ""}))
elif is_design:
    print(json.dumps({"permission": "deny", "decision": "deny", "agent_message": msg, "user_message": msg, "reason": msg}))
else:
    print(json.dumps({"permission": "allow", "decision": "allow", "reason": ""}))
PY
}

PY=""
if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PY="$ROOT/backend/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
fi

if [[ -n "$PY" && -f "$GUARD" ]]; then
  OUT="$(printf '%s' "$RAW" | "$PY" "$GUARD" 2>/dev/null || true)"
  if printf '%s' "$OUT" | grep -q '"permission"'; then
    emit "$OUT"
    exit 0
  fi
fi

FB="$(fallback || true)"
if printf '%s' "$FB" | grep -q '"permission"'; then
  emit "$FB"
  exit 0
fi

emit '{"permission":"deny","decision":"deny","agent_message":"process-fsm-guard deny reason=fail_closed","user_message":"process-fsm-guard deny reason=fail_closed","reason":"process-fsm-guard deny reason=fail_closed"}'
exit 0
