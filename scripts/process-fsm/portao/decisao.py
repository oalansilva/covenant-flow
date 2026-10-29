"""Decisão pura do executor (design D3 e D7): pedido + Status vivo + FSM fixada -> movido, pendente ou recusado.

Sem I/O: quem lê o Status, a issue e os registros dos runs anteriores é o executor (`portao/executor.py`), que passa
tudo para cá. A mesma função decide o pedido do agente (`pedir`) e o comando do Alan capturado pelo hook (`capturar`).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fsm import expand_transitions, vivo_states  # noqa: E402
from portao.gramatica import ORIGEM, Comando, reconhecer  # noqa: E402

TIPOS = ("pedir", "capturar")
# Os seis portões que só o Alan passa; a lei fixada que der outro ator a um deles invalida o executor inteiro.
PORTOES_ALAN = {"T1": "priorizar", "T2": "cancelar", "T6": "devolver_design", "T7": "aprovar_design", "T15": "homologar", "T18": "nao_homologar"}
ATORES_PEDIR = frozenset({"Agent", "Guard", "CI"})
PRAZO_CANCELAR = timedelta(minutes=10)
FORA_DO_BOARD = "(fora do board)"
TOPO_MAX = 10  # `repository_dispatch` aceita no máximo 10 propriedades no topo do `client_payload`


class PedidoInvalido(ValueError):
    pass


@dataclass(frozen=True)
class Pedido:
    request_id: str
    tipo: str
    evento: str
    card: int
    de: str | None
    ator: str
    comando: str | None = None
    origem: Mapping[str, Any] = field(default_factory=dict)
    extras: Mapping[str, Any] = field(default_factory=dict)

    def como_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id, "tipo": self.tipo, "evento": self.evento, "card": self.card, "de": self.de,
            "ator": self.ator, "comando": self.comando, "origem": dict(self.origem), "extras": dict(self.extras),
        }


@dataclass(frozen=True)
class Passo:
    """Um movimento que o executor faz no board: `adicionar` (T0) ou `mover`."""

    transicao: str
    evento: str
    de: str | None
    para: str
    ator: str
    acao: str = "mover"


@dataclass(frozen=True)
class Decisao:
    resultado: str  # movido | pendente | recusado
    de: str | None
    para: str | None = None
    codigo: str | None = None
    mensagem: str | None = None
    passos: tuple[Passo, ...] = ()
    motivo: str | None = None  # motivo do Alan, que vira a linha de motivo do recibo
    encadear: str | None = None  # evento do agente que o mesmo run tenta logo depois (T3 do `/priorizar`)
    comando: Comando | None = None


def _texto(valor: Any) -> str | None:
    return valor.strip() if isinstance(valor, str) and valor.strip() else None


def ler_pedido(raw: Any) -> Pedido:
    """Valida a forma do `client_payload`; nada aqui confia no conteúdo além da forma."""

    if not isinstance(raw, Mapping):
        raise PedidoInvalido("o pedido não é um objeto")
    if len(raw) > TOPO_MAX:
        raise PedidoInvalido(f"o pedido tem {len(raw)} propriedades no topo (máximo {TOPO_MAX})")
    request_id = _texto(raw.get("request_id"))
    tipo = _texto(raw.get("tipo"))
    evento = _texto(raw.get("evento"))
    ator = _texto(raw.get("ator"))
    if not request_id or tipo not in TIPOS or not evento or not ator:
        raise PedidoInvalido("faltam request_id, tipo (pedir|capturar), evento ou ator")
    try:
        card = int(str(raw.get("card")).lstrip("#"))
    except (TypeError, ValueError):
        raise PedidoInvalido("card não é número de issue") from None
    if card <= 0:
        raise PedidoInvalido("card não é número de issue")
    origem = raw.get("origem") or {}
    extras = raw.get("extras") or {}
    if not isinstance(origem, Mapping) or not isinstance(extras, Mapping):
        raise PedidoInvalido("origem e extras precisam ser objetos")
    de = raw.get("de")
    if de is not None and not isinstance(de, str):
        raise PedidoInvalido("de precisa ser texto ou null")
    comando = raw.get("comando")
    if comando is not None and not isinstance(comando, str):
        raise PedidoInvalido("comando precisa ser texto")
    return Pedido(request_id=request_id, tipo=tipo, evento=evento, card=card, de=de, ator=ator, comando=comando,
                  origem=dict(origem), extras=dict(extras))


def _atores(valor: Any) -> set[str]:
    if valor is None:
        return set()
    if isinstance(valor, str):
        return {valor}
    return {str(item) for item in valor}


def lei_invalida(fsm: Mapping[str, Any]) -> str | None:
    """Motivo de a lei fixada não servir, ou None: os seis portões precisam existir e ser só do Alan."""

    linhas = {row.get("id"): row for row in fsm.get("transitions") or [] if isinstance(row, Mapping)}
    for tid, evento in PORTOES_ALAN.items():
        row = linhas.get(tid)
        if row is None or row.get("event") != evento:
            return f"a lei fixada não tem {tid} ({evento})"
        if _atores(row.get("actor")) != {"Alan"}:
            return f"a lei fixada dá {tid} ({evento}) a {sorted(_atores(row.get('actor')))}; só o Alan passa esse portão"
    return None


def eventos_do_alan(fsm: Mapping[str, Any]) -> frozenset[str]:
    return frozenset(
        str(row.get("event")) for row in fsm.get("transitions") or []
        if isinstance(row, Mapping) and _atores(row.get("actor")) == {"Alan"}
    )


def aresta(fsm: Mapping[str, Any], estado: str | None, evento: str) -> dict[str, Any] | None:
    for row in expand_transitions(dict(fsm)):
        if row.get("from") == estado and row.get("event") == evento:
            return row
    return None


def quando_de(registro: Mapping[str, Any]) -> datetime | None:
    valor = registro.get("quando")
    if not isinstance(valor, str):
        return None
    try:
        momento = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError:
        return None
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)


def _do_card(historico: Iterable[Mapping[str, Any]], card: int) -> list[Mapping[str, Any]]:
    achados = []
    for registro in historico:
        if not isinstance(registro, Mapping) or quando_de(registro) is None:
            continue
        try:
            if int(registro.get("card")) != card:
                continue
        except (TypeError, ValueError):
            continue
        achados.append(registro)
    return sorted(achados, key=lambda r: quando_de(r))  # type: ignore[arg-type, return-value]


def ultimo_t5(historico: Iterable[Mapping[str, Any]], card: int) -> Mapping[str, Any] | None:
    feitos = [r for r in _do_card(historico, card) if r.get("tipo") == "pedir" and r.get("evento") == "submeter_design"
              and r.get("resultado") == "movido" and _texto(r.get("digest"))]
    return feitos[-1] if feitos else None


def cancelamento_pendente(historico: Iterable[Mapping[str, Any]], card: int) -> Mapping[str, Any] | None:
    """O último registro de cancelamento do card, se ele for um `/cancelar` pendente (confirmação ou outro `/cancelar` depois troca)."""

    ligados = [r for r in _do_card(historico, card) if r.get("tipo") == "capturar" and r.get("evento") == "cancelar"]
    if not ligados:
        return None
    ultimo = ligados[-1]
    return ultimo if ultimo.get("resultado") == "pendente" else None


def brt(momento: datetime) -> str:
    try:
        from zoneinfo import ZoneInfo

        local = momento.astimezone(ZoneInfo("America/Sao_Paulo"))
    except Exception:  # sem base de fusos: Brasília sem horário de verão desde 2019
        local = momento.astimezone(timezone(timedelta(hours=-3)))
    return local.strftime("%Y-%m-%d %H:%M") + " BRT"


def _recusa(de: str | None, codigo: str, mensagem: str, comando: Comando | None = None) -> Decisao:
    return Decisao("recusado", de, None, codigo, mensagem, comando=comando)


def _status(texto: str | None) -> str:
    return texto if texto else FORA_DO_BOARD


def decidir(
    pedido: Pedido,
    status: str | None,
    fsm: Mapping[str, Any],
    *,
    agora: datetime,
    historico: Iterable[Mapping[str, Any]] = (),
    titulo: str | None = None,
    issue_existe: bool = True,
) -> Decisao:
    """`movido` (com os passos), `pendente` (só `/cancelar`) ou `recusado` com código e mensagem."""

    problema = lei_invalida(fsm)
    if problema:
        return _recusa(status, "lei_invalida", problema)
    if pedido.tipo == "pedir":
        return _decidir_pedido(pedido, status, fsm, issue_existe=issue_existe)
    return _decidir_comando(pedido, status, fsm, agora=agora, historico=list(historico), titulo=titulo)


def _decidir_pedido(pedido: Pedido, status: str | None, fsm: Mapping[str, Any], *, issue_existe: bool) -> Decisao:
    if pedido.ator not in ATORES_PEDIR or pedido.evento in eventos_do_alan(fsm):
        return _recusa(status, "actor", f"`{pedido.evento}` pedido por {pedido.ator}: pedido do agente aceita só transições de Agent, Guard ou CI")
    if pedido.evento == "criar_card":
        if not issue_existe:
            return _recusa(status, "issue_inexistente", f"a issue #{pedido.card} não existe")
        if status is not None:
            return _recusa(status, "ja_no_board", f"#{pedido.card} já está no board (Status atual = {status})")
        row = aresta(fsm, None, "criar_card")
        if row is None or pedido.ator not in _atores(row.get("actor")):
            return _recusa(status, "no_edge", "a lei fixada não tem T0 para este ator")
        passo = Passo(str(row.get("id")), "criar_card", None, str(row.get("to")), pedido.ator, acao="adicionar")
        return Decisao("movido", None, passo.para, passos=(passo,))
    if pedido.de != status:
        return _recusa(status, "de", f"Status atual = {_status(status)}; o pedido diz de={pedido.de}")
    row = aresta(fsm, status, pedido.evento)
    if row is None:
        return _recusa(status, "no_edge", f"sem aresta ({_status(status)}, {pedido.evento}) na lei fixada")
    if pedido.ator not in _atores(row.get("actor")):
        return _recusa(status, "actor", f"{row.get('id')} não aceita o ator {pedido.ator}")
    if pedido.evento == "submeter_design" and not _texto(pedido.extras.get("digest")):
        return _recusa(status, "digest_ausente", "T5 sem o digest do design no pedido")
    passo = Passo(str(row.get("id")), pedido.evento, status, str(row.get("to")), pedido.ator)
    return Decisao("movido", status, passo.para, passos=(passo,))


def _decidir_comando(
    pedido: Pedido,
    status: str | None,
    fsm: Mapping[str, Any],
    *,
    agora: datetime,
    historico: list[Mapping[str, Any]],
    titulo: str | None,
) -> Decisao:
    comando = reconhecer(pedido.comando)
    if comando is None or comando.card != pedido.card or comando.evento != pedido.evento:
        return _recusa(status, "comando_invalido", "o pedido não traz um comando de portão exato que bata com evento e card")
    if pedido.ator != "Alan":
        return _recusa(status, "actor", f"comando de portão com ator {pedido.ator}; só o Alan", comando)
    exigido = ORIGEM[comando.nome]
    vivas = set(vivo_states(dict(fsm)))
    if exigido is None:
        if status not in vivas:
            return _recusa(status, "de", f"Status atual = {_status(status)}; /{comando.nome} exige uma coluna viva (fora de Pronto e Cancelado)", comando)
    elif status != exigido:
        return _recusa(status, "de", f"Status atual = {_status(status)}; /{comando.nome} exige {exigido}", comando)
    row = aresta(fsm, status, comando.evento)
    if row is None:
        return _recusa(status, "no_edge", f"sem aresta ({_status(status)}, {comando.evento}) na lei fixada", comando)
    if "Alan" not in _atores(row.get("actor")):
        return _recusa(status, "actor", f"{row.get('id')} não é portão do Alan na lei fixada", comando)
    passo = Passo(str(row.get("id")), comando.evento, status, str(row.get("to")), "Alan")

    if comando.evento == "aprovar_design":
        digest = _texto(pedido.extras.get("digest"))
        if not digest:
            erro = _texto(pedido.extras.get("digest_erro")) or "o hook não mandou o digest do design"
            return _recusa(status, "digest_ausente", f"sem digest do design atual: {erro}", comando)
        t5 = ultimo_t5(historico, comando.card)
        if t5 is None:
            return _recusa(status, "sem_t5", f"sem envio para aprovação (T5) registrado no executor para #{comando.card}; arraste no board ou reenvie o design", comando)
        if str(t5.get("digest")).strip() != digest:
            momento = quando_de(t5)
            data = brt(momento) if momento else "data desconhecida"
            return _recusa(status, "digest_mudou", f"design mudou desde o envio para aprovação (T5 em {data})", comando)
    if comando.nome == "cancelar":
        nome = f" «{titulo}»" if titulo else ""
        return Decisao("pendente", status, None, None,
                       f"Cancelar #{comando.card}{nome}? Para confirmar: /confirmar-cancelar {comando.card}",
                       motivo=comando.motivo, comando=comando)
    motivo = comando.motivo
    if comando.confirmacao:
        pendente = cancelamento_pendente(historico, comando.card)
        if pendente is None:
            return _recusa(status, "sem_pendente", f"nenhum /cancelar pendente de #{comando.card}", comando)
        momento = quando_de(pendente)
        if momento is None or agora - momento > PRAZO_CANCELAR:
            return _recusa(status, "pendente_vencido", f"o /cancelar de #{comando.card} venceu (mais de 10 minutos); mande /cancelar de novo", comando)
        motivo = _texto(pendente.get("motivo"))
    return Decisao("movido", status, passo.para, passos=(passo,), motivo=motivo, comando=comando,
                   encadear="iniciar_design" if comando.nome == "priorizar" else None)
