"""`claude_trust` / `claude_adapter trust` on an account pin: the shim owns the review, the adapter only delegates."""
from __future__ import annotations

import json

import pytest

import cf_shim
import claude_adapter
import claude_trust
from shim_fixtures import install_account, isolate_account, make_consumer, trust_all

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


def test_trust_record_delegates_to_the_shim_which_asks_for_the_operator_itself(tmp_path, account, capfd):
    root = make_consumer(tmp_path / "new")
    install_account(["claude"])
    assert claude_trust.account_pin(root) and claude_trust.status(root)["reviewed"] is False
    # the delegate hands the record to the installed shim, which needs a terminal and an operator: no pipe, no agent
    assert claude_trust.delegate_record(root) == 2
    assert "recorded" not in capfd.readouterr().out
    assert claude_trust.status(root)["reviewed"] is False
    # the operator's own record (terminal + typed confirmation) is what makes the account pin reviewed
    trust_all(root, ["claude"])
    state = claude_trust.status(root)
    assert state["reviewed"] is True and state["via"] == "account"
    # The legacy project record is not used: no claude-hook-trust.json appears.
    assert not (cf_shim.config_dir() / "claude-hook-trust.json").exists()


def test_trust_record_without_the_shim_installed_fails_visibly(tmp_path, account, capsys):
    root = make_consumer(tmp_path / "new")
    assert claude_trust.delegate_record(root) == 2
    assert "install.sh --account" in capsys.readouterr().err


def test_a_run_under_the_shim_is_verified_against_the_trust_record_not_the_environment(tmp_path, account, monkeypatch):
    root = make_consumer(tmp_path / "new")
    install_account(["claude"])
    trust_all(root, ["claude"])
    digest = cf_shim.status("claude", root)["adapter"]["digest"]
    monkeypatch.setenv("CF_SHIM_ACTIVE", "1")
    monkeypatch.setenv("CF_SHIM_ADAPTER_DIGEST", digest)
    assert claude_trust.shim_verified(root) == digest
    state = claude_trust.status(root)
    assert state == {"reviewed": True, "digest": digest, "reason": "", "via": "account-shim"}


def test_a_forged_environment_is_not_proof_of_review(tmp_path, account, monkeypatch):
    root = make_consumer(tmp_path / "new")
    install_account(["claude"])
    monkeypatch.setenv("CF_SHIM_ACTIVE", "1")
    monkeypatch.setenv("CF_SHIM_ADAPTER_DIGEST", "a" * 64)
    # nothing reviewed: the claim of an arbitrary digest does not make the session reviewed
    assert claude_trust.shim_verified(root) is None
    state = claude_trust.status(root)
    assert state["reviewed"] is False and state["via"] == "account"
    # reviewed, but the claimed digest is not the one of this worktree
    trust_all(root, ["claude"])
    assert claude_trust.shim_verified(root) is None
    # and a worktree whose bytes diverged after the review is not verified even with its own old digest
    good = cf_shim.status("claude", root)["adapter"]["digest"]
    monkeypatch.setenv("CF_SHIM_ADAPTER_DIGEST", good)
    assert claude_trust.shim_verified(root) == good
    (root / "scripts/process-fsm/other_module.py").write_text("VALUE = 666\n")
    assert claude_trust.shim_verified(root) is None and claude_trust.status(root)["reviewed"] is False
    monkeypatch.delenv("CF_SHIM_ACTIVE")
    (root / "scripts/process-fsm/other_module.py").write_text("VALUE = 1\n")
    assert claude_trust.shim_verified(root) is None  # the variable alone, without the shim marker, is nothing


def test_the_adapter_does_not_write_the_legacy_heartbeat_under_a_verified_shim(tmp_path, account, monkeypatch):
    root = make_consumer(tmp_path / "new")
    install_account(["claude"])
    trust_all(root, ["claude"])
    monkeypatch.setenv("CF_SHIM_ACTIVE", "1")
    monkeypatch.setenv("CF_SHIM_ADAPTER_DIGEST", cf_shim.status("claude", root)["adapter"]["digest"])
    monkeypatch.chdir(root)
    monkeypatch.setattr(claude_trust, "project_root", lambda *a, **k: root)
    claude_adapter.session_start({"session_id": "11111111-2222-3333-4444-555555555555", "transcript_path": "/x/y.jsonl", "cwd": str(root)})
    assert claude_trust.read_heartbeat("11111111-2222-3333-4444-555555555555") is None


def test_an_old_pin_keeps_the_project_trust_record(tmp_path, account, capsys):
    root = make_consumer(tmp_path / "old", manifest=False)
    state = claude_trust.status(root)
    assert state["reviewed"] is False and "via" not in state
