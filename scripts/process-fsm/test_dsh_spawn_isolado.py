from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from test_dsh_adapter import PLUGIN_GUARD, PLUGIN_LIB, _node  # noqa: E402
from test_dsh_reasoning_effort import THIS_CLASS_FAILURE  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

ROOT_SESSION = "session-root-839"
CHILD_SESSION = "session-child-839"
PROVIDER_MODEL = {"provider": "opencodealan", "model": "muse-spark-1.2"}
THIS_CLASS_MESSAGE = '"reasoning.effort" does not support "none"'


def _append_inner_ctx_prelude() -> str:
    """Append-inner mock with a scopeTarget-style predicate. Not E3 wrap-as-outer."""
    return r"""
function createScopeRegistry() {
  return { hooks: Object.create(null), parents: new Map(), agents: new Map() };
}
function scopeAdmits(hook, carrierKey, parents) {
  if (hook.global) return true;
  if (hook.scopeKey === undefined) return true;
  for (let cursor = carrierKey; cursor !== undefined; cursor = parents.get(cursor)) {
    if (cursor === hook.scopeKey) return true;
  }
  return false;
}
function makeDispatcher(registry, scopeKey, name) {
  return async (...args) => {
    const list = (registry.hooks[name] || []).filter((hook) =>
      scopeAdmits(hook, scopeKey, registry.parents),
    );
    const last = args[args.length - 1];
    const isWaterfall = typeof last === "function";
    if (!isWaterfall) {
      let lastResult;
      for (const hook of list) lastResult = await hook.fn(...args);
      return lastResult;
    }
    const nextInner = last;
    const payloadArgs = args.slice(0, -1);
    const cbs = list.map((hook) => hook.fn);
    const next = () => {
      const cb = cbs.shift();
      if (!cb) return nextInner(...payloadArgs);
      return cb(...payloadArgs, next);
    };
    return next();
  };
}
function mockAppendInnerCtx(registry, scopeKey) {
  const sections = [];
  const providers = [];
  const events = new Proxy({}, {
    get(_target, prop) {
      if (typeof prop !== "string") return undefined;
      return makeDispatcher(registry, scopeKey, prop);
    },
  });
  const ctx = {
    events,
    sections,
    providers,
    scopeKey,
    registry,
    agents: registry.agents,
    get(name) {
      if (name === "agents") return registry.agents;
      return undefined;
    },
    on(name, fn, opts) {
      const options = typeof opts === "boolean"
        ? { prepend: opts }
        : (opts && typeof opts === "object" ? opts : {});
      const hook = {
        fn,
        ctx,
        scopeKey,
        global: !!options.global,
        prepend: !!options.prepend,
      };
      const list = registry.hooks[name] || [];
      if (hook.prepend) list.unshift(hook);
      else list.push(hook);
      registry.hooks[name] = list;
    },
    systemPrompt: { section(opts) { sections.push(opts); } },
    skills: {
      registerProvider(create) {
        const provider = create({});
        providers.push(provider);
        return provider;
      },
    },
  };
  return ctx;
}
function installModelSelectionStrip(ctx) {
  ctx.on("agent/request", async (_payload, next) => {
    const resolved = await next();
    const selected = {
      provider: resolved && resolved.provider,
      model: resolved && resolved.model,
    };
    const { reasoningEffort: _inheritedEffort, ...withoutInheritedEffort } =
      resolved && typeof resolved === "object" ? resolved : {};
    return {
      ...withoutInheritedEffort,
      provider: selected.provider,
      model: selected.model,
      ...(selected.reasoningEffort === undefined
        ? {}
        : { reasoningEffort: selected.reasoningEffort }),
    };
  });
}
function rootAgent(id) {
  return { id, session: { id, header: { id, delegationDepth: 0 } } };
}
function childAgent(id, parentSession) {
  return {
    id,
    session: {
      id,
      header: {
        id,
        delegationDepth: 1,
        origin: "subagent",
        parentSession,
      },
    },
  };
}
function childSession(id, parentSession) {
  return {
    id,
    header: {
      id,
      delegationDepth: 1,
      origin: "subagent",
      parentSession,
    },
  };
}
function thisClassError() {
  const err = new Error('"reasoning.effort" does not support "none"');
  Object.defineProperty(err, "code", {
    value: "INVALID_REQUEST",
    enumerable: false,
    configurable: true,
    writable: true,
  });
  Object.defineProperty(err, "status", {
    value: 400,
    enumerable: false,
    configurable: true,
    writable: true,
  });
  return err;
}
function thisClassTurnEnd() {
  return {
    type: "turn/end",
    data: {
      reason: {
        kind: "error",
        error: {
          message: '"reasoning.effort" does not support "none"',
          code: "INVALID_REQUEST",
          status: 400,
        },
      },
    },
  };
}
"""


def _node_ok(code: str) -> dict:
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    return json.loads(proc.stdout)


def test_f_mock_is_append_inner_not_e3_wrap() -> None:
    prelude = _append_inner_ctx_prelude()
    e3 = (ROOT / "test_dsh_reasoning_effort.py").read_text(encoding="utf-8")
    assert "function scopeAdmits" in prelude
    assert "hook.prepend" in prelude
    assert "list.unshift" in prelude
    assert "list.push" in prelude
    assert "mockAppendInnerCtx" in prelude
    assert "function mockWaterfallCtx" in e3
    assert "function mockWaterfallCtx" not in prelude
    assert "events[name] = async (payload, next)" not in prelude
    assert "EventEmitter" not in prelude


def test_f1_host_only_apply_plus_child_strip_has_no_high() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const child = mockAppendInnerCtx(registry, "child");
const untaggedHits = [];
const untagged = mockAppendInnerCtx(registry, undefined);
untagged.on("agent/request", async (_payload, next) => {{
  untaggedHits.push("untagged");
  return next();
}});
installModelSelectionStrip(child);
apply(host);
const result = await child.events["agent/request"](
  {{ agent: childAgent({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}), turn: 1, step: 0 }},
  async () => ({json.dumps(PROVIDER_MODEL)}),
);
process.stdout.write(JSON.stringify({{
  result,
  untaggedHits,
  hostHooks: (registry.hooks["agent/request"] || []).map((h) => ({{
    scopeKey: h.scopeKey === undefined ? null : h.scopeKey,
    global: !!h.global,
    prepend: !!h.prepend,
  }})),
}}));
"""
    data = _node_ok(code)
    assert data["result"]["provider"] == "opencodealan"
    assert data["result"]["model"] == "muse-spark-1.2"
    assert data["result"].get("reasoningEffort") != "high"
    assert "reasoningEffort" not in data["result"]
    assert data["untaggedHits"] == ["untagged"]
    host_listeners = [h for h in data["hostHooks"] if h["scopeKey"] == "host"]
    assert host_listeners, "host apply must register on the shared bus"
    assert all(h["global"] is False for h in host_listeners)


def test_f2_created_global_attach_prepend_wins() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const child = mockAppendInnerCtx(registry, "child");
installModelSelectionStrip(child);
apply(host);
await child.events["agent/created"]({{ agent: {{ ctx: child, session: childAgent({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}).session }} }});
const result = await child.events["agent/request"](
  {{
    agent: childAgent({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}),
    turn: 1,
    step: 0,
  }},
  async () => ({json.dumps(PROVIDER_MODEL)}),
);
const createdHooks = (registry.hooks["agent/created"] || []).map((h) => ({{
  global: !!h.global,
  scopeKey: h.scopeKey === undefined ? null : h.scopeKey,
}}));
process.stdout.write(JSON.stringify({{ result, createdHooks }}));
"""
    data = _node_ok(code)
    assert data["result"]["reasoningEffort"] == "high"
    assert data["result"]["provider"] == "opencodealan"
    assert data["result"]["model"] == "muse-spark-1.2"
    assert any(h["global"] is True for h in data["createdHooks"])
    here = Path(__file__).read_text(encoding="utf-8")
    f2 = here.split("def test_f2_created_global_attach_prepend_wins", 1)[1].split(
        "def test_f3_", 1
    )[0]
    assert "attachAgentEffortGuards(child" not in f2
    assert "agent/created" in f2


def test_f3_attach_without_prepend_loses_to_strip() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ sanitizeReasoningEffort }} from {json.dumps(str(PLUGIN_LIB))};
const registry = createScopeRegistry();
const child = mockAppendInnerCtx(registry, "child");
installModelSelectionStrip(child);
child.on("agent/request", async (_payload, next) => sanitizeReasoningEffort(await next()));
const result = await child.events["agent/request"](
  {{ agent: childAgent({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}), turn: 1, step: 0 }},
  async () => ({json.dumps(PROVIDER_MODEL)}),
);
process.stdout.write(JSON.stringify(result));
"""
    data = _node_ok(code)
    assert data.get("reasoningEffort") != "high"
    assert "reasoningEffort" not in data


def test_f4_child_nonenumerable_error_retries_once() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const child = mockAppendInnerCtx(registry, "child");
apply(host);
await child.events["agent/created"]({{ agent: {{ ctx: child }} }});
const payload = {{
  agent: childAgent({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}),
  turn: 1,
  step: 0,
  failure: thisClassError(),
}};
const enumerableKeys = Object.keys(payload.failure);
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
let hostOnlyNext = false;
let hostOnlyResult = null;
{{
  const hostOnly = mockAppendInnerCtx(createScopeRegistry(), "host");
  apply(hostOnly);
  const isolatedChild = mockAppendInnerCtx(hostOnly.registry, "child");
  hostOnlyResult = await isolatedChild.events["agent/request-error"](
    payload,
    async () => {{ hostOnlyNext = true; return {{ kind: "continue" }}; }},
  );
}}
process.stdout.write(JSON.stringify({{
  enumerableKeys,
  first,
  firstNext,
  second,
  secondNext,
  hostOnlyResult,
  hostOnlyNext,
}}));
"""
    data = _node_ok(code)
    assert "message" not in data["enumerableKeys"]
    assert data["first"] == {"kind": "retry"}
    assert data["firstNext"] is False
    assert data["secondNext"] is True
    assert data["second"] != {"kind": "retry"}
    assert data["hostOnlyNext"] is True
    assert data["hostOnlyResult"] != {"kind": "retry"}


def test_f5_foreground_iserror_result_rewritten() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const child = mockAppendInnerCtx(registry, "child");
apply(host);
await child.events["session/event"](
  childSession({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}),
  thisClassTurnEnd(),
);
let nextSucceeded = false;
const result = await host.events["tools/execute"](
  {{
    name: "subagent",
    arguments: {{ description: "one-shot 839", prompt: "PROBE_OK" }},
    agent: rootAgent({json.dumps(ROOT_SESSION)}),
  }},
  async () => {{
    nextSucceeded = true;
    return {{ isError: true, content: "Error: subagent run failed" }};
  }},
);
let throwOnly = false;
try {{
  await (async () => {{
    const nextResult = {{ isError: true, content: "Error: subagent run failed" }};
    void nextResult;
  }})();
}} catch {{
  throwOnly = true;
}}
process.stdout.write(JSON.stringify({{ result, nextSucceeded, throwOnly }}));
"""
    data = _node_ok(code)
    assert data["nextSucceeded"] is True
    assert data["throwOnly"] is False
    blob = json.dumps(data["result"])
    text = data["result"].get("content") or ""
    if isinstance(text, list):
        text = " ".join(block.get("text", "") if isinstance(block, dict) else str(block) for block in text)
    assert data["result"]["isError"] is True
    assert "stopReason" in blob
    assert "Diagnostic:" in blob
    assert "reasoning.effort" in text
    assert "does not support" in text
    assert "none" in text
    assert "dsh_reasoning_effort_none" in blob
    assert "JSON.stringify" not in (PLUGIN_LIB.read_text(encoding="utf-8").split("export function formatChildRunFailure", 1)[1].split("export function createReasoningEffort", 1)[0])


def test_f6_unrelated_failures_unlabelled() -> None:
    code = f"""
import {{ formatChildRunFailure, isReasoningEffortRejection }} from {json.dumps(str(PLUGIN_LIB))};
const cases = {{
  unauth: {{
    match: isReasoningEffortRejection({{ message: "unauthorized", code: "UNAUTHORIZED", status: 401 }}),
    text: formatChildRunFailure({{ stopReason: "error", failure: {{ message: "unauthorized", status: 401 }} }}),
  }},
  rate: {{
    match: isReasoningEffortRejection({{ message: "rate limit exceeded", status: 429 }}),
    text: formatChildRunFailure({{ stopReason: "error", failure: {{ message: "rate limit exceeded", status: 429 }} }}),
  }},
  guard: {{
    match: isReasoningEffortRejection({{ kind: "deny", reason: "process-fsm-guard deny reason=fail_closed" }}),
    text: formatChildRunFailure({{
      stopReason: "error",
      failure: {{ kind: "deny", reason: "process-fsm-guard deny reason=fail_closed" }},
    }}),
  }},
  positive: {{
    match: isReasoningEffortRejection({json.dumps(THIS_CLASS_FAILURE)}),
    text: formatChildRunFailure({{ stopReason: "error", failure: {json.dumps(THIS_CLASS_FAILURE)} }}),
  }},
}};
process.stdout.write(JSON.stringify(cases));
"""
    data = _node_ok(code)
    assert data["unauth"]["match"] is False
    assert "dsh_reasoning_effort_none" not in data["unauth"]["text"]
    assert data["rate"]["match"] is False
    assert "dsh_reasoning_effort_none" not in data["rate"]["text"]
    assert data["guard"]["match"] is False
    assert "dsh_reasoning_effort_none" not in data["guard"]["text"]
    assert data["positive"]["match"] is True
    assert "dsh_reasoning_effort_none" in data["positive"]["text"]
    assert "Diagnostic:" in data["positive"]["text"]
    assert THIS_CLASS_MESSAGE in data["positive"]["text"]
    assert "stopReason" in data["positive"]["text"]
    lib = PLUGIN_LIB.read_text(encoding="utf-8")
    formatter = lib.split("export function formatChildRunFailure", 1)[1].split(
        "export function createReasoningEffort", 1
    )[0]
    assert "JSON.stringify(failure)" not in formatter
    assert "JSON.stringify(failure" not in formatter


def test_f7_continuable_settlement_followup_not_generic() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const child = mockAppendInnerCtx(registry, "child");
const notices = [];
registry.agents.set({json.dumps(ROOT_SESSION)}, {{
  id: {json.dumps(ROOT_SESSION)},
  status: "idle",
  followup(msg) {{ notices.push({{ via: "followup", msg }}); }},
  steer(msg) {{ notices.push({{ via: "steer", msg }}); }},
  inject(msg) {{ notices.push({{ via: "inject", msg }}); }},
}});
apply(host);
const startResult = await host.events["tools/execute"](
  {{
    name: "subagent",
    arguments: {{
      description: "continuable 839",
      prompt: "PROBE_OK",
      run_in_background: true,
    }},
    agent: rootAgent({json.dumps(ROOT_SESSION)}),
  }},
  async () => ({{ isError: false, content: "started subagent {CHILD_SESSION}" }}),
);
const sendResult = await host.events["tools/execute"](
  {{
    name: "send_message",
    arguments: {{ subagentId: {json.dumps(CHILD_SESSION)}, message: "continue" }},
    agent: rootAgent({json.dumps(ROOT_SESSION)}),
  }},
  async () => ({{ isError: false, content: "message queued", messageId: "m1" }}),
);
await child.events["session/event"](
  childSession({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}),
  thisClassTurnEnd(),
);
const sessionHooks = (registry.hooks["session/event"] || []).map((h) => ({{
  global: !!h.global,
  scopeKey: h.scopeKey === undefined ? null : h.scopeKey,
}}));
const noGlobalNotices = [];
{{
  const isolated = createScopeRegistry();
  isolated.agents.set({json.dumps(ROOT_SESSION)}, {{
    id: {json.dumps(ROOT_SESSION)},
    status: "idle",
    followup(msg) {{ noGlobalNotices.push({{ via: "followup", msg }}); }},
    steer(msg) {{ noGlobalNotices.push({{ via: "steer", msg }}); }},
    inject(msg) {{ noGlobalNotices.push({{ via: "inject", msg }}); }},
  }});
  const hostB = mockAppendInnerCtx(isolated, "host");
  hostB.on("session/event", (session, event) => {{
    noGlobalNotices.push({{ via: "host-nonglobal", session, event }});
  }});
  const childB = mockAppendInnerCtx(isolated, "child");
  await childB.events["session/event"](
    childSession({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}),
    thisClassTurnEnd(),
  );
}}
process.stdout.write(JSON.stringify({{
  startResult,
  sendResult,
  notices,
  sessionHooks,
  noGlobalNotices,
}}));
"""
    data = _node_ok(code)
    assert "Diagnostic:" not in json.dumps(data["startResult"])
    assert "dsh_reasoning_effort_none" not in json.dumps(data["startResult"])
    assert "started subagent" in json.dumps(data["startResult"])
    assert "Diagnostic:" not in json.dumps(data["sendResult"])
    assert "message queued" in json.dumps(data["sendResult"])
    assert any(h["global"] is True for h in data["sessionHooks"])
    assert data["notices"], "parent must receive followup/steer after child turn/end"
    blob = json.dumps(data["notices"])
    notice_text = json.dumps(data["notices"][0]["msg"]["content"])
    assert "stopReason" in blob
    assert "Diagnostic:" in blob
    assert "reasoning.effort" in notice_text
    assert "does not support" in notice_text
    assert "none" in notice_text
    assert "dsh_reasoning_effort_none" in blob
    assert any(n["via"] in ("followup", "steer") for n in data["notices"])
    assert not any(n["via"] == "inject" for n in data["notices"])
    assert "failed before it finished" not in blob
    assert "It left no closing message." not in blob
    assert "subagent-settled" not in blob
    assert data["notices"][0]["msg"]["source"]["kind"] == "plugin"
    assert data["notices"][0]["msg"]["source"]["plugin"] == "covenant-flow-process-fsm-guard"
    assert data["notices"][0]["msg"]["source"]["form"] == "notice"
    assert data["noGlobalNotices"] == []


def test_f8_second_continuable_request_still_high() -> None:
    code = f"""
{_append_inner_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const registry = createScopeRegistry();
const host = mockAppendInnerCtx(registry, "host");
const child = mockAppendInnerCtx(registry, "child");
installModelSelectionStrip(child);
apply(host);
await child.events["agent/created"]({{ agent: {{ ctx: child }} }});
const first = await child.events["agent/request"](
  {{ agent: childAgent({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}), turn: 1, step: 0 }},
  async () => ({json.dumps(PROVIDER_MODEL)}),
);
const second = await child.events["agent/request"](
  {{ agent: childAgent({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}), turn: 2, step: 0 }},
  async () => ({json.dumps(PROVIDER_MODEL)}),
);
process.stdout.write(JSON.stringify({{ first, second }}));
"""
    data = _node_ok(code)
    assert data["first"]["reasoningEffort"] == "high"
    assert data["second"]["reasoningEffort"] == "high"


def test_f_attach_must_not_throw() -> None:
    code = f"""
import {{ attachAgentEffortGuards }} from {json.dumps(str(PLUGIN_LIB))};
let threw = false;
try {{
  attachAgentEffortGuards(null);
  attachAgentEffortGuards({{}});
  attachAgentEffortGuards({{
    on() {{ throw new Error("boom"); }},
  }});
}} catch {{
  threw = true;
}}
process.stdout.write(JSON.stringify({{ threw }}));
"""
    data = _node_ok(code)
    assert data["threw"] is False
    lib = PLUGIN_LIB.read_text(encoding="utf-8")
    assert "@deepseek-ai/dsh" not in lib
    guard = PLUGIN_GUARD.read_text(encoding="utf-8")
    assert "@deepseek-ai/dsh" not in guard
    assert 'export const inject = ["systemPrompt", "skills"];' in guard
    body = guard.split("tools/pre-execute", 1)[1]
    assert body.index("isGrillShapedSpawn") < body.index("dsh_reasoning_effort_spawn")
    assert body.index("dsh_reasoning_effort_spawn") < body.index("isCordisRestricted")
    assert body.index("isCordisRestricted") < body.index("runGuard")
