from __future__ import annotations

import json
from pathlib import Path

import pytest

import claude_hooks
from codex_hooks import HookConfigError

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SETTINGS = REPO / ".claude/settings.json"


def test_settings_declare_the_required_events_matchers_timeouts_and_blocking_gate():
    hooks = json.loads(SETTINGS.read_text())["hooks"]
    assert {"SessionStart", "PreToolUse", "PostToolUse", "SubagentStop", "Stop"} <= set(hooks)
    assert hooks["SessionStart"][0]["matcher"] == "startup|resume|clear|compact"
    pre = hooks["PreToolUse"][0]
    assert set(pre["matcher"].split("|")) == {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Agent"}
    assert pre["hooks"][0]["onFailure"] == "block"
    post = {g["matcher"]: g for g in hooks["PostToolUse"]}
    assert set(post) == {"Edit|Write|MultiEdit|NotebookEdit|Bash", "Agent"}
    for event, groups in hooks.items():
        for group in groups:
            for handler in group["hooks"]:
                assert handler["type"] == "command" and isinstance(handler["timeout"], int) and handler["timeout"] > 0
                assert 'python3 "$CLAUDE_PROJECT_DIR/scripts/process-fsm/claude_adapter.py"' in handler["command"]
    assert "block" not in json.dumps(hooks["SubagentStop"])


def test_every_command_names_an_event_the_adapter_dispatches():
    import claude_adapter
    for groups in json.loads(SETTINGS.read_text())["hooks"].values():
        for group in groups:
            for handler in group["hooks"]:
                event = handler["command"].rsplit(" ", 1)[1]
                assert event in {"session-start", "pre-tool-use", "post-tool-use", "subagent-stop", "stop"}
    assert claude_adapter.dispatch("bogus", {}) == 2


def test_repository_hooks_merge_is_current_and_codex_hooks_untouched():
    assert claude_hooks.install(REPO, REPO, check_only=True) is False
    assert not (REPO / ".claude/settings.local.json").exists()


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
