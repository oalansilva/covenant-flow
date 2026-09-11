"""Cursor subagentStop destape: order the mute parent after a completed waited child.

Fail-open. No GitHub. stdin JSON → one JSON object on stdout.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

REPO_FROM_FILE = Path(__file__).resolve().parents[2]
SIDECAR_REL = Path(".cursor") / "tmp" / "awaiting-task.json"

FOLLOWUP_GRILL = (
    "O filho grill já devolveu. Faz o relaying das Qs / handoff T1 agora. "
    "Não perguntes se concluiu. Não spawnes outro grill."
)
FOLLOWUP_APPLY = (
    "O filho Apply já devolveu. "
    "Se as tasks estão feitas ou há P0 visível: materializa o diff e "
    "spawna os dois reviewers (diff-reviewer + code-reviewer) no mesmo turno; "
    "não spawnes outro Apply. "
    "Se devolveu cedo sem P0: bloqueio visível, não abras review. "
    "Não perguntes se concluiu."
)
FOLLOWUP_REVIEW = (
    "O filho reviewer já devolveu. Se o par da onda ainda não devolveu: espera (não commitas, não spawnes o outro reviewer agora).\n"
    "Tabela destape (não pontues cláusula em falta):\n"
    "limpo → commit\n"
    "só juízo → residual, card segue (não gasta correção)\n"
    "mecânico → no máximo um conserto + uma verificação\n"
    "após 1+1 → residual, card segue\n"
    "P0 → a coluna pára\n"
    "MUST NOT «autorizar extra / aceitar residual». Não perguntes se concluiu."
)
FOLLOWUP_QA = (
    "O filho QA já devolveu. Fecha o QA conforme o veredito "
    "(verde → integrar_develop; falhou → evidência visível). "
    "Sinal determinístico (inventário, formatação, skip de ficheiro novo) "
    "fica no Apply/QA até verde ou teto; não reabras onda de juízo. "
    "Não perguntes se concluiu."
)
FOLLOWUP_DESIGN_AUTOR = (
    "O filho Design-autor já devolveu. Spawna o crítico (sem-tela) ou a "
    "dupla A/B (com-tela). Não perguntes se concluiu. Não spawnes outro autor."
)
FOLLOWUP_DESIGN_CRITIC = (
    "O filho crítico de Design já devolveu. Escreve ## Design Critique, "
    "publica o Gist e chama submeter_design. Não perguntes se concluiu."
)

FOLLOWUPS = {
    "grill": FOLLOWUP_GRILL,
    "apply": FOLLOWUP_APPLY,
    "review": FOLLOWUP_REVIEW,
    "qa": FOLLOWUP_QA,
    "design_autor": FOLLOWUP_DESIGN_AUTOR,
    "design_critic": FOLLOWUP_DESIGN_CRITIC,
}

FORBIDDEN_QUESTION = ("concluiu?", "já acabou?", "verifique se nao concluiu")
_EMPTY = "{}"
_EXPLORE_SHELL = frozenset({"explore", "shell"})


def _as_dict(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {}


def _str(raw: Any) -> str:
    return raw.strip() if isinstance(raw, str) else ""


def _truthy(raw: Any) -> bool:
    if raw is True:
        return True
    if isinstance(raw, str) and raw.strip().lower() in {"true", "1", "yes"}:
        return True
    return False


def _as_int(raw: Any) -> int | None:
    if isinstance(raw, bool) or raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.strip().lstrip("-").isdigit():
        return int(raw.strip())
    return None


def _nested(payload: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key in ("tool_input", "toolInput"):
        merged.update(_as_dict(payload.get(key)))
    return merged


def _kind_token(payload: dict[str, Any]) -> str:
    nested = _nested(payload)
    for raw in (
        payload.get("subagent_type"),
        payload.get("type"),
        payload.get("task"),
        nested.get("subagent_type"),
        nested.get("task"),
    ):
        token = _str(raw).lower()
        if token in _EXPLORE_SHELL:
            return token
    return ""


def _sidecar_description(sidecar: dict[str, Any]) -> str:
    return _str(sidecar.get("description")) or _str(_nested(sidecar).get("description"))


def _sidecar_type(sidecar: dict[str, Any]) -> str:
    nested = _nested(sidecar)
    return (
        _str(sidecar.get("subagent_type"))
        or _str(sidecar.get("task"))
        or _str(nested.get("subagent_type"))
        or _str(nested.get("task"))
    )


def _stop_subagent_type(payload: dict[str, Any]) -> str:
    nested = _nested(payload)
    return _str(payload.get("subagent_type")) or _str(nested.get("subagent_type"))


def _stop_description_candidates(payload: dict[str, Any]) -> tuple[str, ...]:
    nested = _nested(payload)
    return (
        _str(payload.get("task")),
        _str(payload.get("description")),
        _str(nested.get("task")),
        _str(nested.get("description")),
    )


def _classify_sources(sidecar: dict[str, Any], payload: dict[str, Any]) -> str:
    """Classify only from sidecar.description ∪ stop.task ∪ subagent_type.

    MUST NOT include the long prompt (``description`` / pasted skill body).
    Stop ``task`` is the short spawn title (top-level or nested).
    """
    nested = _nested(payload)
    parts = (
        _sidecar_description(sidecar),
        _str(payload.get("task")),
        _str(nested.get("task")),
        _str(payload.get("subagent_type")),
        _str(nested.get("subagent_type")),
    )
    return "\n".join(p for p in parts if p)


def classify_etapa(text: str) -> str | None:
    """Classify a waited Cursor etapa. Bare word Design is not a match.

    Design-autor MUST match before crítico / Assessment A/B.
    """
    t = text.lower()
    if "design-autor" in t or "design autor" in t:
        return "design_autor"
    if "design-critic" in t or "design-crítico" in t or "design crítico" in t:
        return "design_critic"
    if "assessment a" in t or "assessment b" in t:
        return "design_critic"
    if "grill-card" in t or "grelha" in t or re.search(r"\bgrill\b", t):
        return "grill"
    if "apply-coluna" in t or "apply coluna" in t:
        return "apply"
    if "diff-reviewer" in t or "code-reviewer" in t:
        return "review"
    if "qa-gate" in t or re.search(r"\bqa\b", t):
        return "qa"
    return None


def _root(payload: dict[str, Any], root: Path | None) -> Path:
    if root is not None:
        return Path(root)
    env = os.environ.get("PROCESS_FSM_ROOT")
    if env:
        return Path(env)
    cwd = payload.get("cwd") or payload.get("workspaceRoot")
    if cwd:
        return Path(str(cwd))
    return REPO_FROM_FILE


def sidecar_path(payload: dict[str, Any], root: Path | None = None) -> Path:
    return _root(payload, root) / SIDECAR_REL


def _sidecar_matches(sidecar: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Sidecar ``description`` MUST be the exact Task description the parent spawned.

    Empty description is not a wildcard. Cursor ``subagentStop`` may place that
    string in ``task`` (the 3–5 word title). Optional sidecar ``task`` /
    ``subagent_type`` compares to stop ``subagent_type`` (or nested), never to
    stop ``task``.
    """
    sd = _sidecar_description(sidecar)
    if not sd:
        return False
    if sd not in _stop_description_candidates(payload):
        return False
    sidecar_type = _sidecar_type(sidecar)
    if not sidecar_type:
        return True
    stop_type = _stop_subagent_type(payload)
    if not stop_type:
        return True
    return sidecar_type == stop_type


def _load_sidecar(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _delete_sidecar(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _empty() -> dict[str, Any]:
    return {}


def decide(payload: dict[str, Any], *, root: Path | None = None) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return _empty()
    status = _str(payload.get("status")).lower()
    if status != "completed":
        return _empty()
    if "loop_count" in payload:
        loop_raw = payload.get("loop_count")
    elif "loopCount" in payload:
        loop_raw = payload.get("loopCount")
    else:
        loop_raw = 0
    if _as_int(loop_raw) != 0:
        return _empty()
    if _truthy(payload.get("is_parallel_worker") if "is_parallel_worker" in payload else payload.get("isParallelWorker")):
        return _empty()
    if _kind_token(payload) in _EXPLORE_SHELL:
        return _empty()
    path = sidecar_path(payload, root)
    sidecar = _load_sidecar(path)
    if sidecar is None or not _sidecar_matches(sidecar, payload):
        return _empty()
    etapa = classify_etapa(_classify_sources(sidecar, payload))
    if etapa is None:
        return _empty()
    message = FOLLOWUPS[etapa]
    if any(bad in message.lower() for bad in FORBIDDEN_QUESTION):
        return _empty()
    _delete_sidecar(path)
    return {"followup_message": message}


def handle(raw: str, *, root: Path | None = None) -> dict[str, Any]:
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return _empty()
    try:
        return decide(payload, root=root)
    except Exception:
        return _empty()


def main() -> int:
    try:
        raw = sys.stdin.read()
        result = handle(raw)
        sys.stdout.write(json.dumps(result, ensure_ascii=True) + "\n")
    except Exception:
        sys.stdout.write(_EMPTY + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
