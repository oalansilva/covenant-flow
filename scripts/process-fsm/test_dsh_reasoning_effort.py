from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from test_dsh_adapter import (  # noqa: E402
    INSTALLER,
    PLUGIN_GUARD,
    PLUGIN_LIB,
    _init_repo,
    _node,
)
from test_overlay_fixtures import write_overlay  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

_SKIP_NO_INSTALLER = pytest.mark.skipif(
    not INSTALLER.is_file(),
    reason="install.sh is product-only; consumer pin does not copy it",
)

THIS_CLASS_FAILURE = {
    "message": '"reasoning.effort" does not support "none"',
    "code": "INVALID_REQUEST",
    "status": 400,
}
ROOT_SESSION = "session-root-817"
CHILD_SESSION = "session-child-817"
SKILL = REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md"


def _waterfall_ctx_prelude() -> str:
    return (
        "function mockWaterfallCtx() {\n"
        "  const events = {};\n"
        "  const sections = [];\n"
        "  const providers = [];\n"
        "  return {\n"
        "    events,\n"
        "    sections,\n"
        "    providers,\n"
        "    on(name, fn) {\n"
        "      const inner = events[name];\n"
        "      events[name] = async (payload, next) => {\n"
        "        const chained = inner ? () => inner(payload, next) : next;\n"
        "        return fn(payload, chained);\n"
        "      };\n"
        "    },\n"
        "    systemPrompt: { section(opts) { sections.push(opts); } },\n"
        "    skills: {\n"
        "      registerProvider(create) {\n"
        "        const provider = create({});\n"
        "        providers.push(provider);\n"
        "        return provider;\n"
        "      },\n"
        "    },\n"
        "  };\n"
        "}\n"
        "function installModelSelectionStrip(ctx) {\n"
        "  ctx.on('agent/request', async (_payload, next) => {\n"
        "    const resolved = await next();\n"
        "    const selected = {\n"
        "      provider: resolved && resolved.provider,\n"
        "      model: resolved && resolved.model,\n"
        "    };\n"
        "    const { reasoningEffort: _inheritedEffort, ...withoutInheritedEffort } =\n"
        "      resolved && typeof resolved === 'object' ? resolved : {};\n"
        "    return {\n"
        "      ...withoutInheritedEffort,\n"
        "      provider: selected.provider,\n"
        "      model: selected.model,\n"
        "      ...(selected.reasoningEffort === undefined\n"
        "        ? {}\n"
        "        : { reasoningEffort: selected.reasoningEffort }),\n"
        "    };\n"
        "  });\n"
        "}\n"
        "function rootAgent(id) {\n"
        "  return {\n"
        "    id,\n"
        "    session: { id, header: { id, delegationDepth: 0 } },\n"
        "  };\n"
        "}\n"
        "function childAgent(id, parentSession) {\n"
        "  return {\n"
        "    id,\n"
        "    session: {\n"
        "      id,\n"
        "      header: {\n"
        "        id,\n"
        "        delegationDepth: 1,\n"
        "        origin: 'subagent',\n"
        "        parentSession,\n"
        "      },\n"
        "    },\n"
        "  };\n"
        "}\n"
    )


def test_e1_sanitize_none_off_and_nested() -> None:
    code = f"""
import {{ sanitizeReasoningEffort }} from {json.dumps(str(PLUGIN_LIB))};
const none = sanitizeReasoningEffort({{ reasoningEffort: "none" }});
const off = sanitizeReasoningEffort({{ reasoningEffort: "Off" }});
const nested = sanitizeReasoningEffort({{ reasoning: {{ effort: "none", other: 1 }} }});
const both = sanitizeReasoningEffort({{
  reasoningEffort: "NONE",
  reasoning: {{ effort: "none" }},
}});
process.stdout.write(JSON.stringify({{ none, off, nested, both }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["none"]["reasoningEffort"] == "high"
    assert data["off"]["reasoningEffort"] == "high"
    assert data["nested"]["reasoningEffort"] == "high"
    assert data["nested"]["reasoning"].get("effort") != "none"
    assert "effort" not in data["nested"]["reasoning"]
    assert data["both"]["reasoningEffort"] == "high"
    assert data["both"]["reasoning"].get("effort") != "none"


def test_e2_sanitize_keeps_medium_and_missing_becomes_high() -> None:
    code = f"""
import {{ sanitizeReasoningEffort }} from {json.dumps(str(PLUGIN_LIB))};
const medium = sanitizeReasoningEffort({{ reasoningEffort: "medium" }});
const missing = sanitizeReasoningEffort({{}});
const empty = sanitizeReasoningEffort({{ reasoningEffort: "" }});
const nil = sanitizeReasoningEffort({{ reasoningEffort: null }});
process.stdout.write(JSON.stringify({{ medium, missing, empty, nil }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["medium"]["reasoningEffort"] == "medium"
    assert data["missing"]["reasoningEffort"] == "high"
    assert data["empty"]["reasoningEffort"] == "high"
    assert data["nil"]["reasoningEffort"] == "high"


def test_e10_rejection_negatives() -> None:
    code = f"""
import {{ isReasoningEffortRejection }} from {json.dumps(str(PLUGIN_LIB))};
const cases = {{
  unauth: isReasoningEffortRejection({{
    message: "unauthorized",
    code: "UNAUTHORIZED",
    status: 401,
  }}),
  unauthNeedles: isReasoningEffortRejection({{
    message: "reasoning.effort none",
    code: "UNAUTHORIZED",
    status: 401,
  }}),
  rate: isReasoningEffortRejection({{
    message: "rate limit exceeded",
    code: "RATE_LIMIT",
    status: 429,
  }}),
  guard: isReasoningEffortRejection({{
    kind: "deny",
    reason: "process-fsm-guard deny reason=fail_closed",
  }}),
  plain: isReasoningEffortRejection({{
    message: "timeout",
    code: "TIMEOUT",
    status: 504,
  }}),
  positive: isReasoningEffortRejection({json.dumps(THIS_CLASS_FAILURE)}),
}};
process.stdout.write(JSON.stringify(cases));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["unauth"] is False
    assert data["unauthNeedles"] is False
    assert data["rate"] is False
    assert data["guard"] is False
    assert data["plain"] is False
    assert data["positive"] is True


def test_e3_sanitize_wins_after_inner_strip() -> None:
    code = f"""
{_waterfall_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockWaterfallCtx();
installModelSelectionStrip(ctx);
apply(ctx);
const result = await ctx.events["agent/request"](
  {{ agent: rootAgent({json.dumps(ROOT_SESSION)}), turn: 9, step: 0 }},
  async () => ({{
    provider: "opencodealan",
    model: "muse-spark-1.2",
    reasoningEffort: "high",
  }}),
);
process.stdout.write(JSON.stringify(result));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["reasoningEffort"] == "high"
    assert data["provider"] == "opencodealan"


def test_e4_child_provider_model_only_becomes_high() -> None:
    code = f"""
{_waterfall_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockWaterfallCtx();
installModelSelectionStrip(ctx);
apply(ctx);
const result = await ctx.events["agent/request"](
  {{
    agent: childAgent({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}),
    turn: 1,
    step: 0,
    provider: "opencodealan",
  }},
  async () => ({{ provider: "opencodealan", model: "muse-spark-1.2" }}),
);
process.stdout.write(JSON.stringify(result));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["provider"] == "opencodealan"
    assert data["model"] == "muse-spark-1.2"
    assert data["reasoningEffort"] == "high"


def test_e5_root_first_this_class_retries_without_next() -> None:
    code = f"""
{_waterfall_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockWaterfallCtx();
apply(ctx);
let nextCalled = false;
const result = await ctx.events["agent/request-error"](
  {{
    agent: rootAgent({json.dumps(ROOT_SESSION)}),
    turn: 9,
    step: 0,
    provider: "opencodealan",
    failure: {json.dumps(THIS_CLASS_FAILURE)},
  }},
  async () => {{ nextCalled = true; return {{ kind: "continue" }}; }},
);
process.stdout.write(JSON.stringify({{ result, nextCalled }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["result"] == {"kind": "retry"}
    assert data["nextCalled"] is False


def test_e6_second_this_class_on_same_agent_calls_next() -> None:
    code = f"""
{_waterfall_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockWaterfallCtx();
apply(ctx);
const payload = {{
  agent: rootAgent({json.dumps(ROOT_SESSION)}),
  turn: 9,
  step: 0,
  provider: "opencodealan",
  failure: {json.dumps(THIS_CLASS_FAILURE)},
}};
const first = await ctx.events["agent/request-error"](payload, async () => ({{ kind: "continue" }}));
let nextCalled = false;
const second = await ctx.events["agent/request-error"](
  payload,
  async () => {{ nextCalled = true; return {{ kind: "continue" }}; }},
);
process.stdout.write(JSON.stringify({{ first, second, nextCalled }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["first"] == {"kind": "retry"}
    assert data["nextCalled"] is True
    assert data["second"] != {"kind": "retry"}


def test_e7_child_this_class_blocks_root_subagent_on_unequal_turns() -> None:
    code = f"""
{_waterfall_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockWaterfallCtx();
apply(ctx);
const childPayload = {{
  agent: childAgent({json.dumps(CHILD_SESSION)}, {json.dumps(ROOT_SESSION)}),
  turn: 1,
  step: 0,
  provider: "opencodealan",
  failure: {json.dumps(THIS_CLASS_FAILURE)},
}};
let childNext = false;
const childResult = await ctx.events["agent/request-error"](
  childPayload,
  async () => {{ childNext = true; }},
);
const rootAgentObj = rootAgent({json.dumps(ROOT_SESSION)});
let applyNext = false;
const applySpawn = await ctx.events["tools/pre-execute"](
  {{
    name: "subagent",
    arguments: {{ description: "Apply-coluna 817", prompt: "implemente" }},
    turn: 9,
    provider: "opencodealan",
    agent: rootAgentObj,
  }},
  async () => {{ applyNext = true; return {{ kind: "allow" }}; }},
);
let reviewerNext = false;
const reviewerSpawn = await ctx.events["tools/pre-execute"](
  {{
    name: "subagent",
    arguments: {{ description: "diff-reviewer 817", prompt: "review the diff" }},
    turn: 9,
    provider: "opencodealan",
    agent: rootAgentObj,
  }},
  async () => {{ reviewerNext = true; return {{ kind: "allow" }}; }},
);
process.stdout.write(JSON.stringify({{
  childTurn: childPayload.turn,
  rootTurn: 9,
  childProvider: childPayload.provider,
  childResult,
  childNext,
  applySpawn,
  applyNext,
  reviewerSpawn,
  reviewerNext,
}}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["childTurn"] == 1
    assert data["rootTurn"] == 9
    assert data["childTurn"] != data["rootTurn"]
    assert data["childProvider"] == "opencodealan"
    assert data["childProvider"] != "spawn"
    assert data["childResult"]["kind"] == "retry"
    assert data["childNext"] is False
    assert data["applyNext"] is False
    assert data["reviewerNext"] is False
    assert data["applySpawn"]["kind"] == "deny"
    assert "dsh_reasoning_effort_spawn" in data["applySpawn"]["reason"]
    assert data["reviewerSpawn"]["kind"] == "deny"
    assert "dsh_reasoning_effort_spawn" in data["reviewerSpawn"]["reason"]
    guard = PLUGIN_GUARD.read_text(encoding="utf-8")
    lib = PLUGIN_LIB.read_text(encoding="utf-8")
    blob = guard + "\n" + lib
    assert 'provider === "spawn"' not in blob
    assert "payload.provider === \"spawn\"" not in blob
    assert "@deepseek-ai/dsh-subagent" not in blob
    assert "Map(payload.turn)" not in blob


def test_e8_root_this_class_does_not_close_spawn_gate() -> None:
    code = f"""
{_waterfall_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockWaterfallCtx();
apply(ctx);
const root = rootAgent({json.dumps(ROOT_SESSION)});
await ctx.events["agent/request-error"](
  {{
    agent: root,
    turn: 9,
    step: 0,
    provider: "opencodealan",
    failure: {json.dumps(THIS_CLASS_FAILURE)},
  }},
  async () => ({{ kind: "continue" }}),
);
let applyNext = false;
const applySpawn = await ctx.events["tools/pre-execute"](
  {{
    name: "subagent",
    arguments: {{ description: "Apply-coluna 817", prompt: "implemente" }},
    turn: 9,
    provider: "opencodealan",
    agent: root,
  }},
  async () => {{ applyNext = true; return {{ kind: "allow" }}; }},
);
let grillNext = false;
const grill = await ctx.events["tools/pre-execute"](
  {{
    name: "subagent",
    arguments: {{ description: "grill-card 701", prompt: "…" }},
    turn: 9,
    provider: "opencodealan",
    agent: root,
  }},
  async () => {{ grillNext = true; return {{ kind: "allow" }}; }},
);
process.stdout.write(JSON.stringify({{ applySpawn, applyNext, grill, grillNext }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["applyNext"] is True
    assert data["applySpawn"]["kind"] != "deny" or "dsh_reasoning_effort_spawn" not in (
        data["applySpawn"].get("reason") or ""
    )
    assert data["grillNext"] is False
    assert data["grill"]["kind"] == "deny"
    assert "dsh_grill_spawn" in data["grill"]["reason"]


def test_e9_same_apply_still_denies_grill_cordis_write(tmp_path: Path) -> None:
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    code = f"""
{_waterfall_ctx_prelude()}
function mockThrowingCtx() {{
  const ctx = mockWaterfallCtx();
  ctx.skills.registerProvider = function (create) {{
    create({{}});
    throw new Error("duplicate name");
  }};
  return ctx;
}}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockThrowingCtx();
let applyThrew = false;
try {{
  apply(ctx);
}} catch (err) {{
  applyThrew = true;
}}
let nextGrill = false;
const grill = await ctx.events["tools/pre-execute"](
  {{ name: "subagent", arguments: {{ description: "grill-card 701", prompt: "…" }} }},
  async () => {{ nextGrill = true; }},
);
let nextCordis = false;
const cordis = await ctx.events["tools/pre-execute"](
  {{ name: "cordis_define", arguments: {{}} }},
  async () => {{ nextCordis = true; }},
);
let nextWrite = false;
const write = await ctx.events["tools/pre-execute"](
  {{ name: "edit", arguments: {{ file_path: "backend/app/main.py" }} }},
  async () => {{ nextWrite = true; }},
);
process.stdout.write(JSON.stringify({{
  applyThrew, nextGrill, nextCordis, nextWrite, grill, cordis, write,
}}));
"""
    proc = _node(code, cwd=repo)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["applyThrew"] is False
    assert data["nextGrill"] is False
    assert data["nextCordis"] is False
    assert data["nextWrite"] is False
    assert data["grill"]["kind"] == "deny"
    assert "dsh_grill_spawn" in data["grill"]["reason"]
    assert data["cordis"]["kind"] == "deny"
    assert "cordis_restrict" in data["cordis"]["reason"]
    assert data["write"]["kind"] == "deny"
    guard = PLUGIN_GUARD.read_text(encoding="utf-8")
    body = guard.split("tools/pre-execute", 1)[1]
    assert body.index("isGrillShapedSpawn") < body.index("dsh_reasoning_effort_spawn")
    assert body.index("dsh_reasoning_effort_spawn") < body.index("isCordisRestricted")
    assert body.index("isCordisRestricted") < body.index("runGuard")
    assert guard.index('ctx.on("tools/pre-execute"') < guard.index("registerProvider")
    assert 'export const inject = ["systemPrompt", "skills"];' in guard


def test_e11_guard_and_law_files_untouched() -> None:
    guard_src = (ROOT / "guard.py").read_text(encoding="utf-8")
    assert "reasoningEffort" not in guard_src
    assert "dsh_reasoning_effort" not in guard_src
    agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    nonempty = [ln for ln in agents.splitlines() if ln.strip()]
    assert len(nonempty) <= 40
    assert "reasoningEffort" not in agents
    assert "dsh_reasoning_effort" not in agents
    stubs_dir = REPO / ".dsh" / "skills"
    for skill in stubs_dir.glob("*/SKILL.md"):
        body = skill.read_text(encoding="utf-8").split("---", 2)[2]
        assert len([ln for ln in body.splitlines() if ln.strip()]) <= 8
    blob = ""
    for path in (REPO / ".dsh").rglob("*"):
        if path.is_file():
            blob += path.read_text(encoding="utf-8", errors="replace")
            blob += "\n" + path.name
    assert "| T0" not in blob
    assert "T0–T17" not in blob and "T0-T17" not in blob
    skill = SKILL.read_text(encoding="utf-8")
    assert "ERROR: subagent spawn failed/empty" in skill
    assert "#518" in skill
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(REPO),
            "diff",
            "--",
            "scripts/process-fsm/dsh_stubs.py",
            "scripts/process-fsm/guard.py",
            ".cursor/process-fsm.yaml",
            "AGENTS.md",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


@_SKIP_NO_INSTALLER
def test_e12_pin_expects_free_patch_and_dsh_auto_false(tmp_path: Path) -> None:
    target = tmp_path / "consumer"
    write_overlay(target, clients={
        "cursor": {"auto": True},
        "grok": {"auto": False},
        "opencode": {"auto": False},
        "dsh": {"auto": False},
    })
    proc = subprocess.run(
        [
            str(INSTALLER),
            "--pin",
            "v1.1.8",
            "--target",
            str(target),
            "--source",
            str(REPO),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    overlay = yaml.safe_load(
        (target / ".covenant-flow" / "overlay.yaml").read_text(encoding="utf-8")
    )
    assert overlay["pin"] == "v1.1.8"
    assert overlay["clients"]["dsh"]["auto"] is False
    guard = (target / ".dsh" / "plugin" / "process-fsm-guard.js").read_text(encoding="utf-8")
    assert "sanitizeReasoningEffort" in guard
    assert 'ctx.on("agent/request"' in guard
    lib = (target / "scripts" / "process-fsm" / "dsh_plugin_lib.js").read_text(encoding="utf-8")
    assert "sanitizeReasoningEffort" in lib
    assert "GRILL_CITATION_MARKERS" in lib
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "Auto dsh" not in agents
