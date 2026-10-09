"""Codex compatibility facade over the account-local selection resolver."""
from __future__ import annotations
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from model_selection import BANDS, SelectionError, resolve, validate_capture, role_band

ModelRoutingError = SelectionError

@dataclass(frozen=True)
class ModelPair:
    band: str
    label: str
    slug: str
    effort: str
    capture: dict

    def as_request(self) -> dict:
        return {"band": self.band, "label": self.label, "model": self.slug, "reasoning_effort": self.effort, "capture": self.capture}


def pair_from_capture(capture: dict, band: str | None = None) -> ModelPair:
    cap = validate_capture(capture, client="codex", band=band)
    entry = cap["selection"]
    return ModelPair(cap["band"], entry["label"], entry["model"], entry["effort"], cap)


def resolve_pair(root: str | Path, band: str) -> ModelPair:
    # root identifies the consumer policy, never an operational selection override.
    return pair_from_capture(resolve("codex", band), band)


def validate_requested_pair(root: str | Path, *, model: Any, effort: Any, role: str, capture: dict | None = None) -> ModelPair:
    band = role_band(role)
    current = resolve("codex", band, role=role)
    if capture is not None:
        validate_capture(capture, client="codex", band=band, role=role)
        if current["effective_sha256"] != capture["effective_sha256"]:
            raise ModelRoutingError("selection_changed before birth; resolve a new capture")
    pair = pair_from_capture(capture or current, band)
    if model != pair.slug or effort != pair.effort:
        raise ModelRoutingError(f"Codex {role} requires explicit {band} selection {pair.slug}/{pair.effort}; request {model!r}/{effort!r} refused")
    return pair


def pin_codex_map(root: str | Path, *, preflight: bool = False) -> bool:
    # Compatibility for old installers: pins install mechanisms, never selections.
    print("Codex selection pin: PASS; no operational files read or written; explicit migration is separate")
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--band", choices=BANDS)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--pin-codex-map", action="store_true", help="legacy no-write compatibility")
    parser.add_argument("--preflight-pin-codex-map", action="store_true", help="legacy no-write compatibility")
    args = parser.parse_args(argv)
    try:
        if args.pin_codex_map or args.preflight_pin_codex_map:
            pin_codex_map(args.root, preflight=args.preflight_pin_codex_map)
            return 0
        if args.band is None:
            parser.error("--band required")
        pair = resolve_pair(args.root, args.band)
        print(json.dumps(pair.as_request(), ensure_ascii=False) if args.json else f"band={pair.band} model={pair.slug} effort={pair.effort} label={pair.label}")
        return 0
    except ModelRoutingError as exc:
        print(f"codex model route error: {exc}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
