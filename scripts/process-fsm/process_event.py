"""SMAG process_event: validate δ then move Project 1 Status. No GitHub in unit tests."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Protocol

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from design_clone_gate import clone_gate_ok, design_token_gap  # noqa: E402
from overlay import (  # noqa: E402
    board_owner_number,
    board_project_id,
    load_overlay,
    repo_owner_name,
    status_field_id,
    status_options,
)
from fsm import (  # noqa: E402
    CARD_GIT_RE,
    EvalContext,
    enabled_events,
    evaluate,
    load_fsm,
)
from graphql_quota import (  # noqa: E402
    GraphQLQuotaError,
    enforce_graphql_quota,
    parse_include_output,
    raise_if_cached_exhausted,
    write_cache,
)
from guard import github_status_provider  # noqa: E402
from resolve import UNBOUND, resolve  # noqa: E402
from t14 import (  # noqa: E402
    LiveT14Runner,
    T14Error,
    T14Runner,
    _pr_list_json,
    classify_qa_gate,
    measure_checks_green,
    run_t14,
    t14_closeout_done,
)
from t16 import (  # noqa: E402
    LiveT16Closer,
    LoteMeasurement,
    T16Closer,
    T16Error,
    classify_package,
    FECHAR_RELEASE_WRONG_GIT_MESSAGE,
    lote_git,
    wrong_fechar_release_git,
    measure_m_lote,
    parse_package_cards,
)
from release_closeout import (  # noqa: E402
    ContextIdentity,
    capture_context,
    format_t16_blockers,
    refuse_pass_from_other_context,
)

REPO_ROOT = ROOT.parents[1]
AMBIENTES = "covenant-flow-environments"
RELEASE_GUARD = "release-guard"
HUMAN_EVENTS = frozenset(
    {"priorizar", "aprovar_design", "homologar", "nao_homologar", "devolver_design", "cancelar"}
)
I4_EVENTS = frozenset({"iniciar_apply", "pedir_review"})
CHANGE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EVENT_GUARDS = {
    "achar_bloqueante": {"open_p0_p1": True, "reviewers_ok": False},
    "aceitar_sha": {"reviewers_ok": True, "open_p0_p1": False},
    "rerun_infra": {"flaky_infra": True, "source_failure": False, "checks_green": False},
    "falha_codigo": {"source_failure": True, "flaky_infra": False, "checks_green": False},
}


class BoardMover(Protocol):
    """One Status move, described as the FSM edge it is: the executor checks event, source column and actor (D9)."""

    via_executor: bool

    def move(self, issue_number: int, evento: str, de: str | None, para: str, ator: str, extras: dict[str, Any] | None = None) -> None: ...


class MoveRefused(RuntimeError):
    """The executor answered and did not move: `code` becomes `reason=executor:<code>`, Status unchanged."""

    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


class FakeMover:
    via_executor = False

    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []
        self.requests: list[dict[str, Any]] = []

    def move(self, issue_number: int, evento: str, de: str | None, para: str, ator: str, extras: dict[str, Any] | None = None) -> None:
        self.requests.append({"issue": issue_number, "evento": evento, "de": de, "para": para, "ator": ator, "extras": dict(extras or {})})
        self.calls.append((issue_number, para))


class ExecutorMover:
    """Moves only by asking the board executor (`portao_client.pedir`); never `gh project item-edit` (D9).

    `pedir` is injectable: unit tests pass a fake executor and never reach GitHub.
    """

    via_executor = True

    def __init__(self, config: Any, *, pedir: Callable[..., dict[str, Any]] | None = None, origem: dict[str, Any] | None = None) -> None:
        self.config = config
        self._pedir = pedir
        self.origem: dict[str, Any] = dict(origem or {})

    def set_client(self, client: str | None) -> None:
        if client and not self.origem.get("cliente"):
            self.origem["cliente"] = client

    def move(self, issue_number: int, evento: str, de: str | None, para: str, ator: str, extras: dict[str, Any] | None = None) -> None:
        if self._pedir is None:
            import portao_client

            self._pedir = portao_client.pedir
        resposta = self._pedir(evento, issue_number, de=de, ator=ator, config=self.config, origem=self.origem, extras=extras or {})
        resultado = str(resposta.get("resultado") or "indisponivel")
        if resultado == "movido":
            return
        code = str(resposta.get("codigo") or resultado)
        raise MoveRefused(code, str(resposta.get("mensagem") or code))


def default_mover(root: Path | None = None) -> "BoardMover":
    """`board.executor` in the overlay selects the executor; without the key, the previous `item-edit` mover (D9)."""

    import portao_client

    try:
        overlay = load_overlay(root or REPO_ROOT)
    except Exception:
        return GhBoardMover()
    config = portao_client.config_do_overlay(overlay)
    return GhBoardMover() if config is None else ExecutorMover(config, origem=_session_origin())


def _session_origin() -> dict[str, Any]:
    return {
        "superficie": os.environ.get("CLAUDE_CODE_ENTRYPOINT") or None,
        "sessao": os.environ.get("CLAUDE_CODE_SESSION_ID") or os.environ.get("CODEX_THREAD_ID") or None,
    }


class GhBoardMover:
    """Live Project Status edit from overlay board ids. Tests MUST inject FakeMover instead."""

    via_executor = False

    def move(self, issue_number: int, evento: str, de: str | None, para: str, ator: str, extras: dict[str, Any] | None = None) -> None:
        del evento, de, ator, extras
        self.set_status(issue_number, para)

    def set_status(self, issue_number: int, to: str) -> None:
        import subprocess

        raise_if_cached_exhausted()
        overlay = load_overlay(REPO_ROOT)
        option = status_options(overlay).get(to)
        field = status_field_id(overlay)
        project_id = board_project_id(overlay)
        if option is None or not field or not project_id:
            raise ValueError(f"unknown Status {to!r} or overlay board ids missing")
        item_id = _item_id_for_issue(issue_number)
        env = os.environ.copy()
        env["GH_DEBUG"] = "api"
        try:
            proc = subprocess.run(
                [
                    "gh",
                    "project",
                    "item-edit",
                    "--id",
                    item_id,
                    "--project-id",
                    project_id,
                    "--field-id",
                    field,
                    "--single-select-option-id",
                    option,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
                env=env,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(str(exc)) from exc
        captured = f"{proc.stdout or ''}\n{proc.stderr or ''}"
        quota = parse_include_output(captured)
        write_cache(quota)
        enforce_graphql_quota(quota)
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "item-edit failed").strip())


def _item_id_for_issue(issue_number: int) -> str:
    import subprocess

    raise_if_cached_exhausted()
    overlay = load_overlay(REPO_ROOT)
    owner, repo_name = repo_owner_name(overlay)
    board_owner, board_number = board_owner_number(overlay)
    if not owner or not repo_name or not board_owner or board_number is None:
        raise RuntimeError("overlay board/repo missing")
    query = (
        f"query($n:Int!){{repository(owner:\"{owner}\",name:\"{repo_name}\")"
        "{issue(number:$n){projectItems(first:20){nodes{id project{number owner{...on User{login}}}}}}}}"
    )
    try:
        proc = subprocess.run(
            [
                "gh",
                "api",
                "graphql",
                "--include",
                "-f",
                f"query={query}",
                "-F",
                f"n={issue_number}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(str(exc)) from exc
    captured = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    quota = parse_include_output(captured)
    write_cache(quota)
    enforce_graphql_quota(quota)
    data = quota.body or {}
    nodes = (
        (((data.get("data") or {}).get("repository") or {}).get("issue") or {}).get("projectItems") or {}
    ).get("nodes") or []
    for node in nodes:
        project = (node or {}).get("project") or {}
        login = (project.get("owner") or {}).get("login")
        if project.get("number") == board_number and login in (None, board_owner):
            item_id = node.get("id")
            if isinstance(item_id, str) and item_id:
                return item_id
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "graphql failed").strip())
    raise RuntimeError(f"issue {issue_number} not on Project {board_number}")


def _unbound(bound: Any) -> bool:
    return bound in (None, "", UNBOUND)


def _quota_reject(exc: GraphQLQuotaError, state: str | None = None) -> dict[str, Any]:
    return _payload(
        result="reject",
        state=state,
        to=None,
        reason="graphql_quota",
        message=str(exc),
    )


def _safe_move(
    mover: BoardMover,
    issue_number: int,
    to: str,
    *,
    evento: str,
    de: str | None,
    ator: str = "Agent",
    extras: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    try:
        mover.move(issue_number, evento, de, to, ator, extras)
    except MoveRefused as exc:
        return _payload(result="reject", state=de, to=None, reason=f"executor:{exc.code}", message=exc.message)
    except GraphQLQuotaError as exc:
        return _quota_reject(exc)
    except (RuntimeError, ValueError, OSError) as exc:
        return _payload(result="reject", state=None, to=None, reason="move_failed", message=str(exc))
    return None


def files_g_design(
    change_dir: Path,
    prototype_dir: Path | None = None,
    repo: Path | None = None,
) -> bool:
    needed = [change_dir / "proposal.md", change_dir / "design.md", change_dir / "tasks.md"]
    if not all(path.is_file() for path in needed):
        return False
    specs = change_dir / "specs"
    if not (specs.is_dir() and any(specs.rglob("*.md"))):
        return False
    return clone_gate_ok(change_dir, prototype_dir, repo or REPO_ROOT)


def compute_digest(change_dir: Path, prototype_dir: Path | None) -> str:
    digest = hashlib.sha256()
    design = change_dir / "design.md"
    if design.is_file():
        digest.update(design.read_bytes())
    if prototype_dir is not None and prototype_dir.is_dir():
        for path in sorted(p for p in prototype_dir.rglob("*") if p.is_file()):
            digest.update(path.relative_to(prototype_dir).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def sidecar_path(change_dir: Path) -> Path:
    return change_dir / ".design-digest"


def measure_digest_changed(change_dir: Path | None, prototype_dir: Path | None, state: str | None) -> bool:
    if change_dir is None:
        return state in {"Pronto para Dev", "Em desenvolvimento"}
    sidecar = sidecar_path(change_dir)
    if not sidecar.is_file():
        return True
    current = compute_digest(change_dir, prototype_dir)
    stored = sidecar.read_text(encoding="utf-8").strip()
    return current != stored


def write_sidecar(change_dir: Path, prototype_dir: Path | None) -> None:
    sidecar_path(change_dir).write_text(
        compute_digest(change_dir, prototype_dir) + "\n",
        encoding="utf-8",
    )


PREFLIGHT_EVENTS = frozenset({"iniciar_design", "recriticar", "submeter_design", "iniciar_apply", "pedir_review", "aceitar_sha", "integrar_develop"})
AGENT_CLIENT_NAMES = {"codex": "codex", "claude": "claude"}

HOST_CLIENT_NAMES = {**AGENT_CLIENT_NAMES, "opencode": "opencode", "cursor-agent": "cursor"}
HOST_ENVIRONMENT = {
    "cursor": ("CURSOR_AGENT", "CURSOR_VERSION", "CURSOR_PROJECT_DIR"),
    "opencode": ("OPENCODE",),
}


def nearest_agent_client(pid: int | None = None, proc_root: Path = Path("/proc"), names: dict[str, str] | None = None) -> str | None:
    """Innermost Codex/Claude Code ancestor of this process, from the process tree."""

    client_names = AGENT_CLIENT_NAMES if names is None else names
    current = os.getpid() if pid is None else pid
    for _ in range(64):
        try:
            argv = [a for a in (proc_root / str(current) / "cmdline").read_bytes().decode("utf-8", "replace").split("\0") if a]
            stat = (proc_root / str(current) / "stat").read_text()
        except OSError:
            return None
        found = {Path(argument).name for argument in argv[:2]}
        for name, client_name in client_names.items():
            if name in found:
                return client_name
        try:
            current = int(stat.rsplit(")", 1)[1].split()[1])
        except (IndexError, ValueError):
            return None
        if current <= 1:
            return None
    return None


def native_client() -> str | None:
    """Native identity: `codex`, `claude`, None, or `ambiguous` when both signals
    are set and the process tree cannot say which one is innermost (a Codex run
    inside Claude Code's Bash inherits CLAUDECODE=1 and still counts as Codex)."""

    codex = bool(os.environ.get("CODEX_THREAD_ID"))
    claude = os.environ.get("CLAUDECODE") == "1"
    if codex and claude:
        return nearest_agent_client() or "ambiguous"
    return "codex" if codex else ("claude" if claude else None)


def host_client() -> str | None:
    """Recover Cursor/OpenCode identity when no explicit client is supplied."""
    present = {client for client, names in HOST_ENVIRONMENT.items() if any(os.environ.get(n) for n in names)}
    if len(present) == 1:
        return next(iter(present))
    if len(present) > 1:
        innermost = nearest_agent_client(names=HOST_CLIENT_NAMES)
        return innermost if innermost in present else None
    return None


def claude_closeout_parent_refusal(root: Path, capture: dict[str, Any] | None = None, checker: Callable[..., Any] | None = None) -> str | None:
    """Preserve T16's observed-parent check against captured claude/execucao."""
    from claude_evidence import EvidenceError, observe_parent
    from model_selection import SelectionError, resolve as resolve_selection
    from release_model_selection import check_claude_parent, load_execucao_pair

    try:
        capture = capture if capture is not None else resolve_selection("claude", "execucao", role="fecho-lote")
        captured = load_execucao_pair(root, "claude", capture)
    except SelectionError as exc:
        return f"claude/execucao capture unavailable ({exc}); T16 refused, Status unchanged"
    result = (checker or check_claude_parent)(root=root, capture=capture)
    if result.ok:
        return None
    try:
        seen = observe_parent()
        observed = f"{seen['model']}/{seen['effort']}"
    except (EvidenceError, OSError, ValueError):
        observed = "unavailable"
    return f"{result.message}; observed parent {observed} vs captured claude/execucao {captured['slug']}/{captured['effort']}; T16 refused, Status unchanged"


def _payload(
    *,
    result: str,
    state: str | None,
    to: str | None,
    reason: str | None,
    enabled: list[str] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"result": result, "state": state, "to": to, "reason": reason}
    if enabled is not None:
        out["enabled_events"] = enabled
    if message:
        out["message"] = message
    return out


def _fechar_message(
    base: str | None,
    *,
    blockers: list[str] | tuple[str, ...] | None = None,
    fail_class: str | None = None,
    extra: str | None = None,
) -> str:
    text = base or "reject"
    if fail_class:
        text = f"{text}; fail_class={fail_class}"
    blocker_text = format_t16_blockers(blockers or ())
    if blocker_text:
        text = f"{text}; blockers: {blocker_text}"
    if extra:
        text = f"{text}; {extra}"
    if AMBIENTES not in text:
        text = f"{text}; see {AMBIENTES} and {RELEASE_GUARD}"
    elif RELEASE_GUARD not in text:
        text = f"{text}; {RELEASE_GUARD}"
    return text


def _codex_stage_refusal(workdir: Path, event: str, state: str | None) -> dict[str, Any] | None:
    from codex_evidence import EvidenceError, preflight

    # T5 submits existing artifacts; it does not start a native stage child.
    # Keep runtime/qualification/binding checks without requiring spawn capacity.
    stage = None if event == "submeter_design" else event
    try:
        preflight(root=workdir, stage=stage)
    except (EvidenceError, OSError, ValueError) as exc:
        return _payload(result="reject", state=state, to=None, reason=f"codex_evidence:{getattr(exc, 'code', 'invalid_input')}", message=str(exc))
    return None


def process_event(
    event: str,
    *,
    cwd: Path | None = None,
    card: str | int | None = None,
    change: str | None = None,
    dry_run: bool = False,
    mover: BoardMover | None = None,
    status: str | None = None,
    q_git: str | None = None,
    bound_card: str | None = None,
    digest_changed: bool | None = None,
    g_design: bool | None = None,
    m_lote: bool | None = None,
    m_lote_measurer: Callable[..., Any] | None = None,
    lote_pass_context: ContextIdentity | None = None,
    checks_green: bool | None = None,
    checks_green_measurer: Callable[..., bool] | None = None,
    checks_green_classifier: Callable[..., dict[str, Any]] | None = None,
    pr_lister: Callable[..., list] | None = None,
    t14_runner: T14Runner | None = None,
    t16_closer: T16Closer | None = None,
    status_provider: Callable[[str | None], str | None] | None = None,
    package_cards: list[int] | None = None,
    fsm: dict[str, Any] | None = None,
    resolve_fn: Callable[..., dict[str, str | None]] = resolve,
    change_dir: Path | None = None,
    prototype_dir: Path | None = None,
    client: str | None = None,
    parent_capture: dict[str, Any] | None = None,
    parent_checker: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    if event == "criar_card":
        if mover is None or not getattr(mover, "via_executor", False):
            return _payload(
                result="reject",
                state=status,
                to=None,
                reason="not_implemented",
                message="criar_card needs board.executor in the overlay; create the issue/card first.",
            )
        try:
            new_card = int(str(card).lstrip("#"))
        except (TypeError, ValueError):
            return _payload(result="reject", state=None, to=None, reason="unbound", message="criar_card needs --card N (the issue already exists)")
        if dry_run:
            return _payload(result="transition", state=None, to="Em Refinamento", reason="T0")
        failed = _safe_move(mover, new_card, "Em Refinamento", evento="criar_card", de=None)
        if failed is not None:
            return failed
        return _payload(result="transition", state=None, to="Em Refinamento", reason="T0")
    table = fsm if fsm is not None else load_fsm()
    workdir = Path(cwd) if cwd is not None else Path.cwd()
    if card is not None:
        card = str(card).lstrip("#")
    if change is not None and CHANGE_SLUG_RE.match(str(change)) is None:
        return _payload(result="reject", state=status, to=None, reason="invalid_change")
    resolved = resolve_fn(workdir, workdir, issue_id=card, status=status)
    q = status if status is not None else resolved.get("q")
    git = q_git if q_git is not None else resolved.get("q_git")
    bound = bound_card if bound_card is not None else resolved.get("bound_card")
    # Codex and Claude Code add availability checks, never a new transition or
    # permission. Other adapters retain their existing path. Conflicting
    # explicit/native identity is refused rather than silently selecting a client.
    native = native_client()
    if native == "ambiguous":
        return _payload(result="reject", state=q, to=None, reason="claude_evidence:ambiguous_client")
    active_client = client or os.environ.get("COVENANT_CLIENT") or native or host_client()
    if native and active_client != native:
        return _payload(result="reject", state=q, to=None, reason=f"{native}_evidence:ambiguous_client")
    if mover is not None and hasattr(mover, "set_client"):
        mover.set_client(active_client)
    if active_client in ("cursor", "opencode", "codex") and event in PREFLIGHT_EVENTS:
        # Account registration (pin with an adapter manifest): the hooks of these clients run from the
        # operator account through the shim. Without the shim, its heartbeat, the client's entry or its
        # review the transition is refused. Older pins and every other client are not checked here.
        import account_registration
        try:
            account_registration.require_active(active_client, workdir)
        except account_registration.RegistrationRefusal as exc:
            prefix = "codex_evidence" if active_client == "codex" else f"{active_client}_registration"
            return _payload(result="reject", state=q, to=None, reason=f"{prefix}:{exc.code}", message=f"{active_client}: {exc}")
    # I4 events must first let the existing engine invalidate stale approval.
    # That route starts no stage child; identity and hook trust still gate it.
    if active_client == "codex" and event in PREFLIGHT_EVENTS and event not in I4_EVENTS:
        refusal = _codex_stage_refusal(workdir, event, q)
        if refusal is not None:
            return refusal
    if active_client == "claude" and event in PREFLIGHT_EVENTS:
        from claude_evidence import EvidenceError, preflight as claude_preflight
        try:
            claude_preflight(root=workdir)
        except (EvidenceError, OSError, ValueError) as exc:
            return _payload(result="reject", state=q, to=None, reason=f"claude_evidence:{getattr(exc, 'code', 'invalid_input')}", message=str(exc))
    if active_client == "claude" and event == "fechar_release":
        refusal = claude_closeout_parent_refusal(workdir, parent_capture, parent_checker)
        if refusal:
            return _payload(result="reject", state=q, to=None, reason="claude_evidence:parent_model", message=_fechar_message(refusal))
    if event in HUMAN_EVENTS:
        return _payload(result="reject", state=q, to=None, reason="actor")
    provider = status_provider if status_provider is not None else github_status_provider
    if q is None:
        try:
            q = provider(None if _unbound(bound) else str(bound))
        except GraphQLQuotaError as exc:
            return _quota_reject(exc)
    match = CARD_GIT_RE.match(str(git or ""))
    parsed_package: list[int] | None
    if package_cards is not None:
        parsed_package = list(package_cards)
    else:
        env_raw = os.environ.get("RELEASE_CARDS")
        parsed_package = parse_package_cards(env_raw, card)
        # None = invalid tokens (I9). [] = empty env; only then fall back to bound_card.
        if parsed_package is not None and len(parsed_package) == 0 and not _unbound(bound):
            if not (env_raw or "").strip():
                parsed_package = parse_package_cards(None, bound)
    if event != "fechar_release":
        if card is not None and match is not None and str(card) != match.group(1):
            return _payload(result="reject", state=q, to=None, reason="card_mismatch")
        if change is not None and match is not None and str(change) != str(git):
            return _payload(result="reject", state=q, to=None, reason="change_mismatch")
        if _unbound(bound):
            return _payload(result="reject", state=q, to=None, reason="unbound")
    else:
        if wrong_fechar_release_git(git):
            return _payload(
                result="reject",
                state=q,
                to=None,
                reason="guard:lote_git",
                message=_fechar_message(FECHAR_RELEASE_WRONG_GIT_MESSAGE),
            )
        if _unbound(bound) and not lote_git(git):
            return _payload(result="reject", state=q, to=None, reason="unbound")
        if parsed_package is None or len(parsed_package) == 0:
            return _payload(result="reject", state=q, to=None, reason="I9")

    issue_number: int | None = None
    try:
        issue_number = int(str(bound if bound not in (None, UNBOUND) else card))
    except (TypeError, ValueError):
        issue_number = None

    inferred_change = change
    if inferred_change is None and match is not None:
        inferred_change = str(git)
    resolved_change_dir = change_dir
    if resolved_change_dir is None and inferred_change:
        candidate = REPO_ROOT / "openspec" / "changes" / inferred_change
        if candidate.is_dir():
            resolved_change_dir = candidate
    resolved_proto = prototype_dir
    if resolved_proto is None and inferred_change:
        proto = REPO_ROOT / "frontend" / "public" / "prototypes" / inferred_change
        resolved_proto = proto if proto.is_dir() else None

    if event == "submeter_design" and g_design is None and resolved_change_dir is not None:
        design_file = resolved_change_dir / "design.md"
        gap = design_token_gap(design_file.read_text(encoding="utf-8")) if design_file.is_file() else None
        if gap:
            return _payload(result="reject", state=q, to=None, reason="guard:design_tokens",
                message=f"T5 refused: design.md has no parseable `{gap}` line (needs `UI impact`, `live_route` and `surface`); fix it and submit again")
    if g_design is None:
        g_design = (
            files_g_design(resolved_change_dir, resolved_proto)
            if resolved_change_dir
            else False
        )
    if digest_changed is None:
        digest_changed = measure_digest_changed(resolved_change_dir, resolved_proto, q)
    lote_report: LoteMeasurement | None = None
    canonical_package = ",".join(str(n) for n in (parsed_package or []))
    current_lote_context = capture_context(
        workdir,
        package=canonical_package,
    )
    if event == "fechar_release" and m_lote is None:
        if m_lote_measurer is None:
            m_lote = False
            lote_report = LoteMeasurement(ok=False, fail_class="measure_absent")
        else:
            try:
                measured = m_lote_measurer(cwd=workdir, package=canonical_package)
            except (OSError, RuntimeError, TypeError, ValueError):
                m_lote = False
                lote_report = LoteMeasurement(ok=False, fail_class="measure_failed")
            else:
                lote_report = measured if isinstance(measured, LoteMeasurement) else None
                m_lote = bool(measured)
                recorded = lote_report.context if lote_report is not None else None
                mismatch = refuse_pass_from_other_context(recorded, current_lote_context)
                if mismatch:
                    m_lote = False
                    lote_report = LoteMeasurement(
                        ok=False,
                        blockers=lote_report.blockers if lote_report else (),
                        output=lote_report.output if lote_report else "",
                        fail_class="context_divergence",
                        context=recorded,
                    )
    elif m_lote is None:
        m_lote = False
    if event == "fechar_release" and m_lote:
        mismatch = refuse_pass_from_other_context(lote_pass_context, current_lote_context)
        if mismatch:
            m_lote = False
            lote_report = LoteMeasurement(
                ok=False,
                blockers=(),
                output=mismatch,
                fail_class="context_divergence",
                context=lote_pass_context,
            )
    classified_reason: str | None = None
    if event == "aceitar_sha":
        rows: list = []
        if pr_lister is not None:
            try:
                rows = list(pr_lister(git) or [])
            except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
                rows = []
        if not rows:
            return _payload(result="reject", state=q, to=None, reason="no_pr")
    # D9: T14 repeated after the closeout (squash, sync, restart, done comment) with Status still QA
    # only asks for the move; it neither re-measures the merged PR nor redoes the squash.
    t14_closed = bool(
        event == "integrar_develop"
        and not dry_run
        and t14_runner is not None
        and t14_closeout_done(t14_runner, q_git=str(git), bound_card=str(bound))
    )
    if t14_closed and checks_green is None:
        checks_green = True
    if event == "integrar_develop" and checks_green is None:
        if checks_green_classifier is not None:
            try:
                classified = checks_green_classifier(bound, git)
            except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError):
                classified = {"ok": False, "reason": "qa-gate failed"}
            if isinstance(classified, dict):
                checks_green = bool(classified.get("ok"))
                token = classified.get("reason")
                classified_reason = str(token) if token else None
            else:
                checks_green = False
                classified_reason = "qa-gate failed"
        elif checks_green_measurer is None:
            checks_green = False
        else:
            try:
                checks_green = bool(checks_green_measurer(bound, git))
            except (OSError, RuntimeError, TypeError, ValueError):
                checks_green = False

    homologado_ids: list[int] = []
    if event == "fechar_release" and m_lote:
        provider = status_provider if status_provider is not None else github_status_provider
        try:
            homologado_ids, _pronto_ids = classify_package(parsed_package or [], provider)
        except GraphQLQuotaError as exc:
            return _quota_reject(exc, state=q)
        except T16Error:
            return _payload(result="reject", state=q, to=None, reason="I9")

    eval_state = "Homologado" if event == "fechar_release" else q
    exclusive = EVENT_GUARDS.get(event, {})
    ctx_kwargs: dict[str, Any] = {
        "state": eval_state,
        "event": event,
        "actor": "Agent",
        "q_git": git,
        "bound_card": bound if not _unbound(bound) else None,
        "g_design": g_design,
        "digest_changed": digest_changed,
        "m_lote": m_lote,
        "checks_green": checks_green,
        "open_p0_p1": exclusive.get("open_p0_p1"),
        "reviewers_ok": exclusive.get("reviewers_ok"),
        "flaky_infra": exclusive.get("flaky_infra"),
        "source_failure": exclusive.get("source_failure"),
    }
    ctx_kwargs.update(exclusive)

    result = evaluate(table, EvalContext(**ctx_kwargs))
    if event in I4_EVENTS and result.reason == "I4":
        if match is None:
            return _payload(result="reject", state=q, to=None, reason="guard:q_git_card")
        if str(bound) != match.group(1):
            return _payload(result="reject", state=q, to=None, reason="card_mismatch")
        compiled = evaluate(
            table,
            EvalContext(
                state=q,
                event="invalidar_aprovacao",
                actor="Guard",
                q_git=git,
                bound_card=bound if not _unbound(bound) else None,
                digest_changed=True,
            ),
        )
        if compiled.result == "transition":
            if not dry_run and mover is not None and issue_number is not None:
                failed = _safe_move(mover, issue_number, compiled.to or "Design", evento="invalidar_aprovacao", de=q, ator="Guard")
                if failed is not None:
                    failed["state"] = q
                    return failed
            return _payload(
                result="transition",
                state=q,
                to=compiled.to,
                reason="I4",
            )
        return _payload(result="reject", state=q, to=None, reason=compiled.reason)

    # Unchanged approval retains the capability refusal for the requested stage.
    # No stage is started by the approval-invalidating route above.
    if active_client == "codex" and event in I4_EVENTS:
        refusal = _codex_stage_refusal(workdir, event, q)
        if refusal is not None:
            return refusal

    enabled = enabled_events(table, eval_state if event == "fechar_release" else q)
    message = None
    if event == "fechar_release":
        extra_ctx = None
        if lote_report is not None and lote_report.fail_class == "context_divergence":
            extra_ctx = lote_report.output or "context divergence; re-run post in the T16 context"
        message = _fechar_message(
            result.reason,
            blockers=lote_report.blockers if lote_report is not None else (),
            fail_class=lote_report.fail_class if lote_report is not None else None,
            extra=extra_ctx,
        )
    if result.result != "transition":
        extra = enabled if event in {"request_implement", "pular_coluna", "Agent.aprovar_design"} or result.reason in {
            "illegal_event",
            "no_edge",
        } else None
        if event == "request_implement":
            extra = enabled
        reason = result.reason
        if event == "integrar_develop" and reason == "guard:checks_green" and classified_reason:
            reason = classified_reason
        return _payload(
            result="reject",
            state=q,
            to=None,
            reason=reason,
            enabled=extra,
            message=message,
        )
    if event == "integrar_develop":
        if dry_run:
            return _payload(result="transition", state=q, to=result.to, reason=result.reason, message=message)
        if t14_runner is None:
            return _payload(result="reject", state=q, to=None, reason="I8")
        try:
            if not t14_closed:
                run_t14(t14_runner, q_git=str(git), bound_card=str(bound))
        except T14Error as exc:
            text = str(exc)
            if "sync: dirty" in text:
                return _payload(result="reject", state=q, to=None, reason="sync: dirty", message=text)
            if "squash: no PR" in text:
                return _payload(result="reject", state=q, to=None, reason="no_pr", message=text)
            return _payload(result="reject", state=q, to=None, reason="I8", message=text)
        if mover is None or issue_number is None:
            return _payload(result="transition", state=q, to=result.to, reason=result.reason, message=message)
        failed = _safe_move(mover, issue_number, result.to or "", evento=event, de=q)
        if failed is not None:
            failed["state"] = q
            return failed
        return _payload(result="transition", state=q, to=result.to, reason=result.reason, message=message)
    if event == "fechar_release":
        if dry_run:
            return _payload(result="transition", state=q or "Homologado", to=result.to, reason=result.reason)
        if homologado_ids:
            if t16_closer is None:
                return _payload(result="reject", state=q, to=None, reason="I9")
            try:
                for number in homologado_ids:
                    t16_closer.comment_pronto(card=str(number), package=parsed_package or homologado_ids)
                    if mover is None:
                        return _payload(result="reject", state=q, to=None, reason="I9")
                    failed = _safe_move(mover, number, result.to or "Pronto", evento=event, de="Homologado",
                                        extras={"pacote": ",".join(str(n) for n in (parsed_package or homologado_ids))})
                    if failed is not None:
                        failed["state"] = q
                        failed["reason"] = "I9"
                        return failed
            except (T16Error, OSError) as exc:
                del exc
                return _payload(result="reject", state=q, to=None, reason="I9")
        return _payload(
            result="transition",
            state=q or "Homologado",
            to=result.to,
            reason=result.reason,
        )
    if dry_run or mover is None or issue_number is None:
        return _payload(result="transition", state=q, to=result.to, reason=result.reason, message=message)
    extras: dict[str, Any] = {}
    if event == "submeter_design" and resolved_change_dir is not None:
        # T5 carries the design digest: the executor keeps it and compares it on `/aprovar-design` (D7).
        extras["digest"] = compute_digest(resolved_change_dir, resolved_proto)
    failed = _safe_move(mover, issue_number, result.to or "", evento=event, de=q, extras=extras)
    if failed is not None:
        failed["state"] = q
        return failed
    if event == "submeter_design" and resolved_change_dir is not None:
        write_sidecar(resolved_change_dir, resolved_proto)
    return _payload(result="transition", state=q, to=result.to, reason=result.reason, message=message)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="process_event")
    parser.add_argument("event")
    parser.add_argument("--card")
    parser.add_argument("--change")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--client", choices=("cursor", "codex", "grok", "opencode", "dsh", "claude"))
    parser.add_argument("--capture", type=Path, help="fechar_release in Claude Code: immutable birth capture of the claude/execucao pair (default: the local selection)")
    args = parser.parse_args(argv)
    parent_capture = None
    if args.capture is not None:
        from model_selection import SelectionError, load_capture
        try:
            parent_capture = load_capture(args.capture)
        except (OSError, ValueError, SelectionError) as exc:
            json.dump(_payload(result="reject", state=None, to=None, reason="claude_evidence:parent_model", message=f"capture unreadable: {exc}"), sys.stdout, ensure_ascii=True)
            sys.stdout.write("\n")
            return 1
    mover: BoardMover | None = None
    try:
        mover = default_mover()
    except Exception as exc:  # a malformed board.executor fails visibly, never falls back to item-edit
        json.dump(_payload(result="reject", state=None, to=None, reason="executor:config", message=str(exc)), sys.stdout, ensure_ascii=True)
        sys.stdout.write("\n")
        return 1
    if args.dry_run and not getattr(mover, "via_executor", False):
        mover = None
    payload = process_event(
        args.event,
        card=args.card,
        change=args.change,
        dry_run=args.dry_run,
        client=args.client,
        parent_capture=parent_capture,
        mover=mover,
        checks_green_measurer=measure_checks_green,
        checks_green_classifier=classify_qa_gate,
        pr_lister=lambda q_git: _pr_list_json(str(q_git or ""), fields="number,headRefOid"),
        t14_runner=None if args.dry_run else LiveT14Runner(),
        m_lote_measurer=measure_m_lote,
        t16_closer=None if args.dry_run else LiveT16Closer(),
    )
    json.dump(payload, sys.stdout, ensure_ascii=True)
    sys.stdout.write("\n")
    return 0 if payload.get("result") == "transition" else 1


if __name__ == "__main__":
    raise SystemExit(main())
