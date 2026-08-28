"""sessionStart paging: inject context_file[q] only. No GitHub in unit tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fsm import enabled_events, load_fsm  # noqa: E402
from guard import github_status_provider  # noqa: E402
from overlay import try_load_overlay  # noqa: E402
from resolve import UNBOUND, resolve  # noqa: E402

UNBOUND_PAGE = "bound_card=⊥. Write produto deny. Não carregue playbook de release."
FOOTER = (
    "Resolva (q, bound_card, q_git). Não invente aresta. "
    "Chat é wording; NLU ≠ δ. Overlay on-demand (portas, Drive, release)."
)

ResolveFn = Callable[..., dict[str, str | None]]
StatusProvider = Callable[[str | None], str | None]


def _unbound(bound_card: Any) -> bool:
    return bound_card in (None, "", UNBOUND)


def page(
    *,
    cwd: str | Path,
    path: str | Path | None = None,
    issue_id: str | int | None = None,
    resolve_fn: ResolveFn = resolve,
    status_provider: StatusProvider | None = github_status_provider,
    fsm: dict[str, Any] | None = None,
) -> dict[str, Any]:
    table = fsm if fsm is not None else load_fsm()
    workdir = Path(cwd)
    # Overlay is optional for paging: missing/invalid MUST NOT abort the turn
    # and MUST NOT dump overlay_doc.
    try_load_overlay(workdir, require_filled=False)
    file_path = Path(path) if path is not None else workdir
    resolved = resolve_fn(workdir, file_path, issue_id=issue_id)
    bound = resolved.get("bound_card")
    git = resolved.get("q_git") or UNBOUND
    q: str | None = None
    if not _unbound(bound) and status_provider is not None:
        q = status_provider(None if _unbound(bound) else str(bound))

    context_files = table.get("context_file") or {}
    if _unbound(bound) or q is None or q not in context_files:
        stub = UNBOUND_PAGE
        events = "(unbound)"
        q_display = None if (_unbound(bound) or q is None) else q
        bound_display = UNBOUND if _unbound(bound) else bound
    else:
        stub = str(context_files[q]).strip("\n")
        events = ", ".join(str(item) for item in enabled_events(table, q))
        q_display = q
        bound_display = bound

    lines = [
        "process-fsm page",
        f"q={q_display if q_display is not None else 'None'} bound_card={bound_display} q_git={git}",
        f"enabled_events: {events}",
        "---",
        stub,
        "---",
        FOOTER,
    ]
    additional = "\n".join(lines) + "\n"
    return {
        "additional_context": additional,
        "q": q_display,
        "bound_card": bound_display,
        "q_git": git,
    }


def write_grok_page(
    *,
    cwd: str | Path,
    dest: Path | None = None,
    **kwargs: Any,
) -> Path:
    """SessionStart Grok: persist Moore page; stdout is ignored by the product."""
    workdir = Path(cwd)
    result = page(cwd=workdir, path=kwargs.pop("path", workdir), **kwargs)
    path = dest if dest is not None else workdir / ".grok" / "rules" / "process-fsm-page.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(result["additional_context"]), encoding="utf-8")
    return path


def main() -> int:
    write_file = "--write-grok-page" in sys.argv
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    cwd = payload.get("cwd") or payload.get("workspaceRoot") or os.getcwd()
    if write_file:
        dest = Path(__file__).resolve().parents[2] / ".grok" / "rules" / "process-fsm-page.md"
        write_grok_page(cwd=cwd, dest=dest)
        return 0
    result = page(cwd=cwd, path=cwd)
    json.dump({"additional_context": result["additional_context"]}, sys.stdout, ensure_ascii=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
