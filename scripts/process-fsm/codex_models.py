"""Resolve Codex child model pairs from the consumer's shared model map."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml

from codex_fs import atomic_write_bytes


EFFORTS = frozenset({"none", "low", "medium", "high", "xhigh", "max"})
MODEL_SLUG = re.compile(r"[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*\Z")
BANDS = ("juizo", "execucao")
PIN_PAIRS = {
    "juizo": {"label": "GPT-6 Sol", "slug": "gpt-6-sol", "effort": "high"},
    "execucao": {"label": "GPT-6 Luna", "slug": "gpt-6-luna", "effort": "max"},
}


class ModelRoutingError(ValueError):
    """A Codex child cannot be routed from the shared model map."""


@dataclass(frozen=True)
class ModelPair:
    band: str
    label: str
    slug: str
    effort: str

    def as_request(self) -> dict[str, str]:
        return {
            "band": self.band,
            "label": self.label,
            "model": self.slug,
            "reasoning_effort": self.effort,
        }


def _read_map(path: Path) -> Mapping[str, Any]:
    if not path.is_file():
        raise ModelRoutingError(f"model map missing: {path}")
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ModelRoutingError(f"cannot read model map {path}: {exc}") from exc
    if not isinstance(document, Mapping):
        raise ModelRoutingError(f"model map must contain a YAML object: {path}")
    return document


def resolve_pair(root: str | Path, band: str) -> ModelPair:
    """Read and validate one Codex pair at the time of each caller request."""

    if band not in BANDS:
        raise ModelRoutingError(f"unknown model band {band!r}; expected juizo or execucao")

    path = Path(root) / ".cursor" / "model-map.yaml"
    document = _read_map(path)
    entry = document.get(band)
    if not isinstance(entry, Mapping):
        raise ModelRoutingError(f"model map is missing band {band!r}: {path}")
    codex = entry.get("codex")
    if not isinstance(codex, Mapping):
        raise ModelRoutingError(f"model map is missing {band}.codex: {path}")

    label = codex.get("label")
    slug = codex.get("slug")
    effort = codex.get("effort")
    if not isinstance(label, str) or not label.strip():
        raise ModelRoutingError(f"model map is missing {band}.codex.label: {path}")
    if not isinstance(slug, str) or not MODEL_SLUG.fullmatch(slug):
        raise ModelRoutingError(f"model map has an invalid {band}.codex.slug: {slug!r}")
    if not isinstance(effort, str) or effort not in EFFORTS:
        raise ModelRoutingError(
            f"model map has an invalid {band}.codex.effort: {effort!r}; "
            f"expected one of {', '.join(sorted(EFFORTS))}"
        )

    forbidden = document.get("forbid")
    if not isinstance(forbidden, list) or any(not isinstance(item, str) for item in forbidden):
        raise ModelRoutingError(f"model map must retain a string-list `forbid`: {path}")
    forbidden_values = {item.casefold() for item in forbidden}
    if slug.casefold() in forbidden_values or label.casefold() in forbidden_values:
        raise ModelRoutingError(f"{band}.codex model {slug!r} is forbidden by {path}")

    return ModelPair(band=band, label=label.strip(), slug=slug, effort=effort)


def validate_requested_pair(
    root: str | Path,
    *,
    model: Any,
    effort: Any,
) -> ModelPair:
    """Ensure a spawn tool call carries a current, explicit map pair."""

    if not isinstance(model, str) or not model.strip():
        raise ModelRoutingError("Codex child request must include an explicit model")
    if not isinstance(effort, str) or not effort.strip():
        raise ModelRoutingError("Codex child request must include an explicit reasoning effort")

    requested_model = model.strip()
    requested_effort = effort.strip()
    invalid_bands: list[str] = []
    for band in BANDS:
        try:
            pair = resolve_pair(root, band)
        except ModelRoutingError as exc:
            invalid_bands.append(f"{band}: {exc}")
            continue
        if pair.slug == requested_model and pair.effort == requested_effort:
            return pair

    expected = "; ".join(invalid_bands) or "neither current band pair matches"
    raise ModelRoutingError(
        f"Codex child request {requested_model!r}/{requested_effort!r} is not a current "
        f"shared-map pair ({expected})"
    )


def plan_codex_map_pin(root: str | Path) -> tuple[Path, bytes]:
    """Append the approved Codex pairs without rewriting existing YAML bytes."""

    path = Path(root) / ".cursor" / "model-map.yaml"
    if not path.is_file():
        raise ModelRoutingError(f"shared model map missing; pin refused: {path}")
    try:
        original = path.read_bytes()
        text = original.decode("utf-8")
        document = yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ModelRoutingError(f"cannot read shared model map {path}: {exc}") from exc
    if not isinstance(document, Mapping):
        raise ModelRoutingError(f"shared model map must contain a YAML object: {path}")
    forbidden = document.get("forbid")
    if not isinstance(forbidden, list) or any(not isinstance(item, str) for item in forbidden):
        raise ModelRoutingError(f"shared model map must retain string-list `forbid`: {path}")
    if any(value.casefold() in {item.casefold() for item in forbidden} for pair in PIN_PAIRS.values() for value in (pair["label"], pair["slug"])):
        raise ModelRoutingError(f"approved Codex pair conflicts with `forbid` in {path}")

    missing: list[str] = []
    for band, expected in PIN_PAIRS.items():
        entry = document.get(band)
        if not isinstance(entry, Mapping):
            raise ModelRoutingError(f"shared model map is missing {band}: {path}")
        for key in ("label", "slug"):
            value = entry.get(key)
            if not isinstance(value, str) or not value:
                raise ModelRoutingError(f"shared model map is missing {band}.{key}: {path}")
        current = entry.get("codex")
        if current is None:
            missing.append(band)
            continue
        if not isinstance(current, Mapping) or any(current.get(key) != value for key, value in expected.items()):
            raise ModelRoutingError(
                f"existing {band}.codex pair differs from the approved pin; reconcile explicitly: {path}"
            )

    if not missing:
        return path, original

    lines = text.splitlines(keepends=True)
    newline = "\r\n" if "\r\n" in text else "\n"
    inserts: list[tuple[int, str]] = []
    for band in missing:
        top_pattern = re.compile(rf"^{re.escape(band)}:\s*(?:#.*)?(?:\r?\n)?$")
        top_index = next((index for index, line in enumerate(lines) if top_pattern.match(line)), None)
        if top_index is None:
            raise ModelRoutingError(f"cannot locate top-level {band}: in {path}")
        next_top = len(lines)
        for index in range(top_index + 1, len(lines)):
            if re.match(r"^[A-Za-z0-9_-]+:\s*(?:#.*)?(?:\r?\n)?$", lines[index]):
                next_top = index
                break
        field_pattern = re.compile(r"^(\s+)slug\s*:")
        slug_index = next(
            (index for index in range(top_index + 1, next_top) if field_pattern.match(lines[index])),
            None,
        )
        if slug_index is None:
            raise ModelRoutingError(f"cannot locate {band}.slug line in {path}")
        indent = len(field_pattern.match(lines[slug_index]).group(1))  # type: ignore[union-attr]
        child = " " * indent
        grandchild = child + "  "
        pair = PIN_PAIRS[band]
        block = (
            f"{child}codex:{newline}"
            f"{grandchild}label: {json.dumps(pair['label'], ensure_ascii=False)}{newline}"
            f"{grandchild}slug: {pair['slug']}{newline}"
            f"{grandchild}effort: {pair['effort']}{newline}"
        )
        inserts.append((slug_index + 1, block))

    for index, block in sorted(inserts, reverse=True):
        if index > 0 and not lines[index - 1].endswith(("\n", "\r")):
            lines[index - 1] += newline
        lines.insert(index, block)
    updated = "".join(lines).encode("utf-8")
    try:
        after = yaml.safe_load(updated.decode("utf-8"))
    except yaml.YAMLError as exc:
        raise ModelRoutingError(f"Codex map pin would produce invalid YAML: {exc}") from exc
    for band, expected in PIN_PAIRS.items():
        actual = after[band]["codex"]
        if any(actual.get(key) != value for key, value in expected.items()):
            raise ModelRoutingError(f"Codex map pin failed validation for {band}: {path}")
    if after.get("forbid") != forbidden:
        raise ModelRoutingError(f"Codex map pin changed `forbid`: {path}")
    for band in BANDS:
        for key in ("label", "slug"):
            if after[band].get(key) != document[band].get(key):
                raise ModelRoutingError(f"Codex map pin changed {band}.{key}: {path}")
    return path, updated


def pin_codex_map(root: str | Path, *, preflight: bool = False) -> bool:
    path, updated = plan_codex_map_pin(root)
    current = path.read_bytes()
    if preflight:
        print(f"Codex model-map preflight: PASS (no files changed): {path}")
        return False
    if current == updated:
        print(f"Codex model-map already current: {path}")
        return False
    atomic_write_bytes(path, updated)
    print(f"Codex model-map extended without replacing Cursor fields: {path}")
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--band", choices=BANDS)
    parser.add_argument("--json", action="store_true", help="emit a compact JSON spawn request")
    parser.add_argument("--pin-codex-map", action="store_true")
    parser.add_argument("--preflight-pin-codex-map", action="store_true")
    args = parser.parse_args(argv)
    if args.pin_codex_map or args.preflight_pin_codex_map:
        try:
            pin_codex_map(args.root, preflight=args.preflight_pin_codex_map)
        except ModelRoutingError as exc:
            print(f"codex model route error: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.band is None:
        parser.error("--band is required unless --pin-codex-map/--preflight-pin-codex-map is used")
    try:
        pair = resolve_pair(args.root, args.band)
    except ModelRoutingError as exc:
        print(f"codex model route error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(pair.as_request(), ensure_ascii=False))
    else:
        print(f"band={pair.band} model={pair.slug} effort={pair.effort} label={pair.label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
