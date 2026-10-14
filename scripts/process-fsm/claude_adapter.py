"""Claude Code hook adapter for the shared Covenant Flow paging, Guard and model selection.

Every hook decision is fail-closed: an exception, a timeout-shaped failure or
malformed input on `PreToolUse` becomes a JSON `deny`, never the non-blocking
exit code 1 the host treats as "continue". Hooks protect only after the
operator's explicit trust review (`claude_adapter.py trust --record`).
"""

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

import claude_trust  # noqa: E402
from guard import (  # noqa: E402
    WRITE_TOOLS,
    decide,
    extract_paths,
    github_status_provider,
    glob_kind,
    normalize,
    repo_relative,
)
from model_selection import validate_spawn  # noqa: E402
from overlay import load_overlay  # noqa: E402
from paging import page  # noqa: E402

GUARDED_TOOLS = frozenset({"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit"})
REVIEWERS = frozenset({"diff-reviewer", "code-reviewer"})
# SubagentHandback is the host's return channel, not a way to read or write the repo.
REVIEWER_TOOLS = frozenset({"Read", "Grep", "Glob", "SubagentHandback"})
OVERRIDE_VARIABLES = ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL")
trust_status = claude_trust.status


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Claude Code hook payload must be a JSON object")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid Claude Code hook JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Claude Code hook payload must be a JSON object")
    return parsed


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _repo_root(cwd: str | Path) -> Path:
    directory = Path(cwd).expanduser().resolve()
    result = subprocess.run(
        ["git", "-C", str(directory), "rev-parse", "--show-toplevel"],
        check=False, capture_output=True, text=True, timeout=5,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    raise RuntimeError(f"cannot resolve Git root from Claude Code hook cwd {directory}: {result.stderr.strip()}")


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


def _tool_input(payload: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("tool_input", "toolInput"):
        if key in payload:
            return _dict(payload[key])
    return {}


def _unreviewed_reason(status: Mapping[str, Any]) -> str:
    return (
        "process-fsm-guard deny reason=hooks_unreviewed. hooks não revisados: "
        + str(status.get("reason") or "digest not recorded")
        + " Product writes and spawns stay denied until the operator reviews the current hook definition."
    )


def _touches_product(request: Mapping[str, Any]) -> bool:
    """True when the call can write a product path; unknown overlay counts as product."""

    canonical = normalize(request)
    cwd = Path(str(canonical["cwd"]))
    try:
        overlay = load_overlay(cwd, require_filled=True)
    except Exception:
        return True
    return any(glob_kind(repo_relative(cwd, item, overlay), overlay) == "product" for item in extract_paths(canonical, overlay))


def _check_spawn(event: Mapping[str, Any], data: Mapping[str, Any], root: Path) -> dict[str, Any] | None:
    for name in OVERRIDE_VARIABLES:
        if str(os.environ.get(name, "")).strip():
            return _pretool_deny(
                f"process-fsm-guard deny reason=env_override. {name} is set and would override the per-spawn model/effort; unset it, no fallback."
            )
    if not _text(data.get("model")):
        return _pretool_deny("process-fsm-guard deny reason=model_missing. Agent spawn requires the explicit captured `model`; no inheritance from the parent.")
    if not _text(data.get("effort")):
        # The requested effort is read only from tool_input.effort: never from the
        # session-level effort field of the hook input, CLAUDE_EFFORT or frontmatter.
        return _pretool_deny(
            "process-fsm-guard deny reason=unsupported_schema. Agent tool_input carries no `effort`; "
            "this host version does not expose the per-spawn effort, so the spawn is refused "
            "(the session effort and `model` alone never validate a spawn)."
        )
    validate_spawn("claude", data)
    from model_selection import request_role

    role = request_role(data)
    if role in REVIEWERS and data.get("subagent_type") != role:
        return _pretool_deny(
            f"process-fsm-guard deny reason=reviewer_agent_type. {role} must be spawned with subagent_type={role} (read-only tools)."
        )
    status = trust_status()
    if not status.get("reviewed"):
        return _pretool_deny(_unreviewed_reason(status))
    from claude_evidence import check_prepared_spawn

    check_prepared_spawn(data, root, session=_text(event.get("session_id")))
    return None


def _refresh_heartbeat(event: Mapping[str, Any]) -> None:
    """Follow a same-session worktree switch: the host moves the transcript and the cwd changes.

    Only rewrites an existing heartbeat (no SessionStart, no heartbeat) and only follows transcript
    and cwd. The digest, reviewed flag, host version and entrypoint stay the ones recorded at
    SessionStart: the heartbeat is the sole anchor of the hooks the host loaded, so it is never
    re-anchored to the current trust status. Best effort: a failure never changes the decision.
    """

    if claude_trust.shim_verified() is not None:
        return  # the account shim refreshes its own heartbeat on every event
    try:
        session_id = _text(event.get("session_id"))
        transcript = _text(event.get("transcript_path"))
        if not session_id or not transcript:
            return
        beat = claude_trust.read_heartbeat(session_id)
        if beat is None:
            return
        cwd = str(_cwd(event))
        if beat.get("transcript_path") == transcript and beat.get("cwd") == cwd:
            return
        claude_trust.write_heartbeat(
            session_id=session_id,
            transcript_path=transcript,
            cwd=cwd,
            digest=str(beat.get("hooks_digest")),
            reviewed=bool(beat.get("reviewed")),
            version=beat.get("host_version"),
            entrypoint=beat.get("entrypoint"),
        )
    except Exception:
        return


def pre_tool_use(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return a documented Claude Code deny decision, or None to continue normally."""

    try:
        event = _dict(payload)
        _refresh_heartbeat(event)
        tool = _text(event.get("tool_name")) or _text(event.get("toolName")) or ""
        agent_id = _text(event.get("agent_id"))
        agent_type = _text(event.get("agent_type")) or ""
        if agent_type in REVIEWERS and tool in REVIEWER_TOOLS:
            return None
        if tool not in GUARDED_TOOLS and tool != "Agent":
            reason = "missing tool name" if not tool else f"unknown tool {tool!r}"
            return _pretool_deny(f"process-fsm-guard deny reason=unknown_tool. {reason}")
        if agent_id and tool == "Agent":
            return _pretool_deny("process-fsm-guard deny reason=child_spawn. A subagent cannot spawn subagents.")
        if agent_type in REVIEWERS and tool not in REVIEWER_TOOLS:
            return _pretool_deny(f"process-fsm-guard deny reason=reviewer_tools. {agent_type} may use only Read, Grep and Glob.")
        data = _tool_input(event)
        if not data:
            return _pretool_deny("process-fsm-guard deny reason=invalid_tool_input. Claude Code tool_input must be a non-empty object.")
        cwd = _cwd(event)
        root = _repo_root(cwd)
        if tool == "Agent":
            return _check_spawn(event, data, root)
        if tool == "Bash" and not isinstance(data.get("command"), str):
            return _pretool_deny("process-fsm-guard deny reason=invalid_tool_input. Bash command must be a string.")
        request = dict(event)
        request["tool_name"] = tool
        request["cwd"] = str(cwd)
        request["tool_input"] = data
        if tool in WRITE_TOOLS and not extract_paths(normalize(request)):
            return _pretool_deny("process-fsm-guard deny reason=empty_path. Claude Code write tools must include an extractable file path.")
        decision = decide(request, status_provider=github_status_provider)
        if decision.get("permission") == "deny":
            return _pretool_deny(_text(decision.get("reason")) or "process-fsm-guard deny.")
        status = trust_status()
        if not status.get("reviewed") and _touches_product(request):
            return _pretool_deny(_unreviewed_reason(status))
        if agent_id and extract_paths(normalize(request)):
            from claude_evidence import verify_child_before_write

            verify_child_before_write(event, root)
        return None
    except Exception as exc:
        # A failed policy lookup must never become an implicit permission.
        return _pretool_deny(f"process-fsm-guard deny reason=evaluation_error. {getattr(exc, 'code', type(exc).__name__)}: {exc}")


def session_start(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Inject the shared `paging.page()`, record the heartbeat; Status failures stay unread."""

    cwd = _cwd(payload)
    notice = ""
    try:
        status = trust_status()
        session_id = _text(payload.get("session_id")) or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
        if session_id and claude_trust.shim_verified() is None:  # under the shim the heartbeat is the shim's
            claude_trust.write_heartbeat(
                session_id=session_id,
                transcript_path=_text(payload.get("transcript_path")) or "",
                cwd=str(cwd),
                digest=str(status.get("digest")),
                reviewed=bool(status.get("reviewed")),
            )
        if not status.get("reviewed"):
            notice = "hooks não revisados: product writes and Agent spawns are denied until `claude_adapter.py trust --record` (operator review).\n"
    except Exception as exc:
        notice = f"hooks não revisados: heartbeat/trust unavailable ({exc}). Product writes and Agent spawns stay denied.\n"
    try:
        result = page(cwd=cwd, path=cwd, client="claude")
        context = str(result.get("additional_context") or "")
        if not context:
            raise RuntimeError("paging.page returned no additional_context")
    except Exception as exc:
        context = (
            "process-fsm page\n"
            "Status unread. Write produto deny. Não invente Status a partir do chat.\n"
            f"Paging error: {exc}\n"
        )
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": notice + context}}


def _post_agent(event: Mapping[str, Any]) -> dict[str, Any] | None:
    """Compare the host's resolvedModel with the captured id; annotate, never trust silently."""

    from claude_evidence import note_resolved_model

    try:
        root = _repo_root(_cwd(event))
        outcome = note_resolved_model(_tool_input(event), event.get("tool_response"), root)
    except Exception as exc:
        text = f"Covenant Flow: the spawn could not be tied to its birth receipt ({getattr(exc, 'code', type(exc).__name__)}: {exc}). Do not accept this child; a new birth is required."
    else:
        if outcome["ok"]:
            return None
        text = (
            f"Covenant Flow model_mismatch: the host resolved {outcome['resolved']} but the capture selected {outcome['expected']}. "
            "The child is invalid; do not accept its result and start a new birth. Nothing was substituted silently."
        )
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}}


def _file_paths(payload: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []
    for key in ("file_path", "path", "filePath", "file", "notebook_path"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip() and value.strip() not in paths:
            paths.append(value.strip())
    for value in extract_paths(normalize(payload)):
        if value not in paths:
            paths.append(value)
    data = _tool_input(payload)
    for key in ("path", "file_path", "filePath", "file", "notebook_path"):
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
    environment["IMPECCABLE_HOOK_HARNESS"] = "claude"
    environment["CURSOR_PROJECT_DIR"] = str(root)
    base = dict(payload)
    base["cwd"] = str(cwd)
    base["hook_event_name"] = event_name
    events = [base]
    if event_name == "PostToolUse":
        base["tool_input"] = _tool_input(payload)
        events = [dict(base, file_path=path) for path in _file_paths(payload)] or [base]
    for event in events:
        try:
            completed = subprocess.run(
                ["node", str(hook)],
                input=json.dumps(event, ensure_ascii=False).encode("utf-8"),
                cwd=root, env=environment, check=False, capture_output=True, timeout=30,
            )
        except Exception:
            continue
        if completed.stdout:
            sys.stdout.buffer.write(completed.stdout)
            sys.stdout.flush()


def _subagent_stop(event: Mapping[str, Any]) -> None:
    """Evidence only: never `decision: block` (that would keep the child running)."""

    try:
        from claude_evidence import evidence_dir, mark

        root = _repo_root(_cwd(event))
        description = None
        meta_hint = _text(event.get("agent_transcript_path"))
        if meta_hint:
            meta = Path(meta_hint).with_suffix(".meta.json")
            description = json.loads(meta.read_text()).get("description")
        if not description:
            return
        out = evidence_dir(root)
        for candidate in out.glob("*.birth.json"):
            birth = json.loads(candidate.read_text())
            if birth.get("task_name") == description and birth.get("parent_session") == event.get("session_id"):
                mark(out, birth["attempt_id"], "subagent-stop", agent_id=event.get("agent_id"), agent_type=event.get("agent_type"),
                     agent_transcript_path=meta_hint, last_message_present=bool(_text(event.get("last_assistant_message"))))
    except Exception:
        return


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
        if _text(payload.get("tool_name")) == "Agent":
            note = _post_agent(payload)
            if note is not None:
                _emit(note)
        else:
            _run_impeccable(payload, "PostToolUse")
        return 0
    if event_name == "subagent-stop":
        _subagent_stop(payload)
        return 0
    if event_name == "stop":
        _run_impeccable(payload, "Stop")
        return 0
    print(f"claude adapter: unknown hook event {event_name!r}", file=sys.stderr)
    return 2


def trust_command(argv: list[str]) -> int:
    if argv == ["--record"]:
        if claude_trust.account_pin():
            return claude_trust.delegate_record()  # the account shim owns the record (registration + adapter)
        print(json.dumps(claude_trust.record(), sort_keys=True))
        return 0
    if argv in ([], ["--status"]):
        status = trust_status()
        print(json.dumps({k: v for k, v in status.items()}, sort_keys=True))
        return 0 if status.get("reviewed") else 1
    print("usage: claude_adapter.py trust [--record|--status]", file=sys.stderr)
    return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "trust":
        try:
            return trust_command(args[1:])
        except Exception as exc:
            print(f"claude adapter trust: {exc}", file=sys.stderr)
            return 2
    if len(args) != 1:
        print("usage: claude_adapter.py session-start|pre-tool-use|post-tool-use|subagent-stop|stop|trust", file=sys.stderr)
        return 2
    try:
        payload = _dict(sys.stdin.read())
        return dispatch(args[0], payload)
    except Exception as exc:
        if args[0] == "pre-tool-use":
            _emit(_pretool_deny(f"process-fsm-guard deny reason=evaluation_error. {exc}"))
            return 0
        print(f"claude adapter: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
