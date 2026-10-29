"""Generate and check `.covenant-flow/adapters.json`, the adapter manifest the pin writes.

The manifest is what lets the account shim (`cf_shim.py`) tell "old pin, project registration" from
"new pin, adapter gone": it declares, per client, how the client is registered (`account` for the four
clients whose global mechanism was proven, `project` for Grok Build and dsh, never `account` for a host
that is `unproven`), the shim protocol, the entry points and the files the adapter can execute with
their digests. The shim compares the worktree with it before every run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cf_shim

# Tool caches are not adapter code: a pytest run rewrites `.pytest_cache/v/cache/nodeids`, and listing it would make the
# shim deny every hook with `adapter_divergent`. `.pytest_cache` is excluded per tree with a pattern the shim applies too
# (`fnmatch` lets `*` cross `/`), at any depth, so both sides of the comparison agree. Beyond that, the only cache is
# `__pycache__/` with the `.pyc` inside it (`cf_shim.is_cache_file`): a loose `.pyc`, `node_modules/` or `.git` inside a
# declared tree can be imported or executed, so they belong to A (R5).
CACHE_EXCLUDE = "*/.pytest_cache/*"
# Data and fixtures the hook never executes stay out of A (R1, R2): editing them must not deny every hook.
DATA_EXCLUDES = ("scripts/process-fsm/route-landmarks.yaml", "scripts/process-fsm/*_fixtures.py")

CORE_TREES = (
    {
        "path": "scripts/process-fsm",
        "exclude": [
            "scripts/process-fsm/test_*",
            "scripts/process-fsm/fixtures/*",
            "scripts/process-fsm/conftest.py",
            *DATA_EXCLUDES,
            CACHE_EXCLUDE,
        ],
    },
    # A vendored Impeccable without hook scripts has nothing to execute; scripts added later show up as divergent.
    {"path": ".agents/skills/impeccable/scripts", "exclude": [CACHE_EXCLUDE], "optional": True},
)
CLIENT_TREES = {
    "claude": (),
    "codex": (),
    "cursor": ({"path": ".cursor/hooks", "exclude": [CACHE_EXCLUDE]},),
    "opencode": ({"path": ".opencode/adapter", "exclude": [CACHE_EXCLUDE]},),
}


def _is_cache_file(relative: str) -> bool:
    return cf_shim.is_cache_file(relative)


def _python_entries(adapter: str, events: tuple[str, ...]) -> dict[str, list[str]]:
    return {event: ["python3", f"scripts/process-fsm/{adapter}", event] for event in events}


ENTRYPOINTS: dict[str, dict[str, list[str]]] = {
    "claude": _python_entries("claude_adapter.py", ("session-start", "pre-tool-use", "post-tool-use", "subagent-stop", "stop", "prompt-submit")),
    "codex": _python_entries("codex_adapter.py", ("session-start", "pre-tool-use", "post-tool-use", "stop")),
    "cursor": {
        "session-start": ["bash", ".cursor/hooks/process-fsm-session-start.sh"],
        "guard": ["bash", ".cursor/hooks/process-fsm-guard.sh"],
        "model-selection": ["bash", ".cursor/hooks/process-fsm-model-selection.sh"],
        "impeccable-after-file-edit": ["bash", ".cursor/hooks/impeccable.sh", "afterFileEdit"],
        "impeccable-stop": ["bash", ".cursor/hooks/impeccable.sh", "stop"],
        "subagent-stop": ["bash", ".cursor/hooks/process-fsm-subagent-stop.sh"],
    },
}
OPENCODE_MODULES = (".opencode/adapter/process-fsm-guard.js", ".opencode/adapter/impeccable-hook.js")
PROJECT_CLIENTS = ("grok", "dsh")


class ManifestBuildError(ValueError):
    pass


def client_entry(root: Path, client: str) -> dict[str, Any]:
    trees = [dict(tree) for tree in (*CORE_TREES, *CLIENT_TREES[client])]
    files: list[str] = []
    for tree in trees:
        listed = [path for path in cf_shim.enumerate_tree(root, tree) if not _is_cache_file(path)]
        if not listed and not tree.get("optional"):
            raise ManifestBuildError(f"{client}: adapter tree {tree['path']} is empty or missing under {root}")
        files.extend(listed)
    entry: dict[str, Any] = {"registration": cf_shim.HOST_REGISTRATION[client], "trees": trees}
    if client == "opencode":
        missing = [m for m in OPENCODE_MODULES if not (root / m).is_file()]
        if missing:
            raise ManifestBuildError(f"opencode: adapter module(s) missing: {', '.join(missing)}")
        entry["modules"] = list(OPENCODE_MODULES)
    else:
        entry["entrypoints"] = ENTRYPOINTS[client]
        for argv in ENTRYPOINTS[client].values():
            if not (root / argv[1]).is_file():
                raise ManifestBuildError(f"{client}: entry point {argv[1]} is missing under {root}")
    if entry["registration"] != "account":
        # An unproven host keeps only the visible failure: no entry points, no file list.
        return {"registration": entry["registration"]}
    digests = cf_shim.hash_files(root, sorted(set(files)))
    # A listed file that yields no digest (unreadable, or a symlink to a file) is a failure of the pin, never a silent drop (R6).
    undigested = sorted(path for path, digest in digests.items() if digest is None)
    if undigested:
        raise ManifestBuildError(f"{client}: cannot compute a digest for adapter file(s): {', '.join(undigested[:5])}")
    entry["files"] = dict(digests)
    return entry


def build(root: str | Path, pin: str) -> dict[str, Any]:
    base = Path(root).resolve()
    clients = {client: client_entry(base, client) for client in cf_shim.CLIENTS}
    for client in PROJECT_CLIENTS:
        clients[client] = {"registration": "project"}
    return {"schema": 1, "pin": pin, "shim_protocol": cf_shim.SHIM_PROTOCOL, "clients": clients}


def render(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")


def write(root: str | Path, pin: str) -> Path:
    path = Path(root).resolve() / cf_shim.MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(render(build(root, pin)))
    return path


def check(root: str | Path) -> None:
    base = Path(root).resolve()
    existing = cf_shim.load_manifest(base)
    if existing is None:
        raise ManifestBuildError(f"adapter manifest missing: {base / cf_shim.MANIFEST}")
    fresh = build(base, str(existing.get("pin")))
    if render(fresh) != render(existing):
        raise ManifestBuildError(f"adapter manifest differs from the worktree: {base / cf_shim.MANIFEST}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("write", "check"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--pin")
    args = parser.parse_args(argv)
    try:
        if args.action == "write":
            if not args.pin:
                parser.error("--pin is required for write")
            print(f"wrote {write(args.root, args.pin)}")
        else:
            check(args.root)
            print("adapter manifest check: PASS")
    except (ManifestBuildError, cf_shim.ManifestError, OSError) as exc:
        print(f"adapter manifest error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
