"""Thin Cursor/Grok hook translation; selection never enters the process FSM."""
from __future__ import annotations
import argparse
import json
import sys
from model_selection import SelectionError, validate_spawn


def pre_tool(client: str, payload: dict) -> dict:
    try:
        arguments = payload.get("tool_input") or payload.get("toolInput") or payload.get("args") or {}
        if isinstance(arguments, str): arguments = json.loads(arguments)
        if not isinstance(arguments, dict): raise SelectionError("native tool input must be an object")
        validate_spawn(client, arguments)
        return {"permission": "allow", "decision": "allow"}
    except (SelectionError, ValueError, OSError) as exc:
        reason = f"model_selection deny: {exc}"
        return {"permission": "deny", "decision": "deny", "reason": reason, "agent_message": reason, "user_message": reason}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", required=True, choices=("cursor", "grok"))
    args = parser.parse_args()
    try:
        result = pre_tool(args.client, json.load(sys.stdin))
    except Exception as exc:
        result = {"permission": "deny", "decision": "deny", "reason": f"model_selection deny: {exc}"}
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
