"""Load and evaluate `.cursor/process-fsm.yaml` without GitHub or Cursor hooks."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
YAML_PATH = REPO_ROOT / ".cursor" / "process-fsm.yaml"

LEGAL_SIGMA = (
    "criar_card",
    "priorizar",
    "cancelar",
    "iniciar_design",
    "recriticar",
    "submeter_design",
    "devolver_design",
    "aprovar_design",
    "iniciar_apply",
    "pedir_review",
    "achar_bloqueante",
    "aceitar_sha",
    "rerun_infra",
    "falha_codigo",
    "integrar_develop",
    "homologar",
    "fechar_release",
    "invalidar_aprovacao",
)

ILLEGAL_EVENTS = frozenset({"request_implement", "pular_coluna", "Agent.aprovar_design"})

EXPECTED_MATRIX = (
    ("T0", None, "criar_card", "Em Refinamento"),
    ("T1", "Em Refinamento", "priorizar", "Todo"),
    ("T2", "Vivo", "cancelar", "Cancelado"),
    ("T3", "Todo", "iniciar_design", "Design"),
    ("T4", "Design", "recriticar", "Design"),
    ("T5", "Design", "submeter_design", "Aprovação de Design"),
    ("T6", "Aprovação de Design", "devolver_design", "Design"),
    ("T7", "Aprovação de Design", "aprovar_design", "Pronto para Dev"),
    ("T8", "Pronto para Dev", "iniciar_apply", "Em desenvolvimento"),
    ("T9", "Em desenvolvimento", "pedir_review", "Code Review"),
    ("T10", "Code Review", "achar_bloqueante", "Em desenvolvimento"),
    ("T11", "Code Review", "aceitar_sha", "QA"),
    ("T12", "QA", "rerun_infra", "QA"),
    ("T13", "QA", "falha_codigo", "Em desenvolvimento"),
    ("T14", "QA", "integrar_develop", "Done"),
    ("T15", "Done", "homologar", "Homologado"),
    ("T16", "Homologado", "fechar_release", "Pronto"),
    ("T17a", "Pronto para Dev", "invalidar_aprovacao", "Design"),
    ("T17b", "Em desenvolvimento", "invalidar_aprovacao", "Design"),
)

ALAN_GATES = {"T1": "priorizar", "T7": "aprovar_design", "T15": "homologar"}
AGENT_GATES = {"T16": "fechar_release"}

CARD_GIT_RE = re.compile(r"^card-(\d+)(?:-.*)?$")


class ValidationError(ValueError):
    pass


def load_fsm(path: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load((path or YAML_PATH).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValidationError("process-fsm.yaml must be a mapping")
    return data


def _actor_set(actor: Any) -> set[str]:
    if actor is None:
        return set()
    if isinstance(actor, str):
        return {actor}
    return set(actor)


def vivo_states(fsm: dict[str, Any]) -> list[str]:
    terminal = set(fsm.get("terminal_states") or [])
    return [s for s in fsm.get("states") or [] if s not in terminal]


def expand_transitions(fsm: dict[str, Any]) -> list[dict[str, Any]]:
    vivo = vivo_states(fsm)
    expanded: list[dict[str, Any]] = []
    for row in fsm.get("transitions") or []:
        source = row.get("from")
        if source == "Vivo":
            for state in vivo:
                clone = copy.deepcopy(row)
                clone["from"] = state
                clone["expanded_from"] = "Vivo"
                expanded.append(clone)
        else:
            expanded.append(copy.deepcopy(row))
    return expanded


def validate_fsm(fsm: dict[str, Any]) -> None:
    required = (
        "states",
        "transitions",
        "illegal_events",
        "illegal_edges",
        "enabled_tools",
        "enabled_events",
        "context_file",
        "invariants",
        "fail_closed_asymmetric",
    )
    missing = [key for key in required if key not in fsm]
    if missing:
        raise ValidationError(f"missing keys: {missing}")
    if fsm.get("fail_closed_asymmetric") is not True:
        raise ValidationError("fail_closed_asymmetric must be true")

    invariant_ids = {item.get("id") for item in fsm.get("invariants") or [] if isinstance(item, dict)}
    expected_ids = {f"I{n}" for n in range(1, 10)}
    if invariant_ids != expected_ids:
        raise ValidationError(f"invariants must be I1–I9, got {sorted(invariant_ids)}")

    illegal = list(fsm.get("illegal_events") or [])
    if "write_produto" in illegal:
        raise ValidationError("write_produto must not be in illegal_events")
    if set(illegal) != ILLEGAL_EVENTS:
        raise ValidationError(f"illegal_events must be {sorted(ILLEGAL_EVENTS)}")

    rows = list(fsm.get("transitions") or [])
    by_id = {row.get("id"): row for row in rows}
    for tid, source, event, dest in EXPECTED_MATRIX:
        row = by_id.get(tid)
        if row is None:
            raise ValidationError(f"missing transition {tid}")
        if row.get("from") != source or row.get("event") != event or row.get("to") != dest:
            raise ValidationError(f"{tid} does not match the design.md matrix")

    sigma = {row.get("event") for row in rows}
    if sigma != set(LEGAL_SIGMA):
        raise ValidationError(f"Σ diverges from the legal alphabet: {sorted(sigma)}")

    for tid, event in ALAN_GATES.items():
        row = by_id[tid]
        if "Alan" not in _actor_set(row.get("actor")) or row.get("event") != event:
            raise ValidationError(f"{tid} must include actor Alan")
    for tid, event in AGENT_GATES.items():
        row = by_id[tid]
        actors = _actor_set(row.get("actor"))
        if "Agent" not in actors or row.get("event") != event:
            raise ValidationError(f"{tid} must include actor Agent")
        if actors == {"Alan"}:
            raise ValidationError(f"{tid} must not be Alan-only")

    expanded = expand_transitions(fsm)
    if not any(row.get("expanded_from") == "Vivo" for row in expanded):
        raise ValidationError("T2 from: Vivo must expand")

    seen: dict[tuple[Any, Any], str] = {}
    for row in expanded:
        key = (row.get("from"), row.get("event"))
        if key in seen:
            raise ValidationError(f"overlapping transition {key}")
        seen[key] = row.get("id") or ""

    for state, event_pairs, group in (
        ("Design", (("recriticar", "T4"), ("submeter_design", "T5")), "design-exit"),
        ("Code Review", (("achar_bloqueante", "T10"), ("aceitar_sha", "T11")), "cr-exit"),
        ("QA", (("rerun_infra", "T12"), ("falha_codigo", "T13"), ("integrar_develop", "T14")), "qa-exit"),
    ):
        for event, tid in event_pairs:
            row = by_id[tid]
            if row.get("from") != state or row.get("event") != event:
                raise ValidationError(f"{tid} determinism group {group} mismatch")
            if row.get("exclusive_group") != group:
                raise ValidationError(f"{tid} must set exclusive_group={group}")

    if "product_globs" in fsm or "design_globs" in fsm:
        raise ValidationError("product_globs/design_globs belong in overlay, not yaml law")

    states = list(fsm.get("states") or [])
    for key in ("enabled_tools", "enabled_events", "context_file"):
        mapping = fsm.get(key) or {}
        if set(mapping) != set(states):
            raise ValidationError(f"{key} must cover every state")


def _unbound(bound_card: Any) -> bool:
    return bound_card in (None, "", "⊥")


def edge_matches(edge: dict[str, Any], ctx: "EvalContext") -> bool:
    if edge.get("event") != ctx.event:
        return False
    if "state" in edge and edge["state"] != ctx.state:
        return False
    if "q_git" in edge and edge["q_git"] != ctx.q_git:
        return False
    if edge.get("unbound") and not _unbound(ctx.bound_card):
        return False
    if edge.get("unbound") is False and _unbound(ctx.bound_card):
        return False
    if "actor" in edge and edge["actor"] != ctx.actor:
        return False
    return True


def i1_write_allowed(ctx: "EvalContext") -> bool:
    if ctx.state not in {"Em desenvolvimento", "Code Review"}:
        return False
    if ctx.q_git in {None, "", "develop", "main", "⊥"}:
        return False
    if _unbound(ctx.bound_card):
        return False
    match = CARD_GIT_RE.match(str(ctx.q_git))
    if match is None:
        return False
    if str(ctx.bound_card) != match.group(1):
        return False
    if ctx.path:
        # #610 will classify by worktree of path; here we only reject obvious escapes.
        return True
    return True


@dataclass(frozen=True)
class EvalContext:
    state: str | None
    event: str
    actor: str | None = None
    q_git: str | None = None
    bound_card: str | int | None = None
    path: str | None = None
    g_design: bool | None = None
    digest_changed: bool | None = None
    m_lote: bool | None = None
    checks_green: bool | None = None
    open_p0_p1: bool | None = None
    reviewers_ok: bool | None = None
    flaky_infra: bool | None = None
    source_failure: bool | None = None


@dataclass(frozen=True)
class EvalResult:
    result: str  # allow | reject | transition
    state: str | None
    to: str | None = None
    reason: str | None = None


NAMED_GUARDS = {
    "G_design": "g_design",
    "digest_changed": "digest_changed",
    "M_lote": "m_lote",
    "checks_green": "checks_green",
    "open_p0_p1": "open_p0_p1",
    "reviewers_ok": "reviewers_ok",
    "flaky_infra": "flaky_infra",
    "source_failure": "source_failure",
}

I4_EVENTS = frozenset({"iniciar_apply", "pedir_review"})


def q_git_card(q_git: str | None) -> bool:
    return bool(q_git) and CARD_GIT_RE.match(str(q_git)) is not None


def enabled_events(fsm: dict[str, Any], state: str | None) -> list[str]:
    mapping = fsm.get("enabled_events") or {}
    if state is None:
        return []
    values = mapping.get(state) or []
    return list(values)


def _guard_holds(row: dict[str, Any], ctx: EvalContext) -> EvalResult | None:
    name = row.get("guard")
    if not name:
        return None
    if name == "q_git_card":
        if q_git_card(ctx.q_git):
            return None
        return EvalResult("reject", ctx.state, None, "guard:q_git_card")
    field = NAMED_GUARDS.get(str(name))
    if field is None:
        return EvalResult("reject", ctx.state, None, f"guard:{name}")
    value = getattr(ctx, field)
    if value is True:
        return None
    return EvalResult("reject", ctx.state, None, f"guard:{name}")


def evaluate(fsm: dict[str, Any], ctx: EvalContext) -> EvalResult:
    if ctx.event in set(fsm.get("illegal_events") or []):
        return EvalResult("reject", ctx.state, None, "illegal_event")
    for edge in fsm.get("illegal_edges") or []:
        if edge_matches(edge, ctx):
            return EvalResult("reject", ctx.state, None, edge.get("id") or "illegal_edge")
    if ctx.event == "write_produto":
        if i1_write_allowed(ctx):
            return EvalResult("allow", ctx.state, ctx.state, "I1")
        return EvalResult("reject", ctx.state, None, "I1")
    for row in expand_transitions(fsm):
        if row.get("from") != ctx.state or row.get("event") != ctx.event:
            continue
        actors = _actor_set(row.get("actor"))
        if actors:
            if ctx.actor is None or ctx.actor not in actors:
                return EvalResult("reject", ctx.state, None, "actor")
        if ctx.event in I4_EVENTS and ctx.digest_changed is not False:
            return EvalResult("reject", ctx.state, None, "I4")
        blocked = _guard_holds(row, ctx)
        if blocked is not None:
            return blocked
        return EvalResult("transition", ctx.state, row.get("to"), row.get("id"))
    return EvalResult("reject", ctx.state, None, "no_edge")
