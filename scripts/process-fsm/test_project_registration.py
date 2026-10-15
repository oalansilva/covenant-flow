"""The account-registration pin takes only Covenant Flow's hook registration out of a project."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import project_registration as pr
from codex_hooks import HookConfigError

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def source(tmp_path: Path) -> Path:
    src = tmp_path / "source"
    plugin = src / ".opencode" / "plugin"
    plugin.mkdir(parents=True)
    for name in pr.OPENCODE_MODULES:
        (plugin / name).write_text("// " + name + "\nexport default async function () { return {}; }\n")
    return src


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value if isinstance(value, str) else json.dumps(value, indent=2))


CLAUDE_OWNED = {"type": "command", "command": 'python3 "$CLAUDE_PROJECT_DIR/scripts/process-fsm/claude_adapter.py" pre-tool-use'}
CODEX_OWNED = {"type": "command", "command": 'python3 "$(git rev-parse --show-toplevel)/scripts/process-fsm/codex_adapter.py" pre-tool-use'}


def test_foreign_claude_hooks_and_keys_survive_and_a_pure_file_is_deleted(tmp_path):
    src, target = source(tmp_path), tmp_path / "consumer"
    foreign = {"type": "command", "command": "python operator-bash.py"}
    write(target / ".claude" / "settings.json", {
        "model": "operator-default",
        "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [foreign, CLAUDE_OWNED]}, {"matcher": "Agent", "hooks": [CLAUDE_OWNED]}],
                  "Stop": [{"hooks": [CLAUDE_OWNED]}]},
    })
    write(target / ".codex" / "hooks.json", {"description": "Covenant Flow local adapter hooks. x", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [CODEX_OWNED]}]}})
    notes = pr.apply(src, target)
    settings = json.loads((target / ".claude" / "settings.json").read_text())
    assert settings == {"model": "operator-default", "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [foreign]}]}}
    assert not (target / ".codex" / "hooks.json").exists()
    assert any(".codex/hooks.json" in n for n in notes)
    pr.check(src, target)


def test_a_claude_file_with_only_covenant_flow_hooks_is_deleted(tmp_path):
    src, target = source(tmp_path), tmp_path / "consumer"
    write(target / ".claude" / "settings.json", {"hooks": {"Stop": [{"hooks": [CLAUDE_OWNED]}]}})
    pr.apply(src, target)
    assert not (target / ".claude" / "settings.json").exists()


def test_cursor_keeps_foreign_entries_and_drops_the_process_and_impeccable_ones(tmp_path):
    src, target = source(tmp_path), tmp_path / "consumer"
    write(target / ".cursor" / "hooks.json", {"version": 1, "hooks": {
        "sessionStart": [{"command": ".cursor/hooks/process-fsm-session-start.sh"}, {"command": "./team-start.sh"}],
        "preToolUse": [{"command": ".cursor/hooks/process-fsm-guard.sh", "matcher": "Write", "failClosed": True}],
        "afterFileEdit": [{"command": "test -f .cursor/hooks/impeccable.sh && exec .cursor/hooks/impeccable.sh afterFileEdit; exit 127"}],
    }})
    pr.apply(src, target)
    assert json.loads((target / ".cursor" / "hooks.json").read_text()) == {"version": 1, "hooks": {"sessionStart": [{"command": "./team-start.sh"}]}}


def test_a_cursor_file_with_only_ours_is_deleted(tmp_path):
    src, target = source(tmp_path), tmp_path / "consumer"
    write(target / ".cursor" / "hooks.json", {"version": 1, "hooks": {"stop": [{"command": ".cursor/hooks/impeccable.sh stop"}]}})
    pr.apply(src, target)
    assert not (target / ".cursor" / "hooks.json").exists()


def test_opencode_modules_move_out_of_the_autoload_path_and_foreign_plugins_stay(tmp_path):
    src, target = source(tmp_path), tmp_path / "consumer"
    for name in pr.OPENCODE_MODULES:
        write(target / ".opencode" / "plugin" / name, "// stale")
    write(target / ".opencode" / "plugin" / "team.js", "// team plugin")
    pr.apply(src, target)
    assert (target / ".opencode" / "plugin" / "team.js").read_text() == "// team plugin"
    for name in pr.OPENCODE_MODULES:
        assert not (target / ".opencode" / "plugin" / name).exists()
        assert (target / ".opencode" / "adapter" / name).read_bytes() == (src / ".opencode" / "plugin" / name).read_bytes()
    pr.check(src, target)


def test_the_empty_autoload_directory_is_removed_and_the_run_is_idempotent(tmp_path):
    src, target = source(tmp_path), tmp_path / "consumer"
    for name in pr.OPENCODE_MODULES:
        write(target / ".opencode" / "plugin" / name, "// stale")
    pr.apply(src, target)
    assert not (target / ".opencode" / "plugin").exists()
    snapshot = {p: p.read_bytes() for p in (target / ".opencode").rglob("*") if p.is_file()}
    assert pr.apply(src, target) == []
    assert {p: p.read_bytes() for p in (target / ".opencode").rglob("*") if p.is_file()} == snapshot


@pytest.mark.parametrize("relative,content", [
    (".claude/settings.json", "{not json"),
    (".claude/settings.json", '{"hooks": []}'),
    (".codex/hooks.json", '{"hooks": {"Stop": "x"}}'),
    (".cursor/hooks.json", '{"hooks": {"stop": ["x"]}}'),
])
def test_malformed_or_non_object_registration_refuses_without_any_write(tmp_path, relative, content):
    src, target = source(tmp_path), tmp_path / "consumer"
    write(target / relative, content)
    write(target / ".opencode" / "plugin" / pr.OPENCODE_MODULES[0], "// stale")
    with pytest.raises(HookConfigError):
        pr.apply(src, target)
    assert (target / relative).read_text() == content
    assert (target / ".opencode" / "plugin" / pr.OPENCODE_MODULES[0]).read_text() == "// stale"
    assert not (target / ".opencode" / "adapter").exists()


def test_grok_and_dsh_registrations_are_never_touched(tmp_path):
    src, target = source(tmp_path), tmp_path / "consumer"
    grok = {"hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": ".grok/hooks/process-fsm-guard.sh"}]}]}}
    write(target / ".grok" / "hooks" / "process-fsm.json", grok)
    write(target / ".dsh" / "cordis.patch.yml", "plugins: [process-fsm]\n")
    write(target / ".dsh" / "dsh_boot.sh", "#!/bin/sh\n")
    before = {p: p.read_bytes() for p in target.rglob("*") if p.is_file()}
    pr.apply(src, target)
    assert {p: p.read_bytes() for p in before} == before
    assert pr.plan(target) == []


def test_the_cli_reports_errors_visibly(tmp_path, capsys):
    src, target = source(tmp_path), tmp_path / "consumer"
    write(target / ".claude" / "settings.json", "{not json")
    assert pr.main(["preflight", "--source", str(src), "--target", str(target)]) == 2
    assert "project registration error" in capsys.readouterr().err
