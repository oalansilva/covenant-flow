"""Shared Cursor/Codex release-closeout table. No FSM events. No guard.decide() edits."""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
ISSUE_1022 = "#1022"
GENERIC_ARCHIVE_MENU = "Sync now / Archive without syncing"
GENERIC_PACKAGE_NAMES = frozenset({"", "<pacote>", "pacote", "release-guard post"})
PRONTO_PLACEHOLDERS = (
    "<pacote>",
    "<lista ou pendência>",
    "<deploy PROD pendente>",
)
SECRET_KEY_NEEDLES = (
    "secret",
    "token",
    "password",
    "credential",
    "authorization",
    "transcript",
    "session",
    "gh_token",
    "api_key",
)
FORBIDDEN_MANIFEST_VALUES = ("BEGIN ", "PRIVATE KEY", "ghp_", "gho_", "github_pat_")
T16_BLOCKER_MESSAGE_CAP = 4000
DOCUMENTAL_ALLOWLIST = (
    "docs/",
    "openspec/changes/archive/",
    "openspec/specs/",
    "AGENTS.md",
    "rules.md",
)

CLIENT_CURSOR = "cursor"
CLIENT_CODEX = "codex"
BAND_EXECUCAO = "execucao"


@dataclass(frozen=True)
class ContextIdentity:
    package: str
    cwd: str
    head: str
    refs: tuple[str, ...]
    branch: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "cwd": self.cwd,
            "head": self.head,
            "refs": list(self.refs),
            "branch": self.branch,
        }


@dataclass(frozen=True)
class Decision:
    action: str
    reason: str
    gaps: tuple[dict[str, str], ...] = ()
    blocker: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "gaps": [dict(item) for item in self.gaps],
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class FieldValue:
    card: str
    field: str
    value: str | None
    origin: str
    gap: bool
    attributed_to_alan: bool = False


@dataclass(frozen=True)
class QuestionItem:
    card: str
    field: str
    prompt: str
    options: tuple[str, ...]
    recommended: str | None = None


@dataclass
class Manifest:
    package: str
    decisions: dict[str, Any]
    origins: dict[str, str]
    evidence_refs: list[str]
    completed_steps: list[str]
    context: dict[str, Any]
    asked_gaps: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "package": self.package,
            "decisions": dict(self.decisions),
            "origins": dict(self.origins),
            "evidence_refs": list(self.evidence_refs),
            "completed_steps": list(self.completed_steps),
            "context": dict(self.context),
            "asked_gaps": list(self.asked_gaps),
        }


@dataclass(frozen=True)
class PreflightItem:
    kind: str
    pending: bool
    detail: str
    started: bool = False


@dataclass(frozen=True)
class ArchivePlan:
    proceed: bool
    ask: bool
    blocker: str
    points_at_1022: bool
    use_generic_menu: bool = False
    worktree_cherry_pick: bool = False


@dataclass(frozen=True)
class MergeSimulation:
    ok: bool
    conflict: bool
    detail: str
    open_pr: bool


from release_model_selection import ModelCheck, load_execucao_pair, check_runtime_model

def manifesto_dir(env: Mapping[str, str] | None = None) -> Path:
    source = env if env is not None else os.environ
    xdg = (source.get("XDG_STATE_HOME") or "").strip()
    if xdg:
        return Path(xdg) / "covenant-flow" / "release-closeout"
    return Path.home() / ".local" / "state" / "covenant-flow" / "release-closeout"


def manifesto_path(package: str, env: Mapping[str, str] | None = None) -> Path:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", (package or "unnamed").strip()) or "unnamed"
    return manifesto_dir(env) / f"{slug}.json"


def capture_context(
    cwd: str | Path,
    *,
    package: str = "",
    runner: Any = subprocess.run,
) -> ContextIdentity:
    work = Path(cwd).resolve()
    head = _git_one(runner, work, ["rev-parse", "HEAD"])
    branch = _git_one(runner, work, ["rev-parse", "--abbrev-ref", "HEAD"])
    refs = []
    for ref in ("origin/develop", "origin/main"):
        sha = _git_one(runner, work, ["rev-parse", ref])
        if sha:
            refs.append(f"{ref}={sha}")
    return ContextIdentity(
        package=str(package or ""),
        cwd=str(work),
        head=head,
        refs=tuple(refs),
        branch=branch,
    )


def same_context(left: ContextIdentity | None, right: ContextIdentity | None) -> bool:
    if left is None or right is None:
        return True
    return (
        left.package == right.package
        and left.cwd == right.cwd
        and left.head == right.head
        and left.refs == right.refs
    )


def describe_context_divergence(left: ContextIdentity, right: ContextIdentity) -> str:
    parts: list[str] = []
    if left.package != right.package:
        parts.append(f"package {left.package!r} vs {right.package!r}")
    if left.cwd != right.cwd:
        parts.append(f"cwd {left.cwd} vs {right.cwd}")
    if left.head != right.head:
        parts.append(f"HEAD {left.head} vs {right.head}")
    if left.refs != right.refs:
        parts.append("refs differ")
    return "context divergence: " + "; ".join(parts or ["unknown"])


def evaluate_decision(
    *,
    authorized: bool,
    data_available: bool,
    gaps: Sequence[Mapping[str, str]] = (),
    already_asked: Sequence[str] = (),
    external_blocker: str = "",
    human_gate_missing: bool = False,
) -> Decision:
    """Single table: proceed / ask_once / stop. Cursor and Codex share this."""
    if human_gate_missing:
        return Decision(
            action="stop",
            reason="human_gate",
            blocker=external_blocker or "human gate still required",
        )
    if external_blocker:
        return Decision(action="stop", reason="external_blocker", blocker=external_blocker)
    remaining = []
    unanswered = []
    asked = set(already_asked)
    for gap in gaps:
        card = str(gap.get("card") or "")
        field_name = str(gap.get("field") or "")
        key = f"{card}:{field_name}"
        item = {"card": card, "field": field_name, "prompt": str(gap.get("prompt") or field_name)}
        if key in asked:
            unanswered.append(item)
            continue
        remaining.append(item)
    if remaining:
        return Decision(
            action="ask_once",
            reason="real_gap",
            gaps=tuple(remaining),
        )
    if unanswered:
        return Decision(
            action="stop",
            reason="real_gap",
            gaps=tuple(unanswered),
        )
    if authorized and data_available:
        return Decision(action="proceed", reason="authorized")
    if not authorized:
        return Decision(action="stop", reason="not_authorized", blocker="task is not authorized")
    return Decision(action="stop", reason="data_missing", blocker="required data is missing")


def reconcile_field(
    *,
    card: str,
    field: str,
    sources: Sequence[Mapping[str, Any]],
) -> FieldValue:
    """Precedence: human attributed to that card > registered > unambiguous > policy.

    Inference is never recorded as Alan's decision. A reply without per-card
    distribution stays a gap.
    """
    human = [item for item in sources if item.get("kind") == "human" and str(item.get("card") or "") == str(card)]
    if len(human) == 1 and str(human[0].get("value") or "").strip():
        return FieldValue(
            card=str(card),
            field=field,
            value=str(human[0]["value"]).strip(),
            origin=str(human[0].get("origin") or "human"),
            gap=False,
            attributed_to_alan=True,
        )
    if len(human) > 1:
        values = {str(item.get("value") or "").strip() for item in human}
        if len(values) > 1:
            return FieldValue(card=str(card), field=field, value=None, origin="conflict", gap=True)
    undistributed = [
        item
        for item in sources
        if item.get("kind") == "human" and not str(item.get("card") or "").strip()
    ]
    if undistributed:
        return FieldValue(
            card=str(card),
            field=field,
            value=None,
            origin="undistributed_human_reply",
            gap=True,
            attributed_to_alan=False,
        )
    registered = [item for item in sources if item.get("kind") == "registered" and str(item.get("card") or "") == str(card)]
    if len(registered) == 1 and str(registered[0].get("value") or "").strip():
        return FieldValue(
            card=str(card),
            field=field,
            value=str(registered[0]["value"]).strip(),
            origin=str(registered[0].get("origin") or "registered"),
            gap=False,
        )
    unambiguous = [item for item in sources if item.get("kind") == "unambiguous" and str(item.get("card") or "") == str(card)]
    if len(unambiguous) == 1 and str(unambiguous[0].get("value") or "").strip():
        return FieldValue(
            card=str(card),
            field=field,
            value=str(unambiguous[0]["value"]).strip(),
            origin=str(unambiguous[0].get("origin") or "unambiguous"),
            gap=False,
        )
    inference = [item for item in sources if item.get("kind") == "inference"]
    if inference:
        return FieldValue(
            card=str(card),
            field=field,
            value=None,
            origin="inference_not_alan",
            gap=True,
            attributed_to_alan=False,
        )
    policy = [item for item in sources if item.get("kind") == "policy"]
    if len(policy) == 1 and str(policy[0].get("value") or "").strip():
        return FieldValue(
            card=str(card),
            field=field,
            value=str(policy[0]["value"]).strip(),
            origin=str(policy[0].get("origin") or "policy"),
            gap=False,
        )
    return FieldValue(card=str(card), field=field, value=None, origin="missing", gap=True)


CURSOR_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["title", "questions"],
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string"},
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "prompt", "options"],
                "additionalProperties": False,
                "properties": {
                    "id": {"type": "string"},
                    "prompt": {"type": "string"},
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["id", "label"],
                            "additionalProperties": False,
                            "properties": {
                                "id": {"type": "string"},
                                "label": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
    },
}

CODEX_QUESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["question", "choices"],
    "additionalProperties": False,
    "properties": {
        "question": {"type": "string"},
        "choices": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}


def client_question_schema(client: str, installed: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if installed is not None:
        return dict(installed)
    if client == CLIENT_CODEX:
        return dict(CODEX_QUESTION_SCHEMA)
    return dict(CURSOR_QUESTION_SCHEMA)


def validate_question_payload(schema: Mapping[str, Any], payload: Mapping[str, Any]) -> tuple[bool, str]:
    allowed = set((schema.get("properties") or {}).keys())
    extra = [key for key in payload.keys() if key not in allowed]
    if extra:
        return False, f"incompatible field: {extra[0]}"
    keys = list(payload.keys())
    if len(keys) != len(set(keys)):
        return False, "duplicate field"
    required = list(schema.get("required") or [])
    for key in required:
        if key not in payload:
            return False, f"missing field: {key}"
    if schema.get("additionalProperties") is False:
        for key in payload:
            if key not in allowed:
                return False, f"incompatible field: {key}"
    questions = payload.get("questions")
    if isinstance(questions, list):
        ids = [str(item.get("id")) for item in questions if isinstance(item, dict)]
        if len(ids) != len(set(ids)):
            return False, "duplicate field"
        for item in questions:
            if not isinstance(item, dict):
                continue
            nested = ((schema.get("properties") or {}).get("questions") or {}).get("items") or {}
            nested_allowed = set((nested.get("properties") or {}).keys()) or {"id", "prompt", "options"}
            for key in item.keys():
                if key not in nested_allowed:
                    return False, f"incompatible field: {key}"
    return True, ""


def encode_question(
    client: str,
    items: Sequence[QuestionItem],
    *,
    tool_available: bool,
    schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    schema = client_question_schema(client, schema)
    if client == CLIENT_CODEX:
        prompt = "; ".join(f"#{item.card} {item.field}: {item.prompt}" for item in items)
        choices: list[str] = []
        for item in items:
            for option in item.options:
                label = f"#{item.card} {item.field}={option}"
                if label not in choices:
                    choices.append(label)
        payload: dict[str, Any] = {"question": prompt, "choices": choices}
    else:
        payload = {
            "title": "Lacunas do pacote",
            "questions": [
                {
                    "id": f"{item.card}-{item.field}",
                    "prompt": f"#{item.card} {item.prompt}",
                    "options": [{"id": option, "label": option} for option in item.options],
                }
                for item in items
            ],
        }
    ok, error = validate_question_payload(schema, payload)
    if not ok:
        return {
            "ok": False,
            "error": error,
            "sent": False,
            "text": question_as_text(items),
            "accepted_recommendation": False,
        }
    if not tool_available:
        return {
            "ok": True,
            "sent": False,
            "text": question_as_text(items),
            "accepted_recommendation": False,
            "payload": payload,
        }
    return {"ok": True, "sent": True, "payload": payload, "accepted_recommendation": False}


def question_as_text(items: Sequence[QuestionItem]) -> str:
    lines = ["Lacunas reais (uma consulta):"]
    for item in items:
        options = ", ".join(item.options)
        rec = f" (recomendado: {item.recommended})" if item.recommended else ""
        lines.append(f"- #{item.card} {item.field}: {item.prompt} [{options}]{rec}")
    lines.append("A recomendação não conta como aceite.")
    return "\n".join(lines)


def _looks_like_secret(key: str, value: Any) -> bool:
    lowered = key.lower()
    if any(needle in lowered for needle in SECRET_KEY_NEEDLES):
        return True
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=True)
    return any(token in text for token in FORBIDDEN_MANIFEST_VALUES)


def sanitize_manifest_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in payload.items():
        if _looks_like_secret(str(key), value):
            continue
        if isinstance(value, dict):
            nested = sanitize_manifest_payload(value)
            clean[str(key)] = nested
        elif isinstance(value, list):
            clean[str(key)] = [
                sanitize_manifest_payload(item) if isinstance(item, dict) else item
                for item in value
                if not (isinstance(item, str) and any(token in item for token in FORBIDDEN_MANIFEST_VALUES))
            ]
        else:
            clean[str(key)] = value
    return clean


def save_manifest(manifest: Manifest, env: Mapping[str, str] | None = None) -> Path:
    path = manifesto_path(manifest.package, env)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = sanitize_manifest_payload(manifest.as_dict())
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    return path


def load_manifest(package: str, env: Mapping[str, str] | None = None) -> Manifest | None:
    path = manifesto_path(package, env)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return Manifest(
        package=str(data.get("package") or package),
        decisions=dict(data.get("decisions") or {}),
        origins=dict(data.get("origins") or {}),
        evidence_refs=list(data.get("evidence_refs") or []),
        completed_steps=list(data.get("completed_steps") or []),
        context=dict(data.get("context") or {}),
        asked_gaps=list(data.get("asked_gaps") or []),
    )


CLOSEOUT_STEPS = (
    "comments",
    "fields",
    "documentation",
    "archive",
    "duplication",
    "integration",
    "context",
    "model",
    "deploy",
    "t16",
)


def first_incomplete_step(completed: Sequence[str]) -> str:
    done = set(completed)
    for step in CLOSEOUT_STEPS:
        if step not in done:
            return step
    return "done"


def resume_manifest(
    package: str,
    *,
    current_context: ContextIdentity,
    env: Mapping[str, str] | None = None,
) -> tuple[Manifest, str, str]:
    """Revalidate mutable context and continue at the first incomplete step."""
    existing = load_manifest(package, env)
    if existing is None:
        fresh = Manifest(
            package=package,
            decisions={},
            origins={},
            evidence_refs=[],
            completed_steps=[],
            context=current_context.as_dict(),
        )
        return fresh, first_incomplete_step([]), "new"
    stored = existing.context or {}
    stored_identity = ContextIdentity(
        package=str(stored.get("package") or existing.package),
        cwd=str(stored.get("cwd") or ""),
        head=str(stored.get("head") or ""),
        refs=tuple(stored.get("refs") or ()),
        branch=str(stored.get("branch") or ""),
    )
    note = "revalidated"
    completed = list(existing.completed_steps)
    if stored_identity.head and not same_context(stored_identity, current_context):
        note = describe_context_divergence(stored_identity, current_context)
        for step in ("archive", "integration", "context", "deploy", "t16"):
            if step in completed:
                completed.remove(step)
    updated = Manifest(
        package=existing.package,
        decisions=existing.decisions,
        origins=existing.origins,
        evidence_refs=existing.evidence_refs,
        completed_steps=completed,
        context=current_context.as_dict(),
        asked_gaps=existing.asked_gaps,
    )
    return updated, first_incomplete_step(completed), note


def format_operation_deny(
    *,
    operation: str,
    path: str,
    q: str | None,
    q_git: str | None,
    bound_card: str | None,
    rule: str,
    cause: str,
    corrective: str,
) -> str:
    return (
        f"deny operation={operation} path={path} q={q} q_git={q_git} "
        f"bound_card={bound_card} rule={rule} cause={cause} "
        f"corrective={corrective}"
    )


def diagnose_guard_decision(
    *,
    operation: str,
    path: str,
    decision: Mapping[str, Any],
    q: str | None,
    q_git: str | None,
    bound_card: str | None,
) -> dict[str, Any]:
    """Wrap a decide() result. Do not copy allow-lists or change decide()."""
    token = str(decision.get("decision") or decision.get("permission") or "")
    raw = str(decision.get("reason") or decision.get("agent_message") or "")
    allowed = token == "allow"
    if allowed:
        return {
            "allowed": True,
            "operation": operation,
            "message": f"allow operation={operation} path={path}",
            "generalizes": False,
        }
    rule = "fail_closed"
    match = re.search(r"reason=([A-Za-z0-9:_-]+)", raw)
    if match:
        rule = match.group(1)
    corrective = "repeat the same operation after fixing this context; do not treat this as a deny of another operation"
    if rule in {"unbound", "fail_closed"} and str(q_git or "").startswith("release-"):
        corrective = f"stop and point at {ISSUE_1022}; do not open a card worktree or cherry-pick"
    message = format_operation_deny(
        operation=operation,
        path=path,
        q=q,
        q_git=q_git,
        bound_card=bound_card,
        rule=rule,
        cause=raw or token,
        corrective=corrective,
    )
    return {
        "allowed": False,
        "operation": operation,
        "rule": rule,
        "message": message,
        "generalizes": False,
        "points_at_1022": ISSUE_1022 in corrective,
    }


def archive_write_plan(
    *,
    decide_result: Mapping[str, Any] | None,
    package_resolved: bool,
    card_resolved: bool,
    q_git: str | None,
    bound_card: str | None,
    conflict: str = "",
    discard: bool = False,
    human_exception: bool = False,
) -> ArchivePlan:
    """Reuse #1022 decide(); never a second allow-list; never worktree+cherry-pick."""
    if conflict or discard or human_exception:
        return ArchivePlan(
            proceed=False,
            ask=True,
            blocker=conflict or ("discard" if discard else "human exception required"),
            points_at_1022=False,
            use_generic_menu=False,
            worktree_cherry_pick=False,
        )
    if not package_resolved or not card_resolved:
        return ArchivePlan(
            proceed=False,
            ask=False,
            blocker=f"package or card is unresolved; archive deny points at {ISSUE_1022}",
            points_at_1022=True,
        )
    token = str((decide_result or {}).get("decision") or (decide_result or {}).get("permission") or "")
    raw = str((decide_result or {}).get("reason") or "")
    if token == "allow":
        return ArchivePlan(proceed=True, ask=False, blocker="", points_at_1022=False)
    unbound_release = str(q_git or "").startswith("release-") and str(bound_card or "") in {"", "⊥", None}
    fail_closed = "fail_closed" in raw or token in {"", "deny"}
    if unbound_release and fail_closed:
        return ArchivePlan(
            proceed=False,
            ask=False,
            blocker=(
                f"archive on unbound release-* denied with fail_closed; "
                f"block points at {ISSUE_1022}; do not worktree+cherry-pick"
            ),
            points_at_1022=True,
        )
    return ArchivePlan(
        proceed=False,
        ask=False,
        blocker=f"archive denied by decide(); points at {ISSUE_1022}",
        points_at_1022=True,
    )


def parse_post_blockers(output: str) -> list[str]:
    blockers: list[str] = []
    for line in (output or "").splitlines():
        text = line.strip()
        if text.startswith("BLOCKER:"):
            blockers.append(text[len("BLOCKER:") :].strip())
    return blockers


def format_t16_blockers(blockers: Sequence[str], *, cap: int = T16_BLOCKER_MESSAGE_CAP) -> str:
    joined = "; ".join(item for item in blockers if item)
    if len(joined) > cap:
        return joined[: cap - 1] + "…"
    return joined


def refuse_pass_from_other_context(
    recorded: ContextIdentity | None,
    current: ContextIdentity,
) -> str | None:
    if recorded is None:
        return None
    if same_context(recorded, current):
        return None
    return describe_context_divergence(recorded, current) + "; re-run post in the T16 context"


def is_placeholder_text(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    if text in GENERIC_PACKAGE_NAMES:
        return True
    return any(token in text for token in PRONTO_PLACEHOLDERS)


def pronto_evidence_args(
    *,
    package: str,
    branches: str,
    deploy: str,
    cards: str,
    commit: str,
) -> tuple[list[str], str]:
    if is_placeholder_text(package) or package.strip() in GENERIC_PACKAGE_NAMES:
        return [], "placeholder package"
    if is_placeholder_text(branches):
        return [], "placeholder branches"
    if is_placeholder_text(deploy):
        return [], "placeholder deploy"
    if not commit.strip():
        return [], "missing commit"
    args = [
        "--transition",
        "pronto",
        "--package",
        package.strip(),
        "--branches",
        branches.strip(),
        "--deploy",
        deploy.strip(),
        "--cards",
        cards.strip(),
        "--commit",
        commit.strip(),
    ]
    return args, ""


def pronto_body_is_complete(body: str) -> bool:
    if is_placeholder_text(body):
        return False
    return not any(token in body for token in PRONTO_PLACEHOLDERS)


def should_post_homologado(*, human_proven: bool, already_has_comment: bool) -> dict[str, Any]:
    if not human_proven:
        return {
            "post": False,
            "reason": "human homologation decision is not proven",
            "called_t7": False,
            "ask_alan_to_write": False,
        }
    if already_has_comment:
        return {
            "post": False,
            "reason": "canonical homologado comment already present",
            "called_t7": False,
            "ask_alan_to_write": False,
        }
    return {
        "post": True,
        "reason": "human decision proven; publish via helper",
        "called_t7": False,
        "ask_alan_to_write": False,
    }


def run_preflight(items: Sequence[PreflightItem]) -> dict[str, Any]:
    pending = [item for item in items if item.pending]
    announced = [item.kind for item in items if item.started and item.kind in {"deploy", "t16"}]
    report = {
        "pending": [
            {"kind": item.kind, "detail": item.detail, "started": False} for item in pending
        ],
        "announces_deploy": False,
        "announces_t16": False,
        "kinds": [item.kind for item in items],
    }
    if announced:
        report["pending"].append(
            {
                "kind": "contract",
                "detail": "preflight must not announce deploy or T16 as already started",
                "started": False,
            }
        )
    return report


def completed_homologado_change_blocks(
    *,
    card: str,
    status: str,
    progress: str,
    package_cards: Sequence[str],
) -> bool:
    if status != "Homologado":
        return False
    if progress != "complete":
        return False
    return str(card) in {str(item) for item in package_cards}


def card_outside_package_is_left_alone(card: str, package_cards: Sequence[str]) -> bool:
    return str(card) not in {str(item) for item in package_cards}


def simulate_merge_against_target(
    cwd: str | Path,
    *,
    head: str,
    target: str,
    runner: Any = subprocess.run,
) -> MergeSimulation:
    work = Path(cwd)
    try:
        proc = runner(
            ["git", "-C", str(work), "merge-tree", target, head],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return MergeSimulation(ok=False, conflict=False, detail=str(exc), open_pr=False)
    text = (proc.stdout or "") + (proc.stderr or "")
    conflict = proc.returncode != 0 or "CONFLICT" in text or "changed in both" in text
    if conflict:
        return MergeSimulation(
            ok=False,
            conflict=True,
            detail="merge conflict against target; do not open the PR",
            open_pr=False,
        )
    return MergeSimulation(ok=True, conflict=False, detail="merge-tree clean", open_pr=True)


def documental_checks_proposal(paths: Sequence[str]) -> dict[str, Any]:
    only_docs = all(
        any(path == item or path.startswith(item) for item in DOCUMENTAL_ALLOWLIST)
        or path in DOCUMENTAL_ALLOWLIST
        for path in paths
    )
    return {
        "documental": only_docs,
        "qa_gate": "required",
        "allowlist": list(DOCUMENTAL_ALLOWLIST),
        "disable_qa_gate": False,
        "coverage": "OpenSpec validate of the change plus harness pytest for touched closeout paths",
        "regression": "release-guard post/audit needles and process-fsm closeout tests remain required",
    }


def gh_supports_flag(
    binary: str,
    command: Sequence[str],
    flag: str,
    *,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    args = [binary, *command, "--help"]
    try:
        proc = runner(args, capture_output=True, text=True, check=False, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as exc:
        text = str(exc)
        return {
            "supported": False,
            "error_class": "binary_error",
            "detail": text,
            "generalizes": False,
        }
    combined = (proc.stdout or "") + (proc.stderr or "")
    if "Permission denied" in combined:
        return {
            "supported": False,
            "error_class": "permission_denied",
            "detail": combined.strip(),
            "generalizes": False,
        }
    if "GraphQL" in combined and proc.returncode != 0:
        return {
            "supported": False,
            "error_class": "graphql",
            "detail": combined.strip(),
            "generalizes": False,
        }
    supported = flag in combined
    return {
        "supported": supported,
        "error_class": "" if proc.returncode == 0 else "help_failed",
        "detail": "",
        "generalizes": False,
    }


def classify_tool_error(message: str) -> dict[str, Any]:
    text = message or ""
    if "Permission denied" in text:
        klass = "permission_denied"
    elif "GraphQL" in text:
        klass = "graphql"
    else:
        klass = "other"
    return {"class": klass, "generalizes": False, "operation": "this_call_only"}



def _git_one(runner: Any, cwd: Path, args: Sequence[str]) -> str:
    try:
        proc = runner(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return (proc.stdout or "").strip()


def decision_table_for_client(client: str) -> dict[str, str]:
    """Same table; only encoding and map key differ per client."""
    key = "execucao.codex" if client == CLIENT_CODEX else "execucao"
    encoding = "codex.choices" if client == CLIENT_CODEX else "cursor.questions"
    return {"table": "release_closeout.evaluate_decision", "map_key": key, "encoding": encoding}
