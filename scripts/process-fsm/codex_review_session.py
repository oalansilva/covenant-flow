"""Dedicated read-only Codex Review: immutable preparation and source-bound binding.

Only the writable principal persists artifacts. Bootstrap/context/probe are explicit
diagnostics, never product review. Rollouts and native command records are reread;
pending envelopes, launcher JSON and TOML declarations are not final evidence.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import subprocess
import sys
import time
from urllib.parse import unquote, urlparse

# Preflight runs in a read-only coordinator. Importing its dependencies must
# not even attempt a best-effort bytecode cache write.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
for ancestor in Path(__file__).resolve().parents:
    adapter = ancestor / "scripts/process-fsm"
    if (ancestor / ".cursor/process-fsm.yaml").is_file() and (adapter / "model_selection.py").is_file():
        if str(adapter) not in sys.path:
            sys.path.append(str(adapter))
        break

import codex_evidence as ce
import codex_context as cc
from model_selection import resolve, save_capture, load_capture, validate_capture, compare_wave

SCHEMA = "codex-dedicated-review-v1"
ROLES = ("diff-reviewer", "code-reviewer")
PHASES = ("bootstrap", "context", "probe", "review")
STAGE_SCHEMA = "codex-review-stage-v1"
STAGE_MAX_AGE_MS = 120_000
# Explicitly classified metadata only. Unknown settings remain fail-closed.
# The original values/rows and their source digests are never normalized away.
NON_AUTHORIZING_SETTINGS = frozenset({"service_tier"})


def fail(code, detail=""):
    raise ce.EvidenceError(code, detail, recovery="preserve artifacts; qualify the native dedicated route without product work or permission toggles")


def inside(root, path):
    from codex_review_probe import inside as checked
    return checked(root, path)


def read_package(path):
    package = ce.check_seal(json.loads(Path(path).read_text()))
    if package.get("schema") != SCHEMA or package.get("state") != "pending_native_launch" or package.get("phase") not in PHASES:
        fail("review_package_invalid")
    root = Path(package["root"])
    inside(root, path)
    for name in ("events", "stderr", "prompt", "helper"):
        inside(root, package[name])
    for name, expected in package["files"].items():
        source = inside(root, name)
        if ce.digest(source.read_bytes()) != expected:
            fail("review_package_changed", name)
    for name in ("binary", "interpreter"):
        if ce.digest(Path(package[name]).read_bytes()) != package[name + "_sha256"]:
            fail("review_launcher_changed", name)
    cap = validate_capture(load_capture(package["coordinator_capture"]), client="codex", band="execucao")
    if cap != package["coordinator_selection"]:
        fail("capture_changed")
    return package


def command(path, action="launch"):
    p = read_package(path)
    return shlex.join([p["interpreter"], "-I", p["helper"], action, "--package", str(Path(path).resolve())])


def _cwd(value):
    parsed = urlparse(value)
    return Path(unquote(parsed.path) if parsed.scheme == "file" and not parsed.netloc else value).resolve()


def native_command(runtime, session, expected, root, *, after=0, before=None, required_exit=0):
    source, rows, meta, turns = runtime.session(session)
    matches = []
    turn = None
    for i, row, sha in rows:
        v = row["payload"]
        if row["type"] == "turn_context":
            turn = v["turn_id"]
        item = v.get("item", {})
        if i < after or before is not None and i >= before or row["type"] != "event_msg" or v.get("type") != "item_completed" or item.get("type") != "CommandExecution":
            continue
        argv = item.get("command")
        if not isinstance(argv, list) or len(argv) != 3 or argv[0] not in {"/bin/bash", "/usr/bin/bash"} or argv[1] not in {"-lc", "-c"} or argv[2] != expected:
            continue
        if v.get("thread_id") != session or v.get("turn_id") != turn or _cwd(item.get("cwd", "")) != Path(root).resolve() or item.get("status") != ("completed" if required_exit == 0 else "failed") or item.get("exit_code") != required_exit or item.get("source") not in {"unified_exec_startup", "unified_exec_poll"} or not item.get("id"):
            # An intact failed preflight is evidence of its specific failure,
            # not malformed launch provenance. Keep that diagnosis visible.
            argv = shlex.split(expected)
            if (len(argv) == 6 and argv[1] == "-I" and argv[2] == str(Path(__file__).resolve())
                    and argv[3] in {"preflight", "stage-check"} and argv[4] == "--package" and command(argv[5], argv[3]) == expected
                    and item.get("status") == "failed" and item.get("exit_code") == 1
                    and v.get("thread_id") == session and v.get("turn_id") == turn
                    and _cwd(item.get("cwd", "")) == Path(root).resolve()
                    and item.get("source") in {"unified_exec_startup", "unified_exec_poll"} and item.get("id")):
                try:
                    failure = json.loads(item["aggregated_output"])
                except (ValueError, TypeError, KeyError):
                    failure = {}
                if isinstance(failure, dict) and isinstance(failure.get("code"), str) and failure["code"]:
                    fail(failure["code"], "native " + argv[3] + ": " + str(failure.get("detail", "")))
            fail("review_launch_source_invalid")
        try:
            output = json.loads(item["aggregated_output"])
        except (ValueError, TypeError, KeyError):
            fail("review_launch_output_invalid")
        matches.append((output, {"source": str(source), "ordinal": i, "raw_sha256": sha, "command_id": item["id"], "turn_id": turn}))
    if len(matches) != 1:
        fail("review_launch_source_unavailable", "one intact native CommandExecution is required")
    return matches[0]


def _readonly_profile():
    # The managed profile below is observed in exec 0.163.0. Unknown forms are
    # not inferred from the profile's name or from the requested sandbox flag.
    return {"type": "managed", "file_system": {"type": "restricted", "entries": [
        {"path": {"type": "special", "value": {"kind": "root"}}, "access": "read"}]},
        "network": "restricted"}


def _settings_match_turn(settings, turn, package):
    fields = {"model", "model_provider_id", "service_tier", "approval_policy", "approvals_reviewer",
              "permission_profile", "cwd", "runtime_workspace_roots", "reasoning_effort",
              "collaboration_mode", "disabled_plugin_ids"}
    if not isinstance(settings, dict) or set(settings) != fields:
        fail("review_coordinator_settings_changed", "unknown or incomplete native settings schema")
    pair = package["coordinator_selection"]["arguments"]
    collaboration = {"mode": "default", "settings": {"model": pair["model"],
        "reasoning_effort": pair["reasoning_effort"], "developer_instructions": None}}
    root = Path(package["root"])
    if (settings["model"] != pair["model"] or settings["reasoning_effort"] != pair["reasoning_effort"]
            or not isinstance(settings["cwd"], str) or _cwd(settings["cwd"]) != root
            or settings["runtime_workspace_roots"] != [str(root)]
            or settings["permission_profile"] != _readonly_profile()
            or settings["permission_profile"] != turn.get("permission_profile")
            or turn.get("sandbox_policy") != {"type": "read-only"}
            or settings["collaboration_mode"] != collaboration
            or settings["approval_policy"] != "never" or settings["approvals_reviewer"] != "user"
            or settings["model_provider_id"] != "openai"
            or not isinstance(settings["service_tier"], str) or not settings["service_tier"].strip()
            or not isinstance(settings["disabled_plugin_ids"], list)
            or any(not isinstance(value, str) for value in settings["disabled_plugin_ids"])):
        fail("review_coordinator_settings_changed", "native settings diverge from the observed read-only turn/binding")


def _authorization_settings(settings):
    """Compare authority only after the complete native schema was validated.

    Service tier is independent new-turn processing metadata. It cannot grant
    model/effort, provider, context, sandbox, approval or worktree authority.
    Source rows keep the actual tier, including changes between native turns.
    """
    return {key: value for key, value in settings.items() if key not in NON_AUTHORIZING_SETTINGS}


def readonly(runtime, session, package):
    source, rows, meta, turns = runtime.session(session)
    pair = package["coordinator_selection"]["arguments"]
    if meta.get("originator") != "codex_exec" or _cwd(meta["cwd"]) != Path(package["root"]) or not turns:
        fail("review_coordinator_identity_mismatch")
    has_settings = any(row["type"] == "event_msg" and row["payload"].get("type") == "thread_settings_applied" for _, row, _ in rows)
    for turn in turns:
        if _cwd(turn["cwd"]) != Path(package["root"]) or turn.get("model") != pair["model"] or turn.get("effort") != pair["reasoning_effort"]:
            fail("review_coordinator_observed_mismatch")
        if turn["sandbox_policy"].get("type") != "read-only":
            fail("review_coordinator_not_read_only")
        if has_settings or "permission_profile" in turn:
            if turn.get("permission_profile") != _readonly_profile() or turn["sandbox_policy"] != {"type": "read-only"}:
                fail("review_coordinator_not_read_only", "managed permission profile missing, unknown or writable")
    active_turn, work_seen, terminal_seen, baseline = None, False, False, None
    pending_settings = []
    by_turn = {turn["turn_id"]: turn for turn in turns}
    for _, row, _ in rows:
        v = row["payload"]
        if row["type"] == "turn_context" and v["turn_id"] != active_turn:
            if has_settings and active_turn is not None and not terminal_seen:
                fail("review_coordinator_settings_changed", "new turn began before the previous turn completed")
            for pending in pending_settings:
                _settings_match_turn(pending, by_turn[v["turn_id"]], package)
            pending_settings.clear()
            active_turn, work_seen, terminal_seen = v["turn_id"], False, False
        if row["type"] == "event_msg" and v.get("type") == "turn_aborted":
            fail("review_coordinator_interrupted")
        if row["type"] == "event_msg" and v.get("type") == "thread_settings_applied":
            between_turns = terminal_seen and baseline is not None
            if (set(v) - {"type", "thread_id", "turn_id", "thread_settings"}
                    or v.get("thread_id") != session or active_turn is None
                    or v.get("turn_id") not in ({None} if between_turns else {None, active_turn})
                    or not between_turns and (work_seen or terminal_seen)
                    or baseline is None and active_turn != turns[0]["turn_id"]):
                fail("review_coordinator_settings_changed", "settings are not initial/native or were applied after work")
            settings = v.get("thread_settings")
            _settings_match_turn(settings, by_turn[active_turn], package)
            if baseline is not None and _authorization_settings(settings) != _authorization_settings(baseline):
                fail("review_coordinator_settings_changed", "resumed authorization settings differ from the original configuration")
            baseline = settings
            if between_turns:
                pending_settings.append(settings)
        if row["type"] == "event_msg" and v.get("type") == "task_complete":
            if has_settings and v.get("turn_id") != active_turn:
                fail("review_coordinator_settings_changed", "terminal identity unavailable or divergent")
            terminal_seen = True
        item = v.get("item", {})
        if (row["type"] == "response_item" and v.get("type") in {"function_call", "custom_tool_call"}
                or row["type"] == "event_msg" and v.get("type") in {"item_started", "item_completed"}
                and isinstance(item, dict) and item.get("type") in {"CommandExecution", "CollabAgentToolCall", "McpToolCall", "FileChange"}):
            if has_settings and terminal_seen:
                fail("review_coordinator_settings_changed", "tool work after terminal requires a new observed turn")
            work_seen = True
    return source, rows, meta, turns


def _permission_sources(runtime, session, turn_id):
    """Keep setting/turn digests fixed per attempt; later resumes do not retune it."""
    source, rows, _, _ = runtime.session(session)
    active, ordinals, terminal_seen, pending = None, set(), False, []
    for i, row, _ in rows:
        v = row["payload"]
        if row["type"] == "turn_context":
            if v["turn_id"] != active:
                active, terminal_seen = v["turn_id"], False
                if active == turn_id:
                    ordinals.update(pending)
                pending.clear()
            if active == turn_id:
                ordinals.add(i)
        if row["type"] == "event_msg" and v.get("type") == "thread_settings_applied":
            if terminal_seen:
                pending.append(i)
            elif active == turn_id:
                ordinals.add(i)
        if row["type"] == "event_msg" and v.get("type") == "task_complete" and v.get("turn_id") == active:
            terminal_seen = True
    return ce._projection(rows, ordinals, source)


def require_principal(package, *, runtime=None):
    rt = runtime or ce.Rollout()
    session = os.environ.get("CODEX_THREAD_ID")
    if session != package["principal_thread"]:
        fail("review_principal_mismatch")
    _, _, _, turns = rt.session(session)
    if turns[-1]["sandbox_policy"].get("type") not in {"workspace-write", "danger-full-access"} or _cwd(turns[-1]["cwd"]) != Path(package["root"]):
        fail("review_prepare_requires_writable_principal")


def binding(path, *, runtime=None, complete=False):
    """Principal launch → real exec thread. Never accept a supplied parent id."""
    rt = runtime or ce.Rollout()
    p = read_package(path)
    if p["phase"] != "bootstrap":
        initial = binding(p["bootstrap"], runtime=rt)
        coordinator = initial["coordinator_thread"]
        readonly(rt, coordinator, p)
        if complete:
            output, ref = native_command(rt, p["principal_thread"], command(path), p["root"], after=p["before_record"])
            _verify_launch_output(path, p, output, coordinator)
            phase_turn = _phase_turn(rt, coordinator, p)
            _completed_turn(rt, coordinator, turn_id=phase_turn)
            if p["phase"] == "review":
                observed, preflight_ref = native_command(rt, coordinator, command(path, "preflight"), p["root"], after=p["coordinator_before_record"])
                pre_start, pre_end = _native_interval(rt, coordinator, preflight_ref)
                checked_at = observed.get("stage_checked_at_ms")
                if type(checked_at) is not int or not pre_start <= checked_at <= pre_end:
                    fail("review_stage_timing_unavailable")
                stage = verify_stage_receipt(path, runtime=rt, at_ms=checked_at)
                launch_start, launch_end = _native_interval(rt, p["principal_thread"], ref)
                if (not launch_start <= stage["recheck_started_ms"] <= stage["recheck_completed_ms"] <= pre_start <= pre_end <= launch_end
                        or stage["status_source"]["ordinal"] >= ref["ordinal"] or ref["turn_id"] != p["principal_turn"]):
                    fail("review_stage_source_changed", "status, launch and preflight ordering differs")
                if observed.get("stage_receipt_sha256") != stage["integrity_sha256"]:
                    fail("review_stage_source_changed")
                if preflight_ref["turn_id"] != phase_turn or observed.get("result") != "ready" or observed.get("stage_status") != "Code Review" or observed.get("phase") != "review" or observed.get("coordinator_thread") != coordinator:
                    fail("review_stage_binding_mismatch")
            return dict(initial, continuation=ref,
                sources=initial["sources"] + [ref] + _permission_sources(rt, coordinator, phase_turn))
        return initial
    output, ref = native_command(rt, p["principal_thread"], command(path), p["root"], after=p["before_record"])
    coordinator = _verify_launch_output(path, p, output)
    source, rows, meta, turns = readonly(rt, coordinator, p)
    # The initial launch must have returned before any diagnostic continuation.
    initial_turn = turns[0]["turn_id"]
    _completed_turn(rt, coordinator, turn_id=initial_turn)
    if coordinator == p["principal_thread"] or meta.get("source") != "exec":
        fail("review_coordinator_identity_mismatch")
    _, _, principal_meta, principal_turns = rt.session(p["principal_thread"])
    if principal_meta["originator"] != p["principal_host"]:
        fail("review_principal_surface_changed")
    return {"schema": SCHEMA, "package": str(Path(path).resolve()), "package_sha256": p["integrity_sha256"],
            "principal_thread": p["principal_thread"], "principal_host": p["principal_host"],
            "coordinator_thread": coordinator, "coordinator_host": meta["originator"],
            "sources": [ref, {"source": str(source), "ordinal": rows[0][0], "type": "session_meta", "event_type": ce.UNAVAILABLE, "raw_sha256": rows[0][2]}]
                + _permission_sources(rt, coordinator, initial_turn)}


def _verify_launch_output(path, p, output, coordinator=None):
    raw = inside(p["root"], p["events"]).read_bytes()
    try:
        events = [json.loads(line) for line in raw.splitlines()]
        started = [e["thread_id"] for e in events if e.get("type") == "thread.started"]
    except (ValueError, KeyError, TypeError):
        fail("review_launch_output_invalid")
    wanted = {"schema": SCHEMA, "package_sha256": p["integrity_sha256"], "coordinator_thread": started[0] if len(started) == 1 else None, "events_sha256": ce.digest(raw), "exit_code": 0}
    if p["phase"] == "review":
        wanted["stage_receipt_sha256"] = _read_stage_receipt(p)["integrity_sha256"]
    if len(started) != 1 or not isinstance(started[0], str) or not started[0] or output != wanted:
        fail("review_launch_output_mismatch")
    if coordinator and coordinator != started[0]:
        fail("review_coordinator_identity_mismatch")
    if len([e for e in events if e.get("type") == "turn.completed"]) != 1 or any(e.get("type") in {"error", "turn.failed"} for e in events):
        fail("review_coordinator_payload_unavailable")
    return started[0]


def _completed_turn(runtime, session, turn_id=None):
    _, rows, _, turns = runtime.session(session)
    turn_id = turn_id or turns[-1]["turn_id"]
    completed = [row["payload"] for _, row, _ in rows if row["type"] == "event_msg" and row["payload"].get("type") == "task_complete" and row["payload"].get("turn_id") == turn_id]
    if len(completed) != 1 or not isinstance(completed[0].get("last_agent_message"), str) or not completed[0]["last_agent_message"].strip():
        fail("review_coordinator_payload_unavailable")


def _phase_turn(runtime, session, package):
    _, rows, _, _ = runtime.session(session)
    turns = [row["payload"]["turn_id"] for i, row, _ in rows if i >= package["coordinator_before_record"] and row["type"] == "turn_context"]
    if not turns:
        fail("review_launch_source_unavailable", "coordinator continuation turn absent")
    return turns[0]


def contract_observation(bootstrap, *, runtime=None):
    rt = runtime or ce.Rollout()
    p = read_package(bootstrap)
    chain = binding(bootstrap, runtime=rt)
    session = chain["coordinator_thread"]
    document, ref = native_command(rt, session, command(bootstrap, "inspect"), p["root"])
    if document.get("schema") != SCHEMA or document.get("session") != session:
        fail("context_contract_unavailable")
    doc = document["contract"]
    if doc.get("internal_context_attestation") != ce.UNAVAILABLE or doc["scope_sha256"] != ce.digest(doc["scope"]):
        fail("context_scope_mismatch")
    # PATH may be the official Node launcher. The observed native ancestor is a
    # different artifact; never call the launcher's hash a runtime observation.
    runtime_binary = doc["runtime_binary"]
    executable = Path(runtime_binary["executable"].removesuffix(" (deleted)"))
    native_bytes = executable.read_bytes()
    if executable.name != "codex" or ce.digest(native_bytes) != runtime_binary["binary_sha256"] or runtime_binary["binary_sha256"] != doc["scope"]["binary_sha256"]:
        fail("context_runtime_mismatch")
    if len(runtime_binary["fragments"]) != len(cc.FRAGMENTS):
        fail("context_contract_unavailable")
    for fragment, observation in zip(cc.FRAGMENTS, runtime_binary["fragments"]):
        offset = observation["offset"]
        if observation["length"] != len(fragment) or observation["sha256"] != ce.digest(fragment) or native_bytes[offset:offset + len(fragment)] != fragment:
            fail("context_contract_unavailable")
    source, rows, meta, turns = rt.session(session)
    if doc["scope"].get("host") != meta["originator"] or doc["scope"].get("tool") != cc.TOOL or doc["scope"].get("multi_agent_version") != "v2" or doc.get("host_version") != meta["cli_version"]:
        fail("context_scope_mismatch")
    for source_ref in doc["runtime_instructions"]:
        if source_ref["source"] != str(source) or not any(i == source_ref["ordinal"] and sha == source_ref["raw_sha256"] for i, row, sha in rows):
            fail("context_source_changed")
    return doc


def resolve_envelope(envelope, *, runtime=None):
    """Resolve only in memory, preserving original pending bytes and their digest."""
    rt = runtime or ce.Rollout()
    original = ce.check_seal(json.loads(Path(envelope["pending_envelope"]).read_text()))
    if envelope != original or original.get("envelope_state") != "pending_coordinator" or original.get("parent_thread") != ce.UNAVAILABLE or original.get("parent_turn") != ce.UNAVAILABLE:
        fail("review_pending_envelope_invalid")
    p = read_package(original["dedicated_package"])
    if original.get("attempt_id") != original.get("capture", {}).get("attempt_id") or original.get("role") != original.get("capture", {}).get("role") or original.get("wave_id") != p["wave_id"] or original.get("root") != p["root"] or original.get("bound_card") != p["bound_card"]:
        fail("review_pending_envelope_invalid")
    if original["pending_envelope"] not in p["files"] or p["files"][original["pending_envelope"]] != ce.digest(Path(original["pending_envelope"]).read_bytes()):
        fail("review_pending_envelope_invalid")
    chain = binding(original["dedicated_package"], runtime=rt)
    parent = chain["coordinator_thread"]
    _, rows, meta, turns = rt.session(parent)
    result = {k: v for k, v in original.items() if k != "integrity_sha256"}
    result.update(parent_thread=parent, parent_turn="deferred_native_read_only", deferred_review_turn=True,
                  parent_host=meta["originator"], driver=ce.DRIVER, envelope_state="resolved_from_native_source")
    return ce.sealed(result)


def resolve_plan(plan, *, runtime=None):
    chain = binding(plan["dedicated_package"], runtime=runtime)
    if plan.get("parent_thread") != ce.UNAVAILABLE:
        fail("review_probe_binding_mismatch")
    return dict(plan, parent_thread=chain["coordinator_thread"], host="codex_exec")


def prepare(*, root, phase, bootstrap=None, diff=None, runtime=None):
    rt = runtime or ce.Rollout()
    root = Path(root).resolve()
    if phase not in PHASES:
        fail("review_package_invalid")
    principal = os.environ.get("CODEX_THREAD_ID")
    source, rows, meta, turns = rt.session(principal)
    if _cwd(turns[-1]["cwd"]) != root or turns[-1]["sandbox_policy"].get("type") not in {"workspace-write", "danger-full-access"}:
        fail("review_prepare_requires_writable_principal")
    card = __import__("re").match(r"card-(\d+)-", root.name)
    if not card:
        fail("worktree_mismatch")
    out = ce.destination(root)
    ce.check_writable_destination(out)
    token = secrets.token_hex(12)
    path = out / f"dedicated-{phase}-{token}.package.json"
    prompt_path = path.with_suffix(".prompt.txt")
    helper = inside(root, Path(__file__).resolve())
    binary = Path(shutil.which("codex") or "").resolve()
    if not binary.is_file():
        fail("review_launcher_unavailable")
    cap = resolve("codex", "execucao")
    capture = path.with_suffix(".capture.json")
    save_capture(capture, cap)
    files = {str(capture): ce.digest(capture.read_bytes()), str(helper): ce.digest(helper.read_bytes())}
    for name in ("codex_evidence.py", "codex_review_probe.py", "codex_context.py", "codex_review.py"):
        sibling = Path(__file__).with_name(name)
        files[str(sibling)] = ce.digest(sibling.read_bytes())
    p = {"schema": SCHEMA, "state": "pending_native_launch", "phase": phase, "root": str(root), "bound_card": card[1],
         "principal_thread": principal, "principal_host": meta["originator"], "principal_turn": turns[-1]["turn_id"], "before_record": len(rows),
         "wave_id": token, "helper": str(helper), "binary": str(binary), "binary_sha256": ce.digest(binary.read_bytes()),
         "interpreter": str(Path(sys.executable).resolve()), "interpreter_sha256": ce.digest(Path(sys.executable).read_bytes()),
         "coordinator_capture": str(capture), "coordinator_selection": cap, "events": str(path.with_suffix(".events.jsonl")),
         "stderr": str(path.with_suffix(".stderr.txt")),
         "prompt": str(prompt_path), "files": files}
    if phase == "review":
        p["stage_receipt"] = str(path.with_suffix(".stage.json"))
        # The principal's query implementation and configured authority are
        # part of this attempt, even though the coordinator never imports them.
        for name in ("guard.py", "resolve.py", "graphql_quota.py", "overlay.py", "fsm.py"):
            source_file = inside(root, Path(__file__).with_name(name))
            files[str(source_file)] = ce.digest(source_file.read_bytes())
        authority = inside(root, root / ".covenant-flow/overlay.yaml")
        files[str(authority)] = ce.digest(authority.read_bytes())
        stage_binding(p, allowed={"Em desenvolvimento", "Code Review"})
    message = (f"# {card[1]} dedicated Codex coordinator. Worktree: {root}. Remain read-only throughout. "
               "Do not review, edit product, run git, change trust/permissions, process_event or substitute clients. "
               "Only the explicitly specified native diagnostic or two review children are allowed.\n")
    if phase == "bootstrap":
        message += ("Bootstrap diagnostic only; no child spawn. Run exactly this inspection command: "
                    + shlex.join([p["interpreter"], "-I", str(helper), "inspect", "--package", str(path)])
                    + ". Then return one fresh nonsecret marker on its own line: context_sentinel: <new random-looking alphanumeric value of 32 characters>. "
                    "Keep that value only in this final message, never in tools, files, env or future child prompts. No product work.\n")
    else:
        bootstrap = inside(root, bootstrap)
        b = read_package(bootstrap)
        chain = binding(bootstrap, runtime=rt)
        if chain["principal_thread"] != principal:
            fail("review_principal_mismatch")
        compare_wave(b["coordinator_selection"], cap)
        p["bootstrap"] = str(bootstrap)
        p["bootstrap_sha256"] = b["integrity_sha256"]
        files[str(bootstrap)] = ce.digest(bootstrap.read_bytes())
        coordinator = chain["coordinator_thread"]
        _, coordinator_rows, coordinator_meta, coordinator_turns = rt.session(coordinator)
        p["coordinator_before_record"] = len(coordinator_rows)
        if phase == "context":
            # Construct the next-turn diagnostic before its native spawn; never
            # write into the coordinator or retrofit a receipt after the call.
            context_cap = resolve("codex", "execucao", role="same-card-search")
            context_capture = path.with_suffix(".child.capture.json")
            save_capture(context_capture, context_cap)
            birth_path = out / f"{context_cap['attempt_id']}.birth.json"
            birth = _pending_birth(p, path, birth_path, context_capture, context_cap, "same_card_search_context_" + token)
            birth["context_diagnostic"] = cc.SCHEMA
            ce.private_write(birth_path, ce.sealed(birth))
            doc = contract_observation(bootstrap, runtime=rt)
            candidates = []
            for i, row, sha in coordinator_rows:
                try:
                    cc.read_sentinel(coordinator_rows, i)
                    candidates.append((i, row, sha))
                except ce.EvidenceError:
                    pass
            if len(candidates) != 1:
                fail("context_sentinel_source_unavailable")
            i, row, sha = candidates[0]
            sentinel = cc.check_new_sentinel(coordinator_rows, i, coordinator)
            control = secrets.token_hex(24)
            requested = cc.prompt(control, context_capture, birth_path)
            plan_path = cc.plan_path(birth_path)
            plan = ce.sealed({"schema": cc.SCHEMA, "birth": str(birth_path), "root": str(root), "parent_thread": coordinator,
                "parent_turn": "deferred_native_read_only", "dedicated_bootstrap": str(bootstrap), "contract": doc,
                "sentinel_source": {"source": str(rt.session(coordinator)[0]), "ordinal": i, "raw_sha256": sha},
                "sentinel_sha256": cc.sha(sentinel.encode()), "control_sha256": cc.sha(control.encode()),
                "prompt_sha256": cc.sha(requested.encode()), "requested_message": requested, "request_observation": "requested",
                "source_records": len(coordinator_rows)})
            ce.private_write(plan_path, plan)
            for artifact in (context_capture, birth_path, plan_path):
                files[str(artifact)] = ce.digest(artifact.read_bytes())
            p["births"] = [str(birth_path)]
            preflight_command = shlex.join([p["interpreter"], "-I", str(helper), "preflight", "--package", str(path)])
            message += ('Execute the exact preflight command ONCE ONLY, with exec_command max_output_tokens=12000 and enclosing functions.exec max_output_tokens=12000. Preserve and print the COMPLETE result object, including session_id and exit_code, not only result.output. If exec_command returns session_id, keep that ID and await the SAME process using write_stdin with empty chars and max_output_tokens=12000 until it returns a final exit_code and no session_id. Accumulate every output fragment in order; polling is not a new execution. If functions.exec yields Script running with cell ID, retain that cell ID and call functions.wait on the SAME cell until completion; preserve its eventual command result/session_id. Keep each wait at most 60 seconds; never finish this turn or spawn while the preflight is running. Only after termination evaluate the complete JSON and exit_code=0, then require result=ready and the exact phase/work_release below. Truncation, missing result/ID, nonzero exit, invalid JSON or uncertainty blocks with review_preflight_output_unavailable or the returned failure code; do not rerun preflight. Context diagnostic only; require phase=context, work_release=diagnostic_only. '
                        "If it fails, return only the failure code and stop before spawning.\n" + preflight_command
                        + "\nThen use the native collaboration.spawn_agent tool exactly once for a same-card-search child with the literal arguments and message below. "
                        "If that native tool is unavailable, report review_native_spawn_unavailable and stop. "
                        "Do not execute the child's diagnostic in the coordinator or substitute a shell/external session. "
                        "The child uses no tools; do not steer it. Wait for its completed payload then return it.\n" + json.dumps({"task_name": birth["task_name"],
                        "fork_turns": "none", **context_cap["arguments"], "message": requested}, ensure_ascii=False) + "\n")
        else:
            if phase == "review":
                cc.verify_qualification(root=root, out=out, session=coordinator, runtime=rt)
                from codex_review_probe import verify_qualification
                verify_qualification(root=root, session=coordinator, runtime=rt)
                verify_route(bootstrap, runtime=rt)
            from codex_review_probe import prepare as prepare_probe
            diff = inside(root, diff)
            p["diff"] = str(diff); p["diff_sha256"] = ce.digest(diff.read_bytes())
            files[str(diff)] = ce.digest(diff.read_bytes())
            p["births"] = []; p["spawns"] = []
            first = None
            for role in ROLES:
                child_cap = resolve("codex", "execucao", role=role)
                compare_wave(cap, child_cap)
                if first is not None:
                    compare_wave(first, child_cap)
                else:
                    first = child_cap
                child_capture = out / f"{child_cap['attempt_id']}.capture.json"
                save_capture(child_capture, child_cap)
                probe = prepare_probe(root=root, capture=child_capture, diff=diff, wave_id=token,
                                      runtime=rt, pending_package=str(path))
                birth_path = out / f"{child_cap['attempt_id']}.birth.json"
                birth = _pending_birth(p, path, birth_path, child_capture, child_cap, role.replace("-", "_") + "_" + token)
                birth.update(review_probe_plan=probe["plan"], review_probe_plan_sha256=ce.check_seal(json.loads(Path(probe["plan"]).read_text()))["integrity_sha256"])
                if phase == "review":
                    context = cc.verify_qualification(root=root, out=out, session=coordinator, runtime=rt)
                    birth.update(context_qualification=context["qualification_path"], context_scope_sha256=context["scope_sha256"])
                ce.private_write(birth_path, ce.sealed(birth))
                profile = root / ".codex/agents" / (role + ".toml")
                for artifact in (child_capture, birth_path, Path(probe["plan"]), profile):
                    files[str(artifact)] = ce.digest(artifact.read_bytes())
                p["births"].append(str(birth_path))
                child_message = (f"#{card[1]} {role}; worktree {root}; " + ("diagnostic only; no product review. " if phase == "probe" else "Code Review of the exact supplied diff only. ")
                    + "Remain read-only. As your FIRST command run the exact fixed-helper command below ONCE ONLY. It verifies package/plan/capture/path/SHA and attempts a write only to the plan's disposable fixture. "
                    "This specific attempt is allowed; successful writing, absent denial or changed readback means stop and report failure. Do not edit product, run git, escalate or read transcripts. "
                    "Coordinator preflight is already a prerequisite: do not run preflight again in the child. Use max_output_tokens=20000 for exec_command and max_output_tokens=32000 for enclosing functions.exec, printing one result at a time. "
                    "NEVER rerun the probe even if output is truncated; report review_probe_output_unavailable and stop. "
                    'Input context and output budgets are different units: diff bytes, Unicode characters and page count are NOT token counts. The model input context window is distinct from its generation/reasoning/work budget and each tool output limit. Do not infer inability to read the diff from byte/page count or remaining generation/work allowance alone. Use actual native context-window/input-usage metadata if exposed; no fixed window size is guaranteed and absence of metadata does not establish shortage. Tokenizer estimates, if supplied, are estimates, not observed native usage. Read all bounded pages sequentially, retaining every returned diff_text and its path/SHA; do not sample, summarize away or omit parts. If an actual input limit, truncation or missing delivery prevents full reading, stop with review_diff_delivery_incomplete and no verdict. '
                    "A small diff is delivered inline as diff_text. For delivery=native-json-bounded-pages-v2 the short probe result is NOT full diff delivery: execute read_command_template with each integer chunk_index from 0 through chunk_count-1, one command/result at a time with the same output budgets. "
                    "Read every returned diff_text chunk before findings. These read commands perform NO write attempt. Do not combine chunks into an oversized tool output, substitute metadata for reading, or silently omit parts; insufficient context/output budget means review_diff_delivery_incomplete and no verdict. "
                    "The fixed helper and each read command verify the same diff SHA; no separate codex_review.py verify is required. Final verify-wave belongs ONLY to the writable principal after both payloads and source-bound collection; its absence now is expected, never a waiver of missing probe/chunks.\n"
                    + f"review_diff_path: {diff}\nreview_diff_sha256: {p['diff_sha256']}\nmodel_selection_capture: {child_capture}\n"
                    + f"model_selection_wave_capture: {p.get('first_capture', child_capture)}\nruntime_evidence_birth: {birth_path}\n"
                    + probe["command"] + "\n")
                p.setdefault("first_capture", str(child_capture))
                p["spawns"].append({"task_name": birth["task_name"], "agent_type": role, "fork_turns": "none", **child_cap["arguments"], "message": child_message})
            message += ('Execute the exact preflight command ONCE ONLY, with exec_command max_output_tokens=12000 and enclosing functions.exec max_output_tokens=12000. Preserve and print the COMPLETE result object, including session_id and exit_code, not only result.output. If exec_command returns session_id, keep that ID and await the SAME process using write_stdin with empty chars and max_output_tokens=12000 until it returns a final exit_code and no session_id. Accumulate every output fragment in order; polling is not a new execution. If functions.exec yields Script running with cell ID, retain that cell ID and call functions.wait on the SAME cell until completion; preserve its eventual command result/session_id. Keep each wait at most 60 seconds; never finish this turn or spawn while the preflight is running. Only after termination evaluate the complete JSON and exit_code=0, then require result=ready and the exact phase/work_release below. Truncation, missing result/ID, nonzero exit, invalid JSON or uncertainty blocks with review_preflight_output_unavailable or the returned failure code; do not rerun preflight. Require phase={phase}, work_release={release}. '.format(phase=phase, release="stage" if phase == "review" else "diagnostic_only")
                        +                         "If blocked, do not spawn. If ready, spawn BOTH native role children in this same turn using the literal arguments below; wait for both completed payloads. "
                        "Do not perform review yourself or persist evidence.\n" + shlex.join([p["interpreter"], "-I", str(helper), "preflight", "--package", str(path)])
                        + "\n" + json.dumps(p["spawns"], ensure_ascii=False) + "\n")
    # Prompt is immutable requested input; it never claims observed runtime.
    _write_text(prompt_path, message)
    files[str(prompt_path)] = ce.digest(prompt_path.read_bytes())
    ce.private_write(path, ce.sealed(p))
    result = {"package": str(path), "state": "pending_native_launch", "command": command(path)}
    if phase == "review":
        result["stage_check_command"] = command(path, "stage-check")
    if phase == "bootstrap":
        result["refusal_command"] = command(path, "route-check")
    return result


def _write_text(path, message):
    from codex_fs import atomic_write_bytes
    atomic_write_bytes(path, message.encode())


def _pending_birth(p, path, birth_path, capture_path, cap, task):
    return {"schema": ce.SCHEMA, "driver": ce.DRIVER, "envelope_state": "pending_coordinator", "pending_envelope": str(birth_path),
        "dedicated_package": str(path), "capture": cap, "capture_path": str(capture_path), "root": p["root"], "bound_card": p["bound_card"],
        "attempt_id": cap["attempt_id"], "role": cap["role"], "band": cap["band"], "task_name": task,
        "parent_thread": ce.UNAVAILABLE, "parent_turn": ce.UNAVAILABLE, "before_record": p["coordinator_before_record"],
        "qualification": p["phase"] != "review", "review_diff_sha256": p.get("diff_sha256", ce.UNAVAILABLE), "wave_id": p["wave_id"],
        "parent_host": ce.UNAVAILABLE, "stage_contract": ce.STAGE_CONTRACT, "stage_status": ce.UNAVAILABLE,
        "work_release": "diagnostic_only" if p["phase"] != "review" else "stage"}


def preflight(path, *, runtime=None):
    rt = runtime or ce.Rollout()
    p = read_package(path)
    chain = binding(path, runtime=rt)
    session = os.environ.get("CODEX_THREAD_ID")
    if session != chain["coordinator_thread"]:
        fail("review_coordinator_identity_mismatch")
    _, rows, _, turns = readonly(rt, session, p)
    if turns[-1].get("multi_agent_version") != "v2":
        fail("review_native_spawn_unavailable", "the active coordinator turn does not expose the required native v2 runtime")
    phase_turn = _phase_turn(rt, session, p)
    if turns[-1]["turn_id"] != phase_turn or any(row["type"] == "event_msg" and row["payload"].get("type") == "task_complete" and row["payload"].get("turn_id") == phase_turn for _, row, _ in rows):
        fail("session_inactive", "dedicated preflight requires this package's active continuation turn")
    status = ce.UNAVAILABLE
    stage = None
    if p["phase"] == "review":
        cc.verify_qualification(root=p["root"], out=ce.destination(p["root"]), session=session, runtime=rt)
        from codex_review_probe import verify_qualification
        verify_qualification(root=p["root"], session=session, runtime=rt)
        verify_route(p["bootstrap"], runtime=rt)
    for birth_path in p.get("births", []):
        birth = ce.check_seal(json.loads(Path(birth_path).read_text()))
        cap = validate_capture(birth["capture"], client="codex")
        compare_wave(cap, resolve("codex", "execucao", role=cap["role"]))
    if p["phase"] == "review":
        # Check freshness after every other prerequisite, at work release.
        checked_at = _clock_ms()
        stage = verify_stage_receipt(path, runtime=rt, at_ms=checked_at)
        status = stage["status"]
    result = {"result": "ready", "phase": p["phase"], "coordinator_thread": session, "stage_status": status, "work_release": "diagnostic_only" if p["phase"] != "review" else "stage", "internal_context_attestation": ce.UNAVAILABLE}
    if stage:
        result["stage_receipt_sha256"] = stage["integrity_sha256"]
        result["stage_checked_at_ms"] = checked_at
    return result


def local_binding(package):
    """Local git/card validation; never imports the network/cache Guard."""
    from resolve import resolve as resolve_card
    bound = resolve_card(package["root"], package["root"])
    if str(bound["bound_card"]) != package["bound_card"] or bound["q_git"] != Path(package["root"]).name:
        fail("review_stage_binding_mismatch", f"bound_card={bound['bound_card']}; q_git={bound['q_git']}")
    return bound


def stage_binding(package, *, allowed):
    bound = local_binding(package)
    try:
        from guard import github_status_provider
        status = github_status_provider(bound["bound_card"])
    except Exception as exc:
        fail("review_stage_query_failed", f"authoritative GitHub status query failed: {type(exc).__name__}: {exc}")
    if status is None:
        fail("review_stage_status_unavailable", "authoritative GitHub query did not return a Status")
    if status not in allowed:
        fail("review_stage_binding_mismatch", f"q={status}; bound_card={bound['bound_card']}; q_git={bound['q_git']}")
    return status


def _clock_ms():
    return int(time.time() * 1000)


def _stage_scope(p):
    return {key: p[key] for key in ("root", "bound_card", "principal_thread", "principal_turn", "wave_id")} | {"package_sha256": p["integrity_sha256"]}


def stage_check(path, *, runtime=None):
    """Query on the principal; the completed native command is its source.

    A requested flag, old cache or manually written JSON cannot substitute it.
    The read-only coordinator only rereads this source and the launch receipt.
    """
    rt = runtime or ce.Rollout()
    p = read_package(path)
    if p["phase"] != "review":
        fail("review_action_phase_mismatch", "stage-check is product-review only")
    require_principal(p, runtime=rt)
    if rt.session(p["principal_thread"])[3][-1]["turn_id"] != p["principal_turn"]:
        fail("review_stage_binding_mismatch", "principal turn changed; prepare a fresh package")
    started = _clock_ms()
    status = stage_binding(p, allowed={"Code Review"})
    return ce.sealed({"schema": STAGE_SCHEMA, "result": "ready", **_stage_scope(p),
        "status": status, "query_started_ms": started, "query_completed_ms": _clock_ms(),
        "status_origin": "principal_live_github_query"})


def _native_interval(runtime, session, ref):
    source, rows, _, _ = runtime.session(session)
    matching = [row["payload"] for i, row, sha in rows if str(source) == ref["source"] and i == ref["ordinal"] and sha == ref["raw_sha256"]]
    if len(matching) != 1:
        fail("review_stage_source_changed")
    value = matching[0]
    start, end = value.get("started_at_ms"), value.get("completed_at_ms")
    if type(start) is not int or type(end) is not int or not 0 < start <= end:
        fail("review_stage_timing_unavailable", "native command start/completion timestamps required")
    return start, end


def _stage_observation(path, *, runtime, at_ms):
    p = read_package(path)
    observed, ref = native_command(runtime, p["principal_thread"], command(path, "stage-check"), p["root"], after=p["before_record"])
    observed = ce.check_seal(observed)
    start, end = _native_interval(runtime, p["principal_thread"], ref)
    begin, done = observed.get("query_started_ms"), observed.get("query_completed_ms")
    if (observed.get("schema") != STAGE_SCHEMA or observed.get("result") != "ready" or observed.get("status") != "Code Review"
            or observed.get("status_origin") != "principal_live_github_query" or ref["turn_id"] != p["principal_turn"]
            or any(observed.get(k) != v for k, v in _stage_scope(p).items())):
        fail("review_stage_binding_mismatch", "native principal status source differs from this attempt")
    if type(begin) is not int or type(done) is not int or not start <= begin <= done <= end <= at_ms or at_ms - begin > STAGE_MAX_AGE_MS:
        fail("review_stage_status_expired", "new principal stage-check and a fresh launch attempt required")
    return observed, ref


def _read_stage_receipt(p):
    try:
        return ce.check_seal(json.loads(inside(p["root"], p["stage_receipt"]).read_text()))
    except (OSError, KeyError, ValueError) as exc:
        fail("review_stage_receipt_unavailable", str(exc))


def verify_stage_receipt(path, *, runtime=None, at_ms=None):
    """Read only; historical collection supplies native preflight time."""
    rt = runtime or ce.Rollout()
    p = read_package(path)
    if p["phase"] != "review":
        fail("review_action_phase_mismatch")
    local_binding(p)
    receipt = _read_stage_receipt(p)
    at = _clock_ms() if at_ms is None else at_ms
    observation, ref = _stage_observation(path, runtime=rt, at_ms=at)
    if (receipt.get("schema") != STAGE_SCHEMA or receipt.get("kind") != "launch_revalidation"
            or any(receipt.get(k) != v for k, v in _stage_scope(p).items())
            or receipt.get("status") != "Code Review" or receipt.get("status_source") != ref
            or receipt.get("observation_sha256") != observation["integrity_sha256"]
            or receipt.get("coordinator_thread") != binding(p["bootstrap"], runtime=rt)["coordinator_thread"]):
        fail("review_stage_source_changed", "launch receipt differs from native principal status source")
    begin, done = receipt.get("recheck_started_ms"), receipt.get("recheck_completed_ms")
    if type(begin) is not int or type(done) is not int or not observation["query_completed_ms"] <= begin <= done <= at:
        fail("review_stage_timing_unavailable", "principal revalidation order differs from native status source")
    return receipt


def principal_preflight(*, root, session, runtime=None):
    """T9 inspects the prepared route; it does not launch or change permissions."""
    rt = runtime or ce.Rollout()
    candidates = []
    for path in ce.destination(root).glob("dedicated-review-*.package.json"):
        # Select the latest attempt by its sealed header before validating its
        # current helper bytes. Preserved older attempts pin previous code and
        # must not prevent a freshly prepared package after an integration.
        p = ce.check_seal(json.loads(path.read_text()))
        if p.get("principal_thread") == session and p.get("root") == str(Path(root).resolve()):
            if p.get("schema") != SCHEMA or p.get("phase") != "review" or type(p.get("before_record")) is not int or p["before_record"] < 0:
                fail("review_package_invalid")
            candidates.append((p["before_record"], path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    if len(candidates) > 1 and candidates[-1][0] == candidates[-2][0]:
        fail("review_package_ambiguous")
    _, path = candidates[-1]
    p = read_package(path)
    compare_wave(p["coordinator_selection"], resolve("codex", "execucao"))
    stage_binding(p, allowed={"Em desenvolvimento", "Code Review"})
    route = verify_route(p["bootstrap"], runtime=rt)
    coordinator = route["coordinator_thread"]
    context = cc.verify_qualification(root=root, out=ce.destination(root), session=coordinator, runtime=rt)
    from codex_review_probe import verify_qualification
    probe = verify_qualification(root=root, session=coordinator, runtime=rt)
    capabilities = {key: "verified" for key in ("native_chat_linkage", "model_effort_observation", "worktree_binding", "context_isolation", "parent_read_only", "review_diff_read", "review_write_denial_readback")}
    capabilities["internal_context_attestation"] = ce.UNAVAILABLE
    _, _, _, turns = rt.session(session)
    return {"result": "ready", "session": session, "parent_turn": turns[-1]["turn_id"], "package": str(path), "coordinator_thread": coordinator,
            "capabilities": capabilities, "context_qualification": context, "review_qualification": probe, "qualification": False,
            "parent_sandbox": turns[-1]["sandbox_policy"]["type"], "destination": str(ce.destination(root))}


def launch(path):
    p = read_package(path)
    rt = ce.Rollout()
    session = os.environ.get("CODEX_THREAD_ID")
    if session != p["principal_thread"]:
        fail("review_principal_mismatch")
    _, _, _, turns = rt.session(session)
    if turns[-1]["sandbox_policy"].get("type") not in {"workspace-write", "danger-full-access"} or _cwd(turns[-1]["cwd"]) != Path(p["root"]):
        fail("review_prepare_requires_writable_principal")
    if p["phase"] == "review" and turns[-1]["turn_id"] != p["principal_turn"]:
        fail("review_stage_binding_mismatch", "principal turn changed; prepare a fresh attempt")
    compare_wave(p["coordinator_selection"], resolve("codex", "execucao"))
    pair = p["coordinator_selection"]["arguments"]
    argv = [p["binary"], "exec", "--sandbox", "read-only", "--cd", p["root"], "--model", pair["model"], "--config", "model_reasoning_effort=" + json.dumps(pair["reasoning_effort"]), "--json"]
    coordinator = None
    if p["phase"] != "bootstrap":
        coordinator = binding(p["bootstrap"])["coordinator_thread"]
        _, coordinator_rows, _, _ = rt.session(coordinator)
        if any(i >= p["coordinator_before_record"] and row["type"] == "turn_context" for i, row, _ in coordinator_rows):
            fail("review_coordinator_turn_changed", "prepare a fresh package before a new continuation")
        if p["phase"] == "review":
            observed, status_ref = _stage_observation(path, runtime=rt, at_ms=_clock_ms())
            verify_route(p["bootstrap"])
            cc.verify_qualification(root=p["root"], out=ce.destination(p["root"]), session=coordinator)
            # Recheck after the other prerequisites, immediately before the
            # exclusive launch receipt and exec; no coordinator network access.
            recheck_start = _clock_ms()
            status = stage_binding(p, allowed={"Code Review"})
            recheck_end = _clock_ms()
            if status != observed["status"] or recheck_end - observed["query_started_ms"] > STAGE_MAX_AGE_MS:
                fail("review_stage_status_expired")
        argv += ["resume", coordinator]
    argv += ["-"]
    # Retain every native JSONL byte. No inherited principal identity in exec.
    env = dict(os.environ)
    env.pop("CODEX_THREAD_ID", None)
    stage_receipt = None
    if p["phase"] == "review":
        stage_receipt = ce.sealed({"schema": STAGE_SCHEMA, "kind": "launch_revalidation", **_stage_scope(p),
            "coordinator_thread": coordinator, "status": status, "status_source": status_ref,
            "observation_sha256": observed["integrity_sha256"], "recheck_started_ms": recheck_start,
            "recheck_completed_ms": recheck_end})
        # Never replace an earlier status TTL or repair a failed attempt in place.
        stage_fd = os.open(inside(p["root"], p["stage_receipt"]), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(stage_fd, "wb") as output:
            output.write((json.dumps(stage_receipt, sort_keys=True) + "\n").encode())
    fd = os.open(p["events"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as output:
        result = subprocess.run(argv, input=Path(p["prompt"]).read_bytes(), stdout=output, stderr=subprocess.PIPE, cwd=p["root"], env=env, check=False)
    stderr_fd = os.open(p["stderr"], os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(stderr_fd, "wb") as output:
        output.write(result.stderr)
    if result.returncode != 0:
        code = "review_launcher_interrupted" if result.returncode in {130, -2} else "review_launcher_failed"
        fail(code, f"native exit={result.returncode}; events preserved; stderr={p['stderr']}; stderr_sha256={ce.digest(result.stderr)}")
    raw = Path(p["events"]).read_bytes()
    try:
        threads = [v["thread_id"] for v in (json.loads(line) for line in raw.splitlines()) if v.get("type") == "thread.started"]
    except (ValueError, KeyError):
        fail("review_launch_output_invalid")
    if len(threads) != 1 or coordinator and threads[0] != coordinator:
        fail("review_coordinator_identity_mismatch")
    output = {"schema": SCHEMA, "package_sha256": p["integrity_sha256"], "coordinator_thread": threads[0], "events_sha256": ce.digest(raw), "exit_code": 0}
    if stage_receipt:
        output["stage_receipt_sha256"] = stage_receipt["integrity_sha256"]
    return output


def verify_route(bootstrap, *, runtime=None):
    rt = runtime or ce.Rollout()
    p = read_package(bootstrap)
    chain = binding(bootstrap, runtime=rt)
    candidates = list(ce.destination(p["root"]).glob("dedicated-route-*.json"))
    for path in candidates:
        q = ce.check_seal(json.loads(path.read_text()))
        if q.get("principal_thread") != p["principal_thread"] or q.get("coordinator_thread") != chain["coordinator_thread"]:
            continue
        if q != qualify_route(q["probe_package"], runtime=rt, persist=False):
            fail("review_route_source_changed")
        return q
    fail("review_route_unqualified", "named roles and this principal→exec route require a completed native diagnostic")


def qualify_route(path, *, runtime=None, persist=True):
    rt = runtime or ce.Rollout()
    p = read_package(path)
    if p["phase"] != "probe":
        fail("review_route_not_diagnostic")
    chain = binding(path, runtime=rt, complete=True)
    cc.verify_qualification(root=p["root"], out=ce.destination(p["root"]), session=chain["coordinator_thread"], runtime=rt)
    proofs = [ce.extract(ce.check_seal(json.loads(Path(b).read_text())), runtime=rt) for b in p["births"]]
    if {q["role"] for q in proofs} != set(ROLES) or len({q["child_thread"] for q in proofs}) != 2 or len({q["native_parent_turn"] for q in proofs}) != 1 or any(q["native_arguments"]["agent_type"] != q["role"] for q in proofs):
        fail("review_route_wave_mismatch")
    bootstrap = read_package(p["bootstrap"])
    refusal, refusal_source = native_command(rt, p["principal_thread"], command(p["bootstrap"], "route-check"), p["root"], after=bootstrap["before_record"], before=p["before_record"], required_exit=1)
    if refusal.get("result") != "blocked" or refusal.get("code") != "review_route_unqualified":
        fail("review_route_refusal_invalid")
    # Per-role evidence already revalidates read/deny/readback and effective RO.
    q = ce.sealed({"schema": SCHEMA, "principal_thread": chain["principal_thread"], "coordinator_thread": chain["coordinator_thread"],
        "principal_host": chain["principal_host"], "coordinator_host": chain["coordinator_host"], "probe_package": str(Path(path).resolve()),
        "probe_package_sha256": p["integrity_sha256"], "proofs": [ce.digest(proof) for proof in proofs], "chain": chain, "refusal_source": refusal_source,
        "internal_context_attestation": ce.UNAVAILABLE})
    if persist:
        require_principal(p, runtime=rt)
        ce.private_write(ce.destination(p["root"]) / f"dedicated-route-{q['integrity_sha256']}.json", q)
    return q


def outcome(code):
    if code in {"review_coordinator_interrupted", "review_launcher_interrupted"}:
        return "interrupted"
    if code in {"review_launch_source_unavailable", "source_unavailable", "context_contract_unavailable", "review_coordinator_payload_unavailable", "review_native_spawn_unavailable"}:
        return "unverified"
    if code in {"review_launcher_failed", "review_launch_output_invalid", "review_launch_output_mismatch", "review_coordinator_identity_mismatch", "review_coordinator_observed_mismatch", "review_coordinator_not_read_only", "review_coordinator_settings_changed"}:
        return "failed"
    return "blocked"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--root", required=True); prep.add_argument("--phase", choices=PHASES, required=True)
    prep.add_argument("--bootstrap"); prep.add_argument("--diff")
    for action in ("launch", "inspect", "preflight", "binding", "qualify-route", "route-check", "stage-check"):
        sub.add_parser(action).add_argument("--package", required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(root=args.root, phase=args.phase, bootstrap=args.bootstrap, diff=args.diff)
        elif args.action == "inspect":
            p = read_package(args.package)
            session = os.environ.get("CODEX_THREAD_ID")
            if p["phase"] != "bootstrap":
                fail("review_action_phase_mismatch", "inspect is bootstrap-only; context continuation requires its prepared preflight command")
            if session == p["principal_thread"]:
                fail("review_coordinator_identity_mismatch")
            readonly(ce.Rollout(), session, p)
            result = {"schema": SCHEMA, "session": session, "contract": cc.contract(ce.Rollout(), session)}
        elif args.action == "stage-check": result = stage_check(args.package)
        elif args.action == "launch": result = launch(args.package)
        elif args.action == "preflight": result = preflight(args.package)
        elif args.action == "binding": result = binding(args.package, complete=True)
        elif args.action == "route-check": result = verify_route(args.package)
        else: result = qualify_route(args.package)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except (ce.EvidenceError, OSError, ValueError, KeyError, TypeError) as exc:
        code = getattr(exc, "code", "review_session_unavailable")
        print(json.dumps({"result": outcome(code), "code": code, "detail": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
