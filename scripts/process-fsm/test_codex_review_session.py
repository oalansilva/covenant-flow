"""Controlled source fixtures for the dedicated route, never host qualification."""
import copy
import errno
import json
from pathlib import Path
import shutil
import sqlite3

import pytest

import codex_context as cc
import codex_evidence as ce
import codex_review_probe as rp
import codex_review_session as cs
import process_authority as pa
from model_selection_fixtures import machine_models

ORIGINAL_STAGE_BINDING = cs.stage_binding
ORIGINAL_LOCAL_BINDING = cs.local_binding
CONSUMER = next(ancestor for ancestor in Path(__file__).resolve().parents
                if (ancestor / ".cursor/process-fsm.yaml").is_file())


def managed_settings(root, pair):
    """Shape observed in exec 0.163.0, without prompt/sentinel contents."""
    return {"model": pair["model"], "model_provider_id": "openai", "service_tier": "default",
        "approval_policy": "never", "approvals_reviewer": "user", "permission_profile": cs._readonly_profile(),
        "cwd": str(root), "runtime_workspace_roots": [str(root)], "reasoning_effort": pair["reasoning_effort"],
        "collaboration_mode": {"mode": "default", "settings": {"model": pair["model"],
            "reasoning_effort": pair["reasoning_effort"], "developer_instructions": None}}, "disabled_plugin_ids": []}


class Dedicated:
    def __init__(self, tmp, monkeypatch):
        self.root = tmp / "card-1098-fixture"
        self.root.mkdir()
        self.rt = ce.Rollout()
        self.rt.home.joinpath("sessions").mkdir(parents=True, exist_ok=True)
        self.principal = "principal"
        self.coordinator = "coordinator"
        self.rows = {}
        self.paths = {}
        self.monkeypatch = monkeypatch
        monkeypatch.setattr(cs, "stage_binding", lambda package, *, allowed: "Code Review")
        monkeypatch.setattr(cs, "local_binding", lambda package: {"bound_card": "1098", "q_git": self.root.name})
        self.now = 1_800_000_000_000
        monkeypatch.setattr(cs, "_clock_ms", lambda: self.now)
        source = Path(cs.__file__).parent
        adapter = self.root / "scripts/process-fsm"
        adapter.mkdir(parents=True)
        for name in ("codex_review_session", "codex_review_probe", "codex_context", "codex_evidence", "codex_review",
                     "guard", "resolve", "graphql_quota", "overlay", "fsm", "process_authority"):
            original = source / (name + ".py")
            if not original.is_file():
                original = CONSUMER / "scripts/process-fsm" / (name + ".py")
            shutil.copyfile(original, adapter / (name + ".py"))
        monkeypatch.setattr(cs, "__file__", str(adapter / "codex_review_session.py"))
        monkeypatch.setattr(rp, "__file__", str(adapter / "codex_review_probe.py"))
        (self.root / ".cursor").mkdir(exist_ok=True)
        shutil.copyfile(CONSUMER / ".cursor/process-fsm.yaml", self.root / ".cursor/process-fsm.yaml")
        authority = self.root / ".covenant-flow/overlay.yaml"
        authority.parent.mkdir(parents=True)
        from test_overlay_fixtures import write_overlay
        write_overlay(self.root)
        import subprocess
        subprocess.run(["git", "init", "--initial-branch", self.root.name, str(self.root)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "--allow-empty", "-m", "fixture"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "remote", "add", "origin", "https://github.com/oalansilva/crypto.git"], check=True, capture_output=True)
        for role in cs.ROLES:
            profile = self.root / ".codex/agents" / (role + ".toml")
            profile.parent.mkdir(parents=True, exist_ok=True)
            profile.write_text('name = "' + role + '"\nsandbox_mode = "read-only"\n')
        self.native = tmp / "codex"
        self.native.write_bytes(b"preamble" + b"\n".join(cc.FRAGMENTS))
        monkeypatch.setattr(cs.shutil, "which", lambda name: str(self.native))
        self.add_session(self.principal, "codex-tui", "workspace-write", "principal-turn", {"model": "parent", "reasoning_effort": "high"})
        monkeypatch.setenv("CODEX_THREAD_ID", self.principal)

    def row(self, kind, payload):
        return {"type": kind, "payload": payload}

    def flush(self, session):
        self.paths[session].write_text("".join(json.dumps(row) + "\n" for row in self.rows[session]))

    def add_session(self, session, host, sandbox, turn, pair, parent=None, agent_path=None):
        path = self.rt.home / "sessions" / (session + ".jsonl")
        source = "exec" if not parent else {"subagent": {"thread_spawn": {"parent_thread_id": parent, "agent_path": agent_path}}}
        self.rows[session] = [self.row("session_meta", {"id": session, "originator": host, "cli_version": "0.163.0", "cwd": str(self.root), "timestamp": "2026-10-17T10:00:00Z", "source": source})]
        self.paths[session] = path
        with sqlite3.connect(self.rt.home / "state_5.sqlite") as db:
            db.execute("CREATE TABLE IF NOT EXISTS threads (id TEXT, rollout_path TEXT, agent_path TEXT)")
            db.execute("INSERT INTO threads VALUES (?,?,?)", (session, str(path), agent_path or "/root"))
        self.add_turn(session, turn, pair, sandbox)

    def add_turn(self, session, turn, pair, sandbox="read-only"):
        self.rows[session] += [self.row("event_msg", {"type": "task_started", "turn_id": turn}),
            self.row("turn_context", {"turn_id": turn, "model": pair["model"], "effort": pair["reasoning_effort"], "cwd": str(self.root), "sandbox_policy": {"type": sandbox}, "multi_agent_version": "v2"})]
        if session == self.coordinator and getattr(self, "native_settings", False):
            self.rows[session][-1]["payload"]["permission_profile"] = cs._readonly_profile()
            self.rows[session].append(self.row("event_msg", {"type": "thread_settings_applied", "thread_id": session,
                "thread_settings": managed_settings(self.root, pair)}))
        self.flush(session)

    def command_event(self, session, turn, cmd, output):
        event = self.row("event_msg", {"type": "item_completed", "thread_id": session, "turn_id": turn,
            "started_at_ms": self.now, "completed_at_ms": self.now,
            "item": {"type": "CommandExecution", "id": "cmd-" + str(len(self.rows[session])), "command": ["/bin/bash", "-lc", cmd], "cwd": self.root.as_uri(),
                     "status": "completed", "source": "unified_exec_startup", "exit_code": 0, "aggregated_output": json.dumps(output)}})
        if "codex_review_probe.py" in cmd:
            from test_codex_review_probe import native_delivery
            self.rows[session] += native_delivery(self, event)
        else:
            self.rows[session].append(event)
        self.flush(session)
        return event

    def finish_launch(self, package):
        p = cs.read_package(package)
        raw = (json.dumps({"type": "thread.started", "thread_id": self.coordinator}) + "\n" + json.dumps({"type": "turn.completed"}) + "\n").encode()
        Path(p["events"]).write_bytes(raw)
        output = {"schema": cs.SCHEMA, "package_sha256": p["integrity_sha256"], "coordinator_thread": self.coordinator, "events_sha256": ce.digest(raw), "exit_code": 0}
        if p["phase"] == "review":
            output["stage_receipt_sha256"] = cs._read_stage_receipt(p)["integrity_sha256"]
        return self.command_event(self.principal, "principal-turn", cs.command(package), output)

    def authorize(self, package):
        """Controlled source fixture, never runtime proof or a live GitHub call."""
        p = cs.read_package(package)
        observed = cs.stage_check(package, runtime=self.rt)
        event = self.command_event(self.principal, "principal-turn", cs.command(package, "stage-check"), observed)
        observed, ref = cs._stage_observation(package, runtime=self.rt, at_ms=self.now)
        receipt = ce.sealed({"schema": cs.STAGE_SCHEMA, "kind": "launch_revalidation", **cs._stage_scope(p),
            "coordinator_thread": self.coordinator, "status": "Code Review", "status_source": ref,
            "observation_sha256": observed["integrity_sha256"], "recheck_started_ms": self.now,
            "recheck_completed_ms": self.now})
        Path(p["stage_receipt"]).write_text(json.dumps(receipt))
        return receipt, event

    def bootstrap(self):
        result = cs.prepare(root=self.root, phase="bootstrap", runtime=self.rt)
        self.bootstrap_path = Path(result["package"])
        p = cs.read_package(self.bootstrap_path)
        self.add_session(self.coordinator, "codex_exec", "read-only", "bootstrap-turn", p["coordinator_selection"]["arguments"])
        instruction = 'Full-history forks: use fork_turns="none" to isolate.'
        ordinal = len(self.rows[self.coordinator])
        self.rows[self.coordinator].append(self.row("response_item", {"type": "message", "role": "developer", "content": [{"type": "input_text", "text": instruction}]}))
        self.flush(self.coordinator)
        refs = self.rt.session(self.coordinator)[1]
        scope = {"host": "codex_exec", "tool": cc.TOOL, "multi_agent_version": "v2", "binary_sha256": ce.digest(self.native.read_bytes()), "instruction_sha256": ce.digest(instruction.encode()), "contract_schema": cc.SCHEMA}
        doc = {"scope": scope, "scope_sha256": ce.digest(scope), "runtime_instructions": [{"source": str(self.paths[self.coordinator]), "ordinal": ordinal, "raw_sha256": refs[ordinal][2]}],
            "runtime_binary": {"executable": str(self.native), "binary_sha256": scope["binary_sha256"], "fragments": [{"offset": self.native.read_bytes().find(f), "length": len(f), "sha256": ce.digest(f)} for f in cc.FRAGMENTS]},
            "host_version": "0.163.0", "internal_context_attestation": "unavailable"}
        self.command_event(self.coordinator, "bootstrap-turn", cs.command(self.bootstrap_path, "inspect"), {"schema": cs.SCHEMA, "session": self.coordinator, "contract": doc})
        self.sentinel = "nonsecretRandomBootstrapSentinel0001"
        self.rows[self.coordinator].append(self.row("response_item", {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "context_sentinel: " + self.sentinel}]}))
        self.rows[self.coordinator].append(self.row("event_msg", {"type": "task_complete", "turn_id": "bootstrap-turn", "last_agent_message": "context_sentinel: " + self.sentinel}))
        self.flush(self.coordinator)
        self.finish_launch(self.bootstrap_path)
        return self.bootstrap_path

    def finish_children(self, package, *, fault=None):
        p = cs.read_package(package)
        turn = p["phase"] + "-turn" + ("-" + p["wave_id"] if p["phase"] == "context" else "")
        if p["phase"] == "review":
            self.authorize(package)
        self.add_turn(self.coordinator, turn, p["coordinator_selection"]["arguments"])
        if p["phase"] == "review":
            self.monkeypatch.setenv("CODEX_THREAD_ID", self.coordinator)
            ready = cs.preflight(package, runtime=self.rt)
            self.command_event(self.coordinator, turn, cs.command(package, "preflight"), ready)
            self.monkeypatch.setenv("CODEX_THREAD_ID", self.principal)
        proofs = []
        for n, birth_path in enumerate(p["births"]):
            birth = ce.check_seal(json.loads(Path(birth_path).read_text()))
            cap = birth["capture"]
            if p["phase"] == "context":
                plan_path = cc.plan_path(birth_path)
                context_plan = json.loads(plan_path.read_text())
                message = context_plan["requested_message"]
                control = __import__("re").search(r"^control: (.+)$", message, __import__("re").M)[1]
                args = {"task_name": birth["task_name"], **cap["arguments"], "fork_turns": "none", "message": message}
                payload = json.dumps({"control": control, "sentinel": None})
            else:
                args = copy.deepcopy(p["spawns"][n])
                payload = "diagnostic completed" if p["phase"] == "probe" else "No findings."
            child = p["phase"] + "-child-" + (birth["attempt_id"] if p["phase"] == "context" else str(n))
            child_path = "/root/" + birth["task_name"]
            native = {"internal_chat_message_metadata_passthrough": {"turn_id": turn}}
            self.rows[self.coordinator] += [self.row("response_item", {"type": "function_call", "namespace": "collaboration", "name": "spawn_agent", "call_id": child, "arguments": json.dumps(args), **native}),
                self.row("response_item", {"type": "function_call_output", "call_id": child, "output": json.dumps({"task_name": child_path}), **native})]
            self.add_session(child, "codex_exec", "read-only", "child-turn", cap["arguments"], parent=self.coordinator, agent_path=child_path)
            if p["phase"] == "context":
                self.rows[child].append(self.row("response_item", {"type": "agent_message", "author": "/root", "content": [{"type": "input_text", "text": message}]}))
            else:
                plan = rp.read_plan(birth["review_probe_plan"], runtime=self.rt)
                output = {"schema": rp.SCHEMA, "plan_sha256": plan["integrity_sha256"], "child_thread": child, "role": birth["role"], "attempt_id": birth["attempt_id"], "wave_id": p["wave_id"],
                    "diff": plan["diff"], "diff_sha256": plan["diff_sha256"], "diff_text": Path(plan["diff"]).read_text(), "fixture": plan["fixture"], "before_sha256": plan["fixture_sha256"], "after_sha256": plan["fixture_sha256"], "denied_errno": errno.EROFS}
                text = output["diff_text"]
                chunked = len(text) > rp.CHUNK_CHARS
                if chunked:
                    output.pop("diff_text")
                    output.update(rp.delivery(text.encode()))
                    output["read_command_template"] = rp.read_command(birth["review_probe_plan"], 0, runtime=self.rt).rsplit(" ", 1)[0] + " <chunk_index>"
                if fault == "write-allowed" and n == 0: output["denied_errno"] = None
                if fault == "wrong-target" and n == 0: output["fixture"] += "-different"
                if fault != "probe-absent" or n != 0:
                    self.command_event(child, "child-turn", rp.command(birth["review_probe_plan"], runtime=self.rt), output)
                    if chunked:
                        for index in range(output["chunk_count"]):
                            self.command_event(child, "child-turn", rp._read_command(plan, birth["review_probe_plan"], index), rp.read_chunk_result(plan, child, index))
            self.rows[child].append(self.row("event_msg", {"type": "task_complete", "turn_id": "child-turn", "last_agent_message": payload}))
            self.flush(child)
            self.rows[self.coordinator].append(self.row("response_item", {"type": "agent_message", "author": child_path, "content": [{"type": "input_text", "text": "Message Type: FINAL_ANSWER\nPayload:\n" + payload}]}))
            self.flush(self.coordinator)
        self.rows[self.coordinator].append(self.row("event_msg", {"type": "task_complete", "turn_id": turn, "last_agent_message": "children returned"}))
        self.flush(self.coordinator)
        self.finish_launch(package)
        return p

    def context(self):
        package = Path(cs.prepare(root=self.root, phase="context", bootstrap=self.bootstrap_path, runtime=self.rt)["package"])
        p = self.finish_children(package)
        result = cc.qualify(cc.plan_path(p["births"][0]), runtime=self.rt)
        return package, result

    def probe(self, fault=None):
        diff = self.root / "diagnostic.patch"
        diff.write_text("diff --git a/x b/x\n-old\n+new\n")
        refusal = self.command_event(self.principal, "principal-turn", cs.command(self.bootstrap_path, "route-check"), {"result": "blocked", "code": "review_route_unqualified"})
        refusal["payload"]["item"].update(status="failed", exit_code=1)
        self.flush(self.principal)
        package = Path(cs.prepare(root=self.root, phase="probe", bootstrap=self.bootstrap_path, diff=diff, runtime=self.rt)["package"])
        self.finish_children(package, fault=fault)
        return package


@pytest.fixture
def dedicated(tmp_path, monkeypatch, machine_models):
    return Dedicated(tmp_path, monkeypatch)


def test_bootstrap_has_no_fake_parent_and_binds_native_chain(dedicated):
    path = dedicated.bootstrap()
    p = cs.read_package(path)
    chain = cs.binding(path, runtime=dedicated.rt)
    assert chain["principal_thread"] == dedicated.principal
    assert chain["coordinator_thread"] == dedicated.coordinator
    assert chain["principal_host"] != chain["coordinator_host"]
    assert p["state"] == "pending_native_launch"
    assert "births" not in p
    assert cs.contract_observation(path, runtime=dedicated.rt)["internal_context_attestation"] == "unavailable"


@pytest.mark.parametrize("fault", ["output", "events", "principal-id", "sandbox", "cwd", "model", "settings", "abort", "source", "duplicate", "binary", "package"])
def test_binding_rejects_false_or_ambiguous_authority(dedicated, fault):
    path = dedicated.bootstrap()
    p = cs.read_package(path)
    command_event = dedicated.rows[dedicated.principal][-1]
    if fault == "output": command_event["payload"]["item"]["aggregated_output"] = json.dumps({"coordinator_thread": "invented"})
    elif fault == "events": Path(p["events"]).write_text('{"type":"thread.started","thread_id":"invented"}\n')
    elif fault == "principal-id": command_event["payload"]["thread_id"] = "other"
    elif fault in {"sandbox", "cwd", "model"}:
        turn = next(row["payload"] for row in dedicated.rows[dedicated.coordinator] if row["type"] == "turn_context")
        if fault == "sandbox": turn["sandbox_policy"] = {"type": "workspace-write"}
        elif fault == "cwd": turn["cwd"] = "/source"
        else: turn["model"] = "unavailable"
    elif fault == "settings": dedicated.rows[dedicated.coordinator].append(dedicated.row("event_msg", {"type": "thread_settings_applied"}))
    elif fault == "abort": dedicated.rows[dedicated.coordinator].append(dedicated.row("event_msg", {"type": "turn_aborted"}))
    elif fault == "source": command_event["payload"]["item"]["source"] = "child-assertion"
    elif fault == "duplicate": dedicated.rows[dedicated.principal].append(copy.deepcopy(command_event))
    elif fault == "binary": dedicated.native.write_bytes(b"changed")
    elif fault == "package": Path(p["prompt"]).write_text("changed")
    dedicated.flush(dedicated.principal); dedicated.flush(dedicated.coordinator)
    with pytest.raises(ce.EvidenceError): cs.binding(path, runtime=dedicated.rt)


def test_same_readonly_coordinator_context_persisted_only_by_principal(dedicated):
    dedicated.bootstrap()
    package, result = dedicated.context()
    p = cs.read_package(package)
    birth = ce.check_seal(json.loads(Path(p["births"][0]).read_text()))
    assert birth["parent_thread"] == birth["parent_turn"] == ce.UNAVAILABLE
    assert birth["envelope_state"] == "pending_coordinator"
    assert dedicated.sentinel not in Path(p["prompt"]).read_text()
    assert dedicated.sentinel not in cc.plan_path(p["births"][0]).read_text()
    assert result["result"] == "passed"
    assert result["parent_thread"] == dedicated.coordinator
    assert result["internal_context_attestation"] == "unavailable"
    assert cc.verify_qualification(root=dedicated.root, out=ce.destination(dedicated.root), session=dedicated.coordinator, runtime=dedicated.rt)["result"] == "passed"
    with pytest.raises(ce.EvidenceError, match="context_qualification_missing"):
        cc.verify_qualification(root=dedicated.root, out=ce.destination(dedicated.root), session=dedicated.principal, runtime=dedicated.rt)


def test_named_probe_route_roundtrip_and_original_pending_envelopes(dedicated):
    dedicated.bootstrap(); dedicated.context()
    package = dedicated.probe()
    p = cs.read_package(package)
    originals = [Path(b).read_bytes() for b in p["births"]]
    proofs = [ce.collect(b, wait_seconds=0, runtime=dedicated.rt) for b in p["births"]]
    for proof in proofs:
        assert proof["dedicated_chain"]["coordinator_thread"] == dedicated.coordinator
        assert proof["parent_thread"] == dedicated.coordinator
        assert proof["native_arguments"]["agent_type"] == proof["role"]
        assert proof["birth"]["parent_thread"] == ce.UNAVAILABLE
        ce.verify_evidence(proof["evidence_path"], runtime=dedicated.rt)
    qualified = cs.qualify_route(package, runtime=dedicated.rt)
    assert qualified["coordinator_thread"] == dedicated.coordinator
    assert cs.verify_route(dedicated.bootstrap_path, runtime=dedicated.rt) == qualified
    dedicated.command_event(dedicated.principal, "principal-turn", cs.command(dedicated.bootstrap_path, "route-check"), qualified)
    assert cs.verify_route(dedicated.bootstrap_path, runtime=dedicated.rt) == qualified
    assert [Path(b).read_bytes() for b in p["births"]] == originals
    assert len({proof["native_parent_turn"] for proof in proofs}) == 1


@pytest.mark.parametrize("fault", ["write-allowed", "wrong-target", "probe-absent"])
def test_named_profiles_require_actual_denial_same_target_and_native_probe(dedicated, fault):
    dedicated.bootstrap(); dedicated.context()
    package = dedicated.probe(fault)
    with pytest.raises(ce.EvidenceError): cs.qualify_route(package, runtime=dedicated.rt)


@pytest.mark.parametrize("fault", ["principal-receipt", "completion-payload", "interrupted", "different-turn", "default-role", "fork-all"])
def test_pending_or_partial_attempt_never_proves_final_wave(dedicated, fault):
    dedicated.bootstrap(); dedicated.context()
    package = dedicated.probe()
    p = cs.read_package(package)
    if fault == "principal-receipt":
        birth = json.loads(Path(p["births"][0]).read_text()); birth["parent_thread"] = dedicated.principal
        with pytest.raises(ce.EvidenceError): cs.resolve_envelope(ce.sealed({k:v for k,v in birth.items() if k != "integrity_sha256"}), runtime=dedicated.rt)
        return
    child = "probe-child-0"
    if fault == "completion-payload": dedicated.rows[child][-1]["payload"].pop("last_agent_message")
    elif fault == "interrupted": dedicated.rows[child].append(dedicated.row("event_msg", {"type": "turn_aborted"}))
    else:
        call = next(row["payload"] for row in dedicated.rows[dedicated.coordinator] if row["type"] == "response_item" and row["payload"].get("type") == "function_call" and row["payload"].get("call_id") == child)
        args = json.loads(call["arguments"])
        if fault == "different-turn": call["internal_chat_message_metadata_passthrough"]["turn_id"] = "other-turn"
        elif fault == "default-role": args.pop("agent_type")
        else: args["fork_turns"] = "all"
        call["arguments"] = json.dumps(args)
    dedicated.flush(child); dedicated.flush(dedicated.coordinator)
    with pytest.raises(ce.EvidenceError): cs.qualify_route(package, runtime=dedicated.rt)


def test_review_refused_before_any_launch_without_own_context_and_named_route(dedicated):
    dedicated.bootstrap()
    diff = dedicated.root / "product.patch"; diff.write_text("diff --git a/a b/a\n-old\n+new\n")
    with pytest.raises(ce.EvidenceError, match="context_qualification_missing"):
        cs.prepare(root=dedicated.root, phase="review", bootstrap=dedicated.bootstrap_path, diff=diff, runtime=dedicated.rt)
    dedicated.context()
    with pytest.raises(ce.EvidenceError, match="review_probe_qualification_missing"):
        cs.prepare(root=dedicated.root, phase="review", bootstrap=dedicated.bootstrap_path, diff=diff, runtime=dedicated.rt)


def qualified_route(dedicated):
    dedicated.bootstrap(); dedicated.context()
    probe = dedicated.probe()
    p = cs.read_package(probe)
    proofs = [ce.collect(b, wait_seconds=0, runtime=dedicated.rt) for b in p["births"]]
    rp.qualify([proof["evidence_path"] for proof in proofs], root=dedicated.root, runtime=dedicated.rt)
    cs.qualify_route(probe, runtime=dedicated.rt)
    return probe


@pytest.mark.parametrize("diff_size", [None, 24000])
def test_product_wave_persists_in_source_bound_principal_without_toggles(dedicated, diff_size):
    from codex_proxy import record
    from codex_review import verify_wave
    qualified_route(dedicated)
    diff = dedicated.root / "product.patch"
    text = "diff --git a/a b/a\n-old\n+new\n"
    diff.write_text(text if diff_size is None else (text * diff_size)[:diff_size])
    package = Path(cs.prepare(root=dedicated.root, phase="review", bootstrap=dedicated.bootstrap_path, diff=diff, runtime=dedicated.rt)["package"])
    # T9 preflight can inspect the already qualified coordinator from writable
    # principal; there is no permission change or product reviewer yet.
    ready = ce.preflight(root=dedicated.root, stage="pedir_review", runtime=dedicated.rt)
    assert ready["parent_sandbox"] == "workspace-write"
    assert ready["coordinator_thread"] == dedicated.coordinator
    assert ready["capabilities"]["internal_context_attestation"] == "unavailable"
    p = dedicated.finish_children(package)
    observed_paths = set()
    for birth in p["births"]:
        proof = ce.collect(birth, wait_seconds=0, runtime=dedicated.rt)
        observed_paths.add(proof["review_observation"]["diff"])
        if diff_size:
            assert proof["review_observation"]["delivery"] == rp.DELIVERY
            assert proof["review_observation"]["delivered_bytes"] == diff_size
        cap = proof["birth"]["capture"]
        record(repo_root=dedicated.root, activity=proof["role"], band=proof["band"], requested_model=cap["arguments"]["model"],
            requested_effort=cap["arguments"]["reasoning_effort"], observed_model=proof["turns"][-1]["observed"]["model"],
            observed_effort=proof["turns"][-1]["observed"]["reasoning_effort"], host=proof["host"], host_version=proof["host_version"],
            status=proof["status"], payload_returned=True, child_id=proof["child_thread"], wave_id=p["wave_id"], sandbox_mode="read-only", bound_card="1098",
            review_diff_sha256=p["diff_sha256"], capture=cap, runtime_evidence=proof["evidence_path"])
    digest, children = verify_wave(root=dedicated.root, wave_id=p["wave_id"], expected_sha256=p["diff_sha256"], bound_card="1098")
    assert digest == ce.digest(diff.read_bytes())
    assert len(set(children)) == 2
    assert observed_paths == {str(diff)}
    dedicated.monkeypatch.setenv("CODEX_THREAD_ID", dedicated.coordinator)
    with pytest.raises(ValueError, match="writable principal"):
        verify_wave(root=dedicated.root, wave_id=p["wave_id"], expected_sha256=p["diff_sha256"], bound_card="1098")


def test_launch_uses_native_readonly_resume_and_no_identity_fallback(dedicated):
    dedicated.bootstrap()
    package = Path(cs.prepare(root=dedicated.root, phase="context", bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)["package"])
    calls = []
    def native(argv, **kwargs):
        calls.append((argv, kwargs))
        kwargs["stdout"].write((json.dumps({"type": "thread.started", "thread_id": dedicated.coordinator}) + "\n").encode())
        return __import__("subprocess").CompletedProcess(argv, 0, stderr=b"")
    dedicated.monkeypatch.setattr(cs.subprocess, "run", native)
    result = cs.launch(package)
    argv, kwargs = calls[0]
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert argv[-3:] == ["resume", dedicated.coordinator, "-"]
    assert "CODEX_THREAD_ID" not in kwargs["env"]
    assert not any("bypass" in value or "ignore" in value for value in argv)
    assert result["coordinator_thread"] == dedicated.coordinator


def test_pending_envelope_is_not_final_evidence(dedicated):
    dedicated.bootstrap()
    package = Path(cs.prepare(root=dedicated.root, phase="context", bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)["package"])
    birth = cs.read_package(package)["births"][0]
    with pytest.raises(ce.EvidenceError): ce.verify_evidence(birth, runtime=dedicated.rt)


def test_profile_contract_explicitly_allows_only_disposable_probe():
    import tomllib
    root = Path(__file__).resolve().parents[2]
    for role in cs.ROLES:
        profile = tomllib.loads((root / ".codex/agents" / (role + ".toml")).read_text())
        text = profile["developer_instructions"]
        assert profile["sandbox_mode"] == "read-only"
        assert "controlled" in text and "disposable fixture" in text
        assert "Do not modify product" in text and "successful writing" in text
        assert "Do not require final verify-wave" in text
        assert "ONCE ONLY" in text and "read_command_template" in text
        assert "No separate codex_review.py verify command is required" in text
        assert "review_diff_delivery_incomplete" in text


def test_prepared_wave_requires_single_preflight_and_probe_with_bounded_outputs(dedicated):
    dedicated.bootstrap(); dedicated.context()
    package = dedicated.probe()
    p = cs.read_package(package)
    coordinator = Path(p["prompt"]).read_text()
    assert "ONCE ONLY" in coordinator and "review_preflight_output_unavailable" in coordinator
    assert "max_output_tokens=12000" in coordinator
    for spawn in p["spawns"]:
        prompt = spawn["message"]
        assert "ONCE ONLY" in prompt and "FIRST command" in prompt
        assert "NEVER rerun the probe" in prompt and "read_command_template" in prompt
        assert "max_output_tokens=20000" in prompt and "max_output_tokens=32000" in prompt
        assert "no separate codex_review.py verify is required" in prompt


def test_immutable_birth_prompts_distinguish_input_window_generation_and_delivery(dedicated):
    dedicated.bootstrap(); dedicated.context()
    package = dedicated.probe()
    p = cs.read_package(package)
    for spawn in p["spawns"]:
        message = spawn["message"]
        assert "bytes, Unicode characters and page count are NOT token counts" in message
        assert "generation/reasoning/work budget" in message
        assert "actual native context-window/input-usage metadata if exposed" in message
        assert "absence of metadata does not establish shortage" in message
        assert "Read all bounded pages sequentially" in message
        assert "actual input limit, truncation or missing delivery" in message
        assert "475000" not in message and "send_message" not in message
        assert "review_diff_delivery_incomplete" in message
        # Both immutable spawn messages are in the sealed coordinator input.
        assert spawn["message"] in json.loads(Path(p["prompt"]).read_text().split("\n")[-2])[p["spawns"].index(spawn)]["message"]


def test_context_and_pair_prompts_keep_async_identity_until_termination(dedicated):
    dedicated.bootstrap()
    context = Path(cs.prepare(root=dedicated.root, phase="context", bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)["package"])
    messages = [Path(cs.read_package(context)["prompt"]).read_text()]
    # No real launch: inspect a probe preparation, not a qualified product wave.
    diff = dedicated.root / "async.patch"; diff.write_text("-a\n+b\n")
    probe = Path(cs.prepare(root=dedicated.root, phase="probe", bootstrap=dedicated.bootstrap_path, diff=diff, runtime=dedicated.rt)["package"])
    messages.append(Path(cs.read_package(probe)["prompt"]).read_text())
    for prompt in messages:
        assert "ONCE ONLY" in prompt and "COMPLETE result object" in prompt
        assert "including session_id and exit_code, not only result.output" in prompt
        assert "write_stdin with empty chars" in prompt and "SAME process" in prompt
        assert "functions.wait on the SAME cell" in prompt
        assert "Accumulate every output fragment in order" in prompt
        assert "never finish this turn or spawn while the preflight is running" in prompt
        assert "Only after termination" in prompt and "do not rerun preflight" in prompt


@pytest.mark.parametrize("fault", ["pending", "lost-plan", "failed-control"])
def test_dedicated_new_context_attempt_blocks_old_success(dedicated, fault):
    dedicated.bootstrap(); _, old = dedicated.context()
    package = Path(cs.prepare(root=dedicated.root, phase="context", bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)["package"])
    p = cs.read_package(package)
    if fault == "lost-plan":cc.plan_path(p["births"][0]).unlink()
    elif fault == "failed-control":
        # A second native child uses its own ID; preserve the first source.
        dedicated.finish_children(package)
        child_id = "context-child-" + json.loads(Path(p["births"][0]).read_text())["attempt_id"]
        child = dedicated.rows[child_id]
        child[-1]["payload"]["last_agent_message"] = '{"control":"wrong","sentinel":null}'
        dedicated.flush(child_id)
    with pytest.raises(ce.EvidenceError):
        cc.verify_qualification(root=dedicated.root, out=ce.destination(dedicated.root),
            session=dedicated.coordinator, runtime=dedicated.rt, expected_path=old["qualification_path"])


@pytest.mark.parametrize("finish_before_command", [False, True])
def test_native_polled_preflight_requires_completed_command_before_turn(dedicated, finish_before_command):
    dedicated.native_settings = True
    path = dedicated.bootstrap();p = cs.read_package(path)
    turn = "async-preflight-turn"
    dedicated.add_turn(dedicated.coordinator, turn, p["coordinator_selection"]["arguments"])
    done = dedicated.row("event_msg", {"type":"task_complete","turn_id":turn,"last_agent_message":"ready"})
    if finish_before_command:dedicated.rows[dedicated.coordinator].append(done)
    command = "python3 fixed-preflight.py --package fixture"
    event = dedicated.command_event(dedicated.coordinator, turn, command, {"result":"ready"})
    event["payload"]["item"]["source"] = "unified_exec_poll"
    if not finish_before_command:dedicated.rows[dedicated.coordinator].append(done)
    dedicated.flush(dedicated.coordinator)
    if finish_before_command:
        with pytest.raises(ce.EvidenceError):cs.readonly(dedicated.rt, dedicated.coordinator, p)
    else:
        cs.readonly(dedicated.rt, dedicated.coordinator, p)
        output, _ = cs.native_command(dedicated.rt, dedicated.coordinator, command, dedicated.root)
        assert output == {"result":"ready"}


def test_historical_attempt_order_survives_helper_upgrade_without_accepting_old_qualification(dedicated):
    dedicated.bootstrap(); package, _ = dedicated.context()
    p = cs.read_package(package)
    helper = Path(p["helper"])
    helper.write_bytes(helper.read_bytes() + b"\n# new candidate installed\n")
    assert cc.diagnostic_parent(p, runtime=dedicated.rt) == dedicated.coordinator
    birth, _, _ = cc.latest_diagnostic(root=dedicated.root, out=ce.destination(dedicated.root),
        session=dedicated.coordinator, runtime=dedicated.rt)
    assert birth["attempt_id"] == json.loads(Path(p["births"][0]).read_text())["attempt_id"]
    with pytest.raises(ce.EvidenceError, match="review_package_changed"):
        cc.verify_qualification(root=dedicated.root, out=ce.destination(dedicated.root),
            session=dedicated.coordinator, runtime=dedicated.rt)


def test_duplicate_product_preflight_is_still_invalid_not_relaxed(dedicated):
    qualified_route(dedicated)
    diff = dedicated.root / "product.patch"; diff.write_text("diff --git a/a b/a\n-old\n+new\n")
    package = Path(cs.prepare(root=dedicated.root, phase="review", bootstrap=dedicated.bootstrap_path, diff=diff, runtime=dedicated.rt)["package"])
    p = dedicated.finish_children(package)
    rows = dedicated.rows[dedicated.coordinator]
    command = cs.command(package, "preflight")
    preflight = next(row for row in rows if row["payload"].get("item", {}).get("command") == ["/bin/bash", "-lc", command])
    rows.insert(rows.index(preflight) + 1, copy.deepcopy(preflight))
    dedicated.flush(dedicated.coordinator)
    with pytest.raises(ce.EvidenceError, match="review_launch_source_unavailable"):
        ce.collect(p["births"][0], wait_seconds=0, runtime=dedicated.rt)


def test_selection_changed_blocks_new_dedicated_phase(dedicated, machine_models):
    import yaml
    dedicated.bootstrap()
    doc = yaml.safe_load(machine_models.read_text())
    doc["clients"]["codex"]["execucao"].update(model="gpt-6.1-sol", effort="high")
    machine_models.write_text(yaml.safe_dump(doc))
    diff = dedicated.root / "diagnostic.patch"; diff.write_text("diagnostic")
    with pytest.raises(ValueError, match="selection_changed"):
        cs.prepare(root=dedicated.root, phase="probe", bootstrap=dedicated.bootstrap_path, diff=diff, runtime=dedicated.rt)


def test_native_launch_source_missing_is_explicitly_unavailable(dedicated):
    dedicated.bootstrap()
    dedicated.rows[dedicated.principal].pop()
    dedicated.flush(dedicated.principal)
    with pytest.raises(ce.EvidenceError, match="review_launch_source_unavailable"):
        cs.binding(dedicated.bootstrap_path, runtime=dedicated.rt)


def test_product_status_comes_from_live_board_not_package(dedicated, monkeypatch):
    import resolve
    import guard
    monkeypatch.setattr(resolve, "resolve", lambda *args: {"bound_card": "1098", "q_git": dedicated.root.name})
    monkeypatch.setattr(guard, "github_status_provider", lambda card, **kwargs: "Design")
    package = {"root": str(dedicated.root), "bound_card": "1098", "stage_status": "Code Review",
               "authority": pa.capture(dedicated.root, "1098")}
    with pytest.raises(ce.EvidenceError, match="q=Design"):
        ORIGINAL_STAGE_BINDING(package, allowed={"Code Review"})


@pytest.fixture
def stage_package(dedicated):
    """Status-verifier fixture only, deliberately not a qualified product wave."""
    dedicated.bootstrap()
    path = Path(cs.prepare(root=dedicated.root, phase="context", bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)["package"])
    p = cs.read_package(path)
    p.update(phase="review", stage_receipt=str(path.with_suffix(".stage.json")),
             authority=pa.capture(dedicated.root, "1098"))
    p.pop("integrity_sha256")
    path.write_text(json.dumps(ce.sealed(p)))
    return path


@pytest.mark.parametrize("fault", ["missing-source", "duplicate-source", "other-turn", "status", "scope", "expired", "future", "timing", "forged-file"])
def test_stage_status_requires_new_intact_native_principal_source(dedicated, stage_package, fault):
    receipt, event = dedicated.authorize(stage_package)
    item = event["payload"]["item"]
    output = json.loads(item["aggregated_output"])
    if fault == "missing-source": dedicated.rows[dedicated.principal].remove(event)
    elif fault == "duplicate-source": dedicated.rows[dedicated.principal].append(copy.deepcopy(event))
    elif fault == "other-turn": event["payload"]["turn_id"] = "other"
    elif fault == "status": output["status"] = "Design"
    elif fault == "scope": output["wave_id"] = "different"
    elif fault == "expired": dedicated.now += cs.STAGE_MAX_AGE_MS + 1
    elif fault == "future": dedicated.now -= 1
    elif fault == "timing": event["payload"].pop("started_at_ms")
    elif fault == "forged-file":
        # A copied status JSON does not replace the missing native command.
        Path(cs.read_package(stage_package)["stage_receipt"]).write_text(json.dumps(output))
        dedicated.rows[dedicated.principal].remove(event)
    if fault in {"status", "scope"}:
        output.pop("integrity_sha256")
        item["aggregated_output"] = json.dumps(ce.sealed(output))
    dedicated.flush(dedicated.principal)
    with pytest.raises(ce.EvidenceError):
        cs.verify_stage_receipt(stage_package, runtime=dedicated.rt)


@pytest.mark.parametrize("field", ["package_sha256", "coordinator_thread", "status_source", "status", "recheck_started_ms"])
def test_stage_receipt_cannot_refresh_or_change_native_status(dedicated, stage_package, field):
    receipt, _ = dedicated.authorize(stage_package)
    receipt.pop("integrity_sha256")
    receipt[field] = dedicated.now + 1 if field == "recheck_started_ms" else "changed"
    Path(cs.read_package(stage_package)["stage_receipt"]).write_text(json.dumps(ce.sealed(receipt)))
    with pytest.raises(ce.EvidenceError): cs.verify_stage_receipt(stage_package, runtime=dedicated.rt)


def test_live_preflight_expires_but_historical_verification_uses_source_time(dedicated, stage_package):
    receipt, _ = dedicated.authorize(stage_package)
    checked = dedicated.now
    assert cs.verify_stage_receipt(stage_package, runtime=dedicated.rt) == receipt
    dedicated.now += cs.STAGE_MAX_AGE_MS + 1
    with pytest.raises(ce.EvidenceError, match="review_stage_status_expired"):
        cs.verify_stage_receipt(stage_package, runtime=dedicated.rt)
    assert cs.verify_stage_receipt(stage_package, runtime=dedicated.rt, at_ms=checked) == receipt


def test_freshness_is_checked_after_other_preflight_prerequisites(dedicated, stage_package, monkeypatch):
    dedicated.authorize(stage_package)
    p = cs.read_package(stage_package)
    dedicated.add_turn(dedicated.coordinator, "review-turn", p["coordinator_selection"]["arguments"])
    def slow_qualification(**kwargs):
        dedicated.now += cs.STAGE_MAX_AGE_MS + 1
    monkeypatch.setattr(cc, "verify_qualification", slow_qualification)
    monkeypatch.setattr(rp, "verify_qualification", lambda **kwargs: {})
    monkeypatch.setattr(cs, "verify_route", lambda *args, **kwargs: {})
    monkeypatch.setenv("CODEX_THREAD_ID", dedicated.coordinator)
    with pytest.raises(ce.EvidenceError, match="review_stage_status_expired"):
        cs.preflight(stage_package, runtime=dedicated.rt)


@pytest.mark.parametrize("status", [None, "Todo", "Design", "Em desenvolvimento"])
def test_authoritative_query_does_not_promote_missing_or_wrong_status(dedicated, stage_package, monkeypatch, status):
    import guard
    monkeypatch.setattr(cs, "stage_binding", ORIGINAL_STAGE_BINDING)
    monkeypatch.setattr(guard, "github_status_provider", lambda card, **kwargs: status)
    with pytest.raises(ce.EvidenceError, match="review_stage_"):
        cs.stage_check(stage_package, runtime=dedicated.rt)


def test_query_write_or_network_error_has_specific_diagnosis(dedicated, stage_package, monkeypatch):
    import guard
    def unavailable(card, **kwargs):
        raise FileNotFoundError("No usable temporary directory found")
    monkeypatch.setattr(cs, "stage_binding", ORIGINAL_STAGE_BINDING)
    monkeypatch.setattr(guard, "github_status_provider", unavailable)
    with pytest.raises(ce.EvidenceError, match="review_stage_query_failed.*No usable temporary"):
        cs.stage_check(stage_package, runtime=dedicated.rt)


def test_failed_native_preflight_preserves_specific_error(dedicated, stage_package):
    p = cs.read_package(stage_package)
    dedicated.add_turn(dedicated.coordinator, "review-turn", p["coordinator_selection"]["arguments"])
    event = dedicated.command_event(dedicated.coordinator, "review-turn", cs.command(stage_package, "preflight"),
        {"result": "blocked", "code": "review_stage_status_expired", "detail": "fresh stage-check required"})
    event["payload"]["item"].update(status="failed", exit_code=1)
    dedicated.flush(dedicated.coordinator)
    with pytest.raises(ce.EvidenceError, match="review_stage_status_expired.*fresh stage-check"):
        cs.native_command(dedicated.rt, dedicated.coordinator, cs.command(stage_package, "preflight"), dedicated.root)


def test_failed_native_stage_check_preserves_specific_error(dedicated, stage_package):
    event = dedicated.command_event(dedicated.principal, "principal-turn", cs.command(stage_package, "stage-check"),
        {"result": "blocked", "code": "review_stage_query_failed", "detail": "authoritative query unavailable"})
    event["payload"]["item"].update(status="failed", exit_code=1)
    dedicated.flush(dedicated.principal)
    with pytest.raises(ce.EvidenceError, match="review_stage_query_failed.*authoritative query unavailable"):
        cs._stage_observation(stage_package, runtime=dedicated.rt, at_ms=dedicated.now)


def test_stage_check_refuses_coordinator_or_changed_principal_turn(dedicated, stage_package, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", dedicated.coordinator)
    with pytest.raises(ce.EvidenceError, match="review_principal_mismatch"):
        cs.stage_check(stage_package, runtime=dedicated.rt)
    monkeypatch.setenv("CODEX_THREAD_ID", dedicated.principal)
    dedicated.add_turn(dedicated.principal, "new-turn", {"model": "parent", "reasoning_effort": "high"}, sandbox="workspace-write")
    with pytest.raises(ce.EvidenceError, match="principal turn changed"):
        cs.stage_check(stage_package, runtime=dedicated.rt)
    with pytest.raises(ce.EvidenceError, match="principal turn changed"):
        cs.launch(stage_package)


def test_local_binding_rejects_card_branch_without_query(dedicated, monkeypatch):
    import resolve
    monkeypatch.setattr(resolve, "resolve", lambda *args: {"bound_card": "9000", "q_git": "card-9000-other"})
    with pytest.raises(ce.EvidenceError, match="review_stage_binding_mismatch"):
        ORIGINAL_LOCAL_BINDING({"root": str(dedicated.root), "bound_card": "1098"})


AUDITED_PREFLIGHT = r'''
import sys
sys.dont_write_bytecode = True
import importlib.util, json, os
from pathlib import Path
root, dependencies, instant, *authority = sys.argv[1:]
git_roots = [root, *authority]
violations = []
def deny(event, args):
    bad = False
    if event == "open":
        mode, flags = args[1:3]
        bad = (isinstance(mode, str) and any(x in mode for x in "wax+")) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND))
    elif event in {"os.mkdir", "os.remove", "os.rmdir", "os.rename", "os.chmod", "os.chown", "os.link", "os.symlink", "os.truncate", "os.utime", "tempfile.mkstemp", "tempfile.mkdtemp"}:
        bad = True
    elif event.startswith("socket."):
        bad = True
    elif event == "subprocess.Popen":
        bad = args[1] not in [["git", "-C", git_root, *tail] for git_root in git_roots for tail in (
            ["rev-parse", "--abbrev-ref", "HEAD"], ["rev-parse", "--show-toplevel"],
            ["config", "--local", "--no-includes", "--get", "remote.origin.url"],
            ["rev-parse", "--absolute-git-dir"], ["rev-parse", "--git-common-dir"])]
    elif event == "sqlite3.connect":
        bad = not isinstance(args[0], str) or not args[0].endswith("?mode=ro")
    elif event == "import" and args[0] in {"guard", "graphql_quota"}:
        bad = True
    if bad:
        violations.append(event)
        raise PermissionError("read-only preflight contract: " + event)
sys.addaudithook(deny)
sys.path.insert(0, dependencies)
helper = Path(root) / "scripts/process-fsm/codex_review_session.py"
spec = importlib.util.spec_from_file_location("codex_review_session", helper)
module = importlib.util.module_from_spec(spec)
sys.modules["codex_review_session"] = module
spec.loader.exec_module(module)
module._clock_ms = lambda: int(instant)
package = next((Path(root) / ".cursor/tmp/codex-evidence").glob("dedicated-review-*.package.json"))
result = module.preflight(package)
assert not violations, violations
assert result["result"] == "ready" and result["stage_status"] == "Code Review"
print(json.dumps({"result": "ready", "violations": violations, "guard_imported": "guard" in sys.modules,
                  "bytecode_writes": False, "classification": "controlled_readonly_contract_not_runtime_qualification"}))
'''


@pytest.mark.parametrize("external_authority", [False, True])
def test_full_product_preflight_cold_import_has_no_write_cache_or_network(dedicated, monkeypatch, tmp_path, external_authority):
    import os
    import subprocess
    import sys
    qualified_route(dedicated)
    authority = None
    if external_authority:
        from test_process_authority import authority_tree
        authority = authority_tree(tmp_path / "external" / dedicated.root.name)
        (dedicated.root / ".covenant-flow/overlay.yaml").unlink()
    diff = dedicated.root / "product.patch"; diff.write_text("diff --git a/a b/a\n-old\n+new\n")
    package = Path(cs.prepare(root=dedicated.root, phase="review", bootstrap=dedicated.bootstrap_path, diff=diff, runtime=dedicated.rt, authority_root=authority)["package"])
    dedicated.authorize(package)
    p = cs.read_package(package)
    dedicated.add_turn(dedicated.coordinator, "review-turn", p["coordinator_selection"]["arguments"])
    subprocess.run(["git", "init", "--initial-branch", dedicated.root.name, str(dedicated.root)], check=True, capture_output=True)
    # Resolve a real branch without creating any commit: the isolated fixture
    # references an existing consumer object through a read-only alternate.
    head = subprocess.run(["git", "-C", str(CONSUMER), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    objects = subprocess.run(["git", "-C", str(CONSUMER), "rev-parse", "--git-path", "objects"], check=True, capture_output=True, text=True).stdout.strip()
    (dedicated.root / ".git/refs/heads" / dedicated.root.name).write_text(head + "\n")
    (dedicated.root / ".git/objects/info/alternates").write_text(str((CONSUMER / objects).resolve()) + "\n")
    env = dict(os.environ, CODEX_THREAD_ID=dedicated.coordinator)
    result = subprocess.run([sys.executable, "-I", "-c", AUDITED_PREFLIGHT, str(dedicated.root), str(CONSUMER / "scripts/process-fsm"), str(dedicated.now), *([str(authority)] if authority else [])],
        cwd=dedicated.root, env=env, check=False, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["violations"] == []
    assert not json.loads(result.stdout)["guard_imported"]


def test_launch_revalidates_status_and_binds_exclusive_receipt(dedicated, monkeypatch):
    qualified_route(dedicated)
    diff = dedicated.root / "product.patch"; diff.write_text("diagnostic diff")
    package = Path(cs.prepare(root=dedicated.root, phase="review", bootstrap=dedicated.bootstrap_path, diff=diff, runtime=dedicated.rt)["package"])
    observed = cs.stage_check(package, runtime=dedicated.rt)
    dedicated.command_event(dedicated.principal, "principal-turn", cs.command(package, "stage-check"), observed)
    queries, calls = [], []
    def status(package, *, allowed):
        queries.append(allowed)
        return "Code Review"
    real_run = cs.subprocess.run
    def native(argv, **kwargs):
        if argv[0] == "git":
            return real_run(argv, **kwargs)
        calls.append(argv)
        kwargs["stdout"].write((json.dumps({"type": "thread.started", "thread_id": dedicated.coordinator}) + "\n").encode())
        return __import__("subprocess").CompletedProcess(argv, 0, stderr=b"")
    monkeypatch.setattr(cs, "stage_binding", status)
    monkeypatch.setattr(cs.subprocess, "run", native)
    result = cs.launch(package)
    receipt = cs.verify_stage_receipt(package, runtime=dedicated.rt)
    assert queries == [{"Code Review"}] and len(calls) == 1
    assert result["stage_receipt_sha256"] == receipt["integrity_sha256"]
    with pytest.raises(FileExistsError): cs.launch(package)
    assert len(calls) == 1
    p = cs.read_package(package)
    for relative in ("scripts/process-fsm/guard.py",):
        dependency = dedicated.root / relative
        assert str(dependency) in p["files"]
        original = dependency.read_bytes()
        dependency.write_bytes(original + b"changed authority\n")
        with pytest.raises(ce.EvidenceError, match="review_package_changed"):
            cs.read_package(package)
        dependency.write_bytes(original)


def test_status_change_between_check_and_launch_blocks_before_exec(dedicated, stage_package, monkeypatch):
    observed = cs.stage_check(stage_package, runtime=dedicated.rt)
    dedicated.command_event(dedicated.principal, "principal-turn", cs.command(stage_package, "stage-check"), observed)
    def changed(package, *, allowed):
        cs.fail("review_stage_binding_mismatch", "q=Em desenvolvimento")
    monkeypatch.setattr(cs, "stage_binding", changed)
    # This unit isolates the live status recheck; route positives are exercised
    # independently by the full cold-import and product-wave contract tests.
    monkeypatch.setattr(cs, "verify_route", lambda *args, **kwargs: {})
    monkeypatch.setattr(cc, "verify_qualification", lambda **kwargs: {})
    with pytest.raises(ce.EvidenceError, match="q=Em desenvolvimento"):
        cs.launch(stage_package)
    assert not Path(cs.read_package(stage_package)["events"]).exists()
    assert not Path(cs.read_package(stage_package)["stage_receipt"]).exists()


def test_principal_selects_latest_package_before_revalidating_code(dedicated, stage_package, monkeypatch):
    p = cs.read_package(stage_package)
    p.pop("integrity_sha256")
    old = copy.deepcopy(p)
    old["before_record"] -= 1
    old["files"][old["helper"]] = "historical-helper-digest"
    out = ce.destination(dedicated.root)
    old_path, new_path = out / "dedicated-review-old.package.json", out / "dedicated-review-new.package.json"
    old_path.write_text(json.dumps(ce.sealed(old)))
    new_path.write_text(json.dumps(ce.sealed(p)))
    old_bytes = old_path.read_bytes()
    monkeypatch.setattr(cs, "verify_route", lambda *args, **kwargs: {"coordinator_thread": dedicated.coordinator})
    monkeypatch.setattr(cc, "verify_qualification", lambda **kwargs: {})
    monkeypatch.setattr(rp, "verify_qualification", lambda **kwargs: {})
    ready = cs.principal_preflight(root=dedicated.root, session=dedicated.principal, runtime=dedicated.rt)
    assert ready["package"] == str(new_path)
    assert old_path.read_bytes() == old_bytes
    # The selected current package still has all code hashes checked.
    p["files"][p["helper"]] = "tampered-current-helper"
    new_path.write_text(json.dumps(ce.sealed(p)))
    with pytest.raises(ce.EvidenceError, match="review_package_changed"):
        cs.principal_preflight(root=dedicated.root, session=dedicated.principal, runtime=dedicated.rt)


def test_context_spawn_preflight_needs_active_native_continuation(dedicated):
    dedicated.bootstrap()
    package = Path(cs.prepare(root=dedicated.root, phase="context", bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)["package"])
    dedicated.monkeypatch.setenv("CODEX_THREAD_ID", dedicated.coordinator)
    with pytest.raises(ce.EvidenceError, match="continuation turn absent"):
        cs.preflight(package, runtime=dedicated.rt)
    p = cs.read_package(package)
    dedicated.add_turn(dedicated.coordinator, "context-active", p["coordinator_selection"]["arguments"])
    assert cs.preflight(package, runtime=dedicated.rt)["work_release"] == "diagnostic_only"


def test_reviewer_cannot_run_other_commands_before_fixed_probe(dedicated):
    dedicated.bootstrap(); dedicated.context()
    package = dedicated.probe()
    child = "probe-child-0"
    event = next(row for row in dedicated.rows[child] if row["payload"].get("item", {}).get("type") == "CommandExecution")
    earlier = copy.deepcopy(event)
    earlier["payload"]["item"]["command"][-1] = "cat another-diff"
    dedicated.rows[child].insert(dedicated.rows[child].index(event), earlier)
    dedicated.flush(child)
    with pytest.raises(ce.EvidenceError, match="review_probe_not_first"):
        cs.qualify_route(package, runtime=dedicated.rt)


def test_native_route_refusal_cannot_be_replaced_with_declared_failure(dedicated):
    dedicated.bootstrap(); dedicated.context()
    package = dedicated.probe()
    event = next(row for row in dedicated.rows[dedicated.principal] if row["payload"].get("item", {}).get("exit_code") == 1)
    event["payload"]["item"]["type"] = "AgentMessage"
    dedicated.flush(dedicated.principal)
    with pytest.raises(ce.EvidenceError, match="review_launch_source_unavailable"):
        cs.qualify_route(package, runtime=dedicated.rt)


@pytest.mark.parametrize("code,expected", [("review_route_unqualified", "blocked"),
    ("review_launcher_failed", "failed"), ("review_coordinator_observed_mismatch", "failed"),
    ("review_coordinator_interrupted", "interrupted"), ("review_launcher_interrupted", "interrupted"),
    ("review_launch_source_unavailable", "unverified"), ("review_coordinator_payload_unavailable", "unverified")])
def test_attempt_failures_are_not_relabelled_as_prebirth_refusal(code, expected):
    assert cs.outcome(code) == expected


class SettingsStream:
    def __init__(self, root):
        self.root = root
        self.pair = {"model": "gpt-6.1-sol", "reasoning_effort": "high"}
        self.package = {"root": str(root), "coordinator_selection": {"arguments": self.pair}}
        self.meta = {"originator": "codex_exec", "cwd": str(root)}
        self.rows = []
        self.add_turn("one")

    def add_turn(self, turn):
        self.rows.append({"type": "turn_context", "payload": {"turn_id": turn, "cwd": str(self.root),
            "model": self.pair["model"], "effort": self.pair["reasoning_effort"],
            "sandbox_policy": {"type": "read-only"}, "permission_profile": cs._readonly_profile()}})
        self.rows.append({"type": "event_msg", "payload": {"type": "thread_settings_applied", "thread_id": "coordinator",
            "thread_settings": managed_settings(self.root, self.pair)}})

    def session(self, session):
        assert session == "coordinator"
        turns = [row["payload"] for row in self.rows if row["type"] == "turn_context"]
        return Path("/native/projection.jsonl"), [(i, row, ce.digest(row)) for i, row in enumerate(self.rows)], self.meta, turns

    def check(self):
        return cs.readonly(self, "coordinator", self.package)


def test_initial_managed_readonly_settings_need_matching_effective_turn(tmp_path):
    stream = SettingsStream(tmp_path)
    assert stream.check()[2] == stream.meta
    stream.rows[0]["payload"].pop("permission_profile")
    with pytest.raises(ce.EvidenceError, match="not_read_only"):
        stream.check()


def test_identical_settings_can_reapply_before_work_in_native_resumes(tmp_path):
    stream = SettingsStream(tmp_path)
    stream.rows += [{"type": "response_item", "payload": {"type": "custom_tool_call"}},
                    {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "one"}}]
    stream.add_turn("two")
    stream.rows.append({"type": "response_item", "payload": {"type": "function_call"}})
    stream.rows.append({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "two"}})
    stream.add_turn("three")
    assert len(stream.check()[3]) == 3


@pytest.mark.parametrize("fault", ["disabled", "write", "extra-entry", "network", "unknown-profile", "unknown-filesystem",
    "turn-disabled", "turn-profile-missing", "turn-policy-extra", "model", "effort", "cwd", "roots", "approval", "provider", "approval-reviewer",
    "collaboration-model", "collaboration-effort", "collaboration-extra", "unknown-setting", "missing-setting",
    "wrong-thread", "wrong-turn", "unknown-envelope", "before-turn", "after-command", "after-terminal",
    "identical-after-work", "repeated-context-after-work", "different-on-resume", "first-settings-on-resume"])
def test_settings_never_hide_mutation_or_unknown_native_state(tmp_path, fault):
    s = SettingsStream(tmp_path)
    turn = s.rows[0]["payload"]; event = s.rows[1]; v = event["payload"]; settings = v["thread_settings"]
    profile = settings["permission_profile"]
    if fault == "disabled": settings["permission_profile"] = {"type": "disabled"}
    elif fault == "write": profile["file_system"]["entries"][0]["access"] = "write"
    elif fault == "extra-entry": profile["file_system"]["entries"].append({"path": "/tmp", "access": "write"})
    elif fault == "network": profile["network"] = "enabled"
    elif fault == "unknown-profile": profile["future_policy"] = True
    elif fault == "unknown-filesystem": profile["file_system"]["write_allowed"] = True
    elif fault == "turn-disabled": turn["permission_profile"] = {"type": "disabled"}
    elif fault == "turn-profile-missing": turn.pop("permission_profile")
    elif fault == "turn-policy-extra": turn["sandbox_policy"]["write_allowed"] = True
    elif fault == "model": settings["model"] = "other"
    elif fault == "effort": settings["reasoning_effort"] = "low"
    elif fault == "cwd": settings["cwd"] = "/source"
    elif fault == "roots": settings["runtime_workspace_roots"].append("/other")
    elif fault == "approval": settings["approval_policy"] = "on-request"
    elif fault == "provider": settings["model_provider_id"] = "other"
    elif fault == "approval-reviewer": settings["approvals_reviewer"] = "auto_review"
    elif fault == "collaboration-model": settings["collaboration_mode"]["settings"]["model"] = "other"
    elif fault == "collaboration-effort": settings["collaboration_mode"]["settings"]["reasoning_effort"] = "low"
    elif fault == "collaboration-extra": settings["collaboration_mode"]["settings"]["future_write"] = True
    elif fault == "unknown-setting": settings["future_write"] = True
    elif fault == "missing-setting": settings.pop("permission_profile")
    elif fault == "wrong-thread": v["thread_id"] = "principal"
    elif fault == "wrong-turn": v["turn_id"] = "other"
    elif fault == "unknown-envelope": v["future_override"] = True
    elif fault == "before-turn": s.rows.reverse()
    elif fault == "after-command": s.rows.insert(1, {"type": "event_msg", "payload": {"type": "item_completed", "item": {"type": "CommandExecution"}}})
    elif fault == "after-terminal": s.rows.insert(1, {"type": "event_msg", "payload": {"type": "task_complete"}})
    elif fault == "identical-after-work": s.rows += [{"type": "response_item", "payload": {"type": "function_call"}}, copy.deepcopy(event)]
    elif fault == "repeated-context-after-work": s.rows += [{"type": "response_item", "payload": {"type": "custom_tool_call"}}, copy.deepcopy(s.rows[0]), copy.deepcopy(event)]
    elif fault == "different-on-resume":
        s.rows.append({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "one"}})
        s.add_turn("two"); s.rows[-1]["payload"]["thread_settings"]["disabled_plugin_ids"] = ["other-plugin"]
    elif fault == "first-settings-on-resume":
        s.rows.pop(); s.add_turn("two")
    with pytest.raises(ce.EvidenceError): s.check()


def test_setting_digests_stay_scoped_to_attempt_while_resumes_are_revalidated(tmp_path):
    s = SettingsStream(tmp_path)
    first = cs._permission_sources(s, "coordinator", "one")
    s.rows.append({"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "one"}})
    s.add_turn("two")
    assert cs._permission_sources(s, "coordinator", "one") == first
    assert s.check()
    s.rows[1]["payload"]["thread_settings"]["service_tier"] = "priority"
    s.rows[-1]["payload"]["thread_settings"]["service_tier"] = "priority"
    assert s.check()  # Still safe; old evidence must nonetheless detect source edits.
    assert cs._permission_sources(s, "coordinator", "one") != first


def test_native_initial_settings_and_identical_resumes_preserve_context_route(dedicated):
    dedicated.native_settings = True
    probe = qualified_route(dedicated)
    before = cs.verify_route(dedicated.bootstrap_path, runtime=dedicated.rt)
    p = cs.read_package(probe)
    pair = p["coordinator_selection"]["arguments"]
    dedicated.add_turn(dedicated.coordinator, "next-safe-turn", pair)
    assert cs.verify_route(dedicated.bootstrap_path, runtime=dedicated.rt) == before


def test_service_tier_metadata_change_preserves_context_preflight_and_route(dedicated, monkeypatch):
    dedicated.native_settings = True
    original_add_turn = dedicated.add_turn
    def add_tiered_turn(session, turn, pair, sandbox='read-only'):
        original_add_turn(session, turn, pair, sandbox)
        if session == dedicated.coordinator and turn != 'bootstrap-turn':
            dedicated.rows[session][-1]['payload']['thread_settings']['service_tier'] = 'priority'
            dedicated.flush(session)
    monkeypatch.setattr(dedicated, 'add_turn', add_tiered_turn)
    qualified_route(dedicated)
    route = cs.verify_route(dedicated.bootstrap_path, runtime=dedicated.rt)
    actual_tiers = [row['payload']['thread_settings']['service_tier'] for row in dedicated.rows[dedicated.coordinator]
                   if row['type'] == 'event_msg' and row['payload'].get('type') == 'thread_settings_applied']
    assert actual_tiers[0] == 'default' and set(actual_tiers[1:]) == {'priority'}
    assert route['coordinator_thread'] == dedicated.coordinator


def test_context_cli_preflight_accepts_tier_metadata_but_releases_diagnostic_only(dedicated, monkeypatch, capsys):
    dedicated.native_settings = True
    dedicated.bootstrap()
    prepared = cs.prepare(root=dedicated.root, phase='context', bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)
    p = cs.read_package(prepared['package'])
    dedicated.add_turn(dedicated.coordinator, 'context-turn', p['coordinator_selection']['arguments'])
    dedicated.rows[dedicated.coordinator][-1]['payload']['thread_settings']['service_tier'] = 'priority'
    dedicated.flush(dedicated.coordinator)
    monkeypatch.setenv('CODEX_THREAD_ID', dedicated.coordinator)
    monkeypatch.setattr(cs.sys, 'argv', ['codex_review_session.py', 'preflight', '--package', prepared['package']])
    assert cs.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output['result'] == 'ready' and output['phase'] == 'context'
    assert output['work_release'] == 'diagnostic_only' and output['stage_status'] == 'unavailable'
    assert output['internal_context_attestation'] == 'unavailable'


def interturn_stream(root):
    s = SettingsStream(root)
    s.rows += [{"type": "response_item", "payload": {"type": "custom_tool_call"}},
        {"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "one"}},
        copy.deepcopy(s.rows[1]), copy.deepcopy(s.rows[1]),
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "two"}}]
    s.add_turn("two")
    return s


def test_native_settings_between_terminal_and_started_context_belong_to_next_turn(tmp_path):
    s = interturn_stream(tmp_path)
    assert s.check()
    first = cs._permission_sources(s, "coordinator", "one")
    second = cs._permission_sources(s, "coordinator", "two")
    assert {ref['ordinal'] for ref in first} == {0, 1}
    assert {ref['ordinal'] for ref in second} == {4, 5, 7, 8}
    # Further identical settings after terminal cannot mutate prior proof refs.
    s.rows += [{"type": "event_msg", "payload": {"type": "task_complete", "turn_id": "two"}}, copy.deepcopy(s.rows[1])]
    assert s.check()
    assert cs._permission_sources(s, "coordinator", "one") == first
    assert cs._permission_sources(s, "coordinator", "two") == second
    s.rows.append({"type": "event_msg", "payload": {"type": "task_started", "turn_id": "three"}})
    s.add_turn("three")
    assert s.check()
    assert cs._permission_sources(s, "coordinator", "two") == second


@pytest.mark.parametrize('fault', ['write', 'network', 'roots', 'model', 'effort', 'provider', 'approval', 'approval-reviewer', 'plugins', 'unknown',
    'changed-then-restored', 'wrong-thread', 'explicit-old-turn', 'missing-terminal', 'wrong-terminal',
    'tool-in-gap', 'resumed-profile', 'resumed-model'])
def test_interturn_settings_do_not_allow_changes_unknown_or_unbound_work(tmp_path, fault):
    s = interturn_stream(tmp_path)
    event = s.rows[4]['payload']; settings = event['thread_settings']
    if fault == 'write': settings['permission_profile']['file_system']['entries'][0]['access'] = 'write'
    elif fault == 'network': settings['permission_profile']['network'] = 'enabled'
    elif fault == 'roots': settings['runtime_workspace_roots'].append('/other')
    elif fault == 'model': settings['model'] = 'other'
    elif fault == 'effort': settings['reasoning_effort'] = 'low'
    elif fault == 'provider': settings['model_provider_id'] = 'other'
    elif fault == 'approval': settings['approval_policy'] = 'on-request'
    elif fault == 'approval-reviewer': settings['approvals_reviewer'] = 'auto_review'
    elif fault == 'plugins': settings['disabled_plugin_ids'] = ['different-plugin']
    elif fault == 'unknown': settings['new_native_override'] = True
    elif fault == 'changed-then-restored': settings['permission_profile'] = {'type':'disabled'}
    elif fault == 'wrong-thread': event['thread_id'] = 'principal'
    elif fault == 'explicit-old-turn': event['turn_id'] = 'one'
    elif fault == 'missing-terminal': s.rows.pop(3)
    elif fault == 'wrong-terminal': s.rows[3]['payload']['turn_id'] = 'other'
    elif fault == 'tool-in-gap': s.rows.insert(6, {'type':'response_item','payload':{'type':'function_call'}})
    elif fault == 'resumed-profile': s.rows[7]['payload']['permission_profile'] = {'type':'disabled'}
    elif fault == 'resumed-model': s.rows[7]['payload']['model'] = 'other'
    with pytest.raises(ce.EvidenceError): s.check()


@pytest.mark.parametrize('before,after', [('default', 'priority'), ('priority', 'default')])
def test_service_tier_change_between_native_turns_preserves_actual_source_values(tmp_path, before, after):
    s = interturn_stream(tmp_path)
    s.rows[1]['payload']['thread_settings']['service_tier'] = before
    for ordinal in (4, 5, 8):
        s.rows[ordinal]['payload']['thread_settings']['service_tier'] = after
    original_rows = copy.deepcopy(s.rows)
    initial = cs._permission_sources(s, 'coordinator', 'one')
    assert s.check()
    assert s.rows == original_rows  # Never fake full-settings equality or edit a source.
    assert s.rows[1]['payload']['thread_settings'] != s.rows[4]['payload']['thread_settings']
    assert cs._authorization_settings(s.rows[1]['payload']['thread_settings']) == cs._authorization_settings(s.rows[4]['payload']['thread_settings'])
    resumed = cs._permission_sources(s, 'coordinator', 'two')
    assert {ref['ordinal'] for ref in initial} == {0, 1}
    assert {ref['ordinal'] for ref in resumed} == {4, 5, 7, 8}
    assert s.rows[1]['payload']['thread_settings']['service_tier'] == before
    assert s.rows[4]['payload']['thread_settings']['service_tier'] == after
    s.rows[4]['payload']['thread_settings']['service_tier'] = before
    assert cs._permission_sources(s, 'coordinator', 'one') == initial
    assert cs._permission_sources(s, 'coordinator', 'two') != resumed


@pytest.mark.parametrize('value', [None, '', '   ', 1, False, {}, []])
def test_service_tier_metadata_still_requires_valid_native_schema(tmp_path, value):
    s = interturn_stream(tmp_path)
    s.rows[4]['payload']['thread_settings']['service_tier'] = value
    with pytest.raises(ce.EvidenceError, match='settings_changed'): s.check()


@pytest.mark.parametrize('location', ['during-work', 'gap-before-next-turn', 'new-turn-before-work'])
def test_service_tier_never_exempts_unknown_fields_or_unbound_timing(tmp_path, location):
    s = interturn_stream(tmp_path)
    if location == 'during-work':
        event = copy.deepcopy(s.rows[1])
        event['payload']['thread_settings']['service_tier'] = 'priority'
        s.rows.insert(3, event)
    else:
        ordinal = 4 if location == 'gap-before-next-turn' else 8
        s.rows[ordinal]['payload']['thread_settings']['service_tier'] = 'priority'
        s.rows[ordinal]['payload']['thread_settings']['future_authority'] = True
    with pytest.raises(ce.EvidenceError): s.check()


def test_context_prepares_exact_preflight_and_native_spawn_without_wrong_inspect(dedicated):
    dedicated.bootstrap()
    prepared = cs.prepare(root=dedicated.root, phase='context', bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)
    p = cs.read_package(prepared['package'])
    prompt = Path(p['prompt']).read_text()
    assert cs.command(prepared['package'], 'preflight') in prompt
    assert cs.command(prepared['package'], 'inspect') not in prompt
    assert 'collaboration.spawn_agent' in prompt
    assert 'review_native_spawn_unavailable' in prompt
    assert dedicated.sentinel not in prompt


def test_context_preflight_refuses_missing_active_v2_runtime(dedicated):
    dedicated.bootstrap()
    prepared = cs.prepare(root=dedicated.root, phase='context', bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)
    p = cs.read_package(prepared['package'])
    dedicated.add_turn(dedicated.coordinator, 'active-context', p['coordinator_selection']['arguments'])
    dedicated.rows[dedicated.coordinator][-1]['payload']['multi_agent_version'] = 'v1'
    dedicated.flush(dedicated.coordinator)
    dedicated.monkeypatch.setenv('CODEX_THREAD_ID', dedicated.coordinator)
    with pytest.raises(ce.EvidenceError, match='review_native_spawn_unavailable'):
        cs.preflight(prepared['package'], runtime=dedicated.rt)


def test_inspect_on_context_reports_action_phase_instead_of_wrong_identity(dedicated, monkeypatch, capsys):
    dedicated.bootstrap()
    prepared = cs.prepare(root=dedicated.root, phase='context', bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)
    monkeypatch.setattr(cs.sys, 'argv', ['codex_review_session.py', 'inspect', '--package', prepared['package']])
    assert cs.main() == 1
    result = json.loads(capsys.readouterr().out)
    assert result['code'] == 'review_action_phase_mismatch'


def test_shell_custom_tool_text_cannot_substitute_native_spawn_origin(dedicated):
    dedicated.bootstrap()
    prepared = cs.prepare(root=dedicated.root, phase='context', bootstrap=dedicated.bootstrap_path, runtime=dedicated.rt)
    p = dedicated.finish_children(prepared['package'])
    call = next(row['payload'] for row in dedicated.rows[dedicated.coordinator]
        if row['type']=='response_item' and row['payload'].get('type')=='function_call')
    call.update(type='custom_tool_call', name='exec', input='shell code mentioning spawn_agent is not a native call')
    dedicated.flush(dedicated.coordinator)
    with pytest.raises(ce.EvidenceError, match='birth_mismatch'):
        ce.collect(p['births'][0], wait_seconds=0, runtime=dedicated.rt)


def test_nucleus_without_overlay_uses_explicit_consumer_and_revalidates_every_reader(dedicated, tmp_path, monkeypatch):
    """Full source-bound wave in the nucleus; authority data stays external."""
    import guard
    from test_process_authority import authority_tree
    qualified_route(dedicated)
    authority = authority_tree(tmp_path / 'consumer' / dedicated.root.name)
    (dedicated.root / '.covenant-flow/overlay.yaml').unlink()
    diff = dedicated.root / 'product.patch'; diff.write_text('diff --git a/a b/a\n-old\n+new\n')
    monkeypatch.setattr(cs, 'stage_binding', ORIGINAL_STAGE_BINDING)
    monkeypatch.setattr(cs, 'local_binding', ORIGINAL_LOCAL_BINDING)
    queries = []
    def status(card, *, authority):
        queries.append(authority)
        assert card == '1098'
        assert authority['root'] != str(dedicated.root)
        return 'Code Review'
    monkeypatch.setattr(guard, 'github_status_provider', status)
    prepared = cs.prepare(root=dedicated.root, phase='review', bootstrap=dedicated.bootstrap_path,
                          diff=diff, authority_root=authority, runtime=dedicated.rt)
    path = Path(prepared['package'])
    package = cs.read_package(path)
    assert package['root'] == str(dedicated.root)
    assert package['authority']['root'] == str(authority)
    assert package['diff'] == str(diff)
    assert all(Path(name).is_relative_to(dedicated.root) for name in package['files'])
    assert cs.inside(dedicated.root, package['stage_receipt'])
    with pytest.raises(ce.EvidenceError): cs.inside(dedicated.root, authority / 'arbitrary-target')
    ready = ce.preflight(root=dedicated.root, stage='pedir_review', runtime=dedicated.rt)
    assert ready['package'] == str(path)
    package = dedicated.finish_children(path)
    proofs = [ce.collect(b, wait_seconds=0, runtime=dedicated.rt) for b in package['births']]
    assert all(proof['status'] == 'completed' for proof in proofs)
    assert len(queries) == 3  # prepare, principal T9 preflight, native stage-check; coordinator/collect are offline.
    assert not (dedicated.root / '.covenant-flow/overlay.yaml').exists()
    overlay = authority / '.covenant-flow/overlay.yaml'
    overlay.write_text(overlay.read_text() + '\n# authority changed\n')
    # Every entry rereads the pinned source before observing runtime, querying,
    # launching, writing receipts or promoting a collected child.
    for operation in (lambda: cs.read_package(path), lambda: cs.stage_check(path, runtime=dedicated.rt),
                      lambda: cs.launch(path), lambda: cs.preflight(path, runtime=dedicated.rt),
                      lambda: ce.collect(package['births'][0], wait_seconds=0, runtime=dedicated.rt)):
        with pytest.raises(ce.EvidenceError, match='review_authority_invalid'):
            operation()


def test_review_missing_authority_has_specific_refusal_and_no_implicit_fallback(dedicated):
    (dedicated.root / '.covenant-flow/overlay.yaml').unlink()
    with pytest.raises(ce.EvidenceError, match='review_authority_invalid.*source_unavailable'):
        cs.prepare(root=dedicated.root, phase='review', runtime=dedicated.rt)
