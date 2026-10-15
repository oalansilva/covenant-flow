"""Generate and verify the read-only Claude Code reviewer agents.

`.claude/agents/<name>.md` is a short contract that pins neither model nor
effort (they come per spawn from the captured local selection) and grants only
`Read, Grep, Glob`. The reviewer contract itself lives in the canonical
`.cursor/agents/<name>.md`; the agent file records that file's SHA-256 so drift
is detected instead of silently copied.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import yaml

from codex_fs import atomic_write_bytes

ROLES = ("diff-reviewer", "code-reviewer")
TOOLS = "Read, Grep, Glob"
FORBIDDEN_TOOLS = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Agent", "Task", "WebFetch", "WebSearch"}
HASH_LINE = re.compile(r"^canonical_sha256: ([0-9a-f]{64})$", re.MULTILINE)


class AgentConfigError(ValueError):
    """A Claude Code reviewer agent is invalid, drifted or conflicts with operator content."""


def _canonical(source: Path, name: str) -> tuple[bytes, str]:
    path = source / ".cursor" / "agents" / f"{name}.md"
    try:
        body = path.read_bytes()
    except OSError as exc:
        raise AgentConfigError(f"canonical reviewer contract missing: {path}") from exc
    text = body.decode("utf-8")
    if not text.startswith("---\n"):
        raise AgentConfigError(f"canonical reviewer has no frontmatter: {path}")
    try:
        meta = yaml.safe_load(text.split("---\n", 2)[1])
    except yaml.YAMLError as exc:
        raise AgentConfigError(f"invalid canonical frontmatter {path}: {exc}") from exc
    if not isinstance(meta, dict) or meta.get("name") != name or not isinstance(meta.get("description"), str):
        raise AgentConfigError(f"canonical reviewer frontmatter mismatch: {path}")
    return body, meta["description"].strip()


def render(source: Path, name: str) -> bytes:
    body, description = _canonical(source, name)
    digest = hashlib.sha256(body).hexdigest()
    text = (
        "---\n"
        f"name: {name}\n"
        f"description: {json.dumps(description, ensure_ascii=False)}\n"
        f"tools: {TOOLS}\n"
        "---\n\n"
        f"Read the complete `.cursor/agents/{name}.md` first and follow it as the sole reviewer contract.\n"
        f"canonical_sha256: {digest}\n\n"
        "This file adds only:\n\n"
        "- The parent supplies the exact interval through `review_diff_path:` and `review_diff_sha256:` "
        "(or bytes under `## Diff`). Read only that file; if it is missing or empty print exactly "
        "`ERROR: review-diff missing` and stop.\n"
        "- You have only Read, Grep and Glob. Do not run git, list or open agent transcripts, "
        "edit or write files, or spawn agents.\n"
        "- Model and effort are chosen per spawn from the captured local selection; this file pins none.\n"
        "- Return the labeled `FINDING` blocks or exactly `No findings.` as the canonical contract defines.\n"
    )
    return text.encode("utf-8")


def validate(path: Path, source: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AgentConfigError(f"agent has no frontmatter: {path}")
    meta = yaml.safe_load(text.split("---\n", 2)[1])
    if not isinstance(meta, dict):
        raise AgentConfigError(f"agent frontmatter must be an object: {path}")
    if "model" in meta or "effort" in meta:
        raise AgentConfigError(f"{path} must not pin model/effort; the pair comes per spawn")
    tools = {t.strip() for t in str(meta.get("tools", "")).split(",") if t.strip()}
    if tools != {"Read", "Grep", "Glob"} or tools & FORBIDDEN_TOOLS:
        raise AgentConfigError(f"{path} must grant only Read, Grep, Glob; got {sorted(tools)}")
    match = HASH_LINE.search(text)
    name = meta.get("name")
    if name not in ROLES or not match:
        raise AgentConfigError(f"{path} lacks a role name or canonical_sha256")
    body, _ = _canonical(source, name)
    if match[1] != hashlib.sha256(body).hexdigest():
        raise AgentConfigError(f"{path} canonical hash is stale; regenerate from .cursor/agents/{name}.md")


def plan(source_root: str | Path, target_root: str | Path) -> list[tuple[Path, bytes]]:
    source, target = Path(source_root), Path(target_root) / ".claude" / "agents"
    planned, errors = [], []
    for name in ROLES:
        content = render(source, name)
        destination = target / f"{name}.md"
        if destination.exists() and destination.read_bytes() != content:
            errors.append(f"existing Claude agent differs; operator review required: {destination}")
            continue
        planned.append((destination, content))
    if errors:
        raise AgentConfigError("Claude agent conflict; no files changed:\n" + "\n".join(errors))
    return planned


def install(source_root: str | Path, target_root: str | Path, *, check_only: bool = False) -> list[Path]:
    planned = plan(source_root, target_root)
    missing = [(p, c) for p, c in planned if not p.exists()]
    if check_only:
        if missing:
            raise AgentConfigError("Claude agent check failed; missing: " + ", ".join(str(p) for p, _ in missing))
        for path, _ in planned:
            validate(path, Path(source_root))
        return []
    for path, content in missing:
        atomic_write_bytes(path, content)
    return [p for p, _ in missing]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preflight", "install", "check"))
    parser.add_argument("--source", type=Path)
    parser.add_argument("--target", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    source = args.source or args.target
    try:
        if args.action == "preflight":
            print(f"Claude agent preflight: PASS ({len(plan(source, args.target))} role(s); no files changed)")
        else:
            for path in install(source, args.target, check_only=args.action == "check"):
                print(f"installed Claude agent: {path}")
            if args.action == "check":
                print("Claude agent check: PASS")
    except AgentConfigError as exc:
        print(f"claude agent error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
