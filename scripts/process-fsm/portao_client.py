"""Cliente do executor na VM (design D4, D8, D9): `pedir` (agente, via `process_event`) e `capturar` (hook de prompt).

Monta o `client_payload`, dispara `repository_dispatch` no repo do executor com o token do `gh` da VM e espera o run
pelo `request_id` até o teto. O resultado é o registro do run (artefato `registro`). Sem resposta no teto devolve
`timeout`; disparo ou run quebrado devolve `indisponivel`. Nunca presume que o card moveu.

Não há linha de comando: o agente pede pelo `process_event`, e só o hook de prompt captura. A Guard nega chamar este
módulo ou o endpoint `dispatches` por fora (regra cooperativa).
"""

from __future__ import annotations

import json
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from portao.decisao import TOPO_MAX
from portao.gramatica import Comando
from portao.quadro import ARTEFATO, EVENT_TYPE, ler_registro_zip, nome_do_run

TETO_ESPERA = 90  # segundos; o hook de prompt tem `timeout` maior na conta (D8)
INTERVALO = 3
ORIGEM_CAMPOS = ("cliente", "superficie", "versao_host", "sessao")


class ExecutorIndisponivel(RuntimeError):
    pass


@dataclass(frozen=True)
class ConfigExecutor:
    repo: str  # owner/nome do repo do executor
    event_type: str = EVENT_TYPE


def config_do_overlay(overlay: Mapping[str, Any] | None) -> ConfigExecutor | None:
    """`board.executor` do overlay; sem a chave, None (o `process_event` usa o mover antigo e o hook não captura)."""

    from overlay import board_executor

    dados = board_executor(overlay)
    if dados is None:
        return None
    return ConfigExecutor(repo=dados["repo"], event_type=dados.get("event_type") or EVENT_TYPE)


class Disparador(Protocol):
    def disparar(self, repo: str, event_type: str, payload: Mapping[str, Any]) -> None: ...

    def achar_run(self, repo: str, request_id: str) -> Mapping[str, Any] | None: ...

    def registro(self, repo: str, run_id: int) -> Mapping[str, Any] | None: ...


class GhDisparador:
    """`gh api` com o token do `gh` da VM (o do agente depois da migração)."""

    def _gh(self, args: list[str], entrada: bytes | None = None) -> bytes:
        try:
            proc = subprocess.run(["gh", "api", *args], input=entrada, capture_output=True, check=False, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ExecutorIndisponivel(f"gh api: {exc}") from exc
        if proc.returncode != 0:
            raise ExecutorIndisponivel((proc.stderr or proc.stdout or b"gh api falhou").decode("utf-8", "replace").strip()[:300])
        return proc.stdout

    def disparar(self, repo: str, event_type: str, payload: Mapping[str, Any]) -> None:
        corpo = json.dumps({"event_type": event_type, "client_payload": dict(payload)}).encode("utf-8")
        self._gh([f"repos/{repo}/dispatches", "--method", "POST", "--input", "-"], corpo)

    def achar_run(self, repo: str, request_id: str) -> Mapping[str, Any] | None:
        dados = json.loads(self._gh([f"repos/{repo}/actions/runs?event=repository_dispatch&per_page=30"]).decode("utf-8") or "{}")
        for run in dados.get("workflow_runs") or []:
            if request_id in str(run.get("display_title") or ""):
                return run
        return None

    def registro(self, repo: str, run_id: int) -> Mapping[str, Any] | None:
        dados = json.loads(self._gh([f"repos/{repo}/actions/runs/{run_id}/artifacts"]).decode("utf-8") or "{}")
        for artefato in dados.get("artifacts") or []:
            if artefato.get("name") == ARTEFATO and not artefato.get("expired"):
                return ler_registro_zip(self._gh([f"repos/{repo}/actions/artifacts/{artefato['id']}/zip"]))
        return None


def montar_pedido(
    tipo: str,
    evento: str,
    card: int | str,
    *,
    de: str | None,
    ator: str,
    comando: str | None = None,
    origem: Mapping[str, Any] | None = None,
    extras: Mapping[str, Any] | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """`client_payload` do D4. Cliente, superfície, versão e sessão vão juntos em `origem` (limite de 10 no topo)."""

    pedido = {
        "request_id": request_id or uuid.uuid4().hex,
        "tipo": tipo,
        "evento": evento,
        "card": int(str(card).lstrip("#")),
        "de": de,
        "ator": ator,
        "comando": comando,
        "origem": {campo: (origem or {}).get(campo) for campo in ORIGEM_CAMPOS},
        "extras": {k: v for k, v in (extras or {}).items() if v is not None},
    }
    assert len(pedido) <= TOPO_MAX
    return pedido


def _falha(pedido: Mapping[str, Any], resultado: str, mensagem: str, run_url: str | None = None) -> dict[str, Any]:
    return {**pedido, "resultado": resultado, "codigo": resultado, "mensagem": mensagem, "run_url": run_url, "para": None}


def enviar(
    pedido: Mapping[str, Any],
    config: ConfigExecutor,
    *,
    disparador: Disparador | None = None,
    teto: float = TETO_ESPERA,
    intervalo: float = INTERVALO,
    relogio: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Dispara e espera o registro do run. `resultado` ∈ movido | pendente | recusado | timeout | indisponivel."""

    via = disparador or GhDisparador()
    try:
        via.disparar(config.repo, config.event_type, pedido)
    except (ExecutorIndisponivel, OSError, ValueError) as exc:
        return _falha(pedido, "indisponivel", f"disparo ao executor falhou: {exc}")
    limite = relogio() + teto
    run_url: str | None = None
    while True:
        try:
            run = via.achar_run(config.repo, str(pedido["request_id"]))
            if run is not None:
                run_url = str(run.get("html_url") or "") or run_url
                if run.get("status") == "completed":
                    registro = via.registro(config.repo, int(run["id"]))
                    if registro is None:
                        return _falha(pedido, "indisponivel", f"o run terminou ({run.get('conclusion')}) sem registro", run_url)
                    return {**dict(registro), "run_url": registro.get("run_url") or run_url}
        except (ExecutorIndisponivel, OSError, ValueError, KeyError) as exc:
            if relogio() >= limite:
                return _falha(pedido, "indisponivel", f"consulta ao executor falhou: {exc}", run_url)
        if relogio() >= limite:
            return _falha(pedido, "timeout", f"sem resposta do executor em {int(teto)} s", run_url)
        dormir(intervalo)


def pedir(
    evento: str,
    card: int | str,
    *,
    de: str | None,
    ator: str,
    config: ConfigExecutor,
    origem: Mapping[str, Any] | None = None,
    extras: Mapping[str, Any] | None = None,
    disparador: Disparador | None = None,
    teto: float = TETO_ESPERA,
    **espera: Any,
) -> dict[str, Any]:
    pedido = montar_pedido("pedir", evento, card, de=de, ator=ator, origem=origem, extras=extras)
    return enviar(pedido, config, disparador=disparador, teto=teto, **espera)


def capturar(
    comando: Comando,
    *,
    config: ConfigExecutor,
    origem: Mapping[str, Any] | None = None,
    extras: Mapping[str, Any] | None = None,
    disparador: Disparador | None = None,
    teto: float = TETO_ESPERA,
    **espera: Any,
) -> dict[str, Any]:
    """Comando do Alan reconhecido pelo hook de prompt. `de` é a coluna exigida pelo comando (None = coluna viva)."""

    dados = dict(extras or {})
    if comando.motivo is not None:
        dados["motivo"] = comando.motivo
    pedido = montar_pedido("capturar", comando.evento, comando.card, de=comando.origem, ator="Alan", comando=comando.texto,
                           origem=origem, extras=dados)
    return enviar(pedido, config, disparador=disparador, teto=teto, **espera)
