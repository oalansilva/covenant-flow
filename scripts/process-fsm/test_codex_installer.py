from __future__ import annotations

import json
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

    first = _pin(target)
    assert first.returncode == 0, first.stderr
    pinned_map = (target / ".cursor" / "model-map.yaml").read_bytes()
    data = yaml.safe_load(pinned_map)
    assert data["juizo"]["codex"] == {"label": "GPT-6 Sol", "slug": "gpt-6-sol", "effort": "high"}
    assert data["execucao"]["codex"] == {"label": "GPT-6 Luna", "slug": "gpt-6-luna", "effort": "max"}
    assert pinned_map.replace(
        b'  codex:\n    label: "GPT-6 Sol"\n    slug: gpt-6-sol\n    effort: high\n', b""
    ).replace(
        b'  codex:\n    label: "GPT-6 Luna"\n    slug: gpt-6-luna\n    effort: max\n', b""
    ) == original_map
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


def test_missing_shared_model_map_aborts_pin_before_any_tree_is_written(tmp_path: Path):
    target, _original_map = _target(tmp_path / "consumer")
    (target / ".cursor" / "model-map.yaml").unlink()

    result = _pin(target)

    assert result.returncode != 0
    assert "shared model map missing" in result.stderr
    assert not (target / ".cursor" / "process-fsm.yaml").exists()
    assert not (target / ".codex" / "agents" / "diff-reviewer.toml").exists()
