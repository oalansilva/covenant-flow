from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from guard import decide  # noqa: E402
from test_dsh_adapter import (  # noqa: E402
    PLUGIN_GUARD,
    PLUGIN_LIB,
    _init_repo,
    _mock_ctx_prelude,
    _node,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

SILENT = lambda bound: (_ for _ in ()).throw(  # noqa: E731
    AssertionError(f"github called bound={bound}")
)

_THROWING_CTX = (
    _mock_ctx_prelude()
    + "function mockThrowingCtx() {\n"
    "  const ctx = mockCtx();\n"
    "  ctx.skills.registerProvider = function (create) {\n"
    "    create({});\n"
    "    throw new Error('duplicate name');\n"
    "  };\n"
    "  return ctx;\n"
    "}\n"
)


def _apply_pre_execute(
    tool: str,
    arguments,
    *,
    cwd: Path | None = None,
) -> dict:
    prelude = _mock_ctx_prelude()
    factory = "mockCtx"
    code = f"""
{prelude}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = {factory}();
let applyThrew = false;
try {{
  apply(ctx);
}} catch (err) {{
  applyThrew = true;
}}
let nextCalled = false;
const result = await ctx.events["tools/pre-execute"](
  {{ name: {json.dumps(tool)}, arguments: {json.dumps(arguments)} }},
  async () => {{ nextCalled = true; return {{ kind: "allow" }}; }},
);
process.stdout.write(JSON.stringify({{ applyThrew, nextCalled, result }}));
"""
    proc = _node(code, cwd=cwd)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_g1_subagent_description_grill_card_denied() -> None:
    data = _apply_pre_execute(
        "subagent",
        {"description": "grill-card 701", "prompt": "…"},
    )
    assert data["applyThrew"] is False
    assert data["nextCalled"] is False
    assert data["result"]["kind"] == "deny"
    assert "dsh_grill_spawn" in data["result"]["reason"]
    guard = PLUGIN_GUARD.read_text(encoding="utf-8")
    body = guard.split("tools/pre-execute", 1)[1]
    assert body.index("isGrillShapedSpawn") < body.index("isCordisRestricted")
    assert body.index("isGrillShapedSpawn") < body.index("runGuard")
    assert guard.index('ctx.on("tools/pre-execute"') < guard.index("registerProvider")


def test_g2_subagent_fork_needle_only_in_prompt_mixed_case() -> None:
    data = _apply_pre_execute(
        "subagent_fork",
        {"description": "refine 701", "prompt": "Please run Grill-Card on the issue"},
    )
    assert data["nextCalled"] is False
    assert data["result"]["kind"] == "deny"
    assert "dsh_grill_spawn" in data["result"]["reason"]


def test_g3_g1_with_run_in_background_false_still_denied() -> None:
    data = _apply_pre_execute(
        "subagent",
        {
            "description": "grill-card 701",
            "prompt": "…",
            "run_in_background": False,
        },
    )
    assert data["nextCalled"] is False
    assert data["result"]["kind"] == "deny"
    assert "dsh_grill_spawn" in data["result"]["reason"]


def test_g4_unrelated_subagent_calls_next() -> None:
    data = _apply_pre_execute(
        "subagent",
        {"description": "design-autor 786", "prompt": "write the OpenSpec"},
    )
    assert data["result"]["kind"] != "deny" or "dsh_grill_spawn" not in (
        data["result"].get("reason") or ""
    )
    assert data["nextCalled"] is True


def test_g5_task_spawn_subagent_and_opencode_task_call_next() -> None:
    prompt = {"prompt": "grill-card 701"}
    for tool in ("Task", "spawn_subagent", "task"):
        data = _apply_pre_execute(tool, prompt)
        assert data["nextCalled"] is True, tool
        result = data["result"] or {}
        if result.get("kind") == "deny":
            assert "dsh_grill_spawn" not in (result.get("reason") or ""), tool


def test_g6_arguments_json_string_denied() -> None:
    data = _apply_pre_execute("subagent", json.dumps({"description": "grill-card 701"}))
    assert data["nextCalled"] is False
    assert data["result"]["kind"] == "deny"
    assert "dsh_grill_spawn" in data["result"]["reason"]


def test_g7_illegal_product_edit_still_write_deny(tmp_path: Path) -> None:
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    data = _apply_pre_execute(
        "edit",
        {"file_path": "backend/app/main.py"},
        cwd=repo,
    )
    assert data["nextCalled"] is False
    assert data["result"]["kind"] == "deny"
    assert "dsh_grill_spawn" not in data["result"]["reason"]


def test_g8_cordis_define_still_cordis_restrict() -> None:
    data = _apply_pre_execute("cordis_define", {})
    assert data["nextCalled"] is False
    assert data["result"]["kind"] == "deny"
    assert "cordis_restrict" in data["result"]["reason"]


def test_g9_register_provider_throw_still_denies_grill_and_write(tmp_path: Path) -> None:
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    code = f"""
{_THROWING_CTX}
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
let nextWrite = false;
const write = await ctx.events["tools/pre-execute"](
  {{ name: "edit", arguments: {{ file_path: "backend/app/main.py" }} }},
  async () => {{ nextWrite = true; }},
);
process.stdout.write(JSON.stringify({{
  applyThrew, nextGrill, nextWrite, grill, write,
}}));
"""
    proc = _node(code, cwd=repo)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["applyThrew"] is False
    assert data["nextGrill"] is False
    assert data["nextWrite"] is False
    assert data["grill"]["kind"] == "deny"
    assert "dsh_grill_spawn" in data["grill"]["reason"]
    assert data["write"]["kind"] == "deny"


def test_g10_is_grill_shaped_spawn_unit_and_negatives() -> None:
    code = f"""
import {{ isGrillShapedSpawn }} from {json.dumps(str(PLUGIN_LIB))};
const cases = {{
  obj: isGrillShapedSpawn("subagent", {{ description: "grill-card 701" }}),
  str: isGrillShapedSpawn("subagent", JSON.stringify({{ prompt: "grill-card 701" }})),
  nested: isGrillShapedSpawn("subagent_fork", {{ inner: {{ prompt: "x grill-card y" }} }}),
  parseFail: isGrillShapedSpawn("subagent", "please run grill-card 701"),
  underscore: isGrillShapedSpawn("subagent", {{ description: "grill_card 701" }}),
  spaced: isGrillShapedSpawn("subagent", {{ description: "grill card 701" }}),
  task: isGrillShapedSpawn("Task", {{ prompt: "grill-card 701" }}),
  spawn: isGrillShapedSpawn("spawn_subagent", {{ prompt: "grill-card 701" }}),
  opencodeTask: isGrillShapedSpawn("task", {{ prompt: "grill-card 701" }}),
}};
process.stdout.write(JSON.stringify(cases));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["obj"] is True
    assert data["str"] is True
    assert data["nested"] is True
    assert data["parseFail"] is True
    assert data["underscore"] is False
    assert data["spaced"] is False
    assert data["task"] is False
    assert data["spawn"] is False
    assert data["opencodeTask"] is False


def test_g11_decide_allows_task_with_grill_card_prompt() -> None:
    result = decide(
        {"tool": "Task", "args": {"prompt": "grill-card 701"}},
        status_provider=SILENT,
    )
    assert result["permission"] == "allow"
    src = (ROOT / "guard.py").read_text(encoding="utf-8")
    for needle in ("grill-card", "dsh_grill_spawn", "isGrillShapedSpawn"):
        assert needle not in src, needle
