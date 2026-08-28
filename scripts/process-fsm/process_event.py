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
from guard import github_status_provider  # noqa: E402
from resolve import UNBOUND, resolve  # noqa: E402
from t14 import LiveT14Runner, T14Error, T14Runner, measure_checks_green, run_t14  # noqa: E402
from t16 import (  # noqa: E402
    LiveT16Closer,
    T16Closer,
    T16Error,
    classify_package,
    lote_git,
    measure_m_lote,
    parse_package_cards,
)

REPO_ROOT = ROOT.parents[1]
AMBIENTES = "covenant-flow-environments"
RELEASE_GUARD = "release-guard"
HUMAN_EVENTS = frozenset({"priorizar", "aprovar_design", "homologar", "devolver_design", "cancelar"})
I4_EVENTS = frozenset({"iniciar_apply", "pedir_review"})
CHANGE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
EVENT_GUARDS = {
    "achar_bloqueante": {"open_p0_p1": True, "reviewers_ok": False},
    "aceitar_sha": {"reviewers_ok": True, "open_p0_p1": False},
    "rerun_infra": {"flaky_infra": True, "source_failure": False, "checks_green": False},
    "falha_codigo": {"source_failure": True, "flaky_infra": False, "checks_green": False},
}


class BoardMover(Protocol):
    def set_status(self, issue_number: int, to: str) -> None: ...


class FakeMover:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str]] = []

    def set_status(self, issue_number: int, to: str) -> None:
        self.calls.append((issue_number, to))


class GhBoardMover:
    """Live Project Status edit from overlay board ids. Tests MUST inject FakeMover instead."""

    def set_status(self, issue_number: int, to: str) -> None:
        import subprocess

        overlay = load_overlay(REPO_ROOT)
        option = status_options(overlay).get(to)
        field = status_field_id(overlay)
        project_id = board_project_id(overlay)
        if option is None or not field or not project_id:
            raise ValueError(f"unknown Status {to!r} or overlay board ids missing")
        item_id = _item_id_for_issue(issue_number)
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
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(str(exc)) from exc
        if proc.returncode != 0:
            raise RuntimeError((proc.stderr or proc.stdout or "item-edit failed").strip())


def _item_id_for_issue(issue_number: int) -> str:
    import json as json_mod
    import subprocess

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
            ["gh", "api", "graphql", "-f", f"query={query}", "-F", f"n={issue_number}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(str(exc)) from exc
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or "graphql failed").strip())
    try:
        data = json_mod.loads(proc.stdout or "{}")
    except json_mod.JSONDecodeError as exc:
        raise RuntimeError("graphql json") from exc
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
    raise RuntimeError(f"issue {issue_number} not on Project {board_number}")


def _unbound(bound: Any) -> bool:
    return bound in (None, "", UNBOUND)


def _safe_move(mover: BoardMover, issue_number: int, to: str) -> dict[str, Any] | None:
    try:
        mover.set_status(issue_number, to)
    except (RuntimeError, ValueError, OSError) as exc:
        return _payload(result="reject", state=None, to=None, reason="move_failed", message=str(exc))
    return None


def files_g_design(change_dir: Path) -> bool:
    needed = [change_dir / "proposal.md", change_dir / "design.md", change_dir / "tasks.md"]
    if not all(path.is_file() for path in needed):
        return False
    specs = change_dir / "specs"
    return bool(specs.is_dir() and any(specs.rglob("*.md")))


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


def _fechar_message(base: str | None) -> str:
    text = base or "reject"
    if AMBIENTES not in text:
        text = f"{text}; see {AMBIENTES} and {RELEASE_GUARD}"
    elif RELEASE_GUARD not in text:
        text = f"{text}; {RELEASE_GUARD}"
    return text


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
    m_lote_measurer: Callable[[], bool] | None = None,
    checks_green: bool | None = None,
    checks_green_measurer: Callable[..., bool] | None = None,
    t14_runner: T14Runner | None = None,
    t16_closer: T16Closer | None = None,
    status_provider: Callable[[str | None], str | None] | None = None,
    package_cards: list[int] | None = None,
    fsm: dict[str, Any] | None = None,
    resolve_fn: Callable[..., dict[str, str | None]] = resolve,
    change_dir: Path | None = None,
    prototype_dir: Path | None = None,
) -> dict[str, Any]:
    if event == "criar_card":
        return _payload(
            result="reject",
            state=status,
            to=None,
            reason="not_implemented",
            message="criar_card is out of scope for process_event; create the issue/card first.",
        )
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
    if q is None:
        q = github_status_provider(None if _unbound(bound) else str(bound))
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

    if g_design is None:
        g_design = files_g_design(resolved_change_dir) if resolved_change_dir else False
    if digest_changed is None:
        digest_changed = measure_digest_changed(resolved_change_dir, resolved_proto, q)
    if event == "fechar_release" and m_lote is None:
        if m_lote_measurer is None:
            m_lote = False
        else:
            try:
                m_lote = bool(m_lote_measurer())
            except (OSError, RuntimeError, TypeError, ValueError):
                m_lote = False
    elif m_lote is None:
        m_lote = False
    if event == "integrar_develop" and checks_green is None:
        if checks_green_measurer is None:
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
                failed = _safe_move(mover, issue_number, compiled.to or "Design")
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

    enabled = enabled_events(table, eval_state if event == "fechar_release" else q)
    message = None
    if event == "fechar_release":
        message = _fechar_message(result.reason)
    if result.result != "transition":
        extra = enabled if event in {"request_implement", "pular_coluna", "Agent.aprovar_design"} or result.reason in {
            "illegal_event",
            "no_edge",
        } else None
        if event == "request_implement":
            extra = enabled
        return _payload(
            result="reject",
            state=q,
            to=None,
            reason=result.reason,
            enabled=extra,
            message=message,
        )
    if event == "integrar_develop":
        if dry_run:
            return _payload(result="transition", state=q, to=result.to, reason=result.reason, message=message)
        if t14_runner is None:
            return _payload(result="reject", state=q, to=None, reason="I8")
        try:
            run_t14(t14_runner, q_git=str(git), bound_card=str(bound))
        except T14Error:
            return _payload(result="reject", state=q, to=None, reason="I8")
        if mover is None or issue_number is None:
            return _payload(result="transition", state=q, to=result.to, reason=result.reason, message=message)
        failed = _safe_move(mover, issue_number, result.to or "")
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
                    failed = _safe_move(mover, number, result.to or "Pronto")
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
    failed = _safe_move(mover, issue_number, result.to or "")
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
    args = parser.parse_args(argv)
    payload = process_event(
        args.event,
        card=args.card,
        change=args.change,
        dry_run=args.dry_run,
        mover=None if args.dry_run else GhBoardMover(),
        checks_green_measurer=measure_checks_green,
        t14_runner=None if args.dry_run else LiveT14Runner(),
        m_lote_measurer=measure_m_lote,
        t16_closer=None if args.dry_run else LiveT16Closer(),
    )
    json.dump(payload, sys.stdout, ensure_ascii=True)
    sys.stdout.write("\n")
    return 0 if payload.get("result") == "transition" else 1


if __name__ == "__main__":
    raise SystemExit(main())
