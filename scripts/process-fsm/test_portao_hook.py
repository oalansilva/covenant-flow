"""Card #1135: hook de prompt do Claude Code (adapter + shim) e registro na conta (entrada e comandos de portão)."""
from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import account_install  # noqa: E402
import cf_shim  # noqa: E402
import claude_adapter  # noqa: E402
import portao_client  # noqa: E402
from shim_fixtures import install_account, isolate_account, last_json, make_consumer, shim_command, trust_all  # noqa: E402
from test_overlay_fixtures import filled_overlay_dict, write_overlay  # noqa: E402

SESSION = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def consumer(tmp_path):
    """A git repo with a filled overlay and `board.executor` on."""

    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "card-1135-x", str(root)], check=True)
    board = dict(filled_overlay_dict()["board"])
    write_overlay(root, board={**board, "executor": {"repo": "oalansilva/portao"}})
    return root


class Captura:
    def __init__(self, resposta: dict[str, Any]) -> None:
        self.resposta = resposta
        self.chamadas: list[dict[str, Any]] = []

    def __call__(self, comando, *, config, origem=None, extras=None, **_: Any) -> dict[str, Any]:
        self.chamadas.append({"comando": comando, "config": config, "origem": origem, "extras": extras})
        return dict(self.resposta)


def _payload(root: Path, prompt: str) -> dict[str, Any]:
    return {"session_id": SESSION, "cwd": str(root), "hook_event_name": "UserPromptSubmit", "prompt": prompt, "prompt_id": "p1"}


# --------------------------------------------------------------------------- adapter (D8)


@pytest.mark.parametrize("prompt", ["aprova aí", "pode seguir", "/aprovar-design 1135 ok", "/Homologar 1135", "implemente"])
def test_texto_que_nao_casa_nao_gera_saida_nem_chama_o_executor(consumer, prompt):
    captura = Captura({"resultado": "movido"})
    assert claude_adapter.prompt_submit(_payload(consumer, prompt), capturar=captura) is None
    assert captura.chamadas == []


def test_comando_certo_vai_ao_executor_e_volta_sem_bloquear(consumer, monkeypatch):
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop")
    monkeypatch.setenv("AI_AGENT", "claude-code_2.1.312")
    captura = Captura({"resultado": "movido", "para": "Homologado", "texto": "Executor #1135: `/homologar 1135` — movido Done → Homologado."})
    out = claude_adapter.prompt_submit(_payload(consumer, "/homologar 1135"), capturar=captura)
    assert "decision" not in out and out["systemMessage"] == captura.resposta["texto"]
    context = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert context.startswith("Comando de portão tratado pelo executor:") and "Não é pedido ao agente" in context
    assert "Siga a FSM a partir do Status atual" in context and "post-card-evidence-comment.sh --transition homologado" in context
    chamada = captura.chamadas[0]
    assert chamada["comando"].evento == "homologar" and chamada["config"].repo == "oalansilva/portao"
    assert chamada["origem"] == {"cliente": "claude", "superficie": "claude-desktop", "versao_host": "2.1.312", "sessao": SESSION}


def test_sem_board_executor_o_comando_nao_e_capturado_e_vira_wording(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    write_overlay(root)
    captura = Captura({"resultado": "movido"})
    out = claude_adapter.prompt_submit(_payload(root, "/priorizar 1135"), capturar=captura)
    assert captura.chamadas == [] and "não capturado" in out["systemMessage"] and "board.executor" in out["systemMessage"]
    assert "é wording" in out["hookSpecificOutput"]["additionalContext"] and "aponte o board" in out["hookSpecificOutput"]["additionalContext"]


def test_timeout_diz_que_o_resultado_sai_no_recibo_e_nao_presume(consumer):
    out = claude_adapter.prompt_submit(_payload(consumer, "/priorizar 1135"), capturar=Captura({"resultado": "timeout"}))
    assert f"sem resposta em {portao_client.TETO_ESPERA} s" in out["systemMessage"] and "recibo da issue #1135" in out["systemMessage"]
    assert "Não presuma o resultado" in out["hookSpecificOutput"]["additionalContext"]
    out = claude_adapter.prompt_submit(_payload(consumer, "/priorizar 1135"), capturar=Captura({"resultado": "indisponivel", "mensagem": "HTTP 502"}))
    assert "indisponível" in out["systemMessage"] and "HTTP 502" in out["systemMessage"]


def test_aprovar_design_manda_o_digest_do_worktree_do_card(consumer):
    captura = Captura({"resultado": "movido", "texto": "ok"})
    claude_adapter.prompt_submit(_payload(consumer, "/aprovar-design 1135"), capturar=captura, digest_of=lambda root, card: ("abc", None))
    assert captura.chamadas[0]["extras"] == {"digest": "abc"}
    claude_adapter.prompt_submit(_payload(consumer, "/aprovar-design 1135"), capturar=captura,
                                 digest_of=lambda root, card: (None, "sem worktree card-1135-* nesta máquina"))
    assert captura.chamadas[1]["extras"] == {"digest_erro": "sem worktree card-1135-* nesta máquina"}


def test_card_design_digest_acha_o_worktree_card_n(tmp_path):
    from process_event import compute_digest

    main = tmp_path / "main"
    subprocess.run(["git", "init", "-q", "-b", "develop", str(main)], check=True)
    subprocess.run(["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    worktree = tmp_path / "wt"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", "-b", "card-77-coisa", str(worktree)], check=True)
    assert claude_adapter.card_design_digest(main, 78) == (None, "sem worktree card-78-* nesta máquina")
    digest, problem = claude_adapter.card_design_digest(main, 77)
    assert digest is None and "design.md" in problem
    change = worktree / "openspec" / "changes" / "card-77-coisa"
    change.mkdir(parents=True)
    (change / "design.md").write_text("# d\n", encoding="utf-8")
    assert claude_adapter.card_design_digest(main, 77) == (compute_digest(change, None), None)


def test_dispatch_prompt_submit_com_erro_fica_visivel_so_para_comando(monkeypatch, capsys):
    def boom(payload):
        raise RuntimeError("quebrou")

    monkeypatch.setattr(claude_adapter, "prompt_submit", boom)
    assert claude_adapter.dispatch("prompt-submit", {"prompt": "/homologar 1135"}) == 0
    out = json.loads(capsys.readouterr().out)
    assert "não capturado" in out["systemMessage"] and "decision" not in out
    assert claude_adapter.dispatch("prompt-submit", {"prompt": "bom dia"}) == 0
    assert capsys.readouterr().out == ""


def test_adapter_main_aceita_prompt_submit(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"prompt": "oi", "cwd": "/"})))
    assert claude_adapter.main(["prompt-submit"]) == 0 and capsys.readouterr().out == ""


# --------------------------------------------------------------------------- shim (D8, spec account-hook-shim)


def test_prompt_submit_gateia_so_comando_e_nunca_bloqueia():
    assert "prompt-submit" in cf_shim.GATING_EVENTS["claude"]
    out = cf_shim.deny_output("claude", "prompt-submit", "reason=hooks_unreviewed", {"prompt": "/homologar 1135"})
    assert "decision" not in out and "hooks_unreviewed" in out["systemMessage"]
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit" and "NÃO capturado" in out["hookSpecificOutput"]["additionalContext"]
    assert cf_shim.deny_output("claude", "prompt-submit", "x", {"prompt": "bom dia"}) is None
    assert cf_shim.deny_output("claude", "prompt-submit", "x", None) is None
    assert cf_shim.deny_output("claude", "pre-tool-use", "x", {"prompt": "/homologar 1"})["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_tetos_encadeados_registro_shim_adapter():
    assert account_install.PROMPT_TIMEOUT > cf_shim.EVENT_TIMEOUTS["prompt-submit"] > portao_client.TETO_ESPERA
    assert cf_shim.EVENT_TIMEOUTS.get("pre-tool-use", cf_shim.HOOK_TIMEOUT) == cf_shim.HOOK_TIMEOUT


def test_shim_roda_o_adapter_do_prompt_com_o_teto_proprio(monkeypatch, tmp_path):
    seen: dict[str, Any] = {}

    def fake_run(argv, **kwargs):
        seen["argv"], seen["timeout"] = argv, kwargs.get("timeout")
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(cf_shim.subprocess, "run", fake_run)
    entry = {"entrypoints": {"prompt-submit": ["python3", "scripts/process-fsm/claude_adapter.py", "prompt-submit"]}}
    decision = cf_shim.Decision("run", root=tmp_path, entry=entry, adapter_digest="a", registration="r")
    cf_shim.run_adapter(tmp_path, entry, "prompt-submit", b"{}", decision, {})
    assert seen["timeout"] == cf_shim.EVENT_TIMEOUTS["prompt-submit"] and seen["argv"][-1] == "prompt-submit"


def test_hook_de_prompt_sem_revisao_falha_visivel_e_nao_chega_ao_adapter(monkeypatch, tmp_path):
    isolate_account(monkeypatch, tmp_path)
    root = make_consumer(tmp_path / "fresh")
    install_account()
    log = tmp_path / "log"
    result = shim_command("claude", "prompt-submit", _payload(root, "/homologar 1135"), log=log)
    out = last_json(result)
    assert out is not None and "hooks_unreviewed" in out["systemMessage"] and "decision" not in out
    assert not log.exists() or "prompt-submit" not in log.read_text()
    quiet = shim_command("claude", "prompt-submit", _payload(root, "bom dia"), log=log)
    assert last_json(quiet) is None


def test_hook_de_prompt_revisado_chama_o_adapter_pinado(monkeypatch, tmp_path):
    isolate_account(monkeypatch, tmp_path)
    root = make_consumer(tmp_path / "fresh")
    install_account()
    trust_all(root)
    log = tmp_path / "log"
    shim_command("claude", "prompt-submit", _payload(root, "/homologar 1135"), log=log)
    calls = [json.loads(line) for line in log.read_text().splitlines() if line.startswith("{")]
    assert calls[-1]["event"] == "prompt-submit" and json.loads(calls[-1]["payload"])["prompt"] == "/homologar 1135"


def test_comando_de_portao_fora_de_repo_consumidor_avisa_e_texto_comum_fica_quieto(monkeypatch, tmp_path, capsys):
    isolate_account(monkeypatch, tmp_path)
    fora = tmp_path / "fora"
    fora.mkdir()
    env = {"HOME": str(tmp_path / "account-home")}
    assert cf_shim.handle_hook("claude", "prompt-submit", json.dumps(_payload(fora, "/homologar 1135")).encode(), env) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert out["systemMessage"].startswith("Comando de portão não capturado: esta sessão está fora de um repo consumidor")
    assert "use o board" in out["systemMessage"] and "decision" not in out
    assert out["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert cf_shim.handle_hook("claude", "prompt-submit", json.dumps(_payload(fora, "bom dia")).encode(), env) == 0
    assert capsys.readouterr().out == ""


def test_pin_sem_hook_de_prompt_diz_que_o_pin_e_anterior_e_nao_adapter_missing(monkeypatch, tmp_path, capsys):
    isolate_account(monkeypatch, tmp_path)
    root = make_consumer(tmp_path / "velho", pin="v1.1.20")
    entry = {"registration": "account", "entrypoints": {"session-start": ["python3", "x.py"]}}
    monkeypatch.setattr(cf_shim, "decide", lambda *a, **k: cf_shim.Decision("run", root=root, entry=entry))
    env = {"HOME": str(tmp_path / "account-home")}
    assert cf_shim.handle_hook("claude", "prompt-submit", json.dumps(_payload(root, "/aprovar-design 1135")).encode(), env) == 0
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    message = out["systemMessage"]
    assert "reason=event_unsupported" in message and "adapter_missing" not in message
    assert "v1.1.20" in message and cf_shim.GATE_HOOK_MIN_PIN in message and "board" in message
    assert cf_shim.handle_hook("claude", "prompt-submit", json.dumps(_payload(root, "bom dia")).encode(), env) == 0
    assert capsys.readouterr().out == ""
    # every other event without an entry point keeps `adapter_missing`
    assert cf_shim.handle_hook("claude", "pre-tool-use", json.dumps({"cwd": str(root), "tool_name": "Bash", "session_id": SESSION}).encode(), env) == 0
    other = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "reason=adapter_missing" in other["hookSpecificOutput"]["permissionDecisionReason"]


# --------------------------------------------------------------------------- registro na conta (task 3.3)


def test_install_registra_user_prompt_submit_e_os_sete_comandos(monkeypatch, tmp_path):
    home = isolate_account(monkeypatch, tmp_path)
    install_account(["claude"])
    hooks = json.loads((home / ".claude" / "settings.json").read_text())["hooks"]
    (group,) = hooks["UserPromptSubmit"]
    (handler,) = group["hooks"]
    assert handler["timeout"] == account_install.PROMPT_TIMEOUT and "onFailure" not in handler and "matcher" not in group
    assert handler["command"].endswith("cf_shim.py\" claude prompt-submit")
    commands = home / ".claude" / "commands"
    names = sorted(p.stem for p in commands.glob("*.md"))
    assert names == sorted(account_install.GATE_COMMANDS)
    body = (commands / "priorizar.md").read_text()
    assert body.startswith("---\ndescription: ") and account_install.COMMAND_MARKER in body
    assert "não é um pedido ao agente" in body and "Não aja sozinho" in body and "aponte o board" in body
    assert "process_event" in body and "contexto adicional" in body


def test_install_e_idempotente_preserva_alheios_e_check_mostra(monkeypatch, tmp_path):
    home = isolate_account(monkeypatch, tmp_path)
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "commands" / "meu.md").write_text("meu comando\n")
    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": {"UserPromptSubmit": [{"hooks": [{"type": "command", "command": "echo alheio"}]}]}}))
    install_account(["claude"])
    first = {p.name: p.read_bytes() for p in (home / ".claude").rglob("*") if p.is_file()}
    install_account(["claude"])
    assert {p.name: p.read_bytes() for p in (home / ".claude").rglob("*") if p.is_file()} == first
    assert (home / ".claude" / "commands" / "meu.md").read_text() == "meu comando\n"
    prompt_hooks = json.loads((home / ".claude" / "settings.json").read_text())["hooks"]["UserPromptSubmit"]
    commands = [h["command"] for g in prompt_hooks for h in g["hooks"]]
    assert "echo alheio" in commands and any("prompt-submit" in c for c in commands)
    lines, _ok = account_install.run_check(None, ["claude"])
    claude_line = next(line for line in lines if line.startswith("claude:"))
    assert "entry=present" in claude_line and "gate_commands=7/7" in claude_line


def test_comando_alheio_com_o_mesmo_nome_recusa_sem_escrever(monkeypatch, tmp_path):
    home = isolate_account(monkeypatch, tmp_path)
    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "commands" / "homologar.md").write_text("do Alan\n")
    with pytest.raises(account_install.InstallError, match="command conflict"):
        install_account(["claude"])
    assert not (home / ".claude" / "settings.json").exists()
    assert sorted(p.name for p in (home / ".claude" / "commands").iterdir()) == ["homologar.md"]


def test_remove_tira_so_os_nossos_comandos(monkeypatch, tmp_path):
    home = isolate_account(monkeypatch, tmp_path)
    install_account(["claude"])
    (home / ".claude" / "commands" / "meu.md").write_text("meu\n")
    account_install.run_remove(["claude"])
    assert sorted(p.name for p in (home / ".claude" / "commands").iterdir()) == ["meu.md"]
    lines, ok = account_install.run_check(None, ["claude"])
    assert not ok


def test_check_acusa_comando_faltando(monkeypatch, tmp_path):
    home = isolate_account(monkeypatch, tmp_path)
    install_account(["claude"])
    (home / ".claude" / "commands" / "cancelar.md").unlink()
    lines, ok = account_install.run_check(None, ["claude"])
    assert not ok and "gate_commands=6/7" in next(line for line in lines if line.startswith("claude:"))


def test_manifesto_declara_o_entrypoint_do_prompt():
    from adapter_manifest import ENTRYPOINTS

    assert ENTRYPOINTS["claude"]["prompt-submit"] == ["python3", "scripts/process-fsm/claude_adapter.py", "prompt-submit"]
    for client in ("codex", "cursor"):
        assert "prompt-submit" not in ENTRYPOINTS[client]
    assert "prompt-submit" not in json.dumps(account_install.codex_document()) and "prompt" not in json.dumps(account_install.cursor_document()).lower()
