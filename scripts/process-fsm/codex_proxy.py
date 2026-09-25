"""Append minimal Codex child-routing proxies without storing prompts/transcripts."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from codex_models import ModelRoutingError, resolve_pair


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
    map_directory = root if map_root is None else Path(map_root).expanduser().resolve()
    map_reason = ""
    try:
        current_pair = resolve_pair(map_directory, band)
    except ModelRoutingError as exc:
        map_reason = f"current shared-map pair is unavailable: {exc}"
        requested_pair_is_current = False
    else:
        requested_pair_is_current = (
            requested_model == current_pair.slug and requested_effort == current_pair.effort
        )
        if not requested_pair_is_current:
            map_reason = f"requested pair does not match the current {band} shared-map pair"

    successful = (
        requested_pair_is_current
        and status == "completed"
        and payload_returned
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
    }
    final_reason = reason.strip() or (map_reason if not requested_pair_is_current else "")
    if final_reason:
        entry["reason"] = final_reason
    encoded = (json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
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
        help="shared model-map root; defaults to --repo-root",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--activity", required=True)
    parser.add_argument("--band", required=True, choices=("juizo", "execucao"))
    parser.add_argument("--requested-model", default="")
    parser.add_argument("--requested-effort", default="")
    parser.add_argument("--observed-model", default=UNAVAILABLE)
    parser.add_argument("--observed-effort", default=UNAVAILABLE)
    parser.add_argument("--host", required=True)
    parser.add_argument("--host-version", required=True)
    parser.add_argument("--status", required=True, choices=("completed", "failed", "interrupted"))
    parser.add_argument("--payload-returned", action="store_true")
    parser.add_argument("--child-id", default=UNAVAILABLE)
    parser.add_argument("--wave-id", default=UNAVAILABLE)
    parser.add_argument("--sandbox-mode", default=UNAVAILABLE)
    parser.add_argument("--bound-card", default=UNAVAILABLE)
    parser.add_argument("--review-diff-sha256", default=UNAVAILABLE)
    parser.add_argument("--reason", default="")
    args = parser.parse_args(argv)
    try:
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
        )
    except ProxyError as exc:
        print(f"codex proxy error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(entry, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
