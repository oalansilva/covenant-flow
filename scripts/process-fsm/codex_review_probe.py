"""Source-bound diagnostic diff delivery and disposable write-denial probe.

Native CommandExecution records, not reviewer assertions, are the source.
This diagnostic never attests internal context or semantic understanding.
"""
from __future__ import annotations

import argparse
import errno
from functools import lru_cache
import json
import os
from pathlib import Path
import shlex
import stat
import sys
from urllib.parse import unquote, urlparse

# -I excludes user/site paths; load only this pinned adapter's siblings.
sys.path.insert(0, str(Path(__file__).resolve().parent))
for ancestor in Path(__file__).resolve().parents:
    adapter = ancestor / "scripts/process-fsm"
    if (ancestor / ".cursor/process-fsm.yaml").is_file() and (adapter / "model_selection.py").is_file():
        # Inactive candidates reuse unchanged pinned dependencies from their
        # own consumer; -I still excludes cwd, PYTHONPATH and user site code.
        if str(adapter) not in sys.path:
            sys.path.append(str(adapter))
        break
import codex_evidence as ce
from model_selection import load_capture, validate_capture

SCHEMA = "codex-review-probe-v1"
REVIEWERS = {"diff-reviewer", "code-reviewer"}
QUALIFICATION = "review-probe-qualification.json"
CHUNK_CHARS = 4096
DELIVERY = "native-json-bounded-pages-v2"
# Both limits stay below the observed native ~64 KiB truncation boundary.
# Tool return counts the outer JSON escaping too, including worst-case ASCII
# encoding of Unicode; explicit token budgets exceed these byte bounds.
MAX_NATIVE_JSON_BYTES = 16000
MAX_TOOL_RETURN_BYTES = 28000
METADATA_RESERVE = 2048
RETURN_METADATA_RESERVE = 512


def fail(code, detail=""):
    raise ce.EvidenceError(code, detail, recovery="writable principal prepares the dedicated package; qualify named roles in the read-only coordinator; preserve fixture/source; no permission toggles")


def inside(root, path):
    path = Path(path)
    if not path.is_absolute():
        path = Path(root) / path
    if any(p.is_symlink() for p in [path, *path.parents]):
        fail("review_probe_path_unsafe")
    path = path.resolve()
    if Path(root).resolve() not in path.parents:
        fail("review_probe_path_unsafe")
    return path


def read_plan(path, *, runtime=None):
    try:
        return _read_plan(path, runtime=runtime)
    except ce.EvidenceError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        fail("review_probe_unavailable", f"plan/source cannot be revalidated: {type(exc).__name__}")


def _read_plan(path, *, runtime=None):
    plan = json.loads(Path(path).read_text())
    if not isinstance(plan, dict):
        fail("review_probe_plan_invalid")
    plan = ce.check_seal(plan)
    if plan.get("schema") != SCHEMA or plan.get("role") not in REVIEWERS:
        fail("review_probe_plan_invalid")
    for key in ("root", "role", "attempt_id", "wave_id", "capture_path", "capture_sha256", "helper", "helper_sha256", "interpreter", "interpreter_sha256", "diff", "diff_sha256", "fixture", "fixture_sha256"):
        if not isinstance(plan.get(key), str) or not plan[key] or plan[key] == ce.UNAVAILABLE:
            fail("review_probe_plan_invalid", key)
    root = Path(plan["root"]).resolve()
    if plan.get("plan_path") != str(Path(path).resolve()):
        fail("review_probe_plan_invalid", "plan_path")
    if inside(root, path) != Path(path).resolve():
        fail("review_probe_path_unsafe")
    for key in ("helper", "diff", "fixture", "capture_path"):
        inside(root, plan[key])
    if Path(plan["helper"]).resolve() != Path(__file__).resolve() or ce.digest(Path(__file__).read_bytes()) != plan["helper_sha256"]:
        fail("review_probe_source_changed")
    if plan["interpreter"] != str(Path(sys.executable).resolve()) or ce.digest(Path(plan["interpreter"]).read_bytes()) != plan["interpreter_sha256"]:
        fail("review_probe_source_changed")
    capture = validate_capture(load_capture(plan["capture_path"]), client="codex", role=plan["role"])
    if ce.digest(capture) != plan["capture_sha256"] or capture["attempt_id"] != plan["attempt_id"]:
        fail("review_probe_capture_changed")
    diff = Path(plan["diff"]).read_bytes()
    if not diff or ce.digest(diff) != plan["diff_sha256"]:
        fail("review_probe_diff_changed")
    fixture = Path(plan["fixture"])
    mode = fixture.stat().st_mode
    if not stat.S_ISREG(mode) or mode & 0o777 != 0o600 or fixture.stat().st_uid != os.getuid():
        fail("review_probe_fixture_invalid")
    if ce.digest(fixture.read_bytes()) != plan["fixture_sha256"]:
        fail("review_probe_fixture_changed")
    if plan.get("dedicated_package"):
        from codex_review_session import resolve_plan
        return resolve_plan(plan, runtime=runtime)
    if any(not isinstance(plan.get(key), str) or plan[key] in {"", ce.UNAVAILABLE} for key in ("host", "parent_thread")):
        fail("review_probe_plan_invalid")
    return plan


def command(path, *, runtime=None):
    plan = read_plan(path, runtime=runtime)
    return shlex.join([plan["interpreter"], "-I", plan["helper"], "run", "--plan", str(Path(path).resolve())])


def read_command(path, index, *, runtime=None):
    plan = read_plan(path, runtime=runtime)
    return _read_command(plan, path, index)


def _read_command(plan, path, index):
    # Relative operands keep the literal command short. Native cwd is checked
    # independently at collection; equivalent/reconstructed paths never count.
    root = Path(plan["root"])
    helper = Path(plan["helper"]).relative_to(root).as_posix()
    relative = Path(path).resolve().relative_to(root).as_posix()
    return shlex.join([plan["interpreter"], "-I", helper, "read", "--plan", relative, "--chunk", str(index)])


def delivery(raw):
    text = raw.decode("utf-8")
    return {"delivery": DELIVERY, "diff_bytes": len(raw), "diff_chars": len(text),
            "max_native_json_bytes": MAX_NATIVE_JSON_BYTES, "max_tool_return_bytes": MAX_TOOL_RETURN_BYTES,
            "chunk_count": len(page_ranges(text))}


@lru_cache(maxsize=4)
def page_ranges(text):
    """Greedy ranges bounded by serialized text cost in both output layers.

    Plain ASCII, quotes, controls and Unicode have different costs. No fixed
    character increase can enforce these two limits. Reserve metadata before
    partitioning, then verify the complete real JSON at delivery/collection.
    """
    ranges = []
    start = native = outer = 0
    for index, char in enumerate(text):
        code = ord(char)
        if char in {'"', '\\'}:
            ncost, ocost = 2, 4
        elif char in '\b\f\n\r\t':
            ncost, ocost = 2, 3
        elif code < 32:
            ncost, ocost = 6, 7
        elif code < 127:
            ncost = ocost = 1
        else:
            ncost, ocost = len(char.encode('utf-8')), 6 if code <= 0xFFFF else 12
        if native + ncost > MAX_NATIVE_JSON_BYTES - METADATA_RESERVE or outer + ocost > MAX_TOOL_RETURN_BYTES - 2 * METADATA_RESERVE:
            ranges.append((start, index))
            start, native, outer = index, 0, 0
        native += ncost
        outer += ocost
    if start < len(text):
        ranges.append((start, len(text)))
    return tuple(ranges)


def output_sizes(result):
    body = json.dumps(result, sort_keys=True, ensure_ascii=False) + '\n'
    envelope = json.dumps({'output': body, 'exit_code': 0}, ensure_ascii=True) + '\n'
    return len(body.encode('utf-8')), len(envelope.encode('utf-8')) + RETURN_METADATA_RESERVE


def require_bounded(result):
    native, returned = output_sizes(result)
    if native > MAX_NATIVE_JSON_BYTES or returned > MAX_TOOL_RETURN_BYTES:
        fail('review_diff_output_limit', 'serialized native JSON or outer tool-return bound exceeded')
    return result


def read_chunk(plan_path, index):
    """Bounded text delivery only; never repeats the fixture write attempt."""
    plan = read_plan(plan_path)
    child = os.environ.get("CODEX_THREAD_ID")
    if child in (None, plan["parent_thread"]):
        fail("review_probe_child_required")
    raw = Path(plan["diff"]).read_bytes()
    layout = delivery(raw)
    if type(index) is not int or not 0 <= index < layout["chunk_count"]:
        fail("review_diff_chunk_invalid")
    return read_chunk_result(plan, child, index)


def prepare(*, root, capture, diff, wave_id, runtime=None, pending_package=None):
    root = Path(root).resolve()
    rt = runtime or ce.Rollout()
    session = os.environ.get("CODEX_THREAD_ID")
    _, _, meta, turns = rt.session(session)
    if turns[-1]["sandbox_policy"].get("type") == "read-only":
        fail("review_probe_prepare_requires_writable")
    if Path(turns[-1]["cwd"]).resolve() != root:
        fail("worktree_mismatch")
    cap = validate_capture(load_capture(capture), client="codex")
    if cap["role"] not in REVIEWERS or not wave_id or wave_id == ce.UNAVAILABLE:
        fail("review_probe_plan_invalid")
    capture = inside(root, capture)
    diff = inside(root, diff)
    raw = diff.read_bytes()
    if not raw:
        fail("diff_unavailable")
    # UTF-8 output gives the reviewer the exact diff; truncation will not verify.
    raw.decode("utf-8")
    out = ce.destination(root)
    ce.check_writable_destination(out)
    fixture = out / f"review-probe-{cap['attempt_id']}.fixture"
    plan_file = out / f"review-probe-{cap['attempt_id']}.plan.json"
    if fixture.exists() or plan_file.exists():
        fail("attempt_conflict")
    # This pre-wave write establishes an owner-writable disposable fixture.
    fd = os.open(fixture, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(os.urandom(32))
    helper = inside(root, Path(__file__).resolve())
    plan_body = {"schema": SCHEMA, "root": str(root), "plan_path": str(plan_file), "parent_thread": session if not pending_package else ce.UNAVAILABLE,
                      "host": meta["originator"], "host_version": meta["cli_version"],
                      "role": cap["role"], "attempt_id": cap["attempt_id"], "wave_id": wave_id,
                      "capture_path": str(capture), "capture_sha256": ce.digest(cap),
                      "diff": str(diff), "diff_sha256": ce.digest(raw), "helper": str(helper),
                      "helper_sha256": ce.digest(helper.read_bytes()), "fixture": str(fixture),
                      "interpreter": str(Path(sys.executable).resolve()), "interpreter_sha256": ce.digest(Path(sys.executable).read_bytes()),
                      "fixture_sha256": ce.digest(fixture.read_bytes())}
    if pending_package:
        plan_body.update(dedicated_package=str(inside(root, pending_package)), host=ce.UNAVAILABLE)
    plan = ce.sealed(plan_body)
    ce.private_write(plan_file, plan)
    fixed_command = shlex.join([plan["interpreter"], "-I", plan["helper"], "run", "--plan", str(plan_file)])
    return {"plan": str(plan_file), "command": fixed_command, "result": "prepared"}


def run(plan_path):
    plan = read_plan(plan_path)
    if os.environ.get("CODEX_THREAD_ID") in (None, plan["parent_thread"]):
        fail("review_probe_child_required")
    raw = Path(plan["diff"]).read_bytes()
    fixture = Path(plan["fixture"])
    before = fixture.read_bytes()
    denied = None
    try:
        # Different bytes would expose an ineffective sandbox on this disposable file.
        with fixture.open("r+b", buffering=0) as stream:
            stream.write(bytes(b ^ 255 for b in before))
    except OSError as exc:
        if exc.errno not in {errno.EACCES, errno.EPERM, errno.EROFS}:
            raise
        denied = exc.errno
    after = fixture.read_bytes()
    result = {"schema": SCHEMA, "plan_sha256": plan["integrity_sha256"],
            "child_thread": os.environ["CODEX_THREAD_ID"], "role": plan["role"],
            "attempt_id": plan["attempt_id"], "wave_id": plan["wave_id"],
            "diff": plan["diff"], "diff_sha256": ce.digest(raw),
            "fixture": plan["fixture"], "before_sha256": ce.digest(before),
            "denied_errno": denied, "after_sha256": ce.digest(after)}
    inline = dict(result, diff_text=raw.decode("utf-8"))
    if len(raw.decode("utf-8")) <= CHUNK_CHARS and all(actual <= cap for actual, cap in zip(output_sizes(inline), (MAX_NATIVE_JSON_BYTES, MAX_TOOL_RETURN_BYTES))):
        result = inline
    else:
        result.update(delivery(raw))
        result["read_command_template"] = _read_command(plan, plan_path, 0).rsplit(" ", 1)[0] + " <chunk_index>"
        result["next_read_command"] = _read_command(plan, plan_path, 0)
    return require_bounded(result)


def delivered_source(rows, ordinal, result, source):
    """Require bytes actually returned by the native tool, not just its log.

    CommandExecution and the enclosing model-visible tool return can truncate
    independently. Both native records must contain the same complete JSON.
    Supported shapes are the observed exec wrapper and direct exec tool JSON;
    unknown/async/multiple-command shapes remain unavailable.
    """
    calls = [(i, row, sha) for i, row, sha in rows if i < ordinal and row["type"] == "response_item"
             and row["payload"].get("type") in {"custom_tool_call", "function_call"}]
    if not calls:
        fail("review_diff_delivery_unavailable", "native enclosing tool call is missing")
    ci, call, csha = calls[-1]
    value = call["payload"]
    if value.get("name") not in {"exec", "exec_command", "write_stdin"} or not value.get("call_id"):
        fail("review_diff_delivery_unavailable", "unsupported delivery tool")
    next_call = min((i for i, row, _ in rows if i > ci and row["type"] == "response_item"
                     and row["payload"].get("type") in {"custom_tool_call", "function_call"}), default=float("inf"))
    outputs = [(i, row, sha) for i, row, sha in rows if ordinal < i < next_call and row["type"] == "response_item"
               and row["payload"].get("type") in {"custom_tool_call_output", "function_call_output"}
               and row["payload"].get("call_id") == value["call_id"]]
    commands = [i for i, row, _ in rows if ci < i < (outputs[0][0] if len(outputs) == 1 else next_call)
                and row["type"] == "event_msg" and row["payload"].get("type") == "item_completed"
                and row["payload"].get("item", {}).get("type") == "CommandExecution"]
    if len(outputs) != 1 or commands != [ordinal]:
        fail("review_diff_delivery_unavailable", "one native command and one corresponding returned output are required")
    oi, output, osha = outputs[0]
    content = output["payload"].get("output")
    if isinstance(content, str):
        texts = [content]
    elif isinstance(content, list) and all(isinstance(p, dict) and p.get("type") in {"input_text", "output_text"} and isinstance(p.get("text"), str) for p in content):
        texts = [p["text"] for p in content]
    else:
        fail("review_diff_delivery_unavailable", "unsupported native returned output schema")
    found = 0
    for text in texts:
        try:
            candidate = json.loads(text)
        except (TypeError, ValueError):
            # Script wrapper status can be separate from its JSON content.
            if "truncated" in text.lower() or "Script running" in text:
                fail("review_diff_delivery_truncated")
            continue
        if isinstance(candidate, dict) and isinstance(candidate.get("output"), str):
            if candidate.get("exit_code") != 0 or candidate.get("session_id") is not None:
                continue
            try:
                candidate = json.loads(candidate["output"])
            except ValueError:
                continue
        if candidate == result:
            found += 1
    if found != 1:
        fail("review_diff_delivery_truncated", "the full exact JSON did not reach the model-visible native tool return")
    return [{"source": str(source), "ordinal": ci, "raw_sha256": csha, "call_id": value["call_id"]},
            {"source": str(source), "ordinal": oi, "raw_sha256": osha, "call_id": value["call_id"]}]


def observe(birth, proof, *, runtime=None):
    """Re-read the exact native command/result and validate every probe binding."""
    rt = runtime or ce.Rollout()
    if birth.get("envelope_state") == "pending_coordinator":
        from codex_review_session import resolve_envelope
        birth = resolve_envelope(birth, runtime=rt)
    path = birth.get("review_probe_plan")
    if not path:
        fail("review_probe_unavailable")
    plan = read_plan(path, runtime=rt)
    expected = {"root": birth["root"], "parent_thread": birth["parent_thread"],
                "role": birth["role"], "attempt_id": birth["attempt_id"],
                "wave_id": birth["wave_id"], "diff_sha256": birth["review_diff_sha256"]}
    if any(plan.get(k) != v for k, v in expected.items()) or plan["integrity_sha256"] != birth.get("review_probe_plan_sha256"):
        fail("review_probe_binding_mismatch")
    source, rows, meta, turns = rt.session(proof["child_thread"])
    if meta["originator"] != plan["host"]:
        fail("review_probe_identity_mismatch")
    if any(t["sandbox_policy"].get("type") != "read-only" for t in turns) or proof["parent_sandbox"] != "read-only":
        fail("review_probe_sandbox_mismatch")
    expected_command = command(path, runtime=rt)
    matches = []
    chunk_sources = []
    delivery_sources = []
    chunks = {}
    layout = delivery(Path(plan["diff"]).read_bytes())
    expected_reads = {_read_command(plan, path, index): index for index in range(layout["chunk_count"])}
    chunked = False
    ended = False
    active_turn = None
    work_seen = False
    prior_commands = 0
    for i, row, sha in rows:
        value = row["payload"]
        if row["type"] == "event_msg" and value.get("type") in {"task_complete", "turn_aborted"}:
            ended = True
        if row["type"] == "event_msg" and value.get("type") == "thread_settings_applied":
            profile = value.get("thread_settings", {}).get("permission_profile", {})
            if isinstance(profile, dict) and profile.get("type") == "disabled":
                fail("review_probe_sandbox_mismatch", "native permission profile is disabled")
            if work_seen:
                fail("review_probe_sandbox_mismatch", "native settings changed after reviewer tools started")
        if row["type"] == "turn_context":
            if active_turn != value["turn_id"]:
                work_seen = False
            active_turn = value["turn_id"]
        if row["type"] == "response_item" and value.get("type") in {"custom_tool_call", "function_call"}:
            work_seen = True
        item = value.get("item", {})
        if not isinstance(item, dict):
            continue
        if row["type"] != "event_msg" or value.get("type") != "item_completed" or item.get("type") != "CommandExecution":
            continue
        prior_commands += 1
        if ended:
            fail("review_probe_after_completion", "delivery cannot be appended after the review payload")
        work_seen = True
        argv = item.get("command")
        if isinstance(argv, list) and len(argv) == 3 and argv[0] in {"/bin/bash", "/usr/bin/bash"} and argv[1] in {"-lc", "-c"} and argv[2] in expected_reads:
            index = expected_reads[argv[2]]
            if not chunked or len(matches) != 1 or index != len(chunks):
                fail("review_diff_chunk_order", "chunks require one preceding probe and consecutive indexes")
            if (value.get("thread_id") != proof["child_thread"] or value.get("turn_id") != active_turn
                    or active_turn != matches[0]["turn_id"] or Path(_native_cwd(item.get("cwd", ""))).resolve() != Path(birth["root"])
                    or item.get("status") != "completed" or item.get("exit_code") != 0
                    or item.get("source") not in {"unified_exec_startup", "unified_exec_poll"} or not item.get("id")):
                fail("review_diff_chunk_source_invalid")
            try:
                result = json.loads(item["aggregated_output"])
            except (ValueError, KeyError, TypeError):
                fail("review_diff_chunk_output_invalid")
            expected = read_chunk_result(plan, proof["child_thread"], index)
            if result != expected:
                fail("review_diff_chunk_output_mismatch")
            chunks[index] = result["diff_text"]
            chunk_sources.append({"source": str(source), "ordinal": i, "raw_sha256": sha,
                                  "command_id": item["id"], "turn_id": active_turn})
            delivery_sources += delivered_source(rows, i, result, source)
            continue
        # This is the native shell argv, including nested functions.exec calls.
        if not isinstance(argv, list) or len(argv) != 3 or argv[0] not in {"/bin/bash", "/usr/bin/bash"} or argv[1] not in {"-lc", "-c"} or argv[2] != expected_command:
            continue
        if birth.get("dedicated_package") and prior_commands != 1:
            fail("review_probe_not_first", "the fixed diagnostic must precede other reviewer commands")
        if value.get("thread_id") != proof["child_thread"] or value.get("turn_id") != active_turn:
            fail("review_probe_identity_mismatch")
        cwd = item.get("cwd", "")
        parsed = urlparse(cwd)
        cwd = unquote(parsed.path) if parsed.scheme == "file" and not parsed.netloc else cwd
        if Path(cwd).resolve() != Path(birth["root"]) or item.get("status") != "completed" or item.get("exit_code") != 0 or item.get("source") not in {"unified_exec_startup", "unified_exec_poll"} or not item.get("id"):
            fail("review_probe_command_incomplete")
        try:
            result = json.loads(item["aggregated_output"])
        except (ValueError, KeyError, TypeError):
            fail("review_probe_output_invalid")
        if not isinstance(result, dict):
            fail("review_probe_output_invalid")
        require_bounded(result)
        wanted = {"schema": SCHEMA, "plan_sha256": plan["integrity_sha256"],
                  "child_thread": proof["child_thread"], "role": plan["role"],
                  "attempt_id": plan["attempt_id"], "wave_id": plan["wave_id"],
                  "diff": plan["diff"], "diff_sha256": plan["diff_sha256"],
                  "fixture": plan["fixture"], "before_sha256": plan["fixture_sha256"],
                  "after_sha256": plan["fixture_sha256"]}
        chunked = result.get("delivery") == DELIVERY
        if chunked:
            template = _read_command(plan, path, 0).rsplit(" ", 1)[0] + " <chunk_index>"
            if (any(result.get(k) != v for k, v in layout.items()) or "diff_text" in result
                    or result.get("read_command_template") != template or result.get("next_read_command") != _read_command(plan, path, 0)):
                fail("review_probe_output_mismatch")
        elif not isinstance(result.get("diff_text"), str) or ce.digest(result["diff_text"].encode()) != plan["diff_sha256"] or len(result["diff_text"]) > CHUNK_CHARS:
            fail("review_probe_output_mismatch")
        if any(result.get(k) != v for k, v in wanted.items()) or type(result.get("denied_errno")) is not int or result["denied_errno"] not in {errno.EACCES, errno.EPERM, errno.EROFS}:
            fail("review_probe_output_mismatch")
        matches.append({"source": str(source), "ordinal": i, "raw_sha256": sha,
                        "command_id": item["id"], "turn_id": active_turn})
        delivery_sources += delivered_source(rows, i, result, source)
    if len(matches) != 1:
        fail("review_probe_unavailable", "exactly one complete native CommandExecution is required")
    if chunked and (set(chunks) != set(range(layout["chunk_count"])) or ce.digest("".join(chunks[i] for i in range(layout["chunk_count"])).encode()) != plan["diff_sha256"]):
        fail("review_diff_delivery_incomplete", "every exact native text chunk is required; a manifest is not full diff delivery")
    return {"schema": SCHEMA, "validation": "verified", "plan": str(Path(path).resolve()),
            "plan_sha256": plan["integrity_sha256"], "diff": plan["diff"],
            "diff_sha256": plan["diff_sha256"], "child_thread": proof["child_thread"],
            "role": plan["role"], "sources": matches + chunk_sources + delivery_sources, "diff_read": "verified",
            "delivery": DELIVERY if chunked else "native-inline-text", "delivered_bytes": layout["diff_bytes"],
            "write_denial_readback": "verified", "limitation": "native diagnostic delivery and disposable write denial; no internal context or semantic-understanding attestation"}


def _native_cwd(cwd):
    parsed = urlparse(cwd)
    return unquote(parsed.path) if parsed.scheme == "file" and not parsed.netloc else cwd


def read_chunk_result(plan, child, index):
    raw = Path(plan["diff"]).read_bytes()
    text = raw.decode("utf-8")
    ranges = page_ranges(text)
    if type(index) is not int or not 0 <= index < len(ranges):
        fail('review_diff_chunk_invalid')
    start, end = ranges[index]
    return require_bounded({"schema": SCHEMA, "plan_sha256": plan["integrity_sha256"], "child_thread": child,
            "diff": plan["diff"], "diff_sha256": plan["diff_sha256"], "delivery": DELIVERY,
            "next_read_command": _read_command(plan, plan["plan_path"], index + 1) if index + 1 < len(ranges) else None,
            "chunk_index": index, "start_char": start, "end_char": end, "diff_text": text[start:end]})


def qualify(evidence_paths, *, root, runtime=None):
    rt = runtime or ce.Rollout()
    observations = []
    parents, children, roles, waves, diffs = set(), set(), set(), set(), set()
    for path in evidence_paths:
        proof = ce.verify_evidence(path, runtime=rt)
        if not proof["qualification"] or proof["root"] != str(Path(root).resolve()):
            fail("review_probe_not_diagnostic")
        observation = observe(proof["birth"], proof, runtime=rt)
        parents.add((proof["parent_thread"], proof.get("native_parent_turn", proof["birth"]["parent_turn"]), proof["host"]))
        children.add(proof["child_thread"]); roles.add(proof["role"])
        waves.add(proof["wave_id"]); diffs.add((observation["diff"], observation["diff_sha256"]))
        observations.append({"evidence": str(Path(path).resolve()), "evidence_sha256": proof["integrity_sha256"], "observation": observation})
    if len(observations) != 2 or len(parents) != 1 or len(children) != 2 or roles != REVIEWERS or len(waves) != 1 or len(diffs) != 1:
        fail("review_probe_wave_mismatch")
    receipt = ce.sealed({"schema": SCHEMA, "root": str(Path(root).resolve()),
                         "parent_thread": next(iter(parents))[0], "host": next(iter(parents))[2],
                         "helper_sha256": ce.digest(Path(__file__).read_bytes()), "observations": observations})
    out = ce.destination(root)
    target = out / f"review-probe-qualification-{receipt['integrity_sha256']}.json"
    ce.private_write(target, receipt)
    return {"qualification": str(target), "result": "qualified"}


def verify_qualification(*, root, session, runtime=None, expected_path=None):
    rt = runtime or ce.Rollout()
    host = rt.session(session)[2]["originator"]
    candidates = [inside(root, expected_path)] if expected_path else sorted(ce.destination(root).glob("review-probe-qualification-*.json"))
    valid = []
    for path in candidates:
        receipt = ce.check_seal(json.loads(path.read_text()))
        if receipt.get("root") != str(Path(root).resolve()) or receipt.get("parent_thread") != session or receipt.get("host") != host:
            continue
        if receipt.get("helper_sha256") != ce.digest(Path(__file__).read_bytes()):
            fail("review_probe_source_changed")
        roles, children, parents, diffs = set(), set(), set(), set()
        for entry in receipt["observations"]:
            proof = ce.verify_evidence(entry["evidence"], runtime=rt)
            if proof["root"] != str(Path(root).resolve()) or proof["parent_thread"] != session or proof["host"] != host:
                fail("review_probe_binding_mismatch")
            observation = observe(proof["birth"], proof, runtime=rt)
            if proof["integrity_sha256"] != entry["evidence_sha256"] or observation != entry["observation"] or not proof["qualification"]:
                fail("review_probe_source_changed")
            roles.add(proof["role"]); children.add(proof["child_thread"])
            parents.add((proof["parent_thread"], proof.get("native_parent_turn", proof["birth"]["parent_turn"])))
            diffs.add((observation["diff"], observation["diff_sha256"]))
        if roles != REVIEWERS or len(children) != 2 or len(parents) != 1 or len(diffs) != 1 or len(receipt["observations"]) != 2:
            fail("review_probe_wave_mismatch")
        valid.append(path)
    if not valid:
        fail("review_probe_qualification_missing")
    selected = valid[-1]
    return {"result": "verified", "qualification": str(selected), "qualification_sha256": ce.check_seal(json.loads(selected.read_text()))["integrity_sha256"], "review_diff_read": "verified", "review_write_denial_readback": "verified"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    for field in ("root", "capture", "diff", "wave-id"):
        prep.add_argument("--" + field, required=True)
    run_parser = sub.add_parser("run"); run_parser.add_argument("--plan", required=True)
    read_parser = sub.add_parser("read"); read_parser.add_argument("--plan", required=True)
    read_parser.add_argument("--chunk", required=True, type=int)
    qual = sub.add_parser("qualify"); qual.add_argument("--root", required=True)
    qual.add_argument("--evidence", action="append", required=True)
    args = parser.parse_args()
    try:
        if args.action == "run":
            result = run(args.plan)
        elif args.action == "read":
            result = read_chunk(args.plan, args.chunk)
        elif args.action == "prepare":
            result = prepare(root=args.root, capture=args.capture, diff=args.diff, wave_id=args.wave_id)
        else:
            result = qualify(args.evidence, root=args.root)
        print(json.dumps(result, sort_keys=True, ensure_ascii=False))
        return 0
    except (ce.EvidenceError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({"result": "blocked", "code": getattr(exc, "code", "review_probe_unavailable"), "detail": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
