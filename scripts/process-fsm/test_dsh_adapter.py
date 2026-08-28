from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from dsh_stubs import stub_errors  # noqa: E402
from paging import page  # noqa: E402
from test_overlay_fixtures import write_overlay  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TODO_STUB = "Próximo evento = iniciar_design. Não apply. Não /opsx:new ainda."
PLAYBOOK = ("release-guard", "subir lote", "deploy PROD")
PLUGIN_GUARD = REPO / ".dsh" / "plugin" / "process-fsm-guard.js"
PLUGIN_HOOK = REPO / ".dsh" / "plugin" / "impeccable-hook.js"
PLUGIN_LIB = REPO / "scripts" / "process-fsm" / "dsh_plugin_lib.js"
OPENCODE_LIB = REPO / "scripts" / "process-fsm" / "opencode_plugin_lib.js"
BOOT = REPO / "scripts" / "process-fsm" / "dsh_boot.sh"
PATCH = REPO / ".dsh" / "cordis.patch.yml"
INSTALLER = REPO / "install.sh"
_SKIP_NO_INSTALLER = pytest.mark.skipif(
    not INSTALLER.is_file(),
    reason="install.sh is product-only; consumer pin does not copy it",
)


def _resolve(bound: str, git: str) -> object:
    def inner(cwd, path, issue_id=None, status=None):
        return {"q": None, "bound_card": bound, "q_git": git}

    return inner


def _provider(status: str | None):
    def inner(bound: str | None) -> str | None:
        return status

    return inner


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(path: Path, branch: str, filename: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", branch, str(path)], check=True, capture_output=True, text=True
    )
    _run_git(path, "config", "user.email", "process-fsm@test.local")
    _run_git(path, "config", "user.name", "process-fsm")
    tracked = path / filename
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("fixture\n", encoding="utf-8")
    _run_git(path, "add", filename)
    _run_git(path, "commit", "-m", "init")
    write_overlay(path)


def _node(code: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["node", "--input-type=module", "-e", code],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO),
        check=False,
        timeout=30,
    )


def _mock_ctx_prelude() -> str:
    return (
        "function mockCtx() {\n"
        "  const events = {};\n"
        "  const sections = [];\n"
        "  return {\n"
        "    events,\n"
        "    sections,\n"
        "    on(name, fn) { events[name] = fn; },\n"
        "    systemPrompt: { section(opts) { sections.push(opts); } },\n"
        "  };\n"
        "}\n"
    )


def test_d15_dsh_page_body_injectable():
    result = page(
        cwd=".",
        resolve_fn=_resolve("782", "card-782-dsh-adapter"),
        status_provider=_provider("Todo"),
    )
    ctx = result["additional_context"]
    assert TODO_STUB in ctx
    assert "q=Todo" in ctx
    assert "(q, bound_card, q_git)" in ctx or "bound_card=" in ctx
    for needle in PLAYBOOK:
        assert needle not in ctx
    assert len(ctx.splitlines()) <= 20
    text = PLUGIN_GUARD.read_text(encoding="utf-8")
    assert "covenant-flow:moore" in text
    assert "runPage" in text
    assert "process-fsm-page.md" not in text
    assert "agent/session-start" not in text
    assert "MUST Read" not in text


def test_d16_mapper_file_path_without_filePath():
    code = f"""
import {{ mapAfterPayload, mapTurnStoppingPayload, runHookMjs }} from {json.dumps(str(PLUGIN_LIB))};
import {{ mapAfterPayload as ocMap }} from {json.dumps(str(OPENCODE_LIB))};
const after = mapAfterPayload({{
  tool: "edit",
  args: {{ file_path: "frontend/src/x.tsx" }},
}});
const idle = mapTurnStoppingPayload();
const oc = ocMap({{ tool: "edit", args: {{ file_path: "frontend/src/x.tsx" }} }});
const status = runHookMjs(after, {json.dumps(str(REPO))});
process.stdout.write(JSON.stringify({{ after, idle, status, oc }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["after"]["file_path"] == "frontend/src/x.tsx"
    assert data["after"]["hook_event_name"] == "PostToolUse"
    assert data["idle"]["hook_event_name"] == "Stop"
    assert data["status"] == 0
    assert data["oc"]["file_path"] == ""
    lib = PLUGIN_LIB.read_text(encoding="utf-8")
    assert "opencode_plugin_lib" not in lib
    assert "filePath" not in lib
    assert "patchText" not in lib


def test_d13_plugin_restricts_cordis_without_next():
    code = f"""
{_mock_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockCtx();
apply(ctx);
let nextCalled = false;
const result = await ctx.events["tools/pre-execute"](
  {{ name: "cordis_define", arguments: {{}} }},
  async () => {{ nextCalled = true; return {{ kind: "allow" }}; }},
);
const run = await ctx.events["tools/pre-execute"](
  {{ name: "cordis_run", arguments: {{}} }},
  async () => {{ nextCalled = true; }},
);
process.stdout.write(JSON.stringify({{ result, run, nextCalled }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["result"]["kind"] == "deny"
    assert data["run"]["kind"] == "deny"
    assert data["nextCalled"] is False


def test_d20_write_like_without_json_is_fail_closed():
    code = f"""
import {{ denyFromDecision }} from {json.dumps(str(PLUGIN_LIB))};
const denied = denyFromDecision(null, "write", {{ file_path: "backend/app/main.py" }});
const view = denyFromDecision(null, "str_replace_editor", {{ command: "view", path: "backend/app/main.py" }});
const grep = denyFromDecision(null, "grep", {{}});
process.stdout.write(JSON.stringify({{ denied, view, grep }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["denied"]["kind"] == "deny"
    assert "fail_closed" in data["denied"]["reason"]
    assert data["view"] is None
    assert data["grep"] is None


def test_plugin_deny_on_illegal_product_write_without_throw(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    code = f"""
{_mock_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockCtx();
apply(ctx);
let nextCalled = false;
let threw = false;
let result = null;
try {{
  result = await ctx.events["tools/pre-execute"](
    {{ name: "edit", arguments: {{ file_path: "backend/app/main.py" }} }},
    async () => {{ nextCalled = true; }},
  );
}} catch (err) {{
  threw = true;
}}
process.stdout.write(JSON.stringify({{
  result, nextCalled, threw,
  section: ctx.sections[0] && ctx.sections[0].name,
  textType: typeof (ctx.sections[0] && ctx.sections[0].text),
}}));
"""
    proc = _node(code, cwd=repo)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["threw"] is False
    assert data["nextCalled"] is False
    assert data["result"]["kind"] == "deny"
    assert data["section"] == "covenant-flow:moore"
    assert data["textType"] == "function"


def test_plugin_next_on_openspec_design(tmp_path: Path):
    repo = tmp_path / "card"
    rel = "openspec/changes/card-782-dsh-adapter/design.md"
    _init_repo(repo, "card-782-dsh-adapter", rel)
    code = f"""
import {{ runGuard, denyFromDecision }} from {json.dumps(str(PLUGIN_LIB))};
const decision = runGuard({{
  tool: "edit",
  args: {{ file_path: {json.dumps(rel)} }},
  cwd: {json.dumps(str(repo))},
  status: "Design",
}});
const denied = denyFromDecision(decision, "edit", {{ file_path: {json.dumps(rel)} }});
process.stdout.write(JSON.stringify({{ decision, denied }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["decision"]["permission"] == "allow"
    assert data["denied"] is None


def test_detector_never_block_or_steer():
    blob = PLUGIN_HOOK.read_text(encoding="utf-8")
    code = f"""
{_mock_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_HOOK))};
const ctx = mockCtx();
apply(ctx);
let nextCalled = false;
await ctx.events["tools/post-execute"](
  {{ name: "edit", arguments: {{ file_path: "frontend/src/x.tsx" }} }},
  {{}},
  async () => {{ nextCalled = true; return {{ kind: "continue" }}; }},
);
await ctx.events["agent/turn-stopping"]({{}});
process.stdout.write(JSON.stringify({{ nextCalled: nextCalled }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["nextCalled"] is True
    assert "kind: 'block'" not in blob and 'kind: "block"' not in blob
    assert "steer(" not in blob and ".steer" not in blob


def test_dsh_plugins_export_apply_not_default():
    for path in (PLUGIN_GUARD, PLUGIN_HOOK):
        code = f"""
import * as ns from {json.dumps(str(path))};
process.stdout.write(JSON.stringify({{ keys: Object.keys(ns).sort(), hasApply: typeof ns.apply }}));
"""
        proc = _node(code)
        assert proc.returncode == 0, proc.stderr
        keys = json.loads(proc.stdout)
        assert "apply" in keys["keys"]
        assert "default" not in keys["keys"]
        assert keys["hasApply"] == "function"
        text = path.read_text(encoding="utf-8")
        assert "export function apply" in text
        assert "export default" not in text


def test_d18_dsh_tree_has_no_law_or_claude_hooks():
    dsh = REPO / ".dsh"
    assert PLUGIN_GUARD.is_file()
    assert PLUGIN_HOOK.is_file()
    assert PATCH.is_file()
    assert BOOT.is_file()
    assert BOOT.stat().st_mode & stat.S_IXUSR
    blob = ""
    for path in dsh.rglob("*"):
        if path.is_file():
            blob += path.read_text(encoding="utf-8", errors="replace")
            blob += "\n" + path.name
    assert "| T0" not in blob
    assert "T0–T17" not in blob and "T0-T17" not in blob
    assert "I1–I9" not in blob
    assert "hooks.json" not in blob
    assert "deepseek-ai/deepseek-harness" not in blob
    patch_text = PATCH.read_text(encoding="utf-8")
    assert "covenant-flow-process-fsm-guard" in patch_text
    assert "covenant-flow-impeccable-hook" in patch_text
    assert "/srv/apps/" not in patch_text
    boot = BOOT.read_text(encoding="utf-8")
    assert "dsh web --patch" in boot
    lib = PLUGIN_LIB.read_text(encoding="utf-8")
    assert "opencode_plugin_lib" not in lib


def test_dsh_boot_materializes_absolute_names(tmp_path: Path):
    dest = tmp_path / "out.patch.yml"
    src = PATCH.read_text(encoding="utf-8")
    out = []
    for line in src.splitlines():
        stripped = line.strip()
        indent = line[: len(line) - len(line.lstrip())]
        if stripped.startswith("name:") and "process-fsm-guard.js" in stripped:
            out.append(f"{indent}name: {PLUGIN_GUARD}")
        elif stripped.startswith("name:") and "impeccable-hook.js" in stripped:
            out.append(f"{indent}name: {PLUGIN_HOOK}")
        else:
            out.append(line)
    dest.write_text("\n".join(out) + "\n", encoding="utf-8")
    text = dest.read_text(encoding="utf-8")
    assert str(PLUGIN_GUARD) in text
    assert str(PLUGIN_HOOK) in text
    assert PLUGIN_GUARD.is_absolute()


def test_dsh_stubs_match_cursor_skills():
    errors = stub_errors()
    assert errors == []
    stub = (REPO / ".dsh" / "skills" / "covenant-flow" / "SKILL.md").read_text(encoding="utf-8")
    assert ".cursor/skills/covenant-flow/SKILL.md" in stub
    assert "MUST Read" in stub
    body = stub.split("---", 2)[2]
    assert len([ln for ln in body.splitlines() if ln.strip()]) <= 8
    assert not (REPO / ".dsh" / "skills" / "impeccable" / "SKILL.md").exists()
    assert not (REPO / ".dsh" / "skills" / "design-critic" / "SKILL.md").exists()
    assert not (REPO / ".dsh" / "skills" / "playwright-cli" / "SKILL.md").exists()


@_SKIP_NO_INSTALLER
def test_pin_copies_dsh_without_injecting_clients_dsh(tmp_path: Path):
    target = tmp_path / "consumer"
    write_overlay(target)
    overlay_before = yaml.safe_load(
        (target / ".covenant-flow" / "overlay.yaml").read_text(encoding="utf-8")
    )
    assert "dsh" not in overlay_before["clients"]
    proc = subprocess.run(
        [
            str(INSTALLER),
            "--pin",
            "v1.1.0",
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
    assert (target / ".dsh" / "plugin" / "process-fsm-guard.js").is_file()
    assert (target / ".dsh" / "plugin" / "impeccable-hook.js").is_file()
    assert (target / ".dsh" / "cordis.patch.yml").is_file()
    overlay = yaml.safe_load((target / ".covenant-flow" / "overlay.yaml").read_text(encoding="utf-8"))
    assert overlay["pin"] == "v1.1.0"
    assert "dsh" not in overlay["clients"]
    agents = (target / "AGENTS.md").read_text(encoding="utf-8")
    assert "dsh" in agents
    assert "Auto dsh" not in agents
    nonempty = [ln for ln in agents.splitlines() if ln.strip()]
    assert len(nonempty) <= 40


@_SKIP_NO_INSTALLER
def test_init_template_omits_clients_dsh(tmp_path: Path):
    dest = tmp_path / "fresh"
    dest.mkdir()
    proc = subprocess.run(
        [str(INSTALLER), "--init", "--target", str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    raw = (dest / ".covenant-flow" / "overlay.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(raw)
    assert "dsh" not in data["clients"]
    assert "clients.dsh" not in raw

