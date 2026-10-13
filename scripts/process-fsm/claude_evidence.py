"""Claude Code transcript-v1 evidence: native birth, every turn and returned payload.

The local JSONL transcripts (parent session and `subagents/agent-<id>.jsonl` +
`.meta.json`) are the only observation source. They are an internal host
format, not a public contract: the driver is qualified per host version and any
other version or schema is `unverified`/`unsupported_schema`, never inferred.
Local digests detect corruption, not a server attestation. No prompts or full
transcripts are persisted, and no manually supplied observation is accepted.
Recovery is always a new birth; there is never a retroactive receipt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import claude_trust
from codex_evidence import (  # the sealed-envelope helpers are client neutral
    EvidenceError,
    _verify_snapshot,
    _verify_snapshots,
    check_seal,
    check_writable_destination,
    destination,
    digest,
    private_write,
    sealed,
)
from model_selection import SelectionError, claude_host_checks, load_capture, policy, request_role, validate_capture

SCHEMA = "claude-transcript-evidence-v1"
DRIVER = "claude-transcript-v1"
HOST = "Claude Code"
# Versions whose transcript schema was checked against a real session. Anything
# else is refused; add a version only after a real rehearsal (tasks 8.2).
QUALIFIED_VERSIONS = ("2.1.296",)
QUALIFIED_ENTRYPOINTS = ("cli",)
DEFAULT_DEST = Path(".cursor/tmp/claude-evidence")
MAX_WAIT = 10.0
UNAVAILABLE = "unavailable"
REVIEWERS = frozenset({"diff-reviewer", "code-reviewer"})
READ_ONLY_TOOLS = frozenset({"Read", "Grep", "Glob"})
RETURN_CHANNEL_TOOLS = frozenset({"SubagentHandback"})
SPAWN_TOOLS = frozenset({"Agent", "Task"})
AGENT_ID = re.compile(r"[A-Za-z0-9]{8,64}\Z")
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{8,128}\Z")
RETRYABLE = {"source_unavailable", "source_truncated", "spawn_return_unavailable", "terminal_unavailable", "payload_unavailable"}


class Runtime:
    """Read-only access to the local Claude Code transcripts."""

    def __init__(self, home: str | Path | None = None):
        self.home = Path(home or Path.home() / ".claude").resolve()

    def parent_path(self, session: str, hint: str | None = None) -> Path:
        if not SESSION_ID.fullmatch(session or ""):
            raise EvidenceError("session_unavailable", f"invalid session id {session!r}")
        projects = self.home / "projects"
        found = {p.resolve() for p in projects.glob(f"*/{session}.jsonl")}
        if hint and hint != UNAVAILABLE:
            found.add(Path(hint).resolve())
        found = {p for p in found if p.name == f"{session}.jsonl" and projects in p.parents}
        if not found:
            raise EvidenceError("source_unavailable", f"no transcript for session {session}")
        if len(found) != 1:
            raise EvidenceError("source_conflict", f"several transcripts for session {session}")
        return found.pop()

    def read(self, path: Path) -> list[tuple[int, dict[str, Any], str]]:
        path = Path(path).resolve()
        if self.home / "projects" not in path.parents:
            raise EvidenceError("source_outside_runtime", str(path))
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise EvidenceError("source_unavailable", str(exc)) from exc
        if not raw.endswith(b"\n"):
            raise EvidenceError("source_truncated", str(path))
        rows = []
        for ordinal, line in enumerate(raw.splitlines()):
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("record is not an object")
            except (ValueError, TypeError) as exc:
                raise EvidenceError("source_malformed", f"{path}:{ordinal}") from exc
            rows.append((ordinal, row, digest(line)))
        return rows

    def session(self, session: str, hint: str | None = None):
        path = self.parent_path(session, hint)
        rows = self.read(path)
        if not rows:
            raise EvidenceError("unsupported_schema", "empty transcript")
        meta = _identity(rows, session)
        return path, rows, meta

    def child_paths(self, parent: Path, session: str, agent_id: str) -> tuple[Path, Path]:
        if not AGENT_ID.fullmatch(agent_id or ""):
            raise EvidenceError("spawn_return_malformed", f"invalid agent id {agent_id!r}")
        base = Path(parent).with_suffix("") / "subagents"
        return base / f"agent-{agent_id}.jsonl", base / f"agent-{agent_id}.meta.json"


def _identity(rows, session: str) -> dict[str, Any]:
    versions, entrypoints, cwd = set(), set(), None
    for _i, row, _s in rows:
        if "sessionId" in row and row["sessionId"] != session:
            raise EvidenceError("identity_mismatch", f"record of session {row['sessionId']!r}", recovery="new checked birth required")
        if isinstance(row.get("version"), str):
            versions.add(row["version"])
        if isinstance(row.get("entrypoint"), str):
            entrypoints.add(row["entrypoint"])
        if isinstance(row.get("cwd"), str) and row.get("type") in {"assistant", "user"}:
            cwd = row["cwd"]
    if not versions or not entrypoints or cwd is None:
        raise EvidenceError("unsupported_schema", "version/entrypoint/cwd missing from transcript records")
    if len(versions) != 1 or not versions <= set(QUALIFIED_VERSIONS):
        raise EvidenceError("unverified", f"host version(s) {sorted(versions)} not qualified; qualified: {', '.join(QUALIFIED_VERSIONS)}", recovery="qualify the driver with a real rehearsal; installed binary is not runtime proof")
    if len(entrypoints) != 1 or not entrypoints <= set(QUALIFIED_ENTRYPOINTS):
        raise EvidenceError("unverified", f"surface(s) {sorted(entrypoints)} not qualified; qualified: {', '.join(QUALIFIED_ENTRYPOINTS)}", recovery="surface fails visibly until it is rehearsed")
    return {"version": versions.pop(), "entrypoint": entrypoints.pop(), "cwd": cwd}


def _blocks(row) -> list[dict[str, Any]]:
    message = row.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [b for b in content if isinstance(b, dict)] if isinstance(content, list) else []


def _text(value) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(t for t in (_text(v.get("text") if isinstance(v, dict) else v) for v in value) if t).strip()
    return ""


def last_observation(rows, *, sidechain: bool) -> dict[str, str]:
    """Model/effort of the latest assistant record, as the host wrote it."""

    for _i, row, _s in reversed(rows):
        if row.get("type") != "assistant" or bool(row.get("isSidechain")) != sidechain:
            continue
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        model, effort = message.get("model"), row.get("effort")
        if isinstance(model, str) and model and isinstance(effort, str) and effort:
            return {"model": model, "effort": effort}
        break
    raise EvidenceError("observation_unavailable", "latest assistant record lacks model/effort")


def observe_parent(*, session: str | None = None, runtime: Runtime | None = None, environ: Mapping[str, str] | None = None) -> dict[str, str]:
    """Observed model/effort/version of the parent session (release closeout)."""

    env = os.environ if environ is None else environ
    session = session or env.get("CLAUDE_CODE_SESSION_ID") or ""
    beat = claude_trust.read_heartbeat(session)
    path, rows, meta = (runtime or Runtime()).session(session, (beat or {}).get("transcript_path"))
    return {**last_observation(rows, sidechain=False), "host_version": meta["version"], "surface": meta["entrypoint"], "source": str(path)}


def _inside(root: Path, cwd: str) -> bool:
    candidate = Path(cwd).resolve()
    return root == candidate or root in candidate.parents


def preflight(
    *,
    root,
    capture=None,
    dest=DEFAULT_DEST,
    session: str | None = None,
    runtime: Runtime | None = None,
    environ: Mapping[str, str] | None = None,
    trust: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    env = os.environ if environ is None else environ
    session = session or env.get("CLAUDE_CODE_SESSION_ID") or ""
    if not session:
        raise EvidenceError("session_unavailable", "CLAUDE_CODE_SESSION_ID missing")
    beat = claude_trust.read_heartbeat(session)
    if beat is None:
        raise EvidenceError(
            "hooks_inactive",
            "no SessionStart heartbeat: project hooks did not run in this session (disabled, untrusted by the host, or absent)",
            recovery="start a new session in the card worktree with hooks enabled; a missing hook is never protection",
        )
    status = (trust or claude_trust.status)()
    if not status.get("reviewed"):
        raise EvidenceError("hooks_unreviewed", status.get("reason") or "hook digest not recorded", recovery="operator reads the hook definition and adapter, then runs claude_adapter.py trust --record")
    if beat.get("hooks_digest") != status.get("digest"):
        raise EvidenceError("hooks_changed", "session heartbeat digest differs from the reviewed definition in use", recovery="start a new session after the reviewed hooks are in place")
    path, rows, meta = (runtime or Runtime()).session(session, beat.get("transcript_path"))
    observed = last_observation(rows, sidechain=False)
    root = Path(root).resolve()
    if not _inside(root, meta["cwd"]):
        raise EvidenceError("worktree_mismatch", f"session cwd {meta['cwd']} is outside {root}")
    try:
        claude_host_checks(policy()["clients"]["claude"], {"environ": env, "version": meta["version"]})
    except SelectionError as exc:
        raise EvidenceError("capability_unavailable", str(exc)) from exc
    if capture is not None:
        validate_capture(load_capture(capture) if isinstance(capture, (str, Path)) else capture, client="claude")
    out = destination(root, dest)
    check_writable_destination(out)
    return {
        "result": "ready", "session": session, "source": str(path), "driver": DRIVER, "host": HOST,
        "host_version": meta["version"], "surface": meta["entrypoint"], "schema": SCHEMA,
        "parent_observed": observed, "source_records": len(rows), "destination": str(out),
        "hooks_digest": status["digest"],
    }


def prepare(*, root, capture, task_name, dest=DEFAULT_DEST, review_diff_sha256=UNAVAILABLE, wave_id=UNAVAILABLE, runtime=None, session=None, environ=None, trust=None):
    cap = validate_capture(load_capture(capture), client="claude")
    pf = preflight(root=root, capture=cap, dest=dest, session=session, runtime=runtime, environ=environ, trust=trust)
    if not task_name or "/" in task_name or task_name != task_name.strip():
        raise EvidenceError("invalid_task_name", task_name)
    try:
        if request_role({"description": task_name}) != cap["role"]:
            raise SelectionError("description role differs from capture")
    except SelectionError as exc:
        raise EvidenceError("invalid_task_name", f"{task_name!r}: {exc}") from exc
    review = cap["role"] in REVIEWERS
    if review and (len(review_diff_sha256) != 64 or any(c not in "0123456789abcdef" for c in review_diff_sha256)):
        raise EvidenceError("diff_unavailable")
    out = Path(pf["destination"])
    for existing in out.glob("*.birth.json"):
        try:
            other = json.loads(existing.read_text())
        except (OSError, ValueError):
            continue
        if other.get("task_name") == task_name and other.get("parent_session") == pf["session"]:
            raise EvidenceError("task_name_not_unique", f"{task_name!r} already has a birth receipt", recovery="use a new unique description with the role needle")
    beat = claude_trust.read_heartbeat(pf["session"]) or {}
    birth = sealed({
        "schema": SCHEMA, "driver": DRIVER, "capture": cap, "capture_path": str(Path(capture).resolve()),
        "root": str(Path(root).resolve()),
        "bound_card": Path(root).resolve().name.split("-")[1] if Path(root).resolve().name.startswith("card-") else UNAVAILABLE,
        "attempt_id": cap["attempt_id"], "role": cap["role"], "band": cap["band"], "task_name": task_name,
        "parent_session": pf["session"], "parent_transcript": pf["source"], "before_record": pf["source_records"],
        "host_version": pf["host_version"], "surface": pf["surface"], "hooks_digest": pf["hooks_digest"],
        "heartbeat_recorded_at": beat.get("recorded_at", UNAVAILABLE),
        "review_diff_sha256": review_diff_sha256, "wave_id": wave_id, "qualification": False,
    })
    target = out / f"{cap['attempt_id']}.birth.json"
    private_write(target, birth)
    os.chmod(target, 0o400)
    return dict(pf, birth=str(target), arguments=cap["arguments"])


def evidence_dir(root) -> Path:
    return destination(root, DEFAULT_DEST)


def mark(out: Path, attempt_id: str, kind: str, **detail: Any) -> Path:
    """Append-only note beside the immutable receipt (model_mismatch, verified, ...)."""

    value = sealed({"schema": SCHEMA, "attempt_id": attempt_id, "mark": kind, **detail})
    target = Path(out) / f"{attempt_id}.{kind}.json"
    try:
        private_write(target, value)
    except EvidenceError:
        if not target.exists():
            raise
    return target


def marked(out: Path, attempt_id: str, kind: str) -> bool:
    return (Path(out) / f"{attempt_id}.{kind}.json").is_file()


def check_prepared_spawn(arguments: Mapping[str, Any], root, *, session: str | None = None, runtime=None, environ=None, trust=None):
    """PreToolUse(Agent): the explicit receipt must match this exact spawn."""

    env = os.environ if environ is None else environ
    session = session or env.get("CLAUDE_CODE_SESSION_ID") or ""
    prompt = arguments.get("prompt") or arguments.get("message") or ""
    match = re.search(r"^runtime_evidence_birth:\s*(\S+)\s*$", prompt, re.MULTILINE)
    if not match:
        raise EvidenceError("birth_receipt_missing", recovery="prepare a checked birth before the native spawn")
    receipt = Path(match[1]).resolve()
    try:
        birth = check_seal(json.loads(receipt.read_text()))
    except (OSError, ValueError) as exc:
        raise EvidenceError("birth_receipt_missing", str(exc)) from exc
    out = evidence_dir(root)
    if receipt.parent != out or receipt.name != f"{birth.get('attempt_id')}.birth.json":
        raise EvidenceError("unsafe_destination", f"receipt must live in {out}")
    if birth.get("schema") != SCHEMA or birth.get("driver") != DRIVER:
        raise EvidenceError("unsupported_schema")
    if birth["root"] != str(Path(root).resolve()) or birth["task_name"] != arguments.get("description") or birth["parent_session"] != session:
        raise EvidenceError("birth_mismatch")
    if any(arguments.get(k) != v for k, v in birth["capture"]["arguments"].items()):
        raise EvidenceError("requested_mismatch")
    if marked(out, birth["attempt_id"], "model_mismatch"):
        raise EvidenceError("model_mismatch", "this birth was invalidated", recovery="new checked birth required")
    return preflight(root=root, capture=birth["capture"], dest=out, session=session, runtime=runtime, environ=env, trust=trust)


def _child_files(payload: Mapping[str, Any], runtime: Runtime) -> tuple[Path, Path]:
    agent_id = str(payload.get("agent_id") or "")
    transcript = payload.get("transcript_path")
    if isinstance(transcript, str) and transcript and Path(transcript).name != "":
        path = Path(transcript)
        base = path.parent if "subagents" in path.parts else path.with_suffix("") / "subagents"
        if AGENT_ID.fullmatch(agent_id):
            return base / f"agent-{agent_id}.jsonl", base / f"agent-{agent_id}.meta.json"
    parent = runtime.parent_path(str(payload.get("session_id") or ""))
    return runtime.child_paths(parent, str(payload.get("session_id") or ""), agent_id)


def verify_child_before_write(payload: Mapping[str, Any], root, *, runtime: Runtime | None = None) -> dict[str, Any]:
    """First write of a child: its latest model/effort must equal the birth capture."""

    rt = runtime or Runtime()
    session = str(payload.get("session_id") or "")
    agent_id = str(payload.get("agent_id") or "")
    child, meta_path = _child_files(payload, rt)
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError) as exc:
        raise EvidenceError("birth_receipt_missing", f"child metadata unreadable: {exc}") from exc
    out = evidence_dir(root)
    births = []
    for candidate in sorted(out.glob("*.birth.json")):
        try:
            value = check_seal(json.loads(candidate.read_text()))
        except (OSError, ValueError):
            continue
        if value.get("parent_session") == session and value.get("task_name") == meta.get("description"):
            births.append(value)
    if len(births) != 1:
        raise EvidenceError("birth_receipt_missing", f"expected one receipt for child {meta.get('description')!r}, found {len(births)}", recovery="new checked birth required")
    birth = births[0]
    attempt = birth["attempt_id"]
    if marked(out, attempt, "model_mismatch"):
        raise EvidenceError("model_mismatch", "this birth was invalidated", recovery="new checked birth required")
    if marked(out, attempt, "verified"):
        return birth
    expected = birth["capture"]["selection"]
    try:
        rows = rt.read(child)
        seen = last_observation(rows, sidechain=True)
    except EvidenceError as exc:
        mark(out, attempt, "model_mismatch", agent_id=agent_id, reason=exc.code, observed=UNAVAILABLE)
        raise EvidenceError("model_mismatch", f"child transcript unreadable before first write ({exc.code})", recovery="new checked birth required") from exc
    if seen != {"model": expected["model"], "effort": expected["effort"]}:
        mark(out, attempt, "model_mismatch", agent_id=agent_id, reason="observed_differs", observed=seen)
        raise EvidenceError("model_mismatch", f"child runs {seen['model']}/{seen['effort']}, captured {expected['model']}/{expected['effort']}", recovery="new checked birth required", observed=seen)
    mark(out, attempt, "verified", agent_id=agent_id, observed=seen)
    return birth


def note_resolved_model(arguments: Mapping[str, Any], response: Any, root, *, session: str | None = None) -> dict[str, Any]:
    """PostToolUse(Agent): `resolvedModel` must equal the captured id."""

    if isinstance(response, str):
        try:
            response = json.loads(response)
        except ValueError:
            response = {}
    resolved = response.get("resolvedModel") if isinstance(response, dict) else None
    prompt = arguments.get("prompt") or ""
    match = re.search(r"^runtime_evidence_birth:\s*(\S+)\s*$", prompt, re.MULTILINE)
    if not match:
        raise EvidenceError("birth_receipt_missing")
    birth = check_seal(json.loads(Path(match[1]).read_text()))
    out = evidence_dir(root)
    expected = birth["capture"]["selection"]["model"]
    if resolved != expected:
        mark(out, birth["attempt_id"], "model_mismatch", reason="resolvedModel", observed=resolved or UNAVAILABLE)
        return {"ok": False, "resolved": resolved or UNAVAILABLE, "expected": expected, "attempt_id": birth["attempt_id"]}
    return {"ok": True, "resolved": resolved, "expected": expected, "attempt_id": birth["attempt_id"]}


def _handbacks(parent, agent_id: str, after: int) -> list[str]:
    tag = f'<agent-message from="{agent_id}">'
    reports = []
    for ordinal, row, _s in parent:
        if ordinal <= after or row.get("type") != "queue-operation" or row.get("operation") != "enqueue":
            continue
        content = row.get("content")
        if not isinstance(content, str) or tag not in content:
            continue
        body = content.split("The report follows:", 1)[1] if "The report follows:" in content else content.split(tag, 1)[1]
        body = re.sub(r"</agent-message>\s*\Z", "", body.strip()).strip()
        reports.append(body)
    return [r for r in reports if r]


def _projection(rows, ordinals, source) -> list[dict[str, Any]]:
    return [{"source": str(source), "ordinal": i, "type": r.get("type", UNAVAILABLE), "event_type": r.get("operation", UNAVAILABLE), "raw_sha256": sha} for i, r, sha in rows if i in ordinals]


def extract(birth, *, runtime: Runtime | None = None):
    rt = runtime or Runtime()
    check_seal(birth)
    if birth.get("schema") != SCHEMA or birth.get("driver") != DRIVER:
        raise EvidenceError("unsupported_schema")
    cap = validate_capture(birth["capture"], client="claude", role=birth["role"])
    if birth["attempt_id"] != cap["attempt_id"] or birth["band"] != cap["band"]:
        raise EvidenceError("birth_mismatch", "attempt/band differs from immutable capture")
    try:
        original = load_capture(birth["capture_path"])
    except (OSError, ValueError, SelectionError) as exc:
        raise EvidenceError("capture_changed", str(exc), recovery="restore immutable birth capture or new birth required") from exc
    if original != cap:
        raise EvidenceError("capture_changed", recovery="restore immutable birth capture or new birth required")
    selected = cap["selection"]
    parent_path, parent, pmeta = rt.session(birth["parent_session"], birth.get("parent_transcript"))
    calls = []
    for ordinal, row, _sha in parent:
        if ordinal < birth["before_record"] or row.get("type") != "assistant" or row.get("isSidechain"):
            continue
        for block in _blocks(row):
            data = block.get("input")
            if block.get("type") == "tool_use" and block.get("name") in SPAWN_TOOLS and isinstance(data, dict) and data.get("description") == birth["task_name"]:
                calls.append((ordinal, row, block))
    if len(calls) != 1:
        raise EvidenceError("birth_mismatch", f"expected one native spawn, found {len(calls)}", recovery="new checked birth required if no intact spawn origin")
    ci, call_row, call = calls[0]
    args = call["input"]
    try:
        if request_role(args) != birth["role"]:
            raise EvidenceError("role_mismatch", "native role/description differs from capture")
    except SelectionError as exc:
        raise EvidenceError("role_mismatch", str(exc)) from exc
    if any(args.get(k) != v for k, v in cap["arguments"].items()):
        raise EvidenceError("requested_mismatch", recovery="new checked birth required")
    message_id = (call_row.get("message") or {}).get("id")
    if not isinstance(message_id, str) or not message_id:
        raise EvidenceError("unsupported_schema", "parent assistant message id unavailable")
    outputs = [
        (i, r) for i, r, _s in parent
        if r.get("type") == "user" and isinstance(r.get("toolUseResult"), dict)
        and any(b.get("type") == "tool_result" and b.get("tool_use_id") == call["id"] for b in _blocks(r))
    ]
    if len(outputs) != 1:
        raise EvidenceError("spawn_return_unavailable")
    oi, out_row = outputs[0]
    result = out_row["toolUseResult"]
    agent_id = result.get("agentId")
    resolved = result.get("resolvedModel")
    if not isinstance(agent_id, str) or not AGENT_ID.fullmatch(agent_id):
        raise EvidenceError("spawn_return_malformed", "agentId missing")
    if resolved != selected["model"]:
        raise EvidenceError("model_mismatch", f"host resolved {resolved!r}, captured {selected['model']!r}", recovery="new checked birth required; do not resume/retune", observed=resolved or UNAVAILABLE)
    child_path, meta_path = rt.child_paths(parent_path, birth["parent_session"], agent_id)
    try:
        meta = json.loads(meta_path.read_text())
    except (OSError, ValueError) as exc:
        raise EvidenceError("source_unavailable", f"child metadata: {exc}") from exc
    if not isinstance(meta, dict) or meta.get("toolUseId") != call["id"] or meta.get("description") != birth["task_name"]:
        raise EvidenceError("identity_mismatch", "child metadata does not belong to this spawn", recovery="new checked birth required")
    if args.get("subagent_type") and meta.get("agentType") not in (None, args["subagent_type"]):
        raise EvidenceError("identity_mismatch", "child agent type")
    for key in ("model", "effort"):
        if key in meta and meta[key] != cap["arguments"][key]:
            raise EvidenceError("requested_mismatch", f"child metadata {key}={meta[key]!r}", recovery="new checked birth required")
    child = rt.read(child_path)
    cmeta = _identity(child, birth["parent_session"])
    if cmeta["version"] != pmeta["version"] or Path(cmeta["cwd"]).resolve() != Path(pmeta["cwd"]).resolve():
        raise EvidenceError("identity_mismatch", "child version/cwd differs from parent")
    turns, tools, used_child = [], set(), set()
    for i, row, _s in child:
        if row.get("agentId") not in (None, agent_id) or (row.get("type") in {"assistant", "user"} and row.get("isSidechain") is not True):
            raise EvidenceError("identity_mismatch", f"record {i} is not a sidechain record of agent {agent_id}")
        if row.get("type") != "assistant":
            continue
        message = row.get("message") if isinstance(row.get("message"), dict) else {}
        observed = {"model": message.get("model") or UNAVAILABLE, "effort": row.get("effort") or UNAVAILABLE}
        if observed != {"model": selected["model"], "effort": selected["effort"]} or row.get("perTurnEffort", observed["effort"]) != observed["effort"]:
            raise EvidenceError("model_mismatch", f"turn record {i}: {observed}", recovery="new checked birth required; do not resume/retune", observed=observed)
        turns.append({"ordinal": i, "uuid": row.get("uuid", UNAVAILABLE), "observed": observed})
        used_child.add(i)
        tools.update(b["name"] for b in _blocks(row) if b.get("type") == "tool_use" and isinstance(b.get("name"), str))
    if not turns:
        raise EvidenceError("observation_unavailable", "child transcript has no assistant record")
    if birth["role"] in REVIEWERS and not tools <= (READ_ONLY_TOOLS | RETURN_CHANNEL_TOOLS):
        raise EvidenceError("child_tool_mismatch", f"reviewer used {sorted(tools - READ_ONLY_TOOLS - RETURN_CHANNEL_TOOLS)}")
    host_status = str(result.get("status") or "")
    payloads: list[str] = []
    if host_status in {"failed", "error"}:
        status = "failed"
    elif host_status in {"interrupted", "killed", "cancelled", "stopped"}:
        status = "interrupted"
    else:
        inline = _text(result.get("content")) or _text([b.get("content") for b in _blocks(out_row) if b.get("tool_use_id") == call["id"]])
        payloads = [inline] if host_status == "completed" and inline else _handbacks(parent, agent_id, oi)
        if not payloads:
            raise EvidenceError("terminal_unavailable", "no completed payload returned to the parent yet")
        status = "completed"
    used_parent = {ci, oi}
    result_doc = {
        "schema": SCHEMA, "driver": DRIVER, "birth": birth, "attempt_id": cap["attempt_id"],
        "bound_card": birth["bound_card"], "root": birth["root"], "role": birth["role"], "band": birth["band"],
        "parent_session": birth["parent_session"], "parent_message_id": message_id, "child_agent_id": agent_id,
        "call_id": call["id"], "host": HOST, "host_version": pmeta["version"], "surface": pmeta["entrypoint"],
        "requested": {"model": selected["model"], "effort": selected["effort"]}, "requested_native": cap["arguments"],
        "resolved_model": resolved, "turns": turns, "tools_used": sorted(tools),
        "read_only": tools <= (READ_ONLY_TOOLS | RETURN_CHANNEL_TOOLS),
        "status": status, "payload_returned": status == "completed",
        "payload_sha256": [digest(p.encode()) for p in payloads], "qualification": False,
        "review_diff_sha256": birth["review_diff_sha256"], "wave_id": birth.get("wave_id", UNAVAILABLE),
        "sources": _projection(parent, used_parent, parent_path) + _projection(child, used_child, child_path),
        "validation": "verified",
    }
    return result_doc


def collect(birth_path, *, dest=None, wait_seconds=5.0, runtime=None):
    if not 0 <= wait_seconds <= MAX_WAIT:
        raise EvidenceError("invalid_wait", f"bounded window is 0..{MAX_WAIT}s")
    birth = check_seal(json.loads(Path(birth_path).read_text()))
    out = destination(birth["root"], dest or Path(birth_path).parent)
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            result = sealed(extract(birth, runtime=runtime))
            target = out / f"{birth['attempt_id']}.evidence.json"
            _verify_snapshots(out, result)
            if target.exists() and json.loads(target.read_text()) != result:
                target = out / f"{birth['attempt_id']}.evidence-{result['integrity_sha256']}.json"
            private_write(target, result)
            return dict(result, evidence_path=str(target))
        except EvidenceError as exc:
            if exc.code not in RETRYABLE or time.monotonic() >= deadline:
                failure = sealed({
                    "schema": SCHEMA, "attempt_id": birth["attempt_id"], "bound_card": birth["bound_card"], "role": birth["role"],
                    "parent_session": birth["parent_session"], "capture_sha256": birth["capture"]["capture_sha256"],
                    "requested": birth["capture"]["arguments"], "observed": exc.observed, "result": "blocked", "code": exc.code,
                    "detail": exc.detail, "wait_seconds": wait_seconds, "recovery": exc.recovery,
                })
                private_write(out / f"{birth['attempt_id']}.failure-{digest(failure)[:12]}.json", failure)
                raise
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def verify_evidence(path, *, runtime=None):
    try:
        envelope = check_seal(json.loads(Path(path).read_text()))
        fresh = sealed(extract(envelope["birth"], runtime=runtime))
        _verify_snapshot(envelope, fresh)
        _verify_snapshots(Path(path).parent, fresh)
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise EvidenceError("evidence_unavailable", str(exc)) from exc
    return envelope


def verify_proxy(entry, *, runtime=None):
    proof = verify_evidence(entry.get("runtime_evidence", ""), runtime=runtime)
    cap = proof["birth"]["capture"]
    last = proof["turns"][-1]["observed"]
    bindings = {
        "activity": proof["role"], "band": proof["band"], "bound_card": proof["bound_card"], "child_id": proof["child_agent_id"],
        "host": proof["host"], "host_version": proof["host_version"], "surface": proof["surface"], "selection_capture": cap,
        "status": proof["status"], "payload_returned": proof["payload_returned"],
        "requested_model": proof["requested"]["model"], "requested_effort": proof["requested"]["effort"],
        "observed_model": last["model"], "observed_effort": last["effort"], "tools_used": proof["tools_used"],
        "read_only": proof["read_only"], "review_diff_sha256": proof["review_diff_sha256"],
        "wave_id": proof.get("wave_id", UNAVAILABLE),
    }
    if any(entry.get(k) != v for k, v in bindings.items()):
        raise EvidenceError("proxy_binding_mismatch")
    if entry.get("evidence_sha256", proof["integrity_sha256"]) != proof["integrity_sha256"]:
        raise EvidenceError("proxy_binding_mismatch", "snapshot digest differs from proxy")
    return proof


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "prepare"):
        p = sub.add_parser(command)
        p.add_argument("--root", type=Path, default=Path.cwd())
        p.add_argument("--capture", type=Path, required=command == "prepare")
        p.add_argument("--dest", type=Path, default=DEFAULT_DEST)
        p.add_argument("--session", help="session id of the spawning session (default CLAUDE_CODE_SESSION_ID)")
        if command == "prepare":
            p.add_argument("--task-name", required=True, help="unique Agent description containing the role needle")
            p.add_argument("--review-diff-sha256", default=UNAVAILABLE)
            p.add_argument("--wave-id", default=UNAVAILABLE)
    p = sub.add_parser("collect")
    p.add_argument("--birth", required=True, type=Path)
    p.add_argument("--wait-seconds", type=float, default=5)
    p = sub.add_parser("verify")
    p.add_argument("--evidence", required=True, type=Path)
    sub.add_parser("observe-parent")
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "collect":
            result = collect(args["birth"], wait_seconds=args["wait_seconds"])
        elif command == "verify":
            result = verify_evidence(args["evidence"])
        elif command == "observe-parent":
            result = observe_parent()
        else:
            result = (prepare if command == "prepare" else preflight)(**args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (EvidenceError, OSError, ValueError, SelectionError) as exc:
        root = args.get("root", Path.cwd())
        print(json.dumps({
            "result": "blocked", "schema": SCHEMA, "root": str(root), "session": args.get("session") or os.environ.get("CLAUDE_CODE_SESSION_ID", UNAVAILABLE),
            "host": HOST, "code": getattr(exc, "code", "invalid_input"), "observed": getattr(exc, "observed", UNAVAILABLE),
            "detail": str(exc), "recovery": getattr(exc, "recovery", "restore source; preserve Status/artifacts"),
        }, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
