"""Safely merge Covenant Flow's Claude Code project hooks into a consumer project.

Reuses the Codex merger: only handlers whose command points at
`scripts/process-fsm/claude_adapter.py` are replaced; every other key, matcher
group and handler of the consumer's `.claude/settings.json` is preserved.
Installing the hooks never grants trust (see `claude_trust.py`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from codex_fs import atomic_write_bytes
from codex_hooks import HookConfigError, _read_json, merge_hooks

MARKER = "scripts/process-fsm/claude_adapter.py"
SETTINGS = Path(".claude") / "settings.json"


def plan(source_root: str | Path, target_root: str | Path) -> tuple[Path, dict[str, Any], bytes]:
    source_path = Path(source_root) / SETTINGS
    target_path = Path(target_root) / SETTINGS
    source_document = _read_json(source_path)
    if not isinstance(source_document.get("hooks"), dict):
        raise HookConfigError(f"source Claude Code settings lack an object `hooks`: {source_path}")
    target_document = _read_json(target_path) if target_path.exists() else None
    merged = merge_hooks(
        source_document, target_document, target_path=target_path,
        marker=MARKER, source_label="source .claude/settings.json",
    )
    rendered = (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return target_path, merged, rendered


def install(source_root: str | Path, target_root: str | Path, *, check_only: bool = False) -> bool:
    path, _document, rendered = plan(source_root, target_root)
    current = path.read_bytes() if path.exists() else None
    if check_only:
        if current != rendered:
            raise HookConfigError(f"Claude Code hook merge differs; no files changed: {path}")
        return False
    if current == rendered:
        return False
    atomic_write_bytes(path, rendered)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "install", "check"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.action == "preflight":
            plan(args.source, args.target)
            print("Claude Code hook merge preflight: PASS (no files changed)")
        elif args.action == "check":
            install(args.source, args.target, check_only=True)
            print("Claude Code hook merge check: PASS")
        elif install(args.source, args.target):
            print(f"merged Covenant Flow hooks into {args.target / SETTINGS}")
        else:
            print("Claude Code hooks already current")
    except HookConfigError as exc:
        print(f"claude hook merge error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
