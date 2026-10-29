"""Card #1135: `process_event` move pelo executor quando o overlay declara `board.executor` (executor falso, sem GitHub)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import process_event as pe  # noqa: E402
from process_event import ExecutorMover, FakeMover, GhBoardMover, HUMAN_EVENTS, compute_digest, default_mover, process_event  # noqa: E402
from portao_client import ConfigExecutor  # noqa: E402
from resolve import UNBOUND  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
SILENT = lambda bound: (_ for _ in ()).throw(AssertionError(f"github called bound={bound}"))  # noqa: E731
CONFIG = ConfigExecutor("oalansilva/portao")


class ExecutorFalso:
    """Faz o papel de `portao_client.pedir`: registra o pedido e responde o que o teste mandar."""

    def __init__(self, resposta: dict[str, Any] | None = None) -> None:
        self.pedidos: list[dict[str, Any]] = []
        self.resposta = resposta or {"resultado": "movido"}

    def __call__(self, evento, card, *, de, ator, config, origem=None, extras=None, **_: Any) -> dict[str, Any]:
        self.pedidos.append({"evento": evento, "card": card, "de": de, "ator": ator, "config": config,
                             "origem": dict(origem or {}), "extras": dict(extras or {})})
        return dict(self.resposta)


@pytest.fixture
def no_item_edit(monkeypatch):
    """Any `gh` call (item-edit, GraphQL) from the mover path fails the test."""

    real = subprocess.run

    def refuse_gh(*args, **kwargs):
        argv = args[0] if args else kwargs.get("args")
        if isinstance(argv, (list, tuple)) and argv and argv[0] == "gh":
            raise AssertionError(f"gh called: {argv}")
        return real(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", refuse_gh)
    monkeypatch.setattr(GhBoardMover, "set_status", lambda *a, **k: (_ for _ in ()).throw(AssertionError("item-edit")))


def _mover(resposta: dict[str, Any] | None = None) -> tuple[ExecutorMover, ExecutorFalso]:
    fake = ExecutorFalso(resposta)
    return ExecutorMover(CONFIG, pedir=fake, origem={"sessao": "s-1"}), fake


def test_transicao_do_agente_pelo_executor(no_item_edit):
    mover, fake = _mover()
    out = process_event("pedir_review", status="Em desenvolvimento", q_git="card-612-process-event", bound_card="612",
                        mover=mover, digest_changed=False, g_design=True, client="grok")
    assert out["result"] == "transition" and out["to"] == "Code Review"
    assert fake.pedidos == [{"evento": "pedir_review", "card": 612, "de": "Em desenvolvimento", "ator": "Agent", "config": CONFIG,
                             "origem": {"sessao": "s-1", "cliente": "grok"}, "extras": {}}]


def test_executor_recusa_vira_reject_com_reason_executor():
    mover, fake = _mover({"resultado": "recusado", "codigo": "no_edge", "mensagem": "sem aresta (QA, aceitar_sha)"})
    out = process_event("aceitar_sha", status="Code Review", q_git="card-612-process-event", bound_card="612", mover=mover,
                        digest_changed=False, pr_lister=lambda q: [{"number": 1}])
    assert out["result"] == "reject" and out["reason"] == "executor:no_edge" and out["state"] == "Code Review"
    assert "sem aresta" in out["message"] and len(fake.pedidos) == 1


@pytest.mark.parametrize("resultado", ["timeout", "indisponivel"])
def test_executor_sem_resposta_nao_presume(resultado):
    mover, _fake = _mover({"resultado": resultado, "codigo": resultado, "mensagem": "sem resposta"})
    out = process_event("pedir_review", status="Em desenvolvimento", q_git="card-612-process-event", bound_card="612",
                        mover=mover, digest_changed=False)
    assert out["result"] == "reject" and out["reason"] == f"executor:{resultado}" and out["state"] == "Em desenvolvimento"


def test_t5_leva_o_digest_do_design(tmp_path):
    change = tmp_path / "openspec" / "changes" / "card-612-process-event"
    (change / "specs" / "x").mkdir(parents=True)
    for name in ("proposal.md", "tasks.md"):
        (change / name).write_text("# x\n", encoding="utf-8")
    (change / "design.md").write_text("UI impact: none\nlive_route: N/A harness-only; no product route\nsurface: new\n", encoding="utf-8")
    (change / "specs" / "x" / "spec.md").write_text("# s\n", encoding="utf-8")
    mover, fake = _mover()
    out = process_event("submeter_design", status="Design", q_git="card-612-process-event", bound_card="612", mover=mover,
                        change_dir=change, digest_changed=False)
    assert out["result"] == "transition"
    assert fake.pedidos[0]["evento"] == "submeter_design" and fake.pedidos[0]["de"] == "Design"
    assert fake.pedidos[0]["extras"] == {"digest": compute_digest(change, None)}
    assert (change / ".design-digest").read_text().strip() == compute_digest(change, None)


def test_t17_pede_com_ator_guard():
    mover, fake = _mover()
    out = process_event("iniciar_apply", status="Pronto para Dev", q_git="card-612-process-event", bound_card="612",
                        mover=mover, digest_changed=True, g_design=True)
    assert out["result"] == "transition" and out["reason"] == "I4"
    assert (fake.pedidos[0]["evento"], fake.pedidos[0]["ator"], fake.pedidos[0]["de"]) == ("invalidar_aprovacao", "Guard", "Pronto para Dev")


def test_t16_um_pedido_por_card_do_pacote():
    from t16 import RecordingT16Closer

    mover, fake = _mover()
    out = process_event("fechar_release", mover=mover, t16_closer=RecordingT16Closer(), status="Homologado", q_git="develop",
                        bound_card=UNBOUND, package_cards=[617, 618], m_lote=True,
                        status_provider=lambda bound: {"617": "Homologado", "618": "Homologado"}.get(str(bound)))
    assert out["result"] == "transition" and out["to"] == "Pronto"
    assert [(p["card"], p["evento"], p["de"], p["extras"]) for p in fake.pedidos] == [
        (617, "fechar_release", "Homologado", {"pacote": "617,618"}),
        (618, "fechar_release", "Homologado", {"pacote": "617,618"}),
    ]


def test_criar_card_pelo_executor_e_sem_executor_continua_not_implemented():
    mover, fake = _mover()
    out = process_event("criar_card", card="1200", mover=mover)
    assert out["result"] == "transition" and out["to"] == "Em Refinamento"
    assert fake.pedidos[0]["evento"] == "criar_card" and fake.pedidos[0]["de"] is None and fake.pedidos[0]["card"] == 1200
    refused, _ = _mover({"resultado": "recusado", "codigo": "ja_no_board", "mensagem": "#1200 já está no board"})
    assert process_event("criar_card", card="1200", mover=refused)["reason"] == "executor:ja_no_board"
    assert process_event("criar_card", card="1200", mover=FakeMover())["reason"] == "not_implemented"


@pytest.mark.parametrize("event", sorted(HUMAN_EVENTS))
def test_eventos_do_alan_recusados_com_actor_sem_chamar_o_executor(event):
    mover, fake = _mover()
    out = process_event(event, status="Aprovação de Design", q_git="card-612-process-event", bound_card="612", mover=mover,
                        digest_changed=False, g_design=True, status_provider=SILENT)
    assert out["result"] == "reject" and out["reason"] == "actor" and fake.pedidos == []


def test_default_mover_segue_a_chave_do_overlay(tmp_path, monkeypatch):
    from test_overlay_fixtures import filled_overlay_dict, write_overlay

    board = dict(filled_overlay_dict()["board"])
    write_overlay(tmp_path)
    assert isinstance(default_mover(tmp_path), GhBoardMover)
    write_overlay(tmp_path, board={**board, "executor": {"repo": "oalansilva/portao"}})
    mover = default_mover(tmp_path)
    assert isinstance(mover, ExecutorMover) and mover.config.repo == "oalansilva/portao"
    write_overlay(tmp_path, board={**board, "executor": {"repo": "quebrado"}})
    with pytest.raises(Exception):
        default_mover(tmp_path)


def test_executor_mover_nunca_usa_item_edit():
    import inspect

    source = inspect.getsource(ExecutorMover)
    assert "updateProjectV2ItemFieldValue" not in source and "subprocess" not in source and "set_status" not in source
    assert ExecutorMover.via_executor is True and FakeMover.via_executor is False and pe.GhBoardMover.via_executor is False
