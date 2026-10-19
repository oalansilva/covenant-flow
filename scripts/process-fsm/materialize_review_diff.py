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


NUCLEUS_PREFIX = "covenant-flow/"
NUCLEUS_INSTALLER = "install.sh"


def _pin_at(repo: Path, ref: str) -> str | None:
    """The `pin:` tag the overlay carries at `ref` (the pin the consumer reviewed before this card)."""

    shown = _run_git(repo, "show", f"{ref}:.covenant-flow/overlay.yaml")
    if shown.returncode != 0:
        return None
    for line in (shown.stdout or "").splitlines():
        if line.startswith("pin:"):
            value = line.split(":", 1)[1].strip().strip("\"'")
            return value or None
    return None


def nucleus_installer_diff(nucleus: Path, base: str) -> str:
    """Diff of the nucleus `install.sh` since the previously pinned tag, as part of the consumer's review diff (R21).

    The installer is the only part of the pin that never reaches the consumer tree, so a diff of the consumer alone
    would hide the code that writes the operator account. Paths are prefixed `covenant-flow/` to say whose file it is.
    """

    result = _run_git(nucleus, "diff", base, "--", NUCLEUS_INSTALLER)
    if result.returncode not in (0, 1):
        raise ValueError(f"cannot diff the nucleus {NUCLEUS_INSTALLER} against {base}: {(result.stderr or '').strip()}")
    text = result.stdout or ""
    return (
        text.replace(f"a/{NUCLEUS_INSTALLER}", f"a/{NUCLEUS_PREFIX}{NUCLEUS_INSTALLER}")
        .replace(f"b/{NUCLEUS_INSTALLER}", f"b/{NUCLEUS_PREFIX}{NUCLEUS_INSTALLER}")
    )


def materialize(repo: Path, mode: str, integration_branch: str, nucleus: Path | None = None, nucleus_base: str | None = None) -> str:
    patch = _materialize_consumer(repo, mode, integration_branch)
    if nucleus is None:
        return patch
    base = nucleus_base or _pin_at(repo, "HEAD" if mode == "pre-commit" else f"origin/{integration_branch}")
    if not base:
        raise ValueError("the nucleus diff needs --nucleus-base or a pinned overlay at the reviewed base")
    extra = nucleus_installer_diff(nucleus, base)
    return patch + ("" if not extra or patch.endswith("\n") or not patch else "\n") + extra


def _materialize_consumer(repo: Path, mode: str, integration_branch: str) -> str:
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
    parser.add_argument("--nucleus", help="covenant-flow checkout: its install.sh diff since the previously pinned tag joins the review diff")
    parser.add_argument("--nucleus-base", help="tag/ref of the nucleus to diff against (default: the pin of the reviewed base)")
    args = parser.parse_args(argv)
    repo = Path(args.root)
    try:
        text = materialize(repo, args.mode, args.integration_branch, Path(args.nucleus) if args.nucleus else None, args.nucleus_base)
    except ValueError as exc:
        print(f"materialize_review_diff: {exc}", file=sys.stderr)
        return 2
    out = repo / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
