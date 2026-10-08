"""Safely merge Covenant Flow's local Codex hooks into a consumer project."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any, Mapping

from codex_fs import atomic_write_bytes


class HookConfigError(ValueError):
    """A Codex hook configuration cannot be merged without operator review."""


def _read_json(path: Path, *, missing: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if missing is not None:
            return missing
        raise HookConfigError(f"hook configuration missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HookConfigError(f"cannot read Codex hooks JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise HookConfigError(f"Codex hooks JSON must be an object: {path}")
    return value


def _validate_groups(document: Mapping[str, Any], path: Path) -> dict[str, list[dict[str, Any]]]:
    raw = document.get("hooks", {})
    if not isinstance(raw, dict):
        raise HookConfigError(f"Codex hooks must be an object in {path}")
    result: dict[str, list[dict[str, Any]]] = {}
    for event, groups in raw.items():
        if not isinstance(event, str) or not isinstance(groups, list):
            raise HookConfigError(f"invalid hooks event/group list in {path}: {event!r}")
        clean: list[dict[str, Any]] = []
        for group in groups:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                raise HookConfigError(f"invalid hook matcher group in {path} ({event})")
            if any(not isinstance(handler, dict) for handler in group["hooks"]):
                raise HookConfigError(f"invalid hook handler in {path} ({event})")
            clean.append(json.loads(json.dumps(group)))
        result[event] = clean
    return result


def _is_managed(handler: Mapping[str, Any]) -> bool:
    command = handler.get("command")
    return isinstance(command, str) and "scripts/process-fsm/codex_adapter.py" in command.replace("\\", "/")


def _matcher(group: Mapping[str, Any]) -> Any:
    return group.get("matcher")


def merge_hooks(source_document: Mapping[str, Any], target_document: Mapping[str, Any] | None, *, target_path: Path) -> dict[str, Any]:
    """Preserve all operator keys/handlers and replace only this adapter's handlers."""

    source_groups = _validate_groups(source_document, Path("source .codex/hooks.json"))
    target = dict(target_document) if target_document is not None else {
        key: value for key, value in source_document.items() if key != "hooks"
    }
    target_groups = _validate_groups(target, target_path) if target_document is not None else {}

    for event, groups in target_groups.items():
        for group in groups:
            group["hooks"] = [handler for handler in group["hooks"] if not _is_managed(handler)]
        # Keep operator group metadata and empty groups; only managed handlers
        # are removed. This avoids destroying unknown matcher-group fields.

    for event, desired_groups in source_groups.items():
        existing = target_groups.setdefault(event, [])
        for desired in desired_groups:
            candidates = [group for group in existing if _matcher(group) == _matcher(desired)]
            if candidates:
                candidates[0]["hooks"].extend(json.loads(json.dumps(desired["hooks"])))
            else:
                existing.append(json.loads(json.dumps(desired)))

    target["hooks"] = target_groups
    return target


def _load_toml_hooks(path: Path) -> bool:
    if not path.exists():
        return False
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise HookConfigError(f"cannot parse Codex config TOML {path}: {exc}") from exc
    if "hooks" in document:
        raise HookConfigError(
            f"Codex hook conflict: {path} defines [hooks]; compose it explicitly before --pin"
        )
    return False


def plan(source_root: str | Path, target_root: str | Path) -> tuple[Path, dict[str, Any], bytes]:
    source = Path(source_root)
    target = Path(target_root)
    source_path = source / ".codex" / "hooks.json"
    target_path = target / ".codex" / "hooks.json"
    config_toml = target / ".codex" / "config.toml"
    _load_toml_hooks(config_toml)
    source_document = _read_json(source_path)
    if not isinstance(source_document.get("hooks"), dict):
        raise HookConfigError(f"source Codex hooks lack an object `hooks`: {source_path}")
    target_document = _read_json(target_path, missing=None) if target_path.exists() else None
    merged = merge_hooks(source_document, target_document, target_path=target_path)
    rendered = (json.dumps(merged, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return target_path, merged, rendered


def install(source_root: str | Path, target_root: str | Path, *, check_only: bool = False) -> bool:
    path, _document, rendered = plan(source_root, target_root)
    if check_only:
        current = path.read_bytes() if path.exists() else b""
        if current != rendered:
            raise HookConfigError(f"Codex hook merge differs; no files changed: {path}")
        return False
    current = path.read_bytes() if path.exists() else None
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
            print("Codex hook merge preflight: PASS (no files changed)")
        elif args.action == "check":
            install(args.source, args.target, check_only=True)
            print("Codex hook merge check: PASS")
        elif install(args.source, args.target):
            print(f"merged Covenant Flow hooks into {args.target / '.codex' / 'hooks.json'}")
        else:
            print("Codex hooks already current")
    except HookConfigError as exc:
        print(f"codex hook merge error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
