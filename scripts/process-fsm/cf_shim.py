#!/usr/bin/env python3
"""Covenant Flow account shim: one thin registration target for Claude Code, Cursor, Codex and OpenCode.

The shim lives in the operator account (`~/.config/covenant-flow/shim/<version>/`) and is the only
thing the host's global hook/plugin registration calls. On every event it finds the consumer from the
working directory of the event, checks the pinned adapter manifest and the operator's trust record and
then runs the adapter that the consumer pinned, with the original payload. It carries no FSM, Guard,
paging or model-selection logic: when anything is off it only says so, in the deny format of the host.

Decision table (`decide`): no overlay or no pin = nothing; pin before account registration (no
adapter manifest) = nothing (the project registration of that pin is the only one that runs); client
registered in the project or not proven = nothing; otherwise `shim_incompatible`, `adapter_missing`,
`adapter_divergent`, `hooks_unreviewed` or `consumer_ambiguous` are visible failures, and a clean
manifest runs the adapter. Standard library only: it runs before any consumer code is trusted.

Trust is the operator's explicit act (`cf_shim.py trust --record`), in two parts: `registration`
(the Covenant Flow entries of the host's account config plus the shim files) and `adapter` (every
file of the pinned manifest). Installing or pinning never records trust.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

SHIM_VERSION = "1.0.0"
SHIM_PROTOCOL = 1
SUPPORTED_PROTOCOLS = (1,)
CLIENTS = ("claude", "cursor", "codex", "opencode")
# The global mechanism each host offers, as proven by the rehearsal of 2026-10-14
# (openspec/changes/card-1101-claude-code-adapter/host-mechanisms.md). A host that is not proven
# is `unproven`: no entry is installed for it, the manifest never declares it `account`.
HOST_REGISTRATION = {"claude": "account", "cursor": "account", "codex": "account", "opencode": "account"}
SHIM_MARKER = "covenant-flow/shim/current/cf_shim.py"
OPENCODE_PLUGIN_NAME = "covenant-flow-shim.js"
OPENCODE_PLUGIN_HEADER = "// covenant-flow-shim: managed by `install.sh --account`; do not edit"
SHIM_FILES = {"claude": ("cf_shim.py",), "cursor": ("cf_shim.py",), "codex": ("cf_shim.py",), "opencode": ("cf_shim.py", "cf_shim_opencode.js")}
MANIFEST = Path(".covenant-flow") / "adapters.json"
OVERLAY = Path(".covenant-flow") / "overlay.yaml"
HOOK_TIMEOUT = 28
PIN_PATTERN = re.compile(r"^pin:\s*[\"']?([^\s\"'#]+)", re.MULTILINE)
SESSION_ID = re.compile(r"[A-Za-z0-9_.:-]{8,128}\Z")
UNAVAILABLE = "unavailable"

RECOVERY = {
    "shim_incompatible": "update the account shim with `install.sh --account` from the same covenant-flow checkout, then start a new session",
    "adapter_missing": "re-run `install.sh --pin <tag>` in the consumer to restore the adapter files",
    "adapter_divergent": "re-run `install.sh --pin <tag>` to restore the pinned adapter, or have the operator review the change and run `cf_shim.py trust --record`",
    "hooks_unreviewed": "the operator reads the registration and the adapter, then runs `python3 ~/.config/covenant-flow/shim/current/cf_shim.py trust --record --client <client>` from the consumer",
    "hooks_changed": "the account registration changed after this session started: start a new session",
    "consumer_ambiguous": "open the session in a single repository or worktree",
    "manifest_invalid": "re-run `install.sh --pin <tag>` to rewrite .covenant-flow/adapters.json",
    "shim_error": "check the shim with `install.sh --account --check` and start a new session",
}

GATING_EVENTS = {
    "claude": {"pre-tool-use"},
    "codex": {"pre-tool-use"},
    "cursor": {"guard", "model-selection"},
}
SESSION_EVENTS = {"claude": "session-start", "codex": "session-start", "cursor": "session-start"}


def config_dir() -> Path:
    return Path.home() / ".config" / "covenant-flow"


def shim_root() -> Path:
    return config_dir() / "shim"


def installed_shim_dir() -> Path:
    return shim_root() / "current"


def trust_path() -> Path:
    return config_dir() / "hook-trust.json"


def sessions_dir() -> Path:
    return config_dir() / "sessions"


def host_config_path(client: str) -> Path:
    home = Path.home()
    return {
        "claude": home / ".claude" / "settings.json",
        "cursor": home / ".cursor" / "hooks.json",
        "codex": home / ".codex" / "hooks.json",
        "opencode": home / ".config" / "opencode" / "plugin" / OPENCODE_PLUGIN_NAME,
    }[client]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _private_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise OSError(f"unsafe destination: {path}")
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".cf-shim-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, sort_keys=True, indent=2, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --------------------------------------------------------------------------- manifest and files


def git_toplevel(directory: str | Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
            check=False, capture_output=True, text=True, timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    top = result.stdout.strip()
    return Path(top).resolve() if result.returncode == 0 and top else None


def pin_of(root: Path) -> str | None:
    try:
        found = PIN_PATTERN.search((root / OVERLAY).read_text(encoding="utf-8"))
    except OSError:
        return None
    return found.group(1) if found else None


class ManifestError(ValueError):
    pass


def load_manifest(root: Path) -> dict[str, Any] | None:
    path = root / MANIFEST
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ManifestError(f"cannot read {path}: {exc}") from exc
    if not isinstance(document, dict) or not isinstance(document.get("clients"), dict):
        raise ManifestError(f"{path} has no `clients` object")
    return document


def enumerate_tree(root: Path, tree: Mapping[str, Any]) -> list[str]:
    """Repo-relative POSIX paths of one declared tree, minus its exclusions."""

    base = root / str(tree["path"])
    excludes = [str(item) for item in tree.get("exclude", [])]
    found: list[str] = []
    if not base.is_dir():
        return found
    for current, directories, names in os.walk(base):
        directories[:] = sorted(d for d in directories if d not in {"__pycache__", "node_modules", ".git"})
        for name in sorted(names):
            relative = (Path(current) / name).relative_to(root).as_posix()
            if name.endswith((".pyc", ".pyo")) or any(fnmatch.fnmatch(relative, pattern) for pattern in excludes):
                continue
            found.append(relative)
    return found


def hash_files(root: Path, files: list[str]) -> dict[str, str | None]:
    actual: dict[str, str | None] = {}
    for relative in files:
        path = root / relative
        try:
            actual[relative] = sha256_bytes(path.read_bytes()) if path.is_file() and not path.is_symlink() else None
        except OSError:
            actual[relative] = None
    return actual


@dataclass
class AdapterState:
    missing: list[str] = field(default_factory=list)
    divergent: list[str] = field(default_factory=list)
    digest: str = UNAVAILABLE


def adapter_state(root: Path, entry: Mapping[str, Any]) -> AdapterState:
    """Compare the worktree with the pinned manifest entry; the digest is the sha256 of what is on disk."""

    pinned = entry.get("files")
    if not isinstance(pinned, dict) or not pinned:
        raise ManifestError("manifest entry has no file list")
    listed = sorted(pinned)
    actual = hash_files(root, listed)
    state = AdapterState(missing=[p for p in listed if actual[p] is None])
    state.divergent = [p for p in listed if actual[p] is not None and actual[p] != pinned[p]]
    for tree in entry.get("trees", []):
        for extra in enumerate_tree(root, tree):
            if extra not in pinned:
                state.divergent.append(f"{extra} (not in manifest)")
    state.digest = sha256_bytes(canonical({p: actual[p] for p in listed}))
    return state


# --------------------------------------------------------------------------- registration (R)


def _managed_command(command: Any) -> bool:
    return isinstance(command, str) and SHIM_MARKER in command.replace("\\", "/")


def host_entries(client: str) -> list[Any] | None:
    """The Covenant Flow entries of the host's account config; None when the host has none."""

    path = host_config_path(client)
    if client == "opencode":
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return None
        return [text] if text.startswith(OPENCODE_PLUGIN_HEADER) else None
    document = _read_json(path)
    hooks = document.get("hooks") if isinstance(document, dict) else None
    if not isinstance(hooks, dict):
        return None
    found: list[Any] = []
    for event, groups in sorted(hooks.items()):
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            if client == "cursor":
                if _managed_command(group.get("command")):
                    found.append({"event": event, "entry": group})
                continue
            for handler in group.get("hooks", []) if isinstance(group.get("hooks"), list) else []:
                if isinstance(handler, dict) and _managed_command(handler.get("command")):
                    found.append({"event": event, "matcher": group.get("matcher"), "handler": handler})
    return found or None


def shim_file_digests(client: str) -> dict[str, str]:
    base = installed_shim_dir().resolve()
    digests: dict[str, str] = {}
    for name in SHIM_FILES[client]:
        path = base / name
        if path.is_file():
            digests[name] = sha256_bytes(path.read_bytes())
    return digests


def registration_digest(client: str) -> str | None:
    """R: the host's Covenant Flow entries and the shim files. None while either is absent."""

    entries = host_entries(client)
    files = shim_file_digests(client)
    if entries is None or len(files) != len(SHIM_FILES[client]):
        return None
    return sha256_bytes(canonical({"client": client, "entries": entries, "shim": files, "protocol": SHIM_PROTOCOL}))


# --------------------------------------------------------------------------- trust record v2


def _review_key(part: str, client: str, digest: str) -> str:
    return f"{part}:{client}:{digest}"


def is_reviewed(part: str, client: str, digest: str | None) -> bool:
    if not digest:
        return False
    document = _read_json(trust_path())
    reviews = document.get("reviews") if isinstance(document, dict) and document.get("version") == 2 else None
    return isinstance(reviews, dict) and _review_key(part, client, digest) in reviews


def record_review(part: str, client: str, digest: str, files: Any) -> None:
    document = _read_json(trust_path()) if trust_path().exists() else {"version": 2, "reviews": {}}
    if not isinstance(document, dict) or document.get("version") != 2 or not isinstance(document.get("reviews"), dict):
        raise OSError(f"cannot extend invalid trust record: {trust_path()}")
    document["reviews"][_review_key(part, client, digest)] = {
        "digest": digest, "part": part, "client": client, "files": files, "recorded_at": _now(),
    }
    _private_write(trust_path(), document)


def consumer_manifest_entry(root: Path | None, client: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    if root is None:
        return None, None
    manifest = load_manifest(root)
    if manifest is None:
        return None, None
    entry = manifest["clients"].get(client)
    return manifest, entry if isinstance(entry, dict) else None


def status(client: str, root: Path | None = None) -> dict[str, Any]:
    """Never raises: what a `process_event` preflight and `--check` need to know."""

    shim_ok = installed_shim_dir().joinpath("cf_shim.py").is_file()
    entries = host_entries(client)
    registration = registration_digest(client)
    result: dict[str, Any] = {
        "client": client,
        "host_registration": HOST_REGISTRATION[client],
        "shim_installed": shim_ok,
        "shim_version": _installed_version(),
        "registered": entries is not None,
        "registration": {"digest": registration or UNAVAILABLE, "reviewed": is_reviewed("registration", client, registration)},
        "adapter": None,
    }
    if root is not None:
        adapter: dict[str, Any] = {"manifest": False, "digest": UNAVAILABLE, "reviewed": False, "missing": [], "divergent": []}
        try:
            manifest, entry = consumer_manifest_entry(root, client)
            if manifest is not None and entry is not None and isinstance(entry.get("files"), dict):
                state = adapter_state(root, entry)
                adapter.update(manifest=True, registration=entry.get("registration"), digest=state.digest,
                               reviewed=is_reviewed("adapter", client, state.digest) and not state.missing and not state.divergent,
                               missing=state.missing, divergent=state.divergent)
            elif manifest is not None:
                adapter.update(manifest=True, registration=(entry or {}).get("registration", "unproven"))
        except ManifestError as exc:
            adapter["error"] = str(exc)
        result["adapter"] = adapter
    return result


def _installed_version() -> str:
    try:
        text = installed_shim_dir().joinpath("cf_shim.py").read_text(encoding="utf-8")
    except OSError:
        return UNAVAILABLE
    found = re.search(r'^SHIM_VERSION = "([^"]+)"', text, re.MULTILINE)
    return found.group(1) if found else UNAVAILABLE


def record(client: str, root: Path | None) -> list[dict[str, Any]]:
    """Operator act: remember the digests just reviewed, registration and (with a pinned consumer) adapter."""

    recorded: list[dict[str, Any]] = []
    registration = registration_digest(client)
    if registration is None:
        raise ValueError(f"{client}: the account registration or the shim is not installed; run `install.sh --account`")
    record_review("registration", client, registration, {"entries": host_entries(client), "shim": shim_file_digests(client)})
    recorded.append({"part": "registration", "client": client, "digest": registration})
    if root is not None:
        manifest, entry = consumer_manifest_entry(root, client)
        if manifest is not None and entry is not None and isinstance(entry.get("files"), dict):
            state = adapter_state(root, entry)
            if state.missing or state.divergent:
                raise ValueError(
                    f"{client}: the worktree differs from the pinned manifest "
                    f"(missing={state.missing[:5]}, divergent={state.divergent[:5]}); restore it with `install.sh --pin` before reviewing"
                )
            record_review("adapter", client, state.digest, {"files": entry["files"]})
            recorded.append({"part": "adapter", "client": client, "digest": state.digest, "files": len(entry["files"])})
    return recorded


# --------------------------------------------------------------------------- session heartbeat


def session_of(client: str, payload: Mapping[str, Any]) -> str | None:
    for key in ("session_id", "conversation_id", "sessionID"):
        value = _text(payload.get(key))
        if value and SESSION_ID.fullmatch(value):
            return value
    return None


def heartbeat_path(client: str, session: str) -> Path:
    return sessions_dir() / client / f"{session}.json"


def read_heartbeat(client: str, session: str | None) -> dict[str, Any] | None:
    if not session or not SESSION_ID.fullmatch(session):
        return None
    value = _read_json(heartbeat_path(client, session))
    return value if isinstance(value, dict) and value.get("version") == 2 else None


_VERSION_FROM_ENV = re.compile(r"claude-code[_-](\d+(?:[.-]\d+){1,3})", re.IGNORECASE)


def host_version(client: str, payload: Mapping[str, Any], environ: Mapping[str, str]) -> str:
    if client == "cursor":
        return _text(payload.get("cursor_version")) or UNAVAILABLE
    if client == "claude":
        found = _VERSION_FROM_ENV.search(environ.get("AI_AGENT", ""))
        return found.group(1).replace("-", ".") if found else UNAVAILABLE
    return UNAVAILABLE


def write_heartbeat(client: str, payload: Mapping[str, Any], cwd: str, root: Path | None, environ: Mapping[str, str]) -> None:
    """SessionStart in any folder: a private record, never output. It anchors the registration the host loaded."""

    session = session_of(client, payload)
    if session is None:
        return
    _private_write(heartbeat_path(client, session), {
        "version": 2, "client": client, "session_id": session,
        "transcript_path": _text(payload.get("transcript_path")) or UNAVAILABLE,
        "cwd": cwd, "last_root": str(root) if root else None,
        "host_version": host_version(client, payload, environ),
        "entrypoint": environ.get("CLAUDE_CODE_ENTRYPOINT") or UNAVAILABLE if client == "claude" else UNAVAILABLE,
        "registration_digest": registration_digest(client) or UNAVAILABLE,
        "recorded_at": _now(), "updated_at": _now(),
    })


def refresh_heartbeat(client: str, payload: Mapping[str, Any], cwd: str, root: Path | None) -> bool:
    """Follow a same-session move (new transcript, new worktree). The registration digest stays the session's own."""

    session = session_of(client, payload)
    beat = read_heartbeat(client, session)
    if beat is None:
        return False
    transcript = _text(payload.get("transcript_path")) or beat.get("transcript_path")
    last_root = str(root) if root else beat.get("last_root")
    if beat.get("transcript_path") == transcript and beat.get("cwd") == cwd and beat.get("last_root") == last_root:
        return False
    beat.update(transcript_path=transcript, cwd=cwd, last_root=last_root, updated_at=_now())
    _private_write(heartbeat_path(client, session or ""), beat)
    return True


# --------------------------------------------------------------------------- discovery and decision


@dataclass
class Decision:
    action: str  # none | run | fail
    code: str = ""
    reason: str = ""
    root: Path | None = None
    entry: dict[str, Any] | None = None
    adapter_digest: str = UNAVAILABLE
    registration: str = UNAVAILABLE


def event_cwd(payload: Mapping[str, Any]) -> list[str]:
    """Hook input `cwd`, else the workspace roots, else the process cwd."""

    for key in ("cwd", "directory", "worktree"):
        value = _text(payload.get(key))
        if value:
            return [value]
    roots = payload.get("workspace_roots")
    if isinstance(roots, list):
        listed = [r.strip() for r in roots if isinstance(r, str) and r.strip()]
        if listed:
            return listed
    return [os.getcwd()]


def discover(candidates: list[str]) -> tuple[Path | None, bool]:
    """(consumer root, ambiguous). A consumer is a Git top-level that carries an overlay."""

    consumers = []
    for candidate in candidates:
        top = git_toplevel(candidate)
        if top is not None and (top / OVERLAY).is_file() and top not in consumers:
            consumers.append(top)
    if len(consumers) > 1:
        return None, True
    return (consumers[0] if consumers else None), False


def decide(client: str, payload: Mapping[str, Any], *, spawn: bool = False, environ: Mapping[str, str] | None = None) -> Decision:
    env = os.environ if environ is None else environ
    root, ambiguous = discover(event_cwd(payload))
    if ambiguous:
        return Decision("fail", "consumer_ambiguous", "the workspace roots belong to different Covenant Flow consumers")
    if root is None or pin_of(root) is None:
        return Decision("none")
    try:
        manifest = load_manifest(root)
    except ManifestError as exc:
        return Decision("fail", "manifest_invalid", str(exc), root=root)
    if manifest is None:
        return Decision("none", root=root)  # pin before account registration: the project registration runs
    entry = manifest["clients"].get(client)
    if not isinstance(entry, dict) or entry.get("registration") != "account":
        return Decision("none", root=root)
    protocol = manifest.get("shim_protocol")
    if protocol not in SUPPORTED_PROTOCOLS:
        return Decision("fail", "shim_incompatible", f"the pin declares shim protocol {protocol!r}; this shim supports {list(SUPPORTED_PROTOCOLS)}", root=root)
    try:
        state = adapter_state(root, entry)
    except ManifestError as exc:
        return Decision("fail", "manifest_invalid", str(exc), root=root)
    if state.missing:
        return Decision("fail", "adapter_missing", "adapter file(s) absent: " + ", ".join(state.missing[:5]), root=root)
    if state.divergent:
        return Decision("fail", "adapter_divergent", "adapter file(s) differ from the pinned manifest: " + ", ".join(state.divergent[:5]), root=root, adapter_digest=state.digest)
    current = registration_digest(client)
    if not is_reviewed("registration", client, current):
        return Decision("fail", "hooks_unreviewed", f"the {client} account registration or the shim was not reviewed by the operator", root=root, adapter_digest=state.digest)
    if not is_reviewed("adapter", client, state.digest):
        return Decision("fail", "hooks_unreviewed", f"the pinned {client} adapter ({state.digest[:12]}) was not reviewed by the operator", root=root, adapter_digest=state.digest, registration=current or UNAVAILABLE)
    if spawn:
        beat = read_heartbeat(client, session_of(client, payload))
        if beat is not None and beat.get("registration_digest") not in (None, UNAVAILABLE, current):
            return Decision("fail", "hooks_changed", "the registration changed after this session started", root=root)
    return Decision("run", root=root, entry=entry, adapter_digest=state.digest, registration=current or UNAVAILABLE)


def failure_text(client: str, decision: Decision) -> str:
    recovery = RECOVERY.get(decision.code, "").replace("<client>", client)
    return f"process-fsm-guard deny reason={decision.code}. {decision.reason}. Recovery: {recovery}."


# --------------------------------------------------------------------------- native outputs


def _claude_pretool_deny(message: str) -> dict[str, Any]:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": message}}


def deny_output(client: str, event: str, message: str) -> dict[str, Any] | None:
    """The host-native deny for a gating event; None for events that never gate."""

    if event not in GATING_EVENTS.get(client, set()):
        return None
    if client == "cursor":
        return {"permission": "deny", "decision": "deny", "user_message": message, "agent_message": message, "reason": message}
    return _claude_pretool_deny(message)


def notice_output(client: str, event: str, message: str) -> dict[str, Any] | None:
    """Session-start page text that carries the visible reason; None for other events."""

    if event != SESSION_EVENTS.get(client):
        return None
    text = f"Covenant Flow: {message}\n"
    if client == "cursor":
        return {"additional_context": text}
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}


def _emit(value: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")


def _foreign_cursor_call(client: str, environ: Mapping[str, str]) -> bool:
    """Cursor also loads `~/.claude/settings.json`: the claude entry must stay quiet there."""

    return client == "claude" and any(environ.get(name) for name in ("CURSOR_VERSION", "CURSOR_PROJECT_DIR"))


def run_adapter(root: Path, entry: Mapping[str, Any], event: str, raw: bytes, decision: Decision, environ: Mapping[str, str]) -> subprocess.CompletedProcess[bytes] | None:
    argv = (entry.get("entrypoints") or {}).get(event)
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        return None
    env = dict(environ)
    env.update(
        CF_SHIM_ACTIVE="1", CF_SHIM_VERSION=SHIM_VERSION, CF_SHIM_ROOT=str(root),
        CF_SHIM_ADAPTER_DIGEST=decision.adapter_digest, CF_SHIM_REGISTRATION_DIGEST=decision.registration,
    )
    return subprocess.run(argv, input=raw, cwd=root, env=env, check=False, capture_output=True, timeout=HOOK_TIMEOUT)


def _page_from_session_start(client: str, completed: subprocess.CompletedProcess[bytes] | None) -> str:
    if completed is None or completed.returncode != 0:
        return ""
    try:
        document = json.loads(completed.stdout.decode("utf-8").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return ""
    if client == "cursor":
        return str(document.get("additional_context") or "")
    inner = document.get("hookSpecificOutput") if isinstance(document, dict) else None
    return str(inner.get("additionalContext") or "") if isinstance(inner, dict) else ""


def is_spawn(client: str, event: str, payload: Mapping[str, Any]) -> bool:
    if client in ("claude", "codex"):
        return event == "pre-tool-use" and _text(payload.get("tool_name")) == "Agent"
    return client == "cursor" and event == "model-selection"


def handle_hook(client: str, event: str, raw: bytes, environ: Mapping[str, str] | None = None) -> int:
    env = dict(os.environ if environ is None else environ)
    if _foreign_cursor_call(client, env):
        return 0
    try:
        payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except (ValueError, UnicodeDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    try:
        return _handle(client, event, raw, payload, env)
    except Exception as exc:  # the shim must never turn its own bug into silence on a gate
        decision = Decision("fail", "shim_error", f"{type(exc).__name__}: {exc}")
        message = failure_text(client, decision)
        out = deny_output(client, event, message) or notice_output(client, event, message)
        if out is not None:
            _emit(out)
        else:
            print(message, file=sys.stderr)
        return 0


def _handle(client: str, event: str, raw: bytes, payload: Mapping[str, Any], env: Mapping[str, str]) -> int:
    candidates = event_cwd(payload)
    decision = decide(client, payload, spawn=is_spawn(client, event, payload), environ=env)
    root = decision.root
    if event == SESSION_EVENTS.get(client):
        # The heartbeat anchors the registration the host loaded; it is written in any folder and says nothing.
        try:
            write_heartbeat(client, payload, candidates[0], root, env)
        except OSError:
            pass
    else:
        try:
            refresh_heartbeat(client, payload, candidates[0], root)
        except OSError:
            pass
    if decision.action == "none":
        return 0
    if decision.action == "fail":
        message = failure_text(client, decision)
        out = deny_output(client, event, message) or notice_output(client, event, message)
        if out is not None:
            _emit(out)
        else:
            print(message, file=sys.stderr)
        return 0
    assert root is not None and decision.entry is not None
    entry_event = event
    if client == "claude" and event == "post-tool-use" and _text(payload.get("tool_name")) == "EnterWorktree":
        return _page_after_worktree_switch(client, root, decision, payload, env)
    try:
        completed = run_adapter(root, decision.entry, entry_event, raw, decision, env)
    except (OSError, subprocess.SubprocessError) as exc:
        failed = Decision("fail", "shim_error", f"adapter did not run: {type(exc).__name__}: {exc}", root=root)
        message = failure_text(client, failed)
        out = deny_output(client, event, message) or notice_output(client, event, message)
        if out is not None:
            _emit(out)
        else:
            print(message, file=sys.stderr)
        return 0
    if completed is None:
        failed = Decision("fail", "adapter_missing", f"the manifest declares no `{event}` entry point for {client}", root=root)
        message = failure_text(client, failed)
        out = deny_output(client, event, message) or notice_output(client, event, message)
        if out is not None:
            _emit(out)
        return 0
    sys.stdout.buffer.write(completed.stdout)
    sys.stdout.flush()
    if completed.stderr:
        sys.stderr.buffer.write(completed.stderr)
    return completed.returncode


def _page_after_worktree_switch(client: str, root: Path, decision: Decision, payload: Mapping[str, Any], env: Mapping[str, str]) -> int:
    """`EnterWorktree` does not reload settings and fires no SessionStart: reinject the page of the card just entered."""

    synthetic = dict(payload, hook_event_name="SessionStart", source="enter-worktree")
    assert decision.entry is not None
    try:
        completed = run_adapter(root, decision.entry, "session-start", json.dumps(synthetic).encode("utf-8"), decision, env)
    except (OSError, subprocess.SubprocessError):
        return 0
    page = _page_from_session_start(client, completed)
    if page:
        _emit({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": page}})
    return 0


# --------------------------------------------------------------------------- OpenCode plugin support


def opencode_decide(directory: str, tool: str | None = None) -> dict[str, Any]:
    """In-process plugin bridge: the plugin asks, then imports the pinned modules itself."""

    payload = {"cwd": directory}
    decision = decide("opencode", payload, spawn=(tool == "task"))
    out: dict[str, Any] = {"action": decision.action, "code": decision.code, "reason": decision.reason}
    if decision.action == "fail":
        out["message"] = failure_text("opencode", decision)
    if decision.action == "run" and decision.root is not None and decision.entry is not None:
        out["root"] = str(decision.root)
        out["modules"] = [str(decision.root / m) for m in decision.entry.get("modules", [])]
    return out


# --------------------------------------------------------------------------- CLI


def _cli_trust(argv: list[str]) -> int:
    clients: list[str] = []
    cwd = Path.cwd()
    mode = "status"
    it = iter(argv)
    for arg in it:
        if arg == "--record":
            mode = "record"
        elif arg == "--status":
            mode = "status"
        elif arg == "--client":
            clients.append(next(it, ""))
        elif arg == "--cwd":
            cwd = Path(next(it, "."))
        else:
            print("usage: cf_shim.py trust [--status|--record] [--client claude|cursor|codex|opencode]... [--cwd DIR]", file=sys.stderr)
            return 2
    if any(c not in CLIENTS for c in clients):
        print(f"unknown client; expected one of {', '.join(CLIENTS)}", file=sys.stderr)
        return 2
    clients = clients or [c for c in CLIENTS if host_entries(c) is not None]
    if mode == "record" and not clients:
        print("cf_shim trust: no registered host; run install.sh --account", file=sys.stderr)
        return 2
    top = git_toplevel(cwd)
    root = top if top is not None and (top / OVERLAY).is_file() else None
    if mode == "record":
        try:
            recorded = [item for client in clients for item in record(client, root)]
        except (ValueError, OSError) as exc:
            print(f"cf_shim trust: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({"recorded": recorded, "path": str(trust_path())}, sort_keys=True))
        return 0
    results = [status(client, root) for client in clients]
    print(json.dumps(results if len(results) != 1 else results[0], sort_keys=True))
    ok = all(
        r["shim_installed"] and r["registered"] and r["registration"]["reviewed"]
        and (r["adapter"] is None or not r["adapter"]["manifest"] or r["adapter"]["reviewed"])
        for r in results
    )
    return 0 if ok and results else 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        print("usage: cf_shim.py <client> <event> | trust ... | status ... | opencode decide ...", file=sys.stderr)
        return 2
    if args[0] == "trust":
        return _cli_trust(args[1:])
    if args[0] == "status":
        client = args[args.index("--client") + 1] if "--client" in args else ""
        cwd = Path(args[args.index("--cwd") + 1]) if "--cwd" in args else Path.cwd()
        if client not in CLIENTS:
            print(f"--client must be one of {', '.join(CLIENTS)}", file=sys.stderr)
            return 2
        top = git_toplevel(cwd)
        print(json.dumps(status(client, top if top is not None and (top / OVERLAY).is_file() else None), sort_keys=True))
        return 0
    if args[0] == "opencode" and len(args) >= 2 and args[1] == "decide":
        directory = args[args.index("--cwd") + 1] if "--cwd" in args else os.getcwd()
        tool = args[args.index("--tool") + 1] if "--tool" in args else None
        try:
            print(json.dumps(opencode_decide(directory, tool), sort_keys=True))
        except Exception as exc:
            print(json.dumps({"action": "fail", "code": "shim_error", "reason": str(exc),
                              "message": f"process-fsm-guard deny reason=shim_error. {exc}. Recovery: {RECOVERY['shim_error']}."}))
        return 0
    if len(args) != 2 or args[0] not in CLIENTS:
        print("usage: cf_shim.py <claude|cursor|codex|opencode> <event>", file=sys.stderr)
        return 2
    return handle_hook(args[0], args[1], sys.stdin.buffer.read())


if __name__ == "__main__":
    raise SystemExit(main())
