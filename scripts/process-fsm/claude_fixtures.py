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
    repo.mkdir(parents=True)
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

    def __init__(self, tmp_path: Path, monkeypatch=None, *, name="card-1101-test", version=VERSION, entrypoint="cli"):
        self.tmp = tmp_path
        self.repo = git_repo(tmp_path, name)
        self.home = Path.home() / ".claude"
        self.runtime = ev.Runtime(home=self.home)
        self.parent = self.home / "projects" / "-slug" / f"{SESSION}.jsonl"
        self.subdir = self.parent.with_suffix("") / "subagents"
        self.env = {"CLAUDE_CODE_SESSION_ID": SESSION, "AI_AGENT": f"claude-code_{version.replace('.', '-')}_agent", "CLAUDE_CODE_ENTRYPOINT": entrypoint}
        self.rows = [
            record("user", self.repo, version=version, entrypoint=entrypoint, message={"role": "user", "content": "start"}),
            assistant(self.repo, model="claude-sonnet-5-5", effort="high", content=[{"type": "text", "text": "ok"}], msg_id="m0", version=version, entrypoint=entrypoint),
        ]
        self.flush()
        claude_trust.write_heartbeat(session_id=SESSION, transcript_path=str(self.parent), cwd=str(self.repo),
                                     digest=DIGEST, reviewed=True, environ=self.env, version=version)

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


# ---------------------------------------------------------------------------------------------------------------
# REAL transcripts, sanitized (task 4.4 and 5.5 of the #1103).
#
# Taken from the local `~/.claude/projects/` of the operator's VM on 2026-10-15 and reduced to the records the
# evidence driver and the tests read. Sanitization: session ids become `{session}`, every working directory becomes
# `{cwd}` (the test repository), every free text (prompts, thinking, tool input and output, reports, notification
# summaries) becomes "[sanitized]". Kept verbatim: record kinds, models, efforts, versions, the surface
# (`entrypoint`), statuses, agent and tool-use ids (opaque, server generated), the `description` of each spawn and the
# structure around them. Keys the driver never reads that carry tokens, paths or repository metadata were dropped.
#
# APP_SESSION_2_1_295: the session `92c55543...` opened by the desktop app over SSH (entrypoint `claude-desktop`,
# the app's own copy of Claude Code 2.1.295, app 2.37337.1) in which the grelha of the #1103 ran. Its only child,
# `grill-card #1103`, ran in the foreground, was resumed by SendMessage (a second `<agent-message>` and a
# `<task-notification>` for ANOTHER tool call, the SendMessage one), and was launched WITHOUT `effort`.
# Known gap (task 4.4): the app has not yet produced a child with an explicit `effort`; `RealWorld.launch(...,
# explicit_effort=True)` adds that single field to the spawn and nothing else, and the unmodified record is kept to
# prove the refusal.
#
# CLI_BACKGROUND_2_1_300: the terminal session (entrypoint `cli`, Claude Code 2.1.300) that designed the #1103. Every
# `Agent` returned `status="async_launched"` with `resolvedModel`, and the conclusion arrived as a `queue-operation`
# `enqueue` with a `<task-notification>` (agents `af0a1917b83c8aa19` = design-autor, `aacea23e2dfb0ccf9` = design-critic).
# ---------------------------------------------------------------------------------------------------------------

APP_SESSION_2_1_295 = {'session': 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee',
 'version': '2.1.295',
 'entrypoint': 'claude-desktop',
 'desktop_app_version': '2.37337.1',
 'agent_id': 'a5bae85b261bb5846',
 'spawn_call_id': 'toolu_01U6h4SuLtj2WDEvUheK1S3S',
 'resume_call_id': 'toolu_01CxrxjAkppBrFo5DgRgcprN',
 'description': 'grill-card #1103',
 'parent_rows': [{'parentUuid': None,
                  'isSidechain': False,
                  'promptId': '6785fced-bc85-4816-95f2-eac5dc71191a',
                  'type': 'user',
                  'message': {'role': 'user', 'content': '[sanitized]'},
                  'uuid': '52dd6175-b1c4-4a84-a9f2-f6dfb0df2fce',
                  'timestamp': '2026-10-15T02:43:42.591Z',
                  'permissionMode': '[sanitized]',
                  'origin': {'kind': '[sanitized]'},
                  'promptSource': '[sanitized]',
                  'turnOrigin': '[sanitized]',
                  'turnPosition': {'promptIndex': 1, 'turnIndex': 1},
                  'userType': 'external',
                  'entrypoint': 'claude-desktop',
                  'cwd': '{cwd}',
                  'sessionId': '{session}',
                  'version': '2.1.295',
                  'gitBranch': 'develop'},
                 {'parentUuid': 'c7c0f227-da5d-4c37-b8ed-892ae5604ae2',
                  'isSidechain': False,
                  'message': {'model': 'claude-opus-5-5',
                              'id': 'msg_011Cg3GFqG8KAwUJm1XsQEwD',
                              'type': 'message',
                              'role': 'assistant',
                              'content': [{'type': 'thinking', 'thinking': '[sanitized]', 'signature': '[sanitized]'}],
                              'stop_reason': 'tool_use'},
                  'thinkingDurationMs': 20235,
                  'serverClassifierRequest': '5d9974a8-1e37-41ff-95e3-f673cda2267b',
                  'apiBlockIndex': 0,
                  'requestId': 'req_011Cg3GFpvYY1oMGR24nBZ4f',
                  'requestedModel': 'claude-opus-5-5',
                  'type': 'assistant',
                  'uuid': '6fa73e6c-ef00-4974-80a3-29644c9c9b15',
                  'timestamp': '2026-10-15T02:51:28.632Z',
                  'advisorModel': 'claude-opus-5-5',
                  'effort': 'medium',
                  'perTurnEffort': 'medium',
                  'userType': 'external',
                  'entrypoint': 'claude-desktop',
                  'cwd': '{cwd}',
                  'sessionId': '{session}',
                  'version': '2.1.295',
                  'gitBranch': 'develop'},
                 {'parentUuid': 'bac401d8-d363-4cd6-952a-e6e4c297ca68',
                  'isSidechain': False,
                  'message': {'model': 'claude-opus-5-5',
                              'id': 'msg_011Cg3GFqG8KAwUJm1XsQEwD',
                              'type': 'message',
                              'role': 'assistant',
                              'content': [{'type': 'tool_use',
                                           'id': 'toolu_01QKFfB7xAXLGkDipnziUgbi',
                                           'name': 'mcp__ccd_turn__update_plan',
                                           'input': {},
                                           'caller': {'type': 'direct'}}],
                              'stop_reason': 'tool_use'},
                  'serverClassifierRequest': '5d9974a8-1e37-41ff-95e3-f673cda2267b',
                  'apiBlockIndex': 2,
                  'requestId': 'req_011Cg3GFpvYY1oMGR24nBZ4f',
                  'requestedModel': 'claude-opus-5-5',
                  'type': 'assistant',
                  'uuid': '4b826171-9cf5-4260-91a5-deb1f5bfa1e1',
                  'timestamp': '2026-10-15T02:51:28.646Z',
                  'advisorModel': 'claude-opus-5-5',
                  'effort': 'medium',
                  'perTurnEffort': 'medium',
                  'userType': 'external',
                  'entrypoint': 'claude-desktop',
                  'cwd': '{cwd}',
                  'sessionId': '{session}',
                  'version': '2.1.295',
                  'gitBranch': 'develop'},
                 {'parentUuid': '4b826171-9cf5-4260-91a5-deb1f5bfa1e1',
                  'isSidechain': False,
                  'promptId': '5dfe5383-4ccd-4cba-9e5a-36098c74a254',
                  'type': 'user',
                  'message': {'role': 'user',
                              'content': [{'tool_use_id': 'toolu_01QKFfB7xAXLGkDipnziUgbi',
                                           'type': 'tool_result',
                                           'content': '[sanitized]'}]},
                  'uuid': 'dc8651ca-0d34-4441-aa99-4de358431221',
                  'timestamp': '2026-10-15T02:51:28.805Z',
                  'toolUseResult': [{'type': 'text', 'text': '[sanitized]'}],
                  'sourceToolAssistantUUID': '4b826171-9cf5-4260-91a5-deb1f5bfa1e1',
                  'userType': 'external',
                  'entrypoint': 'claude-desktop',
                  'cwd': '{cwd}',
                  'sessionId': '{session}',
                  'version': '2.1.295',
                  'gitBranch': 'develop'},
                 {'parentUuid': 'dc8651ca-0d34-4441-aa99-4de358431221',
                  'isSidechain': False,
                  'message': {'model': 'claude-opus-5-5',
                              'id': 'msg_011Cg3GFqG8KAwUJm1XsQEwD',
                              'type': 'message',
                              'role': 'assistant',
                              'content': [{'type': 'tool_use',
                                           'id': 'toolu_01U6h4SuLtj2WDEvUheK1S3S',
                                           'name': 'Agent',
                                           'input': {'description': 'grill-card #1103',
                                                     'subagent_type': 'general-purpose',
                                                     'model': 'opus',
                                                     'run_in_background': False,
                                                     'prompt': '[sanitized]'},
                                           'caller': {'type': 'direct'}}],
                              'stop_reason': 'tool_use'},
                  'serverClassifierRequest': '5d9974a8-1e37-41ff-95e3-f673cda2267b',
                  'apiBlockIndex': 3,
                  'requestId': 'req_011Cg3GFpvYY1oMGR24nBZ4f',
                  'requestedModel': 'claude-opus-5-5',
                  'type': 'assistant',
                  'uuid': 'e079cac7-093a-43e7-9f89-d9c9804d195f',
                  'timestamp': '2026-10-15T02:51:48.230Z',
                  'advisorModel': 'claude-opus-5-5',
                  'effort': 'medium',
                  'perTurnEffort': 'medium',
                  'userType': 'external',
                  'entrypoint': 'claude-desktop',
                  'cwd': '{cwd}',
                  'sessionId': '{session}',
                  'version': '2.1.295',
                  'gitBranch': 'develop'},
                 {'type': 'queue-operation',
                  'operation': 'enqueue',
                  'timestamp': '2026-10-15T02:52:54.040Z',
                  'sessionId': '{session}',
                  'content': '<agent-message from="a5bae85b261bb5846">\n'
                             '[Subagent hand-back] [sanitized]\n'
                             'The report follows:\n'
                             '  [sanitized]\n'
                             '</agent-message>'},
                 {'parentUuid': 'e079cac7-093a-43e7-9f89-d9c9804d195f',
                  'isSidechain': False,
                  'promptId': '5dfe5383-4ccd-4cba-9e5a-36098c74a254',
                  'type': 'user',
                  'message': {'role': 'user',
                              'content': [{'tool_use_id': 'toolu_01U6h4SuLtj2WDEvUheK1S3S',
                                           'type': 'tool_result',
                                           'content': '[sanitized]'}]},
                  'uuid': '91681039-d08c-49d4-9117-6cf71415b5a2',
                  'timestamp': '2026-10-15T02:52:54.067Z',
                  'toolUseResult': {'status': 'completed',
                                    'prompt': '[sanitized]',
                                    'agentId': 'a5bae85b261bb5846',
                                    'agentType': 'general-purpose',
                                    'handback': 'send',
                                    'handbackReport': {'text': '[sanitized]'},
                                    'content': [{'type': 'text',
                                                 'text': 'This agent\'s report was delivered to you as a message from "a5bae85b261bb5846" '
                                                         '(its SubagentHandback call). Read it there; it is not repeated here.\n'}],
                                    'resolvedModel': 'claude-opus-5-5',
                                    'canContinueAgent': True},
                  'sourceToolAssistantUUID': 'e079cac7-093a-43e7-9f89-d9c9804d195f',
                  'userType': 'external',
                  'entrypoint': 'claude-desktop',
                  'cwd': '{cwd}',
                  'sessionId': '{session}',
                  'version': '2.1.295',
                  'gitBranch': 'develop'},
                 {'type': 'queue-operation',
                  'operation': 'remove',
                  'timestamp': '2026-10-15T02:52:54.084Z',
                  'sessionId': '{session}',
                  'content': '<agent-message from="a5bae85b261bb5846">\n'
                             '[Subagent hand-back] [sanitized]\n'
                             'The report follows:\n'
                             '  [sanitized]\n'
                             '</agent-message>'},
                 {'parentUuid': '25c108bc-9125-4bf3-868e-835517fb5929',
                  'isSidechain': False,
                  'message': {'model': 'claude-opus-5-5',
                              'id': 'msg_011Cg3GgWAcrgiB7hvqqkXXQ',
                              'type': 'message',
                              'role': 'assistant',
                              'content': [{'type': 'tool_use',
                                           'id': 'toolu_01CxrxjAkppBrFo5DgRgcprN',
                                           'name': 'SendMessage',
                                           'input': {},
                                           'caller': {'type': 'direct'}}],
                              'stop_reason': 'tool_use'},
                  'serverClassifierRequest': '5bcf6509-5bb8-4da1-8a8a-2392f5f7ad2f',
                  'apiBlockIndex': 2,
                  'requestId': 'req_011Cg3GgV2AeMfTkkZX2Rmmm',
                  'requestedModel': 'claude-opus-5-5',
                  'attributionMcpServer': '[sanitized]',
                  'attributionMcpTool': '[sanitized]',
                  'type': 'assistant',
                  'uuid': '6f26321d-5c9e-4caf-a88e-7a67cf8a6d4c',
                  'timestamp': '2026-10-15T02:56:52.251Z',
                  'advisorModel': 'claude-opus-5-5',
                  'effort': 'medium',
                  'perTurnEffort': 'medium',
                  'userType': 'external',
                  'entrypoint': 'claude-desktop',
                  'cwd': '{cwd}',
                  'sessionId': '{session}',
                  'version': '2.1.295',
                  'gitBranch': 'develop'},
                 {'parentUuid': '6f26321d-5c9e-4caf-a88e-7a67cf8a6d4c',
                  'isSidechain': False,
                  'promptId': '5dfe5383-4ccd-4cba-9e5a-36098c74a254',
                  'type': 'user',
                  'message': {'role': 'user',
                              'content': [{'tool_use_id': 'toolu_01CxrxjAkppBrFo5DgRgcprN',
                                           'type': 'tool_result',
                                           'content': '[sanitized]'}]},
                  'uuid': '643e448a-0f0f-4d11-a9f0-feb0fdb20915',
                  'timestamp': '2026-10-15T02:56:52.706Z',
                  'toolUseResult': {'success': True,
                                    'message': '[sanitized]',
                                    'resumedAgentId': '[sanitized]',
                                    'pin': {'id': 'a5bae85b261bb5846', 'name': 'a5bae85b261bb5846', 'ref': '[sanitized]'}},
                  'sourceToolAssistantUUID': '6f26321d-5c9e-4caf-a88e-7a67cf8a6d4c',
                  'userType': 'external',
                  'entrypoint': 'claude-desktop',
                  'cwd': '{cwd}',
                  'sessionId': '{session}',
                  'version': '2.1.295',
                  'gitBranch': 'develop'},
                 {'type': 'queue-operation',
                  'operation': 'enqueue',
                  'timestamp': '2026-10-15T02:57:31.901Z',
                  'sessionId': '{session}',
                  'content': '<agent-message from="a5bae85b261bb5846">\n'
                             '[Subagent hand-back] [sanitized]\n'
                             'The report follows:\n'
                             '  [sanitized]\n'
                             '</agent-message>'},
                 {'type': 'queue-operation',
                  'operation': 'enqueue',
                  'timestamp': '2026-10-15T02:57:32.027Z',
                  'sessionId': '{session}',
                  'content': '<task-notification>\n'
                             '<task-id>a5bae85b261bb5846</task-id>\n'
                             '<tool-use-id>toolu_01CxrxjAkppBrFo5DgRgcprN</tool-use-id>\n'
                             '<output-file>[sanitized]</output-file>\n'
                             '<status>completed</status>\n'
                             '<summary>[sanitized]</summary>\n'
                             '<note>[sanitized]</note>\n'
                             '<result>[sanitized]</result>\n'
                             '<usage><subagent_tokens>0</subagent_tokens><tool_uses>0</tool_uses><duration_ms>0</duration_ms></usage>\n'
                             '</task-notification>'},
                 {'parentUuid': '18229556-441a-49e9-8fa2-8ee542839369',
                  'isSidechain': False,
                  'message': {'model': 'claude-opus-5-5',
                              'id': 'msg_011Cg3GkAfiVqmcX6jJXYo1e',
                              'type': 'message',
                              'role': 'assistant',
                              'content': [{'type': 'text', 'text': '[sanitized]'}],
                              'stop_reason': 'tool_use'},
                  'serverClassifierRequest': 'eac50814-bec0-4812-bb8d-cba9cb47d62b',
                  'apiBlockIndex': 0,
                  'requestId': 'req_011Cg3GkAPc9ZZWs37PSUDAt',
                  'requestedModel': 'claude-opus-5-5',
                  'type': 'assistant',
                  'uuid': 'f06acd0b-197a-4ba0-a296-77eec6bc25d0',
                  'timestamp': '2026-10-15T02:57:33.201Z',
                  'advisorModel': 'claude-opus-5-5',
                  'effort': 'medium',
                  'perTurnEffort': 'medium',
                  'userType': 'external',
                  'entrypoint': 'claude-desktop',
                  'cwd': '{cwd}',
                  'sessionId': '{session}',
                  'version': '2.1.295',
                  'gitBranch': 'develop'}],
 'child_rows': [{'parentUuid': None,
                 'isSidechain': True,
                 'promptId': '5dfe5383-4ccd-4cba-9e5a-36098c74a254',
                 'agentId': 'a5bae85b261bb5846',
                 'type': 'user',
                 'message': {'role': 'user', 'content': '[sanitized]'},
                 'uuid': 'bb7409ed-373e-4f6f-b48f-22375753a2b1',
                 'timestamp': '2026-10-15T02:51:48.772Z',
                 'userType': 'external',
                 'entrypoint': 'claude-desktop',
                 'cwd': '{cwd}',
                 'sessionId': '{session}',
                 'version': '2.1.295',
                 'gitBranch': 'develop'},
                {'parentUuid': '9110deff-ee81-4c20-b351-ef42b39c6790',
                 'isSidechain': True,
                 'promptId': '5dfe5383-4ccd-4cba-9e5a-36098c74a254',
                 'agentId': 'a5bae85b261bb5846',
                 'type': 'user',
                 'message': {'role': 'user', 'content': '[sanitized]'},
                 'isMeta': True,
                 'uuid': '675033d5-c7e7-4247-a49f-6177a9d0fb8e',
                 'timestamp': '2026-10-15T02:51:48.787Z',
                 'userType': 'external',
                 'entrypoint': 'claude-desktop',
                 'cwd': '{cwd}',
                 'sessionId': '{session}',
                 'version': '2.1.295',
                 'gitBranch': 'develop'},
                {'parentUuid': 'b3e60c3c-68f4-49e8-9185-b4a070853b4a',
                 'isSidechain': True,
                 'agentId': 'a5bae85b261bb5846',
                 'message': {'model': 'claude-opus-5-5',
                             'id': 'msg_011Cg3GJshp5oMdYVELGnP1T',
                             'type': 'message',
                             'role': 'assistant',
                             'content': [{'type': 'tool_use',
                                          'id': 'toolu_01G6guqa5VzLgy2ZNywZ1vgW',
                                          'name': 'Bash',
                                          'input': {'command': '[sanitized]'},
                                          'caller': {'type': 'direct'}}],
                             'stop_reason': None},
                 'serverClassifierRequest': 'fcc7f386-f9c9-4657-a5cf-f90f1dcc0ddb',
                 'apiBlockIndex': 0,
                 'requestId': 'req_011Cg3GJsKVJNVGqNRtcCgo9',
                 'requestedModel': 'claude-opus-5-5',
                 'type': 'assistant',
                 'uuid': 'c2bc652e-eec4-4ec2-909c-c20b0e0eb80e',
                 'timestamp': '2026-10-15T02:51:51.102Z',
                 'advisorModel': 'claude-opus-5-5',
                 'effort': 'medium',
                 'perTurnEffort': 'medium',
                 'userType': 'external',
                 'entrypoint': 'claude-desktop',
                 'cwd': '{cwd}',
                 'sessionId': '{session}',
                 'version': '2.1.295',
                 'gitBranch': 'develop'},
                {'parentUuid': 'c2bc652e-eec4-4ec2-909c-c20b0e0eb80e',
                 'isSidechain': True,
                 'promptId': '5dfe5383-4ccd-4cba-9e5a-36098c74a254',
                 'agentId': 'a5bae85b261bb5846',
                 'type': 'user',
                 'message': {'role': 'user',
                             'content': [{'tool_use_id': 'toolu_01G6guqa5VzLgy2ZNywZ1vgW',
                                          'type': 'tool_result',
                                          'content': '[sanitized]',
                                          'is_error': False}]},
                 'uuid': '2002ac04-dfd1-493e-a0fe-91b73826439b',
                 'timestamp': '2026-10-15T02:51:51.499Z',
                 'sourceToolAssistantUUID': 'c2bc652e-eec4-4ec2-909c-c20b0e0eb80e',
                 'userType': 'external',
                 'entrypoint': 'claude-desktop',
                 'cwd': '{cwd}',
                 'sessionId': '{session}',
                 'version': '2.1.295',
                 'gitBranch': 'develop'},
                {'parentUuid': 'b1fba327-9034-460b-bb91-c7637c4b82e4',
                 'isSidechain': True,
                 'agentId': 'a5bae85b261bb5846',
                 'message': {'model': 'claude-opus-5-5',
                             'id': 'msg_011Cg3GizuZQq5Kiw7CkBPPw',
                             'type': 'message',
                             'role': 'assistant',
                             'content': [{'type': 'thinking', 'thinking': '[sanitized]', 'signature': '[sanitized]'}],
                             'stop_reason': None},
                 'thinkingDurationMs': 952,
                 'serverClassifierRequest': 'ebe952fa-016d-4150-8e59-c6d105915ead',
                 'apiBlockIndex': 0,
                 'requestId': 'req_011Cg3GizdhSwLz6D48dfcLs',
                 'requestedModel': 'claude-opus-5-5',
                 'type': 'assistant',
                 'uuid': 'a202ed5e-5de5-4450-a4f9-4e72dc2ac476',
                 'timestamp': '2026-10-15T02:57:17.826Z',
                 'advisorModel': 'claude-opus-5-5',
                 'effort': 'medium',
                 'perTurnEffort': 'medium',
                 'userType': 'external',
                 'entrypoint': 'claude-desktop',
                 'cwd': '{cwd}',
                 'sessionId': '{session}',
                 'version': '2.1.295',
                 'gitBranch': 'develop'},
                {'parentUuid': 'a202ed5e-5de5-4450-a4f9-4e72dc2ac476',
                 'isSidechain': True,
                 'agentId': 'a5bae85b261bb5846',
                 'message': {'model': 'claude-opus-5-5',
                             'id': 'msg_011Cg3GizuZQq5Kiw7CkBPPw',
                             'type': 'message',
                             'role': 'assistant',
                             'content': [{'type': 'tool_use',
                                          'id': 'toolu_01HT87NGR6PR2eURz1R9ExP2',
                                          'name': 'Bash',
                                          'input': {'command': '[sanitized]'},
                                          'caller': {'type': 'direct'}}],
                             'stop_reason': None},
                 'serverClassifierRequest': 'ebe952fa-016d-4150-8e59-c6d105915ead',
                 'apiBlockIndex': 1,
                 'requestId': 'req_011Cg3GizdhSwLz6D48dfcLs',
                 'requestedModel': 'claude-opus-5-5',
                 'type': 'assistant',
                 'uuid': 'c019d361-e3ad-4f4d-9679-b9a004899c05',
                 'timestamp': '2026-10-15T02:57:19.014Z',
                 'advisorModel': 'claude-opus-5-5',
                 'effort': 'medium',
                 'perTurnEffort': 'medium',
                 'userType': 'external',
                 'entrypoint': 'claude-desktop',
                 'cwd': '{cwd}',
                 'sessionId': '{session}',
                 'version': '2.1.295',
                 'gitBranch': 'develop'},
                {'parentUuid': 'c019d361-e3ad-4f4d-9679-b9a004899c05',
                 'isSidechain': True,
                 'promptId': '5dfe5383-4ccd-4cba-9e5a-36098c74a254',
                 'agentId': 'a5bae85b261bb5846',
                 'type': 'user',
                 'message': {'role': 'user',
                             'content': [{'tool_use_id': 'toolu_01HT87NGR6PR2eURz1R9ExP2',
                                          'type': 'tool_result',
                                          'content': '[sanitized]',
                                          'is_error': False}]},
                 'uuid': 'ddc817a3-7124-4cc6-b6d7-e11ef0380175',
                 'timestamp': '2026-10-15T02:57:20.919Z',
                 'sourceToolAssistantUUID': 'c019d361-e3ad-4f4d-9679-b9a004899c05',
                 'userType': 'external',
                 'entrypoint': 'claude-desktop',
                 'cwd': '{cwd}',
                 'sessionId': '{session}',
                 'version': '2.1.295',
                 'gitBranch': 'develop'},
                {'parentUuid': 'd6644cdb-5943-417f-aec8-d7cad58ad4c7',
                 'isSidechain': True,
                 'agentId': 'a5bae85b261bb5846',
                 'message': {'model': 'claude-opus-5-5',
                             'id': 'msg_011Cg3GjMHQwSf1muinEN5XD',
                             'type': 'message',
                             'role': 'assistant',
                             'content': [{'type': 'tool_use',
                                          'id': 'toolu_01J3kCUwxskKbgbTPg2CZXr8',
                                          'name': 'SubagentHandback',
                                          'input': {},
                                          'caller': {'type': 'direct'}}],
                             'stop_reason': None},
                 'serverClassifierRequest': '36c58303-6b55-4a5b-9a57-2d8e8a00d8d2',
                 'apiBlockIndex': 0,
                 'requestId': 'req_011Cg3GjM1YqRBRK47wgs98w',
                 'requestedModel': 'claude-opus-5-5',
                 'type': 'assistant',
                 'uuid': '5e477208-fc30-4bd1-908a-477be2f99e11',
                 'timestamp': '2026-10-15T02:57:31.576Z',
                 'advisorModel': 'claude-opus-5-5',
                 'effort': 'medium',
                 'perTurnEffort': 'medium',
                 'userType': 'external',
                 'entrypoint': 'claude-desktop',
                 'cwd': '{cwd}',
                 'sessionId': '{session}',
                 'version': '2.1.295',
                 'gitBranch': 'develop'},
                {'parentUuid': '5e477208-fc30-4bd1-908a-477be2f99e11',
                 'isSidechain': True,
                 'promptId': '5dfe5383-4ccd-4cba-9e5a-36098c74a254',
                 'agentId': 'a5bae85b261bb5846',
                 'type': 'user',
                 'message': {'role': 'user',
                             'content': [{'tool_use_id': 'toolu_01J3kCUwxskKbgbTPg2CZXr8',
                                          'type': 'tool_result',
                                          'content': '[sanitized]'}]},
                 'uuid': '38d2ed7f-f569-47b9-b42e-3454af9aaf1b',
                 'timestamp': '2026-10-15T02:57:31.905Z',
                 'toolEndsTurn': True,
                 'sourceToolAssistantUUID': '5e477208-fc30-4bd1-908a-477be2f99e11',
                 'userType': 'external',
                 'entrypoint': 'claude-desktop',
                 'cwd': '{cwd}',
                 'sessionId': '{session}',
                 'version': '2.1.295',
                 'gitBranch': 'develop'}],
 'meta': {'agentType': 'general-purpose',
          'description': 'grill-card #1103',
          'toolUseId': 'toolu_01U6h4SuLtj2WDEvUheK1S3S',
          'spawnDepth': 1,
          'requestShape': 'foreground',
          'requestNonInteractive': True,
          'model': 'opus'}}


CLI_BACKGROUND_2_1_300 = {'session': 'bbbbbbbb-cccc-4ddd-8eee-ffffffffffff',
 'version': '2.1.300',
 'entrypoint': 'cli',
 'children': {'design-autor': {'agent_id': 'af0a1917b83c8aa19',
                               'call_id': 'toolu_0195fAbNof5A3dgYffbook44',
                               'description': 'design-autor 1103 a1',
                               'parent_rows': [{'parentUuid': '57211d39-f381-4e64-8a4f-f0f7717e575e',
                                                'isSidechain': False,
                                                'message': {'model': 'claude-opus-5-5',
                                                            'id': 'msg_011Cg4GnRqqYRjPBTnJWvWuv',
                                                            'type': 'message',
                                                            'role': 'assistant',
                                                            'content': [{'type': 'tool_use',
                                                                         'id': 'toolu_0195fAbNof5A3dgYffbook44',
                                                                         'name': 'Agent',
                                                                         'input': {'description': 'design-autor 1103 a1',
                                                                                   'subagent_type': 'general-purpose',
                                                                                   'model': 'opus',
                                                                                   'effort': 'high',
                                                                                   'prompt': '[sanitized]'},
                                                                         'caller': {'type': 'direct'}}],
                                                            'stop_reason': 'tool_use'},
                                                'apiBlockIndex': 1,
                                                'requestId': 'req_011Cg4GnRZUPzNBsouk5PVLE',
                                                'requestRef': 'fed769d9-94d3-44c9-a615-267e6908034d',
                                                'requestedModel': 'claude-opus-5-5',
                                                'type': 'assistant',
                                                'uuid': '6bdf229c-d41f-4b63-a575-6958af579896',
                                                'timestamp': '2026-10-15T15:39:04.008Z',
                                                'advisorModel': 'claude-opus-5-5',
                                                'effort': 'medium',
                                                'perTurnEffort': 'medium',
                                                'userType': 'external',
                                                'entrypoint': 'cli',
                                                'cwd': '{cwd}',
                                                'sessionId': '{session}',
                                                'version': '2.1.300',
                                                'gitBranch': 'card-1103-claude-desktop-ssh'},
                                               {'parentUuid': '6bdf229c-d41f-4b63-a575-6958af579896',
                                                'isSidechain': False,
                                                'promptId': '4beb87e5-f48e-4e04-83f8-5eb7f4fb2880',
                                                'type': 'user',
                                                'message': {'role': 'user',
                                                            'content': [{'tool_use_id': 'toolu_0195fAbNof5A3dgYffbook44',
                                                                         'type': 'tool_result',
                                                                         'content': '[sanitized]'}]},
                                                'uuid': '4382908c-6789-4829-8d0b-9afa828d98d8',
                                                'timestamp': '2026-10-15T15:39:04.674Z',
                                                'toolUseResult': {'isAsync': True,
                                                                  'status': 'async_launched',
                                                                  'agentId': 'af0a1917b83c8aa19',
                                                                  'description': 'design-autor 1103 a1',
                                                                  'resolvedModel': 'claude-opus-5-5',
                                                                  'prompt': '[sanitized]',
                                                                  'outputFile': '[sanitized]',
                                                                  'canReadOutputFile': True,
                                                                  'canContinueAgent': True},
                                                'sourceToolAssistantUUID': '6bdf229c-d41f-4b63-a575-6958af579896',
                                                'userType': 'external',
                                                'entrypoint': 'cli',
                                                'cwd': '{cwd}',
                                                'sessionId': '{session}',
                                                'version': '2.1.300',
                                                'gitBranch': 'card-1103-claude-desktop-ssh'},
                                               {'type': 'queue-operation',
                                                'operation': 'enqueue',
                                                'timestamp': '2026-10-15T15:50:53.198Z',
                                                'sessionId': '{session}',
                                                'content': '<task-notification>\n'
                                                           '<task-id>af0a1917b83c8aa19</task-id>\n'
                                                           '<tool-use-id>toolu_0195fAbNof5A3dgYffbook44</tool-use-id>\n'
                                                           '<output-file>[sanitized]</output-file>\n'
                                                           '<status>completed</status>\n'
                                                           '<summary>[sanitized]</summary>\n'
                                                           '<note>[sanitized]</note>\n'
                                                           '<result>[sanitized]</result>\n'
                                                           '<usage><subagent_tokens>0</subagent_tokens><tool_uses>0</tool_uses><duration_ms>0</duration_ms></usage>\n'
                                                           '</task-notification>'}],
                               'child_rows': [{'parentUuid': None,
                                               'isSidechain': True,
                                               'promptId': '4beb87e5-f48e-4e04-83f8-5eb7f4fb2880',
                                               'agentId': 'af0a1917b83c8aa19',
                                               'type': 'user',
                                               'message': {'role': 'user', 'content': '[sanitized]'},
                                               'uuid': '81759e3b-a9ec-4186-8dd2-0dfa3db2e78a',
                                               'timestamp': '2026-10-15T15:39:04.387Z',
                                               'userType': 'external',
                                               'entrypoint': 'cli',
                                               'cwd': '{cwd}',
                                               'sessionId': '{session}',
                                               'version': '2.1.300',
                                               'gitBranch': 'card-1103-claude-desktop-ssh'},
                                              {'parentUuid': '8d486e13-1732-46b7-bdcd-db510ffe34ff',
                                               'isSidechain': True,
                                               'agentId': 'af0a1917b83c8aa19',
                                               'message': {'model': 'claude-opus-5-5',
                                                           'id': 'msg_011Cg4GpPSXfJ75TrkaihjJo',
                                                           'type': 'message',
                                                           'role': 'assistant',
                                                           'content': [{'type': 'thinking',
                                                                        'thinking': '[sanitized]',
                                                                        'signature': '[sanitized]'}],
                                                           'stop_reason': None},
                                               'thinkingDurationMs': 537,
                                               'thinkingDisplay': '[sanitized]',
                                               'apiBlockIndex': 0,
                                               'requestId': 'req_011Cg4GpPDPaAwdUeH2CZdEG',
                                               'requestRef': '09b61302-334c-4efc-9c9b-e04894ceb505',
                                               'requestedModel': 'claude-opus-5-5',
                                               'type': 'assistant',
                                               'uuid': '16d9777b-974d-400b-88c2-b7efdd4573ae',
                                               'timestamp': '2026-10-15T15:39:06.166Z',
                                               'advisorModel': 'claude-opus-5-5',
                                               'effort': 'high',
                                               'perTurnEffort': 'high',
                                               'userType': 'external',
                                               'entrypoint': 'cli',
                                               'cwd': '{cwd}',
                                               'sessionId': '{session}',
                                               'version': '2.1.300',
                                               'gitBranch': 'card-1103-claude-desktop-ssh'},
                                              {'parentUuid': '16d9777b-974d-400b-88c2-b7efdd4573ae',
                                               'isSidechain': True,
                                               'agentId': 'af0a1917b83c8aa19',
                                               'message': {'model': 'claude-opus-5-5',
                                                           'id': 'msg_011Cg4GpPSXfJ75TrkaihjJo',
                                                           'type': 'message',
                                                           'role': 'assistant',
                                                           'content': [{'type': 'tool_use',
                                                                        'id': 'toolu_01LVa3S2myLfWjg3ZREtYtH9',
                                                                        'name': 'Bash',
                                                                        'input': {'command': '[sanitized]'},
                                                                        'caller': {'type': 'direct'}}],
                                                           'stop_reason': 'tool_use'},
                                               'wireIngestContext': {'toolu_01LVa3S2myLfWjg3ZREtYtH9': {'cwd': '{cwd}'}},
                                               'apiBlockIndex': 1,
                                               'requestId': 'req_011Cg4GpPDPaAwdUeH2CZdEG',
                                               'requestRef': '09b61302-334c-4efc-9c9b-e04894ceb505',
                                               'requestedModel': 'claude-opus-5-5',
                                               'type': 'assistant',
                                               'uuid': 'dced4a30-3fb7-4a35-878f-8cd3976aeb60',
                                               'timestamp': '2026-10-15T15:39:08.308Z',
                                               'advisorModel': 'claude-opus-5-5',
                                               'effort': 'high',
                                               'perTurnEffort': 'high',
                                               'userType': 'external',
                                               'entrypoint': 'cli',
                                               'cwd': '{cwd}',
                                               'sessionId': '{session}',
                                               'version': '2.1.300',
                                               'gitBranch': 'card-1103-claude-desktop-ssh'},
                                              {'parentUuid': '0e6076d9-2e0b-42e6-844f-4c4a6a053652',
                                               'isSidechain': True,
                                               'agentId': 'af0a1917b83c8aa19',
                                               'message': {'model': 'claude-opus-5-5',
                                                           'id': 'msg_011Cg4GpkdVrZRAStd2qFKWE',
                                                           'type': 'message',
                                                           'role': 'assistant',
                                                           'content': [{'type': 'tool_use',
                                                                        'id': 'toolu_01FSzw7zY979wFBFG9zhu68N',
                                                                        'name': 'Bash',
                                                                        'input': {'command': '[sanitized]'},
                                                                        'caller': {'type': 'direct'}}],
                                                           'stop_reason': 'tool_use'},
                                               'apiBlockIndex': 0,
                                               'requestId': 'req_011Cg4GpkKeh3hePJyRH5HL2',
                                               'requestRef': '1e525c20-d782-4fc1-a412-cc4b7251e539',
                                               'requestedModel': 'claude-opus-5-5',
                                               'type': 'assistant',
                                               'uuid': 'c92763c8-f1fa-40b3-9be7-269a0b2b2dd8',
                                               'timestamp': '2026-10-15T15:39:12.519Z',
                                               'advisorModel': 'claude-opus-5-5',
                                               'effort': 'high',
                                               'perTurnEffort': 'high',
                                               'userType': 'external',
                                               'entrypoint': 'cli',
                                               'cwd': '{cwd}',
                                               'sessionId': '{session}',
                                               'version': '2.1.300',
                                               'gitBranch': 'card-1103-claude-desktop-ssh'},
                                              {'parentUuid': '65baa800-d4ce-410c-b2fc-3cea67ff3042',
                                               'isSidechain': True,
                                               'agentId': 'af0a1917b83c8aa19',
                                               'message': {'model': 'claude-opus-5-5',
                                                           'id': 'msg_011Cg4HgvRVyCNNF77xELkaq',
                                                           'type': 'message',
                                                           'role': 'assistant',
                                                           'content': [{'type': 'text', 'text': '[sanitized]'}],
                                                           'stop_reason': 'end_turn'},
                                               'apiBlockIndex': 1,
                                               'requestId': 'req_011Cg4Hgv7ADf2A1dwnggLHA',
                                               'requestRef': '9b3ec40c-9ecc-467a-9db1-5436390e2680',
                                               'requestedModel': 'claude-opus-5-5',
                                               'type': 'assistant',
                                               'uuid': 'adc80e1a-8b3f-47ba-bfa6-ea469130bbf4',
                                               'timestamp': '2026-10-15T15:50:52.772Z',
                                               'advisorModel': 'claude-opus-5-5',
                                               'effort': 'high',
                                               'perTurnEffort': 'high',
                                               'userType': 'external',
                                               'entrypoint': 'cli',
                                               'cwd': '{cwd}',
                                               'sessionId': '{session}',
                                               'version': '2.1.300',
                                               'gitBranch': 'card-1103-claude-desktop-ssh'}],
                               'meta': {'agentType': 'general-purpose',
                                        'description': 'design-autor 1103 a1',
                                        'toolUseId': 'toolu_0195fAbNof5A3dgYffbook44',
                                        'spawnDepth': 1,
                                        'requestShape': 'background',
                                        'requestNonInteractive': True,
                                        'model': 'opus',
                                        'effort': 'high'}},
              'design-critic': {'agent_id': 'aacea23e2dfb0ccf9',
                                'call_id': 'toolu_018wA7TQWudd7GjSsvruTnc5',
                                'description': 'design-critic 1103 c1',
                                'parent_rows': [{'parentUuid': 'a721c946-42ab-455b-b46f-776ec76aa35e',
                                                 'isSidechain': False,
                                                 'message': {'model': 'claude-opus-5-5',
                                                             'id': 'msg_011Cg4Hn3ak4fAVg67Bfcf4J',
                                                             'type': 'message',
                                                             'role': 'assistant',
                                                             'content': [{'type': 'tool_use',
                                                                          'id': 'toolu_018wA7TQWudd7GjSsvruTnc5',
                                                                          'name': 'Agent',
                                                                          'input': {'description': 'design-critic 1103 c1',
                                                                                    'subagent_type': 'general-purpose',
                                                                                    'model': 'opus',
                                                                                    'effort': 'high',
                                                                                    'prompt': '[sanitized]'},
                                                                          'caller': {'type': 'direct'}}],
                                                             'stop_reason': 'tool_use'},
                                                 'apiBlockIndex': 1,
                                                 'requestId': 'req_011Cg4Hn3FuZRLK48jaGCBSz',
                                                 'requestRef': '301f7137-bcac-4455-b802-136c78b17cf5',
                                                 'requestedModel': 'claude-opus-5-5',
                                                 'type': 'assistant',
                                                 'uuid': 'dba1e440-9333-488e-8487-7fe31047d046',
                                                 'timestamp': '2026-10-15T15:52:01.007Z',
                                                 'advisorModel': 'claude-opus-5-5',
                                                 'effort': 'medium',
                                                 'perTurnEffort': 'medium',
                                                 'userType': 'external',
                                                 'entrypoint': 'cli',
                                                 'cwd': '{cwd}',
                                                 'sessionId': '{session}',
                                                 'version': '2.1.300',
                                                 'gitBranch': 'card-1103-claude-desktop-ssh'},
                                                {'parentUuid': 'dba1e440-9333-488e-8487-7fe31047d046',
                                                 'isSidechain': False,
                                                 'promptId': '8bb44c33-020e-47ba-a658-14e8f24e61c2',
                                                 'type': 'user',
                                                 'message': {'role': 'user',
                                                             'content': [{'tool_use_id': 'toolu_018wA7TQWudd7GjSsvruTnc5',
                                                                          'type': 'tool_result',
                                                                          'content': '[sanitized]'}]},
                                                 'uuid': 'e88c1d98-4869-4cfc-ad82-322c7eccfe49',
                                                 'timestamp': '2026-10-15T15:52:01.664Z',
                                                 'toolUseResult': {'isAsync': True,
                                                                   'status': 'async_launched',
                                                                   'agentId': 'aacea23e2dfb0ccf9',
                                                                   'description': 'design-critic 1103 c1',
                                                                   'resolvedModel': 'claude-opus-5-5',
                                                                   'prompt': '[sanitized]',
                                                                   'outputFile': '[sanitized]',
                                                                   'canReadOutputFile': True,
                                                                   'canContinueAgent': True},
                                                 'sourceToolAssistantUUID': 'dba1e440-9333-488e-8487-7fe31047d046',
                                                 'userType': 'external',
                                                 'entrypoint': 'cli',
                                                 'cwd': '{cwd}',
                                                 'sessionId': '{session}',
                                                 'version': '2.1.300',
                                                 'gitBranch': 'card-1103-claude-desktop-ssh'},
                                                {'type': 'queue-operation',
                                                 'operation': 'enqueue',
                                                 'timestamp': '2026-10-15T15:55:14.025Z',
                                                 'sessionId': '{session}',
                                                 'content': '<task-notification>\n'
                                                            '<task-id>aacea23e2dfb0ccf9</task-id>\n'
                                                            '<tool-use-id>toolu_018wA7TQWudd7GjSsvruTnc5</tool-use-id>\n'
                                                            '<output-file>[sanitized]</output-file>\n'
                                                            '<status>completed</status>\n'
                                                            '<summary>[sanitized]</summary>\n'
                                                            '<note>[sanitized]</note>\n'
                                                            '<result>[sanitized]</result>\n'
                                                            '<usage><subagent_tokens>0</subagent_tokens><tool_uses>0</tool_uses><duration_ms>0</duration_ms></usage>\n'
                                                            '</task-notification>'}],
                                'child_rows': [{'parentUuid': None,
                                                'isSidechain': True,
                                                'promptId': '8bb44c33-020e-47ba-a658-14e8f24e61c2',
                                                'agentId': 'aacea23e2dfb0ccf9',
                                                'type': 'user',
                                                'message': {'role': 'user', 'content': '[sanitized]'},
                                                'uuid': '852b5e3e-72fa-48f1-bac3-782423f79ec2',
                                                'timestamp': '2026-10-15T15:52:01.381Z',
                                                'userType': 'external',
                                                'entrypoint': 'cli',
                                                'cwd': '{cwd}',
                                                'sessionId': '{session}',
                                                'version': '2.1.300',
                                                'gitBranch': 'card-1103-claude-desktop-ssh'},
                                               {'parentUuid': 'd9afdd53-0a7e-4d5d-ae5e-6104d4dedb36',
                                                'isSidechain': True,
                                                'agentId': 'aacea23e2dfb0ccf9',
                                                'message': {'model': 'claude-opus-5-5',
                                                            'id': 'msg_011Cg4Hodn5nS11wZ5dtUTcj',
                                                            'type': 'message',
                                                            'role': 'assistant',
                                                            'content': [{'type': 'thinking',
                                                                         'thinking': '[sanitized]',
                                                                         'signature': '[sanitized]'}],
                                                            'stop_reason': None},
                                                'thinkingDurationMs': 585,
                                                'thinkingDisplay': '[sanitized]',
                                                'apiBlockIndex': 0,
                                                'requestId': 'req_011Cg4HodANeaYu3EzwaBEJx',
                                                'requestRef': 'd6f5c20f-fac4-4772-96b9-ecce3b8156c9',
                                                'requestedModel': 'claude-opus-5-5',
                                                'type': 'assistant',
                                                'uuid': '8f38340e-9439-4637-8916-9f533e00d3f2',
                                                'timestamp': '2026-10-15T15:52:02.828Z',
                                                'advisorModel': 'claude-opus-5-5',
                                                'effort': 'high',
                                                'perTurnEffort': 'high',
                                                'userType': 'external',
                                                'entrypoint': 'cli',
                                                'cwd': '{cwd}',
                                                'sessionId': '{session}',
                                                'version': '2.1.300',
                                                'gitBranch': 'card-1103-claude-desktop-ssh'},
                                               {'parentUuid': '8f38340e-9439-4637-8916-9f533e00d3f2',
                                                'isSidechain': True,
                                                'agentId': 'aacea23e2dfb0ccf9',
                                                'message': {'model': 'claude-opus-5-5',
                                                            'id': 'msg_011Cg4Hodn5nS11wZ5dtUTcj',
                                                            'type': 'message',
                                                            'role': 'assistant',
                                                            'content': [{'type': 'tool_use',
                                                                         'id': 'toolu_013EHiCQwSL3SHvp49kNKRM8',
                                                                         'name': 'Bash',
                                                                         'input': {'command': '[sanitized]'},
                                                                         'caller': {'type': 'direct'}}],
                                                            'stop_reason': 'tool_use'},
                                                'wireIngestContext': {'toolu_013EHiCQwSL3SHvp49kNKRM8': {'cwd': '{cwd}'}},
                                                'apiBlockIndex': 1,
                                                'requestId': 'req_011Cg4HodANeaYu3EzwaBEJx',
                                                'requestRef': 'd6f5c20f-fac4-4772-96b9-ecce3b8156c9',
                                                'requestedModel': 'claude-opus-5-5',
                                                'type': 'assistant',
                                                'uuid': '9af5467f-52b1-428a-8a0d-bc015e4945f5',
                                                'timestamp': '2026-10-15T15:52:03.932Z',
                                                'advisorModel': 'claude-opus-5-5',
                                                'effort': 'high',
                                                'perTurnEffort': 'high',
                                                'userType': 'external',
                                                'entrypoint': 'cli',
                                                'cwd': '{cwd}',
                                                'sessionId': '{session}',
                                                'version': '2.1.300',
                                                'gitBranch': 'card-1103-claude-desktop-ssh'},
                                               {'parentUuid': '28707936-2c69-4d4f-aa26-246eca3189e2',
                                                'isSidechain': True,
                                                'agentId': 'aacea23e2dfb0ccf9',
                                                'message': {'model': 'claude-opus-5-5',
                                                            'id': 'msg_011Cg4HorSaT4usd2cvbEHFz',
                                                            'type': 'message',
                                                            'role': 'assistant',
                                                            'content': [{'type': 'tool_use',
                                                                         'id': 'toolu_0176n9fBFVEyXkREERzxwdky',
                                                                         'name': 'Bash',
                                                                         'input': {'command': '[sanitized]'},
                                                                         'caller': {'type': 'direct'}}],
                                                            'stop_reason': None},
                                                'wireIngestContext': {'toolu_0176n9fBFVEyXkREERzxwdky': {'cwd': '{cwd}'}},
                                                'apiBlockIndex': 0,
                                                'requestId': 'req_011Cg4HorBCnhu1EAdsxfPj3',
                                                'requestRef': '867638aa-cc8f-4d1e-87fe-67d674003ece',
                                                'requestedModel': 'claude-opus-5-5',
                                                'type': 'assistant',
                                                'uuid': 'ffda4a58-78a4-4b6e-9398-3d10f4e1e470',
                                                'timestamp': '2026-10-15T15:52:07.080Z',
                                                'advisorModel': 'claude-opus-5-5',
                                                'effort': 'high',
                                                'perTurnEffort': 'high',
                                                'userType': 'external',
                                                'entrypoint': 'cli',
                                                'cwd': '{cwd}',
                                                'sessionId': '{session}',
                                                'version': '2.1.300',
                                                'gitBranch': 'card-1103-claude-desktop-ssh'},
                                               {'parentUuid': '1f773991-6c7b-4e7a-ac01-d9497a75b994',
                                                'isSidechain': True,
                                                'agentId': 'aacea23e2dfb0ccf9',
                                                'message': {'model': 'claude-opus-5-5',
                                                            'id': 'msg_011Cg4J2FBtfhuazCBXvAcTK',
                                                            'type': 'message',
                                                            'role': 'assistant',
                                                            'content': [{'type': 'text', 'text': '[sanitized]'}],
                                                            'stop_reason': 'end_turn'},
                                                'apiBlockIndex': 0,
                                                'requestId': 'req_011Cg4J2Eu2iNdWsnyL5DQWW',
                                                'requestRef': '91f1513c-287d-420f-b47f-0fbe088d6a8c',
                                                'requestedModel': 'claude-opus-5-5',
                                                'type': 'assistant',
                                                'uuid': 'e7644b1a-c719-422d-976d-0b6a9d8a2d0e',
                                                'timestamp': '2026-10-15T15:55:13.743Z',
                                                'advisorModel': 'claude-opus-5-5',
                                                'effort': 'high',
                                                'perTurnEffort': 'high',
                                                'userType': 'external',
                                                'entrypoint': 'cli',
                                                'cwd': '{cwd}',
                                                'sessionId': '{session}',
                                                'version': '2.1.300',
                                                'gitBranch': 'card-1103-claude-desktop-ssh'}],
                                'meta': {'agentType': 'general-purpose',
                                         'description': 'design-critic 1103 c1',
                                         'toolUseId': 'toolu_018wA7TQWudd7GjSsvruTnc5',
                                         'spawnDepth': 1,
                                         'requestShape': 'background',
                                         'requestNonInteractive': True,
                                         'model': 'opus',
                                         'effort': 'high'}}}}


def _fill(value, cwd: Path, session: str = SESSION):
    if isinstance(value, dict):
        return {k: _fill(v, cwd, session) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, cwd, session) for v in value]
    if value == "{cwd}":
        return str(cwd)
    if value == "{session}":
        return session
    return value


class RealWorld(World):
    """A `World` whose spawn, return and child transcript are the real, sanitized records above.

    `launch` replays a fixture child after the birth receipt exists, exactly where the host wrote it. Nothing but the
    parameters named in its arguments is altered.
    """

    def __init__(self, tmp_path: Path, *, fixture: dict, name: str = "card-1103-test"):
        super().__init__(tmp_path, name=name, version=fixture["version"], entrypoint=fixture["entrypoint"])
        self.fixture = fixture
        self.env = {**self.env, "CLAUDECODE": "1"}
        if fixture.get("desktop_app_version"):
            self.env["CLAUDE_CODE_DESKTOP_APP_VERSION"] = fixture["desktop_app_version"]

    def capture(self, role="apply-coluna", *, effort=None):
        import model_selection
        import yaml

        effort = effort or self.fixture.get("effort_override")
        if effort is not None:  # the real app child ran at `medium`: the selection under test says so
            path = model_selection.selection_path()
            document = yaml.safe_load(path.read_text())
            for band in ("juizo", "execucao"):
                document["clients"]["claude"][band]["effort"] = effort
            path.write_text(yaml.safe_dump(document, sort_keys=False))
        return super().capture(role)

    def prepare(self, role="apply-coluna", task=None, **kw):
        task = task or self.fixture.get("description")
        return super().prepare(role, task, **kw)

    def _write_child(self, agent, child_rows, meta):
        self.subdir.mkdir(parents=True, exist_ok=True)
        (self.subdir / f"agent-{agent}.meta.json").write_text(json.dumps(meta))
        write_jsonl(self.subdir / f"agent-{agent}.jsonl", _fill(child_rows, self.repo))

    def launch(self, parent_rows, child_rows, meta, agent, *, effort=None, mutate=None):
        """Append the parent's records after the birth, then write the child transcript and its meta file."""

        rows = _fill(json.loads(json.dumps(parent_rows)), self.repo)
        if effort is not None:  # the one field the policy requires and the app did not send: added, nothing else
            for row in rows:
                for block in (row.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("name") == "Agent":
                        block["input"]["effort"] = effort
        if mutate is not None:
            mutate(rows)
        self.rows.extend(rows)
        self._write_child(agent, child_rows, meta)
        self.flush()

    # --- the desktop app session
    def app_before_spawn(self):
        """Parent records that precede the spawn in the real app session (the birth receipt is prepared after them)."""

        fixture = self.fixture
        self.rows = _fill(fixture["parent_rows"][:4], self.repo)
        self.flush()

    def launch_app_child(self, *, effort=None, mutate=None):
        fixture = self.fixture
        self.launch(fixture["parent_rows"][4:], fixture["child_rows"], fixture["meta"], fixture["agent_id"], effort=effort, mutate=mutate)

    # --- a child of the terminal session that went to the background
    def launch_background_child(self, name, *, mutate=None):
        child = self.fixture["children"][name]
        self.launch(child["parent_rows"], child["child_rows"], child["meta"], child["agent_id"], mutate=mutate)
        return child


def app_world(tmp_path: Path) -> "RealWorld":
    """The desktop app session, with its parent records up to (not including) the spawn already in the transcript."""

    world = RealWorld(tmp_path, fixture=dict(APP_SESSION_2_1_295, effort_override="medium"))
    world.app_before_spawn()
    return world


def background_world(tmp_path: Path, name: str) -> "RealWorld":
    child = CLI_BACKGROUND_2_1_300["children"][name]
    return RealWorld(tmp_path, fixture=dict(CLI_BACKGROUND_2_1_300, description=child["description"]))
