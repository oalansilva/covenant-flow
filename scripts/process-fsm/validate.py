#!/usr/bin/env python3
"""Validate `.cursor/process-fsm.yaml`. Exit 1 on schema/matrix errors."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fsm import ValidationError, load_fsm, validate_fsm  # noqa: E402


def main() -> int:
    try:
        validate_fsm(load_fsm())
    except ValidationError as exc:
        print(f"process-fsm: {exc}", file=sys.stderr)
        return 1
    print("process-fsm: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
