"""Scoped operational context qualification; never internal-context attestation.

Sources are the executing native runtime binary, its rollout and a completed
diagnostic birth. This module deliberately cannot decrypt native task messages.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import subprocess

SCHEMA = "codex-context-contract-v1"
TOOL = "collaboration.spawn_agent"
PROC_ROOT = Path("/proc")
FRAGMENTS = (
    b'Note that passing `fork_turns="none"` will not pass any surrounding context to the spawned subagent',
    b'Parent history to inherit. Defaults to `all`; use `none` to start without parent history. Only `all` and `none` are supported.',
    b'fork_context is not supported in MultiAgentV2; use fork_turns instead',
)


def ce():
    import codex_evidence
    return codex_evidence


def fail(code, detail=""):
    raise ce().EvidenceError(code, detail, recovery="run an explicit native diagnostic in the same chat; never substitute a declaration or external session")


def sha(value):
    return hashlib.sha256(value).hexdigest()


def text(payload):
    return "\n".join(c.get("text", "") for c in payload.get("content", []) if c.get("type") in {"input_text", "output_text"})


def ancestry_binary():
    """Find our actual native tool-process ancestor, not an arbitrary PATH binary.

    /proc/<pid>/exe is opened directly (also works for deleted executables).
    PID start time and inode are checked on both sides of reading/versioning.
    An inaccessible ancestor is not replaced by a candidate supplied by a user.
    """
    pid, seen = os.getpid(), set()
    while pid and pid not in seen:
        seen.add(pid)
        proc = PROC_ROOT / str(pid)
        try:
            status = proc.joinpath("status").read_text()
            parent = int(next(x.split()[1] for x in status.splitlines() if x.startswith("PPid:")))
            executable = os.readlink(proc / "exe")
            if Path(executable.removesuffix(" (deleted)")).name == "codex":
                def identity():
                    start = proc.joinpath("stat").read_text().rpartition(") ")[2].split()[19]
                    stat = (proc / "exe").stat()
                    return (start, stat.st_dev, stat.st_ino, os.readlink(proc / "exe"))
                before = identity()
                data = proc.joinpath("exe").read_bytes()
                version = subprocess.run([str(proc / "exe"), "--version"], check=True, capture_output=True, text=True, timeout=10).stdout.strip()
                if identity() != before:
                    fail("context_runtime_changed", "ancestor executable changed during collection")
                if not re.fullmatch(r"codex-cli \S+", version):
                    fail("context_contract_unavailable", "native ancestor version is not observable")
                fragments = []
                for fragment in FRAGMENTS:
                    offset = data.find(fragment)
                    if offset == -1:
                        fail("context_contract_unavailable", "native executable lacks the documented context contract")
                    fragments.append({"offset": offset, "length": len(fragment), "sha256": sha(fragment)})
                return {"source": str(proc / "exe"), "pid": pid, "starttime": before[0], "device": before[1], "inode": before[2], "executable": executable, "binary_sha256": sha(data), "version": version, "fragments": fragments}
            pid = parent
        except ce().EvidenceError:
            raise
        except (OSError, ValueError, IndexError, StopIteration, subprocess.SubprocessError) as exc:
            fail("context_contract_unavailable", f"cannot verify native ancestry: {type(exc).__name__}")
    fail("context_contract_unavailable", "native runtime ancestor absent")


def contract(runtime, session):
    path, rows, meta, turns = runtime.session(session)
    turn = turns[-1]
    if turn.get("multi_agent_version") != "v2":
        fail("context_contract_unavailable", "runtime does not identify native multi-agent v2")
    instructions = []
    refs = []
    for ordinal, row, raw_sha in rows:
        value = row["payload"]
        if row["type"] == "response_item" and value.get("type") == "message" and value.get("role") == "developer":
            for line in text(value).splitlines():
                if "fork_turns" in line and "Full-history forks" in line and '"none"' in line:
                    instructions.append(line)
                    refs.append({"source": str(path), "ordinal": ordinal, "raw_sha256": raw_sha})
    if not instructions:
        fail("context_contract_unavailable", "native runtime fork contract instruction absent")
    binary = ancestry_binary()
    if binary["version"].removeprefix("codex-cli ") != meta["cli_version"]:
        fail("context_runtime_mismatch", "executing native ancestor and rollout version differ")
    scope = {"host": meta["originator"], "tool": TOOL, "multi_agent_version": "v2", "binary_sha256": binary["binary_sha256"], "instruction_sha256": sha("\n".join(sorted(set(instructions))).encode()), "contract_schema": SCHEMA}
    return {"scope": scope, "scope_sha256": ce().digest(scope), "runtime_binary": binary, "runtime_instructions": refs, "host_version": meta["cli_version"], "internal_context_attestation": "unavailable"}


def qualification_path(out, session, attempt):
    # Immutable attempts permit requalification without deleting old evidence.
    return Path(out) / f"context-qualification-{sha(session.encode())[:16]}-{attempt}.json"


def plan_path(birth):
    return Path(birth).with_suffix(".context-plan.json")


def prompt(control, capture, birth):
    return ("Nonsecret context diagnostic only. Do not use tools, files, environment, other agents or external messages. "
            "Return exactly one JSON object with keys control and sentinel. Copy the control exactly. "
            "If a context_sentinel was actually supplied in your received context, put its exact value in sentinel; "
            "otherwise set sentinel to null. Do not guess. No product work.\n"
            f"control: {control}\nmodel_selection_capture: {capture}\nruntime_evidence_birth: {birth}")


def read_sentinel(rows, ordinal):
    found = [row for i, row, raw_sha in rows if i == ordinal]
    if len(found) != 1:
        fail("context_sentinel_source_unavailable")
    row = found[0]
    value = row["payload"]
    if row["type"] != "response_item" or value.get("type") != "message" or value.get("role") not in {"user", "assistant"}:
        fail("context_sentinel_source_unavailable", "sentinel must be in earlier parent-only conversation")
    matches = re.findall(r"^context_sentinel: ([A-Za-z0-9_-]{24,128})$", text(value), re.MULTILINE)
    if len(matches) != 1:
        fail("context_sentinel_source_unavailable", "expected exactly one nonsecret sentinel marker")
    return matches[0]


def check_new_sentinel(rows, ordinal, session):
    sentinel = read_sentinel(rows, ordinal)
    source = next(row["payload"] for i, row, raw_sha in rows if i == ordinal)

    def same_native_message(i, row):
        # TUI emits the completed item immediately before its response_item.
        # Normalize only the observed Text/output_text representation, never
        # content from an unrelated prior message or a loose string match.
        value = row["payload"]
        item = value.get("item", {})
        if i != ordinal - 1 or row["type"] != "event_msg" or value.get("type") != "item_completed" or value.get("thread_id") != session:
            return False
        if source.get("role") != "assistant" or item.get("type") != "AgentMessage" or not item.get("id") or item.get("id") != source.get("id"):
            return False
        turn = source.get("internal_chat_message_metadata_passthrough", {}).get("turn_id")
        if not turn or turn != value.get("turn_id") or "phase" not in source or item.get("phase") != source["phase"]:
            return False
        completed, recorded = item.get("content"), source.get("content")
        return (isinstance(completed, list) and isinstance(recorded, list) and bool(completed)
                and len(completed) == len(recorded)
                and all(isinstance(a, dict) and isinstance(b, dict)
                        and a.get("type") == "Text" and b.get("type") == "output_text"
                        and isinstance(a.get("text"), str) and a["text"] == b.get("text")
                        for a, b in zip(completed, recorded)))

    for i, row, raw_sha in rows:
        if i < ordinal and sentinel in json.dumps(row, ensure_ascii=False) and not same_native_message(i, row):
            fail("context_markers_invalid", "sentinel must be new in the parent context")
    return sentinel


def inspect(*, root, qualification=False, runtime=None, sentinel=False):
    if not qualification:
        fail("context_diagnostic_required")
    rt = runtime or ce().Rollout()
    pf = ce().preflight(root=root, qualification=True, runtime=rt)
    doc = contract(rt, pf["session"])
    result = {"result": "ready", "session": pf["session"], "parent_turn": pf["parent_turn"], "contract": doc}
    if sentinel:
        source, rows, meta, turns = rt.session(pf["session"])
        matches = []
        for i, row, raw_sha in rows:
            try:
                read_sentinel(rows, i)
                matches.append(i)
            except ce().EvidenceError:
                pass
        if not matches:
            fail("context_sentinel_source_unavailable")
        result["sentinel_record"] = matches[-1]
    return result


def prepare(*, root, capture, task_name, sentinel_record, qualification=False, runtime=None):
    if not qualification:
        fail("context_diagnostic_required", "context-prepare requires explicit --qualification")
    rt = runtime or ce().Rollout()
    session = os.environ.get("CODEX_THREAD_ID")
    pf = ce().preflight(root=root, capture=capture, qualification=True, runtime=rt)
    doc = contract(rt, session)
    source, rows, meta, turns = rt.session(session)
    sentinel = check_new_sentinel(rows, sentinel_record, session)
    if sentinel in str(Path(root)) or sentinel in str(capture) or sentinel in task_name or sentinel in Path(capture).read_text():
        fail("context_contaminated", "sentinel cannot enter paths, titles or selection capture")
    # No sentinel value is passed to prepare, stored in a capture, or emitted.
    control = secrets.token_hex(24)
    if control == sentinel:
        fail("context_markers_invalid")
    result = ce().prepare(root=root, capture=capture, task_name=task_name, qualification=True, runtime=rt, context_diagnostic=True)
    birth = Path(result["birth"])
    message = prompt(control, str(Path(capture).resolve()), str(birth))
    reference = next({"source": str(source), "ordinal": i, "raw_sha256": raw_sha} for i, row, raw_sha in rows if i == sentinel_record)
    plan = ce().sealed({"schema": SCHEMA, "birth": str(birth), "root": str(Path(root).resolve()), "parent_thread": session, "parent_turn": pf["parent_turn"], "contract": doc, "sentinel_source": reference, "sentinel_sha256": sha(sentinel.encode()), "control_sha256": sha(control.encode()), "prompt_sha256": sha(message.encode()), "requested_message": message, "request_observation": "requested", "source_records": pf["source_records"]})
    ce().private_write(plan_path(birth), plan)
    return dict(result, context_plan=str(plan_path(birth)), message=message, fork_turns="none")


def verify_plan(plan_file, *, runtime=None):
    rt = runtime or ce().Rollout()
    plan = ce().check_seal(json.loads(Path(plan_file).read_text()))
    if plan.get("schema") != SCHEMA:
        fail("context_plan_mismatch")
    source_birth = ce().check_seal(json.loads(Path(plan["birth"]).read_text()))
    birth = source_birth
    if plan.get("dedicated_bootstrap"):
        from codex_review_session import resolve_envelope
        birth = resolve_envelope(source_birth, runtime=rt)
    if not birth["qualification"] or birth["work_release"] != "diagnostic_only" or any(plan[k] != birth[k] for k in ("root", "parent_thread", "parent_turn")):
        fail("context_plan_mismatch")
    if plan["source_records"] != birth["before_record"] or plan["contract"]["scope_sha256"] != ce().digest(plan["contract"]["scope"]):
        fail("context_plan_mismatch")
    proof = ce().extract(source_birth, runtime=rt)
    source, rows, meta, turns = rt.session(plan["parent_thread"])
    if plan.get("dedicated_bootstrap"):
        from codex_review_session import contract_observation
        actual_contract = contract_observation(plan["dedicated_bootstrap"], runtime=rt)
    else:
        actual_contract = contract(rt, plan["parent_thread"])
    if actual_contract["scope"] != plan["contract"]["scope"]:
        fail("context_scope_mismatch")
    for ref in plan["contract"]["runtime_instructions"]:
        if ref["source"] != str(source) or not any(i == ref["ordinal"] and raw_sha == ref["raw_sha256"] for i, row, raw_sha in rows):
            fail("context_source_changed", "native contract instruction source changed")
    reference = plan["sentinel_source"]
    if str(source) != reference["source"] or reference["ordinal"] >= birth["before_record"]:
        fail("context_sentinel_source_unavailable")
    if not any(i == reference["ordinal"] and raw_sha == reference["raw_sha256"] for i, row, raw_sha in rows):
        fail("context_source_changed", "sentinel source changed")
    sentinel = check_new_sentinel(rows, reference["ordinal"], plan["parent_thread"])
    if sha(sentinel.encode()) != plan["sentinel_sha256"]:
        fail("context_source_changed")
    calls = [r["payload"] for i, r, s in rows if r["type"] == "response_item" and r["payload"].get("type") == "function_call" and r["payload"].get("call_id") == proof["call_id"]]
    if len(calls) != 1:
        fail("context_call_mismatch")
    arguments = json.loads(calls[0]["arguments"])
    if arguments.get("fork_turns") != "none":
        fail("context_request_mismatch")
    # The native host encrypts task text before persisting the call. The local
    # request is REQUESTED only. The actual returned control is the independent
    # observation; neither this request nor ciphertext attests internal context.
    message = plan.get("requested_message")
    if plan.get("request_observation") != "requested" or not isinstance(message, str) or sha(message.encode()) != plan["prompt_sha256"]:
        fail("context_plan_mismatch")
    native_message = arguments.get("message")
    opaque = isinstance(native_message, str) and re.fullmatch(r"gAAAA[A-Za-z0-9_-]{50,}={0,2}", native_message) is not None
    if native_message != message and not opaque:
        fail("context_request_mismatch", "readable native message differs from the captured request")
    controls = re.findall(r"^control: ([0-9a-f]{48})$", message, re.MULTILINE)
    if len(controls) != 1 or sha(controls[0].encode()) != plan["control_sha256"] or sha(sentinel.encode()) == plan["control_sha256"]:
        fail("context_control_mismatch")
    if sentinel in message or message != prompt(controls[0], birth["capture_path"], plan["birth"]):
        fail("context_contaminated")
    for i, row, raw_sha in rows:
        value = row["payload"]
        if i >= birth["before_record"] and row["type"] == "response_item" and value.get("type") == "function_call" and value.get("namespace") == "collaboration" and value.get("name") in {"send_message", "followup_task"}:
            try:
                target = json.loads(value["arguments"]).get("target")
            except (ValueError, KeyError, TypeError):
                fail("context_essay_incomplete", "unreadable steering source")
            if target in {proof["child_thread"], proof["child_path"], birth["task_name"]}:
                fail("context_contaminated", "diagnostic child received additional steering")
        if i > reference["ordinal"] and row["type"] == "response_item" and value.get("type") in {"function_call", "custom_tool_call"} and sentinel in json.dumps(value, ensure_ascii=False):
            fail("context_contaminated", "sentinel entered a tool/file/message channel")
    child_source, child, child_meta, child_turns = rt.session(proof["child_thread"])
    if child_meta["originator"] != meta["originator"] or len(proof["turns"]) != 1 or len(child_turns) != 1:
        fail("context_essay_incomplete", "one completed diagnostic child turn on the same host is required")
    # Reject every tool/retrieval route, including opaque custom/native calls.
    received = []
    payloads = []
    child_refs = []
    for i, row, raw_sha in child:
        value = row["payload"]
        kind = value.get("type")
        if row["type"] == "response_item" and isinstance(kind, str) and ("_call" in kind or kind == "tool_response"):
            fail("context_contaminated", "diagnostic child executed a tool")
        if row["type"] == "response_item" and kind not in {"message", "agent_message", "reasoning"}:
            fail("context_essay_incomplete", "unsupported child response schema")
        item = value.get("item", {})
        if isinstance(item, dict) and item.get("type") in {"commandExecution", "fileChange", "mcpToolCall", "webSearch", "collabAgentToolCall", "function_call", "custom_tool_call"}:
            fail("context_contaminated", "diagnostic lifecycle records a tool action")
        if sentinel in json.dumps(row, ensure_ascii=False) and not (row["type"] == "event_msg" and kind == "task_complete"):
            fail("context_contaminated", "sentinel appears in child source")
        if row["type"] == "response_item" and (kind == "agent_message" or (kind == "message" and value.get("role") == "user")):
            contents = value.get("content", [])
            incoming = text(value)
            encrypted = [c for c in contents if c.get("type") == "encrypted_content"]
            if any(c.get("type") not in {"input_text", "encrypted_content"} for c in contents):
                fail("context_essay_incomplete", "unsupported child input schema")
            if encrypted:
                expected = f"Message Type: NEW_TASK\nTask name: {proof['child_path']}\nSender: {meta.get('agent_path', '/root')}\nPayload:\n"
                if not opaque or kind != "agent_message" or len(encrypted) != 1 or incoming != expected:
                    fail("context_contaminated", "opaque input is not the single native diagnostic task")
                received.append("native_encrypted_task")
                child_refs.append({"source": str(child_source), "ordinal": i, "raw_sha256": raw_sha})
                continue
            if "Message Type: NEW_TASK\n" in incoming and "\nPayload:\n" in incoming:
                incoming = incoming.split("\nPayload:\n", 1)[1]
            # AGENTS/environment user context precedes the task; require its
            # complete plaintext visibility but do not interpret it as the task.
            if kind == "agent_message" or incoming == message:
                received.append(incoming)
        if row["type"] == "event_msg" and kind == "task_complete":
            payloads.append(value.get("last_agent_message"))
        child_refs.append({"source": str(child_source), "ordinal": i, "raw_sha256": raw_sha})
    if received != (["native_encrypted_task"] if opaque else [message]) or len(payloads) != 1:
        fail("context_essay_incomplete", "exact single delivered diagnostic task and payload required")
    try:
        answer = json.loads(payloads[0])
    except (ValueError, TypeError):
        fail("context_essay_incomplete", "diagnostic payload must be the requested JSON object")
    if not isinstance(answer, dict) or set(answer) != {"control", "sentinel"} or answer["control"] != controls[0]:
        fail("context_control_mismatch")
    if answer["sentinel"] is not None:
        fail("context_sentinel_leaked" if answer["sentinel"] == sentinel else "context_essay_incomplete")
    return {"schema": SCHEMA, "result": "passed", "scope": plan["contract"]["scope"], "scope_sha256": plan["contract"]["scope_sha256"], "parent_thread": proof["parent_thread"], "parent_turn": proof["birth"]["parent_turn"], "child_thread": proof["child_thread"], "child_path": proof["child_path"], "call_id": proof["call_id"], "attempt_id": proof["attempt_id"], "capture_sha256": ce().digest(birth["capture"]), "control_sha256": plan["control_sha256"], "sentinel_sha256": plan["sentinel_sha256"], "payload_sha256": proof["payload_sha256"], "sentinel_source": reference, "lifecycle_sources": proof["sources"], "native_arguments": {"fork_turns": "none"}, "native_message_sha256": sha(native_message.encode()), "request_observation": "requested", "native_task_text": "opaque" if opaque else "readable", "child_sources": child_refs, "internal_context_attestation": "unavailable", "limitation": "documented contract, requested prompt and observed control/payload with no observed contaminating channel; opaque task text and complete internal context are not attested; no universal guarantee"}


def qualify(plan_file, *, runtime=None):
    result = verify_plan(plan_file, runtime=runtime)
    plan = ce().check_seal(json.loads(Path(plan_file).read_text()))
    if plan.get("dedicated_bootstrap"):
        from codex_review_session import read_package, require_principal
        require_principal(read_package(plan["dedicated_bootstrap"]), runtime=runtime)
    receipt = ce().sealed({"schema": SCHEMA, "plan": str(Path(plan_file).resolve()), "plan_sha256": plan["integrity_sha256"], "observation": result})
    target = qualification_path(Path(plan["birth"]).parent, result["parent_thread"], result["attempt_id"])
    ce().private_write(target, receipt)
    return dict(result, qualification_path=str(target))


def diagnostic_parent(package, *, runtime):
    """Locate an old attempt by immutable native launch, not today's helpers.

    Discovery must survive installing new helper bytes. This only establishes
    the historical parent for ordering; verify_plan still revalidates every
    current artifact and permission before accepting the selected success.
    """
    from codex_review_session import SCHEMA as REVIEW_SCHEMA, native_command, _verify_launch_output
    path = Path(package["bootstrap"]).resolve()
    bootstrap = ce().check_seal(json.loads(path.read_text()))
    if (bootstrap.get("schema") != REVIEW_SCHEMA or bootstrap.get("phase") != "bootstrap"
            or bootstrap.get("root") != package["root"]
            or bootstrap["integrity_sha256"] != package.get("bootstrap_sha256")):
        fail("context_qualification_mismatch", "diagnostic bootstrap identity mismatch")
    cmd = shlex.join([bootstrap["interpreter"], "-I", bootstrap["helper"], "launch", "--package", str(path)])
    output, _ = native_command(runtime, bootstrap["principal_thread"], cmd,
        bootstrap["root"], after=bootstrap["before_record"])
    parent = _verify_launch_output(path, bootstrap, output)
    _, _, meta, _ = runtime.session(parent)
    if parent == bootstrap["principal_thread"] or meta.get("originator") != "codex_exec" or Path(meta["cwd"]).resolve() != Path(package["root"]):
        fail("context_qualification_mismatch", "diagnostic native parent mismatch")
    return parent


def latest_diagnostic(*, root, out, session, runtime):
    """Order all attempts, including incomplete ones, by their native source.

    No receipt filename/mtime, UUID or success-only list is an ordering source.
    Births carry a diagnostic marker before plan creation; legacy plans and
    dedicated context packages remain discoverable without rewriting evidence.
    """
    root, out = Path(root).resolve(), Path(out).resolve()
    _, rows, _, _ = runtime.session(session)
    plans, births = {}, set()
    for path in out.glob("*.context-plan.json"):
        value = json.loads(path.read_text())
        if value.get("parent_thread") != session or Path(value.get("root", "/")) != root:
            continue
        plan = ce().check_seal(value)
        birth = Path(plan["birth"]).resolve()
        if birth in plans:
            fail("context_qualification_mismatch", "duplicate diagnostic plans")
        plans[birth] = (path.resolve(), plan)
        births.add(birth)
    for path in out.glob("*.json"):
        value = json.loads(path.read_text())
        if value.get("schema") != ce().SCHEMA or value.get("root") != str(root) or not value.get("qualification"):
            continue
        diagnostic = value.get("context_diagnostic") == SCHEMA
        if not diagnostic and value.get("envelope_state") == "pending_coordinator" and value.get("dedicated_package"):
            package = ce().check_seal(json.loads(Path(value["dedicated_package"]).read_text()))
            diagnostic = package.get("phase") == "context"
        if diagnostic:
            births.add(path.resolve())
    # Legacy ordinary births did not have a kind marker. A visible native task
    # identifies them even if their plan was lost. Never decrypt opaque tasks.
    calls = []
    for ordinal, row, _ in rows:
        v = row["payload"]
        if row["type"] != "response_item" or v.get("type") != "function_call" or v.get("name") != "spawn_agent":
            continue
        args = json.loads(v["arguments"])
        calls.append((ordinal, args))
        message = args.get("message", "")
        if message.startswith("Nonsecret context diagnostic only."):
            found = re.findall(r"^runtime_evidence_birth: (.+)$", message, re.M)
            if len(found) != 1:
                fail("context_qualification_mismatch", "native diagnostic birth missing")
            births.add(Path(found[0]).resolve())
    attempts, chains = [], {}
    for path in births:
        birth = ce().check_seal(json.loads(path.read_text()))
        if birth.get("envelope_state") == "pending_coordinator":
            package = ce().check_seal(json.loads(Path(birth["dedicated_package"]).read_text()))
            bootstrap = package["bootstrap"]
            if bootstrap not in chains:
                chains[bootstrap] = diagnostic_parent(package, runtime=runtime)
            chain = chains[bootstrap]
            if chain != session:
                continue
            if (package.get("phase") != "context" or package.get("root") != str(root)
                    or package.get("coordinator_before_record") != birth.get("before_record")
                    or str(path) not in package.get("births", [])
                    or package["files"].get(str(path)) != ce().digest(path.read_bytes())):
                fail("context_qualification_mismatch", "context package/birth mismatch")
            # Identification of a prepared attempt does not assert its launch
            # completed. verify_plan later requires the full native chain.
            birth = dict(birth, parent_thread=session, parent_turn="deferred_native_read_only")
        if birth.get("parent_thread") != session or Path(birth.get("root", "/")) != root:
            continue
        before = birth.get("before_record")
        if not birth.get("qualification") or birth.get("work_release") != "diagnostic_only" or type(before) is not int or not 0 <= before <= len(rows):
            fail("context_qualification_mismatch", "diagnostic birth/source mismatch")
        plan_path, plan = plans.get(path, (None, None))
        if plan is not None and (plan.get("schema") != SCHEMA or plan.get("source_records") != before
                or any(plan.get(k) != birth.get(k) for k in ("root", "parent_thread", "parent_turn"))):
            fail("context_qualification_mismatch", "diagnostic plan/birth mismatch")
        native = [ordinal for ordinal, args in calls if ordinal >= before and args.get("task_name") == birth["task_name"]]
        if len(native) > 1:
            fail("context_qualification_mismatch", "duplicate diagnostic native calls")
        attempts.append((max([before, *native]), before, path, birth, plan_path, plan))
    if not attempts:
        fail("context_qualification_missing")
    attempts.sort(key=lambda value: value[:2])
    if len(attempts) > 1 and attempts[-1][:2] == attempts[-2][:2]:
        fail("context_qualification_mismatch", "ambiguous latest diagnostic")
    return attempts[-1][3:]


def verify_qualification(*, root, out, session, runtime=None, expected_path=None):
    rt = runtime or ce().Rollout()
    birth, plan_file, plan = latest_diagnostic(root=root, out=out, session=session, runtime=rt)
    if plan is None:
        fail("context_qualification_missing", "latest diagnostic has no valid plan")
    path = qualification_path(out, session, birth["attempt_id"])
    if expected_path and Path(expected_path).resolve() != path.resolve():
        fail("context_qualification_mismatch", "expected receipt is not the latest diagnostic")
    if not path.is_file():
        fail("context_qualification_missing", "latest diagnostic has not qualified; no fallback to an older success")
    receipt = ce().check_seal(json.loads(path.read_text()))
    if receipt.get("schema") != SCHEMA or Path(receipt["plan"]).resolve() != plan_file or plan["integrity_sha256"] != receipt["plan_sha256"]:
        fail("context_qualification_mismatch")
    fresh = verify_plan(plan_file, runtime=rt)
    if path.resolve() != qualification_path(out, session, fresh["attempt_id"]).resolve():
        fail("context_qualification_mismatch")
    if fresh != receipt["observation"]:
        fail("context_source_changed", "accepted diagnostic source changed or child continued")
    return dict(fresh, qualification_path=str(path.resolve()))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("inspect")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--qualification", action="store_true")
    p.add_argument("--sentinel", action="store_true")
    p = sub.add_parser("prepare")
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--capture", required=True, type=Path)
    p.add_argument("--task-name", required=True)
    p.add_argument("--sentinel-record", required=True, type=int)
    p.add_argument("--qualification", action="store_true")
    for command in ("verify", "qualify"):
        p = sub.add_parser(command)
        p.add_argument("--plan", required=True, type=Path)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command in {"inspect", "prepare"}:
            result = (prepare if command == "prepare" else inspect)(**args)
        else:
            result = (qualify if command == "qualify" else verify_plan)(args["plan"])
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ce().EvidenceError, OSError, ValueError, KeyError) as exc:
        code = getattr(exc, "code", "context_source_unavailable")
        failed = code in {"context_sentinel_leaked", "context_contaminated", "context_request_mismatch", "context_control_mismatch", "context_scope_mismatch", "context_source_changed"}
        print(json.dumps({"result": "failed" if failed else "incomplete", "code": code, "detail": str(exc), "internal_context_attestation": "unavailable"}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
