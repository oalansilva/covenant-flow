from __future__ import annotations

import json
import os
import shutil
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
        "  const providers = [];\n"
        "  return {\n"
        "    events,\n"
        "    sections,\n"
        "    providers,\n"
        "    on(name, fn) { events[name] = fn; },\n"
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
    )


# Copied live rules from dsh-skill listLayerCandidates/validateCandidate/waitWithAbort
# (packages/skill/skill/src/index.ts). MUST NOT import @deepseek-ai/dsh-skill.
_FAKE_DSH_SKILL_RULES = r"""
const SKILL_NAME = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
function validateInvocation(invocation, subject) {
  if (invocation === undefined) return;
  if (typeof invocation !== "object" || invocation === null || Array.isArray(invocation)) {
    throw new TypeError(`${subject} with a non-object invocation policy`);
  }
  if (typeof invocation.modelInvocable !== "boolean") {
    throw new TypeError(`${subject} with a non-boolean invocation.modelInvocable`);
  }
  if (typeof invocation.userInvocable !== "boolean") {
    throw new TypeError(`${subject} with a non-boolean invocation.userInvocable`);
  }
}
function validateCandidate(candidate, providerName) {
  if (typeof candidate.name !== "string") {
    throw new TypeError(`skill provider "${providerName}" returned a non-string skill name`);
  }
  if (!SKILL_NAME.test(candidate.name)) {
    throw new Error(`skill provider "${providerName}" returned invalid skill name "${candidate.name}"`);
  }
  if (typeof candidate.description !== "string") {
    throw new TypeError(`skill provider "${providerName}" returned skill "${candidate.name}" with a non-string description`);
  }
  if (candidate.description.length === 0) {
    throw new Error(`skill provider "${providerName}" returned skill "${candidate.name}" without a description`);
  }
  validateInvocation(candidate.invocation, `skill provider "${providerName}" returned skill "${candidate.name}"`);
  if (candidate.whenToUse !== undefined && typeof candidate.whenToUse !== "string") {
    throw new TypeError(`skill provider "${providerName}" returned skill "${candidate.name}" with a non-string whenToUse`);
  }
  if (typeof candidate.source !== "string") {
    throw new TypeError(`skill provider "${providerName}" returned skill "${candidate.name}" with a non-string source`);
  }
  if (typeof candidate.rank !== "number" || !Number.isFinite(candidate.rank)) {
    throw new Error(`skill provider "${providerName}" returned skill "${candidate.name}" with an invalid rank`);
  }
  if (typeof candidate.provider !== "string") {
    throw new TypeError(`skill provider "${providerName}" returned skill "${candidate.name}" with a non-string provider`);
  }
  if (candidate.provider !== providerName) {
    throw new Error(`skill provider "${providerName}" returned skill "${candidate.name}" for provider "${candidate.provider}"`);
  }
  if (candidate.path !== undefined && typeof candidate.path !== "string") {
    throw new TypeError(`skill provider "${providerName}" returned skill "${candidate.name}" with a non-string path`);
  }
}
function validateDefinition(skill) {
  const name = skill.name;
  if (typeof name !== "string") throw new TypeError("loaded skill name must be a string");
  if (!SKILL_NAME.test(name)) throw new Error(`loaded skill has invalid name "${name}"`);
  if (typeof skill.description !== "string") throw new TypeError(`loaded skill "${name}" description must be a string`);
  if (skill.description.length === 0) throw new Error(`loaded skill "${name}" requires a description`);
  validateInvocation(skill.invocation, `loaded skill "${name}"`);
  if (skill.whenToUse !== undefined && typeof skill.whenToUse !== "string") {
    throw new TypeError(`loaded skill "${name}" whenToUse must be a string`);
  }
  if (typeof skill.source !== "string") throw new TypeError(`loaded skill "${name}" source must be a string`);
  if (typeof skill.provider !== "string") throw new TypeError(`loaded skill "${name}" provider must be a string`);
  if (typeof skill.content !== "string") throw new TypeError(`loaded skill "${name}" content must be a string`);
  if (skill.path !== undefined && typeof skill.path !== "string") {
    throw new TypeError(`loaded skill "${name}" path must be a string`);
  }
}
function waitWithAbort(promise, signal) {
  if (signal === undefined) return promise;
  if (signal.aborted === true) throw new Error(String(signal.reason));
  return new Promise((resolve, reject) => {
    const cleanup = () => { signal.removeEventListener("abort", onAbort); };
    const onAbort = () => { cleanup(); reject(new Error(String(signal.reason))); };
    signal.addEventListener("abort", onAbort, { once: true });
    void promise.then(
      (value) => { cleanup(); resolve(value); },
      (error) => { cleanup(); reject(error instanceof Error ? error : new Error(String(error))); },
    );
  });
}
"""


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
const moore = ctx.sections.find((s) => s.name === "covenant-flow:moore" && s.order === 50);
const agents = ctx.sections.find((s) => s.name === "covenant-flow:agents" && s.order === 40);
process.stdout.write(JSON.stringify({{
  result, nextCalled, threw,
  mooreName: moore && moore.name,
  mooreOrder: moore && moore.order,
  mooreTextType: typeof (moore && moore.text),
  agentsName: agents && agents.name,
  agentsOrder: agents && agents.order,
  agentsTextType: typeof (agents && agents.text),
}}));
"""
    proc = _node(code, cwd=repo)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["threw"] is False
    assert data["nextCalled"] is False
    assert data["result"]["kind"] == "deny"
    assert data["mooreName"] == "covenant-flow:moore"
    assert data["mooreOrder"] == 50
    assert data["mooreTextType"] == "function"
    assert data["agentsName"] == "covenant-flow:agents"
    assert data["agentsOrder"] == 40
    assert data["agentsTextType"] == "function"


def test_plugin_deny_survives_register_provider_throw(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    code = f"""
function mockThrowingCtx() {{
  const events = {{}};
  const sections = [];
  return {{
    events,
    sections,
    on(name, fn) {{ events[name] = fn; }},
    systemPrompt: {{ section(opts) {{ sections.push(opts); }} }},
    skills: {{
      registerProvider(create) {{
        create({{}});
        throw new Error("duplicate name");
      }},
    }},
  }};
}}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockThrowingCtx();
let applyThrew = false;
try {{
  apply(ctx);
}} catch (err) {{
  applyThrew = true;
}}
let nextCalled = false;
const result = await ctx.events["tools/pre-execute"](
  {{ name: "edit", arguments: {{ file_path: "backend/app/main.py" }} }},
  async () => {{ nextCalled = true; }},
);
process.stdout.write(JSON.stringify({{
  applyThrew,
  nextCalled,
  kind: result && result.kind,
}}));
"""
    proc = _node(code, cwd=repo)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["applyThrew"] is False
    assert data["nextCalled"] is False
    assert data["kind"] == "deny"


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
            "v1.1.3",
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
    assert overlay["pin"] == "v1.1.3"
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


def _boot_tree(tmp_path: Path, *, canonical_dev: str | None) -> Path:
    dest = tmp_path / "consumer"
    script_dir = dest / "scripts" / "process-fsm"
    plugin_dir = dest / ".dsh" / "plugin"
    script_dir.mkdir(parents=True)
    plugin_dir.mkdir(parents=True)
    shutil.copy2(BOOT, script_dir / "dsh_boot.sh")
    shutil.copy2(PLUGIN_GUARD, plugin_dir / "process-fsm-guard.js")
    shutil.copy2(PLUGIN_HOOK, plugin_dir / "impeccable-hook.js")
    shutil.copy2(PATCH, dest / ".dsh" / "cordis.patch.yml")
    (script_dir / "overlay.py").write_text(
        "from pathlib import Path\n"
        "import yaml\n"
        "def try_load_overlay(start, require_filled=False):\n"
        "    p = Path(start) / '.covenant-flow' / 'overlay.yaml'\n"
        "    if not p.is_file():\n"
        "        return None\n"
        "    data = yaml.safe_load(p.read_text(encoding='utf-8'))\n"
        "    return data if isinstance(data, dict) else None\n",
        encoding="utf-8",
    )
    overlay: dict = {"canonical_paths": {}}
    if canonical_dev is not None:
        overlay["canonical_paths"]["dev"] = canonical_dev
    (dest / ".covenant-flow").mkdir(parents=True)
    (dest / ".covenant-flow" / "overlay.yaml").write_text(
        yaml.safe_dump(overlay, allow_unicode=True, default_flow_style=False),
        encoding="utf-8",
    )
    return dest


def _fake_dsh_bin(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    dsh = bindir / "dsh"
    dsh.write_text(
        "#!/usr/bin/env bash\n"
        'echo "DSH_CWD=$(pwd)"\n'
        'echo "DSH_ARGS=$*"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    dsh.chmod(0o755)
    return bindir


def test_a1_apply_registers_agents_and_moore_by_name_order():
    lib = PLUGIN_LIB.read_text(encoding="utf-8")
    guard = PLUGIN_GUARD.read_text(encoding="utf-8")
    assert "import 'yaml'" not in lib and 'import "yaml"' not in lib
    assert "FileSystemSkillProvider" not in lib
    assert "FileSystemSkillProvider" not in guard
    assert "complete: true" not in guard and "complete:true" not in guard
    assert "| T0" not in guard
    assert "T0–T17" not in guard
    code = f"""
{_mock_ctx_prelude()}
import {{ apply, inject }} from {json.dumps(str(PLUGIN_GUARD))};
const ctx = mockCtx();
apply(ctx);
const agents = ctx.sections.find((s) => s.name === "covenant-flow:agents");
const moore = ctx.sections.find((s) => s.name === "covenant-flow:moore");
process.stdout.write(JSON.stringify({{
  inject,
  agentsName: agents && agents.name,
  agentsOrder: agents && agents.order,
  agentsTextType: typeof (agents && agents.text),
  agentsComplete: agents && Object.hasOwn(agents, "complete") ? agents.complete : null,
  mooreName: moore && moore.name,
  mooreOrder: moore && moore.order,
  mooreTextType: typeof (moore && moore.text),
  sectionCount: ctx.sections.length,
}}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert "systemPrompt" in data["inject"]
    assert "skills" in data["inject"]
    assert data["agentsName"] == "covenant-flow:agents"
    assert data["agentsOrder"] == 40
    assert data["agentsTextType"] == "function"
    assert data["agentsComplete"] is None
    assert data["mooreName"] == "covenant-flow:moore"
    assert data["mooreOrder"] == 50
    assert data["mooreTextType"] == "function"
    assert data["sectionCount"] == 2


def test_a2_a3_agents_stub_compiles_file_fail_open(tmp_path: Path):
    code = f"""
{_mock_ctx_prelude()}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
import {{ readAgentsStub }} from {json.dumps(str(PLUGIN_LIB))};
const ctx = mockCtx();
apply(ctx);
const agents = ctx.sections.find((s) => s.name === "covenant-flow:agents" && s.order === 40);
const present = agents.text();
const missing = readAgentsStub({json.dumps(str(tmp_path))});
process.stdout.write(JSON.stringify({{ present, missing }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert "NLU ≠ δ" in data["present"] or "Todo" in data["present"]
    assert "T0" not in data["present"]
    assert "release-guard pre" not in data["present"]
    assert data["missing"] == ""
    nonempty = [ln for ln in (REPO / "AGENTS.md").read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(nonempty) <= 40


def test_a4_a5_provider_thenables_with_signal(tmp_path: Path):
    homedir = str(Path.home())
    missing_root = tmp_path / "no-skills"
    missing_root.mkdir()
    code = f"""
{_FAKE_DSH_SKILL_RULES}
import {{ createRepoDshSkillProvider, REPO_ROOT }} from {json.dumps(str(PLUGIN_LIB))};
const homedir = {json.dumps(homedir)};
const provider = createRepoDshSkillProvider(REPO_ROOT);
const ac = new AbortController();
const listedP = provider.list({{ cwd: homedir, signal: ac.signal }});
if (!listedP || typeof listedP.then !== "function") {{
  throw new Error("list must be thenable");
}}
const listed = await waitWithAbort(listedP, ac.signal);
for (const c of listed) {{
  validateCandidate(c, "covenant-flow-process");
}}
const names = listed.map((c) => c.name);
const flow = listed.find((c) => c.name === "covenant-flow");
if (!flow) throw new Error("covenant-flow missing from list");
const skillsRoot = REPO_ROOT + "/.dsh/skills";
for (const c of listed) {{
  if (c.provider !== "covenant-flow-process") throw new Error("provider field");
  if (!c.path || !c.path.startsWith(skillsRoot)) throw new Error("path not under repo skills");
  if (c.path.startsWith(homedir) && !skillsRoot.startsWith(homedir)) {{
    throw new Error("listed a homedir skill");
  }}
}}
const gotP = provider.get(flow, {{ signal: ac.signal }});
if (!gotP || typeof gotP.then !== "function") {{
  throw new Error("get must be thenable");
}}
const defn = await waitWithAbort(gotP, ac.signal);
validateDefinition(defn);
const emptyP = createRepoDshSkillProvider({json.dumps(str(missing_root))}).list({{ cwd: homedir }});
const empty = await emptyP;
process.stdout.write(JSON.stringify({{
  cwd: process.cwd(),
  repo: REPO_ROOT,
  names,
  provider: flow.provider,
  source: flow.source,
  rank: flow.rank,
  modelInvocable: flow.invocation && flow.invocation.modelInvocable,
  userInvocable: flow.invocation && flow.invocation.userInvocable,
  path: flow.path,
  content: defn.content,
  defnProvider: defn.provider,
  defnName: defn.name,
  emptyLen: empty.length,
}}));
"""
    proc = _node(code, cwd=Path.home())
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["cwd"] != data["repo"]
    assert "covenant-flow" in data["names"]
    assert data["provider"] == "covenant-flow-process"
    assert data["source"] == "custom"
    assert data["rank"] == 300
    assert data["modelInvocable"] is True
    assert data["userInvocable"] is True
    assert data["path"].startswith(str(REPO / ".dsh" / "skills"))
    assert ".cursor/skills/covenant-flow/SKILL.md" in data["content"]
    assert "MUST Read" in data["content"]
    assert data["defnProvider"] == "covenant-flow-process"
    assert data["defnName"] == "covenant-flow"
    body = data["content"].split("---", 2)[2]
    assert len([ln for ln in body.splitlines() if ln.strip()]) <= 8
    assert data["emptyLen"] == 0
    imports = [
        ln
        for ln in Path(__file__).read_text(encoding="utf-8").splitlines()
        if ln.startswith("import ") or ln.startswith("from ")
    ]
    assert all("dsh-skill" not in ln and "dsh_skill" not in ln for ln in imports)


def test_a6_patch_yaml_has_no_skill_paths():
    text = PATCH.read_text(encoding="utf-8")
    assert ".dsh/skills" not in text
    assert "customSkillDirs" not in text
    assert "skill-filesystem" not in text
    assert "covenant-flow-process-fsm-guard" in text
    assert "covenant-flow-impeccable-hook" in text


def test_a7_boot_exits_when_dev_is_not_a_directory(tmp_path: Path):
    not_dir = tmp_path / "dev-is-a-file"
    not_dir.write_text("nope\n", encoding="utf-8")
    missing = tmp_path / "does-not-exist"
    cases = (("tree-file", not_dir), ("tree-missing", missing))
    for tree_name, path in cases:
        dest = _boot_tree(tmp_path / tree_name, canonical_dev=str(path))
        proc = subprocess.run(
            ["bash", str(dest / "scripts" / "process-fsm" / "dsh_boot.sh")],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0, proc.stdout
        assert str(path) in proc.stderr


def test_a8_empty_canonical_dev_launches_repo_root(tmp_path: Path):
    dest = _boot_tree(tmp_path, canonical_dev="")
    bindir = _fake_dsh_bin(tmp_path)
    proc = subprocess.run(
        ["bash", str(dest / "scripts" / "process-fsm" / "dsh_boot.sh")],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert f"DSH_CWD={dest.resolve()}" in proc.stdout
    boot = BOOT.read_text(encoding="utf-8")
    assert "dsh web --patch" in boot
    assert not any(ln.strip().startswith("dsh plugin add") for ln in boot.splitlines())
    code_lines = [
        ln for ln in boot.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert not any("workspace" in ln.lower() for ln in code_lines)


def test_a9_directory_canonical_dev_still_preferred(tmp_path: Path):
    launch = tmp_path / "dev-root"
    launch.mkdir()
    dest = _boot_tree(tmp_path, canonical_dev=str(launch))
    bindir = _fake_dsh_bin(tmp_path)
    proc = subprocess.run(
        ["bash", str(dest / "scripts" / "process-fsm" / "dsh_boot.sh")],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PATH": f"{bindir}{os.pathsep}{os.environ.get('PATH', '')}"},
    )
    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert f"DSH_CWD={launch.resolve()}" in proc.stdout
    assert "web --patch" in proc.stdout


def test_a10_apply_registered_provider_survives_wait_with_abort():
    homedir = str(Path.home())
    code = f"""
{_mock_ctx_prelude()}
{_FAKE_DSH_SKILL_RULES}
import {{ apply }} from {json.dumps(str(PLUGIN_GUARD))};
import {{ REPO_ROOT }} from {json.dumps(str(PLUGIN_LIB))};
const ctx = mockCtx();
apply(ctx);
const provider = ctx.providers[0];
if (!provider || provider.name !== "covenant-flow-process") {{
  throw new Error("expected registered covenant-flow-process");
}}
const ac = new AbortController();
const listed = await waitWithAbort(
  provider.list({{ cwd: {json.dumps(homedir)}, signal: ac.signal }}),
  ac.signal,
);
for (const c of listed) validateCandidate(c, "covenant-flow-process");
process.stdout.write(JSON.stringify({{
  name: provider.name,
  names: listed.map((c) => c.name),
  factorySync: true,
}}));
"""
    proc = _node(code, cwd=Path.home())
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["name"] == "covenant-flow-process"
    assert "covenant-flow" in data["names"]
    lib = PLUGIN_LIB.read_text(encoding="utf-8")
    assert "from 'yaml'" not in lib and 'from "yaml"' not in lib
    assert "@deepseek-ai/dsh-skill" not in lib
    assert "deepseek-harness" not in PLUGIN_GUARD.read_text(encoding="utf-8")

