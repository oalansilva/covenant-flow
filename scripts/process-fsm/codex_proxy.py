"""Append minimal Codex child-routing proxies without storing prompts/transcripts."""

from __future__ import annotations

import argparse
import json
import os
import sys
import fcntl
from datetime import datetime, timezone
from pathlib import Path

from codex_models import ModelRoutingError, pair_from_capture
from model_selection import load_capture, validate_capture
from codex_evidence import EvidenceError, collect, verify_evidence, verify_proxy


DEFAULT_PATH = Path(".cursor/tmp/codex-child-proxies.jsonl")
UNAVAILABLE = "unavailable"


class ProxyError(ValueError):
    """A proxy record is invalid or points outside the consumer repository."""


def record(
    *,
    repo_root: str | Path,
    map_root: str | Path | None = None,
    activity: str,
    band: str,
    requested_model: str,
    requested_effort: str,
    observed_model: str = UNAVAILABLE,
    observed_effort: str = UNAVAILABLE,
    host: str,
    host_version: str,
    status: str,
    payload_returned: bool,
    child_id: str = UNAVAILABLE,
    wave_id: str = UNAVAILABLE,
    sandbox_mode: str = UNAVAILABLE,
    bound_card: str = UNAVAILABLE,
    review_diff_sha256: str = UNAVAILABLE,
    reason: str = "",
    output: str | Path = DEFAULT_PATH,
    capture: dict | str | Path | None = None,
    runtime_evidence: str | Path | None = None,
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
        birth = validate_capture(birth, client="codex", band=band, role=activity)
        current_pair = pair_from_capture(birth, band)
    except ModelRoutingError as exc:
        birth = None
        map_reason = f"birth capture is unavailable: {exc}"
        requested_pair_is_current = False
    else:
        requested_pair_is_current = (
            requested_model == current_pair.slug and requested_effort == current_pair.effort
        )
        if not requested_pair_is_current:
            map_reason = f"requested pair does not match the captured {band} selection"

    successful = (
        runtime_evidence is not None
        and
        requested_pair_is_current
        and status == "completed"
        and payload_returned
        and host != UNAVAILABLE
        and host_version != UNAVAILABLE
        and observed_model != UNAVAILABLE
        and observed_effort != UNAVAILABLE
        and observed_model == requested_model
        and observed_effort == requested_effort
    )
    entry: dict[str, object] = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "bound_card": bound_card or UNAVAILABLE,
        "activity": activity,
        "band": band,
        "requested_model": requested_model or UNAVAILABLE,
        "requested_effort": requested_effort or UNAVAILABLE,
        "observed_model": observed_model or UNAVAILABLE,
        "observed_effort": observed_effort or UNAVAILABLE,
        "host": host,
        "host_version": host_version,
        "status": status,
        "payload_returned": bool(payload_returned),
        "successful": successful,
        "child_id": child_id or UNAVAILABLE,
        "wave_id": wave_id or UNAVAILABLE,
        "sandbox_mode": sandbox_mode or UNAVAILABLE,
        "review_diff_sha256": review_diff_sha256 or UNAVAILABLE,
        "selection_capture": birth,
    }
    final_reason = reason.strip() or (map_reason if not requested_pair_is_current else "")
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
                    # Keep the original immutable anchor for the single proxy.
                    # Its verifier rereads every current turn and accepted
                    # snapshot, so a new revision cannot erase prior evidence.
                    revision_fields = {"recorded_at", "runtime_evidence", "evidence_sha256"}
                    if {k:v for k,v in previous.items() if k not in revision_fields} != {k:v for k,v in entry.items() if k not in revision_fields}:
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--map-root",
        type=Path,
        default=None,
        help="deprecated consumer identifier; does not override machine selection",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--capture", required=True, type=Path, help="immutable birth capture, created before spawn")
    parser.add_argument("--activity", required=True)
    parser.add_argument("--band", required=True, choices=("juizo", "execucao"))
    parser.add_argument("--requested-model", default="")
    parser.add_argument("--requested-effort", default="")
    parser.add_argument("--observed-model", default=None)
    parser.add_argument("--observed-effort", default=None)
    parser.add_argument("--host", default=UNAVAILABLE)
    parser.add_argument("--host-version", default=UNAVAILABLE)
    parser.add_argument("--status", default="failed", choices=("completed", "failed", "interrupted"))
    parser.add_argument("--payload-returned", action="store_true")
    parser.add_argument("--child-id", default=UNAVAILABLE)
    parser.add_argument("--wave-id", default=UNAVAILABLE)
    parser.add_argument("--sandbox-mode", default=UNAVAILABLE)
    parser.add_argument("--bound-card", default=UNAVAILABLE)
    parser.add_argument("--review-diff-sha256", default=UNAVAILABLE)
    parser.add_argument("--reason", default="")
    parser.add_argument("--evidence", type=Path, help="verified automatic collector envelope; required for success")
    parser.add_argument("--birth", type=Path, help="automatically collect after native return (bounded flush)")
    parser.add_argument("--wait-seconds", type=float, default=5)
    args = parser.parse_args(argv)
    try:
        if args.birth:
            if args.evidence:
                raise ProxyError("choose birth collection or existing evidence")
            args.evidence = Path(collect(args.birth, wait_seconds=args.wait_seconds)["evidence_path"])
        if args.evidence is None:
            raise ProxyError("automatic evidence required; manual observed flags cannot prove runtime")
        if args.evidence:
            if args.observed_model is not None or args.observed_effort is not None:
                raise ProxyError("manual observed flags cannot accompany automatic evidence")
            proof = verify_evidence(args.evidence)
            args.observed_model = proof["turns"][-1]["observed"]["model"]
            args.observed_effort = proof["turns"][-1]["observed"]["reasoning_effort"]
            args.host, args.host_version = proof["host"], proof["host_version"]
            args.status, args.payload_returned = proof["status"], proof["payload_returned"]
            args.child_id = proof["child_thread"]
            args.sandbox_mode = proof["turns"][-1]["sandbox"]
            args.bound_card = proof["bound_card"]
            args.review_diff_sha256 = proof["review_diff_sha256"]
            args.wave_id = proof.get("wave_id", UNAVAILABLE)
            args.requested_model = args.requested_model or proof["requested"]["model"]
            args.requested_effort = args.requested_effort or proof["requested"]["reasoning_effort"]
        entry = record(
            repo_root=args.repo_root,
            map_root=args.map_root,
            output=args.output,
            activity=args.activity,
            band=args.band,
            requested_model=args.requested_model,
            requested_effort=args.requested_effort,
            observed_model=args.observed_model,
            observed_effort=args.observed_effort,
            host=args.host,
            host_version=args.host_version,
            status=args.status,
            payload_returned=args.payload_returned,
            child_id=args.child_id,
            wave_id=args.wave_id,
            sandbox_mode=args.sandbox_mode,
            bound_card=args.bound_card,
            review_diff_sha256=args.review_diff_sha256,
            reason=args.reason,
            capture=args.capture,
            runtime_evidence=args.evidence,
        )
    except (ProxyError, EvidenceError) as exc:
        print(f"codex proxy error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
