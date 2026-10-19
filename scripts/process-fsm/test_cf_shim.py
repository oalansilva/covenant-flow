"""Account shim: discovery by cwd, the decision table, trust in two parts, heartbeat and worktree follow."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import adapter_manifest
import cf_shim
from shim_fixtures import (
    ALL_HOSTS,
    record_trust_as_operator,
    install_account,
    isolate_account,
    last_json,
    make_consumer,
    shim_command,
    trust_all,
    write,
)

SESSION = "11111111-2222-3333-4444-555555555555"


@pytest.fixture
def account(monkeypatch, tmp_path):
    return isolate_account(monkeypatch, tmp_path)


@pytest.fixture
def consumer(tmp_path, account):
    root = make_consumer(tmp_path / "consumer-1101")
    install_account()
    trust_all(root)
    return root


def calls(log: Path) -> list[dict]:
    return [json.loads(line) for line in log.read_text().splitlines() if line.startswith("{")] if log.exists() else []


def pretool(root: Path, command: str = "ls", tool: str = "Bash", **extra) -> dict:
    return {"session_id": SESSION, "cwd": str(root), "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command}, **extra}


def denial(result) -> str | None:
    out = last_json(result)
    inner = (out or {}).get("hookSpecificOutput") or {}
    return inner.get("permissionDecisionReason") if inner.get("permissionDecision") == "deny" else None


# --- decision table ----------------------------------------------------------------


def test_folder_without_overlay_does_nothing(tmp_path, account):
    install_account()
    plain = tmp_path / "plain"
    plain.mkdir()
    log = tmp_path / "log"
    for event, payload in (("session-start", {"session_id": SESSION, "cwd": str(plain)}), ("pre-tool-use", pretool(plain))):
        result = shim_command("claude", event, payload, log=log)
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
    assert calls(log) == []


def test_overlay_without_pin_does_nothing(tmp_path, account):
    root = make_consumer(tmp_path / "nopin", pin=None, manifest=False)
    install_account()
    log = tmp_path / "log"
    result = shim_command("claude", "pre-tool-use", pretool(root, "deny-me"), log=log)
    assert result.stdout == "" and calls(log) == []


def test_pin_before_account_registration_leaves_the_project_registration_alone(tmp_path, account):
    root = make_consumer(tmp_path / "old-pin", manifest=False)
    install_account()
    log = tmp_path / "log"
    for client, event in (("claude", "pre-tool-use"), ("codex", "pre-tool-use"), ("cursor", "guard")):
        result = shim_command(client, event, pretool(root, "deny-me"), log=log)
        assert result.stdout == "" and result.returncode == 0
    assert calls(log) == [] and not log.exists()


def test_manifest_declaring_project_registration_is_left_alone(consumer, tmp_path):
    manifest = json.loads((consumer / cf_shim.MANIFEST).read_text())
    manifest["clients"]["claude"] = {"registration": "project"}
    (consumer / cf_shim.MANIFEST).write_text(json.dumps(manifest))
    log = tmp_path / "log"
    assert shim_command("claude", "pre-tool-use", pretool(consumer, "deny-me"), log=log).stdout == ""
    assert calls(log) == []


def test_clean_reviewed_pin_runs_the_pinned_adapter_with_the_original_payload(consumer, tmp_path):
    log = tmp_path / "log"
    payload = pretool(consumer, "deny-me --flag")
    result = shim_command("claude", "pre-tool-use", payload, log=log)
    assert denial(result) == "stub deny"
    (call,) = calls(log)
    assert call["event"] == "pre-tool-use" and call["shim"] == "1" and Path(call["cwd"]) == consumer.resolve()
    assert json.loads(call["payload"]) == payload
    state = cf_shim.status("claude", consumer)
    assert call["adapter_digest"] == state["adapter"]["digest"]


@pytest.mark.parametrize("client,event,payload_key", [("claude", "pre-tool-use", "cwd"), ("codex", "pre-tool-use", "cwd")])
def test_claude_and_codex_resolve_the_consumer_from_the_hook_cwd(consumer, tmp_path, client, event, payload_key):
    sub = consumer / "scripts"
    log = tmp_path / "log"
    shim_command(client, event, {"session_id": SESSION, payload_key: str(sub), "tool_name": "Bash", "tool_input": {"command": "ls"}}, log=log)
    assert calls(log)[0]["client"] == client


def test_cursor_resolves_from_workspace_roots_and_runs_the_handler_script(consumer, tmp_path):
    log = tmp_path / "log"
    result = shim_command("cursor", "guard", {"conversation_id": SESSION, "workspace_roots": [str(consumer)], "command": "deny-me"}, log=log)
    assert last_json(result)["permission"] == "deny"
    assert "process-fsm-guard.sh guard" not in log.read_text() and "process-fsm-guard.sh" in log.read_text()
    assert f"cwd={consumer.resolve()}" in log.read_text()


def test_cursor_roots_in_different_consumers_are_ambiguous(consumer, tmp_path):
    other = make_consumer(tmp_path / "consumer-other")
    trust_all(other)
    result = shim_command("cursor", "guard", {"conversation_id": SESSION, "workspace_roots": [str(consumer), str(other)]})
    assert "consumer_ambiguous" in last_json(result)["agent_message"]


def test_unreviewed_adapter_denies_gating_events_in_the_native_format_and_never_runs(tmp_path, account):
    root = make_consumer(tmp_path / "fresh")
    install_account()
    cf_shim.record("claude", None)  # registration reviewed, adapter not
    log = tmp_path / "log"
    result = shim_command("claude", "pre-tool-use", pretool(root, "ls"), log=log)
    reason = denial(result)
    assert reason and "hooks_unreviewed" in reason and "trust --record" in reason
    assert calls(log) == []
    cursor = shim_command("cursor", "guard", {"conversation_id": SESSION, "workspace_roots": [str(root)]}, log=log)
    assert last_json(cursor)["permission"] == "deny" and "hooks_unreviewed" in last_json(cursor)["agent_message"]


def test_unreviewed_registration_is_visible_even_with_a_reviewed_adapter(tmp_path, account):
    root = make_consumer(tmp_path / "fresh")
    install_account()
    state = cf_shim.status("claude", root)
    cf_shim.record_review("adapter", "claude", state["adapter"]["digest"], {})
    reason = denial(shim_command("claude", "pre-tool-use", pretool(root)))
    assert reason and "hooks_unreviewed" in reason and "account registration" in reason


def test_session_start_shows_the_reason_on_the_page_instead_of_denying(tmp_path, account):
    root = make_consumer(tmp_path / "fresh")
    install_account()
    out = last_json(shim_command("claude", "session-start", {"session_id": SESSION, "cwd": str(root)}))
    assert "hooks_unreviewed" in out["hookSpecificOutput"]["additionalContext"]
    cursor = last_json(shim_command("cursor", "session-start", {"conversation_id": SESSION, "workspace_roots": [str(root)]}))
    assert "hooks_unreviewed" in cursor["additional_context"]


def test_missing_adapter_file_is_adapter_missing(consumer):
    (consumer / "scripts/process-fsm/other_module.py").unlink()
    reason = denial(shim_command("claude", "pre-tool-use", pretool(consumer)))
    assert "adapter_missing" in reason and "other_module.py" in reason and "install.sh --pin" in reason


def test_one_changed_byte_is_adapter_divergent(consumer):
    path = consumer / "scripts/process-fsm/claude_adapter.py"
    path.write_text(path.read_text() + "# tampered\n")
    reason = denial(shim_command("claude", "pre-tool-use", pretool(consumer)))
    assert "adapter_divergent" in reason and "claude_adapter.py" in reason


def test_a_new_unlisted_file_in_a_declared_tree_is_divergent(consumer):
    write(consumer / "scripts/process-fsm/sneaky.py", "print(1)\n")
    assert "adapter_divergent" in denial(shim_command("claude", "pre-tool-use", pretool(consumer)))
    # tests and fixtures stay outside the adapter set
    (consumer / "scripts/process-fsm/sneaky.py").unlink()
    write(consumer / "scripts/process-fsm/test_new.py", "x = 1\n")
    write(consumer / "scripts/process-fsm/__pycache__/x.pyc", "z")
    assert denial(shim_command("claude", "pre-tool-use", pretool(consumer))) is None


def test_incompatible_shim_protocol_is_shim_incompatible(consumer):
    manifest = json.loads((consumer / cf_shim.MANIFEST).read_text())
    manifest["shim_protocol"] = 99
    (consumer / cf_shim.MANIFEST).write_text(json.dumps(manifest))
    reason = denial(shim_command("claude", "pre-tool-use", pretool(consumer)))
    assert "shim_incompatible" in reason and "install.sh --account" in reason


def test_unreadable_manifest_is_a_visible_failure_not_an_old_pin(consumer):
    (consumer / cf_shim.MANIFEST).write_text("{broken")
    assert "manifest_invalid" in denial(shim_command("claude", "pre-tool-use", pretool(consumer)))


def test_shim_failure_never_blocks_events_that_do_not_gate(consumer):
    (consumer / "scripts/process-fsm/other_module.py").unlink()
    for event in ("post-tool-use", "stop", "subagent-stop"):
        result = shim_command("claude", event, {"session_id": SESSION, "cwd": str(consumer), "tool_name": "Bash"})
        assert result.returncode == 0 and result.stdout == ""


def test_spawn_is_denied_when_the_registration_changed_after_the_session_started(consumer):
    shim_command("claude", "session-start", {"session_id": SESSION, "cwd": str(consumer)})
    spawn = pretool(consumer, tool="Agent")
    assert denial(shim_command("claude", "pre-tool-use", spawn)) is None
    settings = Path.home() / ".claude/settings.json"
    document = json.loads(settings.read_text())
    document["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 31
    settings.write_text(json.dumps(document))
    cf_shim.record("claude", consumer)  # reviewed, but the session still runs the registration it loaded
    reason = denial(shim_command("claude", "pre-tool-use", spawn))
    assert "hooks_changed" in reason and "new session" in reason
    assert denial(shim_command("claude", "pre-tool-use", pretool(consumer))) is None  # plain tools keep working


# --- trust in two parts ------------------------------------------------------------


def test_installing_and_pinning_never_record_trust(tmp_path, account):
    make_consumer(tmp_path / "c")
    install_account()
    assert not cf_shim.trust_path().exists()
    assert cf_shim.status("claude", tmp_path / "c")["registration"]["reviewed"] is False


def test_changing_one_byte_of_hook_lib_or_a_detector_module_makes_A_unreviewed(consumer, tmp_path):
    before = cf_shim.status("claude", consumer)["adapter"]
    assert before["reviewed"]
    for relative in (".agents/skills/impeccable/scripts/hook-lib.mjs", ".agents/skills/impeccable/scripts/detector/rules.mjs"):
        path = consumer / relative
        original = path.read_text()
        path.write_text(original + "// x\n")
        diverged = cf_shim.status("claude", consumer)["adapter"]
        assert not diverged["reviewed"] and diverged["divergent"], relative
        # the pin is re-run: the manifest follows the new bytes, but the digest is a new one the operator never reviewed
        adapter_manifest.write(consumer, "v1.2.1")
        repinned = cf_shim.status("claude", consumer)["adapter"]
        assert not repinned["divergent"] and repinned["digest"] != before["digest"] and not repinned["reviewed"]
        assert "hooks_unreviewed" in denial(shim_command("claude", "pre-tool-use", pretool(consumer)))
        path.write_text(original)
        adapter_manifest.write(consumer, "v1.2.0")
        assert cf_shim.status("claude", consumer)["adapter"]["reviewed"]


def test_a_new_reviewed_adapter_is_accepted_without_a_new_heartbeat_even_between_worktrees(consumer, tmp_path):
    shim_command("claude", "session-start", {"session_id": SESSION, "cwd": str(consumer)})
    beat_before = cf_shim.read_heartbeat("claude", SESSION)
    other = make_consumer(tmp_path / "consumer-2000", branch="card-2000-other")
    write(other / "scripts/process-fsm/other_module.py", "VALUE = 2\n")  # a different adapter
    adapter_manifest.write(other, "v1.2.0")
    assert cf_shim.status("claude", other)["adapter"]["digest"] != cf_shim.status("claude", consumer)["adapter"]["digest"]
    assert "hooks_unreviewed" in denial(shim_command("claude", "pre-tool-use", pretool(other)))
    cf_shim.record("claude", other)
    log = tmp_path / "log"
    assert denial(shim_command("claude", "pre-tool-use", pretool(other, "deny-me"), log=log)) == "stub deny"
    assert denial(shim_command("claude", "pre-tool-use", pretool(consumer, "deny-me"), log=log)) == "stub deny"
    beat_after = cf_shim.read_heartbeat("claude", SESSION)
    assert beat_after["registration_digest"] == beat_before["registration_digest"] and beat_after["recorded_at"] == beat_before["recorded_at"]


def test_record_refuses_a_diverged_worktree_instead_of_reviewing_it(consumer):
    (consumer / "scripts/process-fsm/other_module.py").write_text("VALUE = 3\n")
    with pytest.raises(ValueError, match="differs from the pinned manifest"):
        cf_shim.record("claude", consumer)


def test_trust_cli_reports_and_records(consumer, tmp_path):
    import subprocess
    import sys

    shim = str(cf_shim.installed_shim_dir() / "cf_shim.py")
    status = subprocess.run([sys.executable, shim, "trust", "--status", "--client", "claude", "--cwd", str(consumer)], capture_output=True, text=True)
    assert status.returncode == 0 and json.loads(status.stdout)["adapter"]["reviewed"] is True
    (consumer / "scripts/process-fsm/other_module.py").write_text("VALUE = 9\n")
    adapter_manifest.write(consumer, "v1.2.0")
    status = subprocess.run([sys.executable, shim, "trust", "--status", "--client", "claude", "--cwd", str(consumer)], capture_output=True, text=True)
    assert status.returncode == 1
    # no terminal behind a subprocess pipe: the record is refused and nothing is written
    refused = subprocess.run([sys.executable, shim, "trust", "--record", "--client", "claude", "--cwd", str(consumer)], capture_output=True, text=True, input="record\n")
    assert refused.returncode == 2 and "recorded" not in refused.stdout
    assert not cf_shim.is_reviewed("adapter", "claude", cf_shim.status("claude", consumer)["adapter"]["digest"])


def test_trust_record_without_client_and_without_a_registered_host_fails_visibly(tmp_path, account, capsys):
    root = make_consumer(tmp_path / "consumer-1101")  # no install --account: no host carries an entry
    code = cf_shim.main(["trust", "--record", "--cwd", str(root)])
    captured = capsys.readouterr()
    assert code != 0 and "no registered host; run install.sh --account" in captured.err
    assert "recorded" not in captured.out and not cf_shim.trust_path().exists()


# --- heartbeat and the worktree switch -----------------------------------------------


def test_session_start_in_any_folder_leaves_only_a_private_heartbeat(tmp_path, account):
    install_account()
    plain = tmp_path / "plain"
    plain.mkdir()
    result = shim_command("claude", "session-start", {"session_id": SESSION, "cwd": str(plain), "transcript_path": "/x/t.jsonl"},
                          env={"AI_AGENT": "claude-code_2-1-299_agent", "CLAUDE_CODE_ENTRYPOINT": "cli"})
    assert result.stdout == "" and result.returncode == 0
    path = cf_shim.heartbeat_path("claude", SESSION)
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    beat = cf_shim.read_heartbeat("claude", SESSION)
    assert beat["cwd"] == str(plain) and beat["last_root"] is None and beat["host_version"] == "2.1.299" and beat["entrypoint"] == "cli"
    assert beat["registration_digest"] == cf_shim.registration_digest("claude")


def test_session_launched_outside_the_worktree_and_switched_into_it_is_active(consumer, tmp_path):
    source = tmp_path / "source-checkout"
    source.mkdir()
    log = tmp_path / "log"
    started = shim_command("claude", "session-start", {"session_id": SESSION, "cwd": str(source), "transcript_path": "/a/t.jsonl"}, log=log)
    assert started.stdout == "" and calls(log) == []
    # the host does not fire SessionStart on EnterWorktree: the PostToolUse(EnterWorktree) hook reinjects the page
    entered = shim_command("claude", "post-tool-use", {"session_id": SESSION, "cwd": str(consumer), "transcript_path": "/b/t.jsonl",
                                                       "tool_name": "EnterWorktree", "hook_event_name": "PostToolUse"}, log=log)
    out = last_json(entered)
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "bound_card=1101" in out["hookSpecificOutput"]["additionalContext"]
    (call,) = calls(log)
    assert call["event"] == "session-start" and Path(call["cwd"]) == consumer.resolve()
    # the Guard of the new worktree decides from the very next event
    assert denial(shim_command("claude", "pre-tool-use", pretool(consumer, "deny-me"), log=log)) == "stub deny"
    beat = cf_shim.read_heartbeat("claude", SESSION)
    assert beat["last_root"] == str(consumer.resolve()) and beat["transcript_path"] == "/b/t.jsonl"
    assert beat["registration_digest"] == cf_shim.registration_digest("claude")  # the session's own anchor


def test_switch_from_a_pin_before_account_registration_to_a_new_pin_and_back(tmp_path, account):
    old = make_consumer(tmp_path / "old", manifest=False)
    new = make_consumer(tmp_path / "new")
    install_account()
    trust_all(new)
    log = tmp_path / "log"
    assert shim_command("claude", "pre-tool-use", pretool(old, "deny-me"), log=log).stdout == ""
    assert denial(shim_command("claude", "pre-tool-use", pretool(new, "deny-me"), log=log)) == "stub deny"
    assert shim_command("claude", "pre-tool-use", pretool(old, "deny-me"), log=log).stdout == ""
    assert len(calls(log)) == 1  # each hook runs exactly once, from the registration that owns it


def test_claude_entry_stays_quiet_inside_cursor_that_also_loads_claude_settings(consumer, tmp_path):
    log = tmp_path / "log"
    result = shim_command("claude", "pre-tool-use", pretool(consumer, "deny-me"), log=log, env={"CURSOR_VERSION": "2026.10.01"})
    assert result.stdout == "" and calls(log) == []


def test_internal_shim_error_on_a_gate_is_a_visible_deny(consumer, monkeypatch):
    monkeypatch.setattr(cf_shim, "decide", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    import io
    import contextlib

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cf_shim.handle_hook("claude", "pre-tool-use", json.dumps(pretool(consumer)).encode(), {})
    document = json.loads(out.getvalue())
    assert code == 0 and "shim_error" in document["hookSpecificOutput"]["permissionDecisionReason"]


def test_invalid_payload_is_not_a_crash(consumer, tmp_path):
    result = shim_command("claude", "pre-tool-use", "not json")
    assert result.returncode == 0  # no cwd in the payload: the process cwd (not a consumer) decides


# --- OpenCode bridge ----------------------------------------------------------------


def test_opencode_decide_lists_the_pinned_modules_or_the_visible_failure(consumer, tmp_path):
    import subprocess
    import sys

    shim = str(cf_shim.installed_shim_dir() / "cf_shim.py")
    ok = json.loads(subprocess.run([sys.executable, shim, "opencode", "decide", "--cwd", str(consumer)], capture_output=True, text=True).stdout)
    assert ok["action"] == "run" and ok["modules"][0].endswith(".opencode/adapter/process-fsm-guard.js")
    none = json.loads(subprocess.run([sys.executable, shim, "opencode", "decide", "--cwd", str(tmp_path)], capture_output=True, text=True).stdout)
    assert none["action"] == "none"
    (consumer / ".opencode/adapter/impeccable-hook.js").unlink()
    broken = json.loads(subprocess.run([sys.executable, shim, "opencode", "decide", "--cwd", str(consumer), "--tool", "write"], capture_output=True, text=True).stdout)
    assert broken["action"] == "fail" and broken["code"] == "adapter_missing" and "install.sh --pin" in broken["message"]


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for the OpenCode plugin")
def test_opencode_global_plugin_loads_pinned_modules_denies_on_failure_and_stays_silent_without_pin(consumer, tmp_path):
    import subprocess

    plugin_dir = Path.home() / ".config/opencode/plugin"
    assert (plugin_dir / cf_shim.OPENCODE_PLUGIN_NAME).read_text().startswith(cf_shim.OPENCODE_PLUGIN_HEADER)
    log = tmp_path / "log"
    runner = tmp_path / "run.mjs"
    runner.write_text(f"""
import plugin from {json.dumps(str(plugin_dir / cf_shim.OPENCODE_PLUGIN_NAME))};
const dir = process.argv[2];
const hooks = await plugin({{ directory: dir }});
const out = [];
for (const [tool, args] of [["bash", {{ command: "ls" }}], ["bash", {{ command: "deny-me" }}], ["read", {{}}]]) {{
  try {{ await hooks["tool.execute.before"]({{ tool }}, {{ args }}); out.push(tool + ":ok"); }} catch (e) {{ out.push(tool + ":" + e.message); }}
}}
console.log(JSON.stringify(out));
""")
    env = {"CF_TEST_LOG": str(log), "HOME": str(Path.home()), "PATH": __import__("os").environ["PATH"]}
    pinned = json.loads(subprocess.run(["node", str(runner), str(consumer)], capture_output=True, text=True, env=env).stdout)
    assert pinned == ["bash:ok", "bash:stub deny", "read:ok"]
    assert "opencode-init" in log.read_text()
    # a broken pin denies the gating tools, reading stays open
    (consumer / ".opencode/adapter/impeccable-hook.js").unlink()
    broken = json.loads(subprocess.run(["node", str(runner), str(consumer)], capture_output=True, text=True, env=env).stdout)
    assert "adapter_missing" in broken[0] and "adapter_missing" in broken[1] and broken[2] == "read:ok"
    # no pin: nothing happens at all
    plain = tmp_path / "plain"
    plain.mkdir()
    none = json.loads(subprocess.run(["node", str(runner), str(plain)], capture_output=True, text=True, env=env).stdout)
    assert none == ["bash:ok", "bash:ok", "read:ok"]


# --- trust is the operator's act (R15) -----------------------------------------------------------------


def test_the_operator_records_trust_with_a_terminal_and_a_typed_confirmation(consumer, monkeypatch, capsys):
    (consumer / "scripts/process-fsm/other_module.py").write_text("VALUE = 9\n")
    adapter_manifest.write(consumer, "v1.2.0")
    assert not cf_shim.status("claude", consumer)["adapter"]["reviewed"]
    assert record_trust_as_operator(monkeypatch, "claude", consumer) == 0
    recorded = json.loads(capsys.readouterr().out)["recorded"]
    assert {item["part"] for item in recorded} == {"registration", "adapter"}
    assert cf_shim.status("claude", consumer)["adapter"]["reviewed"]


@pytest.mark.parametrize("environ,agent", [
    ({"CLAUDECODE": "1"}, "claude"),
    ({"CLAUDE_CODE_ENTRYPOINT": "claude-desktop"}, "claude"),
    ({"AI_AGENT": "claude-code_2-1-295_agent"}, "claude"),
    ({"CODEX_THREAD_ID": "thread-1"}, "codex"),
    ({"CURSOR_AGENT": "1"}, "cursor"),
    ({"OPENCODE": "1"}, "opencode"),
])
def test_trust_record_is_refused_inside_an_agent_session_of_any_registered_client(consumer, monkeypatch, capsys, environ, agent):
    before = cf_shim.trust_path().read_bytes()
    for name, value in environ.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(cf_shim, "operator_confirmed", lambda *a, **k: True)  # even a typed confirmation does not make an agent the operator
    assert cf_shim.main(["trust", "--record", "--client", "claude", "--cwd", str(consumer)]) == 2
    err = capsys.readouterr().err
    assert f"refused inside a {agent} agent session" in err and "plain terminal" in err
    assert cf_shim.trust_path().read_bytes() == before


def test_an_agent_ancestor_in_the_process_tree_is_an_agent_session_even_without_environment(tmp_path):
    for pid, ppid, argv in ((40, 30, ["python3", "cf_shim.py"]), (30, 20, ["bash"]), (20, 10, ["node", "/home/u/.local/bin/claude"]), (10, 1, ["init"])):
        directory = tmp_path / str(pid)
        directory.mkdir()
        (directory / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (directory / "stat").write_text(f"{pid} (proc) S {ppid} 0 0\n")
    assert cf_shim.agent_session({}, tmp_path, 40) == "claude"
    assert cf_shim.agent_session({}, tmp_path, 10) is None
    assert cf_shim.agent_session({}, tmp_path / "missing", 40) is None


def test_the_confirmation_needs_a_terminal_at_both_ends_and_the_typed_word():
    class Stream:
        def __init__(self, tty, line=""):
            self.tty, self.line, self.out = tty, line, ""

        def isatty(self):
            return self.tty

        def readline(self):
            return self.line

        def write(self, text):
            self.out += text

        def flush(self):
            pass

    assert cf_shim.operator_confirmed("s", Stream(False, "record\n"), Stream(True)) is False
    assert cf_shim.operator_confirmed("s", Stream(True, "record\n"), Stream(False)) is False
    assert cf_shim.operator_confirmed("s", Stream(True, "yes\n"), Stream(True)) is False
    assert cf_shim.operator_confirmed("s", Stream(True, "record\n"), Stream(True)) is True


# --- the registration digest is anchored at startup only (R8) ---------------------------------------------


@pytest.mark.parametrize("source", ["compact", "clear", "resume"])
def test_compact_clear_and_resume_keep_the_startup_registration_digest(consumer, source):
    shim_command("claude", "session-start", {"session_id": SESSION, "cwd": str(consumer), "source": "startup"})
    anchor = cf_shim.read_heartbeat("claude", SESSION)
    spawn = pretool(consumer, tool="Agent")
    assert denial(shim_command("claude", "pre-tool-use", spawn)) is None
    settings = Path.home() / ".claude/settings.json"
    document = json.loads(settings.read_text())
    document["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 33
    settings.write_text(json.dumps(document))
    cf_shim.record("claude", consumer)  # the operator reviewed the new registration; the running session still holds the old one
    shim_command("claude", "session-start", {"session_id": SESSION, "cwd": str(consumer), "source": source})
    after = cf_shim.read_heartbeat("claude", SESSION)
    assert after["registration_digest"] == anchor["registration_digest"] and after["recorded_at"] == anchor["recorded_at"]
    reason = denial(shim_command("claude", "pre-tool-use", spawn))
    assert reason and "hooks_changed" in reason
    # a real startup is a new session: it anchors the registration it loaded
    shim_command("claude", "session-start", {"session_id": SESSION, "cwd": str(consumer), "source": "startup"})
    assert cf_shim.read_heartbeat("claude", SESSION)["registration_digest"] == cf_shim.registration_digest("claude")
    assert denial(shim_command("claude", "pre-tool-use", spawn)) is None


# --- who called the shim decides, not what the process inherited (R9) -------------------------------------


def test_codex_registration_called_from_a_process_that_inherited_cursor_variables_is_a_codex_call(consumer, tmp_path):
    log = tmp_path / "log"
    result = shim_command("codex", "pre-tool-use", pretool(consumer, "deny-me"), log=log, env={"CURSOR_VERSION": "2026.10.01", "CURSOR_PROJECT_DIR": str(consumer)})
    assert denial(result) == "stub deny"
    assert [call["client"] for call in calls(log)] == ["codex"]


def test_claude_code_started_from_a_cursor_terminal_keeps_its_gate(consumer, tmp_path):
    log = tmp_path / "log"
    inherited = {"CURSOR_VERSION": "2026.10.01", "CURSOR_PROJECT_DIR": str(consumer)}
    for identity in ({"CLAUDECODE": "1"}, {"CLAUDE_CODE_ENTRYPOINT": "cli"}, {"AI_AGENT": "claude-code_2-1-300_agent"}):
        result = shim_command("claude", "pre-tool-use", pretool(consumer, "deny-me"), log=log, env={**inherited, **identity})
        assert denial(result) == "stub deny", identity
    # Cursor itself loading ~/.claude/settings.json carries no Claude Code identity: still quiet there
    quiet = shim_command("claude", "pre-tool-use", pretool(consumer, "deny-me"), log=log, env=inherited)
    assert quiet.stdout == ""


# --- nested repositories (R11) ----------------------------------------------------------------------------


def test_a_nested_repository_without_overlay_inside_a_pinned_consumer_is_governed_by_the_consumer(consumer, tmp_path):
    from shim_fixtures import init_git
    nested = init_git(consumer / "vendor" / "scratch-clone")
    assert not (nested / ".covenant-flow").exists()
    log = tmp_path / "log"
    result = shim_command("claude", "pre-tool-use", pretool(nested, "deny-me"), log=log)
    assert denial(result) == "stub deny"
    assert Path(calls(log)[0]["cwd"]) == consumer.resolve()
    assert cf_shim.discover([str(nested)]) == (consumer.resolve(), False)
    # a nested repository with no consumer around it still means no consumer
    lone = init_git(tmp_path / "elsewhere" / "lone")
    assert cf_shim.discover([str(lone)]) == (None, False)


# --- the heartbeat records the surface and the app (4.1) and the roots the session touched (R16) -----------


def test_the_heartbeat_records_the_desktop_app_surface_and_versions(tmp_path, account):
    install_account()
    plain = tmp_path / "plain"
    plain.mkdir()
    env = {"AI_AGENT": "claude-code_2-1-295_agent", "CLAUDE_CODE_ENTRYPOINT": "claude-desktop", "CLAUDE_CODE_DESKTOP_APP_VERSION": "2.37337.1", "CLAUDE_SSH_DAEMON_CHILD": "1"}
    shim_command("claude", "session-start", {"session_id": SESSION, "cwd": str(plain), "source": "startup"}, env=env)
    beat = cf_shim.read_heartbeat("claude", SESSION)
    assert (beat["entrypoint"], beat["host_version"], beat["desktop_app_version"], beat["ssh"]) == ("claude-desktop", "2.1.295", "2.37337.1", True)
    terminal = "22222222-2222-3333-4444-555555555555"
    shim_command("claude", "session-start", {"session_id": terminal, "cwd": str(plain)}, env={"AI_AGENT": "claude-code_2-1-300_agent", "CLAUDE_CODE_ENTRYPOINT": "cli"})
    beat = cf_shim.read_heartbeat("claude", terminal)
    assert (beat["entrypoint"], beat["host_version"], beat["desktop_app_version"], beat["ssh"]) == ("cli", "2.1.300", cf_shim.UNAVAILABLE, False)


def test_the_heartbeat_follows_the_roots_a_session_touches_with_their_pins(consumer, tmp_path):
    shim_command("claude", "session-start", {"session_id": SESSION, "cwd": str(consumer)})
    other = make_consumer(tmp_path / "consumer-2000", pin="v1.3.0", branch="card-2000-other")
    trust_all(other)
    shim_command("claude", "pre-tool-use", pretool(other))
    roots = {item["root"]: item["pin"] for item in cf_shim.read_heartbeat("claude", SESSION)["roots"]}
    assert roots == {str(consumer.resolve()): "v1.2.0", str(other.resolve()): "v1.3.0"}
    assert cf_shim.mixed_pins(cf_shim.read_heartbeat("claude", SESSION)["roots"]) == roots
    assert cf_shim.mixed_pins([{"root": "/a", "pin": "v1.2.0"}, {"root": "/b", "pin": "v1.2.0"}]) == {}


# --- OpenCode: an import() failure never blocks reading (R12) ----------------------------------------------


@pytest.mark.skipif(shutil.which("node") is None, reason="node is required for the OpenCode plugin")
def test_opencode_adapter_that_fails_to_import_blocks_write_shell_and_spawn_but_never_read(consumer, tmp_path):
    import os
    import subprocess

    plugin_dir = Path.home() / ".config/opencode/plugin"
    (consumer / ".opencode/adapter/impeccable-hook.js").write_text("throw new Error('cannot start');\n")
    adapter_manifest.write(consumer, "v1.2.0")
    cf_shim.record("opencode", consumer)
    runner = tmp_path / "run.mjs"
    runner.write_text(f"""
import plugin from {json.dumps(str(plugin_dir / cf_shim.OPENCODE_PLUGIN_NAME))};
const hooks = await plugin({{ directory: process.argv[2] }});
const out = [];
for (const tool of ["read", "glob", "grep", "write", "edit", "bash", "task"]) {{
  try {{ await hooks["tool.execute.before"]({{ tool }}, {{ args: {{ command: "ls" }} }}); out.push(tool + ":ok"); }} catch (e) {{ out.push(tool + ":" + e.message); }}
}}
console.log(JSON.stringify(out));
""")
    env = {"HOME": str(Path.home()), "PATH": os.environ["PATH"]}
    out = json.loads(subprocess.run(["node", str(runner), str(consumer)], capture_output=True, text=True, env=env).stdout)
    assert out[:3] == ["read:ok", "glob:ok", "grep:ok"]
    for denied in out[3:]:
        assert "deny reason=adapter_missing" in denied and "cannot start" in denied, denied
