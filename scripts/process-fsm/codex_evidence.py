"""Codex rollout-v1 evidence: native birth, all turns and native returned payload.

The SQLite index is only a locator. Local hashes detect corruption, not a server
attestation. No prompts, full transcripts, or manually supplied observations are
persisted. Ordinary work requires a real qualification of this driver schema.

A host version is accepted when the rollout records the driver reads match the
declared `codex_exec/rollout-v1` schema, never by a version number: the
`cli_version` is recorded in the receipt and the evidence and refuses nothing on
its own. Host names are diagnostic metadata. Schema, session binding and a real
qualification of each host surface are checked independently.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from model_selection import load_capture, request_role, validate_capture

SCHEMA = "codex-rollout-evidence-v1"
DRIVER = "codex_exec/rollout-v1"
# The first driver id embedded the version it was rehearsed on; it names the same schema.
LEGACY_DRIVERS = ("codex_exec/0.162.1/rollout-v1",)
NATIVE_DRIVER = "codex/rollout-v1"
ACCEPTED_DRIVERS = (NATIVE_DRIVER, DRIVER, *LEGACY_DRIVERS)
# Rollout record schema (`codex_exec/rollout-v1`): kind -> required `(field, type)` pairs.
ROLLOUT_SCHEMA = {
    "session_meta": (("id", str), ("originator", str), ("cli_version", str), ("cwd", str)),
    "turn_context": (("turn_id", str), ("cwd", str), ("sandbox_policy", dict)),
    "function_call": (("call_id", str), ("arguments", str)),
    "function_call_output": (("call_id", str), ("output", str)),
    "task_event": (("turn_id", str),),
    "agent_message": (("author", str), ("content", list)),
}


def check_rollout_schema(kind, payload, *, version="unavailable", where=""):
    """`unsupported_schema` naming the record kind, the field and the observed host version."""

    for field, expected in ROLLOUT_SCHEMA[kind]:
        value = payload.get(field) if isinstance(payload, dict) else None
        if not isinstance(value, expected) or (expected is str and not value.strip()):
            raise EvidenceError(
                "unsupported_schema",
                f"{kind} record{where} lacks `{field}` as {expected.__name__} on host version {version}",
                recovery="the host changed the rollout format: revalidate the driver against a real session; no version is refused by its number",
            )
DEFAULT_DEST = Path(".cursor/tmp/codex-evidence")
MAX_WAIT = 10.0
UNAVAILABLE = "unavailable"
if __name__ == "__main__":
    # The optional context driver shares this module's EvidenceError in CLI use.
    sys.modules["codex_evidence"] = sys.modules[__name__]

STAGE_CONTRACT = "codex-native-stage-v3"
LEGACY_STAGE_CONTRACT = "codex-native-stage-v2"
STAGE_CONTRACTS = {STAGE_CONTRACT, LEGACY_STAGE_CONTRACT}


def stage_capabilities(*, proof=None, parent_sandbox=UNAVAILABLE, review_observation=None):
    """Only source-verified observations are capabilities, never caller claims.

    rollout-v1 observes linkage/selection/cwd/lifecycle after a diagnostic birth.
    Operational context qualification is verified separately from lifecycle.
    Historical snapshots keep their original observations. Internal context and
    denied-write/readback require a separately revalidated native diagnostic.
    """
    verified = isinstance(proof, dict) and proof.get("validation") == "verified"
    return {
        "native_chat_linkage": "verified" if verified else UNAVAILABLE,
        "model_effort_observation": "verified" if verified else UNAVAILABLE,
        "worktree_binding": "verified" if verified else UNAVAILABLE,
        "completed_payload": "verified" if verified else UNAVAILABLE,
        "context_isolation": UNAVAILABLE,
        "diagnostic_work_barrier": UNAVAILABLE,
        "parent_read_only": "verified" if parent_sandbox == "read-only" else UNAVAILABLE,
        "review_diff_read": "verified" if review_observation else UNAVAILABLE,
        "review_write_denial_readback": "verified" if review_observation else UNAVAILABLE,
    }


def require_stage_capabilities(*, root, stage, capabilities):
    required = ["native_chat_linkage", "model_effort_observation", "worktree_binding", "context_isolation"]
    if stage in {"diff-reviewer", "code-reviewer", "Code Review", "pedir_review", "aceitar_sha"}:
        required += ["parent_read_only", "review_diff_read", "review_write_denial_readback"]
    missing = [name for name in required if capabilities.get(name) != "verified"]
    if missing:
        card = re.match(r"card-(\d+)-", Path(root).name)
        raise EvidenceError(
            "stage_capability_missing",
            f"{stage} do #{card[1] if card else UNAVAILABLE} impedido antes do trabalho: "
            f"garantia(s) ausente(s)={','.join(missing)}; etapa não executada. "
            "Nenhum filho de etapa deve nascer; uma barreira diagnóstica não comprovada não supre a garantia ausente.",
            recovery="preserve card/Status/artifacts; qualify an authoritative native capability source in the same chat; no external session",
            observed=capabilities,
        )


def require_review_guarantees(proof):
    """Historical lifecycle success does not satisfy the #1098 review contract."""
    capabilities = stage_capabilities(proof=proof, parent_sandbox=proof["parent_sandbox"])
    if proof.get("stage_contract") == STAGE_CONTRACT and not proof["qualification"]:
        from codex_context import verify_qualification as verify_context
        birth = proof["birth"]
        expected = Path(birth["context_qualification"])
        observation = verify_context(root=birth["root"], out=expected.parent,
                                     session=proof["parent_thread"], expected_path=expected)
        if observation["scope_sha256"] != birth["context_scope_sha256"]:
            raise EvidenceError("context_scope_mismatch")
        capabilities["context_isolation"] = "verified"
    if proof["birth"].get("review_probe_plan"):
        from codex_review_probe import observe
        observe(proof["birth"], proof)
        capabilities["review_diff_read"] = "verified"
        capabilities["review_write_denial_readback"] = "verified"
    require_stage_capabilities(root=proof["root"], stage="Code Review",
                               capabilities=capabilities)


class EvidenceError(ValueError):
    def __init__(self, code, detail="", *, recovery="recollect same birth after source/flush recovery", observed=UNAVAILABLE, child_thread=UNAVAILABLE, child_path=UNAVAILABLE):
        self.code, self.detail, self.recovery = code, detail, recovery
        self.observed = observed
        self.child_thread, self.child_path = child_thread, child_path
        super().__init__(f"{code}: {detail}; recovery={recovery}")


def failure_result(code, *, collecting=False):
    if code == "child_interrupted":
        return "interrupted"
    if collecting and code.startswith("review_probe_"):
        return "unverified" if code in {"review_probe_unavailable", "review_probe_output_invalid"} else "failed"
    if collecting and code == "turn_conflict":
        return "failed"
    if code in {"observed_mismatch", "child_sandbox_mismatch", "payload_unavailable", "terminal_unavailable", "return_payload_mismatch", "context_request_mismatch"}:
        return "failed"
    # An unreadable origin after a birth does not prove no work ran.
    return "unverified" if collecting and code in {"source_unavailable", "source_truncated", "source_malformed", "source_conflict"} else "blocked"


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
        version = meta.get("cli_version") if isinstance(meta.get("cli_version"), str) else UNAVAILABLE
        check_rollout_schema("session_meta", meta, version=version)
        turns = [r[1]["payload"] for r in rows if r[1].get("type") == "turn_context"]
        if not turns:
            raise EvidenceError("unsupported_schema", f"turn_context record absent on host version {version}")
        unique, by_id = [], {}
        for turn in turns:
            check_rollout_schema("turn_context", turn, version=version)
            if turn["turn_id"] in by_id:
                if turn != by_id[turn["turn_id"]] or unique[-1]["turn_id"] != turn["turn_id"]:
                    raise EvidenceError("turn_conflict", turn["turn_id"])
            else:
                unique.append(turn)
                by_id[turn["turn_id"]] = turn
        # Runtime may repeat an identical context in one turn. Keep every raw
        # row for provenance, but lifecycle has only one logical turn.
        return path, rows, meta, unique


def qualification_path(out, host):
    # Keep existing exec qualifications intact; surfaces can coexist in one worktree.
    name = "qualification.json" if host == "codex_exec" else f"qualification-{digest(host.encode())[:16]}.json"
    return Path(out) / name


def preflight(*, root, capture=None, dest=DEFAULT_DEST, thread=None, qualification=False, review=False, runtime=None, stage=None, qualification_reference=None):
    review = review or stage in {"diff-reviewer", "code-reviewer", "Code Review", "pedir_review"}
    rt = runtime or Rollout()
    session = thread or os.environ.get("CODEX_THREAD_ID")
    if not session:
        raise EvidenceError("session_unavailable", "CODEX_THREAD_ID missing")
    if stage and not qualification and thread and thread != os.environ.get("CODEX_THREAD_ID"):
        raise EvidenceError("chat_binding_mismatch", f"{stage}: --thread cannot replace the current card chat", recovery="use the same native card chat; no external orchestration session")
    path, rows, meta, turns = rt.session(session)
    if any(not isinstance(turns[-1].get(k), str) or not turns[-1][k] for k in ("model", "effort")):
        raise EvidenceError("observation_unavailable", "active turn model/effort fields unavailable")
    terminals = [r[1]["payload"] for r in rows if r[1].get("type") == "event_msg" and r[1]["payload"].get("type") == "task_complete"]
    if any(t.get("turn_id") == turns[-1]["turn_id"] for t in terminals):
        raise EvidenceError("session_inactive", "prepare requires the active spawn turn")
    root = Path(root).resolve()
    # The current runtime turn governs the working directory. session_meta.cwd
    # is historical after a native resume/rebind, not the active tool context.
    if Path(turns[-1]["cwd"]).resolve() != root:
        raise EvidenceError(
            "worktree_mismatch",
            f"requested={root}; session_cwd={meta['cwd']}; turn_cwd={turns[-1]['cwd']}",
            recovery="bind the native chat to the card worktree and verify its runtime cwd; shell workdir alone is not a session binding",
        )
    if review and turns[-1]["sandbox_policy"].get("type") != "read-only":
        if stage in {"pedir_review", "Code Review"} and not qualification:
            from codex_review_session import principal_preflight
            dedicated = principal_preflight(root=root, session=session, runtime=rt)
            if dedicated is not None:
                return dedicated
        card = re.match(r"card-(\d+)-", root.name)
        raise EvidenceError("parent_sandbox_mismatch", f"Code Review do #{card[1] if card else UNAVAILABLE} impedido: garantia=parent_read_only; review spawn session must be observed read-only", recovery="prepare and qualify the dedicated native read-only coordinator; no manual permission toggles")
    if capture is not None:
        validate_capture(load_capture(capture) if isinstance(capture, (str, Path)) else capture, client="codex")
    out = destination(root, dest)
    proof = None
    capability_reference = None
    if not qualification:
        from codex_qualification_index import Index
        explicit = qualification_reference or os.environ.get("COVENANT_CODEX_QUALIFICATION")
        legacy = [qualification_path(out, meta["originator"])]
        # Migration is a bounded list of original references, never recursive
        # discovery or a search through transcripts ordered by timestamps.
        legacy += [Path(p) for p in os.environ.get("COVENANT_CODEX_LEGACY_QUALIFICATIONS", "").split(os.pathsep) if p]
        try:
            proof, capability_reference = Index().discover(meta["originator"], explicit=explicit, legacy=legacy, runtime=rt)
        except EvidenceError as exc:
            # Preserve the existing public preflight classification while
            # exposing the exact discovery failure to recovery/checkpoints.
            raise EvidenceError("unverified", str(exc), recovery=exc.recovery,
                                observed={"qualification_cause": exc.code}) from exc
    capabilities = stage_capabilities(proof=proof, parent_sandbox=turns[-1]["sandbox_policy"].get("type"))
    context_qualification = {"result": "unavailable", "code": "context_qualification_missing"}
    if not qualification:
        from codex_context import verify_qualification as verify_context
        try:
            context_qualification = verify_context(root=root, out=out, session=session, runtime=rt)
            capabilities["context_isolation"] = "verified"
        except (EvidenceError, OSError, ValueError, KeyError) as exc:
            context_qualification = {"result": "unavailable", "code": getattr(exc, "code", "context_qualification_missing")}
    # This is the approved scoped operational criterion, never internal access.
    capabilities["internal_context_attestation"] = UNAVAILABLE
    review_qualification = {"result": UNAVAILABLE}
    if review and not qualification:
        from codex_review_probe import verify_qualification as verify_review
        try:
            review_qualification = verify_review(root=root, session=session, runtime=rt)
            for key in ("review_diff_read", "review_write_denial_readback"):
                capabilities[key] = "verified"
        except (EvidenceError, OSError, ValueError, KeyError) as exc:
            review_qualification = {"result": UNAVAILABLE, "code": getattr(exc, "code", "review_probe_qualification_missing")}
    if stage == "aceitar_sha" and not qualification:
        # Post-return persistence/transition is writable. The read-only fact
        # comes from both completed reviewers, not this later parent turn.
        from codex_review import verify_latest_wave, ReviewDiffError
        try:
            review_qualification = verify_latest_wave(root=root)
            for key in ("parent_read_only", "review_diff_read", "review_write_denial_readback"):
                capabilities[key] = "verified"
        except (EvidenceError, ReviewDiffError, OSError, ValueError, KeyError) as exc:
            review_qualification = {"result": UNAVAILABLE, "code": getattr(exc, "code", "review_wave_unverified")}
    if stage and not qualification:
        require_stage_capabilities(root=root, stage=stage, capabilities=capabilities)
    try:
        if review:
            # Inspection in the same native read-only chat never probes writes.
            # A future supported preparation path must preserve that guarantee.
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
    return {"result": "ready", "session": session, "parent_turn": turns[-1]["turn_id"], "source": str(path), "driver": DRIVER if meta["originator"] == "codex_exec" else NATIVE_DRIVER, "host": meta["originator"], "host_version": meta["cli_version"], "schema": SCHEMA, "qualification": qualification, "parent_sandbox": turns[-1]["sandbox_policy"]["type"], "source_records": len(rows), "destination": str(out), "capabilities": capabilities, "capability_reference": capability_reference, "context_qualification": context_qualification, "review_qualification": review_qualification}


def refinement_binding(root, card):
    """Explicit source/worktree refinement binding; never a product allow-list.

    The live board is queried before preparation and again before native spawn.
    Historical collection retains the state observed at birth, not today's q.
    """
    from resolve import resolve as resolve_card, UNBOUND
    from guard import github_status_provider
    if not str(card).isdigit():
        raise EvidenceError("refinement_card_invalid")
    local = resolve_card(root, root)
    if str(local["bound_card"]) not in {UNBOUND, str(card)}:
        raise EvidenceError("refinement_card_mismatch", f"expected={card}; observed={local['bound_card']}")
    status = github_status_provider(str(card))
    if status != "Em Refinamento":
        raise EvidenceError("refinement_status_mismatch", f"#{card}: Status={status}")
    return {"card": str(card), "status": status, "q_git": local["q_git"]}


def prepare(*, root, capture, task_name, dest=DEFAULT_DEST, qualification=False, review_diff_sha256=UNAVAILABLE, runtime=None, thread=None, wave_id=UNAVAILABLE, review_probe_plan=None, defer_review_turn=False, context_diagnostic=False, card=None, qualification_reference=None):
    cap = validate_capture(load_capture(capture), client="codex")
    review = cap["role"] in {"code-reviewer", "diff-reviewer"}
    if context_diagnostic and not qualification:
        raise EvidenceError("context_diagnostic_required")
    if defer_review_turn and (not review or not review_probe_plan):
        raise EvidenceError("review_preparation_invalid")
    # Deferred receipts are private preparation, not permission to spawn/work.
    # The actual read-only turn is resolved only from the later native call.
    pf = preflight(root=root, capture=cap, dest=dest, qualification=qualification or defer_review_turn, review=review and not defer_review_turn, runtime=runtime, thread=thread, stage=None if defer_review_turn else cap["role"], qualification_reference=qualification_reference)
    if not task_name or "/" in task_name:
        raise EvidenceError("invalid_task_name", task_name)
    if review and (len(review_diff_sha256) != 64 or any(c not in "0123456789abcdef" for c in review_diff_sha256)):
        raise EvidenceError("diff_unavailable")
    if review:
        check_writable_destination(Path(pf["destination"]))
    refinement = None
    if card is not None:
        if cap["role"] != "grill-card" or qualification:
            raise EvidenceError("refinement_card_invalid", "--card is only the explicit grill-card binding; diagnostics and product roles cannot adopt another card")
        refinement = refinement_binding(root, card)
    birth = sealed({"schema": SCHEMA, "capture": cap, "capture_path": str(Path(capture).resolve()), "root": str(Path(root).resolve()), "bound_card": Path(root).name.split("-")[1] if Path(root).name.startswith("card-") else UNAVAILABLE, "attempt_id": cap["attempt_id"], "role": cap["role"], "band": cap["band"], "task_name": task_name, "parent_thread": pf["session"], "parent_turn": pf["parent_turn"], "before_record": pf["source_records"], "qualification": qualification, "review_diff_sha256": review_diff_sha256, "wave_id": wave_id, "driver": pf["driver"], "parent_host": pf["host"], "stage_contract": STAGE_CONTRACT, "stage_status": UNAVAILABLE, "work_release": "diagnostic_only" if qualification else "stage"})
    if refinement is not None:
        birth = sealed({**{k: v for k, v in birth.items() if k != "integrity_sha256"},
                        "bound_card": str(card), "stage_status": refinement["status"],
                        "refinement_binding": refinement})
    if context_diagnostic:
        birth = sealed({**{k: v for k, v in birth.items() if k != "integrity_sha256"}, "context_diagnostic": "codex-context-contract-v1"})
    if review_probe_plan:
        from codex_review_probe import read_plan
        plan = read_plan(review_probe_plan)
        expected = {"root": str(Path(root).resolve()), "parent_thread": pf["session"], "role": cap["role"], "attempt_id": cap["attempt_id"], "wave_id": wave_id, "diff_sha256": review_diff_sha256}
        if any(plan.get(k) != v for k, v in expected.items()):
            raise EvidenceError("review_probe_binding_mismatch")
        birth.pop("integrity_sha256")
        birth.update(review_probe_plan=str(Path(review_probe_plan).resolve()), review_probe_plan_sha256=plan["integrity_sha256"])
        if defer_review_turn:
            birth.update(parent_turn="deferred_native_read_only", deferred_review_turn=True)
        birth = sealed(birth)
    if not qualification:
        if defer_review_turn:
            from codex_context import verify_qualification as verify_context
            pf["context_qualification"] = verify_context(root=root, out=Path(pf["destination"]), session=pf["session"], runtime=runtime)
            from codex_review_probe import verify_qualification as verify_review
            rq = verify_review(root=root, session=pf["session"], runtime=runtime)
            birth["review_qualification"] = rq["qualification"]
            birth["review_qualification_sha256"] = rq["qualification_sha256"]
        birth.pop("integrity_sha256")
        birth["context_qualification"] = pf["context_qualification"]["qualification_path"]
        birth["context_scope_sha256"] = pf["context_qualification"]["scope_sha256"]
        if pf.get("capability_reference") is not None:
            birth["capability_reference"] = pf["capability_reference"]["receipt"]
            birth["capability_identity"] = pf["capability_reference"]["identity"]
        birth = sealed(birth)
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
    if birth.get("envelope_state") == "pending_coordinator":
        from codex_review_session import resolve_envelope, preflight as dedicated_preflight
        dedicated_preflight(birth["dedicated_package"])
        birth = resolve_envelope(birth)
    if birth["root"] != str(Path(root).resolve()) or birth["task_name"] != arguments.get("task_name") or birth["parent_thread"] != os.environ.get("CODEX_THREAD_ID"):
        raise EvidenceError("birth_mismatch")
    if any(arguments.get(k) != v for k, v in birth["capture"]["arguments"].items()):
        raise EvidenceError("requested_mismatch")
    if arguments.get("fork_turns") != "none":
        raise EvidenceError("context_request_mismatch", "native child requires fork_turns=none; request is not effective isolation proof")
    if birth.get("refinement_binding"):
        bound = refinement_binding(root, birth["bound_card"])
        if (birth["role"] != "grill-card" or bound != birth["refinement_binding"]
                or re.search(r"#" + re.escape(birth["bound_card"]) + r"\b", prompt) is None):
            raise EvidenceError("refinement_card_mismatch", "spawn must name exactly the explicitly bound card in its live refinement state")
    if birth.get("dedicated_package") and birth["role"] in {"diff-reviewer", "code-reviewer"} and arguments.get("agent_type") != birth["role"]:
        raise EvidenceError("role_mismatch", "dedicated Review requires the named native profile before birth")
    if birth.get("deferred_review_turn"):
        if not birth.get("dedicated_package") and (birth["role"] not in {"diff-reviewer", "code-reviewer"} or not birth.get("review_probe_plan")):
            raise EvidenceError("review_preparation_invalid")
        if birth.get("review_probe_plan"):
            from codex_review_probe import read_plan
            plan = read_plan(birth["review_probe_plan"])
            if plan["integrity_sha256"] != birth["review_probe_plan_sha256"]:
                raise EvidenceError("review_probe_source_changed")
    if birth["qualification"]:
        from codex_context import plan_path
        plan_file = plan_path(Path(match[1]))
        if plan_file.exists():
            plan = check_seal(json.loads(plan_file.read_text()))
            if prompt != plan.get("requested_message"):
                raise EvidenceError("context_request_mismatch", "outgoing diagnostic differs from the captured REQUESTED prompt")
    if birth.get("dedicated_package"):
        from codex_review_session import preflight as dedicated_preflight
        return dedicated_preflight(birth["dedicated_package"])
    pf = preflight(root=root, capture=birth["capture"], dest=Path(match[1]).parent, qualification=birth["qualification"], review=birth["role"] in {"diff-reviewer", "code-reviewer"}, stage=birth["role"], qualification_reference=birth.get("capability_reference"))
    if birth.get("capability_identity") and pf["capability_reference"]["identity"] != birth["capability_identity"]:
        raise EvidenceError("qualification_reference_changed")
    if not birth["qualification"] and birth.get("stage_contract") == STAGE_CONTRACT:
        if pf["context_qualification"]["scope_sha256"] != birth["context_scope_sha256"]:
            raise EvidenceError("context_scope_mismatch")
        if birth.get("review_probe_plan") and not birth.get("dedicated_package"):
            from codex_review_probe import verify_qualification as verify_review
            rq = verify_review(root=root, session=birth["parent_thread"], expected_path=birth["review_qualification"])
            if rq["qualification_sha256"] != birth["review_qualification_sha256"]:
                raise EvidenceError("review_probe_source_changed")
    return pf


def _projection(rows, ordinals, source):
    return [{"source": str(source), "ordinal": i, "type": r["type"], "event_type": r["payload"].get("type", UNAVAILABLE), "raw_sha256": sha} for i, r, sha in rows if i in ordinals]


def extract(birth, *, runtime=None):
    rt = runtime or Rollout()
    check_seal(birth)
    source_birth = birth
    dedicated_chain = None
    if birth.get("envelope_state") == "pending_coordinator":
        from codex_review_session import resolve_envelope, binding
        birth = resolve_envelope(birth, runtime=rt)
        dedicated_chain = binding(birth["dedicated_package"], runtime=rt, complete=True)
    if birth.get("schema") != SCHEMA or birth.get("driver") not in ACCEPTED_DRIVERS:
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
    if birth.get("capability_reference"):
        from codex_qualification_index import Index
        capability, reference = Index().discover(parent_meta["originator"], explicit=birth["capability_reference"], runtime=rt)
        if reference["identity"] != birth.get("capability_identity"):
            raise EvidenceError("qualification_reference_changed", "birth's original capability identity changed")
    if birth.get("parent_host", "codex_exec") != parent_meta["originator"]:
        raise EvidenceError("host_mismatch", "spawn session host differs from birth receipt")
    if birth["driver"] != NATIVE_DRIVER and parent_meta["originator"] != "codex_exec":
        raise EvidenceError("host_mismatch", "legacy driver evidence is restricted to its original host")
    deferred = birth.get("deferred_review_turn", False)
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
        check_rollout_schema("function_call", v, version=parent_meta["cli_version"], where=f" (record {i})")
        try:
            args = json.loads(v["arguments"])
        except (KeyError, ValueError) as exc:
            raise EvidenceError("spawn_malformed") from exc
        if args.get("task_name") == birth["task_name"]:
            expected_turn = active_parent_turn if deferred else birth["parent_turn"]
            if v.get("namespace") != "collaboration" or v.get("internal_chat_message_metadata_passthrough", {}).get("turn_id") != expected_turn:
                raise EvidenceError("unsupported_schema", "native spawn namespace/turn metadata unavailable")
            if active_parent_turn != expected_turn:
                raise EvidenceError("turn_mismatch", "spawn belongs to another parent turn")
            calls.append((i, v, args))
    if len(calls) != 1:
        raise EvidenceError("birth_mismatch", f"expected one native spawn, found {len(calls)}", recovery="new checked birth required if no intact spawn origin")
    ci, call, args = calls[0]
    spawn_turn = call["internal_chat_message_metadata_passthrough"]["turn_id"]
    parent_turn = [t for t in parent_turns if t["turn_id"] == spawn_turn]
    if len(parent_turn) != 1:
        raise EvidenceError("turn_mismatch", "birth parent turn")
    if Path(parent_turn[0]["cwd"]).resolve() != Path(birth["root"]):
        raise EvidenceError("worktree_mismatch", "parent spawn turn")
    used_parent.update(i for i, r, s in parent if r["type"] == "turn_context" and r["payload"].get("turn_id") == spawn_turn)
    if not birth["qualification"] and request_role(args) != birth["role"]:
        raise EvidenceError("role_mismatch", "native role/title differs from capture")
    if birth.get("dedicated_package") and birth["role"] in {"diff-reviewer", "code-reviewer"} and args.get("agent_type") != birth["role"]:
        raise EvidenceError("role_mismatch", "dedicated Review requires both named native profiles")
    if any(args.get(k) != v for k, v in cap["arguments"].items()):
        raise EvidenceError("requested_mismatch", recovery="new checked birth required")
    if birth.get("stage_contract") in STAGE_CONTRACTS and args.get("fork_turns") != "none":
        raise EvidenceError("context_request_mismatch", "actual native spawn did not request isolated context")
    outputs = [(i, r["payload"]) for i, r, s in parent if r["type"] == "response_item" and r["payload"].get("type") == "function_call_output" and r["payload"].get("call_id") == call["call_id"]]
    if len(outputs) != 1:
        raise EvidenceError("spawn_return_unavailable")
    oi, output = outputs[0]
    check_rollout_schema("function_call_output", output, version=parent_meta["cli_version"], where=f" (record {oi})")
    if output.get("internal_chat_message_metadata_passthrough", {}).get("turn_id") != spawn_turn:
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
    identity = {"child_thread": child_id, "child_path": child_path}
    if meta.get("timestamp", "") < parent_meta.get("timestamp", ""):
        raise EvidenceError("birth_mismatch", "child predates parent")
    if Path(meta.get("cwd", "")).resolve() != Path(birth["root"]):
        raise EvidenceError("worktree_mismatch", "child session", **identity)
    relevant = []
    used_child = {0}
    seen_turns = {}
    for i, row, sha in child:
        v = row["payload"]
        if row["type"] == "turn_context":
            if v["turn_id"] in seen_turns:
                if v != seen_turns[v["turn_id"]]:
                    raise EvidenceError("turn_conflict", v["turn_id"])
                used_child.add(i)
                continue
            seen_turns[v["turn_id"]] = v
            observed = {"model": v.get("model") or UNAVAILABLE, "reasoning_effort": v.get("effort") or UNAVAILABLE}
            if observed != cap["arguments"]:
                raise EvidenceError("observed_mismatch", f"turn={v['turn_id']}", recovery="new checked birth required; do not resume/retune", observed=observed, **identity)
            if Path(v["cwd"]).resolve() != Path(birth["root"]):
                raise EvidenceError("worktree_mismatch", "child turn", **identity)
            sandbox = v["sandbox_policy"].get("type", UNAVAILABLE)
            if birth["role"] in {"diff-reviewer", "code-reviewer"} and sandbox != "read-only":
                raise EvidenceError("child_sandbox_mismatch", **identity)
            relevant.append({"turn_id": v["turn_id"], "observed": observed, "sandbox": sandbox})
            used_child.add(i)
    if birth["role"] in {"diff-reviewer", "code-reviewer"} and parent_turn[0]["sandbox_policy"].get("type") != "read-only":
        raise EvidenceError("parent_sandbox_mismatch")
    completes = []
    started = set()
    for i, row, sha in child:
        v = row["payload"]
        if row["type"] == "event_msg" and v.get("type") == "turn_aborted":
            raise EvidenceError("child_interrupted", "native runtime recorded turn_aborted; this is not completion", **identity)
        if row["type"] == "event_msg" and v.get("type") in {"task_started", "task_complete"}:
            check_rollout_schema("task_event", v, version=meta["cli_version"], where=f" ({v['type']}, record {i})")
            if v.get("turn_id") not in seen_turns:
                raise EvidenceError("turn_mismatch", "terminal/start belongs to unknown turn")
            used_child.add(i)
            if v["type"] == "task_started":
                started.add(v["turn_id"])
            else:
                payload = v.get("last_agent_message")
                if not isinstance(payload, str) or not payload.strip():
                    raise EvidenceError("payload_unavailable", **identity)
                completes.append((v["turn_id"], payload.strip()))
    if started != set(seen_turns) or {t for t, p in completes} != set(seen_turns) or len(completes) != len(seen_turns):
        raise EvidenceError("terminal_unavailable", "every work turn requires start/context/completion", **identity)
    returns = []
    for i, row, sha in parent:
        v = row["payload"]
        if i <= oi or row["type"] != "response_item" or v.get("type") != "agent_message" or v.get("author") != child_path:
            continue
        check_rollout_schema("agent_message", v, version=parent_meta["cli_version"], where=f" (record {i})")
        for content in v.get("content", []):
            text = content.get("text", "")
            if content.get("type") == "input_text" and text.startswith("Message Type: FINAL_ANSWER\n") and "\nPayload:\n" in text:
                returns.append((i, text.split("\nPayload:\n", 1)[1].strip()))
    if len(returns) != len(completes) or [p for i, p in returns] != [p for t, p in completes]:
        raise EvidenceError("return_payload_mismatch", "native FINAL_ANSWER must match each child terminal payload", **identity)
    used_parent.update([ci, oi, *[i for i, p in returns]])
    if birth["role"] in {"diff-reviewer", "code-reviewer"}:
        # Parent must stay read-only from this birth until this child's return.
        for i, row, sha in parent:
            if ci < i <= returns[-1][0] and row["type"] == "event_msg" and row["payload"].get("type") == "thread_settings_applied":
                raise EvidenceError("parent_sandbox_mismatch", "parent settings changed during the read-only reviewer interval; requalify a new native turn")
            if ci < i <= returns[-1][0] and row["type"] == "turn_context":
                if row["payload"]["sandbox_policy"].get("type") != "read-only":
                    raise EvidenceError("parent_sandbox_mismatch", "parent became writable before reviewer returned")
                used_parent.add(i)
    result = {"schema": SCHEMA, "driver": birth["driver"], "birth": source_birth, "attempt_id": cap["attempt_id"], "bound_card": birth["bound_card"], "root": birth["root"], "role": birth["role"], "band": birth["band"], "parent_thread": birth["parent_thread"], "child_thread": child_id, "child_path": child_path, "call_id": call["call_id"], "host": meta["originator"], "host_version": meta["cli_version"], "requested": cap["arguments"], "turns": relevant, "parent_sandbox": parent_turn[0]["sandbox_policy"]["type"], "status": "completed", "payload_returned": True, "payload_sha256": [digest(p.encode()) for t, p in completes], "qualification": birth["qualification"], "review_diff_sha256": birth["review_diff_sha256"], "sources": _projection(parent, used_parent, parent_path) + _projection(child, used_child, child_source), "validation": "verified"}
    if dedicated_chain:
        result["dedicated_chain"] = dedicated_chain
        result["sources"] += dedicated_chain["sources"]
    if "wave_id" in birth:
        result["wave_id"] = birth["wave_id"]
    if deferred:
        result["native_parent_turn"] = spawn_turn
    if birth.get("review_probe_plan"):
        from codex_review_probe import observe
        result["review_observation"] = observe(birth, result, runtime=rt)
        result["sources"] += result["review_observation"]["sources"]
        if not birth["qualification"]:
            from codex_review_probe import verify_qualification as verify_review
            rq = verify_review(root=birth["root"], session=birth["parent_thread"], runtime=rt, expected_path=birth.get("review_qualification"))
            if not birth.get("dedicated_package") and rq["qualification_sha256"] != birth.get("review_qualification_sha256"):
                raise EvidenceError("review_probe_source_changed")
    if birth.get("stage_contract") in STAGE_CONTRACTS:
        result["stage_contract"] = birth["stage_contract"]
        result["stage_status"] = birth["stage_status"]
        result["work_release"] = birth["work_release"]
        result["native_arguments"] = {k: args.get(k, UNAVAILABLE) for k in ("task_name", "model", "reasoning_effort", "fork_turns", "agent_type")}
        result["capabilities"] = stage_capabilities(proof=result, parent_sandbox=result["parent_sandbox"])
        if birth.get("stage_contract") == STAGE_CONTRACT and not birth["qualification"]:
            from codex_context import verify_qualification as verify_context
            expected = Path(birth["context_qualification"])
            observation = verify_context(root=birth["root"], out=expected.parent, session=birth["parent_thread"], runtime=rt, expected_path=expected)
            if observation["scope_sha256"] != birth["context_scope_sha256"]:
                raise EvidenceError("context_scope_mismatch")
            result["context_scope_sha256"] = observation["scope_sha256"]
            result["capabilities"]["context_isolation"] = "verified"
            result["capabilities"]["internal_context_attestation"] = UNAVAILABLE
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
                outcome = failure_result(exc.code, collecting=True)
                failure = sealed({"schema": SCHEMA, "attempt_id": birth["attempt_id"], "bound_card": birth["bound_card"], "role": birth["role"], "band": birth["band"], "root": birth["root"], "stage_status": birth.get("stage_status", UNAVAILABLE), "parent_thread": birth["parent_thread"], "parent_turn": birth["parent_turn"], "child_thread": exc.child_thread, "child_path": exc.child_path, "capture_path": birth["capture_path"], "capture_sha256": birth["capture"]["capture_sha256"], "requested": birth["capture"]["arguments"], "observed": exc.observed, "result": outcome, "code": exc.code, "detail": exc.detail, "wait_seconds": wait_seconds, "recovery": exc.recovery})
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
    receipt = sealed({"driver": proof["driver"], "session": proof["parent_thread"], "evidence": str(Path(evidence_path).resolve()), "refusal_codes": [r["code"] for r in refusals], "refusals": [str(Path(p).resolve()) for p in refusal_paths]})
    parent_host = (runtime or Rollout()).session(proof["parent_thread"])[2]["originator"]
    private_write(qualification_path(Path(evidence_path).parent, parent_host), receipt)
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
        p.add_argument("--thread", help="authoritative session id of the actual spawn session in the same card chat")
        p.add_argument("--qualification-reference", type=Path, help="explicit immutable original capability receipt; context is still current-scope")
        if command == "prepare":
            p.add_argument("--task-name", required=True)
            p.add_argument("--card", help="explicit issue binding for grill-card in source or its matching worktree")
            p.add_argument("--review-diff-sha256", default=UNAVAILABLE)
            p.add_argument("--wave-id", default=UNAVAILABLE)
            p.add_argument("--review-probe-plan", type=Path)
            p.add_argument("--defer-review-turn", action="store_true", help="prepare while writable; actual native spawn must later be read-only in this same chat")
        else:
            p.add_argument("--review", action="store_true")
            p.add_argument("--stage", default="native-delegation", help="required stage guarantees; qualification is diagnostic only")
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
        stage = args.get("stage", "Code Review" if args.get("review") else UNAVAILABLE)
        if command in {"collect", "verify"}:
            try:
                origin = check_seal(json.loads(Path(args.get("birth") or args["evidence"]).read_text()))
                origin = origin.get("birth", origin)
                root, session, stage = origin["root"], origin["parent_thread"], origin["role"]
            except (OSError, ValueError, KeyError):
                pass
        elif args.get("capture"):
            try:
                stage = validate_capture(load_capture(args["capture"]), client="codex")["role"]
            except (OSError, ValueError):
                pass
        host, version, source = UNAVAILABLE, UNAVAILABLE, UNAVAILABLE
        if session != UNAVAILABLE:
            try:
                path, _, meta, _ = Rollout().session(session)
                host, version, source = meta["originator"], meta["cli_version"], str(path)
            except (EvidenceError, OSError, ValueError):
                pass  # No binary/config fallback for unavailable runtime.
        code = getattr(exc, "code", "invalid_input")
        print(json.dumps({"result": failure_result(code, collecting=command in {"collect", "verify"}), "schema": SCHEMA, "root": str(root), "bound_card": Path(root).name.split("-")[1] if Path(root).name.startswith("card-") else UNAVAILABLE, "stage": stage, "session": session, "child_thread": getattr(exc, "child_thread", UNAVAILABLE), "host": host, "host_version": version, "source": source, "code": code, "observed": getattr(exc, "observed", UNAVAILABLE), "detail": str(exc), "recovery": getattr(exc, "recovery", "restore source; preserve Status/artifacts")}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
