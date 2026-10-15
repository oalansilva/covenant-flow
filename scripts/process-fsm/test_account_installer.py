"""`install.sh --account` end to end: the shim and one registration per in-scope host, never trust."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from test_codex_installer import INSTALL, ROOT, _pin, _target

pytestmark = pytest.mark.skipif(
    not INSTALL.is_file(), reason="installer integration tests require the product install.sh"
)

HOSTS = ("claude", "cursor", "codex", "opencode")


def _account(tmp_path: Path, *args: str, target: Path | None = None, home: Path | None = None) -> subprocess.CompletedProcess[str]:
    home = home or tmp_path / "operator-home"
    home.mkdir(parents=True, exist_ok=True)
    cmd = [str(INSTALL), "--account", *args, "--source", str(ROOT)]
    if target is not None:
        cmd += ["--target", str(target)]
    env = {k: v for k, v in os.environ.items() if k not in ("CURSOR_VERSION", "CURSOR_PROJECT_DIR")}
    env["HOME"] = str(home)
    return subprocess.run(cmd, env=env, cwd=ROOT, capture_output=True, text=True, check=False)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def test_account_installs_the_shim_and_one_entry_per_scope_host_without_trust(tmp_path: Path):
    home = tmp_path / "operator-home"
    (home / ".config" / "covenant-flow").mkdir(parents=True)
    selection = home / ".config" / "covenant-flow" / "model-selection.yaml"
    selection.write_bytes(b"# exact operator bytes\nversion: invalid\n")
    for host in (".claude", ".cursor", ".codex", ".config/opencode"):
        (home / host).mkdir(parents=True, exist_ok=True)
    (home / ".claude" / "settings.json").write_text(json.dumps({"model": "mine", "hooks": {"Notification": [{"hooks": [{"type": "command", "command": "python mine.py"}]}]}}))
    before_selection = selection.read_bytes()

    result = _account(tmp_path, home=home)

    assert result.returncode == 0, result.stderr
    shim = home / ".config" / "covenant-flow" / "shim" / "current" / "cf_shim.py"
    assert shim.is_file() and (shim.parent / "cf_shim_opencode.js").is_file()
    claude = json.loads((home / ".claude" / "settings.json").read_text())
    assert claude["model"] == "mine" and "Notification" in claude["hooks"] and "PreToolUse" in claude["hooks"]
    assert (home / ".cursor" / "hooks.json").is_file() and (home / ".codex" / "hooks.json").is_file()
    assert (home / ".config" / "opencode" / "plugin" / "covenant-flow-shim.js").is_file()
    # No Grok Build or dsh configuration, no trust, no read or write of the selection.
    assert not (home / ".grok").exists() and not (home / ".dsh").exists()
    assert not (home / ".config" / "covenant-flow" / "hook-trust.json").exists()
    assert selection.read_bytes() == before_selection
    assert "trust is not recorded" in result.stdout

    again = _snapshot(home)
    assert _account(tmp_path, home=home).returncode == 0
    assert _snapshot(home) == again  # idempotent


def test_check_reports_the_host_without_registration_and_the_consumer_review_state(tmp_path: Path):
    home = tmp_path / "operator-home"
    for host in (".claude", ".cursor", ".codex", ".config/opencode"):
        (home / host).mkdir(parents=True, exist_ok=True)
    target, _map = _target(tmp_path / "consumer")
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    assert _pin(target).returncode == 0

    empty = _account(tmp_path, "--check", target=target, home=home)
    assert empty.returncode == 1
    for host in HOSTS:
        assert f"{host}: registration=account entry=MISSING shim=MISSING" in empty.stdout
    assert "consumer_pin=account" in empty.stdout
    assert "grok" not in empty.stdout and "dsh" not in empty.stdout

    assert _account(tmp_path, home=home).returncode == 0
    ok = _account(tmp_path, "--check", target=target, home=home)
    assert ok.returncode == 0, ok.stdout
    for host in HOSTS:
        assert f"{host}: registration=account entry=present" in ok.stdout and "registration_review=unreviewed" in ok.stdout
        assert "adapter_review=unreviewed" in ok.stdout  # the pin and the installer recorded no trust


def test_remove_takes_only_covenant_flow_entries_out_and_restores_the_foreign_ones(tmp_path: Path):
    home = tmp_path / "operator-home"
    for host in (".claude", ".cursor", ".codex", ".config/opencode"):
        (home / host).mkdir(parents=True, exist_ok=True)
    foreign = {"model": "mine", "hooks": {"Notification": [{"hooks": [{"type": "command", "command": "python mine.py"}]}]}}
    (home / ".claude" / "settings.json").write_text(json.dumps(foreign))
    cursor = {"version": 1, "hooks": {"stop": [{"command": "./mine.sh"}]}}
    (home / ".cursor" / "hooks.json").write_text(json.dumps(cursor))
    assert _account(tmp_path, home=home).returncode == 0

    removed = _account(tmp_path, "--remove", home=home)

    assert removed.returncode == 0, removed.stderr
    assert json.loads((home / ".claude" / "settings.json").read_text()) == foreign
    assert json.loads((home / ".cursor" / "hooks.json").read_text()) == cursor
    assert not (home / ".codex" / "hooks.json").exists()
    assert not (home / ".config" / "opencode" / "plugin" / "covenant-flow-shim.js").exists()
    assert not (home / ".config" / "covenant-flow" / "shim").exists()


def test_a_malformed_host_config_refuses_the_whole_run_and_names_the_path(tmp_path: Path):
    home = tmp_path / "operator-home"
    for host in (".claude", ".cursor", ".codex", ".config/opencode"):
        (home / host).mkdir(parents=True, exist_ok=True)
    (home / ".cursor" / "hooks.json").write_text("{not json")
    before = _snapshot(home)

    result = _account(tmp_path, home=home)

    assert result.returncode != 0 and str(home / ".cursor" / "hooks.json") in result.stderr
    assert _snapshot(home) == before and not (home / ".config" / "covenant-flow").exists()


def test_account_mode_writes_nothing_to_a_consumer(tmp_path: Path):
    home = tmp_path / "operator-home"
    (home / ".claude").mkdir(parents=True)
    target, _map = _target(tmp_path / "consumer")
    before = _snapshot(target)
    assert _account(tmp_path, target=target, home=home).returncode == 0
    assert _snapshot(target) == before


def test_check_and_remove_are_only_for_account_mode(tmp_path: Path):
    result = subprocess.run([str(INSTALL), "--check", "--target", str(tmp_path)], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode != 0


def _shim(home: Path, client: str, event: str, payload: dict, cwd: Path) -> subprocess.CompletedProcess[str]:
    shim = home / ".config" / "covenant-flow" / "shim" / "current" / "cf_shim.py"
    env = {k: v for k, v in os.environ.items() if k not in ("CURSOR_VERSION", "CURSOR_PROJECT_DIR", "CLAUDECODE", "CODEX_THREAD_ID", "COVENANT_CLIENT")}
    env["HOME"] = str(home)
    return subprocess.run([sys.executable, str(shim), client, event], input=json.dumps(payload), env=env, cwd=cwd, capture_output=True, text=True, check=False)


def test_pinned_consumer_through_the_installed_shim_denies_a_product_write_on_develop(tmp_path: Path):
    home = tmp_path / "operator-home"
    (home / ".claude").mkdir(parents=True)
    target, _map = _target(tmp_path / "consumer")
    subprocess.run(["git", "init", "-q", "-b", "develop", str(target)], check=True)
    subprocess.run(["git", "-C", str(target), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "i"], check=True)
    assert _pin(target).returncode == 0
    assert _account(tmp_path, home=home).returncode == 0
    payload = {"session_id": "11111111-2222-3333-4444-555555555555", "cwd": str(target), "hook_event_name": "PreToolUse",
               "tool_name": "Write", "tool_input": {"file_path": str(target / "backend" / "x.py"), "content": "x"}}

    unreviewed = _shim(home, "claude", "pre-tool-use", payload, tmp_path)
    assert json.loads(unreviewed.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "hooks_unreviewed" in unreviewed.stdout  # installing and pinning are not review

    shim = home / ".config" / "covenant-flow" / "shim" / "current" / "cf_shim.py"
    env = {**os.environ, "HOME": str(home)}
    recorded = subprocess.run([sys.executable, str(shim), "trust", "--record", "--client", "claude", "--cwd", str(target)], env=env, capture_output=True, text=True)
    assert recorded.returncode == 0, recorded.stderr

    denied = _shim(home, "claude", "pre-tool-use", payload, tmp_path)  # launched outside the repo: the cwd of the event decides
    out = json.loads(denied.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "hooks_unreviewed" not in denied.stdout and "q_git=develop" in out["permissionDecisionReason"]

    outside = _shim(home, "claude", "pre-tool-use", dict(payload, cwd=str(tmp_path)), tmp_path)
    assert outside.returncode == 0 and outside.stdout.strip() == ""  # a folder without a pin: nothing
