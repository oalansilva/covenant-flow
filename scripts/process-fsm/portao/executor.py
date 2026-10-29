#!/usr/bin/env python3
"""Executor de movimentos do board (design D1, D3, D4, D7): roda no workflow do repo do executor, nunca na VM.

Para cada pedido (`client_payload` do `repository_dispatch`): lê o Status vivo com o próprio token, decide pela FSM do
SHA fixado (`portao/decisao.py`), move, posta o recibo na issue e grava o registro do run (artefato `registro`), que é
a resposta que o cliente da VM espera e a memória dos runs seguintes (digest do T5, `/cancelar` pendente).

Uso no workflow:

    python3 scripts/process-fsm/portao/executor.py --evento "$GITHUB_EVENT_PATH" --saida registro.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

HERE = Path(__file__).resolve().parent.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from portao.decisao import (  # noqa: E402
    Decisao,
    Pedido,
    PedidoInvalido,
    decidir,
    ler_pedido,
)
from portao.gramatica import reconhecer  # noqa: E402
from portao.quadro import Quadro, QuadroErro  # noqa: E402
from portao.recibo import formatar, resultado_texto  # noqa: E402

REPO_ROOT = HERE.parents[1]


def _agora_iso(agora: datetime) -> str:
    return agora.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def texto_para_alan(registro: Mapping[str, Any]) -> str:
    """A resposta literal do executor, que o hook mostra ao Alan sem passar pelo modelo."""

    card = registro.get("card")
    caminho = registro.get("caminho") or [registro.get("de"), registro.get("para")]
    texto = resultado_texto(str(registro.get("resultado")), caminho, registro.get("mensagem"), registro.get("codigo"))
    origem = f"`{registro['comando']}`" if registro.get("comando") else f"pedido do agente `{registro.get('evento')}`"
    linha = f"Executor #{card}: {origem} — {texto}."
    if registro.get("recibo_url"):
        linha += f" Recibo: {registro['recibo_url']}"
    return linha


def _registro(pedido: Pedido | None, raw: Mapping[str, Any], *, agora: datetime, run_url: str | None, lei: str) -> dict[str, Any]:
    base = pedido.como_dict() if pedido is not None else {k: raw.get(k) for k in ("request_id", "tipo", "evento", "card", "comando")}
    base.update(quando=_agora_iso(agora), run_url=run_url, lei=lei, recibo_url=None, digest=None, motivo=None)
    return base


def _concluir(registro: dict[str, Any], *, resultado: str, de: str | None, para: str | None, caminho: list[str | None],
              codigo: str | None, mensagem: str | None) -> dict[str, Any]:
    registro.update(resultado=resultado, de=de, para=para, caminho=caminho, codigo=codigo, mensagem=mensagem)
    return registro


def _aplicar(quadro: Quadro, card: int, decisao: Decisao) -> None:
    for passo in decisao.passos:
        if passo.acao == "adicionar":
            quadro.adicionar(card, passo.para)
        elif passo.para != passo.de:
            quadro.mover(card, passo.para)


def executar(
    raw: Mapping[str, Any],
    quadro: Quadro,
    fsm: Mapping[str, Any],
    *,
    agora: datetime,
    run_url: str | None,
    lei: str,
) -> dict[str, Any]:
    """Um pedido do começo ao fim. Devolve o registro do run (também a resposta ao cliente)."""

    try:
        pedido = ler_pedido(raw)
    except PedidoInvalido as exc:
        registro = _registro(None, raw if isinstance(raw, Mapping) else {}, agora=agora, run_url=run_url, lei=lei)
        registro["texto"] = f"Executor: pedido inválido ({exc}); nada mudou."
        return _concluir(registro, resultado="recusado", de=None, para=None, caminho=[], codigo="pedido_invalido", mensagem=str(exc))
    registro = _registro(pedido, raw, agora=agora, run_url=run_url, lei=lei)
    card = pedido.card
    if pedido.tipo == "capturar" and reconhecer(pedido.comando) is None:
        # Texto que não casa com a gramática não é comando reconhecido: nada muda e não há recibo (D4).
        registro["texto"] = f"Executor #{card}: recusado: o pedido não traz um comando de portão exato."
        return _concluir(registro, resultado="recusado", de=None, para=None, caminho=[], codigo="comando_invalido",
                         mensagem="o pedido não traz um comando de portão exato")
    try:
        status = quadro.status(card)
    except QuadroErro as exc:
        _concluir(registro, resultado="recusado", de=None, para=None, caminho=[], codigo="quadro", mensagem=f"Status não lido: {exc}")
        return _recibo_e_texto(quadro, pedido, registro, agora=agora, run_url=run_url, lei=lei)

    historico: list[Mapping[str, Any]] = []
    titulo: str | None = None
    issue_existe = True
    try:
        if pedido.tipo == "capturar" and pedido.evento in ("aprovar_design", "cancelar"):
            historico = list(quadro.registros(card))
        if (pedido.tipo == "capturar" and pedido.evento == "cancelar") or pedido.evento == "criar_card":
            dados = quadro.issue(card)
            issue_existe = dados is not None
            titulo = str(dados.get("titulo")) if dados and dados.get("titulo") else None
    except QuadroErro as exc:
        _concluir(registro, resultado="recusado", de=status, para=None, caminho=[], codigo="quadro", mensagem=f"histórico/issue não lidos: {exc}")
        return _recibo_e_texto(quadro, pedido, registro, agora=agora, run_url=run_url, lei=lei)

    decisao = decidir(pedido, status, fsm, agora=agora, historico=historico, titulo=titulo, issue_existe=issue_existe)
    registro["motivo"] = decisao.motivo
    if pedido.tipo == "pedir" and pedido.evento == "submeter_design":
        registro["digest"] = pedido.extras.get("digest")
    if decisao.codigo == "comando_invalido":
        # Comando que não bate com evento e card do pedido: sem recibo (D4).
        _concluir(registro, resultado="recusado", de=status, para=None, caminho=[], codigo=decisao.codigo, mensagem=decisao.mensagem)
        registro["texto"] = f"Executor #{card}: recusado: {decisao.mensagem}."
        return registro
    if decisao.resultado != "movido":
        _concluir(registro, resultado=decisao.resultado, de=status, para=None, caminho=[status], codigo=decisao.codigo, mensagem=decisao.mensagem)
        return _recibo_e_texto(quadro, pedido, registro, agora=agora, run_url=run_url, lei=lei)
    try:
        _aplicar(quadro, card, decisao)
    except QuadroErro as exc:
        _concluir(registro, resultado="recusado", de=status, para=None, caminho=[status], codigo="move_failed", mensagem=f"o board não mudou: {exc}")
        return _recibo_e_texto(quadro, pedido, registro, agora=agora, run_url=run_url, lei=lei)
    caminho: list[str | None] = [decisao.de, decisao.para]
    para = decisao.para
    nota: str | None = None
    if decisao.encadear:
        para, nota, caminho = _encadear(quadro, pedido, fsm, decisao, agora=agora, caminho=caminho)
    _concluir(registro, resultado="movido", de=decisao.de, para=para, caminho=caminho, codigo=None, mensagem=nota)
    return _recibo_e_texto(quadro, pedido, registro, agora=agora, run_url=run_url, lei=lei)


def _encadear(quadro: Quadro, pedido: Pedido, fsm: Mapping[str, Any], decisao: Decisao, *, agora: datetime,
              caminho: list[str | None]) -> tuple[str | None, str | None, list[str | None]]:
    """T3 no mesmo run do `/priorizar`, conferido como pedido do agente; falhou, o card fica em Todo e diz por quê."""

    evento = str(decisao.encadear)
    try:
        status = quadro.status(pedido.card)
    except QuadroErro as exc:
        return decisao.para, f"{evento} recusado: Status não relido ({exc}); o card fica em {decisao.para}", caminho
    seguinte = Pedido(request_id=f"{pedido.request_id}-t3", tipo="pedir", evento=evento, card=pedido.card,
                      de=decisao.para, ator="Agent", origem=pedido.origem)
    segunda = decidir(seguinte, status, fsm, agora=agora)
    if segunda.resultado != "movido":
        return decisao.para, f"{evento} recusado: {segunda.mensagem}; o card fica em {status or decisao.para}", caminho
    try:
        _aplicar(quadro, pedido.card, segunda)
    except QuadroErro as exc:
        return decisao.para, f"{evento} recusado: o board não mudou ({exc}); o card fica em {decisao.para}", caminho
    return segunda.para, None, [*caminho, segunda.para]


def _recibo_e_texto(quadro: Quadro, pedido: Pedido, registro: dict[str, Any], *, agora: datetime, run_url: str | None, lei: str) -> dict[str, Any]:
    corpo = formatar(
        tipo=pedido.tipo, evento=pedido.evento, comando=pedido.comando, resultado=str(registro["resultado"]),
        caminho=registro.get("caminho") or [], mensagem=registro.get("mensagem"), codigo=registro.get("codigo"),
        motivo=registro.get("motivo"), origem=pedido.origem, agora=agora, run_url=run_url, lei=lei,
        digest=registro.get("digest") if registro.get("resultado") == "movido" else None,
    )
    try:
        registro["recibo_url"] = quadro.comentar(pedido.card, corpo)
    except QuadroErro as exc:
        registro["recibo_erro"] = str(exc)
    registro["recibo"] = corpo
    registro["texto"] = texto_para_alan(registro)
    if registro.get("recibo_erro"):
        registro["texto"] += f" (recibo não postado: {registro['recibo_erro']})"
    return registro


# --------------------------------------------------------------------------- CLI do workflow


def _lei(environ: Mapping[str, str], rev_parse: Callable[[], str]) -> str:
    sha = environ.get("PORTAO_LEI_SHA") or rev_parse()
    nome = environ.get("PORTAO_LEI_REPO") or "crypto"
    return f"{nome}@{sha[:12] if sha else 'unavailable'}"


def _rev_parse() -> str:
    try:
        proc = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--evento", type=Path, required=True, help="GITHUB_EVENT_PATH do repository_dispatch")
    parser.add_argument("--saida", type=Path, required=True, help="onde gravar o registro (artefato `registro`)")
    args = parser.parse_args(argv)
    env = os.environ
    from fsm import load_fsm
    from overlay import load_overlay
    from portao.quadro import GhQuadro

    evento = json.loads(args.evento.read_text(encoding="utf-8"))
    raw = (evento or {}).get("client_payload") or {}
    run_url = None
    if env.get("GITHUB_RUN_ID") and env.get("GITHUB_REPOSITORY"):
        run_url = f"{env.get('GITHUB_SERVER_URL', 'https://github.com')}/{env['GITHUB_REPOSITORY']}/actions/runs/{env['GITHUB_RUN_ID']}"
    agora = datetime.now(timezone.utc)
    lei = _lei(env, _rev_parse)
    quadro = GhQuadro(load_overlay(REPO_ROOT), executor_repo=env.get("GITHUB_REPOSITORY", ""))
    registro = executar(raw, quadro, load_fsm(REPO_ROOT / ".cursor" / "process-fsm.yaml"), agora=agora, run_url=run_url, lei=lei)
    args.saida.write_text(json.dumps(registro, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(registro.get("texto") or json.dumps(registro, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
