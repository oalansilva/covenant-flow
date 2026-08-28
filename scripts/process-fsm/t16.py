"""T16 live measurer and package closer. Tests inject fakes; no GitHub in pytest."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Callable, Protocol

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
RELEASE_GUARD = REPO_ROOT / "scripts" / "release-guard"
COMMENT_SCRIPT = REPO_ROOT / "scripts" / "post-card-evidence-comment.sh"
MAX_CARD = 2147483647
HOMOLOGADO = "Homologado"
PRONTO = "Pronto"


class T16Error(RuntimeError):
    """I9: package/comment/closeout failed after M_lote. Status stays Homologado for remaining ids."""


class T16Closer(Protocol):
    def comment_pronto(self, *, card: str, package: list[int]) -> None: ...


class RecordingT16Closer:
    def __init__(self, fail_at: str | None = None) -> None:
        self.calls: list[str] = []
        self.cards: list[str] = []
        self.fail_at = fail_at

    def comment_pronto(self, *, card: str, package: list[int]) -> None:
        del package
        self.calls.append("comment_pronto")
        self.cards.append(str(card))
        if self.fail_at == "comment_pronto":
            raise T16Error("comment_pronto")


def parse_package_cards(raw: str | None, card: str | int | None) -> list[int] | None:
    """Canonical RELEASE_CARDS. None = invalid tokens. [] = empty."""
    text = (raw or "").strip()
    if text:
        ids: list[int] = []
        seen: set[int] = set()
        for token in text.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                number = int(token, 10)
            except ValueError:
                return None
            if number < 1 or number > MAX_CARD:
                return None
            if number not in seen:
                ids.append(number)
                seen.add(number)
        return ids
    if card is None or str(card).strip() in {"", "⊥"}:
        return []
    try:
        number = int(str(card).lstrip("#"), 10)
    except ValueError:
        return None
    if number < 1 or number > MAX_CARD:
        return None
    return [number]


def lote_git(q_git: str | None) -> bool:
    name = str(q_git or "")
    return name == "develop" or name.startswith("release-")


def measure_m_lote(
    *,
    cwd: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    script = RELEASE_GUARD
    try:
        proc = runner(
            [str(script), "post"],
            cwd=str(cwd) if cwd is not None else str(REPO_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired, TypeError, ValueError):
        return False
    return proc.returncode == 0


def classify_package(
    package: list[int],
    status_of: Callable[[str | None], str | None],
) -> tuple[list[int], list[int]]:
    """Return (homologado_ids, pronto_ids). Raises T16Error if any other Status/missing."""
    homologado: list[int] = []
    pronto: list[int] = []
    for number in package:
        status = status_of(str(number))
        if status == HOMOLOGADO:
            homologado.append(number)
        elif status == PRONTO:
            pronto.append(number)
        else:
            raise T16Error(f"package member {number} status={status!r}")
    return homologado, pronto


class LiveT16Closer:
    def __init__(
        self,
        *,
        cwd: Path | None = None,
        comment_script: Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.cwd = cwd or REPO_ROOT
        self.comment_script = comment_script or COMMENT_SCRIPT
        self._run = runner
        self.commit = ""

    def _origin_main(self) -> str:
        try:
            proc = self._run(
                ["git", "-C", str(self.cwd), "rev-parse", "origin/main"],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise T16Error("comment_pronto: origin/main") from exc
        sha = (proc.stdout or "").strip()
        if proc.returncode != 0 or not sha:
            raise T16Error("comment_pronto: origin/main")
        return sha

    def comment_pronto(self, *, card: str, package: list[int]) -> None:
        if not self.commit:
            self.commit = self._origin_main()
        deploy = os.environ.get("PROD_DEPLOY_EVIDENCE", "").strip()
        cards = ",".join(str(n) for n in package)
        args = [
            "bash",
            str(self.comment_script),
            "--transition",
            "pronto",
            "--card",
            str(card),
            "--commit",
            self.commit,
            "--package",
            "release-guard post",
            "--cards",
            cards,
        ]
        if deploy:
            args.extend(["--deploy", deploy])
        try:
            proc = self._run(
                args,
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise T16Error("comment_pronto: timeout") from exc
        if proc.returncode != 0:
            raise T16Error((proc.stderr or proc.stdout or "comment_pronto failed").strip())
