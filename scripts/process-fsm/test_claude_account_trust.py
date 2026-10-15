"""`claude_trust` / `claude_adapter trust` on an account pin: the shim owns the review, the adapter only delegates."""
from __future__ import annotations

import json

import pytest

import cf_shim
import claude_adapter
import claude_trust
from shim_fixtures import install_account, isolate_account, make_consumer

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture
def account(monkeypatch, tmp_path):
    home = isolate_account(monkeypatch, tmp_path)
    for name in ("CF_SHIM_ACTIVE", "CF_SHIM_ADAPTER_DIGEST"):
        monkeypatch.delenv(name, raising=False)
    return home


def test_an_account_pin_is_detected_from_the_manifest_and_an_old_pin_is_not(tmp_path, account):
    assert claude_trust.account_pin(make_consumer(tmp_path / "new")) is True
    assert claude_trust.account_pin(make_consumer(tmp_path / "old", manifest=False)) is False


def test_status_without_the_shim_is_unreviewed_and_says_who_reviews(tmp_path, account):
    root = make_consumer(tmp_path / "new")
    state = claude_trust.status(root)
    assert state["reviewed"] is False and state["via"] == "account" and "trust --record" in state["reason"]


def test_trust_record_delegates_to_the_shim_and_records_both_parts(tmp_path, account, capfd):
    root = make_consumer(tmp_path / "new")
    install_account(["claude"])
    assert claude_trust.account_pin(root) and claude_trust.status(root)["reviewed"] is False
    assert claude_trust.delegate_record(root) == 0
    recorded = json.loads(capfd.readouterr().out)["recorded"]
    assert sorted(item["part"] for item in recorded) == ["adapter", "registration"]
    state = claude_trust.status(root)
    assert state["reviewed"] is True and state["via"] == "account"
    # The legacy project record is not used: no claude-hook-trust.json appears.
    assert not (cf_shim.config_dir() / "claude-hook-trust.json").exists()


def test_trust_record_without_the_shim_installed_fails_visibly(tmp_path, account, capsys):
    root = make_consumer(tmp_path / "new")
    assert claude_trust.delegate_record(root) == 2
    assert "install.sh --account" in capsys.readouterr().err


def test_a_run_under_the_shim_trusts_the_digest_the_shim_just_verified(tmp_path, account, monkeypatch):
    monkeypatch.setenv("CF_SHIM_ACTIVE", "1")
    monkeypatch.setenv("CF_SHIM_ADAPTER_DIGEST", "a" * 64)
    state = claude_trust.status(make_consumer(tmp_path / "new"))
    assert state == {"reviewed": True, "digest": "a" * 64, "reason": "", "via": "account-shim"}


def test_the_adapter_does_not_write_the_legacy_heartbeat_under_the_shim(tmp_path, account, monkeypatch):
    monkeypatch.setenv("CF_SHIM_ACTIVE", "1")
    monkeypatch.setenv("CF_SHIM_ADAPTER_DIGEST", "a" * 64)
    monkeypatch.chdir(make_consumer(tmp_path / "new"))
    claude_adapter.session_start({"session_id": "11111111-2222-3333-4444-555555555555", "transcript_path": "/x/y.jsonl", "cwd": str(tmp_path)})
    assert claude_trust.read_heartbeat("11111111-2222-3333-4444-555555555555") is None


def test_an_old_pin_keeps_the_project_trust_record(tmp_path, account, capsys):
    root = make_consumer(tmp_path / "old", manifest=False)
    state = claude_trust.status(root)
    assert state["reviewed"] is False and "via" not in state
