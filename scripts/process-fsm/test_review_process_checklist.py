from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from review_process_checklist import _check_tasks, check  # noqa: E402


def _write_tasks(change_dir: Path, text: str) -> None:
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "tasks.md").write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("task", "due_phase", "barrier"),
    [
        ("4.2 Publish the pin <!-- covenant-flow:after-commit -->", "postcommit", "commit"),
        ("5.4 Run the pilot <!-- covenant-flow:after-pin -->", "postpin", "pin"),
        ("5.5 Update the board <!-- covenant-flow:after-qa -->", "postqa", "qa"),
    ],
)
def test_phase_annotation_only_defers_a_task_until_its_declared_barrier(
    tmp_path: Path, task: str, due_phase: str, barrier: str
):
    change = tmp_path / "change"
    _write_tasks(change, f"- [ ] {task}\n")

    assert _check_tasks(change, "precommit") is None
    if barrier == "pin":
        assert _check_tasks(change, "postcommit") is None
    if barrier == "qa":
        assert _check_tasks(change, "postcommit") is None
        assert _check_tasks(change, "postpin") is None
    assert _check_tasks(change, due_phase) == f"tasks.md task {task.split()[0]} pending at {due_phase}"
    assert _check_tasks(change) == "tasks.md pending"


@pytest.mark.parametrize(
    "task",
    [
        "1.4 Implement bridges",
        "1.4 Implement bridges <!-- covenant-flow:after-unknown -->",
        "1.4 Implement bridges <!-- covenant-flow:after-commit --> <!-- covenant-flow:after-pin -->",
    ],
)
def test_precommit_rejects_open_implementation_or_invalid_defer_annotation(
    tmp_path: Path, task: str
):
    change = tmp_path / "change"
    _write_tasks(change, f"- [ ] {task}\n")

    expected = "tasks.md phase annotation" if "covenant-flow:" in task else "tasks.md pending"
    assert _check_tasks(change, "precommit") == expected


def test_precommit_uses_open_spec_from_external_consumer_root(tmp_path: Path):
    repo = tmp_path / "product"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "card-1042-codex-adapter", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "checklist@test.local"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Checklist Test"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "README.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "baseline"],
        check=True,
        capture_output=True,
        text=True,
    )
    patch = repo / ".cursor" / "tmp" / "review-diff.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text("diff --git a/README.md b/README.md\n", encoding="utf-8")

    consumer = tmp_path / "consumer"
    change = consumer / "openspec" / "changes" / "card-1042-codex-adapter"
    _write_tasks(
        change,
        "\n".join(
            [
                "- [x] 1.1 Inventory installation paths",
                "- [ ] 4.2 Publish the pin <!-- covenant-flow:after-commit -->",
                "- [ ] 5.4 Run the pilot <!-- covenant-flow:after-pin -->",
                "- [ ] 5.5 Update the board <!-- covenant-flow:after-qa -->",
            ]
        )
        + "\n",
    )
    (change / "design.md").write_text(
        "UI impact: none\nlive_route: N/A harness-only; no product route\nsurface: none\n",
        encoding="utf-8",
    )

    assert check(
        repo,
        "yes",
        change_root=consumer,
        phase="precommit",
    ) is None
    assert check(repo, "yes", change_root=consumer) == "tasks.md pending"

    tasks = change / "tasks.md"
    tasks.write_text(
        tasks.read_text(encoding="utf-8") + "- [ ] 3.2 Run reviewers\n",
        encoding="utf-8",
    )
    assert check(
        repo,
        "yes",
        change_root=consumer,
        phase="precommit",
    ) == "tasks.md pending"
