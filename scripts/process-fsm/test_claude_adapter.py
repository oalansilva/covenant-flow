from __future__ import annotations

import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

import claude_adapter
import claude_evidence as ev
import claude_trust
from claude_fixtures import AGENT, DIGEST, PRETOOL_AGENT_2_1_296, SESSION, World, git_repo, trust_ok
from model_selection import resolve, save_capture
from model_selection_fixtures import machine_models  # noqa: F401
from paging import page as shared_page
from test_overlay_fixtures import COLUMN_IDS, FIELD_ID, write_overlay

ROOT = Path(__file__).resolve().parent
REVIEWED = {"reviewed": True, "digest": DIGEST, "reason": ""}
UNREVIEWED = {"reviewed": False, "digest": "e" * 64, "reason": "digest not recorded"}


@pytest.fixture(autouse=True)
def reviewed(monkeypatch):
    monkeypatch.setattr(claude_adapter, "trust_status", lambda: REVIEWED)


def repo(tmp_path: Path, branch: str) -> Path:
    path = git_repo(tmp_path, branch.replace("/", "-"))
    subprocess.run(["git", "-C", str(path), "checkout", "-q", "-B", branch], check=True, capture_output=True)
    write_overlay(path)
    return path


def with_status(monkeypatch, status):
    monkeypatch.setattr(claude_adapter, "github_status_provider", lambda _bound: status)


def call(tool, tool_input, cwd, **extra):
    return claude_adapter.pre_tool_use({"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd), "session_id": SESSION, **extra})


def reason(decision):
    assert decision is not None and decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    return decision["hookSpecificOutput"]["permissionDecisionReason"]


# --- Guard by Status and binding ------------------------------------------------------


@pytest.mark.parametrize("tool,tool_input", [
    ("Bash", {"command": "printf x > backend/api.py"}),
    ("Edit", {"file_path": "backend/api.py", "old_string": "a", "new_string": "b"}),
    ("Write", {"file_path": "backend/api.py", "content": "x"}),
    ("MultiEdit", {"file_path": "backend/api.py", "edits": []}),
    ("NotebookEdit", {"notebook_path": "backend/n.ipynb", "new_source": "x"}),
])
def test_product_write_on_develop_is_denied_by_command_and_by_edit_with_readback_unchanged(tmp_path, monkeypatch, tool, tool_input):
    work = repo(tmp_path, "develop")
    target = work / "backend" / "api.py"
    target.parent.mkdir()
    target.write_text("original\n")
    with_status(monkeypatch, "Em desenvolvimento")
    path_input = dict(tool_input)
    if "file_path" in path_input:
        path_input["file_path"] = str(target)
    if "notebook_path" in path_input:
        path_input["notebook_path"] = str(work / "backend" / "n.ipynb")
    if tool == "Bash":
        path_input["command"] = f"printf x > {target}"
    assert "process-fsm-guard deny" in reason(call(tool, path_input, work))
    assert target.read_text() == "original\n"


@pytest.mark.parametrize("status,branch", [("Todo", "card-1101-test"), (None, "scratch")])
def test_todo_and_unbound_product_writes_are_denied_by_both_routes(tmp_path, monkeypatch, status, branch):
    work = repo(tmp_path, branch)
    with_status(monkeypatch, status)
    assert reason(call("Bash", {"command": "printf x > backend/api.py"}, work))
    assert reason(call("Edit", {"file_path": str(work / "backend/api.py"), "old_string": "a", "new_string": "b"}, work))
    assert not (work / "backend/api.py").exists()


def test_design_allows_openspec_changes_and_denies_backend(tmp_path, monkeypatch):
    work = repo(tmp_path, "card-1101-test")
    with_status(monkeypatch, "Design")
    assert call("Write", {"file_path": str(work / "openspec/changes/card-1101-test/design.md"), "content": "x"}, work) is None
    assert reason(call("Write", {"file_path": str(work / "backend/api.py"), "content": "x"}, work))


def test_product_is_allowed_after_t8_only_in_the_card_worktree(tmp_path, monkeypatch):
    with_status(monkeypatch, "Em desenvolvimento")
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    card = repo(tmp_path / "a", "card-1101-test")
    assert call("Write", {"file_path": str(card / "backend/api.py"), "content": "x"}, card) is None
    integration = repo(tmp_path / "b", "develop")
    assert reason(call("Write", {"file_path": str(integration / "backend/api.py"), "content": "x"}, integration))


def test_direct_status_edit_through_gh_is_denied(tmp_path, monkeypatch):
    work = repo(tmp_path, "card-1101-test")
    with_status(monkeypatch, "Em desenvolvimento")
    command = f"gh project item-edit --id ITEM --field-id {FIELD_ID} --single-select-option-id {COLUMN_IDS['Pronto para Dev']}"
    assert "process_event" in reason(call("Bash", {"command": command}, work))


# --- fail-closed ----------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["{invalid json", "[]", ""])
def test_malformed_stdin_is_a_visible_deny_with_exit_zero(raw, monkeypatch):
    out = StringIO()
    monkeypatch.setattr(claude_adapter.sys, "stdin", StringIO(raw))
    monkeypatch.setattr(claude_adapter.sys, "stdout", out)
    assert claude_adapter.main(["pre-tool-use"]) == 0
    assert "evaluation_error" in reason(json.loads(out.getvalue()))


def test_subprocess_entry_point_denies_on_garbage_and_never_exits_one():
    done = subprocess.run([sys.executable, str(ROOT / "claude_adapter.py"), "pre-tool-use"], input="oops", capture_output=True, text=True)
    assert done.returncode == 0 and "permissionDecision" in done.stdout and '"deny"' in done.stdout


def test_unknown_tool_non_object_input_and_evaluation_errors_are_denied(tmp_path, monkeypatch):
    assert "unknown_tool" in reason(claude_adapter.pre_tool_use({"tool_name": "mcp__x__write", "tool_input": {"a": 1}}))
    work = repo(tmp_path, "card-1101-test")
    assert "evaluation_error" in reason(call("Bash", "[]", work))
    assert "invalid_tool_input" in reason(call("Bash", {"command": 5}, work))
    assert "empty_path" in reason(call("Write", {"content": "x"}, work))
    monkeypatch.setattr(claude_adapter, "decide", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("guard unavailable")))
    assert "guard unavailable" in reason(call("Bash", {"command": "printf x > backend/a.py"}, work))


def test_timeout_shaped_failures_never_allow(tmp_path, monkeypatch):
    work = repo(tmp_path, "card-1101-test")

    def slow(*_a, **_k):
        raise subprocess.TimeoutExpired("gh", 5)

    monkeypatch.setattr(claude_adapter, "github_status_provider", slow)
    assert "evaluation_error" in reason(call("Edit", {"file_path": str(work / "backend/a.py"), "old_string": "a", "new_string": "b"}, work))


# --- children and reviewers -----------------------------------------------------------


def test_a_child_cannot_spawn_another_agent(tmp_path):
    work = repo(tmp_path, "card-1101-test")
    assert "child_spawn" in reason(call("Agent", {"description": "apply-coluna x", "model": "sonnet", "effort": "high"}, work, agent_id=AGENT, agent_type="general-purpose"))


@pytest.mark.parametrize("agent_type", ["diff-reviewer", "code-reviewer"])
def test_reviewer_with_bash_or_edit_is_denied_and_read_tools_pass(tmp_path, agent_type):
    work = repo(tmp_path, "card-1101-test")
    assert "reviewer_tools" in reason(call("Bash", {"command": "ls"}, work, agent_id=AGENT, agent_type=agent_type))
    assert "reviewer_tools" in reason(call("Edit", {"file_path": str(work / "x"), "old_string": "a", "new_string": "b"}, work, agent_id=AGENT, agent_type=agent_type))
    assert call("Read", {"file_path": "x"}, work, agent_id=AGENT, agent_type=agent_type) is None
    assert call("Grep", {"pattern": "x"}, work, agent_id=AGENT, agent_type=agent_type) is None


# --- spawn --------------------------------------------------------------------------


class Spawn:
    def __init__(self, tmp_path, monkeypatch, role="apply-coluna"):
        self.world = World(tmp_path)
        write_overlay(self.world.repo)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
        monkeypatch.setattr(ev, "Runtime", lambda *a, **k: self.world.runtime.__class__(home=self.world.home))
        self.role = role
        self.cap, self.cap_path, self.task, self.prepared = self.world.prepare(role)

    def args(self, **over):
        base = {"description": self.task, "subagent_type": "general-purpose", **self.cap["arguments"],
                "prompt": f"model_selection_capture: {self.cap_path}\nruntime_evidence_birth: {self.prepared['birth']}"}
        base.update(over)
        return {k: v for k, v in base.items() if v is not None}

    def call(self, **over):
        return claude_adapter.pre_tool_use({"tool_name": "Agent", "tool_input": self.args(**over), "cwd": str(self.world.repo), "session_id": SESSION})


@pytest.fixture
def spawn(tmp_path, monkeypatch):
    monkeypatch.setattr(ev, "preflight", ev.preflight)
    s = Spawn(tmp_path, monkeypatch)
    real = ev.preflight
    monkeypatch.setattr(ev, "preflight", lambda **kw: real(**{**kw, "trust": trust_ok, "runtime": s.world.runtime}))
    return s


def test_spawn_with_captured_pair_and_receipt_is_allowed(spawn):
    assert spawn.call() is None


@pytest.mark.parametrize("over,needle", [
    ({"model": None}, "model_missing"),
    ({"effort": None}, "unsupported_schema"),
    ({"model": "opus"}, "mismatch"),
    ({"effort": "low"}, "mismatch"),
    ({"prompt": "no capture"}, "model_selection_capture"),
])
def test_spawn_without_the_explicit_captured_pair_is_denied(spawn, over, needle):
    assert needle in reason(spawn.call(**over))


def test_recorded_2_1_296_agent_payload_shape_is_accepted_with_the_captured_pair(spawn):
    event = {**PRETOOL_AGENT_2_1_296, "cwd": str(spawn.world.repo), "session_id": SESSION, "tool_input": spawn.args()}
    assert set(spawn.args()) >= set(PRETOOL_AGENT_2_1_296["tool_input"])
    assert claude_adapter.pre_tool_use(event) is None
    without = {**event, "tool_input": spawn.args(effort=None)}
    assert "unsupported_schema" in reason(claude_adapter.pre_tool_use(without))


def test_spawn_with_effort_only_in_the_session_field_is_denied_as_unsupported_schema(spawn):
    decision = claude_adapter.pre_tool_use({"tool_name": "Agent", "tool_input": spawn.args(effort=None), "effort": {"level": "high"}, "cwd": str(spawn.world.repo), "session_id": SESSION})
    text = reason(decision)
    assert "unsupported_schema" in text and "session effort" in text


@pytest.mark.parametrize("name", ["CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL"])
def test_spawn_with_environment_override_is_denied(spawn, monkeypatch, name):
    monkeypatch.setenv(name, "1")
    assert name in reason(spawn.call())


def test_spawn_without_a_birth_receipt_or_with_another_receipt_is_denied(spawn):
    assert "birth_receipt_missing" in reason(spawn.call(prompt=f"model_selection_capture: {spawn.cap_path}"))
    assert "birth_mismatch" in reason(spawn.call(description="apply-coluna 1101 different"))


def test_reviewer_spawn_must_use_the_read_only_agent_type(tmp_path, monkeypatch):
    world = World(tmp_path)
    write_overlay(world.repo)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    real = ev.preflight
    monkeypatch.setattr(ev, "preflight", lambda **kw: real(**{**kw, "trust": trust_ok, "runtime": world.runtime}))
    cap, path, task, prepared = world.prepare("diff-reviewer", diff="a" * 64, wave="w")
    args = {"description": task, "subagent_type": "general-purpose", **cap["arguments"], "prompt": f"model_selection_capture: {path}\nmodel_selection_wave_capture: {path}\nruntime_evidence_birth: {prepared['birth']}"}
    decision = claude_adapter.pre_tool_use({"tool_name": "Agent", "tool_input": args, "cwd": str(world.repo), "session_id": SESSION})
    assert "reviewer_agent_type" in reason(decision)
    args["subagent_type"] = "diff-reviewer"
    assert claude_adapter.pre_tool_use({"tool_name": "Agent", "tool_input": args, "cwd": str(world.repo), "session_id": SESSION}) is None


# --- hook trust and heartbeat --------------------------------------------------------


def test_divergent_hook_digest_denies_product_writes_and_spawns_but_not_other_work(tmp_path, monkeypatch, spawn):
    monkeypatch.setattr(claude_adapter, "trust_status", lambda: UNREVIEWED)
    with_status(monkeypatch, "Em desenvolvimento")
    assert "hooks não revisados" in reason(spawn.call())
    work = spawn.world.repo
    assert "hooks_unreviewed" in reason(call("Write", {"file_path": str(work / "backend/api.py"), "content": "x"}, work))
    assert "hooks_unreviewed" in reason(call("Bash", {"command": "printf x > backend/api.py"}, work))
    assert call("Write", {"file_path": str(work / "openspec/changes/card-1101-test/tasks.md"), "content": "x"}, work) is None
    assert call("Bash", {"command": "ls"}, work) is None


def test_session_start_records_heartbeat_with_digest_and_flags_unreviewed(tmp_path, monkeypatch):
    work = repo(tmp_path, "card-1101-test")
    monkeypatch.setattr(claude_adapter, "page", lambda **kw: shared_page(**kw, status_provider=lambda _b: "Design"))
    ok = claude_adapter.session_start({"cwd": str(work), "session_id": SESSION, "transcript_path": "/x/t.jsonl"})["hookSpecificOutput"]
    assert ok["hookEventName"] == "SessionStart" and "q=Design" in ok["additionalContext"] and "hooks não revisados" not in ok["additionalContext"]
    beat = claude_trust.read_heartbeat(SESSION)
    assert beat["hooks_digest"] == DIGEST and beat["reviewed"] is True and beat["transcript_path"] == "/x/t.jsonl"
    monkeypatch.setattr(claude_adapter, "trust_status", lambda: UNREVIEWED)
    bad = claude_adapter.session_start({"cwd": str(work), "session_id": SESSION})["hookSpecificOutput"]["additionalContext"]
    assert "hooks não revisados" in bad and claude_trust.read_heartbeat(SESSION)["reviewed"] is False


@pytest.mark.parametrize("status", ["Todo", "Design", "Status unread"])
def test_session_start_uses_the_shared_page_per_status(tmp_path, monkeypatch, status):
    work = repo(tmp_path, "card-1101-test")
    value = None if status == "Status unread" else status
    monkeypatch.setattr(claude_adapter, "page", lambda **kw: shared_page(**kw, status_provider=lambda _b: value))
    context = claude_adapter.session_start({"cwd": str(work), "session_id": SESSION})["hookSpecificOutput"]["additionalContext"]
    assert "bound_card=1101" in context and "Adapter Claude Code (não oficial" in context
    assert "Cliente ativo" not in context
    if value is None:
        assert "Status unread" in context and "Write produto deny" in context
    else:
        assert f"q={status}" in context and "enabled_events" in context


def test_session_start_page_failure_stays_unread_and_write_denied(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_adapter, "page", lambda **kw: (_ for _ in ()).throw(RuntimeError("status lookup unavailable")))
    context = claude_adapter.session_start({"cwd": str(tmp_path), "session_id": SESSION})["hookSpecificOutput"]["additionalContext"]
    assert "Status unread" in context and "Write produto deny" in context and "status lookup unavailable" in context


# --- first write of a child ----------------------------------------------------------


@pytest.fixture
def child(tmp_path, monkeypatch):
    s = Spawn(tmp_path, monkeypatch)
    with_status(monkeypatch, "Em desenvolvimento")
    return s


def child_write(s, tool="Edit", **extra):
    path = s.world.repo / "backend" / "api.py"
    data = {"command": f"printf x > {path}"} if tool == "Bash" else {"file_path": str(path), "old_string": "a", "new_string": "b"}
    return claude_adapter.pre_tool_use({"tool_name": tool, "tool_input": data, "cwd": str(s.world.repo), "session_id": SESSION,
                                        "transcript_path": str(s.world.parent), "agent_id": AGENT, "agent_type": "general-purpose", **extra})


@pytest.mark.parametrize("tool", ["Edit", "Write", "Bash"])
def test_first_child_write_with_equal_pair_is_allowed_and_receipt_verified(child, tool, monkeypatch):
    monkeypatch.setattr(ev, "Runtime", lambda *a, **k: child.world.runtime)
    child.world.spawn(child.cap, child.task)
    assert child_write(child, tool) is None
    assert ev.marked(Path(child.prepared["birth"]).parent, child.cap["attempt_id"], "verified")


@pytest.mark.parametrize("kw", [{"child_model": "claude-opus-5-5"}, {"child_effort": "medium"}])
def test_first_child_write_with_divergent_pair_is_denied_with_model_mismatch(child, kw, monkeypatch):
    monkeypatch.setattr(ev, "Runtime", lambda *a, **k: child.world.runtime)
    child.world.spawn(child.cap, child.task, **kw)
    assert "model_mismatch" in reason(child_write(child, "Bash"))
    assert ev.marked(Path(child.prepared["birth"]).parent, child.cap["attempt_id"], "model_mismatch")
    assert "model_mismatch" in reason(child_write(child, "Edit"))


def test_first_child_write_with_absent_or_unreadable_transcript_is_denied(child, monkeypatch):
    monkeypatch.setattr(ev, "Runtime", lambda *a, **k: child.world.runtime)
    child.world.spawn(child.cap, child.task)
    (child.world.subdir / f"agent-{AGENT}.jsonl").unlink()
    assert "model_mismatch" in reason(child_write(child, "Edit"))


def test_read_only_bash_in_a_child_does_not_trigger_the_write_check(child, monkeypatch):
    monkeypatch.setattr(ev, "Runtime", lambda *a, **k: child.world.runtime)
    child.world.spawn(child.cap, child.task, child_model="claude-opus-5-5")
    out = claude_adapter.pre_tool_use({"tool_name": "Bash", "tool_input": {"command": "git status"}, "cwd": str(child.world.repo), "session_id": SESSION,
                                       "transcript_path": str(child.world.parent), "agent_id": AGENT, "agent_type": "general-purpose"})
    assert out is None


# --- post hooks -------------------------------------------------------------------


def test_post_agent_annotates_resolved_model_divergence_only(spawn, capfd):
    event = {"tool_name": "Agent", "tool_input": spawn.args(), "cwd": str(spawn.world.repo), "session_id": SESSION}
    assert claude_adapter.dispatch("post-tool-use", dict(event, tool_response={"resolvedModel": "claude-sonnet-5-5"})) == 0
    assert capfd.readouterr().out == ""
    assert claude_adapter.dispatch("post-tool-use", dict(event, tool_response={"resolvedModel": "claude-opus-5-5"})) == 0
    note = json.loads(capfd.readouterr().out)["hookSpecificOutput"]
    assert note["hookEventName"] == "PostToolUse" and "model_mismatch" in note["additionalContext"] and "decision" not in note
    assert ev.marked(Path(spawn.prepared["birth"]).parent, spawn.cap["attempt_id"], "model_mismatch")


def test_subagent_stop_only_notes_the_receipt_and_never_blocks(spawn, capfd):
    spawn.world.spawn(spawn.cap, spawn.task)
    event = {"hook_event_name": "SubagentStop", "session_id": SESSION, "cwd": str(spawn.world.repo), "agent_id": AGENT, "agent_type": "general-purpose",
             "agent_transcript_path": str(spawn.world.subdir / f"agent-{AGENT}.jsonl"), "last_assistant_message": "done"}
    assert claude_adapter.dispatch("subagent-stop", event) == 0
    assert capfd.readouterr().out == ""
    note = json.loads((Path(spawn.prepared["birth"]).parent / f"{spawn.cap['attempt_id']}.subagent-stop.json").read_text())
    assert note["last_message_present"] is True and "decision" not in json.dumps(note)


def test_post_and_stop_forward_events_to_the_shared_impeccable_hook_as_claude(tmp_path, monkeypatch, capfd):
    root = tmp_path / "r"
    hook = root / ".agents/skills/impeccable/scripts/hook.mjs"
    hook.parent.mkdir(parents=True)
    hook.write_text("// fixture\n")
    monkeypatch.setattr(claude_adapter, "_repo_root", lambda _c: root)
    calls = []

    def fake(command, **kw):
        calls.append(kw)
        return SimpleNamespace(stdout=b'{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"advisory"}}\n')

    monkeypatch.setattr(claude_adapter.subprocess, "run", fake)
    claude_adapter._run_impeccable({"tool_name": "Edit", "tool_input": {"file_path": "frontend/src/a.tsx", "old_string": "a", "new_string": "b"}, "cwd": str(root)}, "PostToolUse")
    assert json.loads(calls[0]["input"])["file_path"] == "frontend/src/a.tsx" and calls[0]["env"]["IMPECCABLE_HOOK_HARNESS"] == "claude"
    assert "advisory" in capfd.readouterr().out
    claude_adapter._run_impeccable({"cwd": str(root)}, "Stop")
    assert json.loads(calls[1]["input"])["hook_event_name"] == "Stop"


# --- trust command ------------------------------------------------------------------


def test_trust_record_persists_the_reviewed_digest_and_changes_invalidate_it(tmp_path, monkeypatch):
    scripts = tmp_path / "repo" / "scripts" / "process-fsm"
    scripts.mkdir(parents=True)
    (scripts / "claude_adapter.py").write_text("import helper\n")
    (scripts / "helper.py").write_text("X = 1\n")
    (tmp_path / "repo" / ".claude").mkdir()
    (tmp_path / "repo" / ".claude/settings.json").write_text(json.dumps({"hooks": {"Stop": []}}))
    assert claude_trust.status(tmp_path / "repo", scripts)["reviewed"] is False
    recorded = claude_trust.record(tmp_path / "repo", scripts)
    assert sorted(recorded["files"]) == ["claude_adapter.py", "helper.py"]
    assert claude_trust.status(tmp_path / "repo", scripts)["reviewed"] is True
    (scripts / "helper.py").write_text("X = 2\n")  # an imported module changes after review
    assert claude_trust.status(tmp_path / "repo", scripts)["reviewed"] is False
    (scripts / "helper.py").write_text("X = 1\n")
    (tmp_path / "repo" / ".claude/settings.json").write_text(json.dumps({"hooks": {"Stop": [], "PreToolUse": []}}))
    assert claude_trust.status(tmp_path / "repo", scripts)["reviewed"] is False


def test_trust_digest_covers_the_impeccable_hook_script_and_its_relative_imports(tmp_path):
    repo_dir = tmp_path / "repo"
    scripts = repo_dir / "scripts" / "process-fsm"
    scripts.mkdir(parents=True)
    (scripts / "claude_adapter.py").write_text("X = 1\n")
    (repo_dir / ".claude").mkdir()
    (repo_dir / ".claude/settings.json").write_text(json.dumps({"hooks": {"Stop": []}}))
    baseline = claude_trust.current_digest(repo_dir, scripts)
    assert sorted(baseline["files"]) == ["claude_adapter.py"]  # consumer without impeccable: nothing extra, no failure
    impeccable = repo_dir / ".agents/skills/impeccable/scripts"
    (impeccable / "lib").mkdir(parents=True)
    (impeccable / "hook.mjs").write_text("import { run } from './hook-lib.mjs';\n")
    (impeccable / "hook-lib.mjs").write_text("import fs from 'node:fs';\nimport { id } from './lib/provider.mjs';\nimport { gone } from './missing.mjs';\n")
    (impeccable / "lib/provider.mjs").write_text("export const id = 1;\n")
    (impeccable / "unrelated.mjs").write_text("export {};\n")
    base = ".agents/skills/impeccable/scripts/"
    assert set(claude_trust.current_digest(repo_dir, scripts)["files"]) == {
        "claude_adapter.py", base + "hook-lib.mjs", base + "hook.mjs", base + "lib/provider.mjs"}
    claude_trust.record(repo_dir, scripts)
    assert claude_trust.status(repo_dir, scripts)["reviewed"] is True
    for name in ("hook.mjs", "hook-lib.mjs", "lib/provider.mjs"):
        before = claude_trust.current_digest(repo_dir, scripts)["digest"]
        original = (impeccable / name).read_text()
        (impeccable / name).write_text(original + " ")
        assert claude_trust.current_digest(repo_dir, scripts)["digest"] != before
        assert claude_trust.status(repo_dir, scripts)["reviewed"] is False
        (impeccable / name).write_text(original)
        assert claude_trust.status(repo_dir, scripts)["reviewed"] is True


@pytest.mark.parametrize("agent", ["claude-code_2-1-296_agent", "claude-code_2.1.296_agent", "claude-code_2-1-296"])
def test_host_version_is_read_from_the_real_and_dotted_agent_identity_without_subprocess(monkeypatch, agent):
    import model_selection

    def boom(*a, **k):
        raise AssertionError("claude --version must not run")

    monkeypatch.setattr(model_selection.subprocess, "run", boom)
    assert model_selection.claude_detect_version({"AI_AGENT": agent}) == "2.1.296"
    assert claude_trust.host_version({"AI_AGENT": agent}) == "2.1.296"
    assert claude_trust.host_version({"AI_AGENT": "other"}) == claude_trust.UNAVAILABLE


def test_heartbeat_with_real_host_identity_records_dotted_version(tmp_path):
    claude_trust.write_heartbeat(session_id=SESSION, transcript_path="/x/t.jsonl", cwd=str(tmp_path), digest=DIGEST, reviewed=True,
                                 environ={"AI_AGENT": "claude-code_2-1-296_agent", "CLAUDE_CODE_ENTRYPOINT": "cli"})
    assert claude_trust.read_heartbeat(SESSION)["host_version"] == "2.1.296"


def test_trust_status_is_unreviewed_when_the_definition_is_unreadable(tmp_path):
    result = claude_trust.status(tmp_path, tmp_path)
    assert result["reviewed"] is False and "cannot read hook definition" in result["reason"]


# --- shared Guard/paging normalization only (task 3.6) ----------------------------------


def test_guard_normalizes_claude_write_tool_names_to_their_target_paths():
    from guard import extract_paths, normalize
    assert extract_paths(normalize({"tool_name": "NotebookEdit", "cwd": "/w", "tool_input": {"notebook_path": "/w/backend/n.ipynb", "new_source": "x"}})) == ["/w/backend/n.ipynb"]
    assert extract_paths(normalize({"tool_name": "MultiEdit", "cwd": "/w", "tool_input": {"file_path": "/w/backend/a.py", "edits": []}})) == ["/w/backend/a.py"]
    assert extract_paths(normalize({"tool_name": "Write", "cwd": "/w", "tool_input": {"file_path": "/w/backend/a.py", "content": ""}})) == ["/w/backend/a.py"]
    assert extract_paths(normalize({"tool_name": "Read", "cwd": "/w", "tool_input": {"file_path": "/w/backend/a.py"}})) == []


def test_only_the_claude_page_carries_the_claude_context(tmp_path, monkeypatch):
    work = repo(tmp_path, "card-1101-test")
    pages = {c: shared_page(cwd=work, path=work, client=c, status_provider=lambda _b: "Design")["additional_context"] for c in ("claude", "codex", "cursor", None)}
    assert "Adapter Claude Code" in pages["claude"] and "model_selection.py resolve --client claude" in pages["claude"]
    assert all("Claude Code" not in pages[c] for c in ("codex", "cursor", None))
    assert "Cliente ativo: Codex CLI" in pages["codex"]
    base = pages["cursor"]
    assert pages["claude"].replace(next(l for l in pages["claude"].splitlines() if l.startswith("Adapter Claude Code")) + "\n", "") == base
