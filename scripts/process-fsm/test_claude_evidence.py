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


def _move_transcript(world, slug="-slug-other"):
    moved = world.home / "projects" / slug / f"{SESSION}.jsonl"
    moved.parent.mkdir(parents=True, exist_ok=True)
    world.parent.rename(moved)
    return moved


def test_stale_transcript_hint_is_dropped_when_the_host_moved_the_transcript(world):
    stale = str(world.parent)
    moved = _move_transcript(world)
    assert world.runtime.parent_path(SESSION, stale) == moved.resolve()
    assert world.runtime.parent_path(SESSION) == moved.resolve()


def test_two_existing_transcripts_remain_a_source_conflict_and_none_unavailable(world):
    hint = str(world.parent)
    other = world.home / "projects" / "-slug-other" / f"{SESSION}.jsonl"
    other.parent.mkdir(parents=True)
    other.write_text(world.parent.read_text())
    with pytest.raises(ev.EvidenceError) as e:
        world.runtime.parent_path(SESSION, hint)
    assert code(e) == "source_conflict"
    other.unlink()
    world.parent.unlink()
    with pytest.raises(ev.EvidenceError) as e:
        world.runtime.parent_path(SESSION, hint)
    assert code(e) == "source_unavailable"


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


def test_preflight_refuses_a_surface_value_the_driver_does_not_know_and_names_it_as_not_a_version(world):
    world.rows = [dict(r, entrypoint="claude-vscode") for r in world.rows]
    world.flush()
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert code(e) == "unverified" and "claude-vscode" in str(e.value) and "not a version check" in str(e.value)


@pytest.mark.parametrize("version", ["2.1.295", "2.1.299", "2.2.0", "9.9.9"])
def test_a_host_version_never_seen_with_the_same_format_is_ready_and_recorded(world, version):
    world.rows = [dict(r, version=version) for r in world.rows]
    world.flush()
    pf = ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert pf["result"] == "ready" and pf["host_version"] == version and pf["host_versions"] == [version]
    cap, _p, task, prepared = world.prepare()
    birth = json.loads(Path(prepared["birth"]).read_text())
    assert birth["host_version"] == version
    world.spawn(cap, task)
    # every record of the child is written by the same (never seen) version
    child = world.subdir / f"agent-{AGENT}.jsonl"
    write_jsonl(child, [dict(json.loads(line), version=version) for line in child.read_text().splitlines()])
    result = world.collect(prepared["birth"])
    assert result["status"] == "completed" and result["host_version"] == version


def test_a_transcript_with_two_host_versions_is_accepted_when_every_record_validates(world):
    world.rows = [dict(world.rows[0], version="2.1.296"), dict(world.rows[1], version="2.1.299")]
    world.flush()
    pf = ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert pf["host_version"] == "2.1.299" and pf["host_versions"] == ["2.1.296", "2.1.299"]


@pytest.mark.parametrize("field", ["message.model", "effort", "message.id", "cwd", "version"])
def test_a_record_the_collector_needs_without_a_required_field_is_unsupported_schema_naming_field_and_version(world, field):
    last = json.loads(json.dumps(world.rows[-1]))
    if "." in field:
        outer, inner = field.split(".")
        last[outer].pop(inner)
    else:
        last.pop(field)
    world.rows[-1] = last
    world.flush()
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    if field == "version":
        # the version is found on the other records, so only the assistant probe names the field
        assert code(e) == "unsupported_schema" and "`version`" in str(e.value)
    else:
        assert code(e) == "unsupported_schema" and f"`{field}`" in str(e.value) and "2.1.296" in str(e.value)


def test_field_of_the_wrong_type_is_unsupported_schema(world):
    world.rows[-1]["effort"] = {"level": "high"}
    world.flush()
    with pytest.raises(ev.EvidenceError) as e:
        ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)
    assert code(e) == "unsupported_schema" and "`effort`" in str(e.value)


def test_extra_fields_and_unused_record_kinds_are_ignored(world):
    world.rows[-1]["brand_new_field"] = {"x": 1}
    world.rows.append({"type": "attachment-from-a-future-version", "sessionId": SESSION, "payload": [1, 2]})
    world.flush()
    assert ev.preflight(root=world.repo, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)["result"] == "ready"


def test_collect_names_the_missing_spawn_result_field_and_version(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task, status="completed")  # only a background launch may omit the resolved model
    for row in world.rows:
        if isinstance(row.get("toolUseResult"), dict):
            row["toolUseResult"].pop("resolvedModel")
    world.flush()
    err = blocked(world, prepared["birth"])
    assert err.code == "unsupported_schema" and "`resolvedModel`" in str(err) and VERSION in str(err)


def test_collect_names_the_missing_child_model_field(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    child = world.subdir / f"agent-{AGENT}.jsonl"
    rows = [json.loads(line) for line in child.read_text().splitlines()]
    rows[1]["message"].pop("model")
    write_jsonl(child, rows)
    err = blocked(world, prepared["birth"])
    assert err.code == "unsupported_schema" and "`message.model`" in str(err)


def test_evidence_that_diverges_fails_the_gate_in_every_host_version(world):
    world.rows = [dict(r, version="9.9.9") for r in world.rows]
    world.flush()
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task, child_model="claude-opus-5-5")
    child = world.subdir / f"agent-{AGENT}.jsonl"
    write_jsonl(child, [dict(json.loads(line), version="9.9.9") for line in child.read_text().splitlines()])
    assert blocked(world, prepared["birth"]).code == "model_mismatch"


def test_host_below_the_capability_floor_is_capability_unavailable_and_newer_is_not_refused_by_number():
    import model_selection

    contract = {"env_overrides": [], "host_min_version": "2.1.292"}
    with pytest.raises(model_selection.SelectionError, match="capability_unavailable.*2.1.291"):
        model_selection.claude_host_checks(contract, {"version": "2.1.291", "environ": {}})
    for version in ("2.1.292", "2.1.299", "9.9.9"):
        model_selection.claude_host_checks(contract, {"version": version, "environ": {}})


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


def test_truncated_parent_or_child_and_unknown_child_surface(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    child = world.subdir / f"agent-{AGENT}.jsonl"
    good = child.read_bytes()
    child.write_bytes(good.rstrip(b"\n"))
    assert blocked(world, prepared["birth"]).code == "source_truncated"
    rows = [dict(json.loads(line), entrypoint="claude-vscode") for line in good.decode().splitlines()]
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


# --- pilot findings 10, 11 and 1 (design section 18) -----------------------------------


def synthetic_row(world, *, msg_id="syn", sidechain=True, agent=AGENT):
    row = record("assistant", world.repo, isSidechain=sidechain, uuid=f"u-{msg_id}",
                 message={"model": "<synthetic>", "id": msg_id, "role": "assistant",
                          "content": [{"type": "text", "text": "API Error: 429 rate limit"}]})
    row["isApiErrorMessage"] = True
    if agent:
        row["agentId"] = agent
    return row


def test_a_final_synthetic_turn_classifies_the_child_as_failed_and_counts_it(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task, extra_child_rows=(synthetic_row(world),))
    result = world.collect(prepared["birth"])
    assert result["status"] == "failed" and result["payload_returned"] is False
    assert result["synthetic_final"] is True and len(result["synthetic_turns"]) == 1
    # the real turns before the error stay the observation; <synthetic> is never a model_mismatch
    assert len(result["turns"]) == 2 and ev.observed_pair(result) == {"model": "claude-sonnet-5-5", "effort": "high"}


def test_an_intermediate_synthetic_turn_is_excluded_from_the_model_comparison_and_counted(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    child = world.subdir / f"agent-{AGENT}.jsonl"
    rows = [json.loads(line) for line in child.read_text().splitlines()]
    rows.insert(2, synthetic_row(world, msg_id="mid"))
    write_jsonl(child, rows)
    result = world.collect(prepared["birth"])
    assert result["status"] == "completed" and result["synthetic_final"] is False
    assert len(result["synthetic_turns"]) == 1 and len(result["turns"]) == 2


def test_a_child_that_only_produced_a_429_turn_is_failed_with_no_observation(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task, child_tools=(), handback=None, extra_child_rows=(synthetic_row(world),))
    result = world.collect(prepared["birth"])
    assert result["status"] == "failed" and result["turns"] == [] and result["payload_returned"] is False
    assert ev.observed_pair(result) == {"model": ev.UNAVAILABLE, "effort": ev.UNAVAILABLE}


def test_a_parent_synthetic_turn_is_not_the_parent_observation(world):
    world.rows.append(synthetic_row(world, msg_id="p429", sidechain=False, agent=None))
    world.flush()
    assert ev.observe_parent(session=SESSION, runtime=world.runtime, environ=world.env)["model"] == "claude-sonnet-5-5"


def test_a_child_born_before_EnterWorktree_is_still_collectable_from_the_receipt_values(world, tmp_path):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    moved = tmp_path / "card-1101-moved"
    moved.mkdir()
    # the session moves to another worktree after the birth: only the parent's present cwd changes
    world.rows.append(record("user", moved, message={"role": "user", "content": "next"}))
    world.rows.append(assistant(moved, model="claude-sonnet-5-5", effort="high", content=[{"type": "text", "text": "in the new worktree"}], msg_id="m-moved"))
    world.flush()
    birth = json.loads(Path(prepared["birth"]).read_text())
    assert birth["parent_cwd"] == str(world.repo)
    result = world.collect(prepared["birth"])
    assert result["status"] == "completed" and result["host_version"] == VERSION


def test_accepted_evidence_stays_valid_when_the_host_updates_after_collection(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    result = world.collect(prepared["birth"])
    assert result["host_versions"] == [VERSION]
    # the host updates and the session is resumed: a later parent record carries a new version
    world.rows.append(assistant(world.repo, model="claude-sonnet-5-5", effort="high", content=[{"type": "text", "text": "after the update"}], msg_id="m-after-update", version="2.1.299"))
    world.flush()
    proof = ev.verify_evidence(result["evidence_path"], runtime=world.runtime)
    assert proof["integrity_sha256"] == result["integrity_sha256"] and proof["host_versions"] == [VERSION]
    assert world.collect(prepared["birth"])["integrity_sha256"] == result["integrity_sha256"]


def test_a_child_whose_cwd_differs_from_the_parent_cwd_recorded_at_birth_is_identity_mismatch(world, tmp_path):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    child = world.subdir / f"agent-{AGENT}.jsonl"
    write_jsonl(child, [dict(json.loads(line), cwd=str(elsewhere)) for line in child.read_text().splitlines()])
    assert blocked(world, prepared["birth"]).code == "identity_mismatch"


def test_a_child_with_another_host_version_than_the_parent_at_birth_is_identity_mismatch(world):
    cap, _p, task, prepared = world.prepare()
    world.spawn(cap, task)
    child = world.subdir / f"agent-{AGENT}.jsonl"
    write_jsonl(child, [dict(json.loads(line), version="2.1.299") for line in child.read_text().splitlines()])
    err = blocked(world, prepared["birth"])
    assert err.code == "identity_mismatch" and "2.1.299" in str(err)


def prepare_named(world, role, task):
    cap, path = world.capture(role)
    return cap, ev.prepare(root=world.repo, capture=path, task_name=task, runtime=world.runtime, session=SESSION, environ=world.env, trust=trust_ok)


def test_prepare_records_the_card_of_the_task_name_when_git_binds_none(tmp_path):
    world = World(tmp_path, name="develop")
    cap, prepared = prepare_named(world, "grill-card", "grill-card 703 afiar")
    birth = json.loads(Path(prepared["birth"]).read_text())
    assert birth["bound_card"] == "703" and birth["card_source"] == "task_name"


def test_prepare_refuses_card_mismatch_when_git_binds_another_card(world):
    with pytest.raises(ev.EvidenceError) as e:
        prepare_named(world, "grill-card", "grill-card 703 afiar")
    assert e.value.code == "card_mismatch" and "1101" in str(e.value) and "703" in str(e.value)
    assert not list((world.repo / ".cursor" / "tmp" / "claude-evidence").glob("*.birth.json"))


def test_prepare_with_matching_card_keeps_git_as_the_source_and_a_task_name_without_card_is_accepted(world, tmp_path):
    _cap, prepared = prepare_named(world, "grill-card", "grill-card 1101 afiar")
    assert json.loads(Path(prepared["birth"]).read_text())["card_source"] == "git"
    (tmp_path / "w2").mkdir()
    other = World(tmp_path / "w2", name="develop")
    _cap, prepared = prepare_named(other, "grill-card", "grill-card sem-card")
    assert json.loads(Path(prepared["birth"]).read_text())["bound_card"] == ev.UNAVAILABLE


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
