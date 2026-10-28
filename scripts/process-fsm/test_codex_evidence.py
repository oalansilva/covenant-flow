"""Controlled rollout fixtures exercise refusals; these do not qualify any host."""
import json
import copy
import sqlite3
from pathlib import Path

import pytest
import yaml

import codex_evidence as ce
from model_selection import resolve, save_capture
from model_selection_fixtures import machine_models


class Essay:
    def __init__(self, tmp_path, monkeypatch, role="qa-gate", sandbox="workspace-write", wave="unavailable", qualification=True, host="codex_exec", skip_prepare=False, capture_suffix=""):
        self.host = host
        self.root = tmp_path / "card-1095-fixture"
        self.root.mkdir(exist_ok=True)
        self.home = Path.home() / ".codex"
        self.sessions = self.home / "sessions"
        self.sessions.mkdir(exist_ok=True)
        parent_label = "review-parent" if sandbox == "read-only" else "parent-" + role
        self.parent = self.sessions / f"{parent_label}.jsonl"
        self.child = self.sessions / f"child-{role}.jsonl"
        self.parent_id = parent_label
        self.child_id = "child-" + role
        self.task = role.replace("-", "_") + "_essay"
        self.agent_path = "/root/" + self.task
        self.sandbox = sandbox
        monkeypatch.setenv("CODEX_THREAD_ID", self.parent_id)
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("CREATE TABLE IF NOT EXISTS threads (id TEXT, rollout_path TEXT, agent_path TEXT)")
            if not db.execute("SELECT id FROM threads WHERE id=?", (self.parent_id,)).fetchone():
                db.execute("INSERT INTO threads VALUES (?,?,?)", (self.parent_id, str(self.parent), "/root"))
        self.cap = resolve("codex", "execucao", role=role)
        self.capture = tmp_path / (role + capture_suffix + ".capture.json")
        save_capture(self.capture, self.cap)
        self.p = [self.row("session_meta", dict(id=self.parent_id, originator=self.host, cli_version="0.162.1", cwd=str(self.root), timestamp="2026-10-13T01:00:00Z", source="exec")), self.row("turn_context", dict(turn_id="parent-turn", model="parent-model", effort="medium", cwd=str(self.root), sandbox_policy={"type": sandbox}))]
        if self.parent.exists():
            self.p = [json.loads(line) for line in self.parent.read_text().splitlines()]
        else:
            self.write(self.parent, self.p)
        (self.root / ce.DEFAULT_DEST).mkdir(parents=True, mode=0o700, exist_ok=True)
        if skip_prepare:
            return
        self.receipt = ce.prepare(root=self.root, capture=self.capture, task_name=self.task, qualification=qualification, wave_id=wave, review_diff_sha256="a" * 64)
        self.birth = Path(self.receipt["birth"])

    @staticmethod
    def row(kind, payload):
        return {"type": kind, "timestamp": "2026-10-13T01:01:00Z", "payload": payload}

    @staticmethod
    def write(path, rows):
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def complete(self, turns=None):
        turns = turns or [("child-turn", self.cap["arguments"])]
        native = {"internal_chat_message_metadata_passthrough": {"turn_id": "parent-turn"}}
        self.p += [self.row("response_item", dict(type="function_call", name="spawn_agent", namespace="collaboration", call_id="call-" + self.task, arguments=json.dumps(dict(task_name=self.task, **self.cap["arguments"], fork_turns="none", message="sensitive prompt")), **native)), self.row("response_item", dict(type="function_call_output", call_id="call-" + self.task, output=json.dumps({"task_name": self.agent_path}), **native))]
        self.c = [self.row("session_meta", dict(id=self.child_id, originator=self.host, cli_version="0.162.1", cwd=str(self.root), timestamp="2026-10-13T01:01:00Z", source={"subagent": {"thread_spawn": {"parent_thread_id": self.parent_id, "agent_path": self.agent_path}}}))]
        for turn, pair in turns:
            self.c += [self.row("event_msg", dict(type="task_started", turn_id=turn)), self.row("turn_context", dict(turn_id=turn, model=pair.get("model"), effort=pair.get("reasoning_effort"), cwd=str(self.root), sandbox_policy={"type": self.sandbox})), self.row("event_msg", dict(type="task_complete", turn_id=turn, last_agent_message="returned " + turn))]
            self.p.append(self.row("response_item", dict(type="agent_message", author=self.agent_path, content=[{"type": "input_text", "text": f"Message Type: FINAL_ANSWER\nTask name: /root\nSender: {self.agent_path}\nPayload:\nreturned {turn}"}])))
        self.write(self.parent, self.p)
        self.write(self.child, self.c)
        with sqlite3.connect(self.home / "state_5.sqlite") as db:
            db.execute("INSERT INTO threads VALUES (?,?,?)", (self.child_id, str(self.child), self.agent_path))
        return self

    def collect(self):
        return ce.collect(self.birth, wait_seconds=0)

    def continue_turn(self, turn, pair=None):
        pair = self.cap["arguments"] if pair is None else pair
        self.c += [self.row("event_msg", dict(type="task_started", turn_id=turn)), self.row("turn_context", dict(turn_id=turn, model=pair.get("model"), effort=pair.get("reasoning_effort"), cwd=str(self.root), sandbox_policy={"type": self.sandbox})), self.row("event_msg", dict(type="task_complete", turn_id=turn, last_agent_message="returned " + turn))]
        self.p.append(self.row("response_item", dict(type="agent_message", author=self.agent_path, content=[{"type": "input_text", "text": f"Message Type: FINAL_ANSWER\nPayload:\nreturned {turn}"}])))
        self.write(self.parent, self.p)
        self.write(self.child, self.c)


@pytest.fixture
def essay(tmp_path, monkeypatch, machine_models):
    return Essay(tmp_path, monkeypatch)


@pytest.mark.parametrize("parent", [False, True])
def test_identical_context_repetitions_preserve_all_origin_rows(essay, parent):
    essay.complete()
    rows, path = (essay.p, essay.parent) if parent else (essay.c, essay.child)
    position = next(i for i, row in enumerate(rows) if row["type"] == "turn_context")
    repeated = copy.deepcopy(rows[position])
    repeated["timestamp"] = "2026-10-13T01:02:00Z"
    rows.insert(position + 1, repeated)
    essay.write(path, rows)
    proof = essay.collect()
    assert len(proof["turns"]) == 1
    refs = [s for s in proof["sources"] if s["source"] == str(path) and s["type"] == "turn_context"]
    assert len(refs) == 2
    assert refs[0]["raw_sha256"] != refs[1]["raw_sha256"]
    assert ce.verify_evidence(proof["evidence_path"])["sources"] == proof["sources"]
    rows[position + 1]["payload"]["extra_runtime_field"] = "changed"
    essay.write(path, rows)
    with pytest.raises(ce.EvidenceError, match="turn_conflict"):
        ce.verify_evidence(proof["evidence_path"])


@pytest.mark.parametrize("field,value", [("model", "other"), ("effort", "low"),
    ("cwd", "/source"), ("sandbox_policy", {"type": "read-only"}), ("unrecognized", True)])
def test_any_repeated_context_payload_divergence_is_refused(essay, field, value):
    essay.complete()
    repeated = copy.deepcopy(essay.c[2])
    repeated["payload"][field] = value
    essay.c.insert(3, repeated)
    essay.write(essay.child, essay.c)
    with pytest.raises(ce.EvidenceError, match="turn_conflict"):
        essay.collect()


def test_native_chain_private_minimal_stable_idempotent_and_gate(essay):
    essay.complete()
    result = essay.collect()
    path = Path(result["evidence_path"])
    assert ce.verify_evidence(path)["child_thread"] == essay.child_id
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert "sensitive prompt" not in path.read_text() and "returned child-turn" not in path.read_text()
    original = path.read_bytes()
    essay.p.append(essay.row("event_msg", {"type": "unrelated-advisory"}))
    essay.write(essay.parent, essay.p)
    assert essay.collect()["integrity_sha256"] == result["integrity_sha256"]
    assert path.read_bytes() == original
    from codex_proxy import record
    kwargs = dict(repo_root=essay.root, activity="qa-gate", band="execucao", requested_model="gpt-6-luna", requested_effort="max", observed_model="gpt-6-luna", observed_effort="max", host="codex_exec", host_version="0.162.1", status="completed", payload_returned=True, child_id=essay.child_id, bound_card="1095", sandbox_mode="workspace-write", review_diff_sha256="a" * 64, capture=essay.cap, runtime_evidence=path)
    proxy = record(**kwargs)
    assert proxy["successful"]
    assert ce.verify_proxy(proxy)["validation"] == "verified"
    assert record(**kwargs) == proxy
    assert len((essay.root / ".cursor/tmp/codex-child-proxies.jsonl").read_text().splitlines()) == 1


def test_completed_continuations_preserve_snapshots_and_one_proxy(essay, machine_models):
    from codex_proxy import record
    essay.complete()
    first = essay.collect()
    path = Path(first["evidence_path"])
    original = path.read_bytes()
    kwargs = dict(repo_root=essay.root, activity="qa-gate", band="execucao", requested_model="gpt-6-luna", requested_effort="max", observed_model="gpt-6-luna", observed_effort="max", host="codex_exec", host_version="0.162.1", status="completed", payload_returned=True, child_id=essay.child_id, bound_card="1095", sandbox_mode="workspace-write", review_diff_sha256="a" * 64, capture=essay.cap, runtime_evidence=path)
    proxy = record(**kwargs)
    # A changed picker only applies to new births, including recollection.
    doc = yaml.safe_load(machine_models.read_text())
    doc["clients"]["codex"]["execucao"].update(model="gpt-6.1-sol", effort="high")
    machine_models.write_text(yaml.safe_dump(doc))
    snapshots = [(path, original)]
    for turn in ("continued", "continued-again"):
        essay.continue_turn(turn)
        result = essay.collect()
        revised = Path(result["evidence_path"])
        assert revised != path
        assert result["birth"] == first["birth"]
        assert essay.collect() == result
        assert revised.stat().st_mode & 0o777 == 0o600
        assert "returned " not in revised.read_text()
        assert all(p.read_bytes() == data for p, data in snapshots)
        assert ce.verify_evidence(path) == {k: v for k, v in first.items() if k != "evidence_path"}
        assert ce.verify_evidence(revised)["turns"] == result["turns"]
        assert record(**dict(kwargs, runtime_evidence=revised)) == proxy
        assert ce.verify_proxy(proxy)["validation"] == "verified"
        snapshots.append((revised, revised.read_bytes()))
    assert len(list(path.parent.glob("*.evidence*.json"))) == 3
    assert len((essay.root / ".cursor/tmp/codex-child-proxies.jsonl").read_text().splitlines()) == 1


@pytest.mark.parametrize("mutation", ["record", "payload", "remove"])
def test_old_anchor_cannot_hide_change_to_accepted_continuation(essay, mutation):
    essay.complete()
    first = essay.collect()
    essay.continue_turn("continued")
    second = essay.collect()
    preserved = {p: p.read_bytes() for p in essay.birth.parent.glob("*.evidence*.json")}
    if mutation == "record":
        essay.c[5]["payload"]["extra_field"] = "changed accepted turn"
    elif mutation == "payload":
        essay.c[-1]["payload"]["last_agent_message"] = "changed"
        essay.p[-1]["payload"]["content"][0]["text"] = "Message Type: FINAL_ANSWER\nPayload:\nchanged"
    else:
        essay.c = essay.c[:4]
        essay.p.pop()
    essay.write(essay.child, essay.c)
    essay.write(essay.parent, essay.p)
    for path in (first["evidence_path"], second["evidence_path"]):
        with pytest.raises(ce.EvidenceError, match="provenance_mismatch"):
            ce.verify_evidence(path)
    with pytest.raises(ce.EvidenceError, match="provenance_mismatch"):
        essay.collect()
    assert all(p.read_bytes() == data for p, data in preserved.items())


def test_divergent_continuation_cannot_reuse_old_proof_or_last_good_turn(essay):
    essay.complete()
    first = essay.collect()
    original = Path(first["evidence_path"]).read_bytes()
    essay.continue_turn("divergent", {"model": "gpt-6-astra", "reasoning_effort": "medium"})
    essay.continue_turn("last-good")
    with pytest.raises(ce.EvidenceError, match="observed_mismatch"):
        ce.verify_evidence(first["evidence_path"])
    with pytest.raises(ce.EvidenceError, match="observed_mismatch"):
        essay.collect()
    assert Path(first["evidence_path"]).read_bytes() == original
    assert len(list(essay.birth.parent.glob("*.evidence*.json"))) == 1


def test_old_anchor_refuses_unfinished_continuation_and_tampered_revision(essay):
    essay.complete()
    first = essay.collect()
    essay.continue_turn("continued")
    complete = essay.c.pop()
    essay.write(essay.child, essay.c)
    with pytest.raises(ce.EvidenceError, match="terminal_unavailable"):
        ce.verify_evidence(first["evidence_path"])
    essay.c.append(complete)
    essay.write(essay.child, essay.c)
    revised = essay.collect()
    path = Path(revised["evidence_path"])
    tampered = json.loads(path.read_text())
    tampered["payload_sha256"][-1] = "f" * 64
    path.write_text(json.dumps(tampered))
    with pytest.raises(ce.EvidenceError, match="integrity_mismatch"):
        ce.verify_evidence(first["evidence_path"])
    with pytest.raises(ce.EvidenceError, match="integrity_mismatch"):
        essay.collect()


@pytest.mark.parametrize("mutation,code", [
    (lambda e: e.c[0]["payload"]["source"]["subagent"]["thread_spawn"].update(parent_thread_id="another"), "source_conflict"),
    (lambda e: e.c[0]["payload"].update(id="another"), "identity_mismatch"),
    (lambda e: e.c[0]["payload"].pop("cli_version"), "unsupported_schema"),
    (lambda e: e.c[2]["payload"].update(model=None), "observed_mismatch"),
    (lambda e: e.c[2]["payload"].update(effort=None), "observed_mismatch"),
    (lambda e: e.c[2]["payload"].update(model="different"), "observed_mismatch"),
    (lambda e: e.c[2]["payload"].update(effort="high"), "observed_mismatch"),
    (lambda e: e.c[3]["payload"].update(turn_id="another"), "turn_mismatch"),
    (lambda e: e.c[3]["payload"].update(last_agent_message=""), "payload_unavailable"),
    (lambda e: e.c.pop(), "terminal_unavailable"),
    (lambda e: e.p[-1]["payload"]["content"][0].update(text="Message Type: FINAL_ANSWER\nPayload:\nother payload"), "return_payload_mismatch"),
    (lambda e: e.p[3]["payload"].update(call_id="another"), "spawn_return_unavailable"),
    (lambda e: e.p[2]["payload"].update(arguments=json.dumps({"task_name": e.task, "model": "wrong", "reasoning_effort": "max"})), "requested_mismatch"),
])
def test_refusal_preserves_work_and_status(essay, mutation, code):
    essay.complete()
    artifact = essay.root / "artifact.txt"
    artifact.write_text("keep useful work")
    mutation(essay)
    essay.write(essay.parent, essay.p)
    essay.write(essay.child, essay.c)
    with pytest.raises(ce.EvidenceError, match=code):
        essay.collect()
    assert artifact.read_text() == "keep useful work"
    assert not list(essay.birth.parent.glob("*.evidence.json"))
    assert list(essay.birth.parent.glob("*.failure-*.json"))


@pytest.mark.parametrize("mutation,code", [
    (lambda e: e.p[0]["payload"].update(originator=""), "unsupported_schema"),
    (lambda e: e.p[0]["payload"].pop("cli_version"), "unsupported_schema"),
    (lambda e: e.p[1]["payload"].pop("turn_id"), "unsupported_schema"),
    (lambda e: e.p[1]["payload"].update(cwd="/other"), "worktree_mismatch"),
])
def test_preflight_host_schema_and_worktree(essay, mutation, code):
    mutation(essay)
    essay.write(essay.parent, essay.p)
    with pytest.raises(ce.EvidenceError, match=code):
        ce.preflight(root=essay.root, qualification=True)


def test_a_cli_version_never_seen_with_the_same_rollout_format_passes_preflight_and_is_recorded(essay):
    essay.complete()
    for rows, path in ((essay.p, essay.parent), (essay.c, essay.child)):
        rows[0]["payload"]["cli_version"] = "9.9.9"
        essay.write(path, rows)
    assert ce.preflight(root=essay.root, qualification=True)["driver"] == ce.DRIVER == "codex_exec/rollout-v1"
    result = essay.collect()
    assert result["host_version"] == "9.9.9" and result["driver"] == "codex_exec/rollout-v1" and result["status"] == "completed"


def test_the_schema_error_names_the_record_kind_the_field_and_the_observed_version(essay):
    essay.complete()
    essay.p[0]["payload"]["cli_version"] = "9.9.9"
    essay.p[1]["payload"].pop("sandbox_policy")
    essay.write(essay.parent, essay.p)
    with pytest.raises(ce.EvidenceError) as e:
        ce.preflight(root=essay.root, qualification=True)
    assert e.value.code == "unsupported_schema" and "turn_context" in str(e.value) and "sandbox_policy" in str(e.value) and "9.9.9" in str(e.value)


@pytest.mark.parametrize("host", ["codex-tui", "codex_app_server", "future-surface"])
def test_host_name_does_not_substitute_for_schema_and_qualification(essay, host):
    essay.p[0]["payload"].update(originator=host, cli_version="9.9.9")
    essay.write(essay.parent, essay.p)
    result = ce.preflight(root=essay.root, qualification=True)
    assert result["host"] == host
    assert result["driver"] == ce.NATIVE_DRIVER
    with pytest.raises(ce.EvidenceError, match="unverified"):
        ce.preflight(root=essay.root)


def test_legacy_birth_cannot_be_relabelled_as_another_host(essay):
    essay.complete()
    essay.p[0]["payload"]["originator"] = "codex-tui"
    essay.write(essay.parent, essay.p)
    with pytest.raises(ce.EvidenceError, match="host_mismatch"):
        essay.collect()


def test_divergent_evidence_fails_the_gate_in_a_new_version_too(essay):
    essay.complete()
    for rows, path in ((essay.p, essay.parent), (essay.c, essay.child)):
        rows[0]["payload"]["cli_version"] = "9.9.9"
    essay.c[2]["payload"].update(model="different")
    essay.write(essay.parent, essay.p)
    essay.write(essay.child, essay.c)
    with pytest.raises(ce.EvidenceError, match="observed_mismatch"):
        essay.collect()


def test_the_first_driver_id_names_the_same_schema_so_existing_births_and_qualifications_stay_valid(essay):
    essay.complete()
    legacy = "codex_exec/0.162.1/rollout-v1"
    assert legacy in ce.ACCEPTED_DRIVERS and legacy != ce.DRIVER
    birth = json.loads(essay.birth.read_text())
    birth.pop("integrity_sha256")
    birth["driver"] = legacy
    essay.birth.chmod(0o600)
    essay.birth.write_text(json.dumps(ce.sealed(birth)))
    result = essay.collect()
    assert result["driver"] == legacy and result["status"] == "completed"


def test_unverified_no_source_session_and_bad_destination(essay, monkeypatch):
    with pytest.raises(ce.EvidenceError, match="unverified"):
        ce.preflight(root=essay.root)
    with pytest.raises(ce.EvidenceError, match="unsafe_destination"):
        ce.preflight(root=essay.root, dest="../escape", qualification=True)
    monkeypatch.delenv("CODEX_THREAD_ID")
    with pytest.raises(ce.EvidenceError, match="session_unavailable"):
        ce.preflight(root=essay.root)
    monkeypatch.setenv("CODEX_THREAD_ID", "missing")
    with pytest.raises(ce.EvidenceError, match="source_unavailable"):
        ce.preflight(root=essay.root)


def test_temporarily_revoked_source_and_truncated_flush_recover_idempotently(essay, monkeypatch):
    essay.complete()
    original = essay.child.read_bytes()
    read_bytes = Path.read_bytes
    def denied(path):
        if path == essay.child:
            raise PermissionError("revoked")
        return read_bytes(path)
    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(ce.EvidenceError, match="source_unavailable"):
        essay.collect()
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    essay.child.write_bytes(original[:-1])
    with pytest.raises(ce.EvidenceError, match="source_truncated"):
        essay.collect()
    essay.child.write_bytes(original)
    proof = essay.collect()
    assert essay.collect()["integrity_sha256"] == proof["integrity_sha256"]
    assert len(list(essay.birth.parent.glob("*.evidence.json"))) == 1
    assert len(list(essay.birth.parent.glob("*.failure-*.json"))) == 2


def test_all_turns_original_birth_and_final_good_turn_cannot_erase_divergence(essay, machine_models):
    bad = {"model": "gpt-6-astra", "reasoning_effort": "medium"}
    essay.complete([("first", bad), ("last", essay.cap["arguments"])])
    with pytest.raises(ce.EvidenceError, match="observed_mismatch"):
        essay.collect()
    essay.c[2]["payload"].update(model="gpt-6-luna", effort="max")
    essay.write(essay.child, essay.c)
    doc = yaml.safe_load(machine_models.read_text())
    doc["clients"]["codex"]["execucao"].update(model="gpt-6.1-sol", effort="high")
    machine_models.write_text(yaml.safe_dump(doc))
    assert len(essay.collect()["turns"]) == 2
    edited = json.loads(essay.capture.read_text())
    edited["selection"]["model"] = "changed"
    essay.capture.chmod(0o600)
    essay.capture.write_text(json.dumps(edited))
    with pytest.raises(ce.EvidenceError, match="capture_changed"):
        essay.collect()


def test_unknown_turn_birth_conflict_source_conflict_and_integrity(essay):
    essay.complete()
    result = essay.collect()
    proof = Path(result["evidence_path"])
    altered = json.loads(proof.read_text())
    altered["status"] = "forged"
    proof.write_text(json.dumps(altered))
    with pytest.raises(ce.EvidenceError, match="integrity_mismatch"):
        ce.verify_evidence(proof)
    essay.p.insert(2, essay.row("turn_context", dict(essay.p[1]["payload"], turn_id="other-turn")))
    essay.write(essay.parent, essay.p)
    with pytest.raises(ce.EvidenceError, match="turn_mismatch"):
        essay.collect()


def test_conflicting_index_and_source_digest_tampering(essay):
    essay.complete()
    proof = essay.collect()
    # Changing an authoritative line changes the stable minimal extraction.
    essay.c[0]["payload"]["extra_field"] = "altered"
    essay.write(essay.child, essay.c)
    with pytest.raises(ce.EvidenceError, match="provenance_mismatch"):
        ce.verify_evidence(proof["evidence_path"])
    with sqlite3.connect(essay.home / "state_5.sqlite") as db:
        db.execute("INSERT INTO threads VALUES (?,?,?)", (essay.child_id, str(essay.child), essay.agent_path))
    with pytest.raises(ce.EvidenceError, match="source_conflict"):
        essay.collect()


def test_review_wave_receipt_requires_observed_parent_readonly(tmp_path, monkeypatch, machine_models):
    with pytest.raises(ce.EvidenceError, match="parent_sandbox_mismatch"):
        Essay(tmp_path, monkeypatch, role="diff-reviewer")


@pytest.mark.parametrize("qualification", [False, True])
def test_review_provenance_wave_sandbox_and_diff(tmp_path, monkeypatch, machine_models, qualification):
    from codex_proxy import record
    from codex_review import verify_wave, ReviewDiffError
    if not qualification:
        # Fixture-only qualification exercises the ordinary preflight path;
        # it makes no support claim for the actual host running these tests.
        qualifier = Essay(tmp_path, monkeypatch)
        with pytest.raises(ce.EvidenceError, match="birth_mismatch"):
            qualifier.collect()
        qualifier.complete()
        qualified = qualifier.collect()
        ce.qualify(qualified["evidence_path"], list(qualifier.birth.parent.glob("*.failure-*.json")))
    proofs = []
    for role in ("diff-reviewer", "code-reviewer"):
        e = Essay(tmp_path, monkeypatch, role=role, sandbox="read-only", wave="review-1095", qualification=True)
        if not qualification:
            # Rehearse a historical receipt, never mint a new stage receipt by
            # bypassing the missing-capability preflight in production code.
            birth = json.loads(e.birth.read_text())
            for key in ("integrity_sha256", "stage_contract", "stage_status", "work_release"):
                birth.pop(key, None)
            birth["qualification"] = False
            e.birth.write_text(json.dumps(ce.sealed(birth)))
        e.complete()
        if qualification:
            args = json.loads(e.p[-3]["payload"]["arguments"])
            args["agent_type"] = "qa-gate"
            e.p[-3]["payload"]["arguments"] = json.dumps(args)
            e.write(e.parent, e.p)
        proof = e.collect()
        args = dict(repo_root=e.root, activity=role, band="execucao", requested_model="gpt-6-luna", requested_effort="max", observed_model="gpt-6-luna", observed_effort="max", host="codex_exec", host_version="0.162.1", status="completed", payload_returned=True, child_id=e.child_id, bound_card="1095", sandbox_mode="read-only", review_diff_sha256="a" * 64, capture=e.cap, wave_id="review-1095", runtime_evidence=proof["evidence_path"])
        proofs.append(record(**args))
    if qualification:
        with pytest.raises(ReviewDiffError, match="qualification evidence cannot prove product review"):
            verify_wave(root=e.root, wave_id="review-1095", expected_sha256="a" * 64, bound_card="1095")
        return
    with pytest.raises(ReviewDiffError, match="dedicated principal/coordinator chain"):
        verify_wave(root=e.root, wave_id="review-1095", expected_sha256="a" * 64, bound_card="1095")
    proofs[0]["review_diff_sha256"] = "b" * 64
    log = e.root / ".cursor/tmp/codex-child-proxies.jsonl"
    log.write_text("".join(json.dumps(p) + "\n" for p in proofs))
    with pytest.raises(ReviewDiffError, match="expected diff"):
        verify_wave(root=e.root, wave_id="review-1095", expected_sha256="a" * 64, bound_card="1095")


def test_process_event_refuses_before_moving_and_ambiguous_client(essay, monkeypatch):
    from process_event import process_event
    state = dict(q="Todo", q_git="card-1095-fixture", bound_card="1095")
    called = []
    class Mover:
        def set_status(self, *args, **kwargs):
            called.append(args)
    result = process_event("iniciar_design", cwd=essay.root, card="1095", resolve_fn=lambda *a, **kw: state, mover=Mover())
    assert result["reason"] == "codex_evidence:unverified"
    assert not called
    result = process_event("iniciar_design", cwd=essay.root, card="1095", resolve_fn=lambda *a, **kw: state, client="cursor")
    assert result["reason"] == "codex_evidence:ambiguous_client"


def test_trusted_hook_rechecks_prepared_birth_and_current_session(essay, monkeypatch):
    import codex_adapter
    monkeypatch.setattr(codex_adapter, "_repo_root", lambda cwd: essay.root)
    args = dict(task_name=essay.task, fork_turns="none", **essay.cap["arguments"], message=f"model_selection_capture: {essay.capture}\nruntime_evidence_birth: {essay.birth}")
    request = {"tool_name": "Agent", "tool_input": args, "cwd": str(essay.root)}
    assert codex_adapter.pre_tool_use(request) is None
    monkeypatch.setenv("CODEX_THREAD_ID", "another-parent")
    assert "birth_mismatch" in codex_adapter.pre_tool_use(request)["hookSpecificOutput"]["permissionDecisionReason"]


def test_bounded_timeout_malformed_source_wrong_birth_and_schema(essay):
    essay.complete()
    original = essay.child.read_bytes()
    essay.child.write_bytes(b"not-json\n")
    with pytest.raises(ce.EvidenceError, match="source_malformed"):
        essay.collect()
    essay.child.write_bytes(original)
    with pytest.raises(ce.EvidenceError, match="invalid_wait"):
        ce.collect(essay.birth, wait_seconds=11)
    birth = json.loads(essay.birth.read_text())
    birth["attempt_id"] = "wrong-birth"
    birth = ce.sealed({k: v for k, v in birth.items() if k != "integrity_sha256"})
    with pytest.raises(ce.EvidenceError, match="birth_mismatch"):
        ce.extract(birth)
    birth["schema"] = "future-schema"
    birth = ce.sealed({k: v for k, v in birth.items() if k != "integrity_sha256"})
    with pytest.raises(ce.EvidenceError, match="unsupported_schema"):
        ce.extract(birth)


def test_readonly_preflight_performs_no_writes_and_failed_child_sandbox(essay, monkeypatch):
    essay.p[1]["payload"]["sandbox_policy"]["type"] = "read-only"
    essay.write(essay.parent, essay.p)
    destination = essay.birth.parent
    original = {p.name: p.read_bytes() for p in destination.iterdir()}
    access = ce.os.access
    monkeypatch.setattr(ce.os, "access", lambda path, mode: False if mode & ce.os.W_OK else access(path, mode))
    assert not ce.os.access(destination, ce.os.W_OK)
    def forbidden(*args, **kwargs):
        raise AssertionError("read-only preflight must not write")
    monkeypatch.setattr(ce.tempfile, "mkstemp", forbidden)
    monkeypatch.setattr(Path, "mkdir", forbidden)
    monkeypatch.setattr(ce.os, "chmod", forbidden)
    monkeypatch.setattr(ce, "private_write", forbidden)
    assert ce.preflight(root=essay.root, qualification=True, review=True)["parent_sandbox"] == "read-only"
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == original
    assert destination.stat().st_mode & 0o777 == 0o700


@pytest.mark.parametrize("problem,code", [
    ("missing", "destination_unwritable"),
    ("file", "destination_unwritable"),
    ("public", "unsafe_destination"),
    ("symlink", "unsafe_destination"),
    ("unreadable", "destination_unwritable"),
])
def test_readonly_preflight_refuses_unprepared_or_unsafe_destination(essay, monkeypatch, problem, code):
    essay.p[1]["payload"]["sandbox_policy"]["type"] = "read-only"
    essay.write(essay.parent, essay.p)
    target = essay.root / "review-evidence"
    if problem == "file":
        target.write_text("not a directory")
    elif problem == "symlink":
        target.symlink_to(essay.birth.parent, target_is_directory=True)
    elif problem != "missing":
        target.mkdir(mode=0o700)
        if problem == "public":
            target.chmod(0o755)
        else:
            scandir = ce.os.scandir
            def denied(path):
                if path == target:
                    raise PermissionError("review destination inspection denied")
                return scandir(path)
            monkeypatch.setattr(ce.os, "scandir", denied)
    def forbidden(*args, **kwargs):
        raise AssertionError("read-only preflight must not prepare destination")
    monkeypatch.setattr(ce.tempfile, "mkstemp", forbidden)
    with pytest.raises(ce.EvidenceError, match=code):
        ce.preflight(root=essay.root, dest=target, qualification=True, review=True)
    assert target.exists() == (problem != "missing")


@pytest.mark.parametrize("review", [False, True])
def test_writable_prepare_probes_destination_before_receipt(essay, monkeypatch, review):
    if review:
        essay.cap = resolve("codex", "execucao", role="diff-reviewer")
        essay.capture = essay.root / "review.capture.json"
        save_capture(essay.capture, essay.cap)
        essay.p[1]["payload"]["sandbox_policy"]["type"] = "read-only"
        essay.write(essay.parent, essay.p)
    original = essay.birth.read_bytes()
    probes = []
    def denied(*args, **kwargs):
        probes.append(kwargs["dir"])
        raise PermissionError("writable orchestrator destination permission revoked")
    monkeypatch.setattr(ce.tempfile, "mkstemp", denied)
    def forbidden(*args, **kwargs):
        raise AssertionError("failed destination probe must precede receipt persistence")
    monkeypatch.setattr(ce, "private_write", forbidden)
    with pytest.raises(ce.EvidenceError, match="destination_unwritable"):
        ce.prepare(root=essay.root, capture=essay.capture, task_name="new_birth", qualification=True, review_diff_sha256="a" * 64)
    assert probes == [essay.birth.parent]
    assert essay.birth.read_bytes() == original
    assert len(list(essay.birth.parent.glob("*.birth.json"))) == 1


def test_model_proxy_consumes_verified_birth_and_all_turns(essay):
    from model_proxy import evidence, verify_continuation
    essay.complete()
    result = essay.collect()
    args = dict(capture=essay.cap, observed={"model": "gpt-6-luna", "effort": "max"}, host="codex_exec", host_version="0.162.1", status="completed", payload_returned=True)
    assert not evidence(**args)["successful"]
    assert evidence(**args, runtime_evidence=result["evidence_path"])["successful"]
    assert verify_continuation(essay.cap, args["observed"], host=args["host"], host_version=args["host_version"], status=args["status"], payload_returned=True, runtime_evidence=result["evidence_path"])["successful"]


@pytest.mark.parametrize("host", ["codex-tui", "codex_app_server"])
def test_surface_requires_its_own_complete_native_qualification(tmp_path, monkeypatch, machine_models, host):
    e = Essay(tmp_path, monkeypatch, host=host)
    with pytest.raises(ce.EvidenceError, match="birth_mismatch"):
        e.collect()
    e.complete()
    proof = e.collect()
    assert proof["driver"] == ce.NATIVE_DRIVER
    assert proof["host"] == host
    ce.qualify(proof["evidence_path"], list(e.birth.parent.glob("*.failure-*.json")))
    assert ce.preflight(root=e.root)["result"] == "ready"
    # A different active surface cannot reuse this qualification.
    alternate = e.sessions / "alternate.jsonl"
    other_rows = [json.loads(json.dumps(row)) for row in e.p[:2]]
    other_rows[0]["payload"].update(id="alternate", originator="another-surface")
    e.write(alternate, other_rows)
    with sqlite3.connect(e.home / "state_5.sqlite") as db:
        db.execute("INSERT INTO threads VALUES (?,?,?)", ("alternate", str(alternate), "/root"))
    # Even a copied, intact qualification cannot qualify another surface.
    ce.qualification_path(e.birth.parent, "another-surface").write_bytes(
        ce.qualification_path(e.birth.parent, host).read_bytes())
    with pytest.raises(ce.EvidenceError, match="qualification belongs to another host surface"):
        ce.preflight(root=e.root, thread="alternate")


def test_native_rebind_uses_observed_active_turn_not_historical_session_cwd(essay):
    essay.p[0]["payload"]["cwd"] = "/historical-launch-directory"
    essay.write(essay.parent, essay.p)
    assert ce.preflight(root=essay.root, qualification=True)["result"] == "ready"
    # Neither the launch directory nor an arbitrary --root overrides the runtime turn.
    with pytest.raises(ce.EvidenceError, match="worktree_mismatch") as err:
        ce.preflight(root="/historical-launch-directory", qualification=True)
    assert "turn_cwd=" in err.value.detail
    assert "shell workdir alone" in err.value.recovery


@pytest.mark.parametrize("mutation,code", [
    (lambda e: e.c[2]["payload"].update(model="wrong"), "observed_mismatch"),
    (lambda e: e.c[2]["payload"].update(effort="wrong"), "observed_mismatch"),
    (lambda e: e.c[2]["payload"].update(cwd="/wrong"), "worktree_mismatch"),
    (lambda e: e.c[0]["payload"]["source"]["subagent"]["thread_spawn"].update(parent_thread_id="wrong"), "source_conflict"),
    (lambda e: e.c[3]["payload"].update(last_agent_message=""), "payload_unavailable"),
])
def test_interactive_surface_preserves_refusals(tmp_path, monkeypatch, machine_models, mutation, code):
    e = Essay(tmp_path, monkeypatch, host="codex-tui").complete()
    mutation(e)
    e.write(e.child, e.c)
    with pytest.raises(ce.EvidenceError, match=code):
        e.collect()


def test_interactive_review_still_requires_runtime_read_only(tmp_path, monkeypatch, machine_models):
    e = Essay(tmp_path, monkeypatch, host="codex-tui")
    with pytest.raises(ce.EvidenceError, match="parent_sandbox_mismatch"):
        ce.preflight(root=e.root, qualification=True, review=True)


def test_parent_worktree_binding_is_revalidated_during_collection(essay):
    essay.complete()
    essay.p[1]["payload"]["cwd"] = "/another-card"
    essay.write(essay.parent, essay.p)
    with pytest.raises(ce.EvidenceError, match="worktree_mismatch"):
        essay.collect()


def test_native_stage_preflight_refuses_unobserved_context_before_receipt(essay):
    with pytest.raises(ce.EvidenceError, match="birth_mismatch"):
        essay.collect()
    essay.complete()
    proof = essay.collect()
    ce.qualify(proof["evidence_path"], list(essay.birth.parent.glob("*.failure-*.json")))
    before = {p.name: p.read_bytes() for p in essay.birth.parent.iterdir()}
    with pytest.raises(ce.EvidenceError) as failure:
        ce.prepare(root=essay.root, capture=essay.capture, task_name="must_not_spawn")
    assert failure.value.code == "stage_capability_missing"
    assert "#1095" in str(failure.value) and "qa-gate" in str(failure.value)
    assert failure.value.observed["context_isolation"] == "unavailable"
    assert "barreira" in str(failure.value)
    assert {p.name: p.read_bytes() for p in essay.birth.parent.iterdir()} == before
    # Requested isolation and unrelated runtime metadata are not effective proof.
    essay.c[0]["payload"].update(history_mode="paginated", context_window={"window_id": "native-id"}, context_isolation="verified")
    essay.write(essay.child, essay.c)
    fresh = ce.extract(json.loads(essay.birth.read_text()))
    assert fresh["native_arguments"]["fork_turns"] == "none"
    assert fresh["capabilities"]["context_isolation"] == "unavailable"
    assert fresh["work_release"] == "diagnostic_only"


def test_new_birth_requires_actual_isolated_context_request_even_for_diagnostic(essay):
    essay.complete()
    args = json.loads(essay.p[2]["payload"]["arguments"])
    args["fork_turns"] = "all"
    essay.p[2]["payload"]["arguments"] = json.dumps(args)
    essay.write(essay.parent, essay.p)
    with pytest.raises(ce.EvidenceError, match="context_request_mismatch"):
        essay.collect()
    assert json.loads(next(essay.birth.parent.glob("*.failure-*.json")).read_text())["result"] == "failed"


def test_interruption_is_not_completed_or_blocked_before_spawn(essay):
    essay.complete()
    essay.c[-1] = essay.row("event_msg", {"type": "turn_aborted", "turn_id": "child-turn", "reason": "interrupted"})
    essay.write(essay.child, essay.c)
    with pytest.raises(ce.EvidenceError, match="child_interrupted"):
        essay.collect()
    assert json.loads(next(essay.birth.parent.glob("*.failure-*.json")).read_text())["result"] == "interrupted"
    assert not list(essay.birth.parent.glob("*.evidence.json"))


def test_declarative_readonly_and_probe_claims_never_satisfy_effective_review(essay):
    essay.complete()
    proof = essay.collect()
    proof.update(parent_sandbox="read-only", context_isolation="verified", review_diff_read=True,
                 review_write_denial_readback=True, sandbox_mode="read-only")
    proof["capabilities"] = {k: "verified" for k in proof["capabilities"]}
    with pytest.raises(ce.EvidenceError, match="context_isolation.*review_diff_read.*review_write_denial_readback"):
        ce.require_review_guarantees(proof)


def test_process_transition_preserves_state_when_native_stage_guarantee_is_missing(essay):
    from process_event import process_event
    with pytest.raises(ce.EvidenceError, match="birth_mismatch"):
        essay.collect()
    essay.complete()
    proof = essay.collect()
    ce.qualify(proof["evidence_path"], list(essay.birth.parent.glob("*.failure-*.json")))
    calls = []
    class Mover:
        def set_status(self, *args, **kwargs):
            calls.append((args, kwargs))
    state = dict(q="Todo", q_git="card-1095-fixture", bound_card="1095")
    result = process_event("iniciar_design", cwd=essay.root, card="1095", resolve_fn=lambda *a, **kw: state, mover=Mover())
    assert result["reason"] == "codex_evidence:stage_capability_missing"
    assert result["state"] == "Todo" and not calls


def test_another_thread_cannot_replace_same_chat_stage(essay):
    with pytest.raises(ce.EvidenceError, match="chat_binding_mismatch"):
        ce.preflight(root=essay.root, stage="qa-gate", thread="external-session")


def test_cli_interruption_uses_birth_identity_and_never_reports_prebirth_block(essay, monkeypatch, capsys):
    essay.complete()
    essay.c[-1] = essay.row("event_msg", {"type": "turn_aborted", "turn_id": "child-turn"})
    essay.write(essay.child, essay.c)
    monkeypatch.chdir(essay.home)
    assert ce.main(["collect", "--birth", str(essay.birth), "--wait-seconds", "0"]) == 2
    out = json.loads(capsys.readouterr().out)
    assert out["result"] == "interrupted" and out["bound_card"] == "1095"
    assert out["root"] == str(essay.root) and out["stage"] == "qa-gate"
    assert out["child_thread"] == essay.child_id and out["session"] == essay.parent_id

def t5_lifecycle_fixture(essay):
    with pytest.raises(ce.EvidenceError, match="birth_mismatch"):
        essay.collect()
    essay.complete()
    proof = essay.collect()
    ce.qualify(proof["evidence_path"], list(essay.birth.parent.glob("*.failure-*.json")))
    change = essay.root / "openspec" / "changes" / "card-1095-fixture"
    change.mkdir(parents=True)
    for name in ("proposal.md", "tasks.md"):
        (change / name).write_text("# fixture\n")
    (change / "design.md").write_text("UI impact: none\nlive_route: N/A harness-only\nsurface: new\n")
    spec = change / "specs" / "harness" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# fixture contract\n")
    return change


def t5_lifecycle_request(essay, change, mover):
    from process_event import process_event

    return process_event(
        "submeter_design", cwd=essay.root, card="1095", change="card-1095-fixture",
        status="Design", q_git="card-1095-fixture", bound_card="1095",
        change_dir=change, mover=mover, client="codex",
    )


def test_t5_uses_real_basic_preflight_without_qualifying_context_or_prepare(essay):
    from process_event import FakeMover, compute_digest, sidecar_path

    change = t5_lifecycle_fixture(essay)
    pf = ce.preflight(root=essay.root)
    assert pf["result"] == "ready"
    assert pf["capabilities"]["context_isolation"] == "unavailable"
    mover = FakeMover()
    out = t5_lifecycle_request(essay, change, mover)
    assert out["result"] == "transition" and out["reason"] == "T5"
    assert mover.calls == [(1095, "Aprovação de Design")]
    assert sidecar_path(change).read_text().strip() == compute_digest(change, None)
    births_before = set(essay.birth.parent.glob("*.birth.json"))
    with pytest.raises(ce.EvidenceError, match="stage_capability_missing"):
        ce.prepare(root=essay.root, capture=essay.capture, task_name="still_no_stage")
    assert set(essay.birth.parent.glob("*.birth.json")) == births_before
    # The lifecycle qualification did not become context evidence.
    assert ce.preflight(root=essay.root)["capabilities"]["context_isolation"] == "unavailable"


@pytest.mark.parametrize("fault,code", [
    ("qualification", "unverified"),
    ("worktree", "worktree_mismatch"),
    ("source", "source_unavailable"),
])
def test_t5_real_basic_preflight_refuses_missing_qualification_identity_or_source(essay, fault, code):
    from process_event import FakeMover, sidecar_path

    change = t5_lifecycle_fixture(essay)
    if fault == "qualification":
        ce.qualification_path(essay.birth.parent, essay.host).unlink()
    elif fault == "worktree":
        essay.p[1]["payload"]["cwd"] = "/other-card"
        essay.write(essay.parent, essay.p)
    else:
        essay.parent.unlink()
    mover = FakeMover()
    out = t5_lifecycle_request(essay, change, mover)
    assert out["result"] == "reject" and out["reason"] == "codex_evidence:" + code
    assert mover.calls == [] and not sidecar_path(change).exists()
