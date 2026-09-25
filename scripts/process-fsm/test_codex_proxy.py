from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from codex_proxy import ProxyError, record  # noqa: E402


def _write_map(root: Path, *, forbidden: list[str] | None = None) -> None:
    path = root / ".cursor" / "model-map.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "juizo": {"codex": {"label": "GPT-6 Sol", "slug": "gpt-6-sol", "effort": "high"}},
        "execucao": {"codex": {"label": "GPT-6 Luna", "slug": "gpt-6-luna", "effort": "max"}},
        "forbid": forbidden if forbidden is not None else ["composer-2.5-fast", "inherit"],
    }
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")


def test_proxy_records_requested_and_observed_pairs_without_prompt_content(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_map(root)
    path = root / ".cursor" / "tmp" / "proxies.jsonl"

    entry = record(
        repo_root=root,
        activity="diff-reviewer",
        band="juizo",
        requested_model="gpt-6-sol",
        requested_effort="high",
        observed_model="gpt-6-sol",
        observed_effort="high",
        host="Codex CLI",
        host_version="0.156.1",
        status="completed",
        payload_returned=True,
        bound_card="1042",
        review_diff_sha256="a" * 64,
        output=path,
    )

    persisted = json.loads(path.read_text(encoding="utf-8"))
    assert entry["successful"] is True
    assert persisted["requested_model"] == persisted["observed_model"] == "gpt-6-sol"
    assert persisted["requested_effort"] == persisted["observed_effort"] == "high"
    assert persisted["review_diff_sha256"] == "a" * 64
    assert "prompt" not in persisted and "transcript" not in persisted


def test_completed_without_payload_is_not_recorded_as_success_and_observed_can_be_unavailable(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_map(root)

    entry = record(
        repo_root=root,
        activity="apply-coluna",
        band="execucao",
        requested_model="gpt-6-luna",
        requested_effort="max",
        host="Codex CLI",
        host_version="0.156.1",
        status="completed",
        payload_returned=False,
        output=".cursor/tmp/proxies.jsonl",
    )

    assert entry["observed_model"] == "unavailable"
    assert entry["observed_effort"] == "unavailable"
    assert entry["successful"] is False


def test_completed_with_payload_but_unavailable_observation_is_not_success(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_map(root)

    entry = record(
        repo_root=root,
        activity="diff-reviewer",
        band="execucao",
        requested_model="gpt-6-luna",
        requested_effort="max",
        host="Codex CLI",
        host_version="0.156.1",
        status="completed",
        payload_returned=True,
        output=".cursor/tmp/proxies.jsonl",
    )

    assert entry["observed_model"] == "unavailable"
    assert entry["observed_effort"] == "unavailable"
    assert entry["successful"] is False


def test_completed_with_wrong_observed_pair_is_not_success(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_map(root)
    entry = record(
        repo_root=root,
        activity="apply-coluna",
        band="execucao",
        requested_model="gpt-6-luna",
        requested_effort="max",
        observed_model="gpt-6-luna",
        observed_effort="high",
        host="Codex CLI",
        host_version="0.156.1",
        status="completed",
        payload_returned=True,
        output=".cursor/tmp/proxies.jsonl",
    )
    assert entry["successful"] is False


def test_proxy_refuses_escape_and_invalid_status(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    kwargs = {
        "repo_root": root,
        "activity": "code-reviewer",
        "band": "juizo",
        "requested_model": "gpt-6-sol",
        "requested_effort": "high",
        "host": "Codex CLI",
        "host_version": "0.156.1",
        "status": "failed",
        "payload_returned": False,
    }

    with pytest.raises(ProxyError, match="stay under repository root"):
        record(**kwargs, output=tmp_path / "outside.jsonl")
    with pytest.raises(ProxyError, match="invalid host status"):
        record(**{**kwargs, "status": "completed-without-result"})


def test_proxy_does_not_mark_obsolete_matching_pair_successful(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_map(root)

    entry = record(
        repo_root=root,
        activity="code-reviewer",
        band="execucao",
        requested_model="gpt-6-luna-v1",
        requested_effort="max",
        observed_model="gpt-6-luna-v1",
        observed_effort="max",
        host="Codex CLI",
        host_version="0.156.1",
        status="completed",
        payload_returned=True,
        output=".cursor/tmp/proxies.jsonl",
    )

    assert entry["successful"] is False
    assert "does not match the current execucao shared-map pair" in entry["reason"]


def test_proxy_does_not_mark_map_pair_successful_when_it_is_forbidden(tmp_path: Path):
    root = tmp_path / "repo"
    root.mkdir()
    _write_map(root, forbidden=["composer-2.5-fast", "gpt-6-luna"])

    entry = record(
        repo_root=root,
        activity="code-reviewer",
        band="execucao",
        requested_model="gpt-6-luna",
        requested_effort="max",
        observed_model="gpt-6-luna",
        observed_effort="max",
        host="Codex CLI",
        host_version="0.156.1",
        status="completed",
        payload_returned=True,
        output=".cursor/tmp/proxies.jsonl",
    )

    assert entry["successful"] is False
    assert "is forbidden" in entry["reason"]


def test_cli_uses_separate_consumer_map_and_keeps_proxy_output_in_repo(tmp_path: Path):
    product = tmp_path / "product"
    consumer = tmp_path / "consumer"
    product.mkdir()
    consumer.mkdir()
    _write_map(consumer)
    map_path = consumer / ".cursor" / "model-map.yaml"
    map_before = map_path.read_bytes()
    output = Path(".cursor/tmp/proxies.jsonl")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "codex_proxy.py"),
            "--repo-root",
            str(product),
            "--map-root",
            str(consumer),
            "--output",
            str(output),
            "--activity",
            "code-reviewer",
            "--band",
            "execucao",
            "--requested-model",
            "gpt-6-luna",
            "--requested-effort",
            "max",
            "--observed-model",
            "gpt-6-luna",
            "--observed-effort",
            "max",
            "--host",
            "Codex CLI",
            "--host-version",
            "0.156.1",
            "--status",
            "completed",
            "--payload-returned",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    entry = json.loads(result.stdout)
    proxy_path = product / output
    assert entry["successful"] is True
    assert proxy_path.is_file()
    assert json.loads(proxy_path.read_text(encoding="utf-8"))["successful"] is True
    assert map_path.read_bytes() == map_before
    assert not (consumer / output).exists()
