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

from adapter_manifest import ENTRYPOINTS  # noqa: E402
from fsm import load_fsm  # noqa: E402
from grok_stubs import stub_errors  # noqa: E402
from overlay import render_agents  # noqa: E402
from graphql_quota import GraphQLQuotaError  # noqa: E402
from paging import UNBOUND_PAGE, page, unread_page, write_grok_page  # noqa: E402
from resolve import UNBOUND  # noqa: E402
from shim_fixtures import registered_account, registered_document, shim_call  # noqa: E402
from test_overlay_fixtures import filled_overlay_dict  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

TODO_STUB = "Próximo evento = iniciar_design. Não apply. Não /opsx:new ainda."
HOMOLOGADO_STUB = "T16 = process_event fechar_release com M_lote live. Chat ≠ δ."
QA_STUB = "MUST NOT process_event"
PLAYBOOK = ("release-guard", "subir lote", "deploy PROD")
UNBOUND_DUMP = ("release-guard", "deploy PROD")
OLD_PLAYBOOK_ORDER = "Não carregue playbook de release."


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
    assert "Write produto deny" in ctx
    assert OLD_PLAYBOOK_ORDER not in ctx
    assert "suba a release" in ctx
    assert "fechar release" in ctx
    assert "carregue overlay" in ctx
    assert "inicie T16" in ctx
    assert "enabled_events: (unbound)" in ctx
    assert _line_count(ctx) <= 20
    for needle in UNBOUND_DUMP:
        assert needle not in ctx
    assert "bound_card=⊥" in ctx


def test_missing_status_is_unbound_stub():
    result = page(
        cwd=".",
        resolve_fn=_resolve("613", "card-613-process-fsm-paging"),
        status_provider=_provider(None),
    )
    ctx = result["additional_context"]
    assert UNBOUND_PAGE not in ctx
    assert "bound_card=⊥" not in ctx
    assert "bound_card=613" in ctx
    assert "Status unread" in ctx
    assert OLD_PLAYBOOK_ORDER in ctx
    assert HOMOLOGADO_STUB not in ctx
    for needle in PLAYBOOK:
        assert needle not in ctx
    assert _line_count(ctx) <= 20
    assert result["bound_card"] == "613"
    assert unread_page("613") in ctx


def test_bound_graphql_quota_zero_is_not_unbound():
    reset = "2026-09-03T02:55:52Z"

    def quota(_bound: str | None) -> str | None:
        raise GraphQLQuotaError(0, reset)

    result = page(
        cwd=".",
        resolve_fn=_resolve("820", "card-820-graphql-quota-rest"),
        status_provider=quota,
    )
    ctx = result["additional_context"]
    assert UNBOUND_PAGE not in ctx
    assert "bound_card=⊥" not in ctx
    assert "bound_card=820" in ctx
    assert "Status unread" in ctx
    assert reset in ctx
    assert HOMOLOGADO_STUB not in ctx
    for needle in PLAYBOOK:
        assert needle not in ctx
    assert _line_count(ctx) <= 20
    assert result["bound_card"] == "820"
    assert unread_page("820", reset) in ctx
    assert OLD_PLAYBOOK_ORDER in ctx


def test_unread_page_keeps_old_playbook_order():
    stub = unread_page("821")
    assert OLD_PLAYBOOK_ORDER in stub
    assert stub != UNBOUND_PAGE
    assert "bound_card=821" in stub

    def unread_821(bound: str | None) -> str | None:
        assert bound == "821"
        return None

    result = page(
        cwd=".",
        resolve_fn=_resolve("821", "card-821-dsh-unbound-t16-moore"),
        status_provider=unread_821,
    )
    ctx = result["additional_context"]
    header = ctx.split("---", 1)[0]
    assert "bound_card=⊥" not in header
    assert "bound_card=821" in header
    assert UNBOUND_PAGE not in ctx
    assert OLD_PLAYBOOK_ORDER in ctx
    assert unread_page("821") in ctx


def test_page_uses_yaml_stubs():
    fsm = load_fsm()
    assert TODO_STUB in str(fsm["context_file"]["Todo"])
    assert HOMOLOGADO_STUB in str(fsm["context_file"]["Homologado"])
    assert "grill-card" in str(fsm["context_file"]["Em Refinamento"])
    assert "sintetizar" in str(fsm["context_file"]["Design"])
    qa = str(fsm["context_file"]["QA"])
    assert QA_STUB in qa
    assert "T14" in qa
    assert "no_pr" in qa
    assert "sync: dirty" in qa


def test_codex_page_routes_reviewers_to_codex_without_changing_cursor_page():
    codex = page(
        cwd=".",
        client="codex",
        resolve_fn=_resolve("613", "card-613-process-fsm-paging"),
        status_provider=_provider("Code Review"),
    )["additional_context"]
    cursor = page(
        cwd=".",
        resolve_fn=_resolve("613", "card-613-process-fsm-paging"),
        status_provider=_provider("Code Review"),
    )["additional_context"]

    assert "Cliente ativo: Codex CLI" in codex
    assert "Agents nativos do Codex" in codex
    assert "`diff-reviewer` e `code-reviewer`" in codex
    assert "ambos `sandbox_mode=read-only` recebem o mesmo" in codex
    assert "fonte autoritativa da cadeia principal/coordenador/filhos" in codex
    assert "read-only desde o nascimento" in codex
    assert "Sem prova, modo diferente ou trace indisponível, recuse visivelmente antes de qualquer spawn" in codex
    assert "O `sandbox_mode` do Agent configura só o filho e não prova nem altera o sandbox do turno pai" in codex
    assert "O principal permanece gravável, sem alternância manual de permissões" in codex
    assert "`/permissions`" not in codex
    assert "`codex exec --sandbox read-only`" in codex
    assert "até ambos retornarem `completed` com payload" in codex
    assert "registra proxies via `codex_proxy.py`" in codex
    assert "metadados observados de runtime/trace e retorno, nunca inferidos" in codex
    assert "use a captura local de nascimento, sem fallback" in codex
    assert "`codex_review_session.py prepare`" in codex
    assert "parent/turno unavailable só se resolvem das fontes reais" in codex
    assert "Coordenador novo qualifica contexto opção 2 e os dois perfis/probes diagnósticos na própria sessão" in codex
    assert "Retomadas nativas conservam read-only; só o principal persiste" in codex
    assert "Perfis permitem só a tentativa do helper em fixture descartável, exigindo deny/readback antes do parecer" in codex
    assert "scripts/process-fsm/review_process_checklist.py" in codex
    assert "`review_diff_path` e SHA-256" in codex
    assert "`codex/execucao` da escolha local" in codex
    assert "Cursor Task, `cursor-agent` ou Composer" in codex
    codex_order = [
        codex.index("o pai/orquestrador gravável primeiro materializa"),
        codex.index("Depois inicia uma sessão Codex CLI dedicada"),
        codex.index("Nessa sessão, no mesmo turno"),
        codex.index("Mantenha essa sessão `read-only`"),
        codex.index("Após os dois retornos, o pai/orquestrador gravável registra proxies"),
        codex.index("Então executa `verify-wave`"),
        codex.index("Faça commit apenas depois de `verify-wave`"),
    ]
    assert codex_order == sorted(codex_order)
    assert "Cliente ativo: Codex CLI" not in cursor
    assert "Agent nativo do Codex" not in cursor

    skill = (REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    codex_protocol = skill.split("Protocolo por filho:", 1)[1].split("\n\n", 1)[0]
    review_contract = (
        skill.split("No Code Review, o principal permanece gravável", 1)[1]
        .lstrip("\n")
        .split("\n\n**Diff grande e saída:**", 1)[0]
    )
    assert "ordem de preparação gravável, onda nativa `read-only` e persistência gravável" in codex_protocol
    assert "`sandbox_mode=read-only` em `.codex/agents/*.toml` é declaração de perfil; não comprova nem altera permissões efetivas" in codex_protocol
    assert "coordenador Codex dedicado automático **read-only desde o nascimento**" in review_contract
    assert "nem pedir alternância manual de permissões" in review_contract
    assert "Fonte ausente ou qualificação incompleta bloqueia antes de trabalho de produto" in review_contract
    assert "ambos** Agents nativos no mesmo turno" in review_contract
    assert "`diff-reviewer` e `code-reviewer`, filhos distintos" in review_contract
    assert "capturas próprias e mesmo path/SHA" in review_contract
    assert "dois probes diagnósticos em perfis nomeados" in review_contract
    assert "exigindo deny/readback antes do parecer" in review_contract
    assert "Coordenador/filhos mantêm read-only até completed e ambos payloads" in review_contract
    assert "Principal gravável coleta/proxy pelos envelopes/capturas originais" in review_contract
    assert "cadeia principal→coordenador→filhos" in review_contract
    assert "não reescreve traces nem fabrica receipt posterior" in review_contract
    assert "dois perfis/filhos, turno do coordenador, pacote/diff/SHA, seleção/contexto e read-only/probes" in review_contract
    assert "Persistência roda no principal comprovado" in review_contract
    assert "`review_process_checklist.py`; commit só com ambos PASS" in review_contract
    skill_order = [
        review_contract.index("Principal materializa/verifica diff exato e SHA"),
        review_contract.index("Coordenador novo não herda qualificação do principal"),
        review_contract.index("coordenador verifica pacote/preflight/Status vivos"),
        review_contract.index("Principal gravável coleta/proxy"),
        review_contract.index("`codex_review.py verify-wave` revalida cadeia"),
        review_contract.index("Depois `review_process_checklist.py`; commit só com ambos PASS"),
    ]
    assert skill_order == sorted(skill_order)


def test_design_stub_names_openspec_prototype_allow():
    fsm = load_fsm()
    stub = str(fsm["context_file"]["Design"])
    assert "sintetizar" in stub
    assert "não reentrevistar" in stub
    assert "OpenSpec/protótipo allow" in stub
    assert "Write produto deny" in stub
    assert stub.strip() != "Write produto deny"
    assert list(fsm["enabled_tools"]["Design"]) == [
        "write_openspec",
        "write_prototype",
        "gist",
        "task_critique",
    ]


def test_design_page_carries_openspec_allow_carveout():
    result = page(
        cwd=".",
        resolve_fn=_resolve("613", "card-899-dsh-design-moore-stub"),
        status_provider=_provider("Design"),
    )
    ctx = result["additional_context"]
    assert "sintetizar" in ctx
    assert "não reentrevistar" in ctx
    assert "OpenSpec/protótipo allow" in ctx
    assert "Write produto deny" in ctx
    assert "q=Design" in ctx
    assert "enabled_events" in ctx
    assert "enabled_tools" not in ctx
    assert _line_count(ctx) <= 20


def test_qa_page_has_closeout_stub():
    result = page(
        cwd=".",
        resolve_fn=_resolve("613", "card-613-process-fsm-paging"),
        status_provider=_provider("QA"),
    )
    ctx = result["additional_context"]
    assert QA_STUB in ctx
    assert "T14" in ctx
    assert "no_pr" in ctx
    assert "sync: dirty" in ctx
    assert "pending" in ctx
    assert _line_count(ctx) <= 20


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
    assert "juízo" in text and "execução" in text
    assert "Task `inherit`" not in text
    assert "every Task inherits" not in text
    assert "herdar o picker" not in text
    assert "T1, T2, T6, T7, T15, T18" not in text and "T1/T7/T15" not in text
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
    assert "Portões do Alan: T1, T2, T6, T7, T15, T18" in text and "T1/T7/T15" not in text
    assert "Texto livre é wording; comando exato capturado fora do agente é evento do Alan." in text
    assert "Chat é wording" not in text
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
        "Clientes: Cursor Agent (cooperativo); Codex CLI (cooperativo; hooks só após trust review); "
        "Grok Build, OpenCode e dsh (cooperativos até ensaio deny na branch de integração)."
    ) in generated
    assert (
        "Não reivindique modo Auto no Cursor, no Codex, no Grok, no OpenCode nem no dsh."
    ) in generated
    assert "Auto permitido" not in generated
    assert "Auto Grok" not in generated
    assert "Auto OpenCode" not in generated
    assert "Auto dsh" not in generated
    assert len([ln for ln in generated.splitlines() if ln.strip()]) <= 40


def test_skill_t18_destape_resume_and_release_picker():
    text = (REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md").read_text(encoding="utf-8")
    assert "Destape/resume mantém captura de nascimento" in text
    assert "Release/lote — chat pai execução" in text
    assert ".cursor/model-map.yaml" in text
    assert "composer-2.5-fast" in text
    assert "lista fechada isolada" in text


def test_skill_priority_anchor():
    text = (REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md").read_text(encoding="utf-8")
    assert "δ e Guard > overlay > skill > wording" in text
    assert "1. Instrução direta de Alan no chat." not in text
    release = text.split("## Release", 1)[1].split("## ", 1)[0]
    assert "bound_card=⊥" in release
    assert "enabled_events: (unbound)" in release
    assert "não deny de T16" in release
    assert "covenant-flow-environments" in release
    assert "Write de produto continua deny" in release


def test_qa_closeout_skill_is_client_labeled():
    text = (REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md").read_text(encoding="utf-8")
    assert "Cursor" in text
    assert "dsh" in text
    assert "MUST NOT" in text and "process_event" in text
    assert "mesmo turno" in text
    assert "qa-gate" in text
    assert "no_pr" in text
    assert "sync: dirty" in text
    dsh = (REPO / ".dsh" / "skills" / "covenant-flow" / "SKILL.md").read_text(encoding="utf-8")
    grok = (REPO / ".grok" / "skills" / "covenant-flow" / "SKILL.md").read_text(encoding="utf-8")
    for stub in (dsh, grok):
        body = stub.split("---", 2)[2]
        assert len([ln for ln in body.splitlines() if ln.strip()]) <= 8
        assert "Em Refinamento → Todo → Design" not in stub
    plugin = (REPO / ".dsh" / "plugin" / "process-fsm-guard.js").read_text(encoding="utf-8")
    assert "covenant-flow:moore" in plugin
    assert "T0–T17" not in plugin and "T0-T17" not in plugin


def test_account_registration_session_start(monkeypatch, tmp_path: Path):
    # The consumer has no `.cursor/hooks.json` of Covenant Flow after the account-registration pin: the entries live in
    # the operator's `~/.cursor/hooks.json` (written by `install.sh --account`, here in a tmp HOME) and call the shim,
    # which runs the pinned `.cursor/hooks/*.sh` the manifest names for the event.
    registered_account(monkeypatch, tmp_path, ["cursor"])
    hooks = registered_document("cursor")["hooks"]
    start = hooks["sessionStart"]
    assert shim_call(start[0]["command"]) == ("cursor", "session-start")
    assert start[0].get("failClosed") is not True
    assert ENTRYPOINTS["cursor"]["session-start"] == ["bash", ".cursor/hooks/process-fsm-session-start.sh"]
    pre = hooks["preToolUse"]
    assert shim_call(pre[0]["command"]) == ("cursor", "guard")
    assert pre[0]["failClosed"] is True
    assert ENTRYPOINTS["cursor"]["guard"] == ["bash", ".cursor/hooks/process-fsm-guard.sh"]
    assert shim_call(hooks["beforeShellExecution"][0]["command"]) == ("cursor", "guard")
    after = hooks["afterFileEdit"][0]["command"]
    stop = hooks["stop"][0]["command"]
    assert shim_call(after) == ("cursor", "impeccable-after-file-edit")
    assert shim_call(stop) == ("cursor", "impeccable-stop")
    assert ENTRYPOINTS["cursor"]["impeccable-after-file-edit"] == ["bash", ".cursor/hooks/impeccable.sh", "afterFileEdit"]
    assert ENTRYPOINTS["cursor"]["impeccable-stop"] == ["bash", ".cursor/hooks/impeccable.sh", "stop"]
    assert (REPO / ".cursor" / "hooks" / "impeccable.sh").is_file()
    adapter = REPO / ".cursor" / "hooks" / "process-fsm-session-start.sh"
    assert adapter.is_file()
    assert adapter.stat().st_mode & stat.S_IXUSR
    destape = hooks["subagentStop"]
    assert shim_call(destape[0]["command"]) == ("cursor", "subagent-stop")
    assert ENTRYPOINTS["cursor"]["subagent-stop"] == ["bash", ".cursor/hooks/process-fsm-subagent-stop.sh"]
    matcher = destape[0]["matcher"]
    assert "generalPurpose" in matcher
    assert "diff-reviewer" in matcher
    assert "code-reviewer" in matcher
    assert destape[0]["loop_limit"] == 32
    assert destape[0].get("failClosed") is not True
    assert "subagentStart" not in hooks
    stop_adapter = REPO / ".cursor" / "hooks" / "process-fsm-subagent-stop.sh"
    assert stop_adapter.is_file()
    assert stop_adapter.stat().st_mode & stat.S_IXUSR


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
    assert OLD_PLAYBOOK_ORDER not in ctx
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
    assert ".cursor/skills/design-critic/SKILL.md" in critic
    assert ".agents/skills/design-critic" not in critic
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
    text = (REPO / ".cursor" / "skills" / "design-critic" / "SKILL.md").read_text(encoding="utf-8")
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
