from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from opencode_stubs import stub_errors  # noqa: E402
from paging import page  # noqa: E402
from test_overlay_fixtures import write_overlay  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TODO_STUB = "Próximo evento = iniciar_design. Não apply. Não /opsx:new ainda."
PLAYBOOK = ("release-guard", "subir lote", "deploy PROD")
PLUGIN_GUARD = REPO / ".opencode" / "plugin" / "process-fsm-guard.js"
PLUGIN_HOOK = REPO / ".opencode" / "plugin" / "impeccable-hook.js"
PLUGIN_LIB = REPO / "scripts" / "process-fsm" / "opencode_plugin_lib.js"


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


def test_g13_opencode_page_body_injectable():
    result = page(
        cwd=".",
        resolve_fn=_resolve("720", "card-720-opencode-three-adapters"),
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
    assert "experimental.chat.system.transform" in text
    assert "system.push" in text
    assert "process-fsm-page.md" not in text
    assert "MUST Read" not in text


def test_g14_detector_mapping_and_exit_zero():
    code = f"""
import {{ mapAfterPayload, mapIdlePayload, runHookMjs }} from {json.dumps(str(PLUGIN_LIB))};
const after = mapAfterPayload({{
  tool: "edit",
  args: {{ filePath: "frontend/src/x.tsx" }},
}});
const idle = mapIdlePayload();
const status = runHookMjs(after, {json.dumps(str(REPO))});
process.stdout.write(JSON.stringify({{ after, idle, status }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["after"]["file_path"] == "frontend/src/x.tsx"
    assert data["after"]["hook_event_name"] == "PostToolUse"
    assert data["idle"]["hook_event_name"] == "Stop"
    assert data["status"] == 0


def test_plugin_throw_on_deny_not_json_permission(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    code = f"""
import plugin from {json.dumps(str(PLUGIN_GUARD))};
const hooks = await plugin({{ directory: {json.dumps(str(repo))}, worktree: {json.dumps(str(repo))} }});
let threw = false;
let message = "";
try {{
  await hooks["tool.execute.before"](
    {{ tool: "edit", sessionID: "s", callID: "c" }},
    {{ args: {{ filePath: "backend/app/main.py" }} }},
  );
}} catch (err) {{
  threw = true;
  message = String(err && err.message ? err.message : err);
}}
process.stdout.write(JSON.stringify({{ threw, message }}));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["threw"] is True
    assert "deny" in data["message"]
    assert '"permission"' not in data["message"]


def test_plugin_does_not_throw_on_openspec_design(tmp_path: Path):
    repo = tmp_path / "card"
    rel = "openspec/changes/card-720-opencode-three-adapters/design.md"
    _init_repo(repo, "card-720-opencode-three-adapters", rel)
    code = f"""
import {{ runGuard, assertAllow }} from {json.dumps(str(PLUGIN_LIB))};
const decision = runGuard({{
  tool: "edit",
  args: {{ filePath: {json.dumps(rel)} }},
  cwd: {json.dumps(str(repo))},
  status: "Design",
}});
assertAllow(decision, "edit");
process.stdout.write(JSON.stringify(decision));
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["permission"] == "allow"
    assert data["decision"] == "allow"


def test_detector_plugin_never_throws():
    code = f"""
import plugin from {json.dumps(str(PLUGIN_HOOK))};
const hooks = await plugin({{ directory: {json.dumps(str(REPO))} }});
await hooks["tool.execute.after"]({{ tool: "edit", args: {{ filePath: "frontend/src/x.tsx" }} }});
await hooks.event({{ event: {{ type: "session.idle", properties: {{ sessionID: "s" }} }} }});
process.stdout.write("ok");
"""
    proc = _node(code)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "ok"


def test_opencode_plugins_export_only_default():
    """1.18.18 treats every named export as a plugin constructor after readV1Plugin."""
    for path in (PLUGIN_GUARD, PLUGIN_HOOK):
        code = f"""
import * as ns from {json.dumps(str(path))};
process.stdout.write(JSON.stringify(Object.keys(ns).sort()));
"""
        proc = _node(code)
        assert proc.returncode == 0, proc.stderr
        keys = json.loads(proc.stdout)
        assert set(keys) <= {"default"}, (path.name, keys)
        assert "default" in keys
        text = path.read_text(encoding="utf-8")
        assert "export default" in text
        assert "export function" not in text
        assert "export const" not in text
        assert "export {" not in text


def test_g16_opencode_tree_has_no_opsx_or_second_law():
    opencode = REPO / ".opencode"
    assert PLUGIN_GUARD.is_file()
    assert PLUGIN_HOOK.is_file()
    assert not (REPO / "opencode.json").exists()
    assert not (opencode / "plugins").exists()
    for folder in ("command", "commands"):
        assert not (opencode / folder).exists()
    blob = ""
    for path in opencode.rglob("*"):
        if path.is_file():
            blob += path.read_text(encoding="utf-8", errors="replace")
            blob += "\n" + path.name
    assert "opsx-" not in blob
    assert "| T0" not in blob
    assert "T0–T17" not in blob and "T0-T17" not in blob
    assert "I1–I9" not in blob


def test_opencode_stubs_match_cursor_skills():
    errors = stub_errors()
    assert errors == []
    stub = (REPO / ".opencode" / "skills" / "covenant-flow" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert ".cursor/skills/covenant-flow/SKILL.md" in stub
    assert "MUST Read" in stub
    body = stub.split("---", 2)[2]
    assert len([ln for ln in body.splitlines() if ln.strip()]) <= 8
    assert not (REPO / ".opencode" / "skills" / "impeccable" / "SKILL.md").exists()
    assert not (REPO / ".opencode" / "skills" / "design-critic" / "SKILL.md").exists()


def test_grok_impeccable_adapter_is_executable():
    adapter = REPO / ".grok" / "hooks" / "impeccable.sh"
    assert adapter.is_file()
    assert adapter.stat().st_mode & stat.S_IXUSR
    text = adapter.read_text(encoding="utf-8")
    assert "hook.mjs" in text
    assert "PostToolUse" in text
