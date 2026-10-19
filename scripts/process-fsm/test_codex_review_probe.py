"""Controlled native-event fixtures; never qualify the real host."""
import copy
import errno
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import codex_evidence as ce
import codex_review_probe as rp
from model_selection import save_capture
from model_selection_fixtures import machine_models
from test_codex_evidence import Essay, essay


@pytest.mark.parametrize('unit', ['x', '"\\', '\x00\x01\b\n\t', '\x7f', 'á中\u2028', '😀🧪'])
def test_adaptive_pages_bound_actual_json_and_outer_return_for_escapes_unicode(tmp_path, unit):
    text=unit*20000
    diff=tmp_path/'adversarial.patch';diff.write_text(text)
    plan={'diff':str(diff),'diff_sha256':ce.digest(text.encode()),'integrity_sha256':'a'*64,
          'root':str(tmp_path),'helper':str(tmp_path/'probe.py'),'interpreter':sys.executable,'plan_path':str(tmp_path/'plan.json')}
    pages=[rp.read_chunk_result(plan,'review-child',i) for i in range(rp.delivery(text.encode())['chunk_count'])]
    assert ''.join(page['diff_text'] for page in pages)==text
    assert pages[0]['start_char']==0 and pages[-1]['end_char']==len(text)
    for previous,current in zip(pages,pages[1:]):
        assert previous['end_char']==current['start_char']
    for page in pages:
        # Independently serialize the actual native stdout and an exec result
        # with ASCII Unicode escapes and realistic wrapper metadata.
        native=json.dumps(page,sort_keys=True,ensure_ascii=False)+'\n'
        returned=json.dumps({'chunk_id':'abcdef','wall_time_seconds':1.234,'exit_code':0,
            'original_token_count':19999,'output':native},ensure_ascii=True)
        assert len(native.encode())<=16000
        assert len(returned.encode())+256<=28000
        assert json.loads(json.loads(returned)['output'])==page
    if unit=='x':
        assert len(pages) < (len(text)+4095)//4096 / 2
    if unit=='😀🧪':
        assert max(len(page['diff_text']) for page in pages)<4096


def test_full_serialized_payload_over_limit_is_refused_instead_of_truncated():
    with pytest.raises(ce.EvidenceError,match='review_diff_output_limit'):
        rp.require_bounded({'diff':'x'*4096,'diff_text':'y'*14000})
    with pytest.raises(ce.EvidenceError,match='review_diff_output_limit'):
        rp.require_bounded({'diff_text':'😀'*5000})


def test_pinned_probe_cli_loads_in_isolated_python_without_user_paths():
    completed = subprocess.run([sys.executable, "-I", rp.__file__, "--help"], capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert "{prepare,run,read,qualify}" in completed.stdout


def prepare_diagnostic(tmp_path, monkeypatch, role="diff-reviewer", *, suffix="", qualification=True, diff_text=None):
    e = Essay(tmp_path, monkeypatch, role=role, sandbox="read-only", qualification=True, wave="probe-wave", skip_prepare=True, capture_suffix=suffix)
    e.p[1]["payload"]["sandbox_policy"] = {"type": "workspace-write"}
    e.write(e.parent, e.p)
    if suffix:
        e.task += suffix; e.agent_path += suffix; e.child_id += suffix
        e.child = e.child.with_name(e.child.stem + suffix + ".jsonl")
    e.review_turn = "review-turn" + suffix
    capture = e.root / f"{role}{suffix}.capture.json"
    save_capture(capture, e.cap)
    helper = e.root / "codex_review_probe.py"
    if not helper.exists():
        shutil.copyfile(rp.__file__, helper)
    monkeypatch.setattr(rp, "__file__", str(helper))
    diff = e.root / "review.patch"
    diff.write_text(diff_text if diff_text is not None else "diff --git a/x b/x\n-old\n+new\n")
    prepared = rp.prepare(root=e.root, capture=capture, diff=diff, wave_id="probe-wave")
    plan_file = Path(prepared["plan"])
    plan = rp.read_plan(plan_file)
    e.receipt = ce.prepare(root=e.root, capture=e.capture, task_name=e.task,
        qualification=qualification, wave_id="probe-wave", review_diff_sha256=ce.digest(diff.read_bytes()),
        review_probe_plan=plan_file, defer_review_turn=True)
    e.birth = Path(e.receipt["birth"])
    return e, plan_file, prepared


def native_delivery(e, event):
    item = event["payload"]["item"]
    call_id = "delivery-" + item["id"]
    return [e.row("response_item", {"type": "custom_tool_call", "name": "exec", "call_id": call_id,
                "input": "text(await tools.exec_command(" + json.dumps({"cmd": item["command"][-1], "max_output_tokens": 20000}) + "))"}),
            event,
            e.row("response_item", {"type": "custom_tool_call_output", "call_id": call_id,
                "output": [{"type": "input_text", "text": "Script completed\nOutput:\n"},
                           {"type": "input_text", "text": json.dumps({"output": item["aggregated_output"], "exit_code": 0})}]})]


def finish_diagnostic(e, plan_file, prepared):
    plan = rp.read_plan(plan_file)
    role = plan["role"]
    diff = Path(plan["diff"])
    e.p = [json.loads(line) for line in e.parent.read_text().splitlines()]
    # Operator's native permission change is represented by a new turn.
    if not any(row["type"] == "turn_context" and row["payload"]["turn_id"] == e.review_turn for row in e.p):
        e.p.append(e.row("turn_context", dict(e.p[1]["payload"], turn_id=e.review_turn, sandbox_policy={"type": "read-only"})))
    e.write(e.parent, e.p)
    e.sandbox = "read-only"
    e.complete()
    for row in e.p:
        if row["type"] == "response_item" and row["payload"].get("type") in {"function_call", "function_call_output"} and row["payload"].get("call_id") == "call-" + e.task:
            row["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = e.review_turn
    result = {"schema": rp.SCHEMA, "plan_sha256": plan["integrity_sha256"],
        "child_thread": e.child_id, "role": role, "attempt_id": plan["attempt_id"],
        "wave_id": "probe-wave", "diff": plan["diff"], "diff_sha256": plan["diff_sha256"],
        "diff_text": diff.read_text(), "fixture": plan["fixture"],
        "before_sha256": plan["fixture_sha256"], "after_sha256": plan["fixture_sha256"], "denied_errno": errno.EACCES}
    event = e.row("event_msg", {"type": "item_completed", "thread_id": e.child_id, "turn_id": "child-turn",
        "item": {"type": "CommandExecution", "id": "exec-probe", "command": ["/bin/bash", "-lc", prepared["command"]],
                 "cwd": e.root.as_uri(), "status": "completed", "source": "unified_exec_startup", "exit_code": 0,
                 "aggregated_output": json.dumps(result)}})
    e.c[-1:-1] = native_delivery(e, event)
    e.write(e.child, e.c); e.write(e.parent, e.p)
    return e, plan_file, event, result


def diagnostic(tmp_path, monkeypatch, role="diff-reviewer"):
    return finish_diagnostic(*prepare_diagnostic(tmp_path, monkeypatch, role))


def test_source_bound_probe_delivers_exact_diff_and_readback(tmp_path, monkeypatch, machine_models):
    e, path, event, result = diagnostic(tmp_path, monkeypatch)
    proof = e.collect()
    assert proof["native_parent_turn"] == "review-turn"
    observation = proof["review_observation"]
    assert observation["diff_read"] == observation["write_denial_readback"] == "verified"
    assert observation["sources"][0] in proof["sources"]
    ce.verify_evidence(proof["evidence_path"])
    # The deferred receipt does not itself grant writable spawn permission.
    e.p.insert(-1, e.row("turn_context", dict(e.p[1]["payload"], turn_id="premature-writable")))
    e.write(e.parent, e.p)
    with pytest.raises(ce.EvidenceError, match="parent_sandbox_mismatch"):
        e.collect()


def chunked_diagnostic(tmp_path, monkeypatch, *, chars=700740, diff_text=None):
    text = diff_text if diff_text is not None else ("diff --git a/file.py b/file.py\n@@ -1 +1 @@\n-old = 'x'\n+new = 'y'\n" * (chars // 50 + 1))[:chars]
    e, path, prepared = prepare_diagnostic(tmp_path, monkeypatch, diff_text=text)
    e, path, event, result = finish_diagnostic(e, path, prepared)
    plan = rp.read_plan(path)
    result.pop("diff_text")
    result.update(rp.delivery(text.encode()))
    result["read_command_template"] = rp.read_command(path, 0).rsplit(" ", 1)[0] + " <chunk_index>"
    result["next_read_command"] = rp.read_command(path, 0)
    event["payload"]["item"]["aggregated_output"] = json.dumps(result)
    next(row for row in e.c if row["payload"].get("type") == "custom_tool_call_output")["payload"] = native_delivery(e, event)[-1]["payload"]
    chunks = []
    for index in range(result["chunk_count"]):
        chunk = copy.deepcopy(event)
        chunk["payload"]["item"].update(id="chunk-" + str(index),
            command=["/bin/bash", "-lc", rp.read_command(path, index)],
            aggregated_output=json.dumps(rp.read_chunk_result(plan, e.child_id, index)))
        chunks.append(chunk)
    e.c[-1:-1] = [row for chunk in chunks for row in native_delivery(e, chunk)]
    e.write(e.child, e.c)
    return e, path, event, result, chunks


def test_700740_byte_diff_requires_every_source_native_chunk_not_manifest(tmp_path, monkeypatch, machine_models):
    e, path, event, manifest, chunks = chunked_diagnostic(tmp_path, monkeypatch)
    assert manifest["diff_bytes"] == 700740
    assert len(event["payload"]["item"]["aggregated_output"]) < 2000
    assert all(len(row["payload"]["item"]["aggregated_output"]) < 20000 for row in chunks)
    proof = e.collect()
    assert proof["review_observation"]["delivery"] == rp.DELIVERY
    assert proof["review_observation"]["delivered_bytes"] == 700740
    assert len(proof["review_observation"]["sources"]) == 3 * (1 + len(chunks))
    ce.verify_evidence(proof["evidence_path"])
    # Source editing after collection is never repaired from the claimed manifest.
    changed = json.loads(chunks[3]["payload"]["item"]["aggregated_output"])
    changed["diff_text"] = "synthetic metadata cannot replace delivered bytes"
    chunks[3]["payload"]["item"]["aggregated_output"] = json.dumps(changed)
    e.write(e.child, e.c)
    with pytest.raises(ce.EvidenceError):
        ce.verify_evidence(proof["evidence_path"])


@pytest.mark.parametrize("fault", ["manifest-only", "truncated", "omitted", "duplicate", "changed-text", "wrong-path", "wrong-child", "wrong-turn", "wrong-command", "wrong-index", "before-probe", "after-payload", "duplicate-probe", "oversized-inline"])
def test_chunk_delivery_never_promotes_incomplete_or_synthetic_reading(tmp_path, monkeypatch, machine_models, fault):
    e, path, probe, manifest, chunks = chunked_diagnostic(tmp_path, monkeypatch, chars=24000)
    item = chunks[1]["payload"]["item"]
    result = json.loads(item["aggregated_output"])
    if fault == "manifest-only":
        e.c = [row for row in e.c if row not in chunks]
    elif fault == "truncated": item["aggregated_output"] = item["aggregated_output"][:200]
    elif fault == "omitted": e.c.remove(chunks[1])
    elif fault == "duplicate": e.c.insert(-1, copy.deepcopy(chunks[1]))
    elif fault == "wrong-turn": chunks[1]["payload"]["turn_id"] = "other"
    elif fault == "wrong-command": item["command"][-1] += " --synthetic"
    elif fault == "before-probe": e.c.remove(chunks[0]); e.c.insert(e.c.index(probe), chunks[0])
    elif fault == "after-payload": e.c.remove(chunks[-1]); e.c.append(chunks[-1])
    elif fault == "duplicate-probe": e.c.insert(-1, copy.deepcopy(probe))
    elif fault == "oversized-inline":
        manifest.pop("delivery"); manifest["diff_text"] = Path(rp.read_plan(path)["diff"]).read_text()
        probe["payload"]["item"]["aggregated_output"] = json.dumps(manifest)
    else:
        key, value = {"changed-text": ("diff_text", "summary only"), "wrong-path": ("diff", "/other.patch"),
                      "wrong-child": ("child_thread", "other"), "wrong-index": ("chunk_index", 0)}[fault]
        result[key] = value; item["aggregated_output"] = json.dumps(result)
    e.write(e.child, e.c)
    with pytest.raises(ce.EvidenceError): e.collect()


def test_chunk_reader_does_no_write_and_preserves_unicode_boundaries(tmp_path, monkeypatch, machine_models):
    text = "x" * (rp.CHUNK_CHARS - 1) + "😀á\n" + "z" * rp.CHUNK_CHARS
    e, path, prepared = prepare_diagnostic(tmp_path, monkeypatch, diff_text=text)
    monkeypatch.setenv("CODEX_THREAD_ID", e.child_id)
    def forbidden(*args, **kwargs): raise AssertionError("chunk reader attempted write")
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    original = Path.open
    def readonly(self, mode="r", *args, **kwargs):
        assert not any(flag in mode for flag in ("w", "a", "+"))
        return original(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", readonly)
    count = rp.delivery(text.encode())["chunk_count"]
    assert "".join(rp.read_chunk(path, i)["diff_text"] for i in range(count)) == text
    for bad in (-1, count, True):
        with pytest.raises(ce.EvidenceError, match="chunk_invalid"): rp.read_chunk(path, bad)


@pytest.mark.parametrize("fault", ["missing-call", "missing-return", "wrong-call", "truncated-wrapper", "truncated-stdout", "metadata-only", "nontext", "unsupported-tool"])
def test_full_native_stdout_without_exact_model_visible_return_is_not_delivery(tmp_path, monkeypatch, machine_models, fault):
    e, path, event, result = diagnostic(tmp_path, monkeypatch)
    call = next(row for row in e.c if row["payload"].get("type") == "custom_tool_call")
    output = next(row for row in e.c if row["payload"].get("type") == "custom_tool_call_output")
    if fault == "missing-call": e.c.remove(call)
    elif fault == "missing-return": e.c.remove(output)
    elif fault == "wrong-call": output["payload"]["call_id"] = "unrelated"
    elif fault == "unsupported-tool": call["payload"]["name"] = "fabricated"
    elif fault == "truncated-wrapper": output["payload"]["output"][0]["text"] = "Script completed\nWarning: truncated output\n"
    elif fault == "truncated-stdout": output["payload"]["output"][-1]["text"] = json.dumps({"exit_code": 0, "output": event["payload"]["item"]["aggregated_output"][:80]})
    elif fault == "metadata-only": output["payload"]["output"] = [{"type": "input_text", "text": json.dumps({"diff_sha256": result["diff_sha256"], "diff_read": "verified"})}]
    else: output["payload"]["output"] = [{"type": "opaque_blob", "data": "not inspected"}]
    e.write(e.child, e.c)
    # The full exact CommandExecution stdout remains present in every case.
    assert json.loads(event["payload"]["item"]["aggregated_output"]) == result
    with pytest.raises(ce.EvidenceError): e.collect()


def test_700740_native_diff_with_only_tool_return_truncated_never_passes(tmp_path, monkeypatch, machine_models):
    e, path, event, manifest, chunks = chunked_diagnostic(tmp_path, monkeypatch)
    output = next(row for row in e.c if row["payload"].get("type") == "custom_tool_call_output"
                  and row["payload"].get("call_id") == "delivery-chunk-" + str(len(chunks) // 2))
    output["payload"]["output"][-1]["text"] = json.dumps({"exit_code": 0, "output": chunks[len(chunks) // 2]["payload"]["item"]["aggregated_output"][:700]})
    e.write(e.child, e.c)
    with pytest.raises(ce.EvidenceError, match="delivery_truncated"): e.collect()


@pytest.mark.parametrize("fault", ["missing", "declaration", "wrong-command", "wrong-cwd", "wrong-thread", "wrong-turn", "exit", "truncated", "output-array", "same-child", "wrong-diff", "wrong-path", "no-denial", "readback", "duplicate", "fixture", "helper", "capture", "plan", "plan-json", "parent-writable", "parent-settings", "child-profile-disabled"])
def test_probe_requires_native_origin_and_all_bindings(tmp_path, monkeypatch, machine_models, fault):
    e, path, event, result = diagnostic(tmp_path, monkeypatch)
    item = event["payload"]["item"]
    if fault == "missing": e.c.remove(event)
    elif fault == "declaration": item["type"] = "AgentMessage"
    elif fault == "wrong-command": item["command"][-1] = "printf 'invented proof'"
    elif fault == "wrong-cwd": item["cwd"] = "/source"
    elif fault == "wrong-thread": event["payload"]["thread_id"] = "other"
    elif fault == "wrong-turn": event["payload"]["turn_id"] = "other"
    elif fault == "exit": item["exit_code"] = 1
    elif fault == "truncated": item["aggregated_output"] = '{"schema":'
    elif fault == "output-array": item["aggregated_output"] = '[]'
    elif fault == "plan-json": path.write_text('[')
    elif fault == "duplicate": e.c.insert(-1, copy.deepcopy(event))
    elif fault == "fixture": Path(result["fixture"]).write_bytes(b"changed")
    elif fault == "helper": Path(rp.__file__).write_text("print('fake')")
    elif fault == "capture":
        capture = Path(rp.read_plan(path)["capture_path"]); capture.chmod(0o600); capture.write_text("{}")
    elif fault == "plan":
        plan = json.loads(path.read_text()); plan["wave_id"] = "other"; path.write_text(json.dumps(ce.sealed({k:v for k,v in plan.items() if k != "integrity_sha256"})))
    elif fault == "parent-writable":
        e.p[2]["payload"]["sandbox_policy"] = {"type": "workspace-write"}
    elif fault == "parent-settings":
        e.p.insert(-1, e.row("event_msg", {"type": "thread_settings_applied", "thread_settings": {"permission_profile": {"type": "disabled"}}}))
    elif fault == "child-profile-disabled":
        e.c.insert(-1, e.row("event_msg", {"type": "thread_settings_applied", "thread_settings": {"permission_profile": {"type": "disabled"}}}))
    else:
        changes = {"same-child": ("child_thread", "other"), "wrong-diff": ("diff_text", "different"),
                   "wrong-path": ("diff", "/other"), "no-denial": ("denied_errno", None), "readback": ("after_sha256", "0" * 64)}
        key, value = changes[fault]; result[key] = value; item["aggregated_output"] = json.dumps(result)
    e.write(e.child, e.c); e.write(e.parent, e.p)
    with pytest.raises((ce.EvidenceError, ValueError)):
        e.collect()


def test_probe_run_returns_real_permission_error_and_unchanged_fixture(tmp_path, monkeypatch, machine_models):
    e, path, event, result = diagnostic(tmp_path, monkeypatch)
    monkeypatch.setenv("CODEX_THREAD_ID", e.child_id)
    original = Path.open
    def denied(self, mode="r", *args, **kwargs):
        if str(self) == result["fixture"] and mode == "r+b":
            raise PermissionError(errno.EACCES, "controlled fixture denial")
        return original(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    assert rp.run(path) == result


def test_large_probe_run_itself_is_short_and_never_repeats_write_for_chunks(tmp_path, monkeypatch, machine_models):
    text = ("diff --git a/a b/a\n-old\n+new\n" * 30000)[:700740]
    e, path, prepared = prepare_diagnostic(tmp_path, monkeypatch, diff_text=text)
    plan = rp.read_plan(path)
    monkeypatch.setenv("CODEX_THREAD_ID", e.child_id)
    original = Path.open
    attempts = []
    def denied(self, mode="r", *args, **kwargs):
        if str(self) == plan["fixture"] and mode == "r+b":
            attempts.append(str(self))
            raise PermissionError(errno.EROFS, "controlled readonly fixture")
        return original(self, mode, *args, **kwargs)
    monkeypatch.setattr(Path, "open", denied)
    result = rp.run(path)
    assert result["denied_errno"] == errno.EROFS and result["delivery"] == rp.DELIVERY
    assert "diff_text" not in result and len(json.dumps(result)) < 2000
    assert result["diff_bytes"] == 700740
    assert result["before_sha256"] == result["after_sha256"] == plan["fixture_sha256"]
    assert "".join(rp.read_chunk(path, i)["diff_text"] for i in range(result["chunk_count"])) == text
    assert attempts == [plan["fixture"]]


def test_writable_probe_is_not_a_positive_and_does_not_restore_bytes(tmp_path, monkeypatch, machine_models):
    e, path, event, expected = diagnostic(tmp_path, monkeypatch)
    monkeypatch.setenv("CODEX_THREAD_ID", e.child_id)
    result = rp.run(path)
    assert result["denied_errno"] is None
    assert result["before_sha256"] != result["after_sha256"]
    with pytest.raises(ce.EvidenceError, match="fixture_changed"):
        rp.read_plan(path)


def test_review_stage_preflight_never_probes_write_destination(essay, monkeypatch):
    essay.p[1]["payload"]["sandbox_policy"] = {"type": "read-only"}
    essay.write(essay.parent, essay.p)
    def forbidden(*a, **kw): raise AssertionError("write probe in read-only preflight")
    monkeypatch.setattr(ce, "check_writable_destination", forbidden)
    for stage in ("pedir_review", "Code Review"):
        assert ce.preflight(root=essay.root, qualification=True, stage=stage)["parent_sandbox"] == "read-only"


def test_independent_diagnostic_wave_qualifies_normal_readonly_preflight(tmp_path, monkeypatch, machine_models):
    a_prepared = prepare_diagnostic(tmp_path, monkeypatch, "diff-reviewer")
    b_prepared = prepare_diagnostic(tmp_path, monkeypatch, "code-reviewer")
    first, _, _, _ = finish_diagnostic(*a_prepared)
    second, _, _, _ = finish_diagnostic(*b_prepared)
    second.p.append(second.row("turn_context", dict(second.p[1]["payload"], turn_id="qualify", sandbox_policy={"type": "workspace-write"})))
    second.write(second.parent, second.p)
    a = first.collect()
    b = second.collect()
    qualified = rp.qualify([a["evidence_path"], b["evidence_path"]], root=first.root)
    verification = rp.verify_qualification(root=first.root, session=first.parent_id)
    assert verification["qualification"] == qualified["qualification"]
    # Controlled lifecycle refusal belongs to the same diagnostic attempt.
    refusal = first.root / ce.DEFAULT_DEST / "controlled-refusal.json"
    ce.private_write(refusal, ce.sealed({"schema": ce.SCHEMA, "attempt_id": a["attempt_id"], "result": "blocked", "code": "controlled-fixture"}))
    ce.qualify(a["evidence_path"], [refusal])
    import codex_context
    # Context's independent three-source contract is exercised in its own suite.
    monkeypatch.setattr(codex_context, "verify_qualification", lambda **kw: {"qualification_path": str(first.root / "context.json"), "scope_sha256": "c" * 64})
    second.p.append(second.row("turn_context", dict(second.p[1]["payload"], turn_id="preflight", sandbox_policy={"type": "read-only"})))
    second.write(second.parent, second.p)
    writer_probe = ce.check_writable_destination
    def forbidden(*args, **kwargs): raise AssertionError("readonly preflight attempted mutation")
    monkeypatch.setattr(ce, "check_writable_destination", forbidden)
    pf = ce.preflight(root=first.root, stage="pedir_review")
    assert pf["parent_sandbox"] == "read-only"
    assert pf["capabilities"]["review_diff_read"] == pf["capabilities"]["review_write_denial_readback"] == "verified"
    assert pf["capabilities"]["context_isolation"] == "verified"
    assert pf["capabilities"]["internal_context_attestation"] == "unavailable"
    # Return to writable preparation only after both diagnostic returns.
    monkeypatch.setattr(ce, "check_writable_destination", writer_probe)
    second.p.append(second.row("turn_context", dict(second.p[1]["payload"], turn_id="product-prepare", sandbox_policy={"type": "workspace-write"})))
    second.write(second.parent, second.p)
    product_a = prepare_diagnostic(tmp_path, monkeypatch, "diff-reviewer", suffix="_product", qualification=False)
    product_b = prepare_diagnostic(tmp_path, monkeypatch, "code-reviewer", suffix="_product", qualification=False)
    x, _, _, _ = finish_diagnostic(*product_a)
    y, _, _, _ = finish_diagnostic(*product_b)
    for e in (x, y):
        args = dict(task_name=e.task, **e.cap["arguments"], fork_turns="none", message=f"runtime_evidence_birth: {e.birth}")
        assert ce.check_prepared_spawn(args, e.root)["parent_sandbox"] == "read-only"
    # Both source-verified product reviewers are still read-only; persist after
    # the operator's new writable context in this same parent chat.
    y.p.append(y.row("turn_context", dict(y.p[1]["payload"], turn_id="persist", sandbox_policy={"type": "workspace-write"})))
    y.write(y.parent, y.p)
    px, py = x.collect(), y.collect()
    from codex_proxy import record
    from codex_review import verify_wave, ReviewDiffError
    for e, proof in ((x, px), (y, py)):
        record(repo_root=e.root, activity=e.cap["role"], band="execucao",
            requested_model=e.cap["arguments"]["model"], requested_effort=e.cap["arguments"]["reasoning_effort"],
            observed_model=e.cap["arguments"]["model"], observed_effort=e.cap["arguments"]["reasoning_effort"],
            host=e.host, host_version="0.162.1", status="completed", payload_returned=True,
            child_id=e.child_id, bound_card="1095", sandbox_mode="read-only", capture=e.cap,
            wave_id="probe-wave", review_diff_sha256=proof["review_diff_sha256"], runtime_evidence=proof["evidence_path"])
    # Historical same-chat diagnostics remain readable, but the revised product
    # gate requires the dedicated chain, without a manual permission toggle.
    with pytest.raises(ReviewDiffError, match="dedicated principal/coordinator chain"):
        verify_wave(root=x.root, wave_id="probe-wave", expected_sha256=px["review_diff_sha256"], bound_card="1095")
    with pytest.raises(ce.EvidenceError, match="stage_capability_missing"):
        ce.preflight(root=x.root, stage="aceitar_sha")
    # No metadata declaration can replace the now-altered real command source.
    next(row for row in second.c if row["payload"].get("item", {}).get("type") == "CommandExecution")["payload"]["item"]["aggregated_output"] = "{}"
    second.write(second.child, second.c)
    with pytest.raises(ce.EvidenceError):
        ce.preflight(root=first.root, stage="pedir_review")


@pytest.mark.parametrize("fault", ["one", "duplicate", "different-turn", "different-diff", "product"])
def test_probe_qualification_rejects_incomplete_or_unbound_wave(tmp_path, monkeypatch, machine_models, fault):
    a_prepared = prepare_diagnostic(tmp_path, monkeypatch, "diff-reviewer")
    b_prepared = prepare_diagnostic(tmp_path, monkeypatch, "code-reviewer")
    first, _, _, _ = finish_diagnostic(*a_prepared)
    a = first.collect()
    second, _, _, _ = finish_diagnostic(*b_prepared)
    b = second.collect()
    paths = [a["evidence_path"], b["evidence_path"]]
    if fault == "one": paths.pop()
    elif fault == "duplicate": paths[1] = paths[0]
    elif fault == "different-turn":
        for row in second.p:
            if row["type"] == "response_item" and row["payload"].get("call_id") == "call-" + second.task:
                row["payload"]["internal_chat_message_metadata_passthrough"]["turn_id"] = "other"
        second.write(second.parent, second.p)
    elif fault == "different-diff": Path(json.loads(second.birth.read_text())["review_probe_plan"]).write_text("{}")
    else:
        envelope = json.loads(Path(b["evidence_path"]).read_text()); envelope["qualification"] = False
        Path(b["evidence_path"]).write_text(json.dumps(ce.sealed({k:v for k,v in envelope.items() if k != "integrity_sha256"})))
    with pytest.raises((ce.EvidenceError, ValueError)):
        rp.qualify(paths, root=first.root)
