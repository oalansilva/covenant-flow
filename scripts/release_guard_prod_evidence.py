#!/usr/bin/env python3
"""Validate PROD_DEPLOY_EVIDENCE against overlay publish window (#968)."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]


def _normalize_unit(name: str) -> str:
    raw = name.strip()
    if not raw:
        return raw
    if not raw.endswith(".service"):
        return f"{raw}.service"
    return raw


def _parse_services_from_evidence(evidence: str) -> set[str]:
    match = re.search(r"(?:^|\s)services=([^ ]+)", evidence)
    if not match:
        return set()
    raw = match.group(1)
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return {_normalize_unit(p) for p in parts}


def _publish_window(prod_env: dict[str, Any]) -> list[str]:
    services = [_normalize_unit(str(s)) for s in (prod_env.get("services") or []) if str(s).strip()]
    oneshot_raw = prod_env.get("oneshot_services")
    if not oneshot_raw:
        return services
    oneshot = {_normalize_unit(str(s)) for s in oneshot_raw if str(s).strip()}
    return [s for s in services if s not in oneshot]


def _load_overlay_prod(overlay_path: Path) -> dict[str, Any] | None:
    if not overlay_path.is_file() or yaml is None:
        return None
    data = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
    environments = data.get("environments") or {}
    if not isinstance(environments, dict):
        return None
    prod = environments.get("prod")
    if not isinstance(prod, dict):
        return None
    return prod


def _evidence_commit_token(evidence: str) -> str:
    token = (evidence or "").strip().split(None, 1)[0] if evidence else ""
    return token


def _deploy_window_start(repo_root: Path, evidence: str) -> datetime | None:
    env_raw = os.environ.get("RELEASE_GUARD_DEPLOY_WINDOW_START", "").strip()
    if env_raw:
        try:
            parsed = datetime.fromisoformat(env_raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return None
    token = _evidence_commit_token(evidence)
    if not token:
        return None
    proc = subprocess.run(
        ["git", "show", "-s", "--format=%cI", token],
        cwd=repo_root,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _parse_systemd_timestamp(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text or text in ("n/a", "N/A"):
        return None
    # systemd: Wed 2026-09-16 12:34:56 UTC
    for fmt in (
        "%a %Y-%m-%d %H:%M:%S %Z",
        "%Y-%m-%d %H:%M:%S %Z",
    ):
        try:
            parsed = datetime.strptime(text, fmt)
            return parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _systemd_show(unit: str) -> dict[str, str]:
    fixture_raw = os.environ.get("RELEASE_GUARD_SYSTEMD_FIXTURES", "").strip()
    if fixture_raw:
        try:
            fixtures = json.loads(fixture_raw)
        except json.JSONDecodeError:
            fixtures = {}
        if isinstance(fixtures, dict):
            entry = fixtures.get(unit) or fixtures.get(_normalize_unit(unit))
            if isinstance(entry, dict):
                return {str(k): str(v) for k, v in entry.items()}
    if os.environ.get("RELEASE_GUARD_SKIP_SYSTEMD", "").strip() in ("1", "true", "yes"):
        return {}
    proc = subprocess.run(
        [
            "systemctl",
            "show",
            _normalize_unit(unit),
            "-p",
            "ActiveState",
            "-p",
            "ExecMainStartTimestamp",
            "--value",
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return {"ActiveState": "unknown", "ExecMainStartTimestamp": ""}
    lines = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    active = lines[0] if len(lines) > 0 else "unknown"
    started = lines[1] if len(lines) > 1 else ""
    return {"ActiveState": active, "ExecMainStartTimestamp": started}


def _health_ok(health_url: str) -> bool:
    mock = os.environ.get("RELEASE_GUARD_MOCK_HEALTH", "").strip().lower()
    if mock in ("ok", "1", "true", "yes"):
        return True
    if mock in ("fail", "0", "false", "no"):
        return False
    if not health_url.strip():
        return False
    proc = subprocess.run(
        ["curl", "-fsS", "--max-time", "15", health_url],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def validate_prod_deploy_evidence(
    *,
    repo_root: Path,
    overlay_path: Path,
    evidence: str,
    strict: bool,
) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    warnings: list[str] = []

    prod = _load_overlay_prod(overlay_path)
    if prod is None:
        return blockers, warnings

    window = _publish_window(prod)
    if not window:
        return blockers, warnings

    listed = _parse_services_from_evidence(evidence)
    if not listed and evidence.strip():
        msg = "PROD_DEPLOY_EVIDENCE missing services= list for overlay publish window"
        if strict:
            blockers.append(msg)
        else:
            warnings.append(msg)
        return blockers, warnings

    window_set = set(window)
    missing = sorted(window_set - listed)
    if missing:
        missing_display = ", ".join(missing)
        msg = (
            "PROD_DEPLOY_EVIDENCE services= omits overlay publish-window unit(s): "
            f"{missing_display}"
        )
        if strict:
            blockers.append(msg)
        else:
            warnings.append(msg)

    extra_oneshot = listed - window_set
    oneshot_declared = {
        _normalize_unit(str(s)) for s in (prod.get("oneshot_services") or []) if str(s).strip()
    }
    for unit in sorted(extra_oneshot):
        if unit in oneshot_declared:
            warnings.append(
                f"PROD_DEPLOY_EVIDENCE lists oneshot job {unit} (allowed warning, not required)"
            )
        else:
            warnings.append(f"PROD_DEPLOY_EVIDENCE lists extra service name: {unit}")

    if missing:
        return blockers, warnings

    if os.environ.get("RELEASE_GUARD_SKIP_SYSTEMD", "").strip() in ("1", "true", "yes"):
        return blockers, warnings

    release = {}
    if yaml is not None and overlay_path.is_file():
        data = yaml.safe_load(overlay_path.read_text(encoding="utf-8")) or {}
        release = data.get("release") or {}
    health_url = str(release.get("health_url") or "").strip()

    window_start = _deploy_window_start(repo_root, evidence)
    for unit in window:
        state = _systemd_show(unit)
        active = (state.get("ActiveState") or "unknown").strip().lower()
        if active in ("inactive", "failed", "dead"):
            if not _health_ok(health_url):
                msg = (
                    f"overlay publish-window unit {unit} is {active} and "
                    f"release.health_url did not respond: {health_url or '(empty)'}"
                )
                if strict:
                    blockers.append(msg)
                else:
                    warnings.append(msg)
            continue
        if active not in ("active", "activating", "reloading"):
            if active == "unknown":
                msg = (
                    f"cannot read systemd state for active overlay publish-window unit {unit}; "
                    "fail-closed for stale-process check"
                )
                if strict:
                    blockers.append(msg)
                else:
                    warnings.append(msg)
            continue
        if window_start is None:
            msg = (
                f"cannot resolve deploy window start for stale-process check on {unit}; "
                "set RELEASE_GUARD_DEPLOY_WINDOW_START or use a resolvable evidence commit"
            )
            if strict:
                blockers.append(msg)
            else:
                warnings.append(msg)
            continue
        started_raw = state.get("ExecMainStartTimestamp") or ""
        started = _parse_systemd_timestamp(started_raw)
        if started is None:
            msg = (
                f"cannot read ExecMainStartTimestamp for active unit {unit} "
                f"(got '{started_raw}'); fail-closed for stale-process check"
            )
            if strict:
                blockers.append(msg)
            else:
                warnings.append(msg)
            continue
        if started < window_start:
            msg = (
                f"active overlay publish-window unit {unit} started before this deploy window "
                f"({started_raw} < {window_start.isoformat()})"
            )
            if strict:
                blockers.append(msg)
            else:
                warnings.append(msg)

    return blockers, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PROD deploy evidence (#968)")
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--overlay-file", type=Path, default=None)
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--strict", choices=("0", "1"), default="1")
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    overlay_path = args.overlay_file or (repo_root / ".covenant-flow" / "overlay.yaml")
    strict = args.strict == "1"
    blockers, warnings = validate_prod_deploy_evidence(
        repo_root=repo_root,
        overlay_path=overlay_path,
        evidence=args.evidence,
        strict=strict,
    )
    for msg in warnings:
        print(f"WARN: {msg}")
    for msg in blockers:
        print(f"BLOCKER: {msg}")
    return 1 if blockers else 0


if __name__ == "__main__":
    sys.exit(main())
