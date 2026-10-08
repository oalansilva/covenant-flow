"""Validate requested vs observed routing for all five native harnesses."""
from __future__ import annotations
from typing import Any
from model_selection import validate_capture

UNAVAILABLE = "unavailable"
NOT_APPLICABLE = "not_applicable"


def evidence(*, capture: dict, observed: dict[str, Any], host: str, host_version: str,
             status: str, payload_returned: bool) -> dict:
    birth = validate_capture(capture, role=capture.get("role"))
    selected = birth["selection"]
    requested = {k: selected.get(k, NOT_APPLICABLE) for k in ("model", "provider", "effort", "variant")}
    actual = {k: observed.get(k, UNAVAILABLE) if requested[k] != NOT_APPLICABLE else NOT_APPLICABLE for k in requested}
    successful = status == "completed" and payload_returned and host not in ("", UNAVAILABLE) and host_version not in ("", UNAVAILABLE) and actual == requested
    return {"selection_capture": birth, "requested": requested, "observed": actual,
            "host": host or UNAVAILABLE, "host_version": host_version or UNAVAILABLE,
            "status": status, "payload_returned": bool(payload_returned), "successful": successful}


def verify_continuation(capture: dict, observed: dict, *, host: str, host_version: str,
                        status: str, payload_returned: bool) -> dict:
    result = evidence(capture=capture, observed=observed, host=host, host_version=host_version,
                      status=status, payload_returned=payload_returned)
    if not result["successful"]:
        from model_selection import SelectionError
        raise SelectionError("continuation rejected: observed runtime differs/unavailable or no completed payload; new spawn required, no retuning")
    return result
