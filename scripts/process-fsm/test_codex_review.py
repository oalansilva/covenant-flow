from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import codex_review  # noqa: E402
from codex_review import ReviewDiffError, capture, verify, verify_wave  # noqa: E402


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _repo(root: Path) -> Path:
    root.mkdir()
    _git(root, "init", "-b", "card-1042-codex-adapter")
    _git(root, "config", "user.email", "codex-review@test.local")
    _git(root, "config", "user.name", "Codex Review Test")
    (root / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(root, "add", "tracked.txt")
    _git(root, "commit", "-m", "base")
    return root


def _write_model_map(root: Path) -> None:
    model_map = root / ".cursor" / "model-map.yaml"
    model_map.parent.mkdir(parents=True, exist_ok=True)
    model_map.write_text(
        "juizo:\n  codex:\n    label: GPT-6 Sol\n    slug: gpt-6-sol\n    effort: high\n"
        "execucao:\n  codex:\n    label: GPT-6 Luna\n    slug: gpt-6-luna\n    effort: max\n"
        "forbid: []\n",
        encoding="utf-8",
    )


def _write_wave(
    repo: Path, entries: list[dict[str, object]], *, map_root: Path | None = None
) -> Path:
    _write_model_map(map_root or repo)
    log = repo / ".cursor" / "tmp" / "codex-child-proxies.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")
    return log


def _wave_entry(activity: str, child_id: str, digest: str) -> dict[str, object]:
    return {
        "wave_id": "1042-review-1",
        "bound_card": "1042",
        "activity": activity,
        "band": "execucao",
        "requested_model": "gpt-6-luna",
        "requested_effort": "max",
        "observed_model": "gpt-6-luna",
        "observed_effort": "max",
        "status": "completed",
        "payload_returned": True,
        "successful": True,
        "child_id": child_id,
        "sandbox_mode": "read-only",
        "review_diff_sha256": digest,
    }


def test_capture_materializes_staged_unstaged_and_untracked_once_with_digest(tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("staged\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    (repo / "tracked.txt").write_text("staged and working\n", encoding="utf-8")
    (repo / "new file.txt").write_text("untracked review content\n", encoding="utf-8")

    path, digest, size = capture(repo)

    body = path.read_bytes()
    assert path == repo / codex_review.DEFAULT_DIFF
    assert size == len(body)
    assert hashlib.sha256(body).hexdigest() == digest
    assert b"staged and working" in body
    assert b"untracked review content" in body
    assert b"new file.txt" in body
    assert verify(path, digest) == (digest, size)


def test_capture_does_not_follow_preexisting_predictable_temp_symlink(tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    output = repo / codex_review.DEFAULT_DIFF
    output.parent.mkdir(parents=True)
    victim = tmp_path / "victim.patch"
    victim.write_bytes(b"protected bytes\n")
    temp_link = output.with_name(f".{output.name}.codex-tmp")
    temp_link.symlink_to(victim)

    path, digest, _size = capture(repo)

    assert path.is_file() and verify(path, digest)[0] == digest
    assert victim.read_bytes() == b"protected bytes\n"
    assert temp_link.is_symlink()


def test_capture_rejects_option_like_base_without_writing_option_output(tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    victim = tmp_path / "git-option-output.patch"
    victim.write_bytes(b"protected bytes\n")

    with pytest.raises(ReviewDiffError, match="invalid Git diff base"):
        capture(repo, base=f"--output={victim}")

    assert victim.read_bytes() == b"protected bytes\n"


def test_capture_excludes_impeccable_critique_tree_for_tracked_and_untracked_files(tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    critique = repo / ".impeccable" / "critique"
    critique.mkdir(parents=True)
    tracked_critique = critique / "notes.md"
    tracked_critique.write_text("initial critique\n", encoding="utf-8")
    _git(repo, "add", ".impeccable/critique/notes.md")
    _git(repo, "commit", "-m", "add critique fixture")

    tracked_critique.write_text("private changed critique\n", encoding="utf-8")
    (critique / "untracked.md").write_text("private untracked critique\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("backend change\n", encoding="utf-8")

    path, _digest, _size = capture(repo)
    body = path.read_bytes()

    assert b"backend change" in body
    assert b".impeccable/critique" not in body
    assert b"private changed critique" not in body
    assert b"private untracked critique" not in body


def test_capture_resolves_three_dot_base_and_ignores_inherited_git_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _repo(tmp_path / "repo")
    outsider = _repo(tmp_path / "outsider")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "update-ref", "refs/remotes/origin/develop", base)
    (repo / "tracked.txt").write_text("range commit change\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "change after develop")
    (repo / "tracked.txt").write_text("working tree change outside range\n", encoding="utf-8")

    monkeypatch.setenv("GIT_DIR", str(outsider / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(outsider))
    monkeypatch.setenv("GIT_INDEX_FILE", str(outsider / ".git" / "index"))
    monkeypatch.setenv("GIT_COMMON_DIR", str(outsider / ".git"))
    monkeypatch.setenv("GIT_NAMESPACE", "missing-namespace")
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(outsider / ".git" / "objects"))
    monkeypatch.setenv("GIT_ALTERNATE_OBJECT_DIRECTORIES", str(outsider / ".git" / "objects"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "core.worktree")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", str(outsider))

    original_run = codex_review.subprocess.run

    def run_with_clean_git_environment(*args, **kwargs):
        env = kwargs.get("env")
        assert isinstance(env, dict)
        assert not any(name.startswith("GIT_") for name in env)
        return original_run(*args, **kwargs)

    monkeypatch.setattr(codex_review.subprocess, "run", run_with_clean_git_environment)

    path, _digest, _size = capture(repo, base="origin/develop...HEAD")

    body = path.read_bytes()
    assert b"range commit change" in body
    assert b"working tree change outside range" not in body


def test_capture_repeat_excludes_review_and_proxy_artifacts_from_untracked_diff(tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    (repo / "new file.txt").write_text("untracked review content\n", encoding="utf-8")
    proxy_log = repo / ".cursor" / "tmp" / "codex-child-proxies.jsonl"
    proxy_log.parent.mkdir(parents=True, exist_ok=True)
    proxy_log.write_text('{"activity":"diff-reviewer"}\n', encoding="utf-8")

    first_path, first_digest, _ = capture(repo)
    first_body = first_path.read_bytes()
    second_path, second_digest, _ = capture(repo)
    second_body = second_path.read_bytes()

    assert first_path == second_path
    assert first_digest == second_digest
    assert first_body == second_body
    assert b"untracked review content" in second_body
    assert b"review-diff.patch" not in second_body
    assert b"codex-child-proxies.jsonl" not in second_body
    assert b'diff-reviewer' not in second_body


def test_capture_repeat_excludes_custom_untracked_output_from_its_own_diff(tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    custom_output = repo / "generated.patch"

    first_path, first_digest, _ = capture(repo, output=custom_output)
    first_body = first_path.read_bytes()
    second_path, second_digest, _ = capture(repo, output=custom_output)
    second_body = second_path.read_bytes()

    assert first_path == second_path == custom_output
    assert first_digest == second_digest
    assert first_body == second_body
    assert b"generated.patch" not in second_body


def test_capture_repeat_excludes_custom_tracked_output_from_its_own_diff(tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    tracked_output = repo / "review output.patch"
    tracked_output.write_text("committed placeholder\n", encoding="utf-8")
    _git(repo, "add", "review output.patch")
    _git(repo, "commit", "-m", "add review output")
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")

    first_path, first_digest, _ = capture(repo, output=tracked_output)
    first_body = first_path.read_bytes()
    second_path, second_digest, _ = capture(repo, output=tracked_output)
    second_body = second_path.read_bytes()

    assert first_path == second_path == tracked_output
    assert first_digest == second_digest
    assert first_body == second_body
    assert b"review output.patch" not in second_body
    assert b"committed placeholder" not in second_body


def test_verify_rejects_wrong_digest_and_empty_intervals(tmp_path: Path):
    patch = tmp_path / "review.patch"
    patch.write_text("diff --git a/x b/x\n+change\n", encoding="utf-8")

    with pytest.raises(ReviewDiffError, match="digest mismatch"):
        verify(patch, "0" * 64)
    patch.write_text("\n", encoding="utf-8")
    with pytest.raises(ReviewDiffError, match="empty"):
        verify(patch, "0" * 64)


def test_capture_rejects_empty_diff_and_output_outside_repository(tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    with pytest.raises(ReviewDiffError, match="empty"):
        capture(repo)
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(ReviewDiffError, match="stay under Git root"):
        capture(repo, output=tmp_path / "outside.patch")


def test_verify_wave_requires_two_distinct_successful_readonly_reviewers_on_same_digest(tmp_path: Path):
    repo = _repo(tmp_path / "repo")
    digest = hashlib.sha256(b"review interval").hexdigest()
    log = _write_wave(
        repo,
        [
            _wave_entry("diff-reviewer", "child-diff", digest),
            _wave_entry("code-reviewer", "child-code", digest),
        ],
    )

    assert verify_wave(
        root=repo,
        proxy_log=log,
        wave_id="1042-review-1",
        expected_sha256=digest,
        bound_card="1042",
    ) == (digest, ("child-diff", "child-code"))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda entries: entries.pop(), "exactly two proxy records"),
        (lambda entries: entries[1].update(activity="diff-reviewer"), "duplicate diff-reviewer"),
        (lambda entries: entries[1].update(review_diff_sha256="0" * 64), "expected diff SHA-256"),
        (lambda entries: entries[0].update(sandbox_mode="workspace-write"), "sandbox_mode=read-only"),
        (lambda entries: entries[0].update(status="failed", successful=False), "did not complete"),
        (lambda entries: entries[0].update(requested_effort="high"), "does not match the current shared map"),
        (
            lambda entries: entries[0].update(
                observed_model="unavailable", observed_effort="unavailable"
            ),
            "observed model pair is unavailable",
        ),
    ],
)
def test_verify_wave_rejects_incomplete_or_mismatched_review_evidence(
    tmp_path: Path, mutate, message: str
):
    repo = _repo(tmp_path / "repo")
    digest = hashlib.sha256(b"review interval").hexdigest()
    entries = [
        _wave_entry("diff-reviewer", "child-diff", digest),
        _wave_entry("code-reviewer", "child-code", digest),
    ]
    mutate(entries)
    log = _write_wave(repo, entries)

    with pytest.raises(ReviewDiffError, match=message):
        verify_wave(
            root=repo,
            proxy_log=log,
            wave_id="1042-review-1",
            expected_sha256=digest,
            bound_card="1042",
        )


def test_verify_wave_reads_shared_map_from_explicit_consumer_root(tmp_path: Path):
    repo = _repo(tmp_path / "product")
    consumer_root = tmp_path / "criptofarol"
    consumer_root.mkdir()
    digest = hashlib.sha256(b"review interval").hexdigest()
    log = _write_wave(
        repo,
        [
            _wave_entry("diff-reviewer", "child-diff", digest),
            _wave_entry("code-reviewer", "child-code", digest),
        ],
        map_root=consumer_root,
    )

    assert not (repo / ".cursor" / "model-map.yaml").exists()
    assert verify_wave(
        root=repo,
        map_root=consumer_root,
        proxy_log=log,
        wave_id="1042-review-1",
        expected_sha256=digest,
        bound_card="1042",
    ) == (digest, ("child-diff", "child-code"))
