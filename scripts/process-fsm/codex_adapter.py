"""Codex-local hook adapter for the shared Covenant Flow paging and Guard."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from codex_models import ModelRoutingError, validate_requested_pair  # noqa: E402
from guard import (  # noqa: E402
    decide,
    extract_paths,
    github_status_provider,
    normalize,
)
from paging import page  # noqa: E402


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Codex hook payload must be a JSON object")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Codex hook JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Codex hook payload must be a JSON object")
    return parsed


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _repo_root(cwd: str | Path) -> Path:
    directory = Path(cwd).expanduser().resolve()
    result = subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    raise RuntimeError(f"cannot resolve Git root from Codex hook cwd {directory}: {result.stderr.strip()}")


def _cwd(payload: Mapping[str, Any]) -> Path:
    value = _text(payload.get("cwd")) or _text(payload.get("workspaceRoot")) or os.getcwd()
    return Path(value).expanduser().resolve()


def _emit(value: Mapping[str, Any]) -> None:
    json.dump(value, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")


def _pretool_deny(reason: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _event_tool(payload: Mapping[str, Any]) -> str:
    return _text(payload.get("tool_name")) or _text(payload.get("toolName")) or _text(payload.get("tool")) or ""


def _tool_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("tool_input", "toolInput", "args"):
        if key in payload:
            return _dict(payload[key])
    return {}


def _routing_effort(tool_input: Mapping[str, Any]) -> Any:
    for key in ("reasoning_effort", "model_reasoning_effort", "effort"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value
    reasoning = tool_input.get("reasoning")
    if isinstance(reasoning, Mapping):
        return reasoning.get("effort")
    return None


def pre_tool_use(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return a documented Codex deny decision, or None to continue normally."""

    try:
        event = _dict(payload)
        tool = _event_tool(event)
        aliases = {
            "exec_command": "Bash",
            "exec-command": "Bash",
            "Edit": "apply_patch",
            "Write": "apply_patch",
            "spawn_agent": "Agent",
        }
        canonical_tool = aliases.get(tool, tool)
        if canonical_tool not in {"Bash", "apply_patch", "Agent"}:
            reason = "missing tool name" if not tool else f"unknown tool {tool!r}"
            return _pretool_deny(f"process-fsm-guard deny reason=unknown_tool. {reason}")

        data = _tool_input(event)
        if not data:
            return _pretool_deny(
                "process-fsm-guard deny reason=invalid_tool_input. Codex tool_input must be a non-empty object."
            )
        cwd = _cwd(event)
        root = _repo_root(cwd)
        if canonical_tool == "Agent":
            validate_requested_pair(
                root,
                model=data.get("model"),
                effort=_routing_effort(data),
            )
            return None

        if canonical_tool == "Bash" and not isinstance(data.get("command"), str):
            return _pretool_deny(
                "process-fsm-guard deny reason=invalid_tool_input. Bash command must be a string."
            )
        request = dict(event)
        request["tool_name"] = canonical_tool
        request["cwd"] = str(cwd)
        request["tool_input"] = data
        if canonical_tool == "apply_patch" and not extract_paths(normalize(request)):
            return _pretool_deny(
                "process-fsm-guard deny reason=empty_path. Codex apply_patch must include an extractable file path."
            )

        decision = decide(request, status_provider=github_status_provider)
        if decision.get("permission") == "deny":
            reason = _text(decision.get("reason")) or "process-fsm-guard deny."
            return _pretool_deny(reason)
        return None
    except Exception as exc:
        # A failed policy lookup must never become an implicit permission.
        return _pretool_deny(f"process-fsm-guard deny reason=evaluation_error. {exc}")


def session_start(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Inject the shared `paging.page()` content; Status failures stay unread."""

    cwd = _cwd(payload)
    try:
        result = page(cwd=cwd, path=cwd)
        context = str(result.get("additional_context") or "")
        if not context:
            raise RuntimeError("paging.page returned no additional_context")
    except Exception as exc:
        context = (
            "process-fsm page\n"
            "Status unread. Write produto deny. Não invente Status a partir do chat.\n"
            f"Paging error: {exc}\n"
        )
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }


def _file_paths(payload: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("file_path", "path", "filePath", "file"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in paths:
            paths.append(value.strip())
    normalized = normalize(payload)
    for value in extract_paths(normalized):
        if value not in paths:
            paths.append(value)
    data = _tool_input(payload)
    for key in ("path", "file_path", "filePath", "file"):
        value = data.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in paths:
            paths.append(value.strip())
    return paths


def _run_impeccable(payload: Mapping[str, Any], event_name: str) -> None:
    cwd = _cwd(payload)
    try:
        root = _repo_root(cwd)
    except Exception:
        return
    hook = root / ".agents" / "skills" / "impeccable" / "scripts" / "hook.mjs"
    if not hook.is_file():
        return

    environment = os.environ.copy()
    environment["IMPECCABLE_HOOK_HARNESS"] = "codex"
    environment["CURSOR_PROJECT_DIR"] = str(root)
    tool = _event_tool(payload)
    base = dict(payload)
    base["cwd"] = str(cwd)
    base["hook_event_name"] = event_name
    if event_name == "PostToolUse":
        data = _tool_input(payload)
        base["tool_input"] = data
        base["tool_name"] = tool
        paths = _file_paths(payload)
        events = []
        if paths:
            for path in paths:
                item = dict(base)
                item["file_path"] = path
                events.append(item)
        else:
            events.append(base)
    else:
        events = [base]

    for event in events:
        try:
            completed = subprocess.run(
                ["node", str(hook)],
                input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
                cwd=root,
                env=environment,
                check=False,
                capture_output=True,
                timeout=30,
            )
        except Exception:
            continue
        if completed.stdout:
            sys.stdout.buffer.write(completed.stdout)
            sys.stdout.flush()


def dispatch(event_name: str, payload: Mapping[str, Any]) -> int:
    if event_name == "session-start":
        _emit(session_start(payload))
        return 0
    if event_name == "pre-tool-use":
        decision = pre_tool_use(payload)
        if decision is not None:
            _emit(decision)
        return 0
    if event_name == "post-tool-use":
        _run_impeccable(payload, "PostToolUse")
        return 0
    if event_name == "stop":
        _run_impeccable(payload, "Stop")
        return 0
    print(f"codex adapter: unknown hook event {event_name!r}", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(
            "usage: codex_adapter.py session-start|pre-tool-use|post-tool-use|stop",
            file=sys.stderr,
        )
        return 2
    try:
        raw = sys.stdin.read()
        payload = _dict(raw)
        return dispatch(args[0], payload)
    except Exception as exc:
        if args[0] == "pre-tool-use":
            _emit(_pretool_deny(f"process-fsm-guard deny reason=evaluation_error. {exc}"))
            return 0
        print(f"codex adapter: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
