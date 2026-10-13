"""Hook trust review and session heartbeat for the Claude Code adapter.

Pinning, installation or the host's workspace-trust dialog never count as
review. Protection exists only while the digest of the hook definition and of
the adapter code in use equals a digest the operator explicitly recorded on
this account (`claude_adapter.py trust --record`). The digest covers the hook
block, the adapter's Python modules and the Impeccable hook script the adapter
runs (`hook.mjs` plus its relative-import closure), when present.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

from model_selection import claude_version_from_env

HERE = Path(__file__).resolve().parent
ADAPTER = "claude_adapter.py"
SETTINGS = Path(".claude") / "settings.json"
UNAVAILABLE = "unavailable"


class TrustError(ValueError):
    pass


def config_dir() -> Path:
    return Path.home() / ".config" / "covenant-flow"


def trust_path() -> Path:
    return config_dir() / "claude-hook-trust.json"


def heartbeat_dir() -> Path:
    return config_dir() / "claude-sessions"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def adapter_modules(scripts_dir: Path = HERE) -> list[Path]:
    """Transitive closure of local modules imported (even lazily) by the adapter."""

    seen: dict[str, Path] = {}
    pending = [ADAPTER[:-3]]
    while pending:
        name = pending.pop()
        if name in seen:
            continue
        path = scripts_dir / f"{name}.py"
        if not path.is_file():
            continue
        seen[name] = path
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            raise TrustError(f"cannot parse adapter module {path}: {exc}") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                pending.extend(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                pending.append(node.module.split(".")[0])
    return [seen[name] for name in sorted(seen)]


def project_root(scripts_dir: Path = HERE) -> Path:
    return scripts_dir.parents[1]


def hooks_block(root: Path) -> Any:
    path = root / SETTINGS
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TrustError(f"cannot read hook definition {path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("hooks"), dict):
        raise TrustError(f"hook definition has no `hooks` object: {path}")
    return document["hooks"]


IMPECCABLE_HOOK = Path(".agents") / "skills" / "impeccable" / "scripts" / "hook.mjs"
_RELATIVE_IMPORT = re.compile(r"""\b(?:from|import)\s*\(?\s*['"](\.{1,2}/[^'"\n]+)['"]""")


def impeccable_files(root: Path) -> list[Path]:
    """`hook.mjs` (run by the adapter on PostToolUse/Stop) and its local relative-import closure.

    Absent files are skipped (consumers without Impeccable); files outside `root` never enter.
    """

    root = Path(root).resolve()
    seen: dict[Path, None] = {}
    pending = [(root / IMPECCABLE_HOOK).resolve()]
    while pending:
        path = pending.pop()
        if path in seen or not path.is_file() or not path.is_relative_to(root):
            continue
        seen[path] = None
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise TrustError(f"cannot read impeccable hook module {path}: {exc}") from exc
        pending.extend((path.parent / spec).resolve() for spec in _RELATIVE_IMPORT.findall(text))
    return sorted(seen)


def current_digest(root: Path | None = None, scripts_dir: Path = HERE) -> dict[str, Any]:
    """Digest of the hook block, every adapter module reachable from the adapter and the Impeccable hook script closure."""

    repo = Path(root) if root is not None else project_root(scripts_dir)
    files = {
        path.relative_to(scripts_dir).as_posix(): _sha256(path.read_bytes())
        for path in adapter_modules(scripts_dir)
    }
    for path in impeccable_files(repo):
        files[path.relative_to(repo.resolve()).as_posix()] = _sha256(path.read_bytes())
    hooks = hooks_block(repo)
    body = {
        "hooks": hooks,
        "hooks_sha256": _sha256(json.dumps(hooks, sort_keys=True, separators=(",", ":")).encode()),
        "files": files,
    }
    return {"digest": _sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()), **body}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _private_write(path: Path, value: Mapping[str, Any], *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if path.is_symlink():
        raise TrustError(f"unsafe destination: {path}")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".claude-trust-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path) if replace else os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def record(root: Path | None = None, scripts_dir: Path = HERE) -> dict[str, Any]:
    """Operator act: remember the digest of the definition they just reviewed."""

    current = current_digest(root, scripts_dir)
    document = _read_json(trust_path()) if trust_path().exists() else {"version": 1, "reviews": {}}
    if not isinstance(document, dict) or document.get("version") != 1 or not isinstance(document.get("reviews"), dict):
        raise TrustError(f"cannot extend invalid trust record: {trust_path()}")
    document["reviews"][current["digest"]] = {
        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(Path(root) if root is not None else project_root(scripts_dir)),
        "hooks_sha256": current["hooks_sha256"],
        "files": current["files"],
    }
    _private_write(trust_path(), document, replace=True)
    return {"recorded": current["digest"], "path": str(trust_path()), "files": sorted(current["files"])}


def is_reviewed(digest: str) -> bool:
    document = _read_json(trust_path())
    return isinstance(document, dict) and isinstance(document.get("reviews"), dict) and digest in document["reviews"]


def status(root: Path | None = None, scripts_dir: Path = HERE) -> dict[str, Any]:
    """Never raises: an unreadable definition is simply unreviewed."""

    try:
        current = current_digest(root, scripts_dir)
    except TrustError as exc:
        return {"reviewed": False, "digest": UNAVAILABLE, "reason": str(exc)}
    reviewed = is_reviewed(current["digest"])
    return {
        "reviewed": reviewed,
        "digest": current["digest"],
        "reason": "" if reviewed else "hooks não revisados: run `claude_adapter.py trust --record` after reading .claude/settings.json and the adapter",
    }


def host_version(environ: Mapping[str, str] | None = None) -> str:
    # Env only (never `claude --version`): the heartbeat runs on every SessionStart.
    return claude_version_from_env(environ) or UNAVAILABLE


def write_heartbeat(
    *,
    session_id: str,
    transcript_path: str,
    cwd: str,
    digest: str,
    reviewed: bool,
    environ: Mapping[str, str] | None = None,
    version: str | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
        raise TrustError(f"invalid session id for heartbeat: {session_id!r}")
    path = heartbeat_dir() / f"{session_id}.json"
    _private_write(
        path,
        {
            "version": 1,
            "session_id": session_id,
            "transcript_path": transcript_path or UNAVAILABLE,
            "cwd": cwd,
            "host_version": version or host_version(env),
            "entrypoint": env.get("CLAUDE_CODE_ENTRYPOINT") or UNAVAILABLE,
            "hooks_digest": digest,
            "reviewed": reviewed,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        },
        replace=True,
    )
    return path


def read_heartbeat(session_id: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id or ""):
        return None
    value = _read_json(heartbeat_dir() / f"{session_id}.json")
    return value if isinstance(value, dict) and value.get("version") == 1 else None
