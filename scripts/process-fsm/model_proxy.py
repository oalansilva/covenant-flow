"""Validate requested vs observed routing for every native harness."""
from __future__ import annotations
from typing import Any
from model_selection import validate_capture

UNAVAILABLE = "unavailable"
NOT_APPLICABLE = "not_applicable"


def evidence(*, capture: dict, observed: dict[str, Any], host: str, host_version: str,
             status: str, payload_returned: bool, runtime_evidence=None) -> dict:
    birth = validate_capture(capture, role=capture.get("role"))
    selected = birth["selection"]
    requested = {k: selected.get(k, NOT_APPLICABLE) for k in ("model", "provider", "effort", "variant")}
    actual = {k: observed.get(k, UNAVAILABLE) if requested[k] != NOT_APPLICABLE else NOT_APPLICABLE for k in requested}
    successful = status == "completed" and payload_returned and host not in ("", UNAVAILABLE) and host_version not in ("", UNAVAILABLE) and actual == requested
    if birth["client"] == "codex":
        # Historical declarations remain readable but cannot prove a new Codex
        # execution. Other adapters keep their existing evidence contract.
        successful = False
        if runtime_evidence is not None:
            from codex_evidence import verify_evidence
            proof = verify_evidence(runtime_evidence)
            successful = (proof["birth"]["capture"] == birth and proof["host"] == host and proof["host_version"] == host_version and proof["status"] == status and proof["payload_returned"] == payload_returned and proof["requested"]["model"] == actual["model"] and proof["requested"]["reasoning_effort"] == actual["effort"])
    if birth["client"] == "claude":
        # Claude Code evidence comes only from its sealed transcript envelope;
        # manual `observed` facts cannot prove a new Claude Code execution.
        successful = False
        if runtime_evidence is not None:
            from claude_evidence import verify_evidence as verify_claude
            proof = verify_claude(runtime_evidence)
            last = proof["turns"][-1]["observed"]
            successful = (proof["birth"]["capture"] == birth and proof["host"] == host and proof["host_version"] == host_version and proof["status"] == status and proof["payload_returned"] == payload_returned and last["model"] == actual["model"] and last["effort"] == actual["effort"] and proof["requested"] == {"model": requested["model"], "effort": requested["effort"]})
    result = {"selection_capture": birth, "requested": requested, "observed": actual,
            "host": host or UNAVAILABLE, "host_version": host_version or UNAVAILABLE,
            "status": status, "payload_returned": bool(payload_returned), "successful": successful}
    if birth["client"] in ("codex", "claude") and runtime_evidence is not None:
        result.update(runtime_evidence=str(runtime_evidence), evidence_sha256=proof["integrity_sha256"])
    if birth["client"] == "claude" and runtime_evidence is not None:
        result["surface"] = proof["surface"]
    return result


def verify_continuation(capture: dict, observed: dict, *, host: str, host_version: str,
                        status: str, payload_returned: bool, runtime_evidence=None) -> dict:
    result = evidence(capture=capture, observed=observed, host=host, host_version=host_version,
                      status=status, payload_returned=payload_returned, runtime_evidence=runtime_evidence)
    if not result["successful"]:
        from model_selection import SelectionError
        raise SelectionError("continuation rejected: observed runtime differs/unavailable or no completed payload; new spawn required, no retuning")
    return result
