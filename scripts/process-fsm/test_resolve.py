from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from resolve import UNBOUND, resolve  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path: Path, branch: str, *, filename: str = "tracked.txt") -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", branch, str(path)], check=True, capture_output=True, text=True)
    _run_git(path, "config", "user.email", "process-fsm@test.local")
    _run_git(path, "config", "user.name", "process-fsm")
    tracked = path / filename
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("fixture\n", encoding="utf-8")
    _run_git(path, "add", filename)
    _run_git(path, "commit", "-m", "init")
    return tracked


def test_path_in_another_card_worktree(tmp_path: Path):
    cwd_repo = tmp_path / "card-605"
    path_repo = tmp_path / "card-610"
    _init_repo(cwd_repo, "card-605-discovery-walk-forward-split")
    tracked = _init_repo(path_repo, "card-610-process-fsm-resolver")

    result = resolve(cwd_repo, tracked, issue_id=610, status="Em desenvolvimento")

    assert result["bound_card"] == UNBOUND
    assert result["q_git"] == "card-610-process-fsm-resolver"
    assert result["q"] == "Em desenvolvimento"


def test_git_dir_env_does_not_override_path_worktree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cwd_repo = tmp_path / "card-605"
    path_repo = tmp_path / "card-610"
    _init_repo(cwd_repo, "card-605-discovery-walk-forward-split")
    tracked = _init_repo(path_repo, "card-610-process-fsm-resolver")
    monkeypatch.setenv("GIT_DIR", str(cwd_repo / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(cwd_repo))

    result = resolve(cwd_repo, tracked)

    assert result["q_git"] == "card-610-process-fsm-resolver"
    assert result["bound_card"] == UNBOUND


def test_session_on_develop_editing_card_worktree(tmp_path: Path):
    cwd_repo = tmp_path / "develop"
    path_repo = tmp_path / "card-610"
    _init_repo(cwd_repo, "develop")
    tracked = _init_repo(path_repo, "card-610-process-fsm-resolver")

    result = resolve(cwd_repo, tracked)

    assert result["bound_card"] == "610"
    assert result["q_git"] == "card-610-process-fsm-resolver"
    assert result["q"] is None


def test_path_on_develop(tmp_path: Path):
    repo = tmp_path / "develop"
    tracked = _init_repo(repo, "develop")

    result = resolve(repo, tracked, issue_id=610)

    assert result["q_git"] == "develop"
    assert result["bound_card"] == UNBOUND


def test_path_on_main(tmp_path: Path):
    repo = tmp_path / "main"
    tracked = _init_repo(repo, "main")

    result = resolve(repo, tracked)

    assert result["q_git"] == "main"
    assert result["bound_card"] == UNBOUND


def test_unbound_non_card_branch(tmp_path: Path):
    repo = tmp_path / "change"
    tracked = _init_repo(repo, "change-608-process-fsm")

    result = resolve(repo, tracked)

    assert result["bound_card"] == UNBOUND
    assert result["q_git"] == "change-608-process-fsm"


def test_issue_id_conflicts_with_path_card(tmp_path: Path):
    repo = tmp_path / "card-610"
    tracked = _init_repo(repo, "card-610-process-fsm-resolver")

    result = resolve(repo, tracked, issue_id=605)

    assert result["bound_card"] == UNBOUND
    assert result["q_git"] == "card-610-process-fsm-resolver"


def test_matching_card_binds(tmp_path: Path):
    repo = tmp_path / "card-610"
    tracked = _init_repo(repo, "card-610-process-fsm-resolver")

    omitted = resolve(repo, tracked)
    with_id = resolve(repo, tracked, issue_id="610")

    assert omitted["bound_card"] == "610"
    assert with_id["bound_card"] == "610"
    assert omitted["q_git"] == "card-610-process-fsm-resolver"


def test_git_missing(tmp_path: Path):
    missing = tmp_path / "not-a-repo"
    missing.mkdir()
    target = missing / "file.txt"
    target.write_text("x\n", encoding="utf-8")

    result = resolve(missing, target)

    assert result["q_git"] == UNBOUND
    assert result["bound_card"] == UNBOUND


def test_detached_head(tmp_path: Path):
    repo = tmp_path / "card-610"
    tracked = _init_repo(repo, "card-610-process-fsm-resolver")
    _run_git(repo, "checkout", "--detach")

    result = resolve(repo, tracked, issue_id=610)

    assert result["q_git"] == UNBOUND
    assert result["bound_card"] == UNBOUND


def test_relative_path_resolves_against_cwd(tmp_path: Path):
    repo = tmp_path / "card-610"
    _init_repo(repo, "card-610-process-fsm-resolver", filename="nested/file.txt")

    result = resolve(repo, "nested/file.txt")

    assert result["bound_card"] == "610"
    assert result["q_git"] == "card-610-process-fsm-resolver"


def test_directory_path_uses_that_directory(tmp_path: Path):
    repo = tmp_path / "card-610"
    _init_repo(repo, "card-610-process-fsm-resolver")

    result = resolve(tmp_path, repo)

    assert result["q_git"] == "card-610-process-fsm-resolver"
    assert result["bound_card"] == "610"


def test_q_is_injected_status(tmp_path: Path):
    repo = tmp_path / "card-610"
    tracked = _init_repo(repo, "card-610-process-fsm-resolver")

    result = resolve(repo, tracked, status="Code Review")

    assert result["q"] == "Code Review"
