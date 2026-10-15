"""Verify one Claude Code review wave: two read-only reviewers, one exact diff.

The diff itself is materialized and verified with `materialize_review_diff.py`
/ `codex_review.py capture|verify` (client neutral); this module only judges
the wave from sealed runtime evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from claude_evidence import READ_ONLY_TOOLS, RETURN_CHANNEL_TOOLS, EvidenceError, verify_proxy
from codex_review import REVIEWERS, SHA256_RE, ReviewDiffError
from model_selection import SelectionError, compare_wave, validate_capture

DEFAULT_PROXY_LOG = Path(".cursor/tmp/claude-child-proxies.jsonl")


def _proxy_entries(root: Path, log_path: str | Path, wave_id: str) -> list[dict[str, Any]]:
    target = Path(log_path).expanduser()
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    if root not in target.parents:
        raise ReviewDiffError(f"proxy log must stay under repository root: {target}")
    if not target.is_file():
        raise ReviewDiffError(f"Claude proxy log missing: {target}")
    entries = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReviewDiffError(f"invalid JSON in Claude proxy log at line {number}: {exc}") from exc
        if not isinstance(entry, dict):
            raise ReviewDiffError(f"invalid Claude proxy record at line {number}: expected an object")
        if entry.get("wave_id") == wave_id:
            entries.append(entry)
    if len(entries) != 2:
        raise ReviewDiffError(f"review wave {wave_id!r} must have exactly two proxy records; found {len(entries)}")
    return entries


def verify_wave(*, root, proxy_log=DEFAULT_PROXY_LOG, wave_id: str, expected_sha256: str, bound_card: str, runtime=None) -> tuple[str, tuple[str, str]]:
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
    by_activity: dict[str, dict[str, Any]] = {}
    for entry in _proxy_entries(repo, proxy_log, wave_id):
        activity = entry.get("activity")
        if activity not in REVIEWERS:
            raise ReviewDiffError(f"review wave {wave_id!r} contains an unexpected activity: {activity!r}")
        if activity in by_activity:
            raise ReviewDiffError(f"review wave {wave_id!r} contains duplicate {activity} records")
        by_activity[activity] = entry
    missing = [a for a in REVIEWERS if a not in by_activity]
    if missing:
        raise ReviewDiffError(f"review wave {wave_id!r} is missing: {', '.join(missing)}")

    child_ids: list[str] = []
    first_capture = None
    for activity in REVIEWERS:
        entry = by_activity[activity]
        try:
            birth = validate_capture(entry.get("selection_capture"), client="claude", band="execucao", role=activity)
            if first_capture is not None:
                compare_wave(first_capture, birth)
                if first_capture["attempt_id"] == birth["attempt_id"]:
                    raise SelectionError("reviewers must have distinct birth captures")
            first_capture = birth
        except SelectionError as exc:
            raise ReviewDiffError(f"{activity} invalid birth capture: {exc}") from exc
        selected = birth["selection"]
        if entry.get("client") != "claude":
            raise ReviewDiffError(f"{activity} proxy record is not a claude record")
        if entry.get("bound_card") != bound_card:
            raise ReviewDiffError(f"{activity} proxy record is not bound to card {bound_card}")
        if entry.get("band") != "execucao":
            raise ReviewDiffError(f"{activity} must use the execucao model band")
        if (entry.get("requested_model"), entry.get("requested_effort")) != (selected["model"], selected["effort"]):
            raise ReviewDiffError(f"{activity} requested pair does not match its birth capture: expected {selected['model']}/{selected['effort']}")
        observed = (entry.get("observed_model"), entry.get("observed_effort"))
        if "unavailable" in observed:
            raise ReviewDiffError(f"{activity} observed model pair is unavailable")
        if observed != (selected["model"], selected["effort"]):
            raise ReviewDiffError(f"{activity} observed model pair differs from its birth capture")
        if entry.get("status") != "completed" or entry.get("payload_returned") is not True:
            raise ReviewDiffError(f"{activity} did not complete with a returned payload")
        if entry.get("successful") is not True:
            raise ReviewDiffError(f"{activity} proxy record is not marked successful")
        if any(not isinstance(entry.get(k), str) or entry[k] in ("", "unavailable") for k in ("host", "host_version", "surface")):
            raise ReviewDiffError(f"{activity} host/version/surface evidence is unavailable")
        tools = entry.get("tools_used")
        if entry.get("read_only") is not True or not isinstance(tools, list) or not set(tools) <= (READ_ONLY_TOOLS | RETURN_CHANNEL_TOOLS):
            raise ReviewDiffError(f"{activity} used tools other than Read/Grep/Glob")
        review_digest = entry.get("review_diff_sha256")
        if not isinstance(review_digest, str) or review_digest.casefold() != expected_digest:
            raise ReviewDiffError(f"{activity} did not review the expected diff SHA-256")
        child_id = entry.get("child_id")
        if not isinstance(child_id, str) or not child_id.strip() or child_id == "unavailable":
            raise ReviewDiffError(f"{activity} child id is unavailable")
        child_ids.append(child_id.strip())
    if child_ids[0] == child_ids[1]:
        raise ReviewDiffError("diff-reviewer and code-reviewer must be distinct child tasks")

    parents = set()
    for activity in REVIEWERS:
        try:
            proof = verify_proxy(by_activity[activity], runtime=runtime)
        except EvidenceError as exc:
            raise ReviewDiffError(f"{activity} runtime provenance rejected: {exc}") from exc
        if proof["qualification"]:
            raise ReviewDiffError(f"{activity} qualification evidence cannot prove product review")
        if not proof["read_only"]:
            raise ReviewDiffError(f"{activity} used write-capable tools")
        parents.add((proof["parent_session"], proof["parent_message_id"]))
    if len(parents) != 1:
        raise ReviewDiffError("reviewers must be born in the same parent message")
    return expected_digest, (child_ids[0], child_ids[1])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    wave = commands.add_parser("verify-wave")
    wave.add_argument("--root", type=Path, default=Path.cwd())
    wave.add_argument("--proxy-jsonl", type=Path, default=DEFAULT_PROXY_LOG)
    wave.add_argument("--wave-id", required=True)
    wave.add_argument("--sha256", required=True)
    wave.add_argument("--bound-card", required=True)
    args = parser.parse_args(argv)
    try:
        digest, child_ids = verify_wave(root=args.root, proxy_log=args.proxy_jsonl, wave_id=args.wave_id, expected_sha256=args.sha256, bound_card=args.bound_card)
        print(f"review_wave_id: {args.wave_id}")
        print(f"review_diff_sha256: {digest}")
        print(f"reviewer_child_ids: {','.join(child_ids)}")
    except ReviewDiffError as exc:
        print(f"claude review interval error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
