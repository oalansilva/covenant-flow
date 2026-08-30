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

from fsm import load_fsm  # noqa: E402
from grok_stubs import stub_errors  # noqa: E402
from overlay import render_agents  # noqa: E402
from paging import UNBOUND_PAGE, page, write_grok_page  # noqa: E402
from resolve import UNBOUND  # noqa: E402
from test_overlay_fixtures import filled_overlay_dict  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TODO_STUB = "Próximo evento = iniciar_design. Não apply. Não /opsx:new ainda."
HOMOLOGADO_STUB = "T16 = process_event fechar_release com M_lote live. Chat ≠ δ."
PLAYBOOK = ("release-guard", "subir lote", "deploy PROD")


def _silent(_bound: str | None) -> str | None:
    raise AssertionError(f"github called bound={_bound}")


def _resolve(bound: str, git: str) -> object:
    def inner(cwd, path, issue_id=None, status=None):
        return {"q": None, "bound_card": bound, "q_git": git}

    return inner


def _provider(status: str | None):
    def inner(bound: str | None) -> str | None:
        assert bound == "613"
        return status

    return inner


def _line_count(text: str) -> int:
    return len(text.splitlines())


def test_todo_page_omits_release_playbook():
    result = page(
        cwd=".",
        resolve_fn=_resolve("613", "card-613-process-fsm-paging"),
        status_provider=_provider("Todo"),
    )
    ctx = result["additional_context"]
    assert TODO_STUB in ctx
    assert "q=Todo" in ctx
    assert "bound_card=613" in ctx
    for needle in PLAYBOOK:
        assert needle not in ctx
    assert _line_count(ctx) <= 20


def test_homologado_page_is_not_release_playbook():
    result = page(
        cwd=".",
        resolve_fn=_resolve("613", "card-613-process-fsm-paging"),
        status_provider=_provider("Homologado"),
    )
    ctx = result["additional_context"]
    assert HOMOLOGADO_STUB in ctx
    assert "release-guard pre" not in ctx
    assert "release-guard post" not in ctx
    assert "deploy PROD" not in ctx
    assert _line_count(ctx) <= 20


def test_unbound_does_not_load_homologado():
    result = page(
        cwd=".",
        resolve_fn=_resolve(UNBOUND, "develop"),
        status_provider=_silent,
    )
    ctx = result["additional_context"]
    assert UNBOUND_PAGE in ctx
    assert HOMOLOGADO_STUB not in ctx
    for needle in PLAYBOOK:
        assert needle not in ctx
    assert "bound_card=⊥" in ctx


def test_missing_status_is_unbound_stub():
    result = page(
        cwd=".",
        resolve_fn=_resolve("613", "card-613-process-fsm-paging"),
        status_provider=_provider(None),
    )
    ctx = result["additional_context"]
    assert UNBOUND_PAGE in ctx
    assert HOMOLOGADO_STUB not in ctx


def test_page_uses_yaml_stubs():
    fsm = load_fsm()
    assert TODO_STUB in str(fsm["context_file"]["Todo"])
    assert HOMOLOGADO_STUB in str(fsm["context_file"]["Homologado"])
    assert "grill-card" in str(fsm["context_file"]["Em Refinamento"])
    assert "sintetizar" in str(fsm["context_file"]["Design"])


def _harness_body_lines() -> list[str]:
    text = (REPO / ".cursor" / "rules" / "harness.mdc").read_text(encoding="utf-8")
    assert text.startswith("---")
    rest = text[3:]
    end = rest.find("\n---")
    body = rest[end + 4 :] if end != -1 else rest
    return [ln for ln in body.splitlines() if ln.strip()]


def test_harness_mdc_body_budget():
    lines = _harness_body_lines()
    text = "\n".join(lines)
    assert 4 <= len(lines) <= 12
    assert "inherit" in text or ".cursor/hooks.json" in text
    assert "T1/T7/T15" not in text
    assert "diff-reviewer" not in text
    assert "release-guard" not in text
    assert "Grok Auto" not in text
    assert "Auto permitido" not in text


def test_agents_md_is_stub():
    text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    nonempty = [ln for ln in text.splitlines() if ln.strip()]
    assert len(nonempty) <= 40
    overlay_path = REPO / ".covenant-flow" / "overlay.yaml"
    if overlay_path.is_file():
        import yaml

        data = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
        doc = str(data.get("overlay_doc") or "").strip()
        if doc:
            assert doc in text
        board = data.get("board") or {}
        owner = str(board.get("owner") or "").strip()
        number = board.get("number")
        if owner and isinstance(number, int):
            assert f"github.com/users/{owner}/projects/{number}" in text
    else:
        assert "docs/crypto-overlay.md" not in text
        assert "covenant-flow" in text
        assert "overlay_doc" in text
    assert "scripts/release-guard pre" not in text
    assert "Em Refinamento -> Todo -> Design" not in text
    assert "(q, bound_card, q_git)" in text
    assert "T1/T7/T15" in text
    assert "Cursor Agent" in text and "Grok Build" in text and "OpenCode" in text
    assert "dsh" in text
    assert "não always-on" not in text
    assert "Grok Auto" not in text
    assert "OpenCode Auto" not in text
    assert "Auto OpenCode" not in text
    assert "Auto Grok" not in text
    assert "Auto dsh" not in text
    assert "dsh Auto" not in text
    assert "cooperativo" in text
    assert "T0–T17" not in text and "T0-T17" not in text
    generated = render_agents(filled_overlay_dict())
    assert filled_overlay_dict()["clients"]["cursor"]["auto"] is True
    assert (
        "Clientes: Cursor Agent (cooperativo); Grok Build, OpenCode e dsh "
        "(cooperativos até ensaio deny na branch de integração)."
    ) in generated
    assert (
        "Não reivindique modo Auto no Cursor, no Grok, no OpenCode nem no dsh."
    ) in generated
    assert "Auto permitido" not in generated
    assert "Auto Grok" not in generated
    assert "Auto OpenCode" not in generated
    assert "Auto dsh" not in generated
    assert len([ln for ln in generated.splitlines() if ln.strip()]) <= 40


def test_skill_priority_anchor():
    text = (REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md").read_text(encoding="utf-8")
    assert "δ e Guard > overlay > skill > wording" in text
    assert "1. Instrução direta de Alan no chat." not in text


def test_hooks_json_session_start():
    hooks = json.loads((REPO / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    start = hooks["hooks"]["sessionStart"]
    assert start[0]["command"] == ".cursor/hooks/process-fsm-session-start.sh"
    assert start[0].get("failClosed") is not True
    pre = hooks["hooks"]["preToolUse"]
    assert pre[0]["command"] == ".cursor/hooks/process-fsm-guard.sh"
    assert pre[0]["failClosed"] is True
    assert hooks["hooks"]["beforeShellExecution"][0]["command"] == ".cursor/hooks/process-fsm-guard.sh"
    assert hooks["hooks"]["afterFileEdit"][0]["command"].endswith("impeccable.sh afterFileEdit")
    assert hooks["hooks"]["stop"][0]["command"].endswith("impeccable.sh stop")
    assert (REPO / ".cursor" / "hooks" / "impeccable.sh").is_file()
    adapter = REPO / ".cursor" / "hooks" / "process-fsm-session-start.sh"
    assert adapter.is_file()
    assert adapter.stat().st_mode & stat.S_IXUSR


def test_session_start_adapter_prefers_venv():
    text = (REPO / ".cursor" / "hooks" / "process-fsm-session-start.sh").read_text(encoding="utf-8")
    assert 'ROOT/backend/.venv/bin/python' in text
    assert "command -v python3" in text


def test_session_start_adapter_fallback(tmp_path: Path):
    hooks = tmp_path / ".cursor" / "hooks"
    hooks.mkdir(parents=True)
    src = (REPO / ".cursor" / "hooks" / "process-fsm-session-start.sh").read_text(encoding="utf-8")
    script = hooks / "process-fsm-session-start.sh"
    script.write_text(src, encoding="utf-8")
    script.chmod(0o755)
    proc = subprocess.run(
        [str(script)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        check=False,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    ctx = data["additional_context"]
    assert UNBOUND_PAGE in ctx
    assert "docs/crypto-overlay.md" not in ctx
    assert "release-guard" not in ctx


def test_write_grok_page_todo(tmp_path: Path):
    dest = tmp_path / ".grok" / "rules" / "process-fsm-page.md"
    write_grok_page(
        cwd=tmp_path,
        dest=dest,
        resolve_fn=_resolve("613", "card-613-process-fsm-paging"),
        status_provider=_provider("Todo"),
    )
    text = dest.read_text(encoding="utf-8")
    assert TODO_STUB in text
    assert "q=Todo" in text
    for needle in PLAYBOOK:
        assert needle not in text
    assert _line_count(text) <= 20


def test_gitignore_skips_generated_page():
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert ".grok/rules/process-fsm-page.md" in text
    assert (REPO / ".grok" / "rules" / "00-harness.md").is_file()
    harness = (REPO / ".grok" / "rules" / "00-harness.md").read_text(encoding="utf-8")
    assert "MUST Read" in harness
    assert "process-fsm-page.md" in harness
    assert "| T0" not in harness
    assert "### Requirement:" not in harness


def test_grok_skill_stubs_match_canonical():
    errors = stub_errors()
    assert errors == []
    stub = (REPO / ".grok" / "skills" / "covenant-flow" / "SKILL.md").read_text(encoding="utf-8")
    assert ".cursor/skills/covenant-flow/SKILL.md" in stub
    assert "Em Refinamento → Todo → Design" not in stub
    body = stub.split("---", 2)[2]
    assert len([ln for ln in body.splitlines() if ln.strip()]) <= 8


def test_stale_stub_fails_check():
    dest = REPO / ".grok" / "skills" / "covenant-flow" / "SKILL.md"
    original = dest.read_text(encoding="utf-8")
    dest.write_text("stale\n", encoding="utf-8")
    try:
        assert stub_errors()
    finally:
        dest.write_text(original, encoding="utf-8")


def test_agents_extra_grok_stubs_point_at_agents_skills():
    errors = stub_errors()
    assert errors == []
    critic = (REPO / ".grok" / "skills" / "design-critic" / "SKILL.md").read_text(encoding="utf-8")
    assert ".agents/skills/design-critic/SKILL.md" in critic
    assert ".cursor/skills/design-critic" not in critic
    body = critic.split("---", 2)[2]
    assert len([ln for ln in body.splitlines() if ln.strip()]) <= 8
    assert "Em Refinamento → Todo → Design" not in critic
    assert "context -> shape -> prototype" not in critic
    impeccable = (REPO / ".grok" / "skills" / "impeccable" / "SKILL.md").read_text(encoding="utf-8")
    assert ".agents/skills/impeccable/SKILL.md" in impeccable
    body_i = impeccable.split("---", 2)[2]
    assert len([ln for ln in body_i.splitlines() if ln.strip()]) <= 8
    alan = (REPO / ".grok" / "skills" / "covenant-flow" / "SKILL.md").read_text(encoding="utf-8")
    assert ".cursor/skills/covenant-flow/SKILL.md" in alan


def test_missing_agents_stub_fails_check():
    dest = REPO / ".grok" / "skills" / "design-critic" / "SKILL.md"
    original = dest.read_text(encoding="utf-8")
    dest.unlink()
    try:
        errors = stub_errors()
        assert any("design-critic" in item and "missing" in item for item in errors)
    finally:
        dest.write_text(original, encoding="utf-8")


def test_stale_agents_stub_fails_check():
    dest = REPO / ".grok" / "skills" / "impeccable" / "SKILL.md"
    original = dest.read_text(encoding="utf-8")
    dest.write_text("stale\n", encoding="utf-8")
    try:
        assert stub_errors()
    finally:
        dest.write_text(original, encoding="utf-8")


def test_apply_skill_does_not_dump_every_context_file():
    skill = (REPO / ".cursor" / "skills" / "openspec-apply-change" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    command = (REPO / ".cursor" / "commands" / "opsx-apply.md").read_text(encoding="utf-8")
    for text in (skill, command):
        assert "Read every file path listed under `contextFiles`" not in text
        assert "Always read context files before starting" not in text
        assert ".impeccable/critique/" in text
        assert "## Apply contract" in text


def test_design_critic_forbids_nielsen_table_and_full_brief_in_design_md():
    text = (REPO / ".agents" / "skills" / "design-critic" / "SKILL.md").read_text(encoding="utf-8")
    assert "Nielsen" in text
    assert "design.md" in text
    assert "Proibido tabela Nielsen" in text
    assert "Brief/Critique/Audit/Trace integrais" in text
    assert ".impeccable/critique/" in text


def test_grok_session_start_script_exists():
    adapter = REPO / ".grok" / "hooks" / "process-fsm-session-start.sh"
    assert adapter.is_file()
    assert adapter.stat().st_mode & stat.S_IXUSR
    text = adapter.read_text(encoding="utf-8")
    assert "--write-grok-page" in text
    wrapper = REPO / ".grok" / "hooks" / "process-fsm-guard.sh"
    assert wrapper.is_file()
    assert wrapper.stat().st_mode & stat.S_IXUSR


def test_write_grok_page_cli_uses_repo_root(tmp_path: Path):
    paging = REPO / "scripts" / "process-fsm" / "paging.py"
    proc = subprocess.run(
        [sys.executable, str(paging), "--write-grok-page"],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    generated = REPO / ".grok" / "rules" / "process-fsm-page.md"
    assert generated.is_file()
    generated.unlink(missing_ok=True)
