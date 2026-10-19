"""Resolve (q, bound_card, q_git) from filesystem/git. No GitHub, no Cursor hooks."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from fsm import CARD_GIT_RE

UNBOUND = "⊥"

# Absolute GIT_DIR/GIT_WORK_TREE (session, hook, worktree) override `git -C`.
_GIT_OVERRIDE_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)

ResolveResult = dict[str, str | None]


def _normalize_issue_id(issue_id: Any) -> str | None:
    if issue_id is None or issue_id == "":
        return None
    text = str(issue_id).strip().lstrip("#")
    return text or None


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _GIT_OVERRIDE_VARS:
        env.pop(key, None)
    return env


def _git_abbrev_ref(directory: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            env=_git_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return UNBOUND
    if result.returncode != 0:
        return UNBOUND
    branch = (result.stdout or "").strip()
    if not branch or branch == "HEAD":
        return UNBOUND
    return branch


def _card_id(branch: str) -> str | None:
    if branch == UNBOUND:
        return None
    match = CARD_GIT_RE.match(branch)
    return match.group(1) if match else None


def _git_dir_for_path(cwd: Path, path: Path) -> Path:
    resolved = path if path.is_absolute() else (cwd / path)
    resolved = resolved.resolve()
    if resolved.is_dir():
        return resolved
    return resolved.parent


def resolve(
    cwd: str | Path,
    path: str | Path,
    issue_id: str | int | None = None,
    status: str | None = None,
) -> ResolveResult:
    """Classify q_git by the file path worktree; bind bound_card from the path card id."""
    cwd_path = Path(cwd).resolve()
    git_dir = _git_dir_for_path(cwd_path, Path(path))
    q_git = _git_abbrev_ref(git_dir)
    cwd_git = _git_abbrev_ref(cwd_path)

    path_card = _card_id(q_git)
    cwd_card = _card_id(cwd_git)
    wanted_issue = _normalize_issue_id(issue_id)

    bound_card = UNBOUND
    if path_card is not None:
        bound_card = path_card
        if cwd_card is not None and cwd_card != path_card:
            bound_card = UNBOUND
        elif wanted_issue is not None and wanted_issue != path_card:
            bound_card = UNBOUND

    return {"q": status, "bound_card": bound_card, "q_git": q_git}


APP_FOLDER_SEGMENTS = (".claude", "worktrees")
APP_FOLDER_TEXT = (
    "pasta do app (sem card): esta pasta foi criada pelo app desktop do Claude, fora do worktree de qualquer card. "
    "Escrita de produto e de OpenSpec, filhos de etapa e process_event ficam recusados aqui. "
    "Para trabalhar num card, peça `#<id>` nesta mesma sessão: ela entra sozinha no worktree `card-<id>-*` com `EnterWorktree`. "
    "A pasta do app não é apagada nem adotada como worktree de card."
)


def configured_worktree_folder(home: Path | None = None) -> Path | None:
    """`worktree.location` of `~/.claude/settings.json` (nested or dotted key), when the app was configured with one."""

    try:
        document = json.loads(((home or Path.home()) / ".claude" / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(document, dict):
        return None
    nested = document.get("worktree")
    value = nested.get("location") if isinstance(nested, dict) else document.get("worktree.location")
    return Path(value).expanduser() if isinstance(value, str) and value.strip() else None


def app_folder(path: str | Path) -> Path | None:
    """The folder the desktop app created for `path` (its worktree option), or None.

    Recognized by the `.claude/worktrees/<name>` segment the app uses by default, or by living under the configured
    worktree folder. The branch the app creates is not `card-<id>-*`, so such a folder is a folder without a card;
    this only names it for the visible message and never binds or adopts it.
    """

    try:
        resolved = Path(path).expanduser().resolve()
    except OSError:
        return None
    parts = resolved.parts
    for index in range(len(parts) - 2):
        if parts[index : index + 2] == APP_FOLDER_SEGMENTS:
            return Path(*parts[: index + 3])
    configured = configured_worktree_folder()
    if configured is not None:
        try:
            base = configured.resolve()
            relative = resolved.relative_to(base)
        except (OSError, ValueError):
            return None
        return base / relative.parts[0] if relative.parts else None
    return None


def app_folder_note(path: str | Path, bound_card: str | None = None) -> str | None:
    """Visible text when `path` is the app's own folder and no card is bound; None otherwise."""

    if bound_card not in (None, "", UNBOUND):
        return None
    folder = app_folder(path)
    return f"{APP_FOLDER_TEXT} Pasta: {folder}." if folder is not None else None
