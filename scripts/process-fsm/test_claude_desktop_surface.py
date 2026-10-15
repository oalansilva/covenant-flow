"""The desktop app over SSH as a surface of the `claude` client, and the background return of a child (#1103).

The records come from REAL sessions (`APP_SESSION_2_1_295`, `CLI_BACKGROUND_2_1_300` in `claude_fixtures.py`), sanitized.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

import claude_adapter
import claude_evidence as ev
import claude_proxy
import model_selection
from claude_fixtures import (
    APP_SESSION_2_1_295,
    CLI_BACKGROUND_2_1_300,
    SESSION,
    World,
    app_world,
    background_world,
    git_repo,
    record,
    trust_ok,
    write_jsonl,
)
from model_selection_fixtures import machine_models  # noqa: F401  (autouse isolated account)
from paging import page
from test_overlay_fixtures import write_overlay

APP_AGENT = APP_SESSION_2_1_295["agent_id"]


def blocked(world, birth_path):
    with pytest.raises(ev.EvidenceError) as e:
        world.collect(birth_path)
    return e.value


def fake_path_claude(tmp_path: Path, monkeypatch, version="2.1.300") -> Path:
    """A `claude` on PATH that records being run: the terminal binary, which is NOT the host of the app session."""

    bin_dir = tmp_path / "terminal-bin"
    bin_dir.mkdir()
    marker = tmp_path / "claude-was-run"
    script = bin_dir / "claude"
    script.write_text(f"#!/bin/sh\necho ran >> {marker}\necho '{version} (Claude Code)'\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    return marker


# --- the fixtures are real, sanitized and say what they are ---------------------------------------------------


def test_the_fixtures_carry_no_machine_session_or_content_residue():
    text = json.dumps([APP_SESSION_2_1_295, CLI_BACKGROUND_2_1_300])
    for needle in ("/home/", "/srv/apps", "oalansilva", "92c55543", "4e409c23", "676794ee", "ubuntu"):
        assert needle not in text, needle
    assert APP_SESSION_2_1_295["entrypoint"] == "claude-desktop" and APP_SESSION_2_1_295["version"] == "2.1.295"
    assert CLI_BACKGROUND_2_1_300["entrypoint"] == "cli" and CLI_BACKGROUND_2_1_300["version"] == "2.1.300"
    surfaces = {row.get("entrypoint") for row in APP_SESSION_2_1_295["parent_rows"] + APP_SESSION_2_1_295["child_rows"] if row.get("entrypoint")}
    assert surfaces == {"claude-desktop"}


def test_claude_desktop_is_a_known_surface_only_next_to_its_real_fixture():
    assert ev.QUALIFIED_ENTRYPOINTS == ("cli", "claude-desktop")
    assert APP_SESSION_2_1_295["parent_rows"] and APP_SESSION_2_1_295["child_rows"]


# --- 4.4: prepare and collect on the real app transcript -------------------------------------------------------


def test_prepare_on_the_real_app_session_records_the_surface_and_both_versions(tmp_path):
    world = app_world(tmp_path)
    cap, _path, _task, prepared = world.prepare("grill-card")
    assert (prepared["surface"], prepared["host_version"]) == ("claude-desktop", "2.1.295")
    birth = json.loads(Path(prepared["birth"]).read_text())
    assert (birth["surface"], birth["host_version"], birth["host_versions"]) == ("claude-desktop", "2.1.295", ["2.1.295"])
    assert birth["task_name"] == "grill-card #1103" and birth["bound_card"] == "1103" and cap["role"] == "grill-card"


def test_the_unmodified_real_app_child_was_launched_without_effort_and_the_collector_says_so(tmp_path):
    world = app_world(tmp_path)
    _cap, _path, _task, prepared = world.prepare("grill-card")
    world.launch_app_child()  # exactly what the app wrote: no `effort` in the spawn
    err = blocked(world, prepared["birth"])
    assert err.code == "unsupported_schema" and "`input.effort`" in str(err) and "2.1.295" in str(err)


def test_collect_on_the_real_app_child_with_an_explicit_effort_and_the_proxy_line(tmp_path, capsys):
    world = app_world(tmp_path)
    cap, path, _task, prepared = world.prepare("grill-card")
    world.launch_app_child(effort="medium")  # the single field the app did not send; every other byte is the real record
    result = world.collect(prepared["birth"])
    assert (result["status"], result["surface"], result["host_version"]) == ("completed", "claude-desktop", "2.1.295")
    assert result["requested"] == {"model": "claude-opus-5-5", "effort": "medium"} and ev.observed_pair(result) == result["requested"]
    assert result["child_agent_id"] == APP_AGENT and result["spawn_status"] == "completed"
    assert "SubagentHandback" in result["tools_used"] and result["payload_returned"] is True
    code = claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", "grill-card", "--band", "juizo", "--birth", prepared["birth"], "--wait-seconds", "0"])
    assert code == 0, capsys.readouterr()
    entry = json.loads(capsys.readouterr().out)
    assert (entry["client"], entry["surface"], entry["host_version"], entry["successful"]) == ("claude", "claude-desktop", "2.1.295", True)
    assert (entry["observed_model"], entry["observed_effort"]) == ("claude-opus-5-5", "medium")


def test_a_notification_for_another_tool_call_of_the_real_app_agent_is_not_this_return(tmp_path):
    world = app_world(tmp_path)
    cap, _path, _task, prepared = world.prepare("grill-card")
    world.launch_app_child(effort="medium")
    notes = [r for r in world.rows if r.get("type") == "queue-operation" and "<task-notification>" in str(r.get("content"))]
    assert notes and APP_AGENT in notes[0]["content"] and APP_SESSION_2_1_295["spawn_call_id"] not in notes[0]["content"]
    # the real return is the foreground result; the SendMessage notification adds nothing to it and breaks nothing
    assert world.collect(prepared["birth"])["status"] == "completed"


def test_a_session_started_in_the_app_and_resumed_in_the_terminal_is_unverified_for_prepare_and_collect(tmp_path):
    world = app_world(tmp_path)
    world.rows.append(record("assistant", world.repo, entrypoint="cli", version="2.1.300", message={"model": "claude-opus-5-5", "id": "m-cli", "role": "assistant", "content": []}, effort="medium"))
    world.flush()
    with pytest.raises(ev.EvidenceError) as e:
        world.prepare("grill-card")
    assert e.value.code == "unverified" and "claude-desktop" in str(e.value) and "cli" in str(e.value) and "more than one surface" in str(e.value)
    clean = app_world(tmp_path / "second")
    _cap, _path, _task, prepared = clean.prepare("grill-card")
    clean.launch_app_child(effort="medium")
    clean.rows.append(record("user", clean.repo, entrypoint="cli", version="2.1.300", message={"role": "user", "content": "back in the terminal"}))
    clean.flush()
    err = blocked(clean, prepared["birth"])
    assert err.code == "unverified" and "more than one surface" in str(err)


def test_an_app_surface_that_is_not_the_rehearsed_one_still_stops_the_stage(tmp_path):
    world = app_world(tmp_path)
    world.rows = [dict(r, entrypoint="claude-desktop-next") for r in world.rows]
    world.flush()
    with pytest.raises(ev.EvidenceError) as e:
        world.prepare("grill-card")
    assert e.value.code == "unverified" and "claude-desktop-next" in str(e.value)


def test_the_receipt_evidence_and_proxy_carry_the_desktop_app_version_and_the_ssh_mark(tmp_path, monkeypatch, capsys):
    world = app_world(tmp_path)
    beat = {"transcript_path": str(world.parent), "recorded_at": "2026-10-15T00:00:00Z", "desktop_app_version": "2.37337.1", "ssh": True}
    monkeypatch.setattr(ev.account_registration, "require_active", lambda *a, **k: {"heartbeat": beat, "status": {"adapter": {"digest": "d" * 64}}})
    cap, path, _task, prepared = world.prepare("grill-card")
    world.launch_app_child(effort="medium")
    birth = json.loads(Path(prepared["birth"]).read_text())
    assert (birth["desktop_app_version"], birth["ssh"]) == ("2.37337.1", True)
    result = world.collect(prepared["birth"])
    assert (result["desktop_app_version"], result["ssh"]) == ("2.37337.1", True)
    assert claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", "grill-card", "--band", "juizo", "--birth", prepared["birth"], "--wait-seconds", "0"]) == 0
    entry = json.loads(capsys.readouterr().out)
    assert (entry["desktop_app_version"], entry["ssh"]) == ("2.37337.1", True)
    line = claude_proxy.handoff_line(entry)
    assert "claude" in line and "claude-desktop" in line and "2.1.295" in line and "2.37337.1" in line
    assert "claude-opus-5-5/medium" in line and "completed" in line and "grill-card" in line and "1103" in line


# --- 4.2: the host version is the session's, never the binary on PATH ----------------------------------------------


def test_inside_a_session_the_binary_on_path_is_never_asked(tmp_path, monkeypatch):
    marker = fake_path_claude(tmp_path, monkeypatch, "2.1.300")
    assert model_selection.claude_detect_version({"CLAUDECODE": "1"}) is None
    assert model_selection.claude_detect_version({"CLAUDECODE": "1", "AI_AGENT": "claude-code_2-1-295_agent"}) == "2.1.295"
    assert not marker.exists()
    # outside any session (the operator's own shell) the fallback still measures the binary
    assert model_selection.claude_detect_version({}) == "2.1.300" and marker.exists()


def test_resolve_in_an_app_session_without_ai_agent_is_capability_unavailable_naming_the_surface(tmp_path, monkeypatch):
    marker = fake_path_claude(tmp_path, monkeypatch)
    monkeypatch.delenv("AI_AGENT")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "claude-desktop")
    with pytest.raises(model_selection.SelectionError) as e:
        model_selection.resolve("claude", "execucao", role="apply-coluna")
    assert "capability_unavailable" in str(e.value) and "claude-desktop" in str(e.value) and "never queried" in str(e.value)
    assert not marker.exists()


def test_prepare_in_an_app_session_without_ai_agent_is_capability_unavailable_naming_the_surface(tmp_path, monkeypatch):
    marker = fake_path_claude(tmp_path, monkeypatch)
    world = app_world(tmp_path)
    env = {k: v for k, v in world.env.items() if k != "AI_AGENT"}
    cap, path = world.capture("grill-card")
    with pytest.raises(ev.EvidenceError) as e:
        ev.prepare(root=world.repo, capture=path, task_name="grill-card #1103", runtime=world.runtime, session=SESSION, environ=env, trust=trust_ok)
    assert e.value.code == "capability_unavailable" and "claude-desktop" in str(e.value) and "AI_AGENT" in str(e.value)
    assert not marker.exists()


def test_heartbeat_receipt_and_proxy_record_the_app_copy_not_the_terminal_binary(tmp_path, monkeypatch, capsys):
    marker = fake_path_claude(tmp_path, monkeypatch, "2.1.300")  # PATH points to ANOTHER version than the app copy
    world = app_world(tmp_path)
    cap, path, _task, prepared = world.prepare("grill-card")
    world.launch_app_child(effort="medium")
    assert claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", "grill-card", "--band", "juizo", "--birth", prepared["birth"], "--wait-seconds", "0"]) == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["host_version"] == "2.1.295" and json.loads(Path(prepared["birth"]).read_text())["host_version"] == "2.1.295"
    assert not marker.exists()


def test_the_session_version_must_agree_with_the_transcript(tmp_path):
    world = app_world(tmp_path)
    env = dict(world.env, AI_AGENT="claude-code_2-1-300_agent")
    cap, path = world.capture("grill-card")
    with pytest.raises(ev.EvidenceError) as e:
        ev.prepare(root=world.repo, capture=path, task_name="grill-card #1103", runtime=world.runtime, session=SESSION, environ=env, trust=trust_ok)
    assert e.value.code == "capability_unavailable" and "2.1.300" in str(e.value) and "2.1.295" in str(e.value)


# --- 4.3: the hook floor (2.1.295) ----------------------------------------------------------------------------------


@pytest.mark.parametrize("version,ready", [("2.1.292", False), ("2.1.293", False), ("2.1.294", False), ("2.1.295", True), ("2.1.296", True)])
def test_births_and_hook_dependent_transitions_need_the_blocking_hook_floor(tmp_path, version, ready):
    world = World(tmp_path, version=version)
    if ready:
        assert ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)["host_version"] == version
        cap, path = world.capture("apply-coluna")
        assert ev.prepare(root=world.repo, capture=path, task_name="apply-coluna 1101 floor", runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)["result"] == "ready"
        return
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert e.value.code == "capability_unavailable" and "onFailure=block" in str(e.value) and "2.1.295" in str(e.value) and version in str(e.value)


def test_the_effort_floor_stays_at_2_1_292_and_the_hook_floor_is_the_code_constant():
    assert model_selection.CLAUDE_HOOK_MIN_VERSION == "2.1.295"
    contract = {"env_overrides": [], "host_min_version": "2.1.292"}
    model_selection.claude_host_checks(contract, {"version": "2.1.292", "environ": {}})
    with pytest.raises(model_selection.SelectionError, match="2.1.294"):
        model_selection.claude_hook_check("2.1.294")
    model_selection.claude_hook_check("2.1.295")
    with pytest.raises(model_selection.SelectionError):
        model_selection.claude_hook_check(None)


# --- 5.1: a final <synthetic> turn fails the child only with an API error ---------------------------------------------


def synthetic(world, *, error: bool):
    row = record("assistant", world.repo, isSidechain=True, uuid="u-syn", message={"model": "<synthetic>", "id": "syn", "role": "assistant", "content": [{"type": "text", "text": "No response requested."}]})
    row["agentId"] = "a0123456789abcdef"
    row["isApiErrorMessage"] = error
    if error:
        row["apiError"] = "rate_limit"
    return row


def test_a_final_synthetic_turn_without_an_api_error_leaves_the_status_to_the_last_real_turn(tmp_path):
    world = World(tmp_path)
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task, extra_child_rows=(synthetic(world, error=False),))
    result = world.collect(prepared["birth"])
    assert result["status"] == "completed" and result["synthetic_final"] is False and result["payload_returned"] is True
    assert ev.observed_pair(result) == {"model": "claude-sonnet-5-5", "effort": "high"}
    assert [t["api_error"] for t in result["synthetic_turns"]] == [False]


def test_a_final_synthetic_turn_that_records_an_api_error_fails_the_child(tmp_path):
    world = World(tmp_path)
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task, extra_child_rows=(synthetic(world, error=True),))
    result = world.collect(prepared["birth"])
    assert result["status"] == "failed" and result["synthetic_final"] is True and result["payload_returned"] is False
    assert [t["api_error"] for t in result["synthetic_turns"]] == [True]


# --- 5.5: the background return of a child ----------------------------------------------------------------------------


def background(tmp_path, name, **kw):
    world = background_world(tmp_path, name)
    cap, path, task, prepared = world.prepare(name)
    child = world.launch_background_child(name, **kw)
    return world, cap, path, prepared, child


def rewrite_notifications(*pairs):
    def apply(rows):
        for row in rows:
            if row.get("type") == "queue-operation":
                for old, new in pairs:
                    row["content"] = row["content"].replace(old, new)
    return apply


@pytest.mark.parametrize("name", ["design-autor", "design-critic"])
def test_the_real_background_children_of_the_1103_are_collected_completed_with_the_result_as_payload(tmp_path, name, capsys):
    world, cap, path, prepared, child = background(tmp_path, name)
    spawn_result = next(r for r in world.rows if isinstance(r.get("toolUseResult"), dict) and r["toolUseResult"].get("agentId") == child["agent_id"])
    assert spawn_result["toolUseResult"]["status"] == "async_launched" and spawn_result["toolUseResult"]["resolvedModel"] == "claude-opus-5-5"
    result = world.collect(prepared["birth"])
    assert result["status"] == "completed" and result["payload_returned"] is True and result["child_agent_id"] == child["agent_id"]
    assert result["payload_sha256"] == [ev.digest("[sanitized]".encode())] and result["spawn_status"] == "async_launched"
    assert (result["surface"], result["host_version"]) == ("cli", "2.1.300")
    assert ev.observed_pair(result) == {"model": "claude-opus-5-5", "effort": "high"} == result["requested"]
    assert claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", name, "--band", "juizo", "--birth", prepared["birth"], "--wait-seconds", "0"]) == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["successful"] is True and (entry["observed_model"], entry["observed_effort"]) == ("claude-opus-5-5", "high")


def test_a_background_child_whose_notification_says_failed_is_failed_and_an_unsuccessful_attempt(tmp_path, capsys):
    world, cap, path, prepared, _child = background(tmp_path, "design-autor", mutate=rewrite_notifications(("<status>completed</status>", "<status>failed</status>")))
    result = world.collect(prepared["birth"])
    assert result["status"] == "failed" and result["payload_returned"] is False and result["payload_sha256"] == []
    assert claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", "design-autor", "--band", "juizo", "--birth", prepared["birth"], "--wait-seconds", "0"]) == 0
    entry = json.loads(capsys.readouterr().out)
    assert entry["successful"] is False and entry["status"] == "failed"


def test_a_killed_background_child_is_interrupted(tmp_path):
    world, _cap, _path, prepared, _child = background(tmp_path, "design-critic", mutate=rewrite_notifications(("<status>completed</status>", "<status>killed</status>")))
    result = world.collect(prepared["birth"])
    assert result["status"] == "interrupted" and result["payload_returned"] is False


def test_a_notification_for_another_tool_call_is_not_this_childs_return(tmp_path):
    call_id = CLI_BACKGROUND_2_1_300["children"]["design-autor"]["call_id"]
    world, _cap, _path, prepared, child = background(tmp_path, "design-autor", mutate=rewrite_notifications((call_id, "toolu_SOMEONE_ELSES_CALL")))
    err = blocked(world, prepared["birth"])
    assert err.code == "terminal_unavailable"  # nothing is the return of this spawn: neither accepted nor an unknown form
    assert child["call_id"] == call_id


def test_a_notification_for_another_agent_is_ignored(tmp_path):
    world, _cap, _path, prepared, child = background(tmp_path, "design-autor", mutate=rewrite_notifications((f"<task-id>{CLI_BACKGROUND_2_1_300['children']['design-autor']['agent_id']}</task-id>", "<task-id>a99999999999999999</task-id>")))
    assert blocked(world, prepared["birth"]).code == "terminal_unavailable"


def test_a_return_form_the_driver_does_not_know_is_unsupported_schema_naming_the_field_not_terminal_unavailable_forever(tmp_path):
    agent = CLI_BACKGROUND_2_1_300["children"]["design-autor"]["agent_id"]
    unknown_form = rewrite_notifications(("<task-notification>", "<task-update>"), ("</task-notification>", "</task-update>"))
    world, _cap, _path, prepared, _child = background(tmp_path, "design-autor", mutate=unknown_form)
    err = blocked(world, prepared["birth"])
    assert err.code == "unsupported_schema" and "queue-operation.content" in str(err) and "2.1.300" in str(err)
    world2, _c, _p, prepared2, _ch = background(tmp_path / "status", "design-autor", mutate=rewrite_notifications(("<status>completed</status>", "<status>paused</status>")))
    err2 = blocked(world2, prepared2["birth"])
    assert err2.code == "unsupported_schema" and "<status>" in str(err2) and "paused" in str(err2)
    world3, _c3, _p3, prepared3, _ch3 = background(tmp_path / "id", "design-autor", mutate=rewrite_notifications(("<tool-use-id>", "<tool-id>"), ("</tool-use-id>", "</tool-id>")))
    assert blocked(world3, prepared3["birth"]).code == "unsupported_schema"
    assert agent  # the agent id is the real one of the fixture


def test_a_child_without_any_notification_yet_stays_terminal_unavailable(tmp_path):
    world = background_world(tmp_path, "design-autor")
    _cap, _path, _task, prepared = world.prepare("design-autor")
    world.launch_background_child("design-autor", mutate=lambda rows: rows.__delitem__(slice(2, None)))  # spawn and launch result only
    assert blocked(world, prepared["birth"]).code == "terminal_unavailable"


def test_a_completed_notification_with_an_empty_result_is_payload_unavailable(tmp_path):
    world, _cap, _path, prepared, _child = background(tmp_path, "design-autor", mutate=rewrite_notifications(("<result>[sanitized]</result>", "<result>   </result>")))
    assert blocked(world, prepared["birth"]).code == "payload_unavailable"


def test_a_background_spawn_without_resolved_model_is_checked_on_the_childs_turns(tmp_path):
    def drop_resolved(rows):
        for row in rows:
            if isinstance(row.get("toolUseResult"), dict):
                row["toolUseResult"].pop("resolvedModel", None)

    world, _cap, _path, prepared, _child = background(tmp_path, "design-autor", mutate=drop_resolved)
    result = world.collect(prepared["birth"])
    assert result["status"] == "completed" and result["resolved_model"] == ev.UNAVAILABLE and result["turns"]
    # a divergent turn of the child is still a model_mismatch: the check moved, it was not skipped
    world2 = background_world(tmp_path / "other", "design-critic")
    _c2, _p2, _t2, prepared2 = world2.prepare("design-critic")
    world2.launch_background_child("design-critic", mutate=drop_resolved)
    child_file = next(world2.subdir.glob("agent-*.jsonl"))
    rows = [json.loads(line) for line in child_file.read_text().splitlines()]
    for row in rows:
        if row.get("type") == "assistant":
            row["message"]["model"] = "claude-sonnet-5-5"
    write_jsonl(child_file, rows)
    assert blocked(world2, prepared2["birth"]).code == "model_mismatch"


def test_a_foreground_result_may_not_omit_the_resolved_model(tmp_path):
    world = app_world(tmp_path)
    _cap, _path, _task, prepared = world.prepare("grill-card")

    def drop_resolved(rows):
        for row in rows:
            if isinstance(row.get("toolUseResult"), dict):
                row["toolUseResult"].pop("resolvedModel", None)

    world.launch_app_child(effort="medium", mutate=drop_resolved)
    err = blocked(world, prepared["birth"])
    assert err.code == "unsupported_schema" and "`resolvedModel`" in str(err)


def test_the_post_agent_hook_does_not_invalidate_a_background_spawn_that_carries_no_resolved_model(tmp_path):
    world = background_world(tmp_path, "design-autor")
    cap, path, task, prepared = world.prepare("design-autor")
    arguments = {"description": task, "prompt": f"runtime_evidence_birth: {prepared['birth']}\nmodel_selection_capture: {path}", **cap["arguments"]}
    ok = ev.note_resolved_model(arguments, {"status": "async_launched", "agentId": "af0a1917b83c8aa19"}, world.repo)
    assert ok["ok"] is True and ok.get("deferred") is True and not ev.marked(Path(prepared["birth"]).parent, cap["attempt_id"], "model_mismatch")
    bad = ev.note_resolved_model(arguments, {"status": "async_launched", "resolvedModel": "claude-sonnet-5-5"}, world.repo)
    assert bad["ok"] is False and ev.marked(Path(prepared["birth"]).parent, cap["attempt_id"], "model_mismatch")


# --- 4.5: a folder created by the app is a folder without a card --------------------------------------------------------


def app_folder_repo(tmp_path: Path, branch="claude/swift-fox") -> Path:
    source = git_repo(tmp_path, "source")
    folder = source / ".claude" / "worktrees" / "swift-fox"
    subprocess.run(["git", "-C", str(source), "worktree", "add", "-q", "-b", branch, str(folder)], check=True, capture_output=True)
    write_overlay(folder)
    return folder


def test_the_page_names_the_app_folder_as_a_folder_without_a_card(tmp_path):
    folder = app_folder_repo(tmp_path)
    result = page(cwd=folder, path=folder, client="claude", status_provider=lambda _b: None)
    text = result["additional_context"]
    assert "pasta do app (sem card)" in text and "EnterWorktree" in text and "#<id>" in text and "bound_card=⊥" in text
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    plain = git_repo(elsewhere, "source")
    write_overlay(plain)
    assert "pasta do app" not in page(cwd=plain, path=plain, client="claude", status_provider=lambda _b: None)["additional_context"]
    assert "pasta do app" not in page(cwd=folder, path=folder, client="codex", status_provider=lambda _b: None)["additional_context"]


def test_a_configured_worktree_folder_is_recognized_too(tmp_path, monkeypatch):
    from resolve import app_folder

    configured = tmp_path / "app-worktrees"
    (configured / "bold-owl" / "src").mkdir(parents=True)
    settings = Path.home() / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"worktree": {"location": str(configured)}}))
    assert app_folder(configured / "bold-owl" / "src") == configured.resolve() / "bold-owl"
    assert app_folder(tmp_path / "somewhere-else") is None
    settings.write_text(json.dumps({"worktree.location": str(configured)}))
    assert app_folder(configured / "bold-owl") == configured.resolve() / "bold-owl"


def test_product_and_openspec_writes_are_denied_in_the_app_folder_with_the_recovery(tmp_path, monkeypatch):
    folder = app_folder_repo(tmp_path)
    monkeypatch.setattr(claude_adapter, "trust_status", lambda: {"reviewed": True, "digest": "d" * 64, "reason": ""})
    monkeypatch.setattr(claude_adapter, "github_status_provider", lambda _bound: None)
    for target in ("backend/api.py", "openspec/changes/card-1103-x/design.md"):
        decision = claude_adapter.pre_tool_use({"tool_name": "Write", "tool_input": {"file_path": str(folder / target), "content": "x"}, "cwd": str(folder), "session_id": SESSION})
        text = decision["hookSpecificOutput"]["permissionDecisionReason"]
        assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
        assert "pasta do app (sem card)" in text and "`#<id>`" in text and "EnterWorktree" in text, target
        assert not (folder / target).exists()
    shell = claude_adapter.pre_tool_use({"tool_name": "Bash", "tool_input": {"command": f"printf x > {folder}/backend/api.py"}, "cwd": str(folder), "session_id": SESSION})
    assert "pasta do app (sem card)" in shell["hookSpecificOutput"]["permissionDecisionReason"]
    assert folder.is_dir()  # nothing was deleted


def test_a_stage_child_is_not_born_in_the_app_folder(tmp_path, monkeypatch):
    folder = app_folder_repo(tmp_path)
    monkeypatch.setattr(claude_adapter, "trust_status", lambda: {"reviewed": True, "digest": "d" * 64, "reason": ""})
    decision = claude_adapter.pre_tool_use({"tool_name": "Agent", "tool_input": {"description": "apply-coluna 1103 x", "prompt": "p", "model": "sonnet", "effort": "high"}, "cwd": str(folder), "session_id": SESSION})
    assert "deny reason=app_folder" in decision["hookSpecificOutput"]["permissionDecisionReason"] and "EnterWorktree" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_prepare_and_process_event_refuse_the_app_folder_and_delete_nothing(tmp_path, monkeypatch):
    from process_event import FakeMover, process_event

    folder = app_folder_repo(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=folder, session=SESSION, environ=os.environ)
    assert e.value.code == "app_folder" and "pasta do app (sem card)" in str(e.value) and "EnterWorktree" in e.value.recovery
    cap = model_selection.resolve("claude", "execucao", role="apply-coluna")
    capture = tmp_path / "cap.json"
    model_selection.save_capture(capture, cap)
    with pytest.raises(ev.EvidenceError) as e:
        ev.prepare(root=folder, capture=capture, task_name="apply-coluna 1103 x", session=SESSION, environ=os.environ)
    assert e.value.code == "app_folder"
    mover = FakeMover()
    out = process_event("iniciar_design", cwd=folder, card="1103", mover=mover, client="claude", status="Todo")
    assert out["result"] == "reject" and out["reason"] == "claude_evidence:app_folder" and "pasta do app (sem card)" in out["message"] and mover.calls == []
    assert folder.is_dir() and (folder / ".git").exists()


# --- 4.7: the app's session tools with a bound card --------------------------------------------------------------------------


def card_worktree(tmp_path: Path) -> Path:
    import subprocess as sp

    work = git_repo(tmp_path, "card-1103-test")
    write_overlay(work)
    sp.run(["git", "-C", str(work), "checkout", "-q", "-B", "card-1103-test"], check=True, capture_output=True)
    return work


def ccd(tool, cwd, **extra):
    return claude_adapter.pre_tool_use({"tool_name": tool, "tool_input": {"x": 1}, "cwd": str(cwd), "session_id": SESSION, **extra})


@pytest.mark.parametrize("tool", sorted(claude_adapter.CCD_SESSION_TOOLS))
def test_session_creating_app_tools_are_denied_with_a_bound_card(tmp_path, tool):
    work = card_worktree(tmp_path)
    reason = ccd(tool, work)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "stage_child_only_agent" in reason and tool in reason and "`Agent`" in reason and "capture and receipt" in reason


@pytest.mark.parametrize("tool", sorted(claude_adapter.CCD_READ_LAYOUT_TOOLS))
def test_read_and_layout_app_tools_stay_free_with_a_bound_card(tmp_path, tool):
    assert ccd(tool, card_worktree(tmp_path)) is None


def test_an_unclassified_app_tool_is_treated_as_session_creating_until_classified(tmp_path):
    work = card_worktree(tmp_path)
    reason = ccd("mcp__ccd_future__fork_session", work)["hookSpecificOutput"]["permissionDecisionReason"]
    assert "stage_child_only_agent" in reason and "not classified" in reason
    assert claude_adapter.CCD_SESSION_TOOLS.isdisjoint(claude_adapter.CCD_READ_LAYOUT_TOOLS)


def test_the_title_tool_of_the_card_session_is_classified_as_allowed(tmp_path):
    assert "mcp__ccd_session_mgmt__set_session_title" in claude_adapter.CCD_READ_LAYOUT_TOOLS
    assert ccd("mcp__ccd_session_mgmt__set_session_title", card_worktree(tmp_path)) is None


def test_without_a_bound_card_the_app_tools_stay_allowed(tmp_path):
    work = git_repo(tmp_path, "source")
    write_overlay(work)
    for tool in ("mcp__ccd_session__spawn_task", "mcp__ccd_future__fork_session", "mcp__ccd_session_mgmt__send_message"):
        assert ccd(tool, work) is None


def test_a_reviewer_child_cannot_use_the_app_tools_at_all(tmp_path):
    work = card_worktree(tmp_path)
    reason = ccd("mcp__ccd_session_mgmt__list_sessions", work, agent_id="a0123456789abcdef", agent_type="diff-reviewer")["hookSpecificOutput"]["permissionDecisionReason"]
    assert "reviewer_tools" in reason


def test_every_app_tool_observed_in_the_launch_arguments_is_classified():
    observed = {
        "mcp__ccd_host__get_storage_usage", "mcp__ccd_pr__get_status", "mcp__ccd_session__dismiss_task", "mcp__ccd_session__list_start_targets",
        "mcp__ccd_session__mark_chapter", "mcp__ccd_session__read_widget_context", "mcp__ccd_session__spawn_task", "mcp__ccd_session__start_session",
        "mcp__ccd_session_mgmt__detach_session", "mcp__ccd_session_mgmt__export_transcript", "mcp__ccd_session_mgmt__get_session",
        "mcp__ccd_session_mgmt__get_usage", "mcp__ccd_session_mgmt__list_events", "mcp__ccd_session_mgmt__list_sessions",
        "mcp__ccd_session_mgmt__search_session_transcripts", "mcp__ccd_session_mgmt__send_message", "mcp__ccd_session_mgmt__set_session_title",
        "mcp__ccd_settings__get_settings", "mcp__ccd_sidebar__create_group", "mcp__ccd_sidebar__create_section", "mcp__ccd_sidebar__list_groups",
        "mcp__ccd_sidebar__list_sections", "mcp__ccd_sidebar__set_view", "mcp__ccd_turn__update_plan", "mcp__ccd_turn__wrap_up",
        "mcp__ccd_view__close_pane", "mcp__ccd_view__get_layout", "mcp__ccd_view__set_transcript_view", "mcp__ccd_view__show_pane",
        "mcp__ccd_window__close_split", "mcp__ccd_window__get_window_layout", "mcp__ccd_window__open_session_in", "mcp__ccd_window__set_sidebar_collapsed",
    }
    assert observed == claude_adapter.CCD_SESSION_TOOLS | claude_adapter.CCD_READ_LAYOUT_TOOLS


def test_the_account_registration_matches_the_app_tools_and_only_what_it_gates():
    import re

    import account_install

    matcher = account_install.claude_document()["hooks"]["PreToolUse"][0]["matcher"]
    assert all(re.search(matcher, tool) for tool in claude_adapter.CCD_SESSION_TOOLS | claude_adapter.CCD_READ_LAYOUT_TOOLS)
    assert all(re.search(matcher, tool) for tool in ("Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Agent"))
    assert not any(re.search(matcher, tool) for tool in ("TodoWrite", "Read", "Glob", "WebFetch", "mcp__other__tool", "EnterWorktree"))


# --- 4.9 (R34): a session in /source on the current pin receives the page ---------------------------------------------------


def test_a_session_started_in_source_on_develop_gets_the_page_with_the_enterworktree_instruction(tmp_path, monkeypatch):
    source = git_repo(tmp_path, "develop")
    write_overlay(source)
    monkeypatch.setattr(claude_adapter, "trust_status", lambda: {"reviewed": True, "digest": "d" * 64, "reason": ""})
    out = claude_adapter.session_start({"session_id": SESSION, "cwd": str(source), "transcript_path": "/x/t.jsonl", "source": "startup"})
    context = out["hookSpecificOutput"]["additionalContext"]
    assert "q_git=develop" in context and "bound_card=⊥" in context and "EnterWorktree" in context and "`#<id>`" in context
    assert "pasta do app" not in context and out["hookSpecificOutput"]["hookEventName"] == "SessionStart"


def test_the_page_says_how_the_app_session_is_conducted(tmp_path, monkeypatch):
    source = git_repo(tmp_path, "develop")
    write_overlay(source)
    text = page(cwd=source, path=source, client="claude", status_provider=lambda _b: None)["additional_context"]
    for needle in ("claude-desktop", "`/source`", "*worktree* desligada", "#<id>", "mcp__ccd_*", "<papel> <id> <único>", "linha de handoff", "(`auto`) não autoriza processo"):
        assert needle in text, needle


# --- R16: the page warns about mixed pins -----------------------------------------------------------------------------------


def test_the_page_warns_when_the_session_touched_worktrees_with_different_pins(tmp_path, monkeypatch):
    import cf_shim

    work = card_worktree(tmp_path)
    monkeypatch.setattr(claude_adapter, "trust_status", lambda: {"reviewed": True, "digest": "d" * 64, "reason": ""})
    cf_shim._private_write(cf_shim.heartbeat_path("claude", SESSION), {
        "version": 2, "client": "claude", "session_id": SESSION, "roots": [{"root": "/a/source", "pin": "v1.1.20"}, {"root": str(work), "pin": "v1.2.0"}],
    })
    context = claude_adapter.session_start({"session_id": SESSION, "cwd": str(work), "source": "enter-worktree"})["hookSpecificOutput"]["additionalContext"]
    assert "Pins mistos" in context and "/a/source = v1.1.20" in context and f"{work} = v1.2.0" in context
    cf_shim._private_write(cf_shim.heartbeat_path("claude", SESSION), {
        "version": 2, "client": "claude", "session_id": SESSION, "roots": [{"root": "/a/source", "pin": "v1.2.0"}, {"root": str(work), "pin": "v1.2.0"}],
    })
    assert "Pins mistos" not in claude_adapter.session_start({"session_id": SESSION, "cwd": str(work)})["hookSpecificOutput"]["additionalContext"]


# --- 4.8: the handoff line, from the proxy ---------------------------------------------------------------------------------------


def test_the_handoff_line_comes_from_the_proxy_never_from_the_request(tmp_path, capsys):
    world = World(tmp_path)
    cap, path, task, prepared = world.prepare()
    world.spawn(cap, task)
    assert claude_proxy.main(["--repo-root", str(world.repo), "--capture", str(path), "--activity", "apply-coluna", "--band", "execucao", "--birth", prepared["birth"], "--wait-seconds", "0", "--handoff"]) == 0
    line = capsys.readouterr().out.strip()
    assert "\n" not in line
    assert line.startswith("apply-coluna") and "client claude" in line and "surface cli" in line and "claude-sonnet-5-5/high" in line and "completed" in line
    failed = dict(json.loads((world.repo / ".cursor/tmp/claude-child-proxies.jsonl").read_text().splitlines()[0]), status="failed", successful=False)
    assert "failed" in claude_proxy.handoff_line(failed) and "gate" in claude_proxy.handoff_line(failed, gate="Code Review")
