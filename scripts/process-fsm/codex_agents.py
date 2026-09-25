"""Safely install project-scoped Codex reviewer roles without model defaults."""

from __future__ import annotations

import argparse
import sys
import tomllib
from pathlib import Path

from codex_fs import atomic_write_bytes


class AgentConfigError(ValueError):
    """A Codex role file is invalid or conflicts with operator-owned content."""


def _read_role(path: Path) -> tuple[str, bytes]:
    try:
        content = path.read_bytes()
        parsed = tomllib.loads(content.decode("utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise AgentConfigError(f"cannot parse Codex agent role {path}: {exc}") from exc
    name = parsed.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AgentConfigError(f"Codex agent role has no name: {path}")
    for key in ("model", "model_reasoning_effort"):
        if key in parsed:
            raise AgentConfigError(f"Codex role {path} must not set {key}; route from model-map per spawn")
    if parsed.get("sandbox_mode") != "read-only":
        raise AgentConfigError(f"Codex reviewer role must set sandbox_mode=read-only: {path}")
    for key in ("description", "developer_instructions"):
        if not isinstance(parsed.get(key), str) or not parsed[key].strip():
            raise AgentConfigError(f"Codex agent role missing {key}: {path}")
    return name, content


def plan(source_root: str | Path, target_root: str | Path) -> list[tuple[Path, bytes]]:
    source = Path(source_root) / ".codex" / "agents"
    target = Path(target_root) / ".codex" / "agents"
    if not source.is_dir():
        raise AgentConfigError(f"Codex agent roles directory missing: {source}")
    roles: list[tuple[Path, bytes]] = []
    names: set[str] = set()
    errors: list[str] = []
    for path in sorted(source.glob("*.toml")):
        name, content = _read_role(path)
        if name in names:
            errors.append(f"duplicate Codex agent name: {name}")
            continue
        names.add(name)
        destination = target / path.name
        if destination.exists():
            try:
                current = destination.read_bytes()
            except OSError as exc:
                errors.append(f"cannot read existing Codex role {destination}: {exc}")
                continue
            if current != content:
                errors.append(f"existing Codex role differs; operator review required: {destination}")
                continue
        roles.append((destination, content))
    if errors:
        raise AgentConfigError("Codex agent role conflict; no files changed:\n" + "\n".join(errors))
    return roles


def install(source_root: str | Path, target_root: str | Path, *, check_only: bool = False) -> list[Path]:
    planned = plan(source_root, target_root)
    missing = [(path, content) for path, content in planned if not path.exists()]
    if check_only and missing:
        raise AgentConfigError(
            "Codex agent role check failed; missing: " + ", ".join(str(path) for path, _ in missing)
        )
    if check_only:
        return []
    for path, content in missing:
        atomic_write_bytes(path, content)
    return [path for path, _ in missing]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "install", "check"))
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        if args.action == "preflight":
            roles = plan(args.source, args.target)
            print(f"Codex agent role preflight: PASS ({len(roles)} role(s); no files changed)")
        else:
            changed = install(args.source, args.target, check_only=args.action == "check")
            for path in changed:
                print(f"installed Codex role: {path}")
            if args.action == "check":
                print("Codex agent role check: PASS")
    except AgentConfigError as exc:
        print(f"codex agent role error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
