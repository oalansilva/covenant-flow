"""Take the Covenant Flow hook registration out of a consumer project (the account-registration pin).

From the account-registration pin onward `install.sh --pin` no longer writes hook registration for
Claude Code, Cursor, Codex or OpenCode into the consumer: it is installed once in the operator account
by `install.sh --account` (see `cf_shim.py`). This module is the pin's side of that rule:

* `.claude/settings.json`, `.codex/hooks.json`, `.cursor/hooks.json`: only the entries that call the
  Covenant Flow adapters are removed; every foreign key, matcher group and handler is kept. A file
  that only held Covenant Flow entries is deleted. Malformed JSON or a non-object `hooks` refuses
  visibly before anything is written.
* `.opencode/plugin/`: the two adapter modules move to `.opencode/adapter/`, a directory the host does
  not auto-load, so that the account's global plugin is the only thing that runs them; foreign plugins
  stay where they are.
* Grok Build (`.grok/hooks/`) and dsh (`.dsh/`) are not touched here: their project registration stays.

Nothing here records trust.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

from codex_fs import atomic_write_bytes
from codex_hooks import HookConfigError, _read_json

NESTED = {  # settings file -> marker of the handlers Covenant Flow owns
    ".claude/settings.json": "scripts/process-fsm/claude_adapter.py",
    ".codex/hooks.json": "scripts/process-fsm/codex_adapter.py",
}
CURSOR_FILE = ".cursor/hooks.json"
CURSOR_MARKERS = (".cursor/hooks/process-fsm-", ".cursor/hooks/impeccable.sh", "./hooks/impeccable.sh")
CODEX_DESCRIPTION_PREFIX = "Covenant Flow local adapter hooks"
OPENCODE_MODULES = ("process-fsm-guard.js", "impeccable-hook.js")
OPENCODE_AUTOLOAD = Path(".opencode") / "plugin"
OPENCODE_ADAPTER = Path(".opencode") / "adapter"


def _owned(command: Any, marker: str) -> bool:
    return isinstance(command, str) and marker in command.replace("\\", "/")


def _strip_nested(document: dict[str, Any], marker: str, path: Path) -> dict[str, Any]:
    result = json.loads(json.dumps(document))
    hooks = result.get("hooks")
    if hooks is None:
        return result
    if not isinstance(hooks, dict):
        raise HookConfigError(f"`hooks` must be an object in {path}")
    for event in list(hooks):
        groups = hooks[event]
        if not isinstance(groups, list):
            raise HookConfigError(f"invalid hooks event/group list in {path}: {event!r}")
        kept = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list) or any(not isinstance(h, dict) for h in group["hooks"]):
                raise HookConfigError(f"invalid hook matcher group in {path} ({event})")
            remaining = [h for h in group["hooks"] if not _owned(h.get("command"), marker)]
            if len(remaining) != len(group["hooks"]) and not remaining:
                continue  # the group only held Covenant Flow handlers
            group["hooks"] = remaining
            kept.append(group)
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        del result["hooks"]
    return result


def _strip_cursor(document: dict[str, Any], path: Path) -> dict[str, Any]:
    result = json.loads(json.dumps(document))
    hooks = result.get("hooks")
    if hooks is None:
        return result
    if not isinstance(hooks, dict):
        raise HookConfigError(f"`hooks` must be an object in {path}")
    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list) or any(not isinstance(e, dict) for e in entries):
            raise HookConfigError(f"invalid hook entries for `{event}` in {path}")
        kept = [e for e in entries if not any(_owned(e.get("command"), marker) for marker in CURSOR_MARKERS)]
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    if not hooks:
        del result["hooks"]
    return result


def _only_ours(document: Mapping[str, Any], relative: str) -> bool:
    """Nothing foreign left: no hooks and no keys beyond the ones the product itself writes."""

    remaining = dict(document)
    if relative == CURSOR_FILE:
        remaining.pop("version", None)
    if relative == ".codex/hooks.json" and str(remaining.get("description", "")).startswith(CODEX_DESCRIPTION_PREFIX):
        remaining.pop("description")
    return not remaining


def plan(target_root: str | Path) -> list[tuple[Path, bytes | None]]:
    """(path, new bytes or None to delete) for every project registration file that changes."""

    target = Path(target_root)
    planned: list[tuple[Path, bytes | None]] = []
    for relative, marker in {**NESTED, CURSOR_FILE: ""}.items():
        path = target / relative
        if not path.exists():
            continue
        if path.is_symlink():
            raise HookConfigError(f"project registration is a symlink: {path}; compose it explicitly before --pin")
        document = _read_json(path)
        stripped = _strip_cursor(document, path) if relative == CURSOR_FILE else _strip_nested(document, marker, path)
        if stripped == document:
            continue
        planned.append((path, None if _only_ours(stripped, relative) else (json.dumps(stripped, indent=2, ensure_ascii=False) + "\n").encode("utf-8")))
    autoload = target / OPENCODE_AUTOLOAD
    if autoload.is_symlink() or (autoload.exists() and not autoload.is_dir()):
        raise HookConfigError(f"OpenCode plugin path is not a directory: {autoload}")
    adapter = target / OPENCODE_ADAPTER
    if adapter.is_symlink() or (adapter.exists() and not adapter.is_dir()):
        raise HookConfigError(f"OpenCode adapter path is not a directory: {adapter}")
    return planned


def apply(source_root: str | Path, target_root: str | Path) -> list[str]:
    source = Path(source_root)
    target = Path(target_root)
    modules = [source / OPENCODE_AUTOLOAD / name for name in OPENCODE_MODULES]
    missing = [str(m) for m in modules if not m.is_file()]
    if missing:
        raise HookConfigError(f"OpenCode adapter module(s) missing in the source: {', '.join(missing)}")
    planned = plan(target)
    notes: list[str] = []
    for module in modules:
        atomic_write_bytes(target / OPENCODE_ADAPTER / module.name, module.read_bytes())
    for module in modules:
        stale = target / OPENCODE_AUTOLOAD / module.name
        if stale.exists() or stale.is_symlink():
            stale.unlink()
            notes.append(f"moved {stale.relative_to(target)} out of the OpenCode auto-load path")
    autoload = target / OPENCODE_AUTOLOAD
    if autoload.is_dir() and not any(autoload.iterdir()):
        autoload.rmdir()
    for path, content in planned:
        if content is None:
            path.unlink()
            notes.append(f"removed {path.relative_to(target)} (held only Covenant Flow entries)")
        else:
            atomic_write_bytes(path, content)
            notes.append(f"removed Covenant Flow entries from {path.relative_to(target)}")
    return notes


def check(source_root: str | Path, target_root: str | Path) -> None:
    target = Path(target_root)
    if plan(target):
        raise HookConfigError("a Covenant Flow hook registration remains in the project; the account-registration pin must not leave one")
    for name in OPENCODE_MODULES:
        if (target / OPENCODE_AUTOLOAD / name).exists():
            raise HookConfigError(f"OpenCode adapter module still auto-loaded: {OPENCODE_AUTOLOAD / name}")
        if (target / OPENCODE_ADAPTER / name).read_bytes() != (Path(source_root) / OPENCODE_AUTOLOAD / name).read_bytes():
            raise HookConfigError(f"OpenCode adapter module differs from the source: {OPENCODE_ADAPTER / name}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "apply", "check"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.action == "preflight":
            plan(args.target)
            print("project registration preflight: PASS (no files changed)")
        elif args.action == "check":
            check(args.source, args.target)
            print("project registration check: PASS (no Covenant Flow registration in the project)")
        else:
            for line in apply(args.source, args.target) or ["no Covenant Flow project registration to remove"]:
                print(line)
    except (HookConfigError, OSError) as exc:
        print(f"project registration error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
