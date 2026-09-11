"""T14 live measurer and atomic closeout runner. Tests inject fakes; no GitHub in pytest."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Protocol

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from overlay import repo_slug, try_load_overlay  # noqa: E402
REPO_ROOT = ROOT.parents[1]
QA_GATE = "qa-gate"
HEALTH_ATTEMPTS = 15
HEALTH_SLEEP_S = 1
_GIT_OVERRIDE_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _overlay_repo() -> str:
    data = try_load_overlay(REPO_ROOT)
    return repo_slug(data) if data else ""


def _overlay_dev_source() -> Path | None:
    data = try_load_overlay(REPO_ROOT)
    if not data:
        return None
    env = ((data.get("environments") or {}).get("dev") or {})
    source = str(env.get("source") or "").strip()
    return Path(source) if source else None


def _overlay_restart(source: Path) -> Path:
    data = try_load_overlay(REPO_ROOT)
    rel = ""
    if data:
        rel = str(((data.get("release") or {}).get("restart")) or "").strip()
    if not rel:
        return source / "restart"
    candidate = Path(rel)
    return candidate if candidate.is_absolute() else (source / rel)


def _overlay_health_url() -> str:
    """T14 public health is DEV. `release.health_url` is T16/PROD evidence."""
    data = try_load_overlay(REPO_ROOT)
    if not data:
        return ""
    env = (data.get("environments") or {}).get("dev") or {}
    url = str(env.get("url") or "").rstrip("/")
    return f"{url}/api/health" if url else ""


class T14Error(RuntimeError):
    """I8: squash/sync/restart/comment failed. Status stays QA."""


class T14Runner(Protocol):
    def squash(self, *, q_git: str, bound_card: str) -> None: ...

    def sync_dev_source(self) -> None: ...

    def restart(self) -> None: ...

    def comment_done(self, *, bound_card: str, q_git: str) -> None: ...


class RecordingT14Runner:
    def __init__(self, fail_at: str | None = None) -> None:
        self.calls: list[str] = []
        self.fail_at = fail_at

    def _step(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_at == name:
            raise T14Error(name)

    def squash(self, *, q_git: str, bound_card: str) -> None:
        self._step("squash")

    def sync_dev_source(self) -> None:
        self._step("sync_dev_source")

    def restart(self) -> None:
        self._step("restart")

    def comment_done(self, *, bound_card: str, q_git: str) -> None:
        self._step("comment_done")


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _GIT_OVERRIDE_VARS:
        env.pop(key, None)
    return env


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    return runner(
        args,
        cwd=str(cwd) if cwd is not None else None,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
        env=_git_env(),
    )


def _pr_list_json(
    q_git: str,
    *,
    fields: str,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[dict]:
    """List PRs for branch head. gh 2.45 matches --head by branch name, not owner:branch."""
    listed = _run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            _overlay_repo(),
            "--head",
            str(q_git),
            "--base",
            "develop",
            "--state",
            "all",
            "--limit",
            "1",
            "--json",
            fields,
        ],
        timeout=20,
        runner=runner,
    )
    if listed.returncode != 0:
        return []
    rows = json.loads(listed.stdout or "[]")
    return rows if isinstance(rows, list) else []


def classify_qa_gate(
    bound_card: str | int | None,
    q_git: str | None,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, bool | str | None]:
    """Classify qa-gate on the PR q_git→develop. Tokens: no_pr | qa-gate pending | qa-gate failed."""
    del bound_card
    if not q_git:
        return {"ok": False, "reason": "no_pr"}
    try:
        listed = _run(
            [
                "gh",
                "pr",
                "list",
                "--repo",
                _overlay_repo(),
                "--head",
                str(q_git),
                "--base",
                "develop",
                "--state",
                "all",
                "--limit",
                "1",
                "--json",
                "number,headRefOid",
            ],
            timeout=20,
            runner=runner,
        )
        if listed.returncode != 0:
            return {"ok": False, "reason": "qa-gate failed"}
        try:
            rows = json.loads(listed.stdout or "[]")
        except json.JSONDecodeError:
            return {"ok": False, "reason": "qa-gate failed"}
        if not isinstance(rows, list) or not rows:
            return {"ok": False, "reason": "no_pr"}
        head = rows[0].get("headRefOid") if isinstance(rows[0], dict) else None
        if not head:
            return {"ok": False, "reason": "no_pr"}
        # gh 2.45 has no `pr checks --json`; use Checks API on the head SHA.
        checks = _run(
            [
                "gh",
                "api",
                f"repos/{_overlay_repo()}/commits/{head}/check-runs",
                "--paginate",
                "--jq",
                ".check_runs[] | {name,status,conclusion}",
            ],
            timeout=30,
            runner=runner,
        )
        if checks.returncode != 0:
            return {"ok": False, "reason": "qa-gate failed"}
        text = (checks.stdout or "").strip()
        if not text:
            return {"ok": False, "reason": "qa-gate failed"}
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(item.get("name") or "") != QA_GATE:
                continue
            status = str(item.get("status") or "").lower()
            conclusion = str(item.get("conclusion") or "").lower()
            if status != "completed":
                return {"ok": False, "reason": "qa-gate pending"}
            if conclusion == "success":
                return {"ok": True, "reason": None}
            return {"ok": False, "reason": "qa-gate failed"}
        return {"ok": False, "reason": "qa-gate failed"}
    except (OSError, subprocess.TimeoutExpired, TypeError, ValueError):
        return {"ok": False, "reason": "qa-gate failed"}


def measure_checks_green(
    bound_card: str | int | None,
    q_git: str | None,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool:
    return bool(classify_qa_gate(bound_card, q_git, runner=runner).get("ok"))


class LiveT14Runner:
    def __init__(
        self,
        *,
        source: Path | None = None,
        restart_path: Path | None = None,
        health_url: str | None = None,
        comment_script: Path | None = None,
        canonical_restart: Path | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        health_get: Callable[[str], bool] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        overlay_source = _overlay_dev_source()
        self.source = source if source is not None else (overlay_source or REPO_ROOT)
        self.canonical_restart = canonical_restart
        if self.canonical_restart is None and overlay_source is not None and source in (None, overlay_source):
            self.canonical_restart = _overlay_restart(self.source)
        self.restart_path = restart_path if restart_path is not None else _overlay_restart(self.source)
        self.health_url = health_url if health_url is not None else _overlay_health_url()
        self.comment_script = comment_script or (self.source / "scripts" / "post-card-evidence-comment.sh")
        self._run = runner
        self._health_get = health_get or _http_health
        self._sleep = sleep
        self.commit = ""
        self.pr: str | None = None

    def squash(self, *, q_git: str, bound_card: str) -> None:
        del bound_card
        try:
            rows = _pr_list_json(str(q_git), fields="number,state,mergedAt", runner=self._run)
        except json.JSONDecodeError as exc:
            raise T14Error("squash: pr list json") from exc
        if not rows:
            if self._sha_on_develop(q_git):
                return
            raise T14Error("squash: no PR")
        number = rows[0].get("number")
        state = str(rows[0].get("state") or "").upper()
        merged = rows[0].get("mergedAt")
        if number is None:
            raise T14Error("squash: no PR number")
        self.pr = str(number)
        if state == "MERGED" or merged:
            return
        merged_pr = _run(
            [
                "gh",
                "pr",
                "merge",
                str(number),
                "--repo",
                _overlay_repo(),
                "--squash",
            ],
            timeout=120,
            runner=self._run,
        )
        if merged_pr.returncode != 0:
            raise T14Error((merged_pr.stderr or merged_pr.stdout or "squash merge failed").strip())

    def _sha_on_develop(self, q_git: str) -> bool:
        fetch = _run(["git", "-C", str(self.source), "fetch", "origin", q_git, "develop"], timeout=60, runner=self._run)
        if fetch.returncode != 0:
            return False
        ancestor = _run(
            ["git", "-C", str(self.source), "merge-base", "--is-ancestor", f"origin/{q_git}", "origin/develop"],
            timeout=20,
            runner=self._run,
        )
        return ancestor.returncode == 0

    def sync_dev_source(self) -> None:
        porcelain = _run(
            ["git", "-C", str(self.source), "status", "--porcelain"],
            timeout=20,
            runner=self._run,
        )
        if porcelain.returncode != 0:
            raise T14Error("sync: status failed")
        dirty = (porcelain.stdout or "").strip()
        if dirty:
            raise T14Error(f"sync: dirty {self.source}\n{dirty}")
        for args, label in (
            (["git", "-C", str(self.source), "fetch", "origin"], "fetch"),
            (["git", "-C", str(self.source), "checkout", "develop"], "checkout"),
            (["git", "-C", str(self.source), "merge", "--ff-only", "origin/develop"], "ff-only"),
        ):
            proc = _run(args, timeout=120, runner=self._run)
            if proc.returncode != 0:
                raise T14Error(f"sync: {label}")
        sha = _run(
            ["git", "-C", str(self.source), "rev-parse", "HEAD"],
            timeout=20,
            runner=self._run,
        )
        if sha.returncode != 0 or not (sha.stdout or "").strip():
            raise T14Error("sync: rev-parse")
        self.commit = (sha.stdout or "").strip()

    def restart(self) -> None:
        restart = Path(self.restart_path)
        if self.canonical_restart is not None and restart.resolve() != Path(self.canonical_restart).resolve():
            raise T14Error("restart: path")
        proc = _run([str(restart)], timeout=600, runner=self._run)
        if proc.returncode != 0:
            raise T14Error((proc.stderr or proc.stdout or "restart failed").strip())
        for _ in range(HEALTH_ATTEMPTS):
            if self._health_get(self.health_url):
                return
            self._sleep(HEALTH_SLEEP_S)
        raise T14Error("restart: public health")

    def comment_done(self, *, bound_card: str, q_git: str) -> None:
        del q_git
        if not self.commit:
            raise T14Error("comment_done: no commit")
        script = self.comment_script
        args = [
            "bash",
            str(script),
            "--transition",
            "done",
            "--card",
            str(bound_card),
            "--commit",
            self.commit,
            "--branch",
            "develop",
            "--review",
            "qa-gate green; canonical DEV restart; public health 200",
        ]
        if self.pr:
            args.extend(["--pr", self.pr])
        proc = _run(args, timeout=60, runner=self._run)
        if proc.returncode != 0:
            raise T14Error((proc.stderr or proc.stdout or "comment_done failed").strip())


def _http_health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            return int(getattr(resp, "status", 0) or 0) == 200
    except (OSError, urllib.error.URLError, ValueError):
        return False


def run_t14(runner: T14Runner, *, q_git: str, bound_card: str) -> None:
    try:
        runner.squash(q_git=q_git, bound_card=bound_card)
        runner.sync_dev_source()
        runner.restart()
        runner.comment_done(bound_card=bound_card, q_git=q_git)
    except T14Error:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise T14Error(str(exc)) from exc
