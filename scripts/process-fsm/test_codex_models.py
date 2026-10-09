from pathlib import Path
import pytest
from model_selection_fixtures import machine_models
from model_selection import resolve, save_capture
from codex_models import ModelRoutingError, resolve_pair, validate_requested_pair, pin_codex_map


def test_codex_pair_facade_carries_birth_capture_and_native_arguments(tmp_path):
    pair = resolve_pair(tmp_path, "juizo")
    assert (pair.slug, pair.effort) == ("gpt-6-sol", "high")
    request = pair.as_request()
    assert request["capture"]["arguments"] == {"model": request["model"], "reasoning_effort": request["reasoning_effort"]}
    assert resolve_pair(tmp_path / "other-consumer", "execucao").slug == "gpt-6-luna"


@pytest.mark.parametrize("model,effort,role", [("", "high", "design-autor"), ("gpt-6-sol", None, "design-autor"), ("inherit", "high", "design-autor"), ("gpt-6-sol", "high", "diff-reviewer")])
def test_explicit_request_requires_exact_role_band(tmp_path, model, effort, role):
    with pytest.raises(ModelRoutingError):
        validate_requested_pair(tmp_path, model=model, effort=effort, role=role)


def test_matching_explicit_request_and_pin_no_write(tmp_path, machine_models):
    cap = resolve("codex", "execucao", role="apply-coluna")
    pair = validate_requested_pair(tmp_path, model="gpt-6-luna", effort="max", role="apply-coluna", capture=cap)
    assert pair.capture == cap
    before = machine_models.read_bytes()
    assert pin_codex_map(tmp_path, preflight=True) is False
    assert pin_codex_map(tmp_path) is False
    assert machine_models.read_bytes() == before
    assert not (tmp_path / ".cursor/model-map.yaml").exists()
