from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path
import pytest
import yaml
from model_selection_fixtures import machine_models
from model_selection import resolve, save_capture
from codex_proxy import ProxyError, record


def kwargs(root, role="code-reviewer", band="execucao"):
    cap = resolve("codex", band, role=role)
    selection = cap["selection"]
    return dict(repo_root=root, activity=role, band=band, capture=cap,
                requested_model=selection["model"], requested_effort=selection["effort"],
                observed_model=selection["model"], observed_effort=selection["effort"],
                host="Codex CLI", host_version="0.162.0", status="completed", payload_returned=True)


def test_proxy_uses_birth_after_edit_and_separates_facts(tmp_path, machine_models):
    data = kwargs(tmp_path)
    doc = yaml.safe_load(machine_models.read_text())
    doc["clients"]["codex"]["execucao"].update(model="gpt-6.1-sol", effort="high")
    machine_models.write_text(yaml.safe_dump(doc))
    entry = record(**data, output=".cursor/tmp/proxies.jsonl")
    assert entry["successful"]
    assert entry["requested_model"] == entry["observed_model"] == "gpt-6-luna"
    assert entry["selection_capture"] == data["capture"]
    assert "prompt" not in entry and "transcript" not in entry


@pytest.mark.parametrize("change", [dict(payload_returned=False), dict(status="failed"), dict(observed_model="unavailable"), dict(observed_effort="unavailable"), dict(observed_model="different"), dict(observed_effort="high"), dict(host_version="unavailable"), dict(capture=None), dict(band="juizo")])
def test_incomplete_mismatched_or_wrong_role_proxies_do_not_succeed(tmp_path, change):
    data = kwargs(tmp_path); data.update(change)
    assert not record(**data)["successful"]


@pytest.mark.parametrize("output", ["../escape.jsonl", "/tmp/escape.jsonl"])
def test_output_cannot_escape_repository(tmp_path, output):
    with pytest.raises(ProxyError): record(**kwargs(tmp_path), output=output)


def test_invalid_activity_status_and_missing_repo_are_visible(tmp_path):
    data = kwargs(tmp_path); data["status"] = "running"
    with pytest.raises(ProxyError): record(**data)
    data["status"] = "completed"; data["activity"] = ""
    with pytest.raises(ProxyError): record(**data)
    data = kwargs(tmp_path); data["repo_root"] = tmp_path / "missing"
    with pytest.raises(ProxyError): record(**data)


def test_proxy_cli_requires_real_birth_file_and_does_not_read_legacy_root(tmp_path):
    cap = tmp_path / "birth.json"; save_capture(cap, resolve("codex", "execucao", role="code-reviewer"))
    script = Path(__file__).with_name("codex_proxy.py")
    argv = [sys.executable, str(script), "--repo-root", str(tmp_path), "--map-root", str(tmp_path / "absent"),
            "--capture", str(cap), "--activity", "code-reviewer", "--band", "execucao",
            "--requested-model", "gpt-6-luna", "--requested-effort", "max", "--observed-model", "gpt-6-luna",
            "--observed-effort", "max", "--host", "Codex", "--host-version", "0.162.0", "--status", "completed", "--payload-returned"]
    result = subprocess.run(argv, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["successful"]
    assert not (tmp_path / "absent").exists()
