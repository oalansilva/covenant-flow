from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from test_overlay_fixtures import filled_overlay_dict


ROOT = Path(__file__).resolve().parents[2]
INSTALL = ROOT / "install.sh"
pytestmark = pytest.mark.skipif(
    not INSTALL.is_file(), reason="installer integration tests require the product install.sh"
)


def _target(root: Path) -> tuple[Path, bytes]:
    root.mkdir()
    overlay = root / ".covenant-flow" / "overlay.yaml"
    overlay.parent.mkdir()
    overlay.write_text(yaml.safe_dump(filled_overlay_dict(), sort_keys=False), encoding="utf-8")
    model = root / ".cursor" / "model-map.yaml"
    model.parent.mkdir()
    original_map = (
        "# Consumer-owned model labels: keep exact.\n"
        "juizo:\n"
        '  label: "deepseek-flash"\n'
        "  slug: deepseek-flash\n"
        "execucao:\n"
        '  label: "deepseek-flash"\n'
        "  slug: deepseek-flash\n"
        "forbid:\n"
        "  - composer-2.5-fast\n"
        "  - inherit\n"
    ).encode()
    model.write_bytes(original_map)
    return root, original_map


def _pin(target: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(INSTALL),
            "--pin",
            "v1.2.0",
            "--source",
            str(ROOT),
            "--target",
            str(target),
        ],
        cwd=ROOT,
        env={**os.environ, "HOME": str(target.parent / "operator-home")},
        capture_output=True,
        text=True,
        check=False,
    )


def test_pin_merges_codex_without_overwriting_cursor_map_or_vendor_skills(tmp_path: Path):
    target, original_map = _target(tmp_path / "consumer")
    vendor = target / ".agents" / "skills" / "impeccable" / "SKILL.md"
    vendor.parent.mkdir(parents=True)
    vendor.write_bytes(b"operator-installed provider bytes\n")
    local_skill = target / ".agents" / "skills" / "playwright-cli" / "SKILL.md"
    local_skill.parent.mkdir(parents=True)
    local_skill.write_bytes(b"operator playwright bytes\n")
    hooks_path = target / ".codex" / "hooks.json"
    hooks_path.parent.mkdir()
    hooks_path.write_text(
        json.dumps(
            {
                "operator_key": "keep",
                "hooks": {
                    "Notification": [
                        {"hooks": [{"type": "command", "command": "python operator-hook.py"}]}
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    config_toml = target / ".codex" / "config.toml"
    config_toml.write_text('[agents]\ndefault_subagent_model = "operator-default"\n', encoding="utf-8")

    local_selection = tmp_path / "operator-home" / ".config" / "covenant-flow" / "model-selection.yaml"
    local_selection.parent.mkdir(parents=True)
    selection_bytes = b"# Exact operator bytes; installer must not read or normalize.\nversion: invalid\n"
    local_selection.write_bytes(selection_bytes)
    first = _pin(target)
    assert first.returncode == 0, first.stderr
    pinned_map = (target / ".cursor" / "model-map.yaml").read_bytes()
    assert pinned_map == original_map
    assert (target / ".cursor" / "model-policy.yaml").is_file()
    assert (target / "scripts" / "process-fsm" / "model_selection.py").is_file()
    assert local_selection.read_bytes() == selection_bytes
    merged_hooks = json.loads(hooks_path.read_text(encoding="utf-8"))
    assert merged_hooks["operator_key"] == "keep"
    assert merged_hooks["hooks"]["Notification"][0]["hooks"][0]["command"] == "python operator-hook.py"
    assert {"SessionStart", "PreToolUse", "PostToolUse", "Stop"} <= set(merged_hooks["hooks"])
    assert vendor.read_bytes() == b"operator-installed provider bytes\n"
    assert local_skill.read_bytes() == b"operator playwright bytes\n"
    assert config_toml.read_text(encoding="utf-8") == '[agents]\ndefault_subagent_model = "operator-default"\n'
    roles = target / ".codex" / "agents"
    assert (roles / "diff-reviewer.toml").is_file()
    assert (roles / "code-reviewer.toml").is_file()
    assert len(list((target / ".agents" / "skills").glob("*/SKILL.md"))) == 20

    second = _pin(target)
    assert second.returncode == 0, second.stderr
    assert (target / ".cursor" / "model-map.yaml").read_bytes() == pinned_map
    assert hooks_path.read_bytes() == json.dumps(merged_hooks, indent=2, ensure_ascii=False).encode() + b"\n"
    assert vendor.read_bytes() == b"operator-installed provider bytes\n"
    assert local_skill.read_bytes() == b"operator playwright bytes\n"
    assert local_selection.read_bytes() == selection_bytes


def test_codex_hook_collision_aborts_pin_before_any_tree_is_written(tmp_path: Path):
    target, original_map = _target(tmp_path / "consumer")
    codex = target / ".codex"
    codex.mkdir(exist_ok=True)
    config = codex / "config.toml"
    config.write_text('[[hooks.PreToolUse]]\nmatcher = "Bash"\n', encoding="utf-8")
    hooks = codex / "hooks.json"
    hooks.write_text('{"hooks":{"Notification":[]}}\n', encoding="utf-8")

    result = _pin(target)

    assert result.returncode != 0
    assert "defines [hooks]" in result.stderr
    assert hooks.read_text(encoding="utf-8") == '{"hooks":{"Notification":[]}}\n'
    assert (target / ".cursor" / "model-map.yaml").read_bytes() == original_map
    assert not (target / ".cursor" / "process-fsm.yaml").exists()
    assert not (target / ".codex" / "agents" / "diff-reviewer.toml").exists()


def test_skill_bridge_conflict_aborts_pin_before_any_tree_is_written(tmp_path: Path):
    target, original_map = _target(tmp_path / "consumer")
    conflict = target / ".agents" / "skills" / "implantar" / "SKILL.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("operator-authored skill\n", encoding="utf-8")

    result = _pin(target)

    assert result.returncode != 0
    assert "skill bridge conflict" in result.stderr
    assert conflict.read_text(encoding="utf-8") == "operator-authored skill\n"
    assert (target / ".cursor" / "model-map.yaml").read_bytes() == original_map
    assert not (target / ".cursor" / "process-fsm.yaml").exists()


def test_pin_without_legacy_map_does_not_create_machine_selection(tmp_path: Path):
    target, _original_map = _target(tmp_path / "consumer")
    (target / ".cursor" / "model-map.yaml").unlink()

    result = _pin(target)

    assert result.returncode == 0, result.stderr
    assert (target / ".cursor" / "process-fsm.yaml").is_file()
    assert (target / ".cursor" / "model-policy.yaml").is_file()
    assert (target / ".codex" / "agents" / "diff-reviewer.toml").is_file()
    assert not (tmp_path / "operator-home" / ".config" / "covenant-flow" / "model-selection.yaml").exists()


def test_pin_installs_functional_resolver_and_selection_hooks(tmp_path, monkeypatch):
    from model_selection_fixtures import document
    import sys
    operator_home = tmp_path / "operator-home"
    selection = operator_home / ".config/covenant-flow/model-selection.yaml"
    selection.parent.mkdir(parents=True)
    selection.write_text(yaml.safe_dump(document()))
    cache = operator_home / ".codex/models_cache.json"
    cache.parent.mkdir(parents=True)
    cache.write_text(json.dumps({"models": [{"slug": "gpt-6-luna", "supported_reasoning_levels": [{"effort": "max"}]}]}))
    target, original_map = _target(tmp_path / "consumer")
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    before = selection.read_bytes()
    result = _pin(target)
    assert result.returncode == 0, result.stderr
    assert selection.read_bytes() == before
    env = {**os.environ, "HOME": str(operator_home)}
    capture = tmp_path / "birth.json"
    resolved = subprocess.run([sys.executable, str(target / "scripts/process-fsm/model_selection.py"), "resolve", "--client", "codex", "--band", "execucao", "--role", "same-card-search", "--capture", str(capture)], env=env, capture_output=True, text=True)
    assert resolved.returncode == 0, resolved.stderr
    birth = json.loads(resolved.stdout)
    assert birth["source_path"] == str(selection)
    assert birth["arguments"] == {"model": "gpt-6-luna", "reasoning_effort": "max"}
    payload = {"tool_name": "Agent", "cwd": str(target), "tool_input": {**birth["arguments"], "description": "same-card-search", "prompt": f"model_selection_capture: {capture}"}}
    allowed = subprocess.run([sys.executable, str(target / "scripts/process-fsm/codex_adapter.py"), "pre-tool-use"], input=json.dumps(payload), env=env, capture_output=True, text=True)
    assert allowed.returncode == 0, allowed.stderr
    assert allowed.stdout.strip() == ""  # Native hook allow is no denial output.
    payload["tool_input"]["model"] = "other"
    denied = subprocess.run([sys.executable, str(target / "scripts/process-fsm/codex_adapter.py"), "pre-tool-use"], input=json.dumps(payload), env=env, capture_output=True, text=True)
    assert json.loads(denied.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert (target / ".cursor/model-map.yaml").read_bytes() == original_map
    assert selection.read_bytes() == before


def test_missing_selection_mechanism_aborts_before_pin_writes(tmp_path):
    import shutil
    source = tmp_path / "source"
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    (source / ".cursor/model-policy.yaml").unlink()
    target, original_map = _target(tmp_path / "consumer")
    result = subprocess.run([str(INSTALL), "--pin", "v1.2.0", "--source", str(source), "--target", str(target)], capture_output=True, text=True, env={**os.environ, "HOME": str(tmp_path / "operator-home")})
    assert result.returncode != 0
    assert "selection mechanism missing" in result.stderr
    assert (target / ".cursor/model-map.yaml").read_bytes() == original_map
    assert not (target / ".cursor/process-fsm.yaml").exists()
    assert not (target / ".codex/hooks.json").exists()
