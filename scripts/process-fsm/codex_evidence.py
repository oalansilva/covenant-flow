"""Codex rollout-v1 evidence: native birth, all turns and native returned payload.

The SQLite index is only a locator. Local hashes detect corruption, not a server
attestation. No prompts, full transcripts, or manually supplied observations are
persisted. Ordinary work requires a real qualification of this host/version.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path

from model_selection import load_capture, request_role, validate_capture

SCHEMA = "codex-rollout-evidence-v1"
DRIVER = "codex_exec/0.162.1/rollout-v1"
DEFAULT_DEST = Path(".cursor/tmp/codex-evidence")
MAX_WAIT = 10.0
UNAVAILABLE = "unavailable"


class EvidenceError(ValueError):
    def __init__(self, code, detail="", *, recovery="recollect same birth after source/flush recovery", observed=UNAVAILABLE):
        self.code, self.detail, self.recovery = code, detail, recovery
        self.observed = observed
        super().__init__(f"{code}: {detail}; recovery={recovery}")


def digest(value):
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def sealed(value):
    return dict(value, integrity_sha256=digest(value))


def check_seal(value):
    if value.get("integrity_sha256") != digest({k: v for k, v in value.items() if k != "integrity_sha256"}):
        raise EvidenceError("integrity_mismatch", recovery="restore intact origin or create new birth")
    return value


def private_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or path.is_symlink():
        raise EvidenceError("unsafe_destination", str(path))
    os.chmod(path.parent, 0o700)
    encoded = json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2).encode() + b"\n"
    if path.exists():
        if path.read_bytes() == encoded:
            return path
        raise EvidenceError("attempt_conflict", str(path), recovery="preserve existing evidence; investigate origin")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".evidence-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return path


def destination(root, dest=DEFAULT_DEST):
    root = Path(root).resolve()
    path = Path(dest)
    if not path.is_absolute():
        path = root / path
    # Reject symlink traversal before resolve; do not chmod an external directory.
    if any(p.is_symlink() for p in [path, *path.parents]):
        raise EvidenceError("unsafe_destination", str(path))
    path = path.resolve()
    if root not in path.parents:
        raise EvidenceError("unsafe_destination", str(path))
    return path


def check_writable_destination(out):
    """Probe writes only in the writable orchestrator, including review prepare."""
    try:
        out.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, name = tempfile.mkstemp(dir=out, prefix=".preflight-")
        os.close(fd)
        Path(name).unlink()
    except OSError as exc:
        raise EvidenceError("destination_unwritable", str(exc)) from exc


class Rollout:
    def __init__(self, home=None):
        self.home = Path(home or Path.home() / ".codex").resolve()

    def locate(self, *, thread=None, agent_path=None):
        try:
            conn = sqlite3.connect(f"file:{self.home / 'state_5.sqlite'}?mode=ro", uri=True)
            with conn:
                fields = {r[1] for r in conn.execute("PRAGMA table_info(threads)")}
                if not {"id", "rollout_path", "agent_path"} <= fields:
                    raise EvidenceError("unsupported_schema", "runtime locator cannot correlate native child identity")
                rows = conn.execute("SELECT id, rollout_path FROM threads WHERE " + ("id=?" if thread else "agent_path=?"), (thread or agent_path,)).fetchall()
            conn.close()
        except (sqlite3.Error, OSError) as exc:
            raise EvidenceError("source_unavailable", str(exc)) from exc
        if not rows:
            raise EvidenceError("source_unavailable", thread or agent_path)
        return rows

    def read(self, path):
        path = Path(path).resolve()
        if self.home / "sessions" not in path.parents:
            raise EvidenceError("source_outside_runtime", str(path))
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise EvidenceError("source_unavailable", str(exc)) from exc
        if not raw.endswith(b"\n"):
            raise EvidenceError("source_truncated", str(path))
        rows = []
        for ordinal, line in enumerate(raw.splitlines()):
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get("payload"), dict):
                    raise ValueError("record object/payload missing")
            except (ValueError, TypeError) as exc:
                raise EvidenceError("source_malformed", f"{path}:{ordinal}") from exc
            rows.append((ordinal, row, digest(line)))
        return rows

    def session(self, thread):
        candidates = self.locate(thread=thread)
        if len(candidates) != 1:
            raise EvidenceError("source_conflict", thread)
        path = Path(candidates[0][1])
        rows = self.read(path)
        if not rows or rows[0][1].get("type") != "session_meta":
            raise EvidenceError("unsupported_schema", "rollout must start with session_meta")
        metas = [r[1]["payload"] for r in rows if r[1].get("type") == "session_meta"]
        if len(metas) != 1 or metas[0].get("id") != thread:
            raise EvidenceError("identity_mismatch", thread, recovery="new checked birth required")
        meta = metas[0]
        if (meta.get("originator"), meta.get("cli_version")) != ("codex_exec", "0.162.1"):
            raise EvidenceError("unsupported_host", f"{meta.get('originator', UNAVAILABLE)}/{meta.get('cli_version', UNAVAILABLE)}", recovery="qualify a versioned driver; installed binary is not runtime proof")
        turns = [r[1]["payload"] for r in rows if r[1].get("type") == "turn_context"]
        if not turns or any(not t.get("turn_id") or not t.get("cwd") or not isinstance(t.get("sandbox_policy"), dict) for t in turns):
            raise EvidenceError("unsupported_schema", "turn identity/cwd/sandbox missing")
        return path, rows, meta, turns


def preflight(*, root, capture=None, dest=DEFAULT_DEST, thread=None, qualification=False, review=False, runtime=None):
    rt = runtime or Rollout()
    session = thread or os.environ.get("CODEX_THREAD_ID")
    if not session:
        raise EvidenceError("session_unavailable", "CODEX_THREAD_ID missing")
    path, rows, meta, turns = rt.session(session)
    if any(not isinstance(turns[-1].get(k), str) or not turns[-1][k] for k in ("model", "effort")):
        raise EvidenceError("observation_unavailable", "active turn model/effort fields unavailable")
    terminals = [r[1]["payload"] for r in rows if r[1].get("type") == "event_msg" and r[1]["payload"].get("type") == "task_complete"]
    if any(t.get("turn_id") == turns[-1]["turn_id"] for t in terminals):
        raise EvidenceError("session_inactive", "prepare requires the active spawn turn")
    root = Path(root).resolve()
    if Path(meta.get("cwd", "")).resolve() != root or Path(turns[-1]["cwd"]).resolve() != root:
        raise EvidenceError("worktree_mismatch", str(root))
    if review and turns[-1]["sandbox_policy"].get("type") != "read-only":
        raise EvidenceError("parent_sandbox_mismatch", "review spawn session must be observed read-only")
    if capture is not None:
        validate_capture(load_capture(capture) if isinstance(capture, (str, Path)) else capture, client="codex")
    out = destination(root, dest)
    if not qualification:
        try:
            qualified = json.loads((out / "qualification.json").read_text())
            check_seal(qualified)
            proof = verify_evidence(qualified["evidence"], runtime=rt)
            if proof["driver"] != DRIVER or not proof["qualification"] or not qualified.get("refusal_codes"):
                raise EvidenceError("unverified", "qualification lacks positive proof and real refusals")
            refusals = [check_seal(json.loads(Path(p).read_text())) for p in qualified["refusals"]]
            if [r.get("code") for r in refusals] != qualified["refusal_codes"] or any(r.get("attempt_id") != proof["attempt_id"] or r.get("result") != "blocked" for r in refusals):
                raise EvidenceError("unverified", "qualification refusal integrity/binding mismatch")
        except (OSError, ValueError, KeyError) as exc:
            raise EvidenceError("unverified", str(exc), recovery="explicit qualification essay without product work or transition") from exc
    try:
        if review:
            # The actual spawning session stays read-only. A separate writable
            # orchestrator prepares the receipt and persists after both returns.
            if not out.is_dir():
                raise OSError("writable orchestrator must prepare private destination before read-only wave")
            if out.stat().st_mode & 0o777 != 0o700:
                raise EvidenceError("unsafe_destination", "prepared review destination must have mode 0700")
            # Open the directory for inspection; W_OK belongs to the writer's
            # sandbox and cannot prove availability from this read-only turn.
            with os.scandir(out):
                pass
        else:
            check_writable_destination(out)
    except OSError as exc:
        raise EvidenceError("destination_unwritable", str(exc)) from exc
    return {"result": "ready", "session": session, "parent_turn": turns[-1]["turn_id"], "source": str(path), "driver": DRIVER, "host": meta["originator"], "host_version": meta["cli_version"], "schema": SCHEMA, "qualification": qualification, "parent_sandbox": turns[-1]["sandbox_policy"]["type"], "source_records": len(rows), "destination": str(out)}


def prepare(*, root, capture, task_name, dest=DEFAULT_DEST, qualification=False, review_diff_sha256=UNAVAILABLE, runtime=None, thread=None, wave_id=UNAVAILABLE):
    cap = validate_capture(load_capture(capture), client="codex")
    review = cap["role"] in {"code-reviewer", "diff-reviewer"}
    pf = preflight(root=root, capture=cap, dest=dest, qualification=qualification, review=review, runtime=runtime, thread=thread)
    if not task_name or "/" in task_name:
        raise EvidenceError("invalid_task_name", task_name)
    if review and (len(review_diff_sha256) != 64 or any(c not in "0123456789abcdef" for c in review_diff_sha256)):
        raise EvidenceError("diff_unavailable")
    if review:
        check_writable_destination(Path(pf["destination"]))
    birth = sealed({"schema": SCHEMA, "capture": cap, "capture_path": str(Path(capture).resolve()), "root": str(Path(root).resolve()), "bound_card": Path(root).name.split("-")[1] if Path(root).name.startswith("card-") else UNAVAILABLE, "attempt_id": cap["attempt_id"], "role": cap["role"], "band": cap["band"], "task_name": task_name, "parent_thread": pf["session"], "parent_turn": pf["parent_turn"], "before_record": pf["source_records"], "qualification": qualification, "review_diff_sha256": review_diff_sha256, "wave_id": wave_id, "driver": DRIVER})
    target = Path(pf["destination"]) / f"{cap['attempt_id']}.birth.json"
    private_write(target, birth)
    return dict(pf, birth=str(target), arguments=cap["arguments"])


def check_prepared_spawn(arguments, root):
    """Trusted hooks reuse the explicit receipt; unavailable hook is no coverage."""
    prompt = arguments.get("message") or arguments.get("prompt") or ""
    match = re.search(r"^runtime_evidence_birth:\s*(\S+)\s*$", prompt, re.MULTILINE)
    if not match:
        raise EvidenceError("birth_receipt_missing", recovery="prepare checked birth before native spawn")
    birth = check_seal(json.loads(Path(match[1]).read_text()))
    if birth["root"] != str(Path(root).resolve()) or birth["task_name"] != arguments.get("task_name") or birth["parent_thread"] != os.environ.get("CODEX_THREAD_ID"):
        raise EvidenceError("birth_mismatch")
    if any(arguments.get(k) != v for k, v in birth["capture"]["arguments"].items()):
        raise EvidenceError("requested_mismatch")
    return preflight(root=root, capture=birth["capture"], dest=Path(match[1]).parent, qualification=birth["qualification"], review=birth["role"] in {"diff-reviewer", "code-reviewer"})


def _projection(rows, ordinals, source):
    return [{"source": str(source), "ordinal": i, "type": r["type"], "event_type": r["payload"].get("type", UNAVAILABLE), "raw_sha256": sha} for i, r, sha in rows if i in ordinals]


def extract(birth, *, runtime=None):
    rt = runtime or Rollout()
    check_seal(birth)
    if birth.get("schema") != SCHEMA or birth.get("driver") != DRIVER:
        raise EvidenceError("unsupported_schema")
    cap = validate_capture(birth["capture"], client="codex", role=birth["role"])
    if birth["attempt_id"] != cap["attempt_id"] or birth["band"] != cap["band"]:
        raise EvidenceError("birth_mismatch", "attempt/band differs from immutable capture")
    try:
        original_capture = load_capture(birth["capture_path"])
    except (OSError, ValueError) as exc:
        raise EvidenceError("capture_changed", str(exc), recovery="restore immutable birth capture or new birth required") from exc
    if original_capture != cap:
        raise EvidenceError("capture_changed", recovery="restore immutable birth capture or new birth required")
    parent_path, parent, parent_meta, parent_turns = rt.session(birth["parent_thread"])
    parent_turn = [t for t in parent_turns if t["turn_id"] == birth["parent_turn"]]
    if len(parent_turn) != 1:
        raise EvidenceError("turn_mismatch", "birth parent turn")
    calls = []
    used_parent = {0}
    active_parent_turn = None
    for i, row, sha in parent:
        v = row["payload"]
        if row["type"] == "turn_context":
            active_parent_turn = v.get("turn_id")
        if row["type"] == "turn_context" and v.get("turn_id") == birth["parent_turn"]:
            used_parent.add(i)
        if i < birth["before_record"] or row["type"] != "response_item" or v.get("type") != "function_call" or v.get("name") != "spawn_agent":
            continue
        try:
            args = json.loads(v["arguments"])
        except (KeyError, ValueError) as exc:
            raise EvidenceError("spawn_malformed") from exc
        if args.get("task_name") == birth["task_name"]:
            if v.get("namespace") != "collaboration" or v.get("internal_chat_message_metadata_passthrough", {}).get("turn_id") != birth["parent_turn"]:
                raise EvidenceError("unsupported_schema", "native spawn namespace/turn metadata unavailable")
            if active_parent_turn != birth["parent_turn"]:
                raise EvidenceError("turn_mismatch", "spawn belongs to another parent turn")
            calls.append((i, v, args))
    if len(calls) != 1:
        raise EvidenceError("birth_mismatch", f"expected one native spawn, found {len(calls)}", recovery="new checked birth required if no intact spawn origin")
    ci, call, args = calls[0]
    if not birth["qualification"] and request_role(args) != birth["role"]:
        raise EvidenceError("role_mismatch", "native role/title differs from capture")
    if any(args.get(k) != v for k, v in cap["arguments"].items()):
        raise EvidenceError("requested_mismatch", recovery="new checked birth required")
    outputs = [(i, r["payload"]) for i, r, s in parent if r["type"] == "response_item" and r["payload"].get("type") == "function_call_output" and r["payload"].get("call_id") == call["call_id"]]
    if len(outputs) != 1:
        raise EvidenceError("spawn_return_unavailable")
    oi, output = outputs[0]
    if output.get("internal_chat_message_metadata_passthrough", {}).get("turn_id") != birth["parent_turn"]:
        raise EvidenceError("turn_mismatch", "native spawn result belongs to another parent turn")
    try:
        child_path = json.loads(output["output"])["task_name"]
    except (KeyError, ValueError) as exc:
        raise EvidenceError("spawn_return_malformed") from exc
    if not child_path.endswith("/" + birth["task_name"]):
        raise EvidenceError("identity_mismatch", "native spawn task path")
    candidates = []
    for child_id, path in rt.locate(agent_path=child_path):
        cp, rows, meta, turns = rt.session(child_id)
        spawn = meta.get("source", {})
        spawn = spawn.get("subagent", {}).get("thread_spawn", {}) if isinstance(spawn, dict) else {}
        if spawn.get("parent_thread_id") == birth["parent_thread"] and spawn.get("agent_path") == child_path:
            candidates.append((child_id, cp, rows, meta, turns))
    if len(candidates) != 1:
        raise EvidenceError("source_conflict", "native path/parent must resolve exactly one child")
    child_id, child_source, child, meta, turns = candidates[0]
    if meta.get("timestamp", "") < parent_meta.get("timestamp", ""):
        raise EvidenceError("birth_mismatch", "child predates parent")
    if Path(meta.get("cwd", "")).resolve() != Path(birth["root"]):
        raise EvidenceError("worktree_mismatch", "child session")
    relevant = []
    used_child = {0}
    seen_turns = set()
    for i, row, sha in child:
        v = row["payload"]
        if row["type"] == "turn_context":
            if v["turn_id"] in seen_turns:
                raise EvidenceError("turn_conflict", v["turn_id"])
            seen_turns.add(v["turn_id"])
            observed = {"model": v.get("model") or UNAVAILABLE, "reasoning_effort": v.get("effort") or UNAVAILABLE}
            if observed != cap["arguments"]:
                raise EvidenceError("observed_mismatch", f"turn={v['turn_id']}", recovery="new checked birth required; do not resume/retune", observed=observed)
            if Path(v["cwd"]).resolve() != Path(birth["root"]):
                raise EvidenceError("worktree_mismatch", "child turn")
            sandbox = v["sandbox_policy"].get("type", UNAVAILABLE)
            if birth["role"] in {"diff-reviewer", "code-reviewer"} and sandbox != "read-only":
                raise EvidenceError("child_sandbox_mismatch")
            relevant.append({"turn_id": v["turn_id"], "observed": observed, "sandbox": sandbox})
            used_child.add(i)
    if birth["role"] in {"diff-reviewer", "code-reviewer"} and parent_turn[0]["sandbox_policy"].get("type") != "read-only":
        raise EvidenceError("parent_sandbox_mismatch")
    completes = []
    started = set()
    for i, row, sha in child:
        v = row["payload"]
        if row["type"] == "event_msg" and v.get("type") in {"task_started", "task_complete"}:
            if v.get("turn_id") not in seen_turns:
                raise EvidenceError("turn_mismatch", "terminal/start belongs to unknown turn")
            used_child.add(i)
            if v["type"] == "task_started":
                started.add(v["turn_id"])
            else:
                payload = v.get("last_agent_message")
                if not isinstance(payload, str) or not payload.strip():
                    raise EvidenceError("payload_unavailable")
                completes.append((v["turn_id"], payload.strip()))
    if started != seen_turns or {t for t, p in completes} != seen_turns or len(completes) != len(seen_turns):
        raise EvidenceError("terminal_unavailable", "every work turn requires start/context/completion")
    returns = []
    for i, row, sha in parent:
        v = row["payload"]
        if i <= oi or row["type"] != "response_item" or v.get("type") != "agent_message" or v.get("author") != child_path:
            continue
        for content in v.get("content", []):
            text = content.get("text", "")
            if content.get("type") == "input_text" and text.startswith("Message Type: FINAL_ANSWER\n") and "\nPayload:\n" in text:
                returns.append((i, text.split("\nPayload:\n", 1)[1].strip()))
    if len(returns) != len(completes) or [p for i, p in returns] != [p for t, p in completes]:
        raise EvidenceError("return_payload_mismatch", "native FINAL_ANSWER must match each child terminal payload")
    used_parent.update([ci, oi, *[i for i, p in returns]])
    result = {"schema": SCHEMA, "driver": DRIVER, "birth": birth, "attempt_id": cap["attempt_id"], "bound_card": birth["bound_card"], "root": birth["root"], "role": birth["role"], "band": birth["band"], "parent_thread": birth["parent_thread"], "child_thread": child_id, "child_path": child_path, "call_id": call["call_id"], "host": meta["originator"], "host_version": meta["cli_version"], "requested": cap["arguments"], "turns": relevant, "parent_sandbox": parent_turn[0]["sandbox_policy"]["type"], "status": "completed", "payload_returned": True, "payload_sha256": [digest(p.encode()) for t, p in completes], "qualification": birth["qualification"], "review_diff_sha256": birth["review_diff_sha256"], "sources": _projection(parent, used_parent, parent_path) + _projection(child, used_child, child_source), "validation": "verified"}
    if "wave_id" in birth:
        result["wave_id"] = birth["wave_id"]
    return result


def _verify_snapshot(envelope, fresh):
    """An accepted snapshot may only grow through intact completed work turns."""
    check_seal(envelope)
    growing = {"integrity_sha256", "turns", "payload_sha256", "sources"}
    if ({k: v for k, v in envelope.items() if k not in growing}
            != {k: v for k, v in fresh.items() if k not in growing}
            or fresh["turns"][:len(envelope["turns"])] != envelope["turns"]
            or fresh["payload_sha256"][:len(envelope["payload_sha256"])] != envelope["payload_sha256"]):
        raise EvidenceError("provenance_mismatch", "accepted birth/turn/payload changed", recovery="restore intact origin or new checked birth")
    sources = {(s["source"], s["ordinal"]): s for s in fresh["sources"]}
    if any(sources.get((s["source"], s["ordinal"])) != s for s in envelope["sources"]):
        raise EvidenceError("provenance_mismatch", "accepted source record changed", recovery="restore intact origin or new checked birth")


def _verify_snapshots(out, fresh):
    # Check every accepted revision: an old anchor must not conceal alteration
    # or removal of a turn first accepted by a later immutable snapshot.
    attempt = fresh["attempt_id"]
    paths = [out / f"{attempt}.evidence.json", *sorted(out.glob(f"{attempt}.evidence-*.json"))]
    for path in paths:
        if path.exists():
            _verify_snapshot(json.loads(path.read_text()), fresh)


def collect(birth_path, *, dest=None, wait_seconds=5.0, runtime=None):
    if not 0 <= wait_seconds <= MAX_WAIT:
        raise EvidenceError("invalid_wait", f"bounded window is 0..{MAX_WAIT}s")
    birth = check_seal(json.loads(Path(birth_path).read_text()))
    out = destination(birth["root"], dest or Path(birth_path).parent)
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            result = sealed(extract(birth, runtime=runtime))
            target = out / f"{birth['attempt_id']}.evidence.json"
            _verify_snapshots(out, result)
            if target.exists() and json.loads(target.read_text()) != result:
                target = out / f"{birth['attempt_id']}.evidence-{result['integrity_sha256']}.json"
            private_write(target, result)
            return dict(result, evidence_path=str(target))
        except EvidenceError as exc:
            if exc.code not in {"source_unavailable", "source_truncated", "spawn_return_unavailable", "terminal_unavailable", "return_payload_mismatch"} or time.monotonic() >= deadline:
                failure = sealed({"schema": SCHEMA, "attempt_id": birth["attempt_id"], "bound_card": birth["bound_card"], "role": birth["role"], "parent_thread": birth["parent_thread"], "capture_sha256": birth["capture"]["capture_sha256"], "requested": birth["capture"]["arguments"], "observed": exc.observed, "result": "blocked", "code": exc.code, "detail": exc.detail, "wait_seconds": wait_seconds, "recovery": exc.recovery})
                # Separate immutable failure from later successful recollection.
                private_write(out / f"{birth['attempt_id']}.failure-{digest(failure)[:12]}.json", failure)
                raise
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def verify_evidence(path, *, runtime=None):
    try:
        envelope = check_seal(json.loads(Path(path).read_text()))
        fresh = sealed(extract(envelope["birth"], runtime=runtime))
        _verify_snapshot(envelope, fresh)
        _verify_snapshots(Path(path).parent, fresh)
    except (OSError, KeyError, json.JSONDecodeError) as exc:
        raise EvidenceError("evidence_unavailable", str(exc)) from exc
    return envelope


def verify_proxy(entry, *, runtime=None):
    proof = verify_evidence(entry.get("runtime_evidence", ""), runtime=runtime)
    cap = proof["birth"]["capture"]
    bindings = {"activity": proof["role"], "band": proof["band"], "bound_card": proof["bound_card"], "child_id": proof["child_thread"], "host": proof["host"], "host_version": proof["host_version"], "selection_capture": cap, "status": proof["status"], "payload_returned": True, "requested_model": proof["requested"]["model"], "requested_effort": proof["requested"]["reasoning_effort"], "observed_model": proof["turns"][-1]["observed"]["model"], "observed_effort": proof["turns"][-1]["observed"]["reasoning_effort"], "sandbox_mode": proof["turns"][-1]["sandbox"], "review_diff_sha256": proof["review_diff_sha256"], "wave_id": proof.get("wave_id", UNAVAILABLE)}
    if any(entry.get(k) != v for k, v in bindings.items()):
        raise EvidenceError("proxy_binding_mismatch")
    if entry.get("evidence_sha256", proof["integrity_sha256"]) != proof["integrity_sha256"]:
        raise EvidenceError("proxy_binding_mismatch", "snapshot digest differs from proxy")
    return proof


def qualify(evidence_path, refusal_paths, *, runtime=None):
    proof = verify_evidence(evidence_path, runtime=runtime)
    if not proof["qualification"]:
        raise EvidenceError("not_qualification")
    refusals = [check_seal(json.loads(Path(p).read_text())) for p in refusal_paths]
    if not refusals or any(r.get("schema") != SCHEMA or r.get("result") != "blocked" or r.get("attempt_id") != proof["attempt_id"] for r in refusals):
        raise EvidenceError("refusal_proof_unavailable")
    receipt = sealed({"driver": DRIVER, "session": proof["parent_thread"], "evidence": str(Path(evidence_path).resolve()), "refusal_codes": [r["code"] for r in refusals], "refusals": [str(Path(p).resolve()) for p in refusal_paths]})
    private_write(Path(evidence_path).parent / "qualification.json", receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("preflight", "prepare"):
        p = sub.add_parser(command)
        p.add_argument("--root", type=Path, default=Path.cwd())
        p.add_argument("--capture", type=Path, required=command == "prepare")
        p.add_argument("--dest", type=Path, default=DEFAULT_DEST)
        p.add_argument("--qualification", action="store_true", help="explicit essay only; no product work or transition")
        p.add_argument("--thread", help="authoritative session id of the actual spawn session (including dedicated read-only wave)")
        if command == "prepare":
            p.add_argument("--task-name", required=True)
            p.add_argument("--review-diff-sha256", default=UNAVAILABLE)
            p.add_argument("--wave-id", default=UNAVAILABLE)
        else:
            p.add_argument("--review", action="store_true")
    p = sub.add_parser("collect")
    p.add_argument("--birth", required=True, type=Path)
    p.add_argument("--wait-seconds", type=float, default=5)
    p = sub.add_parser("verify")
    p.add_argument("--evidence", required=True, type=Path)
    p = sub.add_parser("qualify")
    p.add_argument("--evidence", required=True, type=Path)
    p.add_argument("--refusal", action="append", type=Path, required=True)
    args = vars(parser.parse_args(argv))
    command = args.pop("command")
    try:
        if command == "collect":
            result = collect(args["birth"], wait_seconds=args["wait_seconds"])
        elif command == "verify":
            result = verify_evidence(args["evidence"])
        elif command == "qualify":
            result = qualify(args["evidence"], args["refusal"])
        else:
            result = (prepare if command == "prepare" else preflight)(**args)
        # No source payload/prompt is printed or persisted.
        print(json.dumps(result, sort_keys=True))
        return 0
    except (EvidenceError, OSError, ValueError) as exc:
        root = args.get("root", Path.cwd())
        session = args.get("thread") or os.environ.get("CODEX_THREAD_ID", UNAVAILABLE)
        host, version, source = UNAVAILABLE, UNAVAILABLE, UNAVAILABLE
        if command in {"preflight", "prepare"} and session != UNAVAILABLE:
            try:
                path, _, meta, _ = Rollout().session(session)
                host, version, source = meta["originator"], meta["cli_version"], str(path)
            except (EvidenceError, OSError, ValueError):
                pass  # No binary/config fallback for unavailable runtime.
        print(json.dumps({"result": "blocked", "schema": SCHEMA, "root": str(root), "bound_card": Path(root).name.split("-")[1] if Path(root).name.startswith("card-") else UNAVAILABLE, "session": session, "host": host, "host_version": version, "source": source, "code": getattr(exc, "code", "invalid_input"), "observed": getattr(exc, "observed", UNAVAILABLE), "detail": str(exc), "recovery": getattr(exc, "recovery", "restore source; preserve Status/artifacts")}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
