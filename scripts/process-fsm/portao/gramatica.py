"""Gramática exata dos comandos de portão do Alan (design D6). Função pura, sem I/O.

Casa só quando a mensagem inteira, sem o espaço em branco final, é uma destas linhas:

    /priorizar <card>
    /aprovar-design <card>
    /devolver-design <card> "<motivo>"
    /homologar <card>
    /nao-homologar <card> "<motivo>"
    /cancelar <card> "<motivo>"
    /confirmar-cancelar <card>

`<card>` = número do issue, com ou sem `#`. `<motivo>` = 1 a 500 caracteres entre aspas duplas, sem aspas nem quebra
de linha dentro, com ao menos um caractere visível. Maiúscula diferente, palavra a mais, espaço duplo, outra linha
antes ou depois ou espaço no começo não casam.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MOTIVO_MAX = 500

# nome do comando -> (evento da FSM, exige motivo, é a confirmação do cancelamento)
COMANDOS: dict[str, tuple[str, bool, bool]] = {
    "priorizar": ("priorizar", False, False),
    "aprovar-design": ("aprovar_design", False, False),
    "devolver-design": ("devolver_design", True, False),
    "homologar": ("homologar", False, False),
    "nao-homologar": ("nao_homologar", True, False),
    "cancelar": ("cancelar", True, False),
    "confirmar-cancelar": ("cancelar", False, True),
}

# Coluna de origem exigida por comando; `None` = qualquer coluna viva (fora de Pronto e Cancelado).
ORIGEM: dict[str, str | None] = {
    "priorizar": "Em Refinamento",
    "aprovar-design": "Aprovação de Design",
    "devolver-design": "Aprovação de Design",
    "homologar": "Done",
    "nao-homologar": "Done",
    "cancelar": None,
    "confirmar-cancelar": None,
}

# Linha de motivo do recibo (D4); a de `nao_homologar` satisfaz `motivo_visivel`.
LINHA_MOTIVO = {"devolver_design": "Devolver design", "nao_homologar": "Não homologar", "cancelar": "Cancelar"}

_CARD = r"#?([1-9][0-9]{0,8})"
_SEM_MOTIVO = re.compile(r"/(priorizar|aprovar-design|homologar|confirmar-cancelar) " + _CARD)
_COM_MOTIVO = re.compile(r"/(devolver-design|nao-homologar|cancelar) " + _CARD + r' "([^"\r\n]{1,%d})"' % MOTIVO_MAX)
# Prefixo barato para o shim decidir se a falha visível de um prompt é de comando de portão (sem a gramática inteira).
PREFIXO = re.compile(r"/(?:priorizar|aprovar-design|devolver-design|homologar|nao-homologar|cancelar|confirmar-cancelar)(?:\s|$)")


@dataclass(frozen=True)
class Comando:
    nome: str
    evento: str
    card: int
    motivo: str | None
    texto: str

    @property
    def confirmacao(self) -> bool:
        return COMANDOS[self.nome][2]

    @property
    def origem(self) -> str | None:
        return ORIGEM[self.nome]


def reconhecer(mensagem: object) -> Comando | None:
    """O comando que a mensagem inteira é, ou None. Nunca procura comando dentro de outro texto."""

    if not isinstance(mensagem, str):
        return None
    texto = mensagem.rstrip()
    if not texto or "\n" in texto or "\r" in texto:
        return None
    achado = _SEM_MOTIVO.fullmatch(texto)
    motivo: str | None = None
    if achado is None:
        achado = _COM_MOTIVO.fullmatch(texto)
        if achado is None:
            return None
        motivo = achado.group(3)
        if not motivo.strip() or not motivo.isprintable():
            return None
    nome = achado.group(1)
    return Comando(nome=nome, evento=COMANDOS[nome][0], card=int(achado.group(2)), motivo=motivo, texto=texto)


def parece_comando(mensagem: object) -> bool:
    """True quando a mensagem começa como um comando de portão (casando ou não com a gramática)."""

    return isinstance(mensagem, str) and PREFIXO.match(mensagem.lstrip()) is not None
