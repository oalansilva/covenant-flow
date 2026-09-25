"""Materialize and verify one immutable review interval for Codex reviewers."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from codex_fs import atomic_write_bytes
from codex_models import ModelRoutingError, resolve_pair


DEFAULT_DIFF = Path(".cursor/tmp/review-diff.patch")
DEFAULT_PROXY_LOG = Path(".cursor/tmp/codex-child-proxies.jsonl")
REVIEWERS = ("diff-reviewer", "code-reviewer")
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}\Z")


class ReviewDiffError(ValueError):
    """The review interval could not be materialized or verified."""


def _git(root: Path, *args: str, allow_diff: bool = False) -> bytes:
    env = {name: value for name, value in os.environ.items() if not name.startswith("GIT_")}
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            timeout=30,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReviewDiffError(f"git command failed: {exc}") from exc
    if result.returncode != 0 and not (allow_diff and result.returncode == 1):
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise ReviewDiffError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout


def _git_root(start: str | Path) -> Path:
    directory = Path(start).expanduser().resolve()
    raw = _git(directory, "rev-parse", "--show-toplevel").decode("utf-8", errors="replace").strip()
    if not raw:
        raise ReviewDiffError(f"cannot resolve Git root from {directory}")
    return Path(raw).resolve()


def _tracked_diff(root: Path, base: str, *, exclude: Path) -> bytes:
    relative = exclude.relative_to(root).as_posix()
    if not isinstance(base, str) or not base.strip():
        raise ReviewDiffError("Git diff base must be a non-empty commit or ref")
    def resolve_commit(ref: str) -> str:
        try:
            revision = _git(
                root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"
            ).decode("ascii").strip()
        except ReviewDiffError as exc:
            raise ReviewDiffError(f"invalid Git diff base {base!r}: {exc}") from exc
        if not revision:
            raise ReviewDiffError(f"invalid Git diff base {base!r}: no commit resolved")
        return revision

    if "..." in base:
        if base.count("...") != 1:
            raise ReviewDiffError(f"invalid Git diff base {base!r}: expected one three-dot range")
        left_ref, right_ref = base.split("...", 1)
        if not left_ref.strip() or not right_ref.strip():
            raise ReviewDiffError(f"invalid Git diff base {base!r}: both range refs are required")
        left = resolve_commit(left_ref.strip())
        right = resolve_commit(right_ref.strip())
        revision_args = ("--merge-base", left, right)
    else:
        revision_args = (resolve_commit(base),)
    return _git(
        root,
        "diff",
        "--binary",
        *revision_args,
        "--",
        ".",
        f":(top,exclude,literal){relative}",
        ":(top,exclude,glob).impeccable/critique/**",
        allow_diff=True,
    )


def _is_review_proxy_artifact(relative: Path) -> bool:
    """Do not make local review evidence part of the next untracked review diff."""

    parts = relative.parts
    if len(parts) < 3 or parts[:2] != (".cursor", "tmp"):
        return False
    return any("review" in part.casefold() or "prox" in part.casefold() for part in parts[2:])


def _untracked_diff(root: Path, *, exclude: Path) -> bytes:
    raw_paths = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    out: list[bytes] = []
    excluded = exclude.relative_to(root)
    for raw_path in raw_paths.split(b"\0"):
        if not raw_path:
            continue
        relative = Path(os.fsdecode(raw_path))
        if relative == excluded:
            continue
        if relative.parts[:2] == (".impeccable", "critique"):
            continue
        if _is_review_proxy_artifact(relative):
            continue
        absolute = (root / relative).resolve()
        if root not in absolute.parents or not absolute.is_file():
            raise ReviewDiffError(f"untracked review path escapes repo or is not a file: {relative}")
        patch = _git(root, "diff", "--no-index", "--binary", "--", "/dev/null", str(relative), allow_diff=True)
        if patch:
            out.append(patch)
    return b"".join(out)


def capture(
    start: str | Path,
    *,
    base: str = "HEAD",
    include_untracked: bool = True,
    output: str | Path = DEFAULT_DIFF,
) -> tuple[Path, str, int]:
    root = _git_root(start)
    target = Path(output)
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    if root not in target.parents:
        raise ReviewDiffError(f"review diff output must stay under Git root: {target}")
    diff = _tracked_diff(root, base, exclude=target)
    if include_untracked:
        diff += _untracked_diff(root, exclude=target)
    if not diff.strip():
        raise ReviewDiffError("review interval is empty")
    atomic_write_bytes(target, diff)
    digest = hashlib.sha256(diff).hexdigest()
    return target, digest, len(diff)


def verify(path: str | Path, expected_sha256: str) -> tuple[str, int]:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ReviewDiffError(f"review diff missing: {source}")
    body = source.read_bytes()
    if not body.strip():
        raise ReviewDiffError(f"review diff is empty: {source}")
    digest = hashlib.sha256(body).hexdigest()
    if digest.casefold() != expected_sha256.casefold():
        raise ReviewDiffError(
            f"review diff digest mismatch: expected {expected_sha256}, observed {digest}"
        )
    return digest, len(body)


def _proxy_entries(root: Path, log_path: str | Path, wave_id: str) -> list[dict[str, Any]]:
    target = Path(log_path).expanduser()
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    if root not in target.parents:
        raise ReviewDiffError(f"proxy log must stay under repository root: {target}")
    if not target.is_file():
        raise ReviewDiffError(f"Codex proxy log missing: {target}")

    entries: list[dict[str, Any]] = []
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReviewDiffError(f"cannot read Codex proxy log {target}: {exc}") from exc
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewDiffError(f"invalid JSON in Codex proxy log at line {number}: {exc}") from exc
        if not isinstance(entry, dict):
            raise ReviewDiffError(f"invalid Codex proxy record at line {number}: expected an object")
        if entry.get("wave_id") == wave_id:
            entries.append(entry)
    if len(entries) != 2:
        raise ReviewDiffError(
            f"review wave {wave_id!r} must have exactly two proxy records; found {len(entries)}"
        )
    return entries


def verify_wave(
    *,
    root: str | Path,
    map_root: str | Path | None = None,
    proxy_log: str | Path = DEFAULT_PROXY_LOG,
    wave_id: str,
    expected_sha256: str,
    bound_card: str,
) -> tuple[str, tuple[str, str]]:
    """Verify the two successful, read-only Codex reviewers consumed one exact diff."""

    repo = Path(root).expanduser().resolve()
    if not repo.is_dir():
        raise ReviewDiffError(f"repository root does not exist: {repo}")
    if not wave_id.strip() or wave_id == "unavailable":
        raise ReviewDiffError("wave id must be explicit")
    if not bound_card.strip() or bound_card == "unavailable":
        raise ReviewDiffError("bound card must be explicit")
    if not SHA256_RE.fullmatch(expected_sha256):
        raise ReviewDiffError("expected review diff SHA-256 must be 64 hexadecimal characters")

    expected_digest = expected_sha256.casefold()
    try:
        shared_map_root = Path(map_root).expanduser().resolve() if map_root is not None else repo
        current_pair = resolve_pair(shared_map_root, "execucao")
    except ModelRoutingError as exc:
        raise ReviewDiffError(f"cannot verify reviewer model against the shared map: {exc}") from exc

    records = _proxy_entries(repo, proxy_log, wave_id)
    by_activity: dict[str, dict[str, Any]] = {}
    for entry in records:
        activity = entry.get("activity")
        if activity not in REVIEWERS:
            raise ReviewDiffError(
                f"review wave {wave_id!r} contains an unexpected activity: {activity!r}"
            )
        if activity in by_activity:
            raise ReviewDiffError(f"review wave {wave_id!r} contains duplicate {activity} records")
        by_activity[activity] = entry
    missing = [activity for activity in REVIEWERS if activity not in by_activity]
    if missing:
        raise ReviewDiffError(f"review wave {wave_id!r} is missing: {', '.join(missing)}")

    child_ids: list[str] = []
    for activity in REVIEWERS:
        entry = by_activity[activity]
        if entry.get("bound_card") != bound_card:
            raise ReviewDiffError(f"{activity} proxy record is not bound to card {bound_card}")
        if entry.get("band") != "execucao":
            raise ReviewDiffError(f"{activity} must use the execucao model band")
        if (entry.get("requested_model"), entry.get("requested_effort")) != (
            current_pair.slug,
            current_pair.effort,
        ):
            raise ReviewDiffError(
                f"{activity} requested pair does not match the current shared map: "
                f"expected {current_pair.slug}/{current_pair.effort}"
            )
        observed = (entry.get("observed_model"), entry.get("observed_effort"))
        if "unavailable" in observed:
            raise ReviewDiffError(f"{activity} observed model pair is unavailable")
        if observed != (current_pair.slug, current_pair.effort):
            raise ReviewDiffError(f"{activity} observed model pair differs from the shared map")
        if entry.get("status") != "completed" or entry.get("payload_returned") is not True:
            raise ReviewDiffError(f"{activity} did not complete with a returned payload")
        if entry.get("successful") is not True:
            raise ReviewDiffError(f"{activity} proxy record is not marked successful")
        if entry.get("sandbox_mode") != "read-only":
            raise ReviewDiffError(f"{activity} was not recorded with sandbox_mode=read-only")
        review_digest = entry.get("review_diff_sha256")
        if not isinstance(review_digest, str) or review_digest.casefold() != expected_digest:
            raise ReviewDiffError(f"{activity} did not review the expected diff SHA-256")
        child_id = entry.get("child_id")
        if not isinstance(child_id, str) or not child_id.strip() or child_id == "unavailable":
            raise ReviewDiffError(f"{activity} child id is unavailable")
        child_ids.append(child_id.strip())

    if child_ids[0] == child_ids[1]:
        raise ReviewDiffError("diff-reviewer and code-reviewer must be distinct child tasks")
    return expected_digest, (child_ids[0], child_ids[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    capture_parser = commands.add_parser("capture")
    capture_parser.add_argument("--root", type=Path, default=Path.cwd())
    capture_parser.add_argument("--base", default="HEAD", help="git diff base, e.g. HEAD or origin/develop...HEAD")
    capture_parser.add_argument("--output", type=Path, default=DEFAULT_DIFF)
    capture_parser.add_argument("--no-untracked", action="store_true")
    verify_parser = commands.add_parser("verify")
    verify_parser.add_argument("--path", type=Path, required=True)
    verify_parser.add_argument("--sha256", required=True)
    wave_parser = commands.add_parser("verify-wave")
    wave_parser.add_argument("--root", type=Path, default=Path.cwd())
    wave_parser.add_argument(
        "--map-root",
        type=Path,
        help="consumer root containing .cursor/model-map.yaml (defaults to --root)",
    )
    wave_parser.add_argument("--proxy-jsonl", type=Path, default=DEFAULT_PROXY_LOG)
    wave_parser.add_argument("--wave-id", required=True)
    wave_parser.add_argument("--sha256", required=True)
    wave_parser.add_argument("--bound-card", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "capture":
            path, digest, size = capture(
                args.root,
                base=args.base,
                include_untracked=not args.no_untracked,
                output=args.output,
            )
            print(f"review_diff_path: {path}")
            print(f"review_diff_sha256: {digest}")
            print(f"review_diff_bytes: {size}")
        elif args.action == "verify":
            digest, size = verify(args.path, args.sha256)
            print(f"review_diff_sha256: {digest}")
            print(f"review_diff_bytes: {size}")
        else:
            digest, child_ids = verify_wave(
                root=args.root,
                map_root=args.map_root,
                proxy_log=args.proxy_jsonl,
                wave_id=args.wave_id,
                expected_sha256=args.sha256,
                bound_card=args.bound_card,
            )
            print(f"review_wave_id: {args.wave_id}")
            print(f"review_diff_sha256: {digest}")
            print(f"reviewer_child_ids: {','.join(child_ids)}")
    except ReviewDiffError as exc:
        print(f"codex review interval error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
