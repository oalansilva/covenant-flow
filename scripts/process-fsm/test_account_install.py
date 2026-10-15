"""Account installer: one registration per in-scope host, foreign entries kept, no partial writes, no trust."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import account_install
import adapter_manifest
import cf_shim
from shim_fixtures import ALL_HOSTS, HERE, install_account, isolate_account, make_consumer, trust_all


@pytest.fixture
def account(monkeypatch, tmp_path):
    return isolate_account(monkeypatch, tmp_path)


def snapshot(home: Path) -> dict[str, bytes]:
    return {str(p.relative_to(home)): p.read_bytes() for p in sorted(home.rglob("*")) if p.is_file() and not p.is_symlink()}


def seed_foreign(home: Path) -> None:
    (home / ".claude").mkdir()
    (home / ".claude/settings.json").write_text(json.dumps({"theme": "dark", "hooks": {
        "Stop": [{"hooks": [{"type": "command", "command": "echo foreign-claude"}]}],
        "PreToolUse": [{"matcher": "Bash|Agent", "keep": True, "hooks": [{"type": "command", "command": "echo foreign-pre"}]}],
    }}, indent=2))
    (home / ".cursor").mkdir()
    (home / ".cursor/hooks.json").write_text(json.dumps({"version": 1, "hooks": {"stop": [{"command": "echo foreign-cursor"}]}}, indent=2))
    (home / ".codex").mkdir()
    (home / ".codex/hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo foreign-codex"}]}]}}, indent=2))
    (home / ".codex/config.toml").write_text('[hooks.state."/x/hooks.json:stop:0:0"]\ntrusted_hash = "sha256:abc"\n')


def test_every_host_of_the_scope_gets_one_entry_and_the_shim_is_versioned(account):
    install_account()
    base = cf_shim.shim_root()
    assert (base / "current").is_symlink() and (base / "current").resolve().name == cf_shim.SHIM_VERSION
    assert (base / cf_shim.SHIM_VERSION / "cf_shim.py").read_bytes() == (HERE / "cf_shim.py").read_bytes()
    claude = json.loads((account / ".claude/settings.json").read_text())["hooks"]
    assert {"SessionStart", "PreToolUse", "PostToolUse", "SubagentStop", "Stop"} == set(claude)
    pre = claude["PreToolUse"][0]
    assert set(pre["matcher"].split("|")) == {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Agent"}
    assert pre["hooks"][0]["onFailure"] == "block" and pre["hooks"][0]["timeout"] == 30
    assert {g["matcher"] for g in claude["PostToolUse"]} == {"Edit|Write|MultiEdit|NotebookEdit|Bash", "Agent", "EnterWorktree"}
    cursor = json.loads((account / ".cursor/hooks.json").read_text())["hooks"]
    guard, models = cursor["preToolUse"]
    assert guard["failClosed"] is True and models["failClosed"] is True
    assert "failClosed" not in cursor["beforeShellExecution"][0]
    assert cursor["subagentStop"][0]["loop_limit"] == 32 and "afterFileEdit" in cursor and "stop" in cursor
    codex = json.loads((account / ".codex/hooks.json").read_text())["hooks"]
    assert set(codex) == {"SessionStart", "PreToolUse", "PostToolUse", "Stop"}
    plugin = (account / ".config/opencode/plugin/covenant-flow-shim.js").read_text()
    assert plugin.startswith(cf_shim.OPENCODE_PLUGIN_HEADER) and "cf_shim_opencode.js" in plugin
    for client in ALL_HOSTS:
        assert cf_shim.registration_digest(client)
    # each entry calls the shim of the account, never a path of a repository
    for blob in (json.dumps(claude), json.dumps(cursor), json.dumps(codex)):
        assert "covenant-flow/shim/current/cf_shim.py" in blob and "CLAUDE_PROJECT_DIR" not in blob and "git rev-parse" not in blob


def test_install_preserves_foreign_keys_and_handlers_and_is_idempotent(account):
    seed_foreign(account)
    install_account()
    first = snapshot(account)
    claude = json.loads((account / ".claude/settings.json").read_text())
    assert claude["theme"] == "dark"
    commands = json.dumps(claude)
    assert "echo foreign-claude" in commands and "echo foreign-pre" in commands
    pre_group = next(g for g in claude["hooks"]["PreToolUse"] if g["matcher"] == "Bash|Agent")
    assert pre_group["keep"] is True and len(pre_group["hooks"]) == 1
    assert "echo foreign-cursor" in (account / ".cursor/hooks.json").read_text()
    assert "echo foreign-codex" in (account / ".codex/hooks.json").read_text()
    assert (account / ".codex/config.toml").read_text().count("trusted_hash") == 1  # the host's own trust bookkeeping is untouched
    install_account()
    assert snapshot(account) == first
    for client in ("claude", "codex"):
        document = json.loads(cf_shim.host_config_path(client).read_text())
        count = json.dumps(document).count(f"cf_shim.py\\\" {client} pre-tool-use")
        assert count == 1


def test_remove_restores_what_was_there_and_leaves_no_entry(account):
    seed_foreign(account)
    before = snapshot(account)
    install_account()
    assert snapshot(account) != before
    account_install.run_remove(None)
    after = snapshot(account)
    assert {k: json.loads(v) for k, v in after.items() if k.endswith(".json")} == {k: json.loads(v) for k, v in before.items() if k.endswith(".json")}
    assert after[".codex/config.toml"] == before[".codex/config.toml"]
    assert not cf_shim.shim_root().exists() and not (account / ".config/opencode/plugin/covenant-flow-shim.js").exists()


def test_remove_deletes_files_the_installer_alone_created(account):
    install_account()
    account_install.run_remove(None)
    assert [p for p in account.rglob("*") if p.is_file()] == []


def test_a_malformed_host_config_refuses_the_whole_run_without_any_write(account):
    (account / ".cursor").mkdir()
    (account / ".cursor/hooks.json").write_text("{not json")
    (account / ".claude").mkdir()
    (account / ".claude/settings.json").write_text(json.dumps({"hooks": {"Stop": []}}))
    before = snapshot(account)
    with pytest.raises(account_install.InstallError, match=r"\.cursor/hooks\.json"):
        install_account()
    assert snapshot(account) == before and not cf_shim.shim_root().exists()
    assert not (account / ".codex").exists() and not (account / ".config").exists()


@pytest.mark.parametrize("path,content,needle", [
    (".claude/settings.json", "[1, 2]", "settings.json"),
    (".claude/settings.json", '{"hooks": []}', "hooks"),
    (".codex/config.toml", "[hooks]\nPreToolUse = []\n", "inline"),
    (".config/opencode/plugin/covenant-flow-shim.js", "export default {}\n", "not managed"),
])
def test_conflicts_that_cannot_merge_without_loss_are_refused_naming_the_path(account, path, content, needle):
    target = account / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    before = snapshot(account)
    with pytest.raises(account_install.InstallError, match=needle):
        install_account()
    assert snapshot(account) == before


def test_grok_and_dsh_are_never_touched_and_never_named_as_hosts(account):
    install_account()
    names = " ".join(str(p.relative_to(account)) for p in account.rglob("*"))
    assert ".grok" not in names and ".dsh" not in names and "grok" not in names.lower()
    assert set(cf_shim.CLIENTS) == {"claude", "cursor", "codex", "opencode"}
    assert account_install.main(["install", "--hosts", "grok"]) == 2


def test_an_unproven_host_gets_nothing_and_is_reported(account, monkeypatch):
    monkeypatch.setitem(cf_shim.HOST_REGISTRATION, "cursor", "unproven")
    lines = account_install.run_install(HERE, ALL_HOSTS)
    assert any(line.startswith("cursor: registration=unproven") for line in lines)
    assert not (account / ".cursor/hooks.json").exists()
    check, ok = account_install.run_check(None, ALL_HOSTS)
    assert any("cursor: registration=unproven" in line for line in check) and ok


def line_of(lines, client):
    return next(line for line in lines if line.startswith(f"{client}:"))


def test_check_shows_a_host_without_registration_and_the_review_state(account, tmp_path):
    consumer = make_consumer(tmp_path / "c")
    lines, ok = account_install.run_check(consumer, ["claude", "codex"])
    assert not ok and "entry=MISSING" in line_of(lines, "claude") and "shim=MISSING" in line_of(lines, "claude")
    install_account(["claude"])
    lines, ok = account_install.run_check(consumer, ["claude", "codex"])
    assert not ok and "claude: registration=account entry=present" in line_of(lines, "claude") and "registration_review=unreviewed" in line_of(lines, "claude")
    assert "codex: registration=account entry=MISSING" in line_of(lines, "codex")
    install_account(["claude", "codex"])
    trust_all(consumer, ["claude", "codex"])
    lines, ok = account_install.run_check(consumer, ["claude", "codex"])
    assert ok and "consumer_pin=account" in lines[0] and "adapter_review=reviewed" in line_of(lines, "claude")
    not_installed, _ = account_install.run_check(consumer, ["claude"])
    assert "codex: registration=not_installed" in line_of(not_installed, "codex")


def test_check_reports_a_pin_before_account_registration(account, tmp_path):
    old = make_consumer(tmp_path / "old", manifest=False)
    install_account(["claude"])
    lines, _ = account_install.run_check(old, ["claude"])
    assert "project (pin predates account registration)" in lines[0] and "old pin" in line_of(lines, "claude")


def test_nothing_in_the_installer_reads_or_writes_the_model_selection_or_trust(account):
    install_account()
    assert not (account / ".config/covenant-flow/model-selection.yaml").exists()
    assert not cf_shim.trust_path().exists()
    source = (HERE / "account_install.py").read_text()
    assert "model-selection.yaml" not in source and "model_selection" not in source and "record_review" not in source


# --- the manifest the pin writes ------------------------------------------------------


def test_manifest_declares_registration_per_client_protocol_entry_points_and_digests(tmp_path):
    root = make_consumer(tmp_path / "c")
    manifest = json.loads((root / cf_shim.MANIFEST).read_text())
    assert manifest["shim_protocol"] == cf_shim.SHIM_PROTOCOL and manifest["pin"] == "v1.2.0"
    assert {c: manifest["clients"][c]["registration"] for c in manifest["clients"]} == {
        "claude": "account", "cursor": "account", "codex": "account", "opencode": "account", "grok": "project", "dsh": "project"}
    claude = manifest["clients"]["claude"]
    assert claude["entrypoints"]["pre-tool-use"] == ["python3", "scripts/process-fsm/claude_adapter.py", "pre-tool-use"]
    assert "scripts/process-fsm/claude_adapter.py" in claude["files"] and ".agents/skills/impeccable/scripts/detector/rules.mjs" in claude["files"]
    assert not any("test_" in f or "/fixtures/" in f for f in claude["files"])
    assert any(f.startswith(".cursor/hooks/") for f in manifest["clients"]["cursor"]["files"])
    assert not any(f.startswith(".cursor/hooks/") for f in claude["files"])
    assert manifest["clients"]["opencode"]["modules"] == [".opencode/adapter/process-fsm-guard.js", ".opencode/adapter/impeccable-hook.js"]
    assert "files" not in manifest["clients"]["grok"] and "entrypoints" not in manifest["clients"]["dsh"]
    adapter_manifest.check(root)


def test_the_test_only_fixture_helper_is_outside_the_tree_the_manifest_and_digest_a(tmp_path):
    root = make_consumer(tmp_path / "c")
    helper = root / "scripts/process-fsm/shim_fixtures.py"
    helper.write_text("HELPER = 1\n")
    manifest = json.loads((root / cf_shim.MANIFEST).read_text())
    assert "scripts/process-fsm/shim_fixtures.py" not in manifest["clients"]["claude"]["files"]
    tree = adapter_manifest.CORE_TREES[0]
    assert "scripts/process-fsm/shim_fixtures.py" not in cf_shim.enumerate_tree(root, tree)
    assert "scripts/process-fsm/other_module.py" in cf_shim.enumerate_tree(root, tree)
    before = cf_shim.status("claude", root)["adapter"]["digest"]
    helper.write_text("HELPER = 2\n")
    assert cf_shim.status("claude", root)["adapter"]["digest"] == before
    adapter_manifest.check(root)


def test_tool_caches_inside_the_trees_stay_out_of_the_manifest_and_never_diverge(tmp_path):
    root = make_consumer(tmp_path / "c")
    caches = [
        "scripts/process-fsm/.pytest_cache/v/cache/nodeids",
        "scripts/process-fsm/.pytest_cache/README.md",
        "scripts/process-fsm/.pytest_cache/CACHEDIR.TAG",
        "scripts/process-fsm/.pytest_cache/.gitignore",
        "scripts/process-fsm/sub/.pytest_cache/v/cache/lastfailed",
        "scripts/process-fsm/__pycache__/other_module.cpython-312.pyc",
        "scripts/process-fsm/stray.pyc",
        ".agents/skills/impeccable/scripts/.pytest_cache/v/cache/nodeids",
        ".cursor/hooks/.pytest_cache/v/cache/nodeids",
        ".opencode/adapter/.pytest_cache/v/cache/nodeids",
        ".opencode/adapter/node_modules/pkg/index.js",
    ]
    for relative in caches:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[]\n")
    adapter_manifest.write(root, "v1.2.0")
    manifest = json.loads((root / cf_shim.MANIFEST).read_text())
    for client in ("claude", "codex", "cursor", "opencode"):
        listed = manifest["clients"][client]["files"]
        assert not any(".pytest_cache" in f or "__pycache__" in f or "node_modules" in f or f.endswith((".pyc", ".pyo")) for f in listed), client
    for client in ("claude", "codex", "cursor", "opencode"):
        entry = manifest["clients"][client]
        assert not cf_shim.adapter_state(root, entry).divergent, client
    for relative in caches:
        (root / relative).write_text('["changed"]\n')
    (root / "scripts/process-fsm/.pytest_cache/v/cache/new_file").write_text("new\n")
    for client in ("claude", "codex", "cursor", "opencode"):
        state = cf_shim.adapter_state(root, manifest["clients"][client])
        assert not state.divergent and not state.missing, client
    adapter_manifest.check(root)
    (root / "scripts/process-fsm/other_module.py").write_text("VALUE = 9\n")
    assert cf_shim.adapter_state(root, manifest["clients"]["claude"]).divergent


def test_manifest_never_declares_account_for_a_host_without_a_proven_mechanism(tmp_path, monkeypatch):
    monkeypatch.setitem(cf_shim.HOST_REGISTRATION, "opencode", "unproven")
    root = make_consumer(tmp_path / "c")
    entry = json.loads((root / cf_shim.MANIFEST).read_text())["clients"]["opencode"]
    assert entry == {"registration": "unproven"}


def test_manifest_check_detects_drift_and_a_missing_entry_point_stops_the_pin(tmp_path):
    root = make_consumer(tmp_path / "c")
    (root / "scripts/process-fsm/other_module.py").write_text("VALUE = 5\n")
    with pytest.raises(adapter_manifest.ManifestBuildError, match="differs"):
        adapter_manifest.check(root)
    (root / "scripts/process-fsm/claude_adapter.py").unlink()
    with pytest.raises(adapter_manifest.ManifestBuildError, match="claude_adapter.py"):
        adapter_manifest.build(root, "v1.2.0")


def test_remove_of_a_host_subset_keeps_the_shim_while_other_hosts_still_point_to_it(account):
    install_account()
    lines = account_install.run_remove(["cursor"])
    assert cf_shim.shim_root().exists() and (cf_shim.shim_root() / "current" / "cf_shim.py").is_file()
    assert any(line.startswith("shim kept") for line in lines)
    assert not (account / ".cursor/hooks.json").exists()
    assert "cf_shim.py" in (account / ".claude/settings.json").read_text() and "cf_shim.py" in (account / ".codex/hooks.json").read_text()
    # the last managed entry out takes the shim with it
    account_install.run_remove(None)
    assert not cf_shim.shim_root().exists()


def test_a_symlinked_host_config_is_written_through_and_the_link_is_kept(account):
    (account / ".claude").mkdir()
    real = account / "dotfiles/claude-settings.json"
    real.parent.mkdir()
    real.write_text(json.dumps({"theme": "dark"}))
    link = account / ".claude/settings.json"
    link.symlink_to(real)
    install_account(["claude"])
    assert link.is_symlink() and link.resolve() == real.resolve()
    document = json.loads(real.read_text())
    assert document["theme"] == "dark" and "PreToolUse" in document["hooks"]
