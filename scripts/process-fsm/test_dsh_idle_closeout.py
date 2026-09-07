from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from paging import page  # noqa: E402
from test_dsh_adapter import PLUGIN_GUARD, PLUGIN_LIB, PATCH, _node  # noqa: E402
from test_dsh_spawn_isolado import _append_inner_ctx_prelude  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

ROOT_SESSION = "session-root-858"
CHILD_SESSION = "session-child-858"
EMPTY_FAILURE = {"message": "EMPTY_RESPONSE", "code": "EMPTY_RESPONSE"}
THIS_CLASS_FAILURE = {
    "message": '"reasoning.effort" does not support "none"',
    "code": "INVALID_REQUEST",
    "status": 400,
}
WAIT_CAP_MS = 2_400_000
GUARD_PY = ROOT / "guard.py"
SKILL = REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md"
FSM_YAML = REPO / ".cursor" / "process-fsm.yaml"


def _node_ok(code: str) -> dict:
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return json.loads(proc.stdout)


def _resolve(bound: str, git: str) -> object:
    def inner(cwd, path, issue_id=None, status=None):
        return {"q": None, "bound_card": bound, "q_git": git}

    return inner


def test_w1_execute_loops_until_terminal() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const waits = [];
const reads = [];
host.jobs = {{
  async wait(id, timeoutMs, caller, signal) {{
    waits.push({{ id, timeoutMs }});
    if (waits.length === 1) return {{ id, status: "running" }};
    return {{ id, status: "completed", finishedAt: Date.now() }};
  }},
  read(id, caller) {{
    reads.push({{ id }});
    return {{
      text: "qa-gate FAIL\\n",
      snapshot: {{ id, status: "completed", detail: "exit code: 1" }},
    }};
  }},
  list() {{ return [{{ id: "job-1", status: "running" }}]; }},
}};
apply(host);
let nextReturnedRunning = false;
const result = await host.events["tools/execute"](
  {{
    name: "job_output",
    arguments: {{ job_id: "job-1", wait: true, timeout_ms: {WAIT_CAP_MS} }},
    agent: rootAgent({json.dumps(ROOT_SESSION)}),
  }},
  async () => {{
    const snap = await host.jobs.wait("job-1", 30000, rootAgent({json.dumps(ROOT_SESSION)}));
    nextReturnedRunning = snap.status === "running";
    return {{
      content: [{{ type: "text", text: `running gh pr checks\\n[status: ${{snap.status}}]` }}],
      value: {{ text: "running gh pr checks\\n", job: snap }},
    }};
  }},
);
const blob = typeof result.content === "string"
  ? result.content
  : Array.isArray(result.content)
    ? result.content.map((b) => (b && b.text) || "").join("\\n")
    : JSON.stringify(result);
process.stdout.write(JSON.stringify({{
  waitCount: waits.length,
  readCount: reads.length,
  nextReturnedRunning,
  result,
  blob,
  firstTimeout: waits[0] && waits[0].timeoutMs,
}}));
"""
    data = _node_ok(code)
    assert data["nextReturnedRunning"] is True
    assert data["waitCount"] >= 2
    blob = json.dumps(data["result"]) + data["blob"]
    assert "completed" in blob
    assert "[status: running]" not in data["blob"] or "completed" in blob
    status = (
        (((data["result"] or {}).get("value") or {}).get("job") or {}).get("status")
    )
    assert status == "completed"
    # Rest of stream after the host's consuming wait+read MUST appear.
    assert "qa-gate FAIL" in blob
    assert "running gh pr checks" in blob
    assert "exit code: 1" in blob
    assert "[status: completed, exit code: 1]" in blob
    job = ((data["result"] or {}).get("value") or {}).get("job") or {}
    assert job.get("detail") == "exit code: 1"
    value_text = ((data["result"] or {}).get("value") or {}).get("text") or ""
    assert "running gh pr checks" in value_text
    assert "qa-gate FAIL" in value_text
    # status==completed without the log / detail line MUST fail W1.
    assert not (status == "completed" and "qa-gate FAIL" not in blob)
    assert not (
        status == "completed" and "[status: completed, exit code: 1]" not in blob
    )
    # A single host wait of 30s/10min that returns running MUST fail W1.
    assert not (data["waitCount"] == 1 and data["firstTimeout"] in (30000, 600000))


def test_w1_read_throw_fail_open_keeps_snapshot_detail() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const waits = [];
host.jobs = {{
  async wait(id, timeoutMs) {{
    waits.push({{ id, timeoutMs }});
    if (waits.length === 1) return {{ id, status: "running" }};
    return {{ id, status: "completed", detail: "exit code: 1", finishedAt: Date.now() }};
  }},
  read() {{ throw new Error("read unavailable"); }},
  list() {{ return [{{ id: "job-1", status: "running" }}]; }},
}};
apply(host);
const result = await host.events["tools/execute"](
  {{
    name: "job_output",
    arguments: {{ job_id: "job-1", wait: true, timeout_ms: {WAIT_CAP_MS} }},
    agent: rootAgent({json.dumps(ROOT_SESSION)}),
  }},
  async () => {{
    const snap = await host.jobs.wait("job-1", 30000);
    return {{
      content: `running gh pr checks\\n[status: ${{snap.status}}]`,
      value: {{ text: "running gh pr checks\\n", job: snap }},
    }};
  }},
);
process.stdout.write(JSON.stringify({{ result, waitCount: waits.length }}));
"""
    data = _node_ok(code)
    assert data["waitCount"] >= 2
    blob = json.dumps(data["result"])
    assert "running gh pr checks" in blob
    assert "qa-gate FAIL" not in blob
    assert "[status: completed, exit code: 1]" in blob
    job = ((data["result"] or {}).get("value") or {}).get("job") or {}
    assert job.get("status") == "completed"
    assert job.get("detail") == "exit code: 1"


def test_w1_read_absent_fail_open_keeps_snapshot_detail() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const waits = [];
host.jobs = {{
  async wait(id, timeoutMs) {{
    waits.push({{ id, timeoutMs }});
    if (waits.length === 1) return {{ id, status: "running" }};
    return {{ id, status: "completed", detail: "exit code: 1" }};
  }},
  list() {{ return [{{ id: "job-1", status: "running" }}]; }},
}};
apply(host);
const result = await host.events["tools/execute"](
  {{
    name: "job_output",
    arguments: {{ job_id: "job-1", wait: true, timeout_ms: {WAIT_CAP_MS} }},
    agent: rootAgent({json.dumps(ROOT_SESSION)}),
  }},
  async () => {{
    const snap = await host.jobs.wait("job-1", 30000);
    return {{
      content: `running gh pr checks\\n[status: ${{snap.status}}]`,
      value: {{ text: "running gh pr checks\\n", job: snap }},
    }};
  }},
);
process.stdout.write(JSON.stringify({{ result, waitCount: waits.length }}));
"""
    data = _node_ok(code)
    assert data["waitCount"] >= 2
    blob = json.dumps(data["result"])
    assert "running gh pr checks" in blob
    assert "[status: completed, exit code: 1]" in blob
    job = ((data["result"] or {}).get("value") or {}).get("job") or {}
    assert job.get("detail") == "exit code: 1"


def test_w2_turn_stopping_global_steers_pending_jobs() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const child = mockAppendInnerCtx(registry, "child");
const notices = [];
const root = {{
  id: {json.dumps(ROOT_SESSION)},
  status: "running",
  session: {{ id: {json.dumps(ROOT_SESSION)}, header: {{ id: {json.dumps(ROOT_SESSION)}, delegationDepth: 0 }} }},
  steer(msg) {{ notices.push({{ via: "steer", msg }}); }},
  inject(msg) {{ notices.push({{ via: "inject", msg }}); }},
  followup(msg) {{ notices.push({{ via: "followup", msg }}); }},
}};
registry.agents.set({json.dumps(ROOT_SESSION)}, root);
host.jobs = {{
  list(agent) {{ return [{{ id: "job-1", status: "running" }}]; }},
  async wait() {{ return {{ id: "job-1", status: "running" }}; }},
}};
apply(host);
await child.events["agent/turn-stopping"]({{ agent: root, turn: 3, signal: {{}} }});
const stoppingHooks = (registry.hooks["agent/turn-stopping"] || []).map((h) => ({{
  global: !!h.global,
  scopeKey: h.scopeKey === undefined ? null : h.scopeKey,
}}));
const noGlobalNotices = [];
{{
  const isolated = createScopeRegistry();
  const hostB = mockAppendInnerCtx(isolated, "host");
  const childB = mockAppendInnerCtx(isolated, "child");
  const agentB = {{
    id: {json.dumps(ROOT_SESSION)},
    status: "running",
    steer(msg) {{ noGlobalNotices.push({{ via: "steer", msg }}); }},
    inject(msg) {{ noGlobalNotices.push({{ via: "inject", msg }}); }},
  }};
  isolated.agents.set({json.dumps(ROOT_SESSION)}, agentB);
  hostB.jobs = {{ list() {{ return [{{ id: "job-1", status: "running" }}]; }} }};
  hostB.on("agent/turn-stopping", (payload) => {{
    noGlobalNotices.push({{ via: "host-nonglobal" }});
    if (payload && payload.agent && typeof payload.agent.inject === "function") {{
      payload.agent.inject({{ content: "inject-only" }});
    }}
  }});
  await childB.events["agent/turn-stopping"]({{ agent: agentB, turn: 1, signal: {{}} }});
}}
process.stdout.write(JSON.stringify({{ notices, stoppingHooks, noGlobalNotices }}));
"""
    data = _node_ok(code)
    assert any(h["global"] is True for h in data["stoppingHooks"])
    assert data["notices"], "turn-stopping with pending jobs must steer"
    assert any(n["via"] == "steer" for n in data["notices"])
    assert not any(n["via"] == "inject" for n in data["notices"])
    msg = data["notices"][0]["msg"]
    assert msg["source"]["kind"] == "plugin"
    assert msg["source"]["plugin"] == "covenant-flow-process-fsm-guard"
    assert msg["source"]["form"] == "notice"
    assert len(msg["source"]["summary"]) <= 120
    blob = json.dumps(msg)
    assert "job_output" in blob
    assert "wait" in blob
    assert data["noGlobalNotices"] == []


def test_w3_turn_stopping_without_pending_does_not_steer() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const child = mockAppendInnerCtx(registry, "child");
const notices = [];
const root = {{
  id: {json.dumps(ROOT_SESSION)},
  status: "idle",
  session: {{ id: {json.dumps(ROOT_SESSION)}, header: {{ id: {json.dumps(ROOT_SESSION)}, delegationDepth: 0 }} }},
  steer(msg) {{ notices.push({{ via: "steer", msg }}); }},
  inject(msg) {{ notices.push({{ via: "inject", msg }}); }},
}};
registry.agents.set({json.dumps(ROOT_SESSION)}, root);
host.jobs = {{
  list() {{ return [{{ id: "job-done", status: "completed" }}]; }},
}};
apply(host);
await child.events["agent/turn-stopping"]({{ agent: root, turn: 4, signal: {{}} }});
process.stdout.write(JSON.stringify({{ notices }}));
"""
    data = _node_ok(code)
    assert data["notices"] == []


def test_w4_wait_without_timeout_rewritten_to_cap() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
apply(host);
const args = {{ job_id: "job-1", wait: true }};
let nextCalled = false;
const result = await host.events["tools/pre-execute"](
  {{ name: "job_output", arguments: args, agent: rootAgent({json.dumps(ROOT_SESSION)}) }},
  async () => {{ nextCalled = true; return {{ kind: "allow" }}; }},
);
const over = {{ job_id: "job-2", wait: true, timeout_ms: 3600000 }};
await host.events["tools/pre-execute"](
  {{ name: "job_output", arguments: over, agent: rootAgent({json.dumps(ROOT_SESSION)}) }},
  async () => ({{ kind: "allow" }}),
);
process.stdout.write(JSON.stringify({{ args, over, nextCalled, result }}));
"""
    data = _node_ok(code)
    assert data["nextCalled"] is True
    assert data["args"]["timeout_ms"] == WAIT_CAP_MS
    assert data["args"]["timeout_ms"] != 30000
    assert data["over"]["timeout_ms"] == WAIT_CAP_MS


def test_w5_w6_dead_turn_retries_once_then_next() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply, inject }} from {json.dumps(str(PLUGIN_GUARD))};
import {{ isDeadTurnFailure, isReasoningEffortRejection }} from {json.dumps(str(PLUGIN_LIB))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const child = mockAppendInnerCtx(registry, "child");
apply(host);
await child.events["agent/created"]({{ agent: {{ ctx: child }} }});
const payload = {{
  agent: childAgent({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}),
  turn: 1,
  step: 0,
  failure: {json.dumps(EMPTY_FAILURE)},
}};
let firstNext = false;
const first = await child.events["agent/request-error"](
  payload,
  async () => {{ firstNext = true; return {{ kind: "continue" }}; }},
);
let secondNext = false;
const second = await child.events["agent/request-error"](
  payload,
  async () => {{ secondNext = true; return {{ kind: "continue" }}; }},
);
let thirdNext = false;
const third = await child.events["agent/request-error"](
  payload,
  async () => {{ thirdNext = true; return {{ kind: "continue" }}; }},
);
let hostFirstNext = false;
const hostFirst = await host.events["agent/request-error"](
  {{
    agent: rootAgent({json.dumps(ROOT_SESSION)}),
    failure: {json.dumps(EMPTY_FAILURE)},
  }},
  async () => {{ hostFirstNext = true; return {{ kind: "continue" }}; }},
);
let hostSecondNext = false;
const hostSecond = await host.events["agent/request-error"](
  {{
    agent: rootAgent({json.dumps(ROOT_SESSION)}),
    failure: {json.dumps(EMPTY_FAILURE)},
  }},
  async () => {{ hostSecondNext = true; return {{ kind: "continue" }}; }},
);
process.stdout.write(JSON.stringify({{
  inject,
  first,
  firstNext,
  second,
  secondNext,
  third,
  thirdNext,
  hostFirst,
  hostFirstNext,
  hostSecond,
  hostSecondNext,
  emptyIsDead: isDeadTurnFailure({json.dumps(EMPTY_FAILURE)}),
  emptyIsEffort: isReasoningEffortRejection({json.dumps(EMPTY_FAILURE)}),
  effortIsDead: isDeadTurnFailure({json.dumps(THIS_CLASS_FAILURE)}),
  quotaIsDead: isDeadTurnFailure({{ message: "usage-limit exceeded" }}),
  missingIsDead: isDeadTurnFailure({{ message: "session missing", code: "SESSION_NOT_FOUND" }}),
  emptyContentIsDead: isDeadTurnFailure({{ content: [] }}),
}}));
"""
    data = _node_ok(code)
    assert data["first"] == {"kind": "retry"}
    assert data["firstNext"] is False
    assert data["secondNext"] is True
    assert data["second"] != {"kind": "retry"}
    assert data["thirdNext"] is True
    assert data["third"] != {"kind": "retry"}
    assert data["hostFirst"] == {"kind": "retry"}
    assert data["hostFirstNext"] is False
    assert data["hostSecondNext"] is True
    assert data["hostSecond"] != {"kind": "retry"}
    assert data["emptyIsDead"] is True
    assert data["emptyIsEffort"] is False
    assert data["effortIsDead"] is False
    assert data["quotaIsDead"] is True
    assert data["missingIsDead"] is True
    assert data["emptyContentIsDead"] is True
    assert "systemPrompt" in data["inject"]
    assert "skills" in data["inject"]
    assert "jobs" in data["inject"]


def test_w7_patch_wait_cap_without_wake_budget_or_t0() -> None:
    patch_text = PATCH.read_text(encoding="utf-8")
    assert "- id: tool-jobs" in patch_text
    assert "maxWaitTimeoutMs: 2400000" in patch_text or "maxWaitTimeoutMs: 2_400_000" in patch_text
    assert "maxConsecutiveWakes" not in patch_text
    assert "insert:" in patch_text
    assert "covenant-flow-process-fsm-guard" in patch_text
    loaded = list(yaml.safe_load_all(patch_text))
    assert loaded, "patch yaml must parse"
    rows = loaded[0] if isinstance(loaded[0], list) else loaded
    tool_jobs = [row for row in rows if isinstance(row, dict) and row.get("id") == "tool-jobs"]
    assert tool_jobs, "non-insert tool-jobs row required"
    assert tool_jobs[0].get("config", {}).get("maxWaitTimeoutMs") == WAIT_CAP_MS
    assert "maxConsecutiveWakes" not in (tool_jobs[0].get("config") or {})
    blob = ""
    for path in (REPO / ".dsh").rglob("*"):
        if path.is_file():
            blob += path.read_text(encoding="utf-8", errors="replace")
            blob += "\n" + path.name
    assert "| T0" not in blob
    assert "T0–T17" not in blob and "T0-T17" not in blob
    guard_src = GUARD_PY.read_text(encoding="utf-8")
    for needle in (
        "dsh_dead_turn",
        "maxWaitTimeoutMs",
        "agent/turn-stopping",
        "JOB_WAIT_LOOP",
        "job_output",
        "EMPTY_RESPONSE",
        "SESSION_NOT_FOUND",
    ):
        assert needle not in guard_src
    lib = PLUGIN_LIB.read_text(encoding="utf-8")
    guard = PLUGIN_GUARD.read_text(encoding="utf-8")
    assert "@deepseek-ai/dsh" not in lib
    assert "@deepseek-ai/dsh" not in guard
    assert "createDeadTurnRequestErrorHandler" in lib
    assert "waitJobOutputUntilSettled" in lib
    assert '{ global: true }' in guard or "global: true" in guard
    assert "agent/turn-stopping" in guard
    rewritten = []
    for line in patch_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("name:") and "process-fsm-guard.js" in stripped:
            rewritten.append("name: /abs/process-fsm-guard.js")
        elif stripped.startswith("name:") and "impeccable-hook.js" in stripped:
            rewritten.append("name: /abs/impeccable-hook.js")
        else:
            rewritten.append(line)
    boot_out = "\n".join(rewritten)
    assert "maxWaitTimeoutMs: 2400000" in boot_out
    assert "- id: tool-jobs" in boot_out


def test_w8_regression_needles_paging_and_skill() -> None:
    skill = SKILL.read_text(encoding="utf-8")
    assert "MUST NOT spawnar filho QA" in skill or "MUST NOT spawnar filho QA" in skill
    assert "job_output wait" in skill
    assert "sem `continue`" in skill or "sem continue" in skill
    assert "MUST NOT `process_event`" in skill or "MUST NOT process_event" in skill
    fsm = yaml.safe_load(FSM_YAML.read_text(encoding="utf-8"))
    qa = str(fsm["context_file"]["QA"])
    assert "MUST NOT process_event" in qa
    assert "MUST NOT spawnar filho QA" in qa
    assert "job_output wait" in qa
    assert "sem continue" in qa
    assert "T14" in qa
    result = page(
        cwd=".",
        resolve_fn=_resolve("858", "card-858-dsh-idle-closeout"),
        status_provider=lambda _bound: "QA",
    )
    ctx = result["additional_context"]
    assert len(ctx.splitlines()) <= 20
    assert qa.strip().splitlines()[0] in ctx
    assert "job_output wait" in ctx
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    nonempty = [ln for ln in agents.splitlines() if ln.strip()]
    assert len(nonempty) <= 40
    assert "idle-closeout" not in agents
    for skill_path in (REPO / ".dsh" / "skills").glob("*/SKILL.md"):
        body = skill_path.read_text(encoding="utf-8").split("---", 2)[2]
        assert len([ln for ln in body.splitlines() if ln.strip()]) <= 8
        assert "T0" not in body and "T14" not in body
    grok = (REPO / ".grok" / "skills" / "covenant-flow" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    grok_body = grok.split("---", 2)[2]
    assert len([ln for ln in grok_body.splitlines() if ln.strip()]) <= 8
    assert 'export const inject = ["systemPrompt", "skills", "jobs"];' in PLUGIN_GUARD.read_text(
        encoding="utf-8"
    )
    assert (ROOT / "test_dsh_spawn_isolado.py").is_file()
    assert (ROOT / "test_dsh_reasoning_effort.py").is_file()
    assert (ROOT / "test_dsh_grill_spawn.py").is_file()
    assert (ROOT / "test_dsh_adapter.py").is_file()
