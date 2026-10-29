"""Card #1135: Guard nega disparo do executor fora do `process_event`; regras escritas citam os seis portões."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from board_status import is_executor_dispatch_command, is_status_edit_command  # noqa: E402
from fsm import ALAN_GATES, load_fsm, validate_fsm  # noqa: E402
from guard import decide  # noqa: E402
from overlay import render_agents  # noqa: E402
from paging import FOOTER  # noqa: E402
from test_overlay_fixtures import FIELD_ID, filled_overlay_dict, write_overlay  # noqa: E402

SIX = "T1, T2, T6, T7, T15, T18"
WORDING = "Texto livre é wording; comando exato capturado fora do agente é evento do Alan."
SILENT = lambda bound: (_ for _ in ()).throw(AssertionError(f"github called bound={bound}"))  # noqa: E731

NEGADOS = [
    'python3 scripts/process-fsm/portao_client.py capturar "/homologar 1135"',
    "python3 -c 'import portao_client; portao_client.capturar(c)'",
    'python3 -c "from portao_client import capturar"',
    "cd scripts/process-fsm && python3 -c 'from portao.executor import executar'",
    "gh api repos/oalansilva/portao/dispatches -f event_type=portao -F client_payload[tipo]=capturar",
    "gh api --method POST repos/oalansilva/outro/dispatches --input payload.json",
    "curl -X POST -H 'Authorization: token x' https://api.github.com/repos/oalansilva/portao/dispatches -d @p.json",
    "python3 scripts/process-fsm/portao/executor.py --evento e.json --saida r.json",
    "python3 /srv/x/scripts/process-fsm/portao/executor.py --evento e.json",
    "python3 scripts/process-fsm/process_event.py pedir_review --card 1 && gh api repos/o/p/dispatches -f event_type=x",
]
PERMITIDOS = [
    "python3 scripts/process-fsm/process_event.py pedir_review --card 1135",
    "python3 /srv/x/scripts/process-fsm/process_event.py criar_card --card 1200 --client claude",
    "cat scripts/process-fsm/portao_client.py",
    "grep -n capturar scripts/process-fsm/portao_client.py",
    "sed -n 1,40p scripts/process-fsm/portao/decisao.py",
    "python3 -m pytest scripts/process-fsm/test_portao.py -q",
    "git diff -- scripts/process-fsm/portao_client.py",
    "cat scripts/process-fsm/portao/executor.py",
    "sed -n 1,80p scripts/process-fsm/portao/executor.py",
    "git add scripts/process-fsm/portao/executor.py",
    "git diff -- scripts/process-fsm/portao/executor.py",
]


@pytest.mark.parametrize("command", NEGADOS)
def test_classifica_disparo_do_executor(command):
    assert is_executor_dispatch_command(command)


@pytest.mark.parametrize("command", PERMITIDOS)
def test_nao_classifica_leitura_nem_process_event(command):
    assert not is_executor_dispatch_command(command)


def _fallback_guard(tmp_path: Path, command: str) -> dict:
    """Run the Cursor guard hook alone (no guard.py, no board_status): the PyYAML-free Python fallback decides."""
    import json

    repo = tmp_path / "fb"
    hooks = repo / ".cursor" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    script = hooks / "process-fsm-guard.sh"
    script.write_text((REPO / ".cursor" / "hooks" / "process-fsm-guard.sh").read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(0o755)
    proc = subprocess.run([str(script)], input=json.dumps({"command": command, "cwd": str(repo)}),
                          capture_output=True, text=True, cwd=str(repo), check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


@pytest.mark.parametrize("command", NEGADOS)
def test_fallback_do_guard_nega_disparo_do_executor(tmp_path, command):
    data = _fallback_guard(tmp_path, command)
    assert data["permission"] == "deny" and "executor_dispatch" in data["reason"]
    assert "process_event" in data["agent_message"] and "not a guarantee" in data["agent_message"]


@pytest.mark.parametrize("command", PERMITIDOS)
def test_fallback_do_guard_nao_nega_leitura_nem_process_event(tmp_path, command):
    data = _fallback_guard(tmp_path, command)
    assert "executor_dispatch" not in (data.get("reason") or "")


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "card"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "card-1135-x", str(repo)], check=True)
    write_overlay(repo)
    return repo


def test_guard_nega_capturar_e_dispatches_e_aponta_process_event(tmp_path):
    repo = _repo(tmp_path)
    for command in ('python3 scripts/process-fsm/portao_client.py capturar "/homologar 1135"',
                    "gh api repos/oalansilva/portao/dispatches -f event_type=portao"):
        result = decide({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo), "status": "Done"}, status_provider=SILENT)
        assert result["permission"] == "deny" and "executor_dispatch" in result["reason"] and "process_event" in result["agent_message"]
        assert "not a guarantee" in result["agent_message"]


def test_guard_deixa_process_event_e_mantem_a_regra_de_item_edit(tmp_path):
    repo = _repo(tmp_path)
    ok = decide({"tool_name": "Bash", "tool_input": {"command": "python3 scripts/process-fsm/process_event.py pedir_review --card 1135"},
                 "cwd": str(repo), "status": "Em desenvolvimento"}, status_provider=SILENT)
    assert ok["permission"] == "allow"
    edit = decide({"tool_name": "Bash", "tool_input": {"command": f"gh project item-edit --id X --field-id {FIELD_ID}"},
                   "cwd": str(repo), "status": "Done"}, status_provider=SILENT)
    assert edit["permission"] == "deny" and "status_item_edit" in edit["reason"]
    assert is_status_edit_command("gh project item-edit --id X", None)


# --------------------------------------------------------------------------- regras escritas (D10)


def test_agents_gerado_cita_os_seis_portoes_e_a_nova_regra_de_wording_sem_crescer():
    text = render_agents(filled_overlay_dict())
    assert f"Portões do Alan: {SIX} (board ou comando exato)" in text and WORDING in text
    assert "Agent não move Status: pede pelo `process_event`" in text
    assert "Chat é wording" not in text and "Alan único" not in text
    assert len([line for line in text.splitlines() if line.strip()]) == 14  # as many non-empty lines as before #1135
    stub = (REPO / "AGENTS.md").read_text(encoding="utf-8")
    assert f"Portões do Alan: {SIX}" in stub and WORDING in stub and len([ln for ln in stub.splitlines() if ln.strip()]) == 14


def test_pagina_do_processo_e_fallback_do_cursor_trocam_a_frase():
    assert WORDING in FOOTER and "Chat é wording" not in FOOTER
    assert f"Portões do Alan: {SIX}." in FOOTER and "T1/T7/T15" not in FOOTER
    hook = (REPO / ".cursor" / "hooks" / "process-fsm-session-start.sh").read_text(encoding="utf-8")
    assert WORDING in hook and "Chat é wording" not in hook
    assert f"Portões do Alan: {SIX}." in hook and "T1/T7/T15" not in hook


def test_fsm_alan_gates_e_acoes_do_digest():
    assert set(ALAN_GATES) == {"T1", "T2", "T6", "T7", "T15", "T18"}
    fsm = load_fsm()
    validate_fsm(fsm)
    rows = {row["id"]: row for row in fsm["transitions"]}
    assert "freeze_digest" in rows["T5"]["actions"]
    assert "check_digest" in rows["T7"]["actions"] and "freeze_digest" not in rows["T7"]["actions"]
    i2 = next(item for item in fsm["invariants"] if item["id"] == "I2")["text"]
    assert i2.startswith(SIX)
    for tid in ALAN_GATES:
        assert rows[tid]["actor"] == "Alan"


def test_validate_fsm_recusa_portao_sem_alan():
    fsm = load_fsm()
    for row in fsm["transitions"]:
        if row["id"] == "T6":
            row["actor"] = "Agent"
    with pytest.raises(Exception, match="T6"):
        validate_fsm(fsm)


def _skill(*parts: str) -> str:
    return (REPO / ".cursor" / "skills").joinpath(*parts).read_text(encoding="utf-8")


def test_skill_covenant_flow_tem_comandos_de_portao_e_nivel_cooperativo():
    text = _skill("covenant-flow", "SKILL.md")
    section = text.split("### Comandos de portão", 1)[1].split("\n## ", 1)[0].split("\n### ", 1)[0]
    for command in ("/priorizar <card>", "/aprovar-design <card>", '/devolver-design <card> "motivo"', "/homologar <card>",
                    '/nao-homologar <card> "motivo"', '/cancelar <card> "motivo"', "/confirmar-cancelar <card>"):
        assert command in section
    assert "cooperativo" in section and "apagar o run e o recibo" in section and "não avisa o Alan" in section
    assert "sem esse contexto" in section.lower() and "aponte o board" in section
    gates = next(line for line in text.splitlines() if line.startswith("Gates humanos"))
    for tid in ("T1", "T2", "T6", "T7", "T15", "T18"):
        assert tid in gates
    assert "comenta pedindo o motivo" in gates and "restaurar Done" not in text
    assert "o movimento de Status é do executor do board" in text


def test_github_project_board_nao_orienta_item_add_nem_item_edit():
    for text in (_skill("github-project-board", "SKILL.md"), _skill("github-project-board", "references", "project-board-commands.md")):
        for line in text.splitlines():
            assert "gh project item-add" not in line and "gh project item-edit" not in line, line
        assert "process_event" in text and "restaurar Done" not in text
    board = _skill("github-project-board", "SKILL.md")
    for tid in ("T1", "T2", "T6", "T7", "T15", "T18"):
        assert tid in board


def test_yaml_i2_cita_os_seis_no_texto_carregado():
    data = yaml.safe_load((REPO / ".cursor" / "process-fsm.yaml").read_text(encoding="utf-8"))
    i2 = next(item for item in data["invariants"] if item["id"] == "I2")
    assert SIX in i2["text"]
