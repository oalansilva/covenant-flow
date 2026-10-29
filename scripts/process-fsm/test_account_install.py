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
    assert {"SessionStart", "PreToolUse", "PostToolUse", "SubagentStop", "Stop", "UserPromptSubmit"} == set(claude)
    pre = claude["PreToolUse"][0]
    # anchored: a tool that merely contains "Write" (TodoWrite) never reaches the adapter; the app's `mcp__ccd_*` do
    assert pre["matcher"] == account_install.PRETOOL_MATCHER == "^(Bash|Edit|Write|MultiEdit|NotebookEdit|Agent|mcp__ccd_.*)$"
    import re
    assert all(re.search(pre["matcher"], name) for name in ("Bash", "Agent", "mcp__ccd_session__spawn_task", "mcp__ccd_future__tool"))
    assert not any(re.search(pre["matcher"], name) for name in ("TodoWrite", "WebFetch", "Read", "EnterWorktree"))
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
        "scripts/process-fsm/sub/__pycache__/helper.cpython-312.pyc",
        ".agents/skills/impeccable/scripts/.pytest_cache/v/cache/nodeids",
        ".cursor/hooks/.pytest_cache/v/cache/nodeids",
        ".opencode/adapter/.pytest_cache/v/cache/nodeids",
    ]
    for relative in caches:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[]\n")
    adapter_manifest.write(root, "v1.2.0")
    manifest = json.loads((root / cf_shim.MANIFEST).read_text())
    for client in ("claude", "codex", "cursor", "opencode"):
        listed = manifest["clients"][client]["files"]
        assert not any(".pytest_cache" in f or "__pycache__" in f for f in listed), client
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


def test_remove_takes_the_versioned_shim_directories_and_the_current_link_with_no_orphan(account):
    install_account()
    root = cf_shim.shim_root()
    (root / "0.9.0").mkdir()
    (root / "0.9.0" / "cf_shim.py").write_text("# an older shim\n")
    assert (root / "current").is_symlink() and (root / cf_shim.SHIM_VERSION).is_dir()
    account_install.run_remove(None)
    assert not root.exists() and not (root / "current").is_symlink()
    assert [p for p in account.rglob("*") if "shim" in p.name] == []


def test_remove_deletes_the_target_of_a_symlinked_config_the_installer_alone_created(account):
    (account / ".claude").mkdir()
    real = account / "dotfiles/hooks.json"
    real.parent.mkdir()
    real.write_text("{}")
    (account / ".codex").mkdir()
    (account / ".codex/hooks.json").symlink_to(real)
    install_account(["codex"])
    assert real.is_file() and "cf_shim.py" in real.read_text()
    account_install.run_remove(None)
    assert not (account / ".codex/hooks.json").is_symlink() and not (account / ".codex/hooks.json").exists()
    assert not real.exists()  # the link and its target both go, no orphan with the entries left in it


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


# --- remove is lossless (R18, R19) -----------------------------------------------------------------


@pytest.mark.parametrize("client,relative,content", [
    ("claude", ".claude/settings.json", "{}"),
    ("claude", ".claude/settings.json", '{"theme": "dark"}'),
    ("claude", ".claude/settings.json", '{"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo foreign"}]}]}}'),
    ("codex", ".codex/hooks.json", "{}"),
    ("codex", ".codex/hooks.json", '{"hooks": {}}'),
    ("cursor", ".cursor/hooks.json", "{}"),
    ("cursor", ".cursor/hooks.json", '{"version": 1}'),
    ("cursor", ".cursor/hooks.json", '{"version": 1, "hooks": {"stop": [{"command": "echo foreign"}]}}'),
])
def test_remove_on_a_file_without_covenant_flow_entries_leaves_it_byte_identical(account, client, relative, content):
    target = account / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content + "\n")
    before = target.read_bytes()
    lines = account_install.run_remove([client])
    assert target.read_bytes() == before
    assert any("nothing to remove" in line for line in lines)


def test_remove_after_install_leaves_no_empty_hooks_object_and_keeps_foreign_entries(account):
    (account / ".claude").mkdir()
    (account / ".claude/settings.json").write_text(json.dumps({"theme": "dark"}))
    (account / ".cursor").mkdir()
    (account / ".cursor/hooks.json").write_text(json.dumps({"version": 1, "extra": True}))
    install_account()
    account_install.run_remove(None)
    assert json.loads((account / ".claude/settings.json").read_text()) == {"theme": "dark"}
    assert json.loads((account / ".cursor/hooks.json").read_text()) == {"version": 1, "extra": True}
    for path in account.rglob("*.json"):
        assert '"hooks": {}' not in path.read_text().replace('"hooks":{}', '"hooks": {}'), path


# --- the digest of the adapter covers what runs and only what runs (R1-R7) -------------------------


def adapter_digest(root, client="claude"):
    return cf_shim.status(client, root)["adapter"]["digest"]


def test_the_route_catalog_and_fixture_modules_are_data_not_adapter_code(tmp_path):
    root = make_consumer(tmp_path / "c")
    (root / "scripts/process-fsm/route-landmarks.yaml").write_text("routes: []\n")
    (root / "scripts/process-fsm/claude_fixtures.py").write_text("FIXTURE = 1\n")
    (root / "scripts/process-fsm/model_selection_fixtures.py").write_text("FIXTURE = 1\n")
    adapter_manifest.write(root, "v1.2.0")
    manifest = json.loads((root / cf_shim.MANIFEST).read_text())
    for client in ("claude", "codex"):
        files = manifest["clients"][client]["files"]
        assert not any(f.endswith(("route-landmarks.yaml", "_fixtures.py")) for f in files), client
    before = adapter_digest(root)
    for name, text in (("route-landmarks.yaml", "routes: [/combo/results]\n"), ("claude_fixtures.py", "FIXTURE = 2\n"), ("model_selection_fixtures.py", "FIXTURE = 3\n")):
        (root / "scripts/process-fsm" / name).write_text(text)
        state = cf_shim.status("claude", root)["adapter"]
        assert state["digest"] == before and not state["divergent"] and not state["missing"], name
    # and a new fixture module appearing later is not divergence either
    (root / "scripts/process-fsm/other_fixtures.py").write_text("X = 1\n")
    assert not cf_shim.status("claude", root)["adapter"]["divergent"]
    adapter_manifest.check(root)


def test_editing_the_route_catalog_does_not_deny_the_hooks(tmp_path, account):
    from shim_fixtures import shim_command
    root = make_consumer(tmp_path / "c")
    install_account()
    trust_all(root)
    payload = {"session_id": "11111111-2222-3333-4444-555555555555", "cwd": str(root), "tool_name": "Bash", "tool_input": {"command": "ls"}}
    (root / "scripts/process-fsm/route-landmarks.yaml").write_text("routes: [/new]\n")
    (root / "scripts/process-fsm/claude_fixtures.py").write_text("FIXTURE = 9\n")
    result = shim_command("claude", "pre-tool-use", payload)
    assert "adapter_divergent" not in result.stdout and result.returncode == 0


def test_changing_only_the_executed_argv_makes_A_unreviewed(tmp_path, account):
    from shim_fixtures import shim_command
    root = make_consumer(tmp_path / "c")
    install_account()
    trust_all(root)
    manifest = json.loads((root / cf_shim.MANIFEST).read_text())
    reviewed = cf_shim.status("claude", root)["adapter"]
    assert reviewed["reviewed"]
    manifest["clients"]["claude"]["entrypoints"]["pre-tool-use"] = ["python3", "scripts/process-fsm/other_module.py", "pre-tool-use"]
    (root / cf_shim.MANIFEST).write_text(json.dumps(manifest))
    changed = cf_shim.status("claude", root)["adapter"]
    assert changed["digest"] != reviewed["digest"] and not changed["reviewed"] and not changed["divergent"]
    payload = {"session_id": "11111111-2222-3333-4444-555555555555", "cwd": str(root), "tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert "hooks_unreviewed" in shim_command("claude", "pre-tool-use", payload).stdout
    # the OpenCode modules are executed too: the same holds for them
    opencode = json.loads((root / cf_shim.MANIFEST).read_text())
    opencode["clients"]["claude"] = manifest["clients"]["claude"]
    before = cf_shim.status("opencode", root)["adapter"]["digest"]
    opencode["clients"]["opencode"]["modules"] = list(reversed(opencode["clients"]["opencode"]["modules"]))
    (root / cf_shim.MANIFEST).write_text(json.dumps(opencode))
    assert cf_shim.status("opencode", root)["adapter"]["digest"] != before


def test_a_module_reached_through_a_directory_symlink_is_part_of_A(tmp_path):
    root = make_consumer(tmp_path / "c")
    real = root / "shared_modules"
    real.mkdir()
    (real / "helper.py").write_text("VALUE = 1\n")
    link = root / "scripts/process-fsm/linked"
    link.symlink_to(real, target_is_directory=True)
    adapter_manifest.write(root, "v1.2.0")
    manifest = json.loads((root / cf_shim.MANIFEST).read_text())
    assert "scripts/process-fsm/linked/helper.py" in manifest["clients"]["claude"]["files"]
    before = adapter_digest(root)
    (real / "helper.py").write_text("VALUE = 2\n")  # the target changes, the link path does not
    state = cf_shim.status("claude", root)["adapter"]
    assert "scripts/process-fsm/linked/helper.py" in state["divergent"] and not state["reviewed"]
    adapter_manifest.write(root, "v1.2.0")
    assert adapter_digest(root) != before


def test_a_directory_symlink_leaving_the_repository_fails_the_pin_and_the_shim(tmp_path, account):
    from shim_fixtures import shim_command
    root = make_consumer(tmp_path / "c")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evil.py").write_text("VALUE = 1\n")
    install_account()
    trust_all(root)
    payload = {"session_id": "11111111-2222-3333-4444-555555555555", "cwd": str(root), "tool_name": "Bash", "tool_input": {"command": "ls"}}
    assert "manifest_invalid" not in shim_command("claude", "pre-tool-use", payload).stdout
    (root / "scripts/process-fsm/escape").symlink_to(outside, target_is_directory=True)
    denied = shim_command("claude", "pre-tool-use", payload).stdout  # the shim refuses visibly too, never lets the module in
    assert "manifest_invalid" in denied and "leaves the repository" in denied
    with pytest.raises(cf_shim.ManifestError, match="escape.*leaves the repository"):
        adapter_manifest.build(root, "v1.2.0")
    assert adapter_manifest.main(["write", "--root", str(root), "--pin", "v1.2.0"]) == 2
    # a symlink loop is refused as well, not walked forever
    (root / "scripts/process-fsm/escape").unlink()
    (root / "scripts/process-fsm/loop").symlink_to(root / "scripts/process-fsm", target_is_directory=True)
    with pytest.raises(cf_shim.ManifestError, match="loop"):
        adapter_manifest.build(root, "v1.2.0")


def test_a_loose_pyc_and_node_modules_are_part_of_A_but_pycache_is_not(tmp_path):
    root = make_consumer(tmp_path / "c")
    before = adapter_digest(root)
    pycache = root / "scripts/process-fsm/__pycache__"
    pycache.mkdir()
    (pycache / "claude_adapter.cpython-312.pyc").write_bytes(b"cache")
    assert adapter_digest(root) == before and not cf_shim.status("claude", root)["adapter"]["divergent"]
    (root / "scripts/process-fsm/stray.pyc").write_bytes(b"importable bytecode")
    assert "scripts/process-fsm/stray.pyc (not in manifest)" in cf_shim.status("claude", root)["adapter"]["divergent"]
    adapter_manifest.write(root, "v1.2.0")
    manifest = json.loads((root / cf_shim.MANIFEST).read_text())
    assert "scripts/process-fsm/stray.pyc" in manifest["clients"]["claude"]["files"]
    assert not any("__pycache__" in f for f in manifest["clients"]["claude"]["files"])
    assert adapter_digest(root) != before
    node = root / ".opencode/adapter/node_modules/pkg/index.js"
    node.parent.mkdir(parents=True)
    node.write_text("module.exports = 1\n")
    adapter_manifest.write(root, "v1.2.0")
    assert ".opencode/adapter/node_modules/pkg/index.js" in json.loads((root / cf_shim.MANIFEST).read_text())["clients"]["opencode"]["files"]


def test_a_listed_file_without_a_digest_fails_the_pin_naming_it_and_writes_no_manifest(tmp_path):
    root = make_consumer(tmp_path / "c")
    (root / cf_shim.MANIFEST).unlink()
    target = root / "scripts/process-fsm/other_module.py"
    target.unlink()
    (root / "scripts/process-fsm/real_module.py").write_text("VALUE = 1\n")
    target.symlink_to(root / "scripts/process-fsm/real_module.py")  # a file symlink has no digest
    with pytest.raises(adapter_manifest.ManifestBuildError, match="other_module.py"):
        adapter_manifest.build(root, "v1.2.0")
    assert adapter_manifest.main(["write", "--root", str(root), "--pin", "v1.2.0"]) == 2
    assert not (root / cf_shim.MANIFEST).exists()


def test_the_real_impeccable_detector_is_part_of_A_and_one_byte_changes_it(tmp_path):
    import shutil
    detector = HERE.parents[1] / ".agents/skills/impeccable/scripts/detector"
    if not detector.is_dir():
        pytest.skip("this tree carries no vendored Impeccable detector")
    root = make_consumer(tmp_path / "c")
    shutil.copytree(detector, root / ".agents/skills/impeccable/scripts/detector", dirs_exist_ok=True)
    adapter_manifest.write(root, "v1.2.0")
    listed = json.loads((root / cf_shim.MANIFEST).read_text())["clients"]["claude"]["files"]
    real = [f for f in listed if f.startswith(".agents/skills/impeccable/scripts/detector/") and f.endswith("detect-antipatterns.mjs")]
    assert real, "the real detector entry module must be listed"
    reviewed = adapter_digest(root)
    path = root / real[0]
    path.write_bytes(path.read_bytes() + b" ")
    state = cf_shim.status("claude", root)["adapter"]
    assert real[0] in state["divergent"]
    adapter_manifest.write(root, "v1.2.0")
    assert adapter_digest(root) != reviewed
