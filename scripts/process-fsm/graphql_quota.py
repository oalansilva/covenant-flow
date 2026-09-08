"""GraphQL quota from response headers. REST GET /rate_limit MUST NOT authorize GraphQL."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SOURCE_HEADERS = "graphql-headers"
SOURCE_FIELD = "rateLimit-field"
CACHE_ENV = "PROCESS_FSM_GRAPHQL_QUOTA_CACHE"
NOW_ENV = "PROCESS_FSM_GRAPHQL_QUOTA_NOW"


class GraphQLQuotaError(Exception):
    """GraphQL remaining is 0 or the body is RATE_LIMIT. Fail immediately with reset."""

    def __init__(self, remaining: int, reset_at: str | None = None) -> None:
        self.remaining = remaining
        self.reset_at = reset_at or ""
        super().__init__(
            f"GraphQL quota remaining={self.remaining} reset_at={self.reset_at}"
        )


@dataclass
class GraphQLQuota:
    remaining: int | None = None
    reset_at: str | None = None
    rate_limited: bool = False
    source: str | None = None
    http_status: int | None = None
    body: dict[str, Any] | None = None


def _clock(now: datetime | None = None) -> datetime:
    if now is not None:
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)
    raw = os.environ.get(NOW_ENV)
    if raw:
        parsed = _parse_iso(raw)
        if parsed is not None:
            return parsed
    return datetime.now(timezone.utc)


def reset_to_iso(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        ts = int(raw)
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = str(raw).strip()
    if not text:
        return None
    if text.isdigit():
        return datetime.fromtimestamp(int(text), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    return _format_iso(_parse_iso(text))


def _parse_iso(text: str) -> datetime | None:
    token = text.strip()
    if token.endswith("Z"):
        token = token[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(token)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _format_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _header_map(headers: Mapping[str, str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not headers:
        return out
    for key, value in headers.items():
        out[str(key).lower()] = str(value).strip()
    return out


def _http_candidate(line: str) -> str:
    """Strip GH_DEBUG `api` prefixes (`< `, `> `, `* `) so HTTP dumps parse."""
    text = line.lstrip("\t ")
    if text.startswith("< ") or text.startswith("> "):
        return text[2:]
    return text


def split_include_output(raw: str) -> tuple[int | None, dict[str, str], str]:
    """Split `gh api --include` or `GH_DEBUG=api` dump into HTTP status, headers, body.

    Last HTTP response wins (debug traces may include the request line too).
    """
    text = (raw or "").replace("\r\n", "\n")
    if not text.strip():
        return None, {}, ""
    lines = text.split("\n")
    last: tuple[int | None, dict[str, str], int] | None = None
    idx = 0
    while idx < len(lines):
        candidate = _http_candidate(lines[idx])
        if candidate.upper().startswith("HTTP/"):
            parts = candidate.split()
            http_status = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
            headers: dict[str, str] = {}
            idx += 1
            while idx < len(lines):
                raw_line = lines[idx]
                hline = _http_candidate(raw_line)
                if not hline.strip():
                    idx += 1
                    break
                if hline.startswith("* ") or hline.startswith("*"):
                    break
                if hline.upper().startswith("HTTP/"):
                    break
                if ":" in hline:
                    name, value = hline.split(":", 1)
                    headers[name.strip().lower()] = value.strip()
                    idx += 1
                    continue
                break
            last = (http_status, headers, idx)
            continue
        idx += 1
    if last is not None:
        http_status, headers, body_idx = last
        return http_status, headers, "\n".join(lines[body_idx:])
    return None, {}, text


def _parse_body(raw: str | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, Mapping):
        return dict(raw)
    text = str(raw).strip()
    if not text:
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None
        else:
            return None
    return data if isinstance(data, dict) else None


def _rate_limited(body: Mapping[str, Any] | None) -> bool:
    if not body:
        return False
    errors = body.get("errors")
    if not isinstance(errors, list):
        return False
    return any(isinstance(item, dict) and item.get("type") == "RATE_LIMIT" for item in errors)


def parse_graphql_quota(
    *,
    headers: Mapping[str, str] | None = None,
    body: str | Mapping[str, Any] | None = None,
    http_status: int | None = None,
) -> GraphQLQuota:
    parsed_body = _parse_body(body)
    quota = GraphQLQuota(http_status=http_status, body=parsed_body)
    quota.rate_limited = _rate_limited(parsed_body)
    header_map = _header_map(headers)
    resource = header_map.get("x-ratelimit-resource")
    headers_ok = resource in (None, "", "graphql")
    remaining_raw = header_map.get("x-ratelimit-remaining") if headers_ok else None
    reset_raw = header_map.get("x-ratelimit-reset") if headers_ok else None
    if remaining_raw is not None and remaining_raw != "":
        try:
            quota.remaining = int(remaining_raw)
            quota.source = SOURCE_HEADERS
        except ValueError:
            quota.remaining = None
    if reset_raw:
        quota.reset_at = reset_to_iso(reset_raw)
        if quota.source is None and headers_ok:
            quota.source = SOURCE_HEADERS
    if quota.rate_limited and quota.remaining is None:
        quota.remaining = 0
    query_ok = (
        not quota.rate_limited
        and isinstance(parsed_body, dict)
        and isinstance(parsed_body.get("data"), dict)
        and parsed_body.get("data")
    )
    if query_ok and quota.source != SOURCE_HEADERS:
        rate_limit = (parsed_body.get("data") or {}).get("rateLimit")
        if isinstance(rate_limit, dict):
            rem = rate_limit.get("remaining")
            if isinstance(rem, (int, float)) and not isinstance(rem, bool):
                quota.remaining = int(rem)
                quota.source = SOURCE_FIELD
            reset_at = rate_limit.get("resetAt") or rate_limit.get("reset_at")
            iso = reset_to_iso(reset_at)
            if iso:
                quota.reset_at = iso
                if quota.source is None:
                    quota.source = SOURCE_FIELD
    return quota


def parse_include_output(raw: str) -> GraphQLQuota:
    http_status, headers, body = split_include_output(raw or "")
    return parse_graphql_quota(headers=headers, body=body, http_status=http_status)


def enforce_graphql_quota(quota: GraphQLQuota) -> GraphQLQuota:
    exhausted = quota.rate_limited or (
        quota.remaining is not None and quota.remaining <= 0
    )
    if exhausted:
        raise GraphQLQuotaError(
            quota.remaining if quota.remaining is not None else 0,
            quota.reset_at,
        )
    return quota


def cache_path() -> Path:
    env = os.environ.get(CACHE_ENV)
    if env:
        return Path(env)
    return Path(tempfile.gettempdir()) / f"criptofarol-graphql-quota-{os.getuid()}.json"


def load_cache(path: Path | None = None) -> dict[str, Any] | None:
    target = path if path is not None else cache_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def write_cache(quota: GraphQLQuota, path: Path | None = None) -> None:
    if quota.source != SOURCE_HEADERS or quota.remaining is None:
        return
    target = path if path is not None else cache_path()
    payload = {
        "remaining": quota.remaining,
        "reset_at": quota.reset_at,
        "source": SOURCE_HEADERS,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=True) + "\n", encoding="utf-8")
    tmp.replace(target)


def ingest_rest_rate_limit(_payload: Mapping[str, Any] | None = None) -> None:
    """REST GET /rate_limit MUST NOT write the GraphQL quota cache."""
    return None


def rest_authorizes_graphql(_payload: Mapping[str, Any] | None = None) -> bool:
    """REST resources.graphql.remaining, including 5000, MUST NOT authorize GraphQL."""
    return False


def cached_blocks_network(*, now: datetime | None = None) -> GraphQLQuotaError | None:
    data = load_cache()
    if not data or data.get("source") != SOURCE_HEADERS:
        return None
    remaining = data.get("remaining")
    if remaining != 0:
        return None
    reset_at = data.get("reset_at")
    iso = reset_to_iso(reset_at) if reset_at else None
    if iso is None:
        return None
    reset_dt = _parse_iso(iso)
    if reset_dt is None:
        return None
    if _clock(now) < reset_dt:
        return GraphQLQuotaError(0, iso)
    return None


def raise_if_cached_exhausted(*, now: datetime | None = None) -> None:
    err = cached_blocks_network(now=now)
    if err is not None:
        raise err


def format_header_diagnostic(raw: str) -> str | None:
    quota = parse_include_output(raw)
    if quota.source != SOURCE_HEADERS or quota.remaining is None:
        return None
    return f"remaining={quota.remaining} reset={quota.reset_at or ''}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="graphql_quota")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args(argv)
    if args.diagnose:
        raw = sys_stdin()
        text = format_header_diagnostic(raw)
        if text:
            print(text)
        return 0
    return 0


def sys_stdin() -> str:
    import sys

    return sys.stdin.read()


if __name__ == "__main__":
    raise SystemExit(main())
