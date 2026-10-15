"""Materialize Code Review / Apply-verify diff; exclude Design critique snapshots."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
PATCH_REL = Path(".cursor") / "tmp" / "review-diff.patch"
CRITIQUE_PREFIX = ".impeccable/critique/"
_GIT_OVERRIDE_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _git_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in _GIT_OVERRIDE_VARS:
        env.pop(key, None)
    return env


def _run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
        env=_git_env(),
    )


def _norm_repo_path(raw: str) -> str:
    path = raw.strip().replace("\\", "/")
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    if len(path) >= 2 and path[0] in {'"', "'"} and path[-1] == path[0]:
        path = path[1:-1]
    if path.startswith("./"):
        path = path[2:]
    return path


def is_critique_artifact(path: str) -> bool:
    normalized = _norm_repo_path(path)
    return CRITIQUE_PREFIX in normalized


def _split_unified_diff(patch: str) -> list[str]:
    if not patch.strip():
        return []
    chunks: list[str] = []
    current: list[str] = []
    for line in patch.splitlines(keepends=True):
        if line.startswith("diff --git ") and current:
            chunks.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("".join(current))
    return chunks


def _chunk_path(chunk: str) -> str:
    first = chunk.splitlines()[0] if chunk else ""
    if not first.startswith("diff --git "):
        return ""
    parts = first.split()
    if len(parts) < 4:
        return ""
    old_p = _norm_repo_path(parts[2])
    new_p = _norm_repo_path(parts[3])
    return new_p if new_p != "/dev/null" else old_p


def filter_critique_hunks(patch: str) -> str:
    kept = [
        chunk
        for chunk in _split_unified_diff(patch)
        if chunk and not is_critique_artifact(_chunk_path(chunk))
    ]
    return "".join(kept)


def list_untracked(repo: Path) -> list[str]:
    result = _run_git(repo, "ls-files", "--others", "--exclude-standard")
    if result.returncode != 0:
        return []
    paths = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    return [path for path in paths if not is_critique_artifact(path)]


def materialize(repo: Path, mode: str, integration_branch: str) -> str:
    if mode == "pre-commit":
        tracked = _run_git(repo, "diff", "HEAD")
        if tracked.returncode not in (0, 1):
            tracked_text = ""
        else:
            tracked_text = filter_critique_hunks(tracked.stdout or "")
        untracked_parts: list[str] = []
        for rel in list_untracked(repo):
            path = repo / rel
            if not path.is_file():
                continue
            one = _run_git(repo, "diff", "--no-index", "--", os.devnull, rel)
            if one.returncode in (0, 1) and (one.stdout or "").strip():
                untracked_parts.append(one.stdout)
        return filter_critique_hunks(tracked_text + "".join(untracked_parts))
    if mode == "closing":
        result = _run_git(repo, "diff", f"origin/{integration_branch}...HEAD")
        if result.returncode not in (0, 1):
            return ""
        return filter_critique_hunks(result.stdout or "")
    raise ValueError(f"unknown mode: {mode}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="materialize_review_diff")
    parser.add_argument(
        "--mode",
        choices=("pre-commit", "closing"),
        default="pre-commit",
    )
    parser.add_argument("--root", default=str(REPO_ROOT))
    parser.add_argument("--integration-branch", default="develop")
    parser.add_argument("--out", default=str(PATCH_REL))
    args = parser.parse_args(argv)
    repo = Path(args.root)
    text = materialize(repo, args.mode, args.integration_branch)
    out = repo / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
