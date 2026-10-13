"""Synthetic, sanitized Claude Code transcripts shaped like a real 2.1.296 CLI session.

Only the fields the evidence driver reads are reproduced; ids, prompts and
payloads are invented. Used by the claude_* tests, never by production code.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from model_selection import resolve, save_capture
import claude_evidence as ev
import claude_trust

SESSION = "11111111-2222-3333-4444-555555555555"
AGENT = "a0123456789abcdef"
VERSION = "2.1.296"
DIGEST = "d" * 64

# Real `PreToolUse` payload of the `Agent` tool recorded on host 2.1.296 (CLI, `-p`)
# in the task 8.2 rehearsal; ids and paths sanitized, keys and shapes verbatim.
# The session effort lives in the top-level `effort` object; the per-spawn effort
# only in `tool_input.effort`.
PRETOOL_AGENT_2_1_296 = {
    "session_id": SESSION,
    "transcript_path": f"/home/user/.claude/projects/-repo/{SESSION}.jsonl",
    "cwd": "/repo",
    "prompt_id": "00000000-0000-0000-0000-000000000000",
    "permission_mode": "acceptEdits",
    "effort": {"level": "medium"},
    "hook_event_name": "PreToolUse",
    "tool_name": "Agent",
    "tool_input": {
        "description": "apply-coluna 1101 ensaio-8.2-payload",
        "prompt": "responda ok",
        "subagent_type": "general-purpose",
        "model": "haiku",
        "effort": "low",
    },
    "tool_use_id": "toolu_00000000000000000000000000",
}


def trust_ok():
    return {"reviewed": True, "digest": DIGEST, "reason": ""}


def git_repo(tmp_path: Path, name="card-1101-test") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    subprocess.run(["git", "init", "-b", name, str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "i"], check=True, capture_output=True)
    return repo


def write_jsonl(path: Path, rows, *, truncate=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    path.write_text(body.rstrip("\n") if truncate else body)


def record(kind: str, cwd: Path, *, session=SESSION, version=VERSION, entrypoint="cli", **extra):
    return {"type": kind, "sessionId": session, "version": version, "entrypoint": entrypoint, "cwd": str(cwd), **extra}


def assistant(cwd, *, model, effort, content, msg_id, sidechain=False, agent=None, **kw):
    row = record("assistant", cwd, isSidechain=sidechain, effort=effort, perTurnEffort=effort,
                 message={"model": model, "id": msg_id, "role": "assistant", "content": content}, uuid=f"u-{msg_id}-{len(content)}", **kw)
    if agent:
        row["agentId"] = agent
    return row


class World:
    """A repo, a Claude home with one parent transcript, a heartbeat and a captured birth."""

    def __init__(self, tmp_path: Path, monkeypatch=None, *, name="card-1101-test"):
        self.tmp = tmp_path
        self.repo = git_repo(tmp_path, name)
        self.home = Path.home() / ".claude"
        self.runtime = ev.Runtime(home=self.home)
        self.parent = self.home / "projects" / "-slug" / f"{SESSION}.jsonl"
        self.subdir = self.parent.with_suffix("") / "subagents"
        self.env = {"CLAUDE_CODE_SESSION_ID": SESSION, "AI_AGENT": f"claude-code_{VERSION.replace('.', '-')}_agent", "CLAUDE_CODE_ENTRYPOINT": "cli"}
        self.rows = [
            record("user", self.repo, message={"role": "user", "content": "start"}),
            assistant(self.repo, model="claude-sonnet-5-5", effort="high", content=[{"type": "text", "text": "ok"}], msg_id="m0"),
        ]
        self.flush()
        claude_trust.write_heartbeat(session_id=SESSION, transcript_path=str(self.parent), cwd=str(self.repo),
                                     digest=DIGEST, reviewed=True, environ=self.env, version=VERSION)

    def flush(self, **kw):
        write_jsonl(self.parent, self.rows, **kw)

    def capture(self, role="apply-coluna"):
        band = "juizo" if role in {"design-autor", "design-critic", "grill-card"} else "execucao"
        cap = resolve("claude", band, role=role)
        path = self.tmp / f"cap-{cap['attempt_id']}.json"
        save_capture(path, cap)
        return cap, path

    def prepare(self, role="apply-coluna", task=None, *, diff=ev.UNAVAILABLE, wave=ev.UNAVAILABLE):
        cap, path = self.capture(role)
        task = task or f"{role} 1101 {cap['attempt_id'][:8]}"
        out = ev.prepare(root=self.repo, capture=path, task_name=task, runtime=self.runtime, session=SESSION,
                         environ=self.env, trust=trust_ok, review_diff_sha256=diff, wave_id=wave)
        return cap, path, task, out

    def spawn(self, cap, task, *, role="apply-coluna", call_id="toolu_A", agent=AGENT, resolved=None, status="async_launched",
              child_model=None, child_effort=None, child_tools=("Read", "Bash"), subagent_type="general-purpose",
              msg_id="m-spawn", meta_overrides=None, child_session=SESSION, handback="Final report: done", content=None,
              args_override=None, extra_child_rows=()):
        sel = cap["selection"]
        args = {"description": task, "subagent_type": subagent_type, "prompt": "p", **cap["arguments"], **(args_override or {})}
        self.rows.append(assistant(self.repo, model="claude-sonnet-5-5", effort="high", msg_id=msg_id,
                                   content=[{"type": "tool_use", "id": call_id, "name": "Agent", "input": args}]))
        self.rows.append(record("user", self.repo, toolUseResult={"isAsync": True, "status": status, "agentId": agent, "description": task,
                                                                   "resolvedModel": resolved or sel["model"], **({"content": [{"type": "text", "text": content}]} if content else {})},
                                message={"role": "user", "content": [{"type": "tool_result", "tool_use_id": call_id, "content": [{"type": "text", "text": "Async agent launched"}]}]}))
        meta = {"agentType": subagent_type, "description": task, "toolUseId": call_id, "spawnDepth": 1,
                "model": cap["arguments"]["model"], "effort": cap["arguments"]["effort"], **(meta_overrides or {})}
        (self.subdir).mkdir(parents=True, exist_ok=True)
        (self.subdir / f"agent-{agent}.meta.json").write_text(json.dumps(meta))
        crow = [record("user", self.repo, session=child_session, isSidechain=True, agentId=agent, message={"role": "user", "content": "task"})]
        for n, tool in enumerate(child_tools):
            crow.append(assistant(self.repo, model=child_model or sel["model"], effort=child_effort or sel["effort"], msg_id=f"c{n}",
                                  content=[{"type": "tool_use", "id": f"t{n}", "name": tool, "input": {}}], sidechain=True, agent=agent, session=child_session))
        crow.extend(extra_child_rows)
        write_jsonl(self.subdir / f"agent-{agent}.jsonl", crow)
        if handback:
            self.rows.append({"type": "queue-operation", "operation": "enqueue", "sessionId": SESSION,
                              "content": f'<agent-message from="{agent}">\n[Subagent hand-back] frame\nThe report follows:\n  {handback}\n</agent-message>'})
        self.flush()
        return args

    def collect(self, birth_path, **kw):
        return ev.collect(birth_path, wait_seconds=0, runtime=self.runtime, **kw)
