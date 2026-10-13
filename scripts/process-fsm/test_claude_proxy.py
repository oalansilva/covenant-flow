from __future__ import annotations

import json
from pathlib import Path

import pytest

import claude_evidence as ev
import claude_proxy
from claude_fixtures import SESSION, World
from model_proxy import evidence as model_evidence
from model_selection_fixtures import machine_models  # noqa: F401


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def completed(world, role="apply-coluna", **kw):
    cap, path, task, prepared = world.prepare(role)
    world.spawn(cap, task, **kw)
    return cap, path, prepared


def test_proxy_records_requested_and_observed_pair_surface_and_status(world, capsys):
    cap, path, prepared = completed(world)
    code = claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", "apply-coluna", "--band", "execucao", "--birth", prepared["birth"], "--wait-seconds", "0"])
    assert code == 0, capsys.readouterr()
    entry = json.loads(capsys.readouterr().out)
    assert entry["client"] == "claude" and entry["successful"] is True
    assert (entry["requested_model"], entry["requested_effort"]) == ("claude-sonnet-5-5", "high")
    assert (entry["observed_model"], entry["observed_effort"]) == ("claude-sonnet-5-5", "high")
    assert entry["host_version"] == "2.1.296" and entry["surface"] == "cli" and entry["status"] == "completed" and entry["payload_returned"]
    log = world.repo / ".cursor/tmp/claude-child-proxies.jsonl"
    assert len(log.read_text().splitlines()) == 1
    # idempotent per attempt: a second collection never adds a third entry
    assert claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", "apply-coluna", "--band", "execucao", "--birth", prepared["birth"], "--wait-seconds", "0"]) == 0
    assert len(log.read_text().splitlines()) == 1


def test_proxy_refuses_manual_observation_and_missing_evidence(world, capsys):
    cap, path, prepared = completed(world)
    assert claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", "apply-coluna", "--band", "execucao"]) == 2
    assert "automatic evidence required" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", "apply-coluna", "--band", "execucao", "--observed-model", "x"])


def test_manual_record_without_runtime_evidence_is_never_successful(world):
    cap, path, prepared = completed(world)
    entry = claude_proxy.record(repo_root=world.repo, activity="apply-coluna", band="execucao", requested_model="claude-sonnet-5-5", requested_effort="high",
                                observed_model="claude-sonnet-5-5", observed_effort="high", host="Claude Code", host_version="2.1.296",
                                status="completed", payload_returned=True, capture=path)
    assert entry["successful"] is False and "not authoritative" in entry["reason"]


def test_proxy_refuses_when_evidence_diverges(world, capsys):
    cap, path, prepared = completed(world, child_effort="low")
    assert claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", "apply-coluna", "--band", "execucao", "--birth", prepared["birth"], "--wait-seconds", "0"]) == 2
    assert not (world.repo / ".cursor/tmp/claude-child-proxies.jsonl").exists()


def test_model_proxy_evidence_claude_requires_runtime_envelope(world):
    cap, path, prepared = completed(world)
    facts = dict(capture=cap, observed={"model": "claude-sonnet-5-5", "effort": "high"}, host="Claude Code", host_version="2.1.296", status="completed", payload_returned=True)
    assert model_evidence(**facts)["successful"] is False  # configuration/claims are not observation
    envelope = world.collect(prepared["birth"])["evidence_path"]
    good = model_evidence(**facts, runtime_evidence=envelope)
    assert good["successful"] is True and good["surface"] == "cli" and good["requested"]["effort"] == "high"
    wrong = dict(facts, observed={"model": "claude-opus-5-5", "effort": "high"})
    assert model_evidence(**wrong, runtime_evidence=envelope)["successful"] is False
    assert model_evidence(**dict(facts, observed={}), runtime_evidence=envelope)["successful"] is False
