"""Formatador do recibo que o executor posta na issue (design D4).

    <linha de motivo, só quando o card moveu ou ficou pendente: "Devolver design: …" | "Não homologar: …" | "Cancelar: …">
    Portão: `<comando como digitado>` — <movido De → Para | recusado: motivo | pendente: …>
    Quando: <AAAA-MM-DD HH:MM BRT> · Cliente: <cliente>/<superfície> <versão> · Sessão: <id curto>
    Executor: <run_url> · Lei: <repo>@<SHA do PIN>

Pedido do agente troca a segunda linha por "Pedido do agente: `<evento>` — …". Recibo de comando recusado nunca começa
pela linha de motivo: senão um `Não homologar:` recusado satisfaria depois o `motivo_visivel` de um arrasto.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from portao.decisao import brt
from portao.gramatica import LINHA_MOTIVO

INDISPONIVEL = "unavailable"


def resultado_texto(resultado: str, caminho: Sequence[str | None], mensagem: str | None, codigo: str | None) -> str:
    if resultado == "movido":
        texto = "movido " + " → ".join(str(c) for c in caminho)
        return f"{texto}; {mensagem}" if mensagem else texto
    if resultado == "pendente":
        return f"pendente: {mensagem or 'aguardando confirmação'}"
    return f"recusado: {mensagem or codigo or 'sem motivo'}"


def _curto(valor: Any, tamanho: int = 8) -> str:
    texto = str(valor).strip() if valor not in (None, "") else INDISPONIVEL
    return texto if texto == INDISPONIVEL else texto[:tamanho]


def formatar(
    *,
    tipo: str,
    evento: str,
    comando: str | None,
    resultado: str,
    caminho: Sequence[str | None],
    mensagem: str | None,
    codigo: str | None,
    motivo: str | None,
    origem: Mapping[str, Any],
    agora: datetime,
    run_url: str | None,
    lei: str,
    digest: str | None = None,
) -> str:
    linhas: list[str] = []
    rotulo = LINHA_MOTIVO.get(evento)
    if rotulo and motivo and resultado in ("movido", "pendente"):
        linhas.append(f"{rotulo}: {motivo}")
    texto = resultado_texto(resultado, caminho, mensagem, codigo)
    if tipo == "capturar":
        linhas.append(f"Portão: `{comando}` — {texto}")
    else:
        linhas.append(f"Pedido do agente: `{evento}` — {texto}")
    if digest:
        linhas.append(f"Design: sha256 {digest}")
    cliente = origem.get("cliente") or INDISPONIVEL
    superficie = origem.get("superficie") or INDISPONIVEL
    versao = origem.get("versao_host") or INDISPONIVEL
    linhas.append(f"Quando: {brt(agora)} · Cliente: {cliente}/{superficie} {versao} · Sessão: {_curto(origem.get('sessao'))}")
    linhas.append(f"Executor: {run_url or INDISPONIVEL} · Lei: {lei}")
    return "\n".join(linhas) + "\n"
