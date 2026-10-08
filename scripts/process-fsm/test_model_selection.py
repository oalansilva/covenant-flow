from __future__ import annotations
import copy
import json
import subprocess
from pathlib import Path
import pytest
import yaml
from model_selection_fixtures import machine_models, document
from model_selection import (SelectionError, resolve, selection_path, validate_capture,
                             save_capture, compare_wave, migration_plan, apply_migration,
                             validate_document, request_role)
from codex_models import resolve_pair, validate_requested_pair, pin_codex_map
from model_proxy import evidence, verify_continuation
from release_model_selection import check_runtime_model


def edit(path, client, band, **values):
    doc = yaml.safe_load(path.read_text())
    doc["clients"][client][band].update(values)
    path.write_text(yaml.safe_dump(doc, sort_keys=False))


@pytest.mark.parametrize("client", ["cursor", "codex", "grok", "opencode", "dsh"])
def test_selection_shared_across_two_repos_two_worktrees_every_band(machine_models, tmp_path, client):
    repos = []
    for n in (1, 2):
        repo = tmp_path / f"repo-{n}"
        subprocess.run(["git", "init", "-b", "main", str(repo)], capture_output=True, check=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=test", "-c", "user.email=test@test", "commit", "--allow-empty", "-m", "init"], capture_output=True, check=True)
        wt = tmp_path / f"worktree-{n}"
        subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", "test", str(wt)], capture_output=True, check=True)
        repos += [repo, wt]
    old = {b: resolve(client, b) for b in ("juizo", "execucao")}
    for band in ("juizo", "execucao"):
        before = copy.deepcopy(yaml.safe_load(machine_models.read_text()))
        if client == "codex":
            edit(machine_models, client, band, model="gpt-6.1-sol", effort="high")
        elif client == "dsh":
            edit(machine_models, client, band, model="another-model", effort="high")
        else:
            edit(machine_models, client, band, model="another-model")
        for root in repos:
            # Cwd/root cannot override the account's operational file.
            if client == "codex":
                assert resolve_pair(root, band).slug == "gpt-6.1-sol"
            result = subprocess.run(["python3", str(Path(__file__).with_name("model_selection.py")), "resolve", "--client", client, "--band", band, "--role", "design-autor" if band == "juizo" else "apply-coluna"], cwd=root, capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            assert json.loads(result.stdout)["selection"]["model"] == ("gpt-6.1-sol" if client == "codex" else "another-model")
            assert not subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"])
        after = yaml.safe_load(machine_models.read_text())
        before["clients"][client][band] = after["clients"][client][band]
        assert before == after
        assert validate_capture(old[band])["selection"]["model"] != ("gpt-6.1-sol" if client == "codex" else "another-model")


@pytest.mark.parametrize("body", ["version: 1\nversion: 1\nclients: {}", "version: 2\nclients: {}", "version: 1\nclients: {}\nroles: {}", "version: 1\nclients: {codex: {juizo: {model: x, model: y}}}", "version: true\nclients: {}"])
def test_invalid_global_schema_and_duplicate_keys(machine_models, body):
    machine_models.write_text(body)
    with pytest.raises(SelectionError): resolve("cursor", "juizo")


@pytest.mark.parametrize("client,change", [("cursor", {"effort": "high"}), ("grok", {"effort": "high"}), ("codex", {"effort": "none"}), ("codex", {"model": "unadvertised"}), ("dsh", {"effort": ""}), ("opencode", {"provider": ""}), ("cursor", {"model": "inherit"}), ("codex", {"model": "composer-2.5-fast"})])
def test_refusals_no_substitution(machine_models, client, change):
    edit(machine_models, client, "execucao", **change)
    with pytest.raises(SelectionError): resolve(client, "execucao")


@pytest.mark.parametrize("missing", ["file", "client", "band", "effort", "catalogue"])
def test_missing_does_not_fallback_to_git_map(machine_models, tmp_path, missing):
    repo = tmp_path / "repo"; (repo / ".cursor").mkdir(parents=True)
    (repo / ".cursor/model-map.yaml").write_text("juizo: {codex: {label: legacy, slug: gpt-6-sol, effort: high}}")
    doc = yaml.safe_load(machine_models.read_text())
    if missing == "file": machine_models.unlink()
    elif missing == "catalogue": (Path.home() / ".codex/models_cache.json").unlink()
    else:
        if missing == "client": del doc["clients"]["codex"]
        elif missing == "band": del doc["clients"]["codex"]["juizo"]
        else: del doc["clients"]["codex"]["juizo"]["effort"]
        machine_models.write_text(yaml.safe_dump(doc))
    with pytest.raises(SelectionError, match="codex/juizo"):
        resolve_pair(repo, "juizo")


def test_role_band_exact_even_when_models_coincide(machine_models, tmp_path):
    role = request_role({"description": "diff-reviewer 1080"})
    assert role == "diff-reviewer"
    with pytest.raises(SelectionError): validate_requested_pair(tmp_path, model="gpt-6-sol", effort="high", role=role)
    with pytest.raises(SelectionError): request_role({"prompt": "diff-reviewer"})
    with pytest.raises(SelectionError): resolve("codex", "juizo", role="apply-coluna")


def test_capture_immutable_edits_wave_same_band_only(machine_models, tmp_path):
    first = resolve("codex", "execucao", role="diff-reviewer")
    path = tmp_path / "birth.json"; save_capture(path, first)
    with pytest.raises(FileExistsError): save_capture(path, first)
    edit(machine_models, "cursor", "execucao", model="different")
    compare_wave(first, resolve("codex", "execucao", role="code-reviewer"))
    edit(machine_models, "codex", "execucao", model="gpt-6.1-sol", effort="high")
    with pytest.raises(SelectionError, match="selection_changed"):
        compare_wave(first, resolve("codex", "execucao", role="code-reviewer"))
    assert validate_capture(first)["selection"]["model"] == "gpt-6-luna"
    changed = copy.deepcopy(first); changed["selection"]["model"] = "forged"
    with pytest.raises(SelectionError, match="digest mismatch"): validate_capture(changed)


def test_continuation_and_parent_release_use_birth_capture(machine_models, tmp_path):
    first = resolve("codex", "execucao", role="fecho-lote")
    edit(machine_models, "codex", "execucao", model="gpt-6.1-sol", effort="high")
    facts = {"model": "gpt-6-luna", "effort": "max"}
    assert verify_continuation(first, facts, host="Codex", host_version="0.162", status="completed", payload_returned=True)["successful"]
    assert check_runtime_model(root=tmp_path, client="codex", runtime_slug="gpt-6-luna", runtime_effort="max", capture=first).ok
    assert not check_runtime_model(root=tmp_path, client="codex", runtime_slug="gpt-6.1-sol", runtime_effort="high", capture=first).ok
    assert not check_runtime_model(root=tmp_path, client="codex", runtime_slug="gpt-6-luna", capture=first).ok
    with pytest.raises(SelectionError): verify_continuation(first, {}, host="Codex", host_version="0.162", status="completed", payload_returned=True)


def test_observed_not_inferred_and_nonapplicable_is_distinct(machine_models):
    cap = resolve("cursor", "execucao", role="diff-reviewer")
    entry = evidence(capture=cap, observed={}, host="Cursor", host_version="real", status="completed", payload_returned=True)
    assert entry["observed"]["model"] == "unavailable"
    assert entry["observed"]["effort"] == "not_applicable"
    assert not entry["successful"]


@pytest.mark.parametrize("client", ["dsh", "opencode"])
def test_release_requires_complete_captured_route(machine_models, tmp_path, client):
    capture = resolve(client, "execucao", role="fecho-lote")
    selected = capture["selection"]
    observed = {
        "runtime_slug": selected["model"],
        "runtime_effort": selected.get("effort", ""),
        "runtime_provider": selected["provider"],
        "runtime_variant": selected.get("variant", ""),
    }
    assert check_runtime_model(root=tmp_path, client=client, capture=capture, **observed).ok
    # Editing the local route after birth must not change the release obligation.
    edit(machine_models, client, "execucao", provider="updated-provider")
    assert check_runtime_model(root=tmp_path, client=client, capture=capture, **observed).ok
    for field in ("provider", "variant") if client == "opencode" else ("provider",):
        for missing_or_different in ("", None, "unavailable", "not_applicable", "other-route"):
            facts = dict(observed, **{f"runtime_{field}": missing_or_different})
            result = check_runtime_model(root=tmp_path, client=client, capture=capture, **facts)
            assert not result.ok
            assert result.divergence
            assert field in result.message


@pytest.mark.parametrize("observed_variant", ["", None, "not_applicable", "unavailable"])
def test_release_optional_variant_absent_is_not_required(machine_models, tmp_path, observed_variant):
    doc = yaml.safe_load(machine_models.read_text())
    del doc["clients"]["opencode"]["execucao"]["variant"]
    machine_models.write_text(yaml.safe_dump(doc))
    capture = resolve("opencode", "execucao", role="fecho-lote")
    result = check_runtime_model(
        root=tmp_path, client="opencode", capture=capture,
        runtime_slug="test-model", runtime_provider="test-provider",
        runtime_variant=observed_variant,
    )
    assert result.ok


def legacy(path):
    data = {b: {"label": "Cursor " + b, "slug": "cursor-" + b, "grok": {"label": "Grok " + b, "slug": "grok-" + b, "effort": "high"}} for b in ("juizo", "execucao")}
    path.write_text(yaml.safe_dump(data)); return data


def test_explicit_migration_preserves_existing_and_missing_routes(machine_models, tmp_path):
    source = tmp_path / "legacy.yaml"; legacy(source)
    original = machine_models.read_bytes()
    assert migration_plan(source, {})["action"] == "preserve_existing"
    assert machine_models.read_bytes() == original
    machine_models.unlink()
    plan = migration_plan(source, {})
    assert plan["unmigrated_clients"] == ["opencode", "dsh"]
    with pytest.raises(SelectionError): apply_migration(plan)
    assert not machine_models.exists()


def test_atomic_migration_has_requested_codex_and_preserves_other_routes(machine_models, tmp_path):
    machine_models.unlink()
    source = tmp_path / "legacy.yaml"; old = legacy(source)
    routes = {c: document()["clients"][c] for c in ("opencode", "dsh")}
    plan = migration_plan(source, routes)
    assert plan["document"]["clients"]["codex"]["juizo"]["model"] == "gpt-6-astra"
    assert plan["document"]["clients"]["codex"]["execucao"]["effort"] == "high"
    apply_migration(plan)
    saved = machine_models.read_bytes()
    with pytest.raises(SelectionError): apply_migration(plan)
    assert machine_models.read_bytes() == saved
    assert not list(machine_models.parent.glob(".model-selection-*"))
    for band in ("juizo", "execucao"):
        assert resolve("cursor", band)["selection"]["model"] == old[band]["slug"]
        assert resolve("dsh", band)["selection"] == routes["dsh"][band]


def test_pin_never_reads_requires_or_writes_selection_or_legacy(machine_models, tmp_path):
    before = machine_models.read_bytes()
    assert not pin_codex_map(tmp_path)
    assert machine_models.read_bytes() == before
    machine_models.unlink()
    assert not pin_codex_map(tmp_path, preflight=True)
    assert not machine_models.exists() and not (tmp_path / ".cursor").exists()
