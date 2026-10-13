from __future__ import annotations

from pathlib import Path

import pytest

import process_event as pe
from process_event import FakeMover, nearest_agent_client, native_client, process_event
from test_overlay_fixtures import write_overlay

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture
def card(tmp_path):
    change = tmp_path / "openspec" / "changes" / "card-1101-fixture"
    change.mkdir(parents=True)
    for name in ("proposal.md", "design.md", "tasks.md"):
        (change / name).write_text("# x\n")
    write_overlay(tmp_path)
    return tmp_path


def run(card, event="iniciar_design", state="Todo", **kw):
    resolved = dict(q=state, q_git="card-1101-fixture", bound_card="1101")
    mover = kw.pop("mover", FakeMover())
    return process_event(event, cwd=card, card="1101", resolve_fn=lambda *a, **k: resolved, mover=mover, **kw), mover


def test_claude_dependent_events_are_refused_visibly_when_hooks_are_not_active(card, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "11111111-2222-3333-4444-555555555555")
    for event in sorted(pe.PREFLIGHT_EVENTS):
        out, mover = run(card, event)
        assert out["result"] == "reject" and out["reason"] == "claude_evidence:hooks_inactive", event
        assert mover.calls == []


def test_claude_preflight_pass_lets_the_shared_fsm_decide_without_new_edges(card, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    seen = []
    import claude_evidence
    monkeypatch.setattr(claude_evidence, "preflight", lambda **kw: seen.append(kw["root"]) or {"result": "ready"})
    out, mover = run(card, "iniciar_design", "Todo", client="claude")
    assert seen == [card] and out["result"] == "transition" and out["to"] == "Design"
    # the same event reaches the same shared decision for the other clients
    monkeypatch.delenv("CLAUDECODE")
    other, _ = run(card, "iniciar_design", "Todo", client="cursor")
    assert (other["result"], other["to"]) == ("transition", "Design")


def test_events_outside_the_preflight_set_do_not_require_claude_evidence(card, monkeypatch):
    monkeypatch.setattr(pe, "native_client", lambda: "claude")
    import claude_evidence
    monkeypatch.setattr(claude_evidence, "preflight", lambda **kw: (_ for _ in ()).throw(AssertionError("must not run")))
    out, _ = run(card, "fechar_release", "Homologado", client="claude")
    assert out["reason"] != "claude_evidence:hooks_inactive"


@pytest.mark.parametrize("event,state", [("priorizar", "Em Refinamento"), ("aprovar_design", "Aprovação de Design"), ("homologar", "Done"), ("nao_homologar", "Done")])
def test_human_events_are_rejected_for_claude_and_status_is_unchanged(card, monkeypatch, event, state):
    monkeypatch.setenv("CLAUDECODE", "1")
    out, mover = run(card, event, state, client="claude")
    assert out["result"] == "reject" and out["reason"] in {"actor", "claude_evidence:hooks_inactive"} and mover.calls == []


def test_implemente_has_no_edge_in_todo_and_changes_nothing(card, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    out, mover = run(card, "implemente", "Todo", client="claude")
    assert out["result"] == "reject" and out["state"] == "Todo" and out["to"] is None and mover.calls == []


def test_native_identity_conflict_is_refused(card, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    out, mover = run(card, "iniciar_design", client="cursor")
    assert out["reason"] == "claude_evidence:ambiguous_client" and mover.calls == []
    monkeypatch.setenv("COVENANT_CLIENT", "grok")
    out, _ = run(card, "iniciar_design")
    assert out["reason"] == "claude_evidence:ambiguous_client"


def test_without_native_signal_other_clients_keep_their_path(card):
    out, _ = run(card, "iniciar_design", client="cursor")
    assert out["result"] == "transition"


# --- nested Codex inside Claude Code (task 6.6) -----------------------------------------


def test_codex_inside_claude_bash_is_still_codex(card, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.setattr(pe, "nearest_agent_client", lambda *a, **k: "codex")
    assert native_client() == "codex"
    out, mover = run(card, "iniciar_design")
    assert out["reason"].startswith("codex_evidence:") and out["reason"] != "codex_evidence:ambiguous_client" and mover.calls == []
    # explicit codex stays accepted, an explicit claude is the conflicting identity
    assert run(card, "iniciar_design", client="codex")[0]["reason"].startswith("codex_evidence:")
    assert run(card, "iniciar_design", client="claude")[0]["reason"] == "codex_evidence:ambiguous_client"


def test_both_signals_without_a_demonstrable_innermost_client_are_ambiguous(card, monkeypatch):
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    monkeypatch.setattr(pe, "nearest_agent_client", lambda *a, **k: None)
    out, mover = run(card, "iniciar_design", client="codex")
    assert out["result"] == "reject" and out["reason"].endswith("ambiguous_client") and mover.calls == []


def test_codex_alone_is_detected_exactly_as_before(card, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    assert native_client() == "codex"
    assert run(card, "iniciar_design", client="cursor")[0]["reason"] == "codex_evidence:ambiguous_client"


def tree(root: Path, chain):
    """chain: [(pid, ppid, argv)], innermost first."""
    for pid, ppid, argv in chain:
        directory = root / str(pid)
        directory.mkdir(parents=True)
        (directory / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + b"\0")
        (directory / "stat").write_text(f"{pid} (proc) S {ppid} 0 0\n")


def test_nearest_agent_client_reads_the_innermost_ancestor(tmp_path):
    tree(tmp_path, [(40, 30, ["python3", "process_event.py"]), (30, 20, ["codex", "exec"]), (20, 10, ["node", "/usr/bin/claude"]), (10, 1, ["bash"])])
    assert nearest_agent_client(40, tmp_path) == "codex"
    other = tmp_path / "b"
    other.mkdir()
    tree(other, [(40, 30, ["python3", "x"]), (30, 20, ["node", "/home/u/.local/bin/claude"]), (20, 10, ["codex"]), (10, 1, ["bash"])])
    assert nearest_agent_client(40, other) == "claude"
    empty = tmp_path / "c"
    empty.mkdir()
    tree(empty, [(40, 10, ["python3"]), (10, 1, ["bash"])])
    assert nearest_agent_client(40, empty) is None
    assert nearest_agent_client(99999, empty) is None
