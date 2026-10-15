"""Generate and safely install thin Claude Code bridges to the canonical skills.

Same bridge contract, manifest and drift refusal as `codex_skills.py` (reused,
not forked), targeting `.claude/skills/`. The bridges carry no workflow text.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import codex_skills
from codex_skills import BridgeError, expected_bridges as canonical_bridges, install_bridges as _install, render_bridge

SKILLS_DIR = (".claude", "skills")
# Not canonical Cursor skills: vendored content under .agents/skills/, bridged in place.
VENDORED = ("impeccable", "playwright-cli")


def expected_bridges(source_root: str | Path) -> dict[str, str]:
    source = Path(source_root)
    bridges = dict(canonical_bridges(source))
    for name in VENDORED:
        skill_file = source / ".agents" / "skills" / name / "SKILL.md"
        if not skill_file.is_file():
            raise BridgeError(f"vendored skill missing: {skill_file}")
        declared, description = codex_skills._metadata(skill_file)
        if declared != name:
            raise BridgeError(f"vendored skill name mismatch: {skill_file}")
        if name in bridges:
            raise BridgeError(f"vendored skill collides with a canonical skill: {name}")
        bridges[name] = render_bridge(name, description, f".agents/skills/{name}/SKILL.md")
    return dict(sorted(bridges.items()))


def install_bridges(source_root, target_root, *, check_only=False, preflight_only=False) -> list[str]:
    return _install(
        source_root, target_root, check_only=check_only, preflight_only=preflight_only,
        skills_dir=SKILLS_DIR, bridges=expected_bridges(source_root),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "install", "check", "preflight"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--target", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    source = args.source or args.target
    try:
        changed = install_bridges(source, args.target, check_only=args.action == "check", preflight_only=args.action == "preflight")
    except BridgeError as exc:
        print(f"claude skill bridge error: {exc}", file=sys.stderr)
        return 2
    for line in changed:
        print(line)
    if args.action == "check":
        print("Claude skill bridge coverage/drift: PASS")
    elif args.action == "preflight":
        print("Claude skill bridge conflict preflight: PASS (no files changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
