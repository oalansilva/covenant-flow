#!/usr/bin/env bash
# Covenant Flow installer. Canal v1 = copy into the consumer git and commit.
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  install.sh --init [--target DIR]
  install.sh --pin <vMAJOR.MINOR.PATCH> [--target DIR] [--source DIR]

--init   Write .covenant-flow/overlay.yaml with required keys empty. Does not guess values.
--pin    Copy nucleus, adapters, .agents/skills, helpers, and render AGENTS.md.
         Requires a valid filled overlay. Refuses submodule / empty overlay.

v1 refuses submodule, gitignore-as-install, marketplace, and template-clone as the channel.
USAGE
}

PRODUCT_ROOT="$(cd "$(dirname "$0")" && pwd)"
TARGET="$(pwd)"
MODE=""
PIN=""
SOURCE="$PRODUCT_ROOT"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --init) MODE="init"; shift ;;
    --pin) MODE="pin"; PIN="${2:-}"; shift 2 ;;
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

copy_tree "$SOURCE/.cursor/process-fsm.yaml" "$TARGET/.cursor/process-fsm.yaml"
copy_tree "$SOURCE/.cursor/hooks.json" "$TARGET/.cursor/hooks.json"
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

copy_tree "$SOURCE/.opencode/plugin/" "$TARGET/.opencode/plugin/"
copy_tree "$SOURCE/.opencode/skills/" "$TARGET/.opencode/skills/"

copy_tree "$SOURCE/.dsh/plugin/" "$TARGET/.dsh/plugin/"
copy_tree "$SOURCE/.dsh/skills/" "$TARGET/.dsh/skills/"
copy_tree "$SOURCE/.dsh/cordis.patch.yml" "$TARGET/.dsh/cordis.patch.yml"

copy_tree "$SOURCE/.agents/skills/impeccable/" "$TARGET/.agents/skills/impeccable/"
copy_tree "$SOURCE/.agents/skills/design-critic/" "$TARGET/.agents/skills/design-critic/"
copy_tree "$SOURCE/.agents/skills/playwright-cli/" "$TARGET/.agents/skills/playwright-cli/"

copy_tree "$SOURCE/scripts/process-fsm/" "$TARGET/scripts/process-fsm/"
copy_tree "$SOURCE/scripts/release-guard" "$TARGET/scripts/release-guard"
if [[ -f "$SOURCE/scripts/post-card-evidence-comment.sh" ]]; then
  copy_tree "$SOURCE/scripts/post-card-evidence-comment.sh" "$TARGET/scripts/post-card-evidence-comment.sh"
fi

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

# Do not touch overlay_doc markdown.
echo "implantar --pin $PIN complete in $TARGET"
echo "Commit these trees in the consumer git (not a submodule)."
