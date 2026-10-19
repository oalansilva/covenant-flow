"""Append minimal Claude Code child-routing proxies without storing prompts/transcripts."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from claude_evidence import EvidenceError, collect, observed_pair, verify_evidence, verify_proxy
from model_selection import SelectionError, load_capture, validate_capture

DEFAULT_PATH = Path(".cursor/tmp/claude-child-proxies.jsonl")
UNAVAILABLE = "unavailable"


class ProxyError(ValueError):
    """A proxy record is invalid or points outside the consumer repository."""


def record(
    *,
    repo_root: str | Path,
    activity: str,
    band: str,
    requested_model: str,
    requested_effort: str,
    observed_model: str = UNAVAILABLE,
    observed_effort: str = UNAVAILABLE,
    host: str,
    host_version: str,
    surface: str = UNAVAILABLE,
    status: str,
    payload_returned: bool,
    child_id: str = UNAVAILABLE,
    wave_id: str = UNAVAILABLE,
    tools_used: list[str] | None = None,
    read_only: bool = False,
    bound_card: str = UNAVAILABLE,
    review_diff_sha256: str = UNAVAILABLE,
    reason: str = "",
    output: str | Path = DEFAULT_PATH,
    capture: dict | str | Path | None = None,
    runtime_evidence: str | Path | None = None,
    desktop_app_version: str = UNAVAILABLE,
    ssh: bool = False,
) -> dict[str, object]:
    root = Path(repo_root).expanduser().resolve()
    if not root.is_dir():
        raise ProxyError(f"repository root does not exist: {root}")
    if not activity.strip() or not host.strip() or not host_version.strip():
        raise ProxyError("activity, host, and host_version are required")
    if band not in {"juizo", "execucao"}:
        raise ProxyError(f"invalid model band: {band!r}")
    if status not in {"completed", "failed", "interrupted"}:
        raise ProxyError(f"invalid host status: {status!r}")
    target = Path(output).expanduser()
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    if root not in target.parents:
        raise ProxyError(f"proxy output must stay under repository root: {target}")
    map_reason = ""
    try:
        birth = load_capture(capture) if isinstance(capture, (str, Path)) else capture
        birth = validate_capture(birth, client="claude", band=band, role=activity)
        selected = birth["selection"]
        requested_is_captured = (requested_model, requested_effort) == (selected["model"], selected["effort"])
        if not requested_is_captured:
            map_reason = f"requested pair does not match the captured {band} selection"
    except SelectionError as exc:
        birth = None
        requested_is_captured = False
        map_reason = f"birth capture is unavailable: {exc}"

    successful = (
        runtime_evidence is not None
        and requested_is_captured
        and status == "completed"
        and payload_returned
        and UNAVAILABLE not in (host, host_version, observed_model, observed_effort)
        and (observed_model, observed_effort) == (requested_model, requested_effort)
    )
    entry: dict[str, object] = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "bound_card": bound_card or UNAVAILABLE,
        "client": "claude",
        "activity": activity,
        "band": band,
        "requested_model": requested_model or UNAVAILABLE,
        "requested_effort": requested_effort or UNAVAILABLE,
        "observed_model": observed_model or UNAVAILABLE,
        "observed_effort": observed_effort or UNAVAILABLE,
        "host": host,
        "host_version": host_version,
        "surface": surface or UNAVAILABLE,
        "desktop_app_version": desktop_app_version or UNAVAILABLE,
        "ssh": bool(ssh),
        "status": status,
        "payload_returned": bool(payload_returned),
        "successful": successful,
        "child_id": child_id or UNAVAILABLE,
        "wave_id": wave_id or UNAVAILABLE,
        "tools_used": list(tools_used or []),
        "read_only": bool(read_only),
        "review_diff_sha256": review_diff_sha256 or UNAVAILABLE,
        "selection_capture": birth,
    }
    final_reason = reason.strip() or map_reason
    if final_reason:
        entry["reason"] = final_reason
    if runtime_evidence is not None:
        entry["runtime_evidence"] = str(Path(runtime_evidence).resolve())
        try:
            proof = verify_proxy(entry)
            if Path(proof["root"]).resolve() != root:
                raise EvidenceError("worktree_mismatch", "proxy output repository differs from birth")
        except EvidenceError as exc:
            raise ProxyError(str(exc)) from exc
        entry["attempt_id"] = proof["attempt_id"]
        entry["evidence_sha256"] = proof["integrity_sha256"]
    else:
        entry["reason"] = "legacy/manual metadata is not authoritative runtime evidence"
    encoded = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        if runtime_evidence and target.exists():
            for line in target.read_text().splitlines():
                previous = json.loads(line)
                if previous.get("attempt_id") == entry["attempt_id"]:
                    # One immutable proxy per attempt: its verifier rereads every turn.
                    revision_fields = {"recorded_at", "runtime_evidence", "evidence_sha256"}
                    if {k: v for k, v in previous.items() if k not in revision_fields} != {k: v for k, v in entry.items() if k not in revision_fields}:
                        raise ProxyError("attempt conflict: existing proxy preserved")
                    try:
                        verify_proxy(previous)
                    except EvidenceError as exc:
                        raise ProxyError(str(exc)) from exc
                    return previous
        os.write(descriptor, encoded)
    finally:
        os.close(descriptor)
    return entry


def handoff_line(entry: dict, gate: str | None = None) -> str:
    """One handoff line per child, taken from the proxy entry and never from the request (design 6).

    Client, surface (with the host version and, for the desktop app, its version), the model/effort the transcript
    showed, and the status. When the evidence is missing or diverges the line says which gate fails.
    """

    versions = f"host {entry.get('host_version', UNAVAILABLE)}"
    if entry.get("desktop_app_version") not in (None, UNAVAILABLE):
        versions += f", app {entry['desktop_app_version']}"
    line = (
        f"{entry.get('activity', UNAVAILABLE)} {entry.get('bound_card', UNAVAILABLE)}: client {entry.get('client', 'claude')}, "
        f"surface {entry.get('surface', UNAVAILABLE)} ({versions}), "
        f"observed {entry.get('observed_model', UNAVAILABLE)}/{entry.get('observed_effort', UNAVAILABLE)} "
        f"(requested {entry.get('requested_model', UNAVAILABLE)}/{entry.get('requested_effort', UNAVAILABLE)}), status {entry.get('status', UNAVAILABLE)}"
    )
    if not entry.get("successful"):
        reason = str(entry.get("reason") or entry.get("status") or "evidence missing or divergent")
        line += f"; the gate that requires this evidence ({gate or 'next gate'}) fails: {reason}"
    return line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--capture", required=True, type=Path, help="immutable birth capture, created before spawn")
    parser.add_argument("--activity", required=True)
    parser.add_argument("--band", required=True, choices=("juizo", "execucao"))
    parser.add_argument("--reason", default="")
    parser.add_argument("--evidence", type=Path, help="verified collector envelope; required for success")
    parser.add_argument("--birth", type=Path, help="collect automatically after the native return (bounded flush)")
    parser.add_argument("--wait-seconds", type=float, default=5)
    parser.add_argument("--handoff", action="store_true", help="print the one-line handoff (client, surface, observed pair, status) instead of the JSON entry")
    parser.add_argument("--gate", default=None, help="with --handoff: the gate named when the evidence is missing or diverges")
    args = parser.parse_args(argv)
    try:
        if args.birth:
            if args.evidence:
                raise ProxyError("choose birth collection or existing evidence")
            args.evidence = Path(collect(args.birth, wait_seconds=args.wait_seconds)["evidence_path"])
        if args.evidence is None:
            raise ProxyError("automatic evidence required; manual observed flags cannot prove runtime")
        proof = verify_evidence(args.evidence)
        last = observed_pair(proof)
        entry = record(
            repo_root=args.repo_root,
            output=args.output,
            activity=args.activity,
            band=args.band,
            requested_model=proof["requested"]["model"],
            requested_effort=proof["requested"]["effort"],
            observed_model=last["model"],
            observed_effort=last["effort"],
            host=proof["host"],
            host_version=proof["host_version"],
            surface=proof["surface"],
            status=proof["status"],
            payload_returned=proof["payload_returned"],
            child_id=proof["child_agent_id"],
            wave_id=proof.get("wave_id", UNAVAILABLE),
            tools_used=proof["tools_used"],
            read_only=proof["read_only"],
            bound_card=proof["bound_card"],
            review_diff_sha256=proof["review_diff_sha256"],
            reason=args.reason,
            capture=args.capture,
            runtime_evidence=args.evidence,
            desktop_app_version=proof.get("desktop_app_version", UNAVAILABLE),
            ssh=bool(proof.get("ssh", False)),
        )
    except (ProxyError, EvidenceError) as exc:
        print(f"claude proxy error: {exc}", file=sys.stderr)
        return 2
    print(handoff_line(entry, args.gate) if args.handoff else json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
