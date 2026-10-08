"""Isolated machine selections/catalogue for harness tests; never touch operator HOME."""
from pathlib import Path
import json
import os
import pytest
import yaml


def document() -> dict:
    pairs = {"juizo": {"label": "GPT-6 Sol", "model": "gpt-6-sol", "effort": "high"},
             "execucao": {"label": "GPT-6 Luna", "model": "gpt-6-luna", "effort": "max"}}
    return {"version": 1, "clients": {
        "codex": pairs,
        "cursor": {b: {"label": "Cursor " + b, "model": "cursor-" + b} for b in pairs},
        "grok": {b: {"label": "Grok " + b, "model": "grok-" + b} for b in pairs},
        "opencode": {b: {"label": "OpenCode " + b, "provider": "test-provider", "model": "test-model", "variant": "high"} for b in pairs},
        "dsh": {b: {"label": "dsh " + b, "provider": "test-provider", "model": "test-model", "effort": "medium"} for b in pairs},
    }}


def write_catalogue(home: Path) -> None:
    path = home / ".codex/models_cache.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"models": [{"slug": model, "supported_reasoning_levels": [{"effort": e} for e in efforts]} for model, efforts in {
        "gpt-6-sol": ["low", "medium", "high", "xhigh", "max"],
        "gpt-6-luna": ["low", "medium", "high", "xhigh", "max"],
        "gpt-6-astra": ["medium", "high", "max"],
        "gpt-6.1-sol": ["medium", "high", "max"],
        "updated-sol": ["xhigh"],
    }.items()]}))


@pytest.fixture(autouse=True)
def machine_models(tmp_path, monkeypatch):
    home = tmp_path / "machine-account"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    path = home / ".config/covenant-flow/model-selection.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(yaml.safe_dump(document(), sort_keys=False))
    write_catalogue(home)
    grok = home / ".grok/models_cache.json"
    grok.parent.mkdir()
    grok.write_text(json.dumps({"models": {m: {} for m in ["grok-juizo", "grok-execucao", "another-model"]}}))
    bin_dir = home / "bin"; bin_dir.mkdir()
    cursor = bin_dir / "cursor-agent"
    cursor.write_text("#!/bin/sh\ncat <<'CAT'\ncursor-juizo - Judgment\ncursor-execucao - Execution\nanother-model - Other\ndifferent - Different\nCAT\n")
    cursor.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", ""))
    return path
