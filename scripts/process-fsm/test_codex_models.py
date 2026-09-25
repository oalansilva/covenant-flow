from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from codex_models import ModelRoutingError, pin_codex_map, resolve_pair, validate_requested_pair  # noqa: E402


def _write_map(root: Path, data: dict) -> Path:
    path = root / ".cursor" / "model-map.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _valid_map() -> dict:
    return {
        "juizo": {
            "label": "Cursor judgment",
            "slug": "cursor-judgment",
            "codex": {"label": "GPT-6 Sol", "slug": "gpt-6-sol", "effort": "high"},
        },
        "execucao": {
            "label": "Cursor execution",
            "slug": "cursor-execution",
            "codex": {"label": "GPT-6 Luna", "slug": "gpt-6-luna", "effort": "max"},
        },
        "forbid": ["composer-2.5-fast", "inherit"],
    }


def test_resolves_each_codex_band_without_mutating_cursor_or_forbid(tmp_path: Path):
    path = _write_map(tmp_path, _valid_map())
    before = path.read_bytes()

    judgment = resolve_pair(tmp_path, "juizo")
    execution = resolve_pair(tmp_path, "execucao")

    assert judgment.as_request() == {
        "band": "juizo",
        "label": "GPT-6 Sol",
        "model": "gpt-6-sol",
        "reasoning_effort": "high",
    }
    assert execution.as_request() == {
        "band": "execucao",
        "label": "GPT-6 Luna",
        "model": "gpt-6-luna",
        "reasoning_effort": "max",
    }
    assert path.read_bytes() == before


def test_a_valid_map_edit_changes_the_next_resolution_only(tmp_path: Path):
    path = _write_map(tmp_path, _valid_map())
    first = resolve_pair(tmp_path, "juizo")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["juizo"]["codex"].update(label="Updated Sol", slug="updated-sol", effort="xhigh")
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")

    next_spawn = resolve_pair(tmp_path, "juizo")
    execution = resolve_pair(tmp_path, "execucao")
    current = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert (first.slug, first.effort) == ("gpt-6-sol", "high")
    assert (next_spawn.slug, next_spawn.effort) == ("updated-sol", "xhigh")
    assert (execution.slug, execution.effort) == ("gpt-6-luna", "max")
    assert current["juizo"]["label"] == "Cursor judgment"
    assert current["juizo"]["slug"] == "cursor-judgment"
    assert current["execucao"]["label"] == "Cursor execution"
    assert current["execucao"]["slug"] == "cursor-execution"
    assert current["forbid"] == ["composer-2.5-fast", "inherit"]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda data: data["juizo"].pop("codex"), "missing juizo.codex"),
        (lambda data: data["juizo"]["codex"].pop("slug"), "invalid juizo.codex.slug"),
        (lambda data: data["juizo"]["codex"].update(slug=""), "invalid juizo.codex.slug"),
        (lambda data: data["juizo"]["codex"].pop("effort"), "invalid juizo.codex.effort"),
        (lambda data: data["juizo"]["codex"].update(effort="default"), "invalid juizo.codex.effort"),
        (lambda data: data.update(forbid="inherit"), "string-list `forbid`"),
        (lambda data: data["forbid"].append("gpt-6-sol"), "is forbidden"),
    ],
)
def test_invalid_or_forbidden_pairs_fail_visibly(tmp_path: Path, mutate, message: str):
    data = _valid_map()
    mutate(data)
    _write_map(tmp_path, data)

    with pytest.raises(ModelRoutingError, match=message):
        resolve_pair(tmp_path, "juizo")


def test_missing_map_and_unknown_band_fail_visibly(tmp_path: Path):
    with pytest.raises(ModelRoutingError, match="model map missing"):
        resolve_pair(tmp_path, "juizo")
    _write_map(tmp_path, _valid_map())
    with pytest.raises(ModelRoutingError, match="unknown model band"):
        resolve_pair(tmp_path, "review")


def test_spawn_request_requires_current_explicit_pair(tmp_path: Path):
    _write_map(tmp_path, _valid_map())

    pair = validate_requested_pair(tmp_path, model="gpt-6-luna", effort="max")

    assert pair.band == "execucao"
    with pytest.raises(ModelRoutingError, match="explicit model"):
        validate_requested_pair(tmp_path, model=None, effort="max")
    with pytest.raises(ModelRoutingError, match="explicit reasoning effort"):
        validate_requested_pair(tmp_path, model="gpt-6-luna", effort=None)
    with pytest.raises(ModelRoutingError, match="not a current shared-map pair"):
        validate_requested_pair(tmp_path, model="inherit", effort="max")


def _cursor_map_bytes(root: Path, *, forbid: str = "composer-2.5-fast") -> Path:
    path = root / ".cursor" / "model-map.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Existing Cursor choices belong to the consumer.\n"
        "juizo:\n"
        '  label: "deepseek-flash"\n'
        "  slug: deepseek-flash\n"
        "execucao:\n"
        '  label: "deepseek-flash"\n'
        "  slug: deepseek-flash\n"
        "forbid:\n"
        f"  - {forbid}\n"
        "  - inherit\n",
        encoding="utf-8",
    )
    return path


def test_pin_adds_codex_pairs_without_rewriting_existing_map_bytes(tmp_path: Path):
    path = _cursor_map_bytes(tmp_path)
    original = path.read_bytes()
    original_map = yaml.safe_load(original)

    assert pin_codex_map(tmp_path, preflight=True) is False
    assert path.read_bytes() == original
    assert pin_codex_map(tmp_path) is True
    pinned = path.read_bytes()
    data = yaml.safe_load(pinned)

    assert data["juizo"]["codex"] == {"label": "GPT-6 Sol", "slug": "gpt-6-sol", "effort": "high"}
    assert data["execucao"]["codex"] == {"label": "GPT-6 Luna", "slug": "gpt-6-luna", "effort": "max"}
    for band in ("juizo", "execucao"):
        for key in ("label", "slug"):
            assert data[band][key] == original_map[band][key]
    assert data["forbid"] == original_map["forbid"]
    assert pin_codex_map(tmp_path) is False
    assert path.read_bytes() == pinned
    # Removing only the inserted Codex blocks restores every destination byte.
    restored = pinned.replace(
        b'  codex:\n    label: "GPT-6 Sol"\n    slug: gpt-6-sol\n    effort: high\n', b""
    ).replace(
        b'  codex:\n    label: "GPT-6 Luna"\n    slug: gpt-6-luna\n    effort: max\n', b""
    )
    assert restored == original


def test_pin_does_not_follow_preexisting_predictable_temp_symlink(tmp_path: Path):
    path = _cursor_map_bytes(tmp_path)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"protected bytes\n")
    temp_link = path.with_name(".model-map.yaml.codex-tmp")
    temp_link.symlink_to(victim)

    assert pin_codex_map(tmp_path) is True

    assert "codex:" in path.read_text(encoding="utf-8")
    assert victim.read_bytes() == b"protected bytes\n"
    assert temp_link.is_symlink()


def test_pin_conflicts_and_forbid_refuse_without_editing_the_target(tmp_path: Path):
    conflicting = _valid_map()
    conflicting["juizo"]["codex"]["slug"] = "operator-model"
    path = _write_map(tmp_path, conflicting)
    before = path.read_bytes()
    with pytest.raises(ModelRoutingError, match="differs from the approved pin"):
        pin_codex_map(tmp_path)
    assert path.read_bytes() == before

    forbidden_root = tmp_path / "forbidden"
    forbidden_path = _cursor_map_bytes(forbidden_root, forbid="gpt-6-sol")
    forbidden_before = forbidden_path.read_bytes()
    with pytest.raises(ModelRoutingError, match="conflicts with `forbid`"):
        pin_codex_map(forbidden_root)
    assert forbidden_path.read_bytes() == forbidden_before
