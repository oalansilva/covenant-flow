from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import claude_evidence as ev
from claude_fixtures import AGENT, DIGEST, SESSION, VERSION, World, assistant, record, trust_ok, write_jsonl
from model_selection_fixtures import machine_models  # noqa: F401  (autouse isolated account)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def code(excinfo) -> str:
    return excinfo.value.code


# --- preflight ---------------------------------------------------------------------


def test_preflight_ready_reports_session_version_surface_and_parent_observation(world):
    pf = ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert pf["result"] == "ready" and pf["host_version"] == VERSION and pf["surface"] == "cli"
    assert pf["parent_observed"] == {"model": "claude-sonnet-5-5", "effort": "high"}


def test_preflight_requires_a_session(world):
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session="", environ={}, trust=trust_ok)
    assert code(e) == "session_unavailable"


def test_preflight_without_heartbeat_means_hooks_did_not_run(world):
    (Path.home() / ".config/covenant-flow/claude-sessions" / f"{SESSION}.json").unlink()
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert code(e) == "hooks_inactive"


def test_preflight_refuses_unreviewed_and_changed_hooks(world):
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env,
                     trust=lambda: {"reviewed": False, "digest": DIGEST, "reason": "hooks não revisados"})
    assert code(e) == "hooks_unreviewed"
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env,
                     trust=lambda: {"reviewed": True, "digest": "e" * 64, "reason": ""})
    assert code(e) == "hooks_changed"


@pytest.mark.parametrize("field,value", [("version", "2.1.295"), ("entrypoint", "claude-vscode")])
def test_preflight_refuses_unqualified_version_or_surface(world, field, value):
    world.rows = [dict(r, **{field: value}) for r in world.rows]
    world.flush()
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert code(e) == "unverified"


def test_preflight_refuses_a_session_outside_the_worktree_and_truncated_source(world, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=other, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert code(e) == "worktree_mismatch"
    world.flush(truncate=True)
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert code(e) == "source_truncated"


@pytest.mark.parametrize("name", ["CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL"])
def test_preflight_refuses_environment_overrides(world, name):
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ={**world.env, name: "x"}, trust=trust_ok)
    assert code(e) == "capability_unavailable" and name in str(e.value)


def test_transcript_of_another_session_is_a_foreign_identity(world):
    world.rows.append(record("assistant", world.repo, session="99999999-0000-0000-0000-000000000000", message={"model": "m"}))
    world.flush()
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert code(e) == "identity_mismatch"


# --- prepare / collect positive path ------------------------------------------------


def test_prepare_then_collect_records_observed_pair_per_turn_and_payload(world):
    cap, _path, task, prepared = world.prepare()
    birth = Path(prepared["birth"])
    assert oct(birth.stat().st_mode & 0o777) == "0o400"
    world.spawn(cap, task)
    result = world.collect(birth)
    assert result["status"] == "completed" and result["payload_returned"] is True
    assert result["host"] == "Claude Code" and result["host_version"] == VERSION and result["surface"] == "cli"
    assert result["requested"] == {"model": "claude-sonnet-5-5", "effort": "high"}
    assert result["resolved_model"] == "claude-sonnet-5-5"
    assert all(t["observed"] == result["requested"] for t in result["turns"]) and len(result["turns"]) == 2
    assert result["child_agent_id"] == AGENT and result["tools_used"] == ["Bash", "Read"] and result["read_only"] is False
    assert len(result["payload_sha256"]) == 1
    # observed is never copied from requested: it comes from every child turn
    assert ev.verify_evidence(result["evidence_path"], runtime=world.runtime)["integrity_sha256"] == result["integrity_sha256"]


def test_collect_is_idempotent_and_foreground_completed_payload_counts(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task, status="completed", content="inline final answer", handback=None)
    first = world.collect(prepared["birth"])
    second = world.collect(prepared["birth"])
    assert first["evidence_path"] == second["evidence_path"] and first["status"] == "completed"


def test_prepare_requires_role_needle_unique_task_and_review_diff(world):
    cap, path = world.capture("apply-coluna")
    for bad in ("", "no/slash", " padded ", "just a description"):
        with pytest.raises(ev.EvidenceError) as e:
            ev.prepare(root=world.repo, capture=path, task_name=bad, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
        assert code(e) == "invalid_task_name"
    ev.prepare(root=world.repo, capture=path, task_name="apply-coluna 1101 one", runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    with pytest.raises(ev.EvidenceError) as e:
        ev.prepare(root=world.repo, capture=path, task_name="apply-coluna 1101 one", runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert code(e) in {"task_name_not_unique", "attempt_conflict"}
    rcap, rpath = world.capture("diff-reviewer")
    with pytest.raises(ev.EvidenceError) as e:
        ev.prepare(root=world.repo, capture=rpath, task_name="diff-reviewer 1101 a", runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert code(e) == "diff_unavailable"


# --- refusals: missing, divergent, foreign, truncated, unqualified ------------------


def blocked(world, birth_path):
    with pytest.raises(ev.EvidenceError) as e:
        world.collect(birth_path)
    return e.value


@pytest.mark.parametrize("kw,expected", [
    ({"child_model": "claude-opus-5-5"}, "model_mismatch"),
    ({"child_effort": "medium"}, "model_mismatch"),
    ({"resolved": "claude-opus-5-5"}, "model_mismatch"),
    ({"child_session": "99999999-0000-0000-0000-000000000000"}, "identity_mismatch"),
    ({"meta_overrides": {"toolUseId": "toolu_OTHER"}}, "identity_mismatch"),
    ({"meta_overrides": {"effort": "low"}}, "requested_mismatch"),
    ({"args_override": {"effort": "low"}}, "requested_mismatch"),
    ({"handback": None}, "terminal_unavailable"),
])
def test_divergent_or_missing_evidence_is_refused_and_leaves_a_failure_record(world, kw, expected):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task, **kw)
    err = blocked(world, prepared["birth"])
    assert err.code == expected
    failures = list(Path(prepared["birth"]).parent.glob("*.failure-*.json"))
    assert len(failures) == 1 and json.loads(failures[0].read_text())["result"] == "blocked"


def test_divergence_in_an_earlier_turn_is_not_hidden_by_a_correct_last_turn(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    child = world.subdir / f"agent-{AGENT}.jsonl"
    rows = [json.loads(line) for line in child.read_text().splitlines()]
    rows[1]["effort"] = rows[1]["perTurnEffort"] = "low"
    write_jsonl(child, rows)
    assert blocked(world, prepared["birth"]).code == "model_mismatch"


def test_truncated_parent_or_child_and_unqualified_child_version(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    child = world.subdir / f"agent-{AGENT}.jsonl"
    good = child.read_bytes()
    child.write_bytes(good.rstrip(b"\n"))
    assert blocked(world, prepared["birth"]).code == "source_truncated"
    rows = [dict(json.loads(line), version="2.1.200") for line in good.decode().splitlines()]
    write_jsonl(child, rows)
    assert blocked(world, prepared["birth"]).code == "unverified"
    child.write_bytes(good)
    world.flush(truncate=True)
    assert blocked(world, prepared["birth"]).code == "source_truncated"


def test_missing_spawn_or_result_and_cleaned_source_require_new_birth(world):
    cap, _p, task, prepared = world.prepare()
    assert blocked(world, prepared["birth"]).code == "birth_mismatch"
    world.spawn(cap, task)
    world.parent.unlink()
    assert blocked(world, prepared["birth"]).code == "source_unavailable"


def test_failed_and_interrupted_children_are_never_successful(world):
    for status, expected in (("failed", "failed"), ("killed", "interrupted")):
        cap, _p, task, prepared = world.prepare(task=None)
        world.spawn(cap, task, status=status, handback=None, agent=("a1" + status.ljust(10, "0")[:10] + "bbbb"), call_id=f"toolu_{status}", msg_id=f"m-{status}")
        result = world.collect(prepared["birth"])
        assert result["status"] == expected and result["payload_returned"] is False


def test_reviewer_with_a_write_tool_is_refused_and_read_only_reviewer_passes(world):
    diff = "a" * 64
    cap, _p, task, prepared = world.prepare("diff-reviewer", diff=diff, wave="wave-1")
    world.spawn(cap, task, role="diff-reviewer", subagent_type="diff-reviewer", child_tools=("Read", "Edit"))
    assert blocked(world, prepared["birth"]).code == "child_tool_mismatch"
    cap2, _p2, task2, prepared2 = world.prepare("code-reviewer", diff=diff, wave="wave-1")
    world.spawn(cap2, task2, role="code-reviewer", subagent_type="code-reviewer", child_tools=("Read", "Grep", "SubagentHandback"),
                agent="aabbccddeeff00112", call_id="toolu_B", msg_id="m-b")
    ok = world.collect(prepared2["birth"])
    assert ok["read_only"] is True and ok["review_diff_sha256"] == diff


# --- spawn hook receipt + first-write verification ----------------------------------


def spawn_args(cap, task, prepared, **extra):
    return {"description": task, "subagent_type": "general-purpose", **cap["arguments"],
            "prompt": f"model_selection_capture: x\nruntime_evidence_birth: {prepared['birth']}", **extra}


def test_check_prepared_spawn_accepts_only_the_matching_receipt(world):
    cap, _p, task, prepared = world.prepare()
    args = spawn_args(cap, task, prepared)
    assert ev.check_prepared_spawn(args, world.repo, session=SESSION, runtime=world.runtime, environ=world.env, trust=trust_ok)["result"] == "ready"
    for broken, expected in (
        ({"prompt": "model_selection_capture: x"}, "birth_receipt_missing"),
        ({"description": "apply-coluna 1101 other"}, "birth_mismatch"),
        ({"effort": "low"}, "requested_mismatch"),
    ):
        with pytest.raises(ev.EvidenceError) as e:
            ev.check_prepared_spawn({**args, **broken}, world.repo, session=SESSION, runtime=world.runtime, environ=world.env, trust=trust_ok)
        assert e.value.code == expected
    with pytest.raises(ev.EvidenceError) as e:
        ev.check_prepared_spawn(args, world.repo, session="99999999-0000-0000-0000-000000000000", runtime=world.runtime, environ=world.env, trust=trust_ok)
    assert e.value.code == "birth_mismatch"


def child_event(world, **extra):
    return {"session_id": SESSION, "agent_id": AGENT, "transcript_path": str(world.parent), **extra}


def test_first_write_verified_when_pair_equals_capture_then_not_reread(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    out = Path(prepared["birth"]).parent
    ev.verify_child_before_write(child_event(world), world.repo, runtime=world.runtime)
    assert ev.marked(out, cap["attempt_id"], "verified")
    (world.subdir / f"agent-{AGENT}.jsonl").unlink()  # a second write does not reread the transcript
    ev.verify_child_before_write(child_event(world), world.repo, runtime=world.runtime)


@pytest.mark.parametrize("kw", [{"child_model": "claude-opus-5-5"}, {"child_effort": "medium"}])
def test_first_write_with_divergent_pair_is_denied_and_receipt_marked(world, kw):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task, **kw)
    with pytest.raises(ev.EvidenceError) as e:
        ev.verify_child_before_write(child_event(world), world.repo, runtime=world.runtime)
    assert e.value.code == "model_mismatch"
    assert ev.marked(Path(prepared["birth"]).parent, cap["attempt_id"], "model_mismatch")
    # once marked, even a check-prepared spawn of that birth is invalid
    with pytest.raises(ev.EvidenceError) as again:
        ev.check_prepared_spawn(spawn_args(cap, task, prepared), world.repo, session=SESSION, runtime=world.runtime, environ=world.env, trust=trust_ok)
    assert again.value.code == "model_mismatch"


def test_first_write_with_absent_or_unreadable_child_transcript_is_denied(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    child = world.subdir / f"agent-{AGENT}.jsonl"
    child.write_bytes(b"")
    with pytest.raises(ev.EvidenceError) as e:
        ev.verify_child_before_write(child_event(world), world.repo, runtime=world.runtime)
    assert e.value.code == "model_mismatch"
    assert ev.marked(Path(prepared["birth"]).parent, cap["attempt_id"], "model_mismatch")


def test_first_write_without_a_birth_receipt_is_denied(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task, meta_overrides={"description": "apply-coluna 1101 unprepared"})
    with pytest.raises(ev.EvidenceError) as e:
        ev.verify_child_before_write(child_event(world), world.repo, runtime=world.runtime)
    assert e.value.code == "birth_receipt_missing"


def test_post_spawn_resolved_model_divergence_marks_the_receipt(world):
    cap, _p, task, prepared = world.prepare()
    args = spawn_args(cap, task, prepared)
    assert ev.note_resolved_model(args, {"resolvedModel": "claude-sonnet-5-5"}, world.repo)["ok"] is True
    bad = ev.note_resolved_model(args, json.dumps({"resolvedModel": "claude-opus-5-5"}), world.repo)
    assert bad["ok"] is False and ev.marked(Path(prepared["birth"]).parent, cap["attempt_id"], "model_mismatch")
    assert ev.note_resolved_model(args, {}, world.repo)["ok"] is False


# --- parent observation (release closeout) -----------------------------------------


def test_observe_parent_reads_the_last_parent_turn_only(world):
    world.rows.append(assistant(world.repo, model="claude-opus-5-5", effort="medium", content=[], msg_id="m9"))
    world.rows.append(assistant(world.repo, model="claude-sonnet-5-5", effort="high", content=[], msg_id="m10", sidechain=True, agent=AGENT))
    world.flush()
    seen = ev.observe_parent(session=SESSION, runtime=world.runtime, environ=world.env)
    assert (seen["model"], seen["effort"], seen["host_version"]) == ("claude-opus-5-5", "medium", VERSION)


def test_cli_prepare_and_blocked_output(world, capsys, monkeypatch):
    cap, path = world.capture()
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "")
    assert ev.main(["preflight", "--root", str(world.repo)]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["result"] == "blocked" and out["code"] == "session_unavailable"
