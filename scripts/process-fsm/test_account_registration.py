"""`process_event` refuses `hooks_inactive` when a new-pin session has no account registration behind it."""
from __future__ import annotations

import pytest

import account_registration as ar
import adapter_manifest
import cf_shim
import process_event as pe
from process_event import FakeMover, process_event
from shim_fixtures import ALL_HOSTS, install_account, isolate_account, make_consumer, shim_command, trust_all
from test_overlay_fixtures import write_overlay

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
SESSION = "11111111-2222-3333-4444-555555555555"
SCOPE = ("claude", "codex", "cursor", "opencode")


@pytest.fixture
def account(monkeypatch, tmp_path):
    home = isolate_account(monkeypatch, tmp_path)
    monkeypatch.delenv("CLAUDECODE", raising=False)
    return home


def new_pin_consumer(tmp_path, *, manifest=True):
    root = make_consumer(tmp_path / "card-1101-fixture", manifest=False)
    change = root / "openspec" / "changes" / "card-1101-fixture"
    change.mkdir(parents=True)
    for name in ("proposal.md", "design.md", "tasks.md"):
        (change / name).write_text("# x\n")
    write_overlay(root, pin="v1.2.0")
    if manifest:
        adapter_manifest.write(root, "v1.2.0")
    return root


def run(root, event="iniciar_design", client=None, state="Todo"):
    resolved = dict(q=state, q_git="card-1101-fixture", bound_card="1101")
    mover = FakeMover()
    out = process_event(event, cwd=root, card="1101", resolve_fn=lambda *a, **k: resolved, mover=mover, client=client)
    return out, mover


def start_session(root, client, session=SESSION):
    key = "conversation_id" if client == "cursor" else "session_id"
    shim_command(client, "session-start" if client != "opencode" else "session-start", {key: session, "cwd": str(root), "workspace_roots": [str(root)]})


@pytest.mark.parametrize("client", SCOPE)
def test_new_pin_without_the_shim_refuses_every_dependent_transition_naming_client_and_recovery(tmp_path, account, client, monkeypatch):
    root = new_pin_consumer(tmp_path)
    if client == "claude":
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    if client == "codex":
        monkeypatch.setenv("CODEX_THREAD_ID", SESSION)
    for event in sorted(pe.PREFLIGHT_EVENTS):
        out, mover = run(root, event, client=client)
        prefix = {"claude": "claude_evidence", "codex": "codex_evidence"}.get(client, f"{client}_registration")
        assert out["result"] == "reject" and out["reason"] == f"{prefix}:hooks_inactive", (client, event, out)
        assert "install.sh --account" in out["message"] and "shim is not installed" in out["message"]
        assert out["state"] == "Todo" and mover.calls == []


@pytest.mark.parametrize("client", SCOPE)
def test_shim_installed_but_the_client_entry_is_missing(tmp_path, account, client, monkeypatch):
    root = new_pin_consumer(tmp_path)
    install_account([c for c in SCOPE if c != client])
    if client == "claude":
        monkeypatch.setenv("CLAUDECODE", "1")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    if client == "codex":
        monkeypatch.setenv("CODEX_THREAD_ID", SESSION)
    out, _ = run(root, client=client)
    assert out["reason"].endswith(":hooks_inactive") and f"{client} has no Covenant Flow account registration" in out["message"]


def test_registered_but_unreviewed_registration_or_adapter(tmp_path, account):
    root = new_pin_consumer(tmp_path)
    install_account()
    out, _ = run(root, client="cursor")
    assert out["reason"] == "cursor_registration:hooks_unreviewed" and "registration" in out["message"]
    cf_shim.record_review("registration", "cursor", cf_shim.registration_digest("cursor"), {})
    out, _ = run(root, client="cursor")
    assert out["reason"] == "cursor_registration:hooks_unreviewed" and "adapter" in out["message"]
    cf_shim.record("cursor", root)
    out, mover = run(root, client="cursor")
    assert (out["result"], out["to"]) == ("transition", "Design")


@pytest.mark.parametrize("client", ("cursor", "opencode"))
def test_clients_without_a_session_identity_need_shim_and_reviewed_registration_only(tmp_path, account, client):
    root = new_pin_consumer(tmp_path)
    install_account()
    trust_all(root)
    out, _ = run(root, client=client)
    assert (out["result"], out["to"]) == ("transition", "Design")


def test_codex_session_needs_the_shim_heartbeat(tmp_path, account, monkeypatch):
    root = new_pin_consumer(tmp_path)
    install_account()
    trust_all(root)
    monkeypatch.setenv("CODEX_THREAD_ID", SESSION)
    out, mover = run(root, client="codex")
    assert out["reason"] == "codex_evidence:hooks_inactive" and "no shim heartbeat" in out["message"] and mover.calls == []
    start_session(root, "codex")
    seen = []
    import codex_evidence
    monkeypatch.setattr(codex_evidence, "preflight", lambda **kw: seen.append(kw["root"]) or {"result": "ready"})
    out, _ = run(root, client="codex")
    assert out["result"] == "transition" and seen


def test_registration_changed_after_the_session_started_is_hooks_changed(tmp_path, account, monkeypatch):
    root = new_pin_consumer(tmp_path)
    install_account()
    trust_all(root)
    monkeypatch.setenv("CODEX_THREAD_ID", SESSION)
    start_session(root, "codex")
    hooks = cf_shim.host_config_path("codex")
    import json
    document = json.loads(hooks.read_text())
    document["hooks"]["Stop"][0]["hooks"][0]["timeout"] = 45
    hooks.write_text(json.dumps(document))
    cf_shim.record("codex", root)
    out, _ = run(root, client="codex")
    assert out["reason"] == "codex_evidence:hooks_changed" and "new session" in out["message"]


def test_claude_goes_through_the_account_check_inside_its_evidence_preflight(tmp_path, account, monkeypatch):
    root = new_pin_consumer(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    out, _ = run(root, client="claude")
    assert out["reason"] == "claude_evidence:hooks_inactive" and "shim is not installed" in out["message"]
    install_account()
    trust_all(root)
    out, _ = run(root, client="claude")
    assert out["reason"] == "claude_evidence:hooks_inactive" and "no shim heartbeat" in out["message"]


def test_unproven_registration_is_refused_citing_it_and_never_presented_as_protected(tmp_path, account, monkeypatch):
    monkeypatch.setitem(cf_shim.HOST_REGISTRATION, "cursor", "unproven")
    root = new_pin_consumer(tmp_path)
    install_account(["claude", "codex", "opencode"])
    trust_all(root, ["claude", "codex", "opencode"])
    out, mover = run(root, client="cursor")
    assert out["reason"] == "cursor_registration:hooks_inactive" and "registration=unproven" in out["message"] and mover.calls == []
    assert ar.registration_of(root, "cursor") == "unproven"


def test_pin_before_account_registration_keeps_todays_behavior(tmp_path, account, monkeypatch):
    root = new_pin_consumer(tmp_path, manifest=False)
    assert ar.require_active("cursor", root) is None
    for client in ("cursor", "opencode"):
        out, _ = run(root, client=client)
        assert (out["result"], out["to"]) == ("transition", "Design")
    monkeypatch.setenv("CODEX_THREAD_ID", SESSION)
    out, _ = run(root, client="codex")
    assert out["reason"].startswith("codex_evidence:") and "shim" not in out["message"]


@pytest.mark.parametrize("client", ("grok", "dsh"))
def test_grok_and_dsh_are_never_checked_for_the_shim(tmp_path, account, client):
    root = new_pin_consumer(tmp_path)
    out, _ = run(root, client=client)
    assert (out["result"], out["to"]) == ("transition", "Design")
    assert ar.require_active(client, root) is None
    assert ar.registration_of(root, client) == "project"


def test_events_outside_the_preflight_set_are_not_checked(tmp_path, account):
    root = new_pin_consumer(tmp_path)
    out, _ = run(root, "fechar_release", client="cursor", state="Homologado")
    assert not out["reason"].startswith("cursor_registration")


def test_a_broken_manifest_is_a_visible_refusal_not_an_old_pin(tmp_path, account):
    root = new_pin_consumer(tmp_path)
    (root / cf_shim.MANIFEST).write_text("{broken")
    out, _ = run(root, client="cursor")
    assert out["reason"] == "cursor_registration:hooks_inactive" and "manifest" in out["message"]


def test_diverged_adapter_is_refused_before_the_transition(tmp_path, account):
    root = new_pin_consumer(tmp_path)
    install_account()
    trust_all(root)
    (root / "scripts/process-fsm/other_module.py").write_text("VALUE = 7\n")
    out, mover = run(root, client="cursor")
    assert out["reason"] == "cursor_registration:adapter_divergent" and mover.calls == []
