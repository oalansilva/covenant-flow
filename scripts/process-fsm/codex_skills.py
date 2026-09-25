"""Generate and safely install thin Codex bridges to canonical Cursor skills."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from codex_fs import atomic_write_bytes

import yaml


MANIFEST = ".covenant-flow-bridges.json"
# The pre-bridge product shipped a full copy of design-critic at this path.
LEGACY_DESIGN_CRITIC_SHA256 = "4e75831e94356dea58df8ee56d04ffdbac3fb8d0d93482cb54eaa62ec57b6d13"
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


class BridgeError(ValueError):
    """A skill bridge cannot be reconciled without risking local content."""


def _metadata(skill_file: Path) -> tuple[str, str]:
    text = skill_file.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise BridgeError(f"canonical skill has no YAML frontmatter: {skill_file}")
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        raise BridgeError(f"canonical skill has incomplete YAML frontmatter: {skill_file}")
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise BridgeError(f"invalid frontmatter in {skill_file}: {exc}") from exc
    if not isinstance(data, dict):
        raise BridgeError(f"canonical skill frontmatter must be an object: {skill_file}")
    name = data.get("name")
    description = data.get("description")
    if not isinstance(name, str) or not SKILL_NAME.fullmatch(name):
        raise BridgeError(f"invalid skill name in {skill_file}: {name!r}")
    if not isinstance(description, str) or not description.strip():
        raise BridgeError(f"missing skill description in {skill_file}")
    return name, description.strip()


def render_bridge(name: str, description: str) -> str:
    canonical = f".cursor/skills/{name}/SKILL.md"
    return (
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        "---\n\n"
        "# Canonical skill bridge\n\n"
        f"Read the complete `{canonical}` file and follow it as the sole runbook. "
        "This bridge intentionally contains no copied workflow.\n"
    )


def expected_bridges(source_root: str | Path) -> dict[str, str]:
    root = Path(source_root)
    skills_root = root / ".cursor" / "skills"
    if not skills_root.is_dir():
        raise BridgeError(f"canonical skills directory missing: {skills_root}")

    bridges: dict[str, str] = {}
    for skill_file in sorted(skills_root.glob("*/SKILL.md")):
        name, description = _metadata(skill_file)
        if name in bridges:
            raise BridgeError(f"duplicate canonical skill name: {name}")
        if skill_file.parent.name != name:
            raise BridgeError(f"canonical skill directory/name mismatch: {skill_file}")
        bridges[name] = render_bridge(name, description)
    if not bridges:
        raise BridgeError(f"no canonical skills found under {skills_root}")
    return bridges


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_manifest(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BridgeError(f"cannot read bridge manifest {path}: {exc}") from exc
    if (
        not isinstance(data, dict)
        or data.get("version") != 1
        or not isinstance(data.get("files"), dict)
        or any(not isinstance(k, str) or not isinstance(v, str) for k, v in data["files"].items())
    ):
        raise BridgeError(f"invalid bridge manifest: {path}")
    return data


def _atomic_write(path: Path, content: bytes) -> None:
    atomic_write_bytes(path, content)


def install_bridges(
    source_root: str | Path,
    target_root: str | Path,
    *,
    check_only: bool = False,
    preflight_only: bool = False,
) -> list[str]:
    """Install generated bridges; preserve non-Covenant skills and refuse edits."""

    source = Path(source_root)
    target = Path(target_root)
    bridges = expected_bridges(source)
    skills_root = target / ".agents" / "skills"
    manifest_path = skills_root / MANIFEST
    previous = _read_manifest(manifest_path)
    old_files = previous["files"] if previous else {}

    planned: list[tuple[str, Path, bytes, str]] = []
    errors: list[str] = []
    for name, text in bridges.items():
        relative = f"{name}/SKILL.md"
        destination = skills_root / relative
        expected = text.encode("utf-8")
        desired_hash = _digest(expected)
        if not destination.exists():
            planned.append((name, destination, expected, "create"))
            continue
        current = destination.read_bytes()
        if current == expected:
            continue
        previous_hash = old_files.get(relative)
        if previous_hash and previous_hash == _digest(current):
            planned.append((name, destination, expected, "update generated"))
            continue
        if name == "design-critic" and _digest(current) == LEGACY_DESIGN_CRITIC_SHA256:
            planned.append((name, destination, expected, "reconcile legacy copy"))
            continue
        errors.append(f"{destination}: existing content is not an unchanged managed bridge")

    stale_managed = set(old_files) - {f"{name}/SKILL.md" for name in bridges}
    if stale_managed:
        errors.append(
            f"{manifest_path}: stale managed skill(s) need explicit review: "
            + ", ".join(sorted(stale_managed))
        )
    if errors:
        raise BridgeError("skill bridge conflict; no files changed:\n" + "\n".join(errors))
    if preflight_only:
        return [f"preflight: {len(planned)} bridge(s) will be installed or updated"]
    if check_only and planned:
        paths = ", ".join(str(item[1]) for item in planned)
        raise BridgeError(f"skill bridge coverage/drift check failed; needs install: {paths}")

    manifest = {
        "version": 1,
        "files": {
            f"{name}/SKILL.md": _digest(text.encode("utf-8"))
            for name, text in bridges.items()
        },
    }
    if check_only:
        if previous is None:
            raise BridgeError(f"skill bridge manifest missing: {manifest_path}")
        if previous != manifest:
            raise BridgeError(f"skill bridge manifest drift: {manifest_path}")
        return []

    changed: list[str] = []
    for name, destination, content, action in planned:
        _atomic_write(destination, content)
        changed.append(f"{action}: .agents/skills/{name}/SKILL.md")
    manifest_bytes = (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    if not manifest_path.exists() or manifest_path.read_bytes() != manifest_bytes:
        _atomic_write(manifest_path, manifest_bytes)
        changed.append("updated .agents/skills/" + MANIFEST)
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "install", "check", "preflight"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--target", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    source = args.source or args.target
    try:
        changed = install_bridges(
            source,
            args.target,
            check_only=args.action == "check",
            preflight_only=args.action == "preflight",
        )
    except BridgeError as exc:
        print(f"codex skill bridge error: {exc}", file=sys.stderr)
        return 2
    for line in changed:
        print(line)
    if args.action == "check":
        print("Codex skill bridge coverage/drift: PASS")
    elif args.action == "preflight":
        print("Codex skill bridge conflict preflight: PASS (no files changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
