from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from graphql_quota import (  # noqa: E402
    SOURCE_HEADERS,
    GraphQLQuotaError,
    cached_blocks_network,
    enforce_graphql_quota,
    format_header_diagnostic,
    ingest_rest_rate_limit,
    load_cache,
    parse_graphql_quota,
    parse_include_output,
    raise_if_cached_exhausted,
    rest_authorizes_graphql,
    write_cache,
)

G1_INCLUDE = """HTTP/2 200
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 2026-09-03T02:55:52Z
X-RateLimit-Resource: graphql

{"data":null,"errors":[{"type":"RATE_LIMIT","message":"API rate limit exceeded"}]}
"""
G2_INCLUDE = """HTTP/2 200
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1788399352
X-RateLimit-Resource: graphql

{"errors":[{"type":"RATE_LIMIT"}]}
"""
REST_5000 = {"resources": {"graphql": {"limit": 5000, "used": 0, "remaining": 5000, "reset": 1788399352}}}


@pytest.fixture
def quota_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "graphql-quota.json"
    monkeypatch.setenv("PROCESS_FSM_GRAPHQL_QUOTA_CACHE", str(path))
    return path


def test_g1_rate_limit_headers_iso(quota_cache: Path) -> None:
    quota = parse_include_output(G1_INCLUDE)
    assert quota.remaining == 0
    assert quota.reset_at == "2026-09-03T02:55:52Z"
    assert quota.rate_limited is True
    assert quota.source == SOURCE_HEADERS
    assert quota.http_status == 200
    with pytest.raises(GraphQLQuotaError) as excinfo:
        enforce_graphql_quota(quota)
    err = excinfo.value
    assert err.remaining == 0
    assert err.reset_at == "2026-09-03T02:55:52Z"


def test_g2_reset_epoch_becomes_iso(quota_cache: Path) -> None:
    quota = parse_include_output(G2_INCLUDE)
    assert quota.remaining == 0
    expected = datetime.fromtimestamp(1788399352, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert quota.reset_at == expected
    with pytest.raises(GraphQLQuotaError) as excinfo:
        enforce_graphql_quota(quota)
    assert excinfo.value.remaining == 0
    assert excinfo.value.reset_at == expected


def test_g3_successful_query_uses_rate_limit_field(quota_cache: Path) -> None:
    quota = parse_graphql_quota(
        headers={},
        body={"data": {"rateLimit": {"remaining": 12, "resetAt": "2026-09-03T02:55:52Z"}}},
        http_status=200,
    )
    assert quota.remaining == 12
    assert quota.rate_limited is False
    assert quota.source == "rateLimit-field"
    enforce_graphql_quota(quota)
    write_cache(quota)
    assert load_cache() is None


GH_DEBUG_DUMP = """* Request at 2026-09-03 02:54:00.000 +0000
* Request to https://api.github.com/graphql
> POST /graphql HTTP/1.1
> Host: api.github.com

* Request took 80.000ms
* Response from https://api.github.com/graphql
< HTTP/2.0 200 OK
< X-RateLimit-Remaining: 0
< X-RateLimit-Reset: 2026-09-03T02:55:52Z
< X-RateLimit-Resource: graphql

GraphQL: API rate limit exceeded for user ID 126212
"""


def test_g15_gh_debug_dump_parses_item_list_headers() -> None:
    """Live `gh project item-list` has no HTTP/2 block; GH_DEBUG=api does."""
    quota = parse_include_output(GH_DEBUG_DUMP)
    assert quota.remaining == 0
    assert quota.reset_at == "2026-09-03T02:55:52Z"
    assert quota.source == SOURCE_HEADERS
    assert quota.http_status == 200
    diag = format_header_diagnostic(GH_DEBUG_DUMP)
    assert diag is not None
    assert "remaining=0" in diag
    assert "2026-09-03T02:55:52Z" in diag
    assert format_header_diagnostic("GraphQL: API rate limit exceeded") is None


def test_g4_rest_remaining_5000_does_not_authorize_or_write_cache(quota_cache: Path) -> None:
    before = {"remaining": 0, "reset_at": "2026-09-03T02:55:52Z", "source": SOURCE_HEADERS}
    quota_cache.write_text(json.dumps(before) + "\n", encoding="utf-8")
    ingest_rest_rate_limit(REST_5000)
    assert rest_authorizes_graphql(REST_5000) is False
    assert json.loads(quota_cache.read_text(encoding="utf-8")) == before
    with pytest.raises(GraphQLQuotaError):
        enforce_graphql_quota(parse_include_output(G1_INCLUDE))


def test_g9_cache_skip_until_reset(quota_cache: Path) -> None:
    write_cache(
        parse_include_output(G1_INCLUDE),
    )
    now = datetime(2026, 9, 3, 1, 0, 0, tzinfo=timezone.utc)
    err = cached_blocks_network(now=now)
    assert err is not None
    assert err.remaining == 0
    assert err.reset_at == "2026-09-03T02:55:52Z"
    with pytest.raises(GraphQLQuotaError):
        raise_if_cached_exhausted(now=now)


def test_g10_cache_after_reset_allows_one_call(quota_cache: Path) -> None:
    write_cache(parse_include_output(G1_INCLUDE))
    now = datetime(2026, 9, 3, 3, 0, 0, tzinfo=timezone.utc)
    assert cached_blocks_network(now=now) is None
    raise_if_cached_exhausted(now=now)


def test_g13_evidence_script_uses_rest_comments() -> None:
    script = (REPO / "scripts" / "post-card-evidence-comment.sh").read_text(encoding="utf-8")
    assert "gh issue view --json comments" not in script
    for line in script.splitlines():
        if "gh issue view" in line:
            assert False, line
    assert "/issues/" in script and "/comments" in script
    assert "fail-closed" in script or "refusing to post" in script


def test_g14_skills_issue_rest_and_pontual_status() -> None:
    grill = (REPO / ".cursor" / "skills" / "grill-card" / "SKILL.md").read_text(encoding="utf-8")
    board = (REPO / ".cursor" / "skills" / "github-project-board" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    refs = (
        REPO / ".cursor" / "skills" / "github-project-board" / "references" / "project-board-commands.md"
    ).read_text(encoding="utf-8")
    kaizen = (REPO / ".cursor" / "skills" / "kaizen" / "SKILL.md").read_text(encoding="utf-8")
    for text, label in ((grill, "grill"), (board, "board"), (refs, "refs"), (kaizen, "kaizen")):
        for line in text.splitlines():
            if "gh issue view" in line:
                assert "MUST NOT" in line, (label, line)
    assert "gh issue edit" in grill
    assert "gh api" in grill and "issues" in grill
    combined_board = board + "\n" + refs
    assert "item-list" in combined_board
    assert "MUST NOT `gh project item-list` to operate one card" in combined_board or (
        "MUST NOT" in board and "item-list" in board and "one card" in board
    )
    assert "pontual" in board.lower() or "issue(number" in board
    assert "MUST NOT `gh project item-list`" in kaizen or (
        "/kaizen card" in kaizen and "item-list" in kaizen
    )


def test_g17_no_sleep_or_retry_loop() -> None:
    files = [
        ROOT / "guard.py",
        ROOT / "process_event.py",
        ROOT / "graphql_quota.py",
        REPO / "scripts" / "release-guard",
    ]
    for path in files:
        text = path.read_text(encoding="utf-8")
        if path.name == "release-guard":
            start = text.find("snapshot_fail_diagnose")
            end = text.find("\nensure_pr_snapshot")
            chunk = text[start:end] if start >= 0 else text
            assert "time.sleep" not in chunk
            assert "gh api rate_limit" not in chunk
            assert "GH_DEBUG=api" in chunk
            continue
        if path.name == "guard.py":
            start = text.find("def github_status_provider")
            chunk = text[start : start + 4000]
        elif path.name == "process_event.py":
            start = text.find("def _item_id_for_issue")
            chunk = text[start : start + 2500]
        else:
            chunk = text
        assert "time.sleep" not in chunk, path
        assert "for _ in range" not in chunk or path.name == "graphql_quota.py"


def test_g18_and_g6_6_harness_constraints() -> None:
    roots = [
        ROOT / "guard.py",
        ROOT / "process_event.py",
        ROOT / "paging.py",
        ROOT / "graphql_quota.py",
        REPO / "scripts" / "release-guard",
        REPO / "scripts" / "post-card-evidence-comment.sh",
    ]
    blob = "\n".join(path.read_text(encoding="utf-8") for path in roots)
    assert "time.sleep" not in blob
    assert "auto-dsh" not in blob
    assert "token swap" not in blob
    assert "dual-write" not in blob
    assert "GET /rate_limit" not in blob or "MUST NOT" in blob
    board = (REPO / ".cursor" / "skills" / "github-project-board" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Sem REST de coluna" in board or "MUST NOT inventar REST de coluna" in board or (
        "REST" in board and "coluna" in board
    )
