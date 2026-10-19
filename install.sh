#!/usr/bin/env bash
# Covenant Flow installer. Canal v1 = copy into the consumer git and commit.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  install.sh --init [--target DIR]
  install.sh --pin <vMAJOR.MINOR.PATCH> [--target DIR] [--source DIR]
  install.sh --account [--check | --remove] [--target DIR] [--source DIR]

--init     Write .covenant-flow/overlay.yaml with required keys empty. Does not guess values.
--pin      Copy nucleus, adapters, .agents/skills, helpers, and render AGENTS.md.
           Also installs the Claude Code adapter files (CLAUDE.md only when absent,
           .claude/skills bridges, .claude/agents) and writes .covenant-flow/adapters.json.
           It writes NO hook registration for Claude Code, Cursor, Codex or OpenCode and
           removes only Covenant Flow's entries from their project registration files; the
           Grok Build and dsh registrations are copied as before.
           scripts/process-fsm/route-landmarks.yaml (the T5 clone-gate catalog) is consumer data:
           copied as a seed only when absent, never overwritten or deleted.
           Requires a valid filled overlay. Refuses submodule / empty overlay.
--account  Install the account shim (~/.config/covenant-flow/shim/) and merge one hook
           registration into the global config of each of Claude Code, Cursor, Codex and
           OpenCode found on this machine (foreign entries preserved; Grok Build and dsh
           untouched). --check reports per host (and for the consumer at --target) what is
           missing or unreviewed; --remove takes only Covenant Flow's entries out. It never
           records trust: the operator runs `cf_shim.py trust --record`.

v1 refuses submodule, gitignore-as-install, marketplace, and template-clone as the channel.
USAGE
}

PRODUCT_ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET="$(pwd)"
MODE=""
PIN=""
ACCOUNT_ACTION="install"
SOURCE="$PRODUCT_ROOT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --init) MODE="init"; shift ;;
    --pin) MODE="pin"; PIN="${2:-}"; shift 2 ;;
    --account) MODE="account"; shift ;;
    --check) ACCOUNT_ACTION="check"; shift ;;
    --remove) ACCOUNT_ACTION="remove"; shift ;;
    --target) TARGET="$(cd "${2:-.}" && pwd)"; shift 2 ;;
    --source) SOURCE="$(cd "${2:-.}" && pwd)"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown arg: $1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$MODE" ]]; then
  usage >&2
  exit 2
fi
if [[ "$MODE" != "account" && "$ACCOUNT_ACTION" != "install" ]]; then
  die "--check and --remove apply to --account only"
fi

die() { echo "implantar: $*" >&2; exit 1; }

refuse_bad_channels() {
  if [[ -f "$TARGET/.gitmodules" ]] && grep -qE 'path = \.cursor/?$' "$TARGET/.gitmodules"; then
    die "v1 recusa submodule em .cursor/"
  fi
  if [[ -d "$TARGET/.cursor/.git" ]]; then
    die "v1 recusa .cursor como repositório/submodule separado"
  fi
}

python_overlay() {
  PYTHONPATH="$SOURCE/scripts/process-fsm${PYTHONPATH:+:$PYTHONPATH}" python3 "$@"
}

copy_tree() {
  local from="$1" to="$2"
  mkdir -p "$(dirname "$to")"
  rsync -a --delete "$from" "$to"
}

# CLAUDE.md is consumer-owned once it exists. It is created only when absent; an
# existing file is kept byte for byte and must already import AGENTS.md, otherwise
# Claude Code would not load the project law and the pin refuses visibly.
claude_memory() {
  local action="$1"
  CLAUDE_MD_SOURCE="$SOURCE/CLAUDE.md" CLAUDE_MD_TARGET="$TARGET/CLAUDE.md" python3 - "$action" <<'PY'
import os
import re
import sys
from pathlib import Path

action = sys.argv[1]
source = Path(os.environ["CLAUDE_MD_SOURCE"])
target = Path(os.environ["CLAUDE_MD_TARGET"])
IMPORT = re.compile(r"(?:^|\s)@(?:\./)?AGENTS\.md(?=\s|$)")


def imports_agents(text: str) -> bool:
    # An import inside a fenced block or an inline code span is not an import.
    text = re.sub(r"(?ms)^(```|~~~).*?^\1", "", text)
    text = re.sub(r"`[^`\n]*`", "", text)
    return bool(IMPORT.search(text))


if not source.is_file() or not imports_agents(source.read_text(encoding="utf-8")):
    raise SystemExit(f"implantar: source CLAUDE.md missing or without the @AGENTS.md import: {source}")
if target.is_symlink() or (target.exists() and not target.is_file()):
    raise SystemExit(f"implantar: CLAUDE.md conflict: {target} is not a regular file; compose it explicitly before --pin")
if target.exists():
    if not imports_agents(target.read_text(encoding="utf-8", errors="replace")):
        raise SystemExit(
            f"implantar: CLAUDE.md conflict: {target} exists without an @AGENTS.md import; "
            "add the import explicitly before --pin (the pin never edits an existing CLAUDE.md)"
        )
    print("preserving existing CLAUDE.md (imports AGENTS.md)" if action == "install" else "CLAUDE.md preflight: PASS (existing file imports AGENTS.md)")
elif action == "install":
    target.write_bytes(source.read_bytes())
    print(f"created {target}")
else:
    print("CLAUDE.md preflight: PASS (absent; will be created)")
PY
}

copy_tree_if_missing() {
  local from="$1" to="$2"
  if [[ -e "$to" ]]; then
    echo "preserving existing path: $to"
    return
  fi
  copy_tree "$from" "$to"
}

if [[ "$MODE" == "init" ]]; then
  refuse_bad_channels
  mkdir -p "$TARGET/.covenant-flow"
  dest="$TARGET/.covenant-flow/overlay.yaml"
  if [[ -f "$dest" ]]; then
    echo "overlay already exists: $dest"
  else
    python_overlay - <<PY
from pathlib import Path
from overlay import write_init
write_init(Path("$TARGET"))
PY
    echo "wrote $dest (empty required keys)"
  fi
  python_overlay - <<PY
from pathlib import Path
from overlay import empty_required_keys, load_overlay
data = load_overlay(Path("$TARGET"), require_filled=False)
keys = empty_required_keys(data)
print("empty keys:")
for key in keys:
    print(" -", key)
PY
  exit 0
fi

if [[ "$MODE" == "account" ]]; then
  # Operator account only: nothing is written to a consumer and no trust is recorded.
  [[ -f "$SOURCE/scripts/process-fsm/account_install.py" && -f "$SOURCE/scripts/process-fsm/cf_shim.py" ]] || die "source has no account shim: $SOURCE"
  exec python3 "$SOURCE/scripts/process-fsm/account_install.py" "$ACCOUNT_ACTION" --source "$SOURCE/scripts/process-fsm" --target "$TARGET"
fi

if [[ "$MODE" != "pin" ]]; then
  die "unknown mode"
fi

[[ "$PIN" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "pin must be vMAJOR.MINOR.PATCH, got ${PIN:-empty}"
[[ -d "$SOURCE/.cursor" ]] || die "source is not a covenant-flow tree: $SOURCE"
refuse_bad_channels
[[ -f "$TARGET/.covenant-flow/overlay.yaml" ]] || die "overlay missing; run --init and fill keys before --pin"

python_overlay - <<PY
from pathlib import Path
from overlay import OverlayError, load_overlay
try:
    load_overlay(Path("$TARGET"), require_filled=True)
except OverlayError as exc:
    raise SystemExit(f"overlay invalid: {exc}")
PY

# All Codex collisions are checked before any part of the pin is written. The
# bridge preflight refuses operator-edited skills without touching vendor paths.
# Hook registration is not written by the pin (it lives in the operator account):
# the project-registration preflight only proves that Covenant Flow's entries can be
# removed from the project files without loss.
python_overlay "$SOURCE/scripts/process-fsm/project_registration.py" preflight --source "$SOURCE" --target "$TARGET"
python_overlay "$SOURCE/scripts/process-fsm/codex_skills.py" preflight --source "$SOURCE" --target "$TARGET"
python_overlay "$SOURCE/scripts/process-fsm/codex_agents.py" preflight --source "$SOURCE" --target "$TARGET"
# Claude Code collisions are also checked before anything is written: an own
# CLAUDE.md without the AGENTS.md import and operator-edited bridges or agents
# under .claude/. Preflight never trusts.
claude_memory preflight
python_overlay "$SOURCE/scripts/process-fsm/claude_skills.py" preflight --source "$SOURCE" --target "$TARGET"
python_overlay "$SOURCE/scripts/process-fsm/claude_agents.py" preflight --source "$SOURCE" --target "$TARGET"
# Preflight only the shipped mechanisms. Never read the account's selections.
for mechanism in .cursor/model-policy.yaml scripts/process-fsm/model_selection.py scripts/process-fsm/model_selection_adapter.py scripts/process-fsm/model_selection_lib.js scripts/process-fsm/model_proxy.py scripts/process-fsm/release_model_selection.py scripts/process-fsm/codex_adapter.py scripts/process-fsm/codex_binding.py scripts/process-fsm/codex_proxy.py scripts/process-fsm/codex_review.py scripts/process-fsm/codex_evidence.py scripts/process-fsm/codex_fs.py scripts/process-fsm/claude_adapter.py scripts/process-fsm/claude_agents.py scripts/process-fsm/claude_evidence.py scripts/process-fsm/claude_proxy.py scripts/process-fsm/claude_review.py scripts/process-fsm/claude_skills.py scripts/process-fsm/claude_trust.py scripts/process-fsm/cf_shim.py scripts/process-fsm/cf_shim_opencode.js scripts/process-fsm/account_install.py scripts/process-fsm/account_registration.py scripts/process-fsm/adapter_manifest.py scripts/process-fsm/project_registration.py .claude/agents/diff-reviewer.md .claude/agents/code-reviewer.md CLAUDE.md .dsh/plugin/process-fsm-guard.js .opencode/plugin/process-fsm-guard.js .opencode/plugin/impeccable-hook.js .cursor/hooks/process-fsm-model-selection.sh .grok/hooks/process-fsm-model-selection.sh; do
  [[ -f "$SOURCE/$mechanism" ]] || die "selection mechanism missing in source: $mechanism"
done
python_overlay - <<PY
from model_selection import policy
if "claude" not in policy()["clients"]:
    raise SystemExit("implantar: source policy lacks the claude contract")
PY

# Terminal-flow delta is shipped from the nucleus. Missing members refuse
# before copying; the consumer's overlay document is never a generic doc target.
TERMINAL_MEMBERS=(
  scripts/process-fsm/codex_qualification_index.py
  scripts/process-fsm/codex_qualification.py
  scripts/process-fsm/codex_terminal.py
  scripts/process-fsm/codex_terminal_review.py
  docs/codex-terminal-flow.md
  docs/codex-runtime-evidence.md
  docs/codex-native-capabilities.md
  docs/codex-review-qualification.md
)
for terminal_member in "${TERMINAL_MEMBERS[@]}"; do
  [[ -f "$SOURCE/$terminal_member" ]] || die "terminal mechanism missing in source: $terminal_member"
done
TERMINAL_TARGET="$TARGET" python_overlay - <<'PY'
import os
from pathlib import Path
from overlay import load_overlay
root = Path(os.environ["TERMINAL_TARGET"])
doc = load_overlay(root, require_filled=True).get("overlay_doc")
generic_docs = {root / ("docs/" + name + ".md") for name in ("codex-terminal-flow", "codex-runtime-evidence", "codex-native-capabilities", "codex-review-qualification")}
if doc and (root / doc).resolve() in {path.resolve() for path in generic_docs}:
    raise SystemExit("implantar: terminal docs collide with consumer-owned overlay_doc")
PY

copy_tree "$SOURCE/.cursor/model-policy.yaml" "$TARGET/.cursor/model-policy.yaml"
copy_tree "$SOURCE/.cursor/process-fsm.yaml" "$TARGET/.cursor/process-fsm.yaml"
copy_tree "$SOURCE/.cursor/hooks/" "$TARGET/.cursor/hooks/"
copy_tree "$SOURCE/.cursor/rules/" "$TARGET/.cursor/rules/"
copy_tree "$SOURCE/.cursor/commands/" "$TARGET/.cursor/commands/"
copy_tree "$SOURCE/.cursor/agents/" "$TARGET/.cursor/agents/"
copy_tree "$SOURCE/.cursor/skills/" "$TARGET/.cursor/skills/"
rm -f "$TARGET/.cursor/BUGBOT.md"
find "$TARGET" -name 'BUGBOT.md' ! -path '*/.git/*' -print -delete

copy_tree "$SOURCE/.grok/hooks/" "$TARGET/.grok/hooks/"
mkdir -p "$TARGET/.grok/rules"
copy_tree "$SOURCE/.grok/rules/00-harness.md" "$TARGET/.grok/rules/00-harness.md"
copy_tree "$SOURCE/.grok/skills/" "$TARGET/.grok/skills/"

# The OpenCode adapter modules go to .opencode/adapter/ below (not auto-loaded by the host).
copy_tree "$SOURCE/.opencode/skills/" "$TARGET/.opencode/skills/"

copy_tree "$SOURCE/.dsh/plugin/" "$TARGET/.dsh/plugin/"
copy_tree "$SOURCE/.dsh/skills/" "$TARGET/.dsh/skills/"
copy_tree "$SOURCE/.dsh/cordis.patch.yml" "$TARGET/.dsh/cordis.patch.yml"

copy_tree_if_missing "$SOURCE/.agents/skills/impeccable/" "$TARGET/.agents/skills/impeccable/"
copy_tree_if_missing "$SOURCE/.agents/skills/playwright-cli/" "$TARGET/.agents/skills/playwright-cli/"

# route-landmarks.yaml is consumer data (the catalog of the T5 clone gate): the nucleus ships a seed that is
# copied only when the consumer has none, and the --delete of the tree sync never reaches the consumer's file.
rsync_process_fsm() {
  mkdir -p "$TARGET/scripts"
  rsync -a --delete --exclude='/route-landmarks.yaml' "$SOURCE/scripts/process-fsm/" "$TARGET/scripts/process-fsm/"
}
rsync_process_fsm
for terminal_doc in codex-terminal-flow codex-runtime-evidence codex-native-capabilities codex-review-qualification; do
  copy_tree "$SOURCE/docs/$terminal_doc.md" "$TARGET/docs/$terminal_doc.md"
done
if [[ -f "$SOURCE/scripts/process-fsm/route-landmarks.yaml" ]]; then
  copy_tree_if_missing "$SOURCE/scripts/process-fsm/route-landmarks.yaml" "$TARGET/scripts/process-fsm/route-landmarks.yaml"
fi
copy_tree "$SOURCE/scripts/release-guard" "$TARGET/scripts/release-guard"
if [[ -f "$SOURCE/scripts/post-card-evidence-comment.sh" ]]; then
  copy_tree "$SOURCE/scripts/post-card-evidence-comment.sh" "$TARGET/scripts/post-card-evidence-comment.sh"
fi
# release-guard calls this helper beside itself when PROD_DEPLOY_EVIDENCE is set (#968).
if [[ -f "$SOURCE/scripts/release_guard_prod_evidence.py" ]]; then
  copy_tree "$SOURCE/scripts/release_guard_prod_evidence.py" "$TARGET/scripts/release_guard_prod_evidence.py"
fi

python_overlay "$TARGET/scripts/process-fsm/codex_skills.py" install --source "$TARGET" --target "$TARGET"
python_overlay "$SOURCE/scripts/process-fsm/codex_agents.py" install --source "$SOURCE" --target "$TARGET"

# Claude Code adapter. Bridges come from SOURCE so an operator-installed vendor
# skill under .agents/skills (kept above) is never parsed or rewritten. The account
# trust record is never read or written.
claude_memory install
python_overlay "$SOURCE/scripts/process-fsm/claude_skills.py" install --source "$SOURCE" --target "$TARGET"
python_overlay "$SOURCE/scripts/process-fsm/claude_agents.py" install --source "$SOURCE" --target "$TARGET"
python_overlay "$SOURCE/scripts/process-fsm/claude_skills.py" check --source "$SOURCE" --target "$TARGET"
python_overlay "$SOURCE/scripts/process-fsm/claude_agents.py" check --source "$SOURCE" --target "$TARGET"
for adapter_file in "$SOURCE"/scripts/process-fsm/claude_*.py; do
  cmp -s "$adapter_file" "$TARGET/scripts/process-fsm/$(basename "$adapter_file")" || die "Claude adapter file differs after copy: $(basename "$adapter_file")"
done

# Account-registration pin: no hook registration of Claude Code, Cursor, Codex or OpenCode stays in
# the consumer (only Covenant Flow's entries are removed; the OpenCode adapter modules move out of the
# auto-load path). Grok Build (.grok/hooks/) and dsh (.dsh/) keep their project registration.
python_overlay "$SOURCE/scripts/process-fsm/project_registration.py" apply --source "$SOURCE" --target "$TARGET"
python_overlay "$SOURCE/scripts/process-fsm/project_registration.py" check --source "$SOURCE" --target "$TARGET"

python_overlay - <<PY
from pathlib import Path
from overlay import load_overlay, render_agents, set_pin
root = Path("$TARGET")
set_pin(root, "$PIN")
overlay = load_overlay(root, require_filled=True)
root.joinpath("AGENTS.md").write_text(render_agents(overlay), encoding="utf-8")
print("pin", "$PIN")
print("overlay_doc", overlay.get("overlay_doc"))
PY

# The adapter manifest is what the account shim reads; written last, over the copied files.
python_overlay "$SOURCE/scripts/process-fsm/adapter_manifest.py" write --root "$TARGET" --pin "$PIN"
python_overlay "$SOURCE/scripts/process-fsm/adapter_manifest.py" check --root "$TARGET"

# Do not touch overlay_doc markdown or account model selections.
echo "No hook registration was written to the consumer: run \`install.sh --account\` once in the operator account."
echo "The pin does not confer trust: the operator reviews with \`python3 ~/.config/covenant-flow/shim/current/cf_shim.py trust --record\` (Codex also needs its own /hooks review)."
echo "implantar --pin $PIN complete in $TARGET"
echo "Commit these trees in the consumer git (not a submodule)."
