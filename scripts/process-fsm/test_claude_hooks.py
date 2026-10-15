from __future__ import annotations

import json
from pathlib import Path

import pytest

import claude_hooks
from codex_hooks import HookConfigError
from shim_fixtures import install_account, registered_account, registered_document, shim_call

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]

# Since the account-registration pin a consumer carries no `.claude/settings.json` entries of Covenant Flow:
# the registration is what `install.sh --account` writes to the operator's `~/.claude/settings.json`.
# These tests run `account_install` in a tmp HOME and read that file.


@pytest.fixture
def claude_account(monkeypatch, tmp_path):
    return registered_account(monkeypatch, tmp_path, ["claude"])


def test_account_registration_declares_the_required_events_matchers_timeouts_and_blocking_gate(claude_account):
    hooks = registered_document("claude")["hooks"]
    assert {"SessionStart", "PreToolUse", "PostToolUse", "SubagentStop", "Stop"} <= set(hooks)
    assert hooks["SessionStart"][0]["matcher"] == "startup|resume|clear|compact"
    pre = hooks["PreToolUse"][0]
    assert set(pre["matcher"].split("|")) == {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Agent"}
    assert pre["hooks"][0]["onFailure"] == "block"
    post = {g["matcher"]: g for g in hooks["PostToolUse"]}
    # EnterWorktree does not reload settings and fires no SessionStart: the account entry reinjects the card page.
    assert set(post) == {"Edit|Write|MultiEdit|NotebookEdit|Bash", "Agent", "EnterWorktree"}
    for event, groups in hooks.items():
        for group in groups:
            for handler in group["hooks"]:
                assert handler["type"] == "command" and isinstance(handler["timeout"], int) and handler["timeout"] > 0
                # one entry calling the account shim: no path of a repository and no project variable
                assert shim_call(handler["command"])[0] == "claude"
                assert "CLAUDE_PROJECT_DIR" not in handler["command"] and "claude_adapter.py" not in handler["command"]
    assert "block" not in json.dumps(hooks["SubagentStop"])


def test_every_registered_command_names_an_event_the_adapter_dispatches(claude_account):
    import claude_adapter
    from adapter_manifest import ENTRYPOINTS
    seen = set()
    for groups in registered_document("claude")["hooks"].values():
        for group in groups:
            for handler in group["hooks"]:
                client, event = shim_call(handler["command"])
                assert event in {"session-start", "pre-tool-use", "post-tool-use", "subagent-stop", "stop"}
                # the pinned manifest maps the event to the adapter file the shim runs
                assert ENTRYPOINTS[client][event] == ["python3", "scripts/process-fsm/claude_adapter.py", event]
                seen.add(event)
    assert seen == set(ENTRYPOINTS["claude"])
    assert (REPO / ENTRYPOINTS["claude"]["pre-tool-use"][1]).is_file()
    assert claude_adapter.dispatch("bogus", {}) == 2


def test_account_registration_is_current_idempotent_and_leaves_other_hosts_and_local_settings_untouched(claude_account):
    import account_install
    home = claude_account
    path = home / ".claude" / "settings.json"
    planned_path, planned = account_install.plan_host("claude")
    assert planned_path == path and path.read_bytes() == planned  # current: re-running would change nothing
    before = path.read_bytes()
    install_account(["claude"])
    assert path.read_bytes() == before
    assert not (home / ".claude" / "settings.local.json").exists()
    assert not (home / ".codex").exists() and not (home / ".cursor").exists()


def source(root: Path) -> Path:
    path = root / ".claude/settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash|Agent", "hooks": [{"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/scripts/process-fsm/claude_adapter.py" pre-tool-use', "timeout": 30}]}]}}))
    return root


def test_merge_preserves_consumer_hooks_keys_and_replaces_only_the_previous_adapter(tmp_path):
    src = source(tmp_path / "src")
    target = tmp_path / "target"
    (target / ".claude").mkdir(parents=True)
    old = {"permissions": {"allow": ["Bash(ls)"]}, "hooks": {
        "PreToolUse": [{"matcher": "Bash|Agent", "operator_group_key": 1, "hooks": [
            {"type": "command", "command": "python3 scripts/process-fsm/claude_adapter.py old"},
            {"type": "command", "command": "python3 /operator/policy.py"}]}],
        "Notification": [{"hooks": [{"type": "command", "command": "notify"}]}]}}
    (target / ".claude/settings.json").write_text(json.dumps(old))
    _, merged, _ = claude_hooks.plan(src, target)
    commands = [h["command"] for h in merged["hooks"]["PreToolUse"][0]["hooks"]]
    assert "python3 /operator/policy.py" in commands and not any(c.endswith("claude_adapter.py old") for c in commands)
    assert any("claude_adapter.py" in c and c.endswith("pre-tool-use") for c in commands)
    assert merged["permissions"] == old["permissions"] and merged["hooks"]["Notification"] == old["hooks"]["Notification"]
    assert merged["hooks"]["PreToolUse"][0]["operator_group_key"] == 1


def test_install_is_idempotent_and_never_follows_a_temp_symlink(tmp_path):
    src = source(tmp_path / "src")
    target = tmp_path / "target"
    (target / ".claude").mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.write_text("protected")
    (target / ".claude/.settings.json.covenant-flow-tmp").symlink_to(victim)
    assert claude_hooks.install(src, target) is True
    assert claude_hooks.install(src, target) is False
    assert victim.read_text() == "protected" and not (target / ".claude/settings.json").is_symlink()
    assert claude_hooks.main(["check", "--source", str(src), "--target", str(target)]) == 0


@pytest.mark.parametrize("content", ["{ not json", json.dumps({"hooks": {"PreToolUse": "x"}}), "[]"])
def test_invalid_consumer_settings_refuse_without_changing_bytes(tmp_path, content):
    src = source(tmp_path / "src")
    target = tmp_path / "target"
    (target / ".claude").mkdir(parents=True)
    path = target / ".claude/settings.json"
    path.write_text(content)
    with pytest.raises(HookConfigError):
        claude_hooks.install(src, target)
    assert path.read_text() == content
    assert claude_hooks.main(["install", "--source", str(src), "--target", str(target)]) == 2


def test_hook_install_does_not_grant_trust(tmp_path, monkeypatch):
    import claude_trust
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    src = source(tmp_path / "src")
    target = tmp_path / "target"
    claude_hooks.install(src, target)
    assert str(claude_trust.trust_path()).startswith(str(tmp_path / "home"))
    assert not claude_trust.trust_path().exists()
