from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import codex_hooks  # noqa: E402
from codex_hooks import HookConfigError, install, merge_hooks, plan  # noqa: E402


def _source(root: Path) -> Path:
    hooks = root / ".codex" / "hooks.json"
    hooks.parent.mkdir(parents=True, exist_ok=True)
    hooks.write_text(
        json.dumps(
            {
                "description": "Covenant hooks",
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash|apply_patch|Agent",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "$(git rev-parse --show-toplevel)/scripts/process-fsm/codex_adapter.py" pre-tool-use',
                                    "timeout": 30,
                                }
                            ],
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    return root


def _managed(command: str) -> dict[str, str]:
    return {"type": "command", "command": command}


def test_merge_preserves_local_handlers_and_replaces_only_previous_adapter(tmp_path: Path):
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    target_dir = target / ".codex"
    target_dir.mkdir(parents=True)
    old = {
        "operator_key": {"keep": True},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash|apply_patch|Agent",
                    "operator_group_key": "keep too",
                    "hooks": [
                        _managed("python scripts/process-fsm/codex_adapter.py old"),
                        _managed("python /operator/hooks/policy.py"),
                    ],
                }
            ],
            "Notification": [{"hooks": [_managed("python /operator/hooks/notify.py")]}],
        },
    }
    path = target_dir / "hooks.json"
    path.write_text(json.dumps(old), encoding="utf-8")

    merged_path, merged, _rendered = plan(source, target)

    assert merged_path == path
    assert merged["operator_key"] == {"keep": True}
    group = merged["hooks"]["PreToolUse"][0]
    assert group["operator_group_key"] == "keep too"
    commands = [hook["command"] for hook in group["hooks"]]
    assert "python /operator/hooks/policy.py" in commands
    assert any("codex_adapter.py" in command and "pre-tool-use" in command for command in commands)
    assert merged["hooks"]["Notification"] == old["hooks"]["Notification"]


def test_install_does_not_follow_preexisting_predictable_temp_symlink(tmp_path: Path):
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    codex = target / ".codex"
    codex.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"protected bytes\n")
    temp_link = codex / ".hooks.json.covenant-flow-tmp"
    temp_link.symlink_to(victim)

    assert install(source, target) is True

    hooks = codex / "hooks.json"
    assert hooks.is_file() and not hooks.is_symlink()
    assert json.loads(hooks.read_text(encoding="utf-8"))["hooks"]
    assert victim.read_bytes() == b"protected bytes\n"
    assert temp_link.is_symlink()


def test_install_is_idempotent_and_keeps_unrelated_codex_toml(tmp_path: Path):
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    toml = target / ".codex" / "config.toml"
    toml.parent.mkdir(parents=True)
    toml.write_text('[agents]\ndefault_subagent_model = "gpt-6-sol"\n', encoding="utf-8")

    assert install(source, target) is True
    before = (target / ".codex" / "hooks.json").read_bytes()
    assert install(source, target) is False
    assert (target / ".codex" / "hooks.json").read_bytes() == before
    assert toml.read_text(encoding="utf-8") == '[agents]\ndefault_subagent_model = "gpt-6-sol"\n'
    assert codex_hooks.install(source, target, check_only=True) is False


def test_hooks_toml_conflict_refuses_before_any_write(tmp_path: Path):
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    codex = target / ".codex"
    codex.mkdir(parents=True)
    config = codex / "config.toml"
    config.write_text('[[hooks.PreToolUse]]\nmatcher = "Bash"\n', encoding="utf-8")
    hooks = codex / "hooks.json"
    hooks.write_text('{"hooks":{"Notification":[]}}\n', encoding="utf-8")

    with pytest.raises(HookConfigError, match=r"defines \[hooks\]"):
        plan(source, target)

    assert hooks.read_text(encoding="utf-8") == '{"hooks":{"Notification":[]}}\n'
    assert not (codex / ".hooks.json.covenant-flow-tmp").exists()


def test_invalid_existing_hooks_refuse_without_replacing_bytes(tmp_path: Path):
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    hooks = target / ".codex" / "hooks.json"
    hooks.parent.mkdir(parents=True)
    original = '{ not json\n'
    hooks.write_text(original, encoding="utf-8")

    with pytest.raises(HookConfigError, match="cannot read Codex hooks JSON"):
        install(source, target)

    assert hooks.read_text(encoding="utf-8") == original


def test_invalid_existing_hook_shape_refuses_without_partial_merge(tmp_path: Path):
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    hooks = target / ".codex" / "hooks.json"
    hooks.parent.mkdir(parents=True)
    original = json.dumps({"hooks": {"PreToolUse": "not-a-list"}})
    hooks.write_text(original, encoding="utf-8")

    with pytest.raises(HookConfigError, match="event/group list"):
        install(source, target)

    assert hooks.read_text(encoding="utf-8") == original
