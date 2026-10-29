"""Card #1135: gramática, decisão, recibo e executor do board com quadro falso (sem GitHub, sem rede)."""
from __future__ import annotations

import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import portao_client  # noqa: E402
from fsm import load_fsm  # noqa: E402
from portao.decisao import PORTOES_ALAN, TOPO_MAX, Pedido, decidir, lei_invalida, ler_pedido, PedidoInvalido  # noqa: E402
from portao.executor import executar  # noqa: E402
from portao.gramatica import parece_comando, reconhecer  # noqa: E402
from portao.quadro import QuadroErro, nome_do_run  # noqa: E402

AGORA = datetime(2026, 10, 28, 17, 0, tzinfo=timezone.utc)
RUN = "https://github.com/oalansilva/portao/actions/runs/1"
LEI = "crypto@abc123def456"
ORIGEM = {"cliente": "claude", "superficie": "claude-desktop", "versao_host": "2.1.312", "sessao": "1ddc9dda-003f-42d7"}
FSM = load_fsm()


class QuadroFalso:
    """Board em memória: Status por card, comentários postados, registros dos runs anteriores."""

    def __init__(self, status: Mapping[int, str | None] | None = None, *, titulo: str = "Comandos de portão",
                 existe: bool = True, registros: list[Mapping[str, Any]] | None = None,
                 falhar_em: set[str] | None = None, depois_de_mover: Any = None) -> None:
        self.estado: dict[int, str | None] = dict(status or {})
        self.titulo = titulo
        self.existe = existe
        self._registros = list(registros or [])
        self.falhar_em = set(falhar_em or ())
        self.depois_de_mover = depois_de_mover
        self.movimentos: list[tuple[int, str]] = []
        self.adicionados: list[tuple[int, str]] = []
        self.comentarios: list[tuple[int, str]] = []

    def status(self, card: int) -> str | None:
        return self.estado.get(card)

    def issue(self, card: int) -> Mapping[str, Any] | None:
        return {"titulo": self.titulo} if self.existe else None

    def mover(self, card: int, para: str) -> None:
        if para in self.falhar_em:
            raise QuadroErro(f"cota esgotada movendo para {para}")
        self.movimentos.append((card, para))
        self.estado[card] = para
        if self.depois_de_mover is not None:
            self.depois_de_mover(self, card, para)

    def adicionar(self, card: int, para: str) -> None:
        self.adicionados.append((card, para))
        self.estado[card] = para

    def comentar(self, card: int, corpo: str) -> str | None:
        self.comentarios.append((card, corpo))
        return f"https://github.com/oalansilva/crypto/issues/{card}#issuecomment-{len(self.comentarios)}"

    def registros(self, card: int) -> list[Mapping[str, Any]]:
        return list(self._registros)


def capturado(texto: str, *, extras: Mapping[str, Any] | None = None, ator: str = "Alan") -> dict[str, Any]:
    comando = reconhecer(texto)
    assert comando is not None, texto
    dados = dict(extras or {})
    if comando.motivo is not None:
        dados["motivo"] = comando.motivo
    return portao_client.montar_pedido("capturar", comando.evento, comando.card, de=comando.origem, ator=ator,
                                       comando=comando.texto, origem=ORIGEM, extras=dados)


def pedido_agente(evento: str, card: int, de: str | None, *, ator: str = "Agent", extras: Mapping[str, Any] | None = None) -> dict[str, Any]:
    return portao_client.montar_pedido("pedir", evento, card, de=de, ator=ator, origem=ORIGEM, extras=extras)


def rodar(pedido: Mapping[str, Any], quadro: QuadroFalso, *, fsm: Mapping[str, Any] | None = None, agora: datetime = AGORA) -> dict[str, Any]:
    return executar(pedido, quadro, fsm or FSM, agora=agora, run_url=RUN, lei=LEI)


# --------------------------------------------------------------------------- gramática (D6, D11)

ACEITOS = [
    ("/priorizar 1135", "priorizar", 1135, None),
    ("/priorizar #1135", "priorizar", 1135, None),
    ("/aprovar-design 1135", "aprovar_design", 1135, None),
    ('/devolver-design 1135 "falta o fluxo de erro"', "devolver_design", 1135, "falta o fluxo de erro"),
    ("/homologar 1135", "homologar", 1135, None),
    ('/nao-homologar 1135 "botão quebrado"', "nao_homologar", 1135, "botão quebrado"),
    ('/cancelar 1135 "duplicado"', "cancelar", 1135, "duplicado"),
    ("/confirmar-cancelar 1135", "cancelar", 1135, None),
    ("/homologar 1135   \n", "homologar", 1135, None),
]

RECUSADOS = [
    "aprova aí",
    "pode seguir",
    "/Aprovar-design 1135",
    "/aprovar-design 1135 ok",
    "/aprovar-design  1135",
    " /aprovar-design 1135",
    "ok\n/aprovar-design 1135",
    "/aprovar-design 1135\nobrigado",
    "/aprovar-design",
    "/aprovar-design abc",
    "/aprovar-design 0",
    "/aprovar-design 1135 1136",
    "/nao-homologar 1135",
    '/nao-homologar 1135 ""',
    '/nao-homologar 1135 "   "',
    "/nao-homologar 1135 sem aspas",
    '/nao-homologar 1135 "tem "aspas" dentro"',
    '/nao-homologar 1135 "' + "x" * 501 + '"',
    '/cancelar 1135 "linha\nquebrada"',
    "/cancelar 1135",
    '/confirmar-cancelar 1135 "motivo"',
    "/aprovar_design 1135",
    "por favor /homologar 1135",
]


@pytest.mark.parametrize("texto,evento,card,motivo", ACEITOS)
def test_gramatica_aceita_a_linha_exata(texto, evento, card, motivo):
    comando = reconhecer(texto)
    assert comando is not None and (comando.evento, comando.card, comando.motivo) == (evento, card, motivo)


@pytest.mark.parametrize("texto", RECUSADOS)
def test_gramatica_recusa_variacoes(texto):
    assert reconhecer(texto) is None


def test_motivo_de_500_caracteres_vale_e_parece_comando_so_pelo_prefixo():
    assert reconhecer('/nao-homologar 7 "' + "x" * 500 + '"') is not None
    assert parece_comando("/aprovar-design 1135 ok") and parece_comando("  /cancelar 1")
    assert not parece_comando("aprova aí") and not parece_comando("/priorizacao 1")


# --------------------------------------------------------------------------- pedido (D4)


def test_pedido_cabe_em_10_propriedades_e_agrupa_a_origem():
    pedido = capturado('/cancelar 1135 "duplicado"')
    assert len(pedido) <= TOPO_MAX
    assert set(pedido["origem"]) == {"cliente", "superficie", "versao_host", "sessao"}
    assert pedido["extras"] == {"motivo": "duplicado"} and pedido["de"] is None and pedido["ator"] == "Alan"
    with pytest.raises(PedidoInvalido):
        ler_pedido({**pedido, **{f"x{i}": i for i in range(3)}})


def test_pedido_invalido_nao_move_nem_deixa_recibo():
    quadro = QuadroFalso({1135: "Done"})
    out = rodar({"tipo": "pedir"}, quadro)
    assert out["resultado"] == "recusado" and out["codigo"] == "pedido_invalido"
    assert quadro.movimentos == [] and quadro.comentarios == []


# --------------------------------------------------------------------------- comandos do Alan (D7, specs alan-gate-commands)

CERTOS = [
    ("/aprovar-design 1135", "Aprovação de Design", "Pronto para Dev"),
    ('/devolver-design 1135 "falta o fluxo de erro"', "Aprovação de Design", "Design"),
    ("/homologar 1135", "Done", "Homologado"),
    ('/nao-homologar 1135 "botão quebrado"', "Done", "Em desenvolvimento"),
]


def _t5(digest: str, quando: datetime, card: int = 1135) -> dict[str, Any]:
    return {"tipo": "pedir", "evento": "submeter_design", "card": card, "resultado": "movido", "digest": digest,
            "quando": quando.strftime("%Y-%m-%dT%H:%M:%SZ")}


@pytest.mark.parametrize("texto,de,para", CERTOS)
def test_cada_comando_certo_move_e_deixa_recibo(texto, de, para):
    quadro = QuadroFalso({1135: de}, registros=[_t5("d1", AGORA - timedelta(hours=2))])
    out = rodar(capturado(texto, extras={"digest": "d1"}), quadro)
    assert out["resultado"] == "movido" and out["para"] == para
    assert quadro.movimentos == [(1135, para)]
    assert len(quadro.comentarios) == 1
    corpo = quadro.comentarios[0][1]
    assert f"Portão: `{texto}` — movido {de} → {para}" in corpo
    assert "Cliente: claude/claude-desktop 2.1.312" in corpo and "Sessão: 1ddc9dda" in corpo
    assert f"Executor: {RUN} · Lei: {LEI}" in corpo and "Quando: 2026-10-28 14:00 BRT" in corpo
    assert out["texto"].startswith("Executor #1135:") and out["recibo_url"] in out["texto"]


def test_nao_homologar_recibo_comeca_pela_linha_de_motivo():
    quadro = QuadroFalso({1135: "Done"})
    rodar(capturado('/nao-homologar 1135 "texto"'), quadro)
    corpo = quadro.comentarios[0][1]
    assert corpo.splitlines()[0] == "Não homologar: texto"
    assert "Cliente:" in corpo and "Quando:" in corpo and RUN in corpo


def test_recibo_de_comando_recusado_nao_comeca_pela_linha_de_motivo():
    quadro = QuadroFalso({1135: "QA"})
    out = rodar(capturado('/nao-homologar 1135 "texto"'), quadro)
    assert out["resultado"] == "recusado" and quadro.movimentos == []
    corpo = quadro.comentarios[0][1]
    assert not corpo.startswith("Não homologar:") and "Não homologar: texto" not in corpo


def test_homologar_fora_de_done_recusa_com_status_atual():
    quadro = QuadroFalso({1135: "QA"})
    out = rodar(capturado("/homologar 1135"), quadro)
    assert out["resultado"] == "recusado" and quadro.movimentos == []
    assert "Status atual = QA; /homologar exige Done" in out["mensagem"]
    assert "Status atual = QA; /homologar exige Done" in out["texto"]
    assert "recusado: Status atual = QA" in quadro.comentarios[0][1]


def test_priorizar_certo_termina_em_design_no_mesmo_run():
    quadro = QuadroFalso({1135: "Em Refinamento"})
    out = rodar(capturado("/priorizar 1135"), quadro)
    assert out["resultado"] == "movido" and out["para"] == "Design"
    assert quadro.movimentos == [(1135, "Todo"), (1135, "Design")]
    assert "movido Em Refinamento → Todo → Design" in quadro.comentarios[0][1]


def test_priorizar_com_t3_recusado_fica_em_todo_e_diz_por_que():
    def outro_moveu(quadro, card, para):
        if para == "Todo":
            quadro.estado[card] = "Cancelado"  # o Status mudou entre o T1 e o T3

    quadro = QuadroFalso({1135: "Em Refinamento"}, depois_de_mover=outro_moveu)
    out = rodar(capturado("/priorizar 1135"), quadro)
    assert out["resultado"] == "movido" and out["para"] == "Todo"
    assert quadro.movimentos == [(1135, "Todo")]
    assert "iniciar_design recusado" in out["mensagem"] and "Status atual = Cancelado" in out["mensagem"]
    assert "iniciar_design recusado" in quadro.comentarios[0][1]


def test_priorizar_com_erro_do_board_no_t3_fica_em_todo():
    quadro = QuadroFalso({1135: "Em Refinamento"}, falhar_em={"Design"})
    out = rodar(capturado("/priorizar 1135"), quadro)
    assert out["para"] == "Todo" and quadro.estado[1135] == "Todo"
    assert "o board não mudou" in out["mensagem"]


def test_aprovar_design_com_design_alterado_depois_do_t5_recusa_com_a_data():
    quadro = QuadroFalso({1135: "Aprovação de Design"}, registros=[_t5("antigo", datetime(2026, 10, 28, 12, 30, tzinfo=timezone.utc))])
    out = rodar(capturado("/aprovar-design 1135", extras={"digest": "novo"}), quadro)
    assert out["resultado"] == "recusado" and out["codigo"] == "digest_mudou" and quadro.movimentos == []
    assert "design mudou desde o envio para aprovação (T5 em 2026-10-28 09:30 BRT)" in out["mensagem"]


def test_aprovar_design_usa_o_ultimo_t5_e_recusa_sem_t5_ou_sem_digest():
    registros = [_t5("velho", AGORA - timedelta(days=2)), _t5("atual", AGORA - timedelta(hours=1)), _t5("outro-card", AGORA, card=99)]
    quadro = QuadroFalso({1135: "Aprovação de Design"}, registros=registros)
    assert rodar(capturado("/aprovar-design 1135", extras={"digest": "atual"}), quadro)["resultado"] == "movido"
    sem_t5 = rodar(capturado("/aprovar-design 1135", extras={"digest": "x"}), QuadroFalso({1135: "Aprovação de Design"}))
    assert sem_t5["codigo"] == "sem_t5"
    sem_worktree = rodar(capturado("/aprovar-design 1135", extras={"digest_erro": "sem worktree card-1135-* nesta máquina"}),
                         QuadroFalso({1135: "Aprovação de Design"}, registros=registros))
    assert sem_worktree["codigo"] == "digest_ausente" and "sem worktree card-1135-*" in sem_worktree["mensagem"]


def test_cancelar_sem_confirmacao_nao_move_e_traz_titulo_e_confirmacao():
    quadro = QuadroFalso({1135: "Design"}, titulo="Comandos de portão do Alan")
    out = rodar(capturado('/cancelar 1135 "duplicado"'), quadro)
    assert out["resultado"] == "pendente" and quadro.movimentos == []
    assert "«Comandos de portão do Alan»" in out["texto"] and "/confirmar-cancelar 1135" in out["texto"]
    corpo = quadro.comentarios[0][1]
    assert corpo.startswith("Cancelar: duplicado\n") and "pendente" in corpo


def test_confirmacao_dentro_do_prazo_cancela_com_o_motivo_do_pedido():
    quadro = QuadroFalso({1135: "Design"})
    pendente = rodar(capturado('/cancelar 1135 "duplicado"'), quadro, agora=AGORA - timedelta(minutes=5))
    quadro._registros = [pendente]
    out = rodar(capturado("/confirmar-cancelar 1135"), quadro)
    assert out["resultado"] == "movido" and out["para"] == "Cancelado"
    assert quadro.comentarios[-1][1].startswith("Cancelar: duplicado\n")


def test_confirmacao_sem_pendente_vencida_ou_de_outro_card_recusa():
    sem = rodar(capturado("/confirmar-cancelar 1135"), QuadroFalso({1135: "Design"}))
    assert sem["codigo"] == "sem_pendente"
    quadro = QuadroFalso({1135: "Design"})
    vencido = rodar(capturado('/cancelar 1135 "duplicado"'), quadro, agora=AGORA - timedelta(minutes=11))
    quadro._registros = [vencido]
    assert rodar(capturado("/confirmar-cancelar 1135"), quadro)["codigo"] == "pendente_vencido"
    outro = QuadroFalso({1135: "Design", 7: "Design"})
    outro._registros = [rodar(capturado('/cancelar 7 "x"'), outro)]
    assert rodar(capturado("/confirmar-cancelar 1135"), outro)["codigo"] == "sem_pendente"
    assert outro.estado[1135] == "Design"


def test_confirmacao_ja_usada_nao_vale_de_novo():
    quadro = QuadroFalso({1135: "Design"})
    primeiro = rodar(capturado('/cancelar 1135 "duplicado"'), quadro, agora=AGORA - timedelta(minutes=2))
    confirmado = rodar(capturado("/confirmar-cancelar 1135"), QuadroFalso({1135: "Design"}, registros=[primeiro]), agora=AGORA - timedelta(minutes=1))
    assert confirmado["resultado"] == "movido"
    again = rodar(capturado("/confirmar-cancelar 1135"), QuadroFalso({1135: "Design"}, registros=[primeiro, confirmado]))
    assert again["codigo"] == "sem_pendente"


def test_cancelar_exige_coluna_viva():
    out = rodar(capturado('/cancelar 1135 "x"'), QuadroFalso({1135: "Pronto"}))
    assert out["resultado"] == "recusado" and "exige uma coluna viva" in out["mensagem"]


def test_texto_aproximado_forjado_como_capturar_nao_move_nem_deixa_recibo():
    quadro = QuadroFalso({1135: "Done"})
    forjado = portao_client.montar_pedido("capturar", "homologar", 1135, de="Done", ator="Alan", comando="pode homologar", origem=ORIGEM)
    out = rodar(forjado, quadro)
    assert out["codigo"] == "comando_invalido" and quadro.movimentos == [] and quadro.comentarios == []
    divergente = portao_client.montar_pedido("capturar", "homologar", 1135, de="Done", ator="Alan", comando="/homologar 7", origem=ORIGEM)
    assert rodar(divergente, quadro)["codigo"] == "comando_invalido" and quadro.movimentos == []


def test_capturar_com_ator_do_agente_recusa_actor():
    quadro = QuadroFalso({1135: "Done"})
    out = rodar(capturado("/homologar 1135", ator="Agent"), quadro)
    assert out["codigo"] == "actor" and quadro.movimentos == []


# --------------------------------------------------------------------------- pedidos do agente (D3, D9, specs board-executor)


@pytest.mark.parametrize("evento", sorted(PORTOES_ALAN.values()))
def test_portao_do_alan_pedido_pelo_agente_recusa_actor(evento):
    origem = {"priorizar": "Em Refinamento", "cancelar": "Design", "devolver_design": "Aprovação de Design",
              "aprovar_design": "Aprovação de Design", "homologar": "Done", "nao_homologar": "Done"}[evento]
    quadro = QuadroFalso({1135: origem})
    out = rodar(pedido_agente(evento, 1135, origem), quadro)
    assert out["resultado"] == "recusado" and out["codigo"] == "actor"
    assert quadro.movimentos == [] and quadro.estado[1135] == origem


def test_transicao_do_agente_com_coluna_certa_move_e_errada_recusa():
    quadro = QuadroFalso({1135: "Em desenvolvimento"})
    out = rodar(pedido_agente("pedir_review", 1135, "Em desenvolvimento"), quadro)
    assert out["resultado"] == "movido" and out["para"] == "Code Review"
    assert "Pedido do agente: `pedir_review` — movido Em desenvolvimento → Code Review" in quadro.comentarios[0][1]
    errado = QuadroFalso({1135: "QA"})
    out = rodar(pedido_agente("pedir_review", 1135, "Em desenvolvimento"), errado)
    assert out["resultado"] == "recusado" and out["codigo"] == "de" and "Status atual = QA" in out["mensagem"]
    assert errado.movimentos == [] and errado.estado[1135] == "QA"


def test_pedido_sem_aresta_na_lei_fixada_recusa_no_edge():
    quadro = QuadroFalso({1135: "QA"})
    out = rodar(pedido_agente("aceitar_sha", 1135, "QA"), quadro)
    assert out["codigo"] == "no_edge" and quadro.movimentos == []


def test_t5_exige_digest_e_o_guarda_no_registro_e_no_recibo():
    sem = rodar(pedido_agente("submeter_design", 1135, "Design"), QuadroFalso({1135: "Design"}))
    assert sem["codigo"] == "digest_ausente"
    quadro = QuadroFalso({1135: "Design"})
    out = rodar(pedido_agente("submeter_design", 1135, "Design", extras={"digest": "abc"}), quadro)
    assert out["resultado"] == "movido" and out["digest"] == "abc"
    assert "Design: sha256 abc" in quadro.comentarios[0][1]


def test_t17_so_com_ator_guard():
    assert rodar(pedido_agente("invalidar_aprovacao", 1135, "Pronto para Dev", ator="Guard"), QuadroFalso({1135: "Pronto para Dev"}))["para"] == "Design"
    assert rodar(pedido_agente("invalidar_aprovacao", 1135, "Pronto para Dev"), QuadroFalso({1135: "Pronto para Dev"}))["codigo"] == "actor"


def test_criar_card_poe_a_issue_no_board_em_refinamento():
    quadro = QuadroFalso({})
    out = rodar(pedido_agente("criar_card", 1200, None), quadro)
    assert out["resultado"] == "movido" and quadro.adicionados == [(1200, "Em Refinamento")]
    assert rodar(pedido_agente("criar_card", 1200, None), QuadroFalso({1200: "Todo"}))["codigo"] == "ja_no_board"
    assert rodar(pedido_agente("criar_card", 1200, None), QuadroFalso({}, existe=False))["codigo"] == "issue_inexistente"


def test_fsm_que_da_portao_ao_agente_invalida_tudo():
    fsm = copy.deepcopy(FSM)
    for row in fsm["transitions"]:
        if row["id"] == "T7":
            row["actor"] = ["Alan", "Agent"]
    assert lei_invalida(fsm)
    for pedido, status in (
        (capturado("/aprovar-design 1135", extras={"digest": "d"}), "Aprovação de Design"),
        (pedido_agente("pedir_review", 1135, "Em desenvolvimento"), "Em desenvolvimento"),
    ):
        quadro = QuadroFalso({1135: status})
        out = rodar(pedido, quadro, fsm=fsm)
        assert out["codigo"] == "lei_invalida" and quadro.movimentos == []
    assert lei_invalida(FSM) is None


def test_decisao_pura_nao_le_comentario():
    # O executor não tem entrada de comentário: um comentário `/homologar 1135` na issue não vira pedido.
    import inspect
    from portao import executor as modulo

    assert "comentario" not in inspect.signature(decidir).parameters
    assert "comentarios" not in inspect.getsource(modulo.executar)
    assert isinstance(ler_pedido(pedido_agente("pedir_review", 1, "Em desenvolvimento")), Pedido)


def test_erro_de_board_no_move_recusa_sem_presumir():
    quadro = QuadroFalso({1135: "Done"}, falhar_em={"Homologado"})
    out = rodar(capturado("/homologar 1135"), quadro)
    assert out["resultado"] == "recusado" and out["codigo"] == "move_failed" and quadro.estado[1135] == "Done"


# --------------------------------------------------------------------------- cliente (D4, D8)


class DisparadorFalso:
    def __init__(self, *, registro: Mapping[str, Any] | None = None, completa_em: int = 2, falha: Exception | None = None) -> None:
        self.disparos: list[tuple[str, str, dict[str, Any]]] = []
        self.consultas = 0
        self._registro = registro
        self.completa_em = completa_em
        self.falha = falha

    def disparar(self, repo, event_type, payload):
        if self.falha:
            raise self.falha
        self.disparos.append((repo, event_type, dict(payload)))

    def achar_run(self, repo, request_id):
        self.consultas += 1
        status = "completed" if self.consultas >= self.completa_em else "in_progress"
        return {"id": 7, "status": status, "conclusion": "success", "html_url": RUN,
                "display_title": nome_do_run(1135, "homologar", request_id)}

    def registro(self, repo, run_id):
        return self._registro


class Relogio:
    def __init__(self) -> None:
        self.t = 0.0

    def agora(self) -> float:
        return self.t

    def dormir(self, segundos: float) -> None:
        self.t += segundos


def test_cliente_dispara_e_devolve_o_registro_do_run():
    registro = {"resultado": "movido", "para": "Homologado", "texto": "Executor #1135: ok"}
    via = DisparadorFalso(registro=registro)
    relogio = Relogio()
    comando = reconhecer("/homologar 1135")
    out = portao_client.capturar(comando, config=portao_client.ConfigExecutor("oalansilva/portao"), origem=ORIGEM,
                                 disparador=via, relogio=relogio.agora, dormir=relogio.dormir)
    assert out["resultado"] == "movido" and out["run_url"] == RUN
    repo, event_type, payload = via.disparos[0]
    assert repo == "oalansilva/portao" and event_type == "portao"
    assert payload["tipo"] == "capturar" and payload["ator"] == "Alan" and payload["comando"] == "/homologar 1135"
    assert len(payload) <= TOPO_MAX


def test_cliente_sem_resposta_no_teto_devolve_timeout_sem_presumir():
    via = DisparadorFalso(completa_em=10**6)
    relogio = Relogio()
    out = portao_client.pedir("pedir_review", 1135, de="Em desenvolvimento", ator="Agent",
                              config=portao_client.ConfigExecutor("o/p"), disparador=via, teto=9,
                              relogio=relogio.agora, dormir=relogio.dormir)
    assert out["resultado"] == "timeout" and out["para"] is None and "9 s" in out["mensagem"]


def test_cliente_com_disparo_quebrado_devolve_indisponivel():
    via = DisparadorFalso(falha=portao_client.ExecutorIndisponivel("HTTP 403"))
    out = portao_client.pedir("pedir_review", 1135, de="Em desenvolvimento", ator="Agent",
                              config=portao_client.ConfigExecutor("o/p"), disparador=via)
    assert out["resultado"] == "indisponivel" and "403" in out["mensagem"]
    sem_registro = DisparadorFalso(registro=None, completa_em=1)
    relogio = Relogio()
    out = portao_client.pedir("pedir_review", 1135, de="Em desenvolvimento", ator="Agent", config=portao_client.ConfigExecutor("o/p"),
                              disparador=sem_registro, relogio=relogio.agora, dormir=relogio.dormir)
    assert out["resultado"] == "indisponivel"


def test_config_do_overlay_sem_chave_e_com_chave_invalida():
    from overlay import OverlayInvalid

    assert portao_client.config_do_overlay({"board": {}}) is None
    assert portao_client.config_do_overlay({"board": {"executor": {"repo": "oalansilva/portao"}}}).repo == "oalansilva/portao"
    with pytest.raises(OverlayInvalid):
        portao_client.config_do_overlay({"board": {"executor": {"repo": "sem-barra"}}})


def test_registro_zip_e_lido_pelo_nome_do_artefato():
    import io
    import json
    import zipfile

    from portao.quadro import ler_registro_zip

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as arquivo:
        arquivo.writestr("registro.json", json.dumps({"resultado": "movido"}))
    assert ler_registro_zip(buffer.getvalue()) == {"resultado": "movido"}
    assert ler_registro_zip(b"lixo") is None


# --------------------------------------------------------------------------- GhQuadro com `gh` substituído (sem rede)


def test_gh_quadro_le_status_move_e_acha_registros_do_card(monkeypatch):
    import io
    import json
    import zipfile

    from portao.quadro import GhQuadro
    from test_overlay_fixtures import COLUMN_IDS, filled_overlay_dict

    def zip_de(dados):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as arquivo:
            arquivo.writestr("registro.json", json.dumps(dados))
        return buffer.getvalue()

    chamadas: list[list[str]] = []
    runs = [{"id": 1, "display_title": "portao #1135 submeter_design r1", "status": "completed"},
            {"id": 2, "display_title": "portao #11 homologar r2", "status": "completed"},
            {"id": 3, "display_title": "portao #1135 homologar r3", "status": "in_progress"}]

    def fake_gh(self, args, *, token, entrada=None):
        chamadas.append(list(args))
        alvo = args[0]
        if alvo == "graphql":
            query = next(a for a in args if a.startswith("query="))
            if "updateProjectV2ItemFieldValue" in query:
                return json.dumps({"data": {"updateProjectV2ItemFieldValue": {"projectV2Item": {"id": "I"}}}}).encode()
            node = {"id": "ITEM", "project": {"number": 1, "owner": {"login": "oalansilva"}}, "fieldValueByName": {"name": "Done"}}
            return json.dumps({"data": {"repository": {"issue": {"projectItems": {"nodes": [node]}}}}}).encode()
        if "actions/runs?" in alvo:
            return json.dumps({"workflow_runs": runs}).encode()
        if alvo.endswith("/artifacts"):
            return json.dumps({"artifacts": [{"id": 9, "name": "registro", "expired": False}]}).encode()
        if alvo.endswith("/zip"):
            return zip_de({"card": 1135, "evento": "submeter_design", "digest": "d"})
        raise AssertionError(args)

    monkeypatch.setattr(GhQuadro, "_gh", fake_gh)
    quadro = GhQuadro(filled_overlay_dict(repo="oalansilva/crypto"), executor_repo="oalansilva/portao", environ={"PORTAO_TOKEN": "t"})
    assert quadro.status(1135) == "Done"
    quadro.mover(1135, "Homologado")
    mutation = chamadas[-1]
    assert f"o={COLUMN_IDS['Homologado']}" in mutation and "i=ITEM" in mutation
    assert quadro.registros(1135) == [{"card": 1135, "evento": "submeter_design", "digest": "d"}]
    with pytest.raises(QuadroErro):
        GhQuadro(filled_overlay_dict(repo="oalansilva/crypto"), executor_repo="o/p", environ={})
