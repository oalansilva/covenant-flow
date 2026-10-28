"""Controlled sources; these tests never qualify the invoking native host."""
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

import codex_context as cc
import codex_evidence as ce
from model_selection import resolve, save_capture
from test_codex_evidence import Essay
from model_selection_fixtures import machine_models

SENTINEL = "parent_only_nonsecret_sentinel_13579"
INSTRUCTION = 'Full-history forks (`fork_turns` omitted or "all") inherit the parent model. Set `fork_turns` to "none" for overrides.'


@pytest.fixture
def diagnostic(tmp_path, monkeypatch, machine_models):
    e = Essay(tmp_path, monkeypatch, host="codex-tui")
    e.birth.unlink()  # Only this fixture's first, unused diagnostic receipt.
    e.p[1]["payload"]["multi_agent_version"] = "v2"
    e.p += [e.row("response_item", {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": INSTRUCTION}]}), e.row("response_item", {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "context_sentinel: " + SENTINEL}]})]
    e.write(e.parent, e.p)
    binary = {"source": "/proc/123/exe", "pid": 123, "starttime": "55", "device": 1, "inode": 9, "executable": "/native/codex", "binary_sha256": "b" * 64, "version": "codex-cli 0.162.1", "fragments": [{"offset": i * 100, "length": len(fragment), "sha256": cc.sha(fragment)} for i, fragment in enumerate(cc.FRAGMENTS)]}
    monkeypatch.setattr(cc, "ancestry_binary", lambda: binary)
    e.context_result = cc.prepare(root=e.root, capture=e.capture, task_name=e.task, sentinel_record=3, qualification=True)
    e.plan = Path(e.context_result["context_plan"])
    e.control = e.context_result["message"].split("\ncontrol: ")[1].split("\n")[0]
    with pytest.raises(ce.EvidenceError, match="birth_mismatch"):
        e.collect()
    e.complete()
    call = next(r["payload"] for r in e.p if r["payload"].get("type") == "function_call")
    args = json.loads(call["arguments"])
    args["message"] = e.context_result["message"]
    call["arguments"] = json.dumps(args)
    inbound = e.row("response_item", {"type": "agent_message", "author": "/root", "content": [{"type": "input_text", "text": f"Message Type: NEW_TASK\nTask name: {e.agent_path}\nSender: /root\nPayload:\n" + args["message"]}]})
    e.c.insert(1, inbound)
    payload(e, {"control": e.control, "sentinel": None})
    return e


def payload(e, answer):
    value = json.dumps(answer) if not isinstance(answer, str) else answer
    for row in e.c:
        if row["payload"].get("type") == "task_complete":
            row["payload"]["last_agent_message"] = value
    e.p[-1]["payload"]["content"][0]["text"] = "Message Type: FINAL_ANSWER\nPayload:\n" + value
    e.write(e.parent, e.p)
    e.write(e.child, e.c)


def lifecycle(e):
    proof = e.collect()
    ce.qualify(proof["evidence_path"], list(e.birth.parent.glob("*.failure-*.json")))
    return proof


def next_diagnostic(e, monkeypatch, *, complete=True):
    """Append a distinct attempt to real fixture rollouts, never fake receipts."""
    import copy
    import uuid
    n = copy.copy(e)
    token = uuid.uuid4().hex
    n.task = "context_" + token
    n.agent_path = "/root/" + n.task
    n.child_id = "child-" + token
    n.child = n.sessions / (n.child_id + ".jsonl")
    n.cap = resolve("codex", "execucao", role="qa-gate")
    n.capture = n.root / (token + ".capture.json")
    save_capture(n.capture, n.cap)
    ordinal = len(n.p)
    n.p.append(n.row("response_item", {"type": "message", "role": "assistant",
        "content": [{"type": "output_text", "text": "context_sentinel: " + uuid.uuid4().hex}]}))
    n.write(n.parent, n.p)
    n.context_result = cc.prepare(root=n.root, capture=n.capture, task_name=n.task,
        sentinel_record=ordinal, qualification=True)
    n.birth = Path(n.context_result["birth"])
    n.plan = Path(n.context_result["context_plan"])
    n.control = n.context_result["message"].split("\ncontrol: ")[1].split("\n")[0]
    if complete:
        n.complete()
        call = next(r["payload"] for r in reversed(n.p) if r["payload"].get("type") == "function_call")
        args = json.loads(call["arguments"]);args["message"] = n.context_result["message"]
        call["arguments"] = json.dumps(args)
        n.c.insert(1, n.row("response_item", {"type": "agent_message", "author": "/root",
            "content": [{"type": "input_text", "text": args["message"]}]}))
        payload(n, {"control": n.control, "sentinel": None})
    return n


@pytest.mark.parametrize("failure", ["sentinel", "control", "incomplete", "not-started", "missing-plan"])
def test_newer_diagnostic_prevents_fallback_to_old_success(diagnostic, monkeypatch, failure):
    e = diagnostic
    old = cc.qualify(e.plan)
    n = next_diagnostic(e, monkeypatch, complete=failure not in {"not-started", "missing-plan"})
    if failure == "sentinel":
        marker = n.p[json.loads(n.plan.read_text())["sentinel_source"]["ordinal"]]["payload"]["content"][0]["text"].split(": ")[1]
        payload(n, {"control": n.control, "sentinel": marker})
    elif failure == "control":payload(n, {"control": "wrong", "sentinel": None})
    elif failure == "incomplete":
        n.c = [r for r in n.c if r["payload"].get("type") != "task_complete"]
        n.write(n.child, n.c)
    elif failure == "missing-plan":n.plan.unlink()
    if failure in {"sentinel", "control", "incomplete"}:
        with pytest.raises(ce.EvidenceError):cc.qualify(n.plan)
    for expected in (None, old["qualification_path"]):
        with pytest.raises(ce.EvidenceError, match="context_qualification_(missing|mismatch)"):
            cc.verify_qualification(root=e.root, out=e.birth.parent, session=e.parent_id, expected_path=expected)
    assert Path(old["qualification_path"]).is_file()


def test_new_legitimate_success_replaces_old_success_even_with_reversed_mtime(diagnostic, monkeypatch):
    import os
    e = diagnostic;old = cc.qualify(e.plan)
    n = next_diagnostic(e, monkeypatch)
    new = cc.qualify(n.plan)
    os.utime(n.plan, (1, 1));os.utime(Path(new["qualification_path"]), (1, 1))
    result = cc.verify_qualification(root=e.root, out=e.birth.parent, session=e.parent_id)
    assert result["attempt_id"] == n.cap["attempt_id"] != old["attempt_id"]
    assert result["qualification_path"] == new["qualification_path"]


@pytest.mark.parametrize("foreign", ["parent", "root"])
def test_unrelated_context_attempt_cannot_supersede_this_parent(diagnostic, monkeypatch, foreign):
    e = diagnostic;old = cc.qualify(e.plan)
    n = next_diagnostic(e, monkeypatch, complete=False)
    for path in (n.birth, n.plan):
        value = json.loads(path.read_text());value.pop("integrity_sha256")
        value["parent_thread" if foreign == "parent" else "root"] = "different-parent" if foreign == "parent" else str(e.root.parent / "different-root")
        path.write_text(json.dumps(ce.sealed(value)))
    assert cc.verify_qualification(root=e.root, out=e.birth.parent, session=e.parent_id)["attempt_id"] == old["attempt_id"]


def test_new_scope_failure_does_not_reuse_previous_scope_success(diagnostic, monkeypatch):
    e = diagnostic;cc.qualify(e.plan)
    original = cc.ancestry_binary()
    monkeypatch.setattr(cc, "ancestry_binary", lambda: dict(original, binary_sha256="d" * 64))
    next_diagnostic(e, monkeypatch, complete=False)
    with pytest.raises(ce.EvidenceError, match="context_qualification_missing"):
        cc.verify_qualification(root=e.root, out=e.birth.parent, session=e.parent_id)


def test_three_independent_sources_qualify_operational_context_only(diagnostic):
    e = diagnostic
    lifecycle(e)
    assert ce.preflight(root=e.root)["capabilities"]["context_isolation"] == "unavailable"
    observation = cc.qualify(e.plan)
    assert observation["result"] == "passed"
    assert observation["internal_context_attestation"] == "unavailable"
    assert observation["request_observation"] == "requested"
    for marker in (SENTINEL, e.control):
        assert marker not in json.dumps(observation)
    assert SENTINEL not in e.plan.read_text()
    pf = ce.preflight(root=e.root, stage="iniciar_apply")
    assert pf["capabilities"]["context_isolation"] == "verified"
    assert pf["capabilities"]["internal_context_attestation"] == "unavailable"
    assert pf["capabilities"]["diagnostic_work_barrier"] == "unavailable"
    assert pf["context_qualification"]["child_thread"] == e.child_id
    capture = e.root / "next.capture.json"
    save_capture(capture, resolve("codex", "execucao", role="qa-gate"))
    new = ce.prepare(root=e.root, capture=capture, task_name="next_stage")
    birth = json.loads(Path(new["birth"]).read_text())
    assert birth["context_scope_sha256"] == observation["scope_sha256"]
    assert birth["work_release"] == "stage"
    # Existing #1049 guarantees are not supplied by this qualification.
    with pytest.raises(ce.EvidenceError, match="parent_sandbox_mismatch.*parent_read_only"):
        ce.preflight(root=e.root, stage="pedir_review")
    with pytest.raises(ce.EvidenceError, match="parent_sandbox_mismatch"):
        ce.preflight(root=e.root, review=True)


def test_native_encrypted_task_is_requested_not_delivered_plaintext_attestation(diagnostic):
    e = diagnostic
    call = next(r["payload"] for r in e.p if r["payload"].get("type") == "function_call")
    args = json.loads(call["arguments"])
    args["message"] = "gAAAA" + "Z" * 120 + "=="
    call["arguments"] = json.dumps(args)
    e.c[1]["payload"]["content"] = [{"type": "input_text", "text": f"Message Type: NEW_TASK\nTask name: {e.agent_path}\nSender: /root\nPayload:\n"}, {"type": "encrypted_content", "encrypted_content": "opaque-native-task"}]
    e.write(e.parent, e.p)
    e.write(e.child, e.c)
    result = cc.qualify(e.plan)
    assert result["native_task_text"] == "opaque"
    assert result["request_observation"] == "requested"
    assert result["internal_context_attestation"] == "unavailable"
    assert "opaque task text" in result["limitation"]


@pytest.mark.parametrize("mutation,code", [
    ("control", "context_control_mismatch"),
    ("sentinel", "context_sentinel_leaked"),
    ("guess", "context_essay_incomplete"),
    ("payload", "context_essay_incomplete"),
    ("fork_all", "context_request_mismatch"),
    ("fork_missing", "context_request_mismatch"),
    ("tool", "context_contaminated"),
    ("opaque_tool", "context_contaminated"),
    ("steering", "context_essay_incomplete"),
    ("parent_steering", "context_contaminated"),
    ("child_host", "context_essay_incomplete"),
    ("sentinel_tool", "context_contaminated"),
    ("sentinel_source", "context_source_changed"),
    ("request", "context_request_mismatch"),
])
def test_missing_divergent_contaminated_inputs_never_qualify(diagnostic, mutation, code):
    e = diagnostic
    call = next(r["payload"] for r in e.p if r["payload"].get("type") == "function_call")
    args = json.loads(call["arguments"])
    if mutation == "control":
        payload(e, {"control": "wrong", "sentinel": None})
    elif mutation == "sentinel":
        payload(e, {"control": e.control, "sentinel": SENTINEL})
    elif mutation == "guess":
        payload(e, {"control": e.control, "sentinel": "guessed"})
    elif mutation == "payload":
        payload(e, "not JSON")
    elif mutation.startswith("fork"):
        args.pop("fork_turns") if mutation == "fork_missing" else args.update(fork_turns="all")
    elif mutation in {"tool", "opaque_tool"}:
        e.c.insert(-1, e.row("response_item", {"type": "function_call" if mutation == "tool" else "custom_tool_call", "name": "read_file", "arguments": "opaque"}))
    elif mutation == "steering":
        e.c.insert(-1, e.c[1])
    elif mutation == "parent_steering":
        e.p.append(e.row("response_item", {"type": "function_call", "namespace": "collaboration", "name": "send_message", "arguments": json.dumps({"target": e.agent_path, "message": "opaque"})}))
    elif mutation == "child_host":
        e.c[0]["payload"]["originator"] = "other-host"
    elif mutation == "sentinel_tool":
        e.p.append(e.row("response_item", {"type": "custom_tool_call", "input": "save " + SENTINEL}))
    elif mutation == "sentinel_source":
        e.p[3]["payload"]["content"][0]["text"] += "changed"
    elif mutation == "request":
        args["message"] = "some different readable prompt"
    call["arguments"] = json.dumps(args)
    e.write(e.parent, e.p)
    e.write(e.child, e.c)
    with pytest.raises(ce.EvidenceError, match=code):
        cc.qualify(e.plan)
    assert not list(e.birth.parent.glob("context-qualification-*.json"))


@pytest.mark.parametrize("change", ["plan", "receipt", "child", "binary", "runtime_instruction", "host", "root", "session"])
def test_qualification_revalidates_sources_identity_and_scope(diagnostic, monkeypatch, change):
    e = diagnostic
    cc.qualify(e.plan)
    kwargs = dict(root=e.root, out=e.birth.parent, session=e.parent_id)
    if change == "plan":
        value = json.loads(e.plan.read_text())
        value["control_sha256"] = "0" * 64
        e.plan.write_text(json.dumps(value))
    elif change == "receipt":
        target = next(e.birth.parent.glob("context-qualification-*.json"))
        value = json.loads(target.read_text())
        value["observation"]["child_thread"] = "another-child"
        target.write_text(json.dumps(ce.sealed({k: v for k, v in value.items() if k != "integrity_sha256"})))
    elif change == "child":
        e.c[0]["payload"]["source"]["subagent"]["thread_spawn"]["parent_thread_id"] = "other-parent"
        e.write(e.child, e.c)
    elif change == "binary":
        original = cc.ancestry_binary()
        monkeypatch.setattr(cc, "ancestry_binary", lambda: dict(original, binary_sha256="c" * 64))
    elif change == "runtime_instruction":
        e.p[2]["payload"]["extra"] = "tampered source"
        e.write(e.parent, e.p)
    elif change == "host":
        e.p[0]["payload"]["originator"] = "other-host"
        e.write(e.parent, e.p)
    elif change == "root":
        kwargs["root"] = e.root.parent
    else:
        kwargs["session"] = "another-session"
    with pytest.raises((ce.EvidenceError, OSError, KeyError)):
        cc.verify_qualification(**kwargs)


def test_incomplete_or_continued_essay_is_not_a_positive(diagnostic):
    e = diagnostic
    cc.qualify(e.plan)
    e.continue_turn("not-another-diagnostic")
    with pytest.raises(ce.EvidenceError, match="context_essay_incomplete"):
        cc.verify_qualification(root=e.root, out=e.birth.parent, session=e.parent_id)


def test_diagnostic_requires_explicit_qualification_and_source_contract(diagnostic):
    e = diagnostic
    with pytest.raises(ce.EvidenceError, match="context_diagnostic_required"):
        cc.prepare(root=e.root, capture=e.capture, task_name="no_product", sentinel_record=3)
    e.p[1]["payload"].pop("multi_agent_version")
    e.write(e.parent, e.p)
    with pytest.raises(ce.EvidenceError, match="context_contract_unavailable"):
        cc.inspect(root=e.root, qualification=True)


def test_requested_prompt_hook_compares_without_promoting_to_observed(diagnostic):
    e = diagnostic
    arguments = dict(e.cap["arguments"], task_name=e.task, fork_turns="none", message=e.context_result["message"])
    assert ce.check_prepared_spawn(arguments, e.root)["qualification"]
    arguments["message"] += "\nextra"
    with pytest.raises(ce.EvidenceError, match="context_request_mismatch"):
        ce.check_prepared_spawn(arguments, e.root)


@pytest.fixture
def native_process(tmp_path, monkeypatch):
    proc = tmp_path / "proc"
    ancestor = proc / "11"
    child = proc / "10"
    ancestor.mkdir(parents=True)
    child.mkdir()
    python = tmp_path / "python"
    python.write_bytes(b"python process")
    native = tmp_path / "codex"
    native.write_bytes(b"\x00".join(cc.FRAGMENTS))
    (child / "exe").symlink_to(python)
    (child / "status").write_text("PPid:\t11\n")
    (ancestor / "exe").symlink_to(native)
    (ancestor / "status").write_text("PPid:\t0\n")
    (ancestor / "stat").write_text("11 (native codex) " + " ".join(["S"] + ["0"] * 18 + ["123456"]))
    monkeypatch.setattr(cc, "PROC_ROOT", proc)
    monkeypatch.setattr(cc.os, "getpid", lambda: 10)
    monkeypatch.setattr(cc.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="codex-cli 0.163.0\n"))
    return native, ancestor


def test_binary_is_discovered_from_ancestry_and_fragments_are_revalidatable(native_process):
    native, ancestor = native_process
    result = cc.ancestry_binary()
    assert result["pid"] == 11 and result["starttime"] == "123456"
    assert result["binary_sha256"] == cc.sha(native.read_bytes())
    for expected, actual in zip(cc.FRAGMENTS, result["fragments"]):
        assert native.read_bytes()[actual["offset"]:actual["offset"] + actual["length"]] == expected
        assert actual["sha256"] == cc.sha(expected)


@pytest.mark.parametrize("mutation", ["fragment", "inaccessible", "version", "pid_reuse", "exe_replaced"])
def test_binary_missing_raced_or_unverifiable_never_qualifies(native_process, monkeypatch, mutation):
    native, ancestor = native_process
    code = "context_contract_unavailable"
    if mutation == "fragment":
        native.write_bytes(cc.FRAGMENTS[0])
    elif mutation == "inaccessible":
        (ancestor / "exe").unlink()
    elif mutation == "version":
        monkeypatch.setattr(cc.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="an arbitrary executable"))
    else:
        def race(*args, **kwargs):
            if mutation == "pid_reuse":
                (ancestor / "stat").write_text((ancestor / "stat").read_text().replace("123456", "654321"))
            else:
                replacement = native.with_name("replacement")
                replacement.write_bytes(native.read_bytes())
                (ancestor / "exe").unlink()
                (ancestor / "exe").symlink_to(replacement)
            return SimpleNamespace(stdout="codex-cli 0.163.0")
        monkeypatch.setattr(cc.subprocess, "run", race)
        code = "context_runtime_changed"
    with pytest.raises(ce.EvidenceError, match=code):
        cc.ancestry_binary()


def test_runtime_version_cannot_be_asserted_from_an_unrelated_binary(diagnostic, monkeypatch):
    e = diagnostic
    original = cc.ancestry_binary()
    monkeypatch.setattr(cc, "ancestry_binary", lambda: dict(original, version="codex-cli 9.9.9"))
    with pytest.raises(ce.EvidenceError, match="context_runtime_mismatch"):
        cc.inspect(root=e.root, qualification=True)


def test_cli_failure_is_explicit_and_never_a_positive(diagnostic, capsys):
    assert cc.main(["inspect", "--root", str(diagnostic.root)]) == 2
    result = json.loads(capsys.readouterr().out)
    assert result["result"] == "incomplete"
    assert result["code"] == "context_diagnostic_required"
    assert result["internal_context_attestation"] == "unavailable"


def test_actual_stage_birth_is_rechecked_and_qualification_is_not_transferable(diagnostic):
    e = diagnostic
    lifecycle(e)
    cc.qualify(e.plan)
    capture = e.root / "next.capture.json"
    cap = resolve("codex", "execucao", role="qa-gate")
    save_capture(capture, cap)
    prepared = ce.prepare(root=e.root, capture=capture, task_name="qa_gate_next_stage")
    native = {"internal_chat_message_metadata_passthrough": {"turn_id": "parent-turn"}}
    args = dict(cap["arguments"], task_name="qa_gate_next_stage", agent_type="default", fork_turns="none", message="stage task")
    e.p += [e.row("response_item", dict(type="function_call", name="spawn_agent", namespace="collaboration", call_id="next-call", arguments=json.dumps(args), **native)), e.row("response_item", dict(type="function_call_output", call_id="next-call", output=json.dumps({"task_name": "/root/qa_gate_next_stage"}), **native)), e.row("response_item", {"type": "agent_message", "author": "/root/qa_gate_next_stage", "content": [{"type": "input_text", "text": "Message Type: FINAL_ANSWER\nPayload:\nnext result"}]})]
    other = e.home / "sessions/next-stage.jsonl"
    child = json.loads(json.dumps(e.c))
    child[0]["payload"].update(id="next-child", source={"subagent": {"thread_spawn": {"parent_thread_id": e.parent_id, "agent_path": "/root/qa_gate_next_stage"}}})
    child = [row for row in child if row["payload"].get("type") != "agent_message"]
    for row in child:
        if row["payload"].get("type") == "task_complete":
            row["payload"]["last_agent_message"] = "next result"
    e.write(e.parent, e.p)
    e.write(other, child)
    with sqlite3.connect(e.home / "state_5.sqlite") as db:
        db.execute("INSERT INTO threads VALUES (?,?,?)", ("next-child", str(other), "/root/qa_gate_next_stage"))
    result = ce.collect(prepared["birth"], wait_seconds=0)
    assert result["capabilities"]["context_isolation"] == "verified"
    assert result["capabilities"]["internal_context_attestation"] == "unavailable"
    assert ce.verify_evidence(result["evidence_path"])["child_thread"] == "next-child"
    args["fork_turns"] = "all"
    e.p[-3]["payload"]["arguments"] = json.dumps(args)
    e.write(e.parent, e.p)
    with pytest.raises(ce.EvidenceError, match="context_request_mismatch"):
        ce.verify_evidence(result["evidence_path"])


def test_legacy_v2_snapshot_keeps_its_original_capability_shape(diagnostic):
    e = diagnostic
    birth = json.loads(e.birth.read_text())
    birth.pop("integrity_sha256")
    birth["stage_contract"] = ce.LEGACY_STAGE_CONTRACT
    e.birth.write_text(json.dumps(ce.sealed(birth)))
    result = e.collect()
    assert result["stage_contract"] == "codex-native-stage-v2"
    assert "internal_context_attestation" not in result["capabilities"]
    assert result["capabilities"]["context_isolation"] == "unavailable"
    assert ce.verify_evidence(result["evidence_path"])["stage_contract"] == "codex-native-stage-v2"


def mirrored_sentinel(e):
    rows = json.loads(json.dumps(e.p[:4]))
    source = rows[-1]["payload"]
    source.update(id="msg-native-sentinel", phase="commentary", internal_chat_message_metadata_passthrough={"turn_id": "parent-turn"})
    source["content"][0].update(type="output_text", annotations=[], logprobs=[])
    mirror = e.row("event_msg", {"type": "item_completed", "thread_id": e.parent_id, "turn_id": "parent-turn", "started_at_ms": 1, "completed_at_ms": 2, "item": {"type": "AgentMessage", "id": source["id"], "phase": "commentary", "content": [{"type": "Text", "text": source["content"][0]["text"]}]}})
    rows.insert(3, mirror)
    return rows


def test_prepare_accepts_only_the_identity_bound_native_mirror(diagnostic):
    e = diagnostic
    rows = mirrored_sentinel(e)
    assert cc.check_new_sentinel([(i, row, "source-digest") for i, row in enumerate(rows)], 4, e.parent_id) == SENTINEL
    e.birth.unlink()
    e.plan.unlink()
    e.write(e.parent, rows)
    result = cc.prepare(root=e.root, capture=e.capture, task_name=e.task, sentinel_record=4, qualification=True)
    assert Path(result["birth"]).is_file()
    assert SENTINEL not in json.dumps(result)
    assert SENTINEL not in Path(result["context_plan"]).read_text()


@pytest.mark.parametrize("mutation", ["id", "turn", "thread", "phase", "content", "type", "old_message", "nonadjacent"])
def test_native_mirror_exception_cannot_hide_prior_reuse(diagnostic, mutation):
    e = diagnostic
    rows = mirrored_sentinel(e)
    mirror = rows[3]["payload"]
    ordinal = 4
    if mutation == "id":
        mirror["item"]["id"] = "unrelated-message"
    elif mutation == "turn":
        mirror["turn_id"] = "older-turn"
    elif mutation == "thread":
        mirror["thread_id"] = "another-parent"
    elif mutation == "phase":
        mirror["item"]["phase"] = "final_answer"
    elif mutation == "content":
        mirror["item"]["content"][0]["text"] += "different"
    elif mutation == "type":
        mirror["item"]["type"] = "UnknownMessage"
    elif mutation == "old_message":
        rows.insert(3, json.loads(json.dumps(rows[4])))
        ordinal += 1
    else:
        rows.insert(4, e.row("event_msg", {"type": "unrelated-event"}))
        ordinal += 1
    with pytest.raises(ce.EvidenceError, match="context_markers_invalid"):
        cc.check_new_sentinel([(i, row, "source-digest") for i, row in enumerate(rows)], ordinal, e.parent_id)
