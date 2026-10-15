"""Residual of the #1101 that enters the #1103: Guard destinations (R33), native client for Cursor/OpenCode (R10),
the T16 parent check and the T5 tokens at the event (R26, R28), and the nucleus installer in the review diff (R21)."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import account_registration  # noqa: F401  (imported so the refusal module is loaded like in production)
import process_event as pe
from guard import decide, extract_path, strip_heredoc_bodies
from materialize_review_diff import materialize
from model_selection_fixtures import machine_models  # noqa: F401  (autouse isolated account)
from process_event import FakeMover, process_event
from shim_fixtures import init_git, isolate_account, make_consumer, write
from test_guard import SILENT, _init_repo, _shell_payload
from test_overlay_fixtures import write_overlay

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


# --- R33: the real destination of a shell redirection -----------------------------------------------------------------------


def repo_on(tmp_path: Path, branch: str) -> Path:
    repo = tmp_path / "work"
    _init_repo(repo, branch, "backend/app/main.py")
    return repo


def scratchpad(tmp_path: Path) -> Path:
    pad = tmp_path / "session-scratchpad"
    (pad / "backend").mkdir(parents=True)  # a scratch folder that merely looks like product: still outside the repo
    return pad


def test_a_redirect_to_the_scratchpad_outside_the_repo_is_not_a_product_write(tmp_path):
    repo = repo_on(tmp_path, "develop")
    pad = scratchpad(tmp_path)
    for command in (f"echo notes > {pad}/backend/plan.md", f"cat report.txt | tee {pad}/backend/out.txt", f"echo x >> {pad}/backend/log.txt", f"printf x > {pad}/note.txt"):
        assert extract_path({"command": command, "cwd": str(repo)}) is None, command
        assert decide(_shell_payload(repo, command, status="Em desenvolvimento"), status_provider=SILENT)["permission"] == "allow", command


def test_a_relative_redirect_that_climbs_out_of_the_repo_is_resolved_too(tmp_path):
    repo = repo_on(tmp_path, "develop")
    pad = scratchpad(tmp_path)
    relative = f"../{pad.name}/backend/plan.md"
    assert extract_path({"command": f"echo x > {relative}", "cwd": str(repo)}) is None


def test_append_markers_inside_a_heredoc_body_are_text(tmp_path):
    repo = repo_on(tmp_path, "develop")
    pad = scratchpad(tmp_path)
    command = f"cat > {pad}/notes.md <<'EOF'\nusage: tool >> backend/app/main.py\nand echo y > backend/app/main.py\nEOF"
    assert extract_path({"command": command, "cwd": str(repo)}) is None
    assert decide(_shell_payload(repo, command, status="Em desenvolvimento"), status_provider=SILENT)["permission"] == "allow"
    stripped = strip_heredoc_bodies(command)
    assert "backend/app/main.py" not in stripped and stripped.startswith(f"cat > {pad}/notes.md")
    # tab-indented terminator, quoted and unquoted delimiters
    assert "main.py" not in strip_heredoc_bodies("cat <<-EOT\n\techo a >> backend/app/main.py\n\tEOT\ntrue")
    assert "main.py" not in strip_heredoc_bodies('cat <<"EOT"\necho a >> backend/app/main.py\nEOT')


def test_a_heredoc_fed_to_an_interpreter_is_code_and_keeps_being_judged(tmp_path):
    repo = repo_on(tmp_path, "develop")
    for runner in ("bash", "sh", "python3", "node"):
        command = f"{runner} <<'EOF'\necho x > backend/app/main.py\nEOF"
        assert extract_path({"command": command, "cwd": str(repo)}) == "backend/app/main.py", runner
        assert decide(_shell_payload(repo, command, status="Em desenvolvimento"), status_provider=SILENT)["permission"] == "deny", runner
    piped = "cat <<'EOF' | bash\necho x > backend/app/main.py\nEOF"
    assert extract_path({"command": piped, "cwd": str(repo)}) == "backend/app/main.py"


def test_a_redirect_into_the_repository_is_still_denied_as_before(tmp_path):
    repo = repo_on(tmp_path, "develop")
    for command in ("echo x > backend/app/main.py", f"echo x > {repo}/backend/app/main.py", "echo x >> ./backend/new.py", "echo x | tee backend/app/main.py"):
        result = decide(_shell_payload(repo, command, status="Em desenvolvimento"), status_provider=SILENT)
        assert result["permission"] == "deny", command
    # a heredoc that writes INTO the repo is judged by the redirect on its own command line
    written = f"cat > {repo}/backend/app/main.py <<'EOF'\nbody\nEOF"
    assert decide(_shell_payload(repo, written, status="Em desenvolvimento"), status_provider=SILENT)["permission"] == "deny"


def test_a_redirect_into_another_checkout_of_the_project_is_not_a_scratchpad(tmp_path):
    import guard

    card = tmp_path / "card"
    _init_repo(card, "card-1103-x", "backend/app/main.py")
    integration = tmp_path / "integration"
    _init_repo(integration, "develop", "backend/app/main.py")
    pad = scratchpad(tmp_path)
    # outside this repo but inside another checkout: still judged by the product globs (the old /tmp rule aside)
    assert guard._destination_outside_repos(str(integration / "backend/app/main.py"), card) is False
    assert guard._destination_outside_repos(str(pad / "backend/plan.md"), card) is True
    assert guard._destination_outside_repos(str(card / "backend/app/main.py"), card) is False
    assert guard._destination_outside_repos("backend/app/main.py", card) is False  # inside the repo
    assert guard._destination_outside_repos("backend/app/main.py", None) is False  # repository unknown: undecided


def test_a_variable_destination_stays_undecided_and_is_not_promoted_to_a_sink(tmp_path):
    repo = repo_on(tmp_path, "develop")
    assert extract_path({"command": 'echo x > "$OUT"', "cwd": str(repo)}) is None  # nothing product-looking in it
    assert extract_path({"command": f"cp x backend/app/main.py", "cwd": str(repo)}) == "backend/app/main.py"


# --- R10: Cursor and OpenCode are detected natively for hooks_inactive --------------------------------------------------------


def new_pin_consumer(tmp_path: Path) -> Path:
    from shim_fixtures import make_consumer as _make
    import adapter_manifest

    root = _make(tmp_path / "card-1101-fixture", manifest=False)
    change = root / "openspec" / "changes" / "card-1101-fixture"
    change.mkdir(parents=True)
    for name in ("proposal.md", "design.md", "tasks.md"):
        (change / name).write_text("# x\n")
    write_overlay(root, pin="v1.2.0")
    adapter_manifest.write(root, "v1.2.0")
    return root


def run_event(root: Path, **kw):
    resolved = dict(q="Todo", q_git="card-1101-fixture", bound_card="1101")
    mover = FakeMover()
    out = process_event("iniciar_design", cwd=root, card="1101", resolve_fn=lambda *a, **k: resolved, mover=mover, **kw)
    return out, mover


@pytest.mark.parametrize("client,variable", [("cursor", "CURSOR_AGENT"), ("cursor", "CURSOR_VERSION"), ("opencode", "OPENCODE")])
def test_cursor_and_opencode_refuse_hooks_inactive_without_client_flag_or_covenant_client(tmp_path, monkeypatch, client, variable):
    isolate_account(monkeypatch, tmp_path)
    root = new_pin_consumer(tmp_path)
    monkeypatch.setenv(variable, "1")
    out, mover = run_event(root)  # no `client=`, no COVENANT_CLIENT
    assert out["result"] == "reject" and out["reason"] == f"{client}_registration:hooks_inactive" and mover.calls == []
    assert "install.sh --account" in out["message"]


def test_an_explicit_client_always_wins_over_the_native_host_signal(tmp_path, monkeypatch):
    isolate_account(monkeypatch, tmp_path)
    root = new_pin_consumer(tmp_path)
    monkeypatch.setenv("CURSOR_AGENT", "1")
    out, _ = run_event(root, client="grok")  # a Grok session inside a Cursor terminal stays Grok
    assert (out["result"], out["to"]) == ("transition", "Design")
    monkeypatch.setenv("COVENANT_CLIENT", "dsh")
    out, _ = run_event(root)
    assert (out["result"], out["to"]) == ("transition", "Design")


def test_no_native_signal_keeps_todays_path(tmp_path, monkeypatch):
    isolate_account(monkeypatch, tmp_path)
    root = new_pin_consumer(tmp_path)
    assert pe.host_client() is None
    out, _ = run_event(root)
    assert (out["result"], out["to"]) == ("transition", "Design")


def test_two_host_signals_are_resolved_by_the_innermost_agent_process(monkeypatch):
    monkeypatch.setenv("CURSOR_AGENT", "1")
    monkeypatch.setenv("OPENCODE", "1")
    monkeypatch.setattr(pe, "nearest_agent_client", lambda *a, **k: "opencode")
    assert pe.host_client() == "opencode"
    monkeypatch.setattr(pe, "nearest_agent_client", lambda *a, **k: None)
    assert pe.host_client() is None


def test_claude_and_codex_still_win_over_a_cursor_terminal(tmp_path, monkeypatch):
    isolate_account(monkeypatch, tmp_path)
    monkeypatch.setenv("CURSOR_AGENT", "1")
    monkeypatch.setenv("CODEX_THREAD_ID", "t-1")
    assert pe.native_client() == "codex"
    root = new_pin_consumer(tmp_path)
    out, _ = run_event(root)
    assert out["reason"].startswith("codex_evidence:")


# --- R26: T16 in Claude Code checks the parent at the event ------------------------------------------------------------------------


def t16_kwargs():
    from test_process_event import _t16_kwargs

    return _t16_kwargs()


def test_fechar_release_in_claude_is_refused_for_a_parent_on_the_judgment_model_and_status_is_unchanged(tmp_path, monkeypatch):
    from claude_fixtures import SESSION, World, assistant
    from t16 import RecordingT16Closer

    world = World(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    world.rows.append(assistant(world.repo, model="claude-opus-5-5", effort="high", content=[], msg_id="m-opus"))
    world.flush()
    mover, closer = FakeMover(), RecordingT16Closer()
    out = process_event("fechar_release", mover=mover, t16_closer=closer, client="claude", **t16_kwargs())
    assert out["result"] == "reject" and out["reason"] == "claude_evidence:parent_model"
    assert "claude-opus-5-5/high" in out["message"] and "claude-sonnet-5-5/high" in out["message"] and "Status unchanged" in out["message"]
    assert mover.calls == [] and closer.calls == []


def test_fechar_release_in_claude_is_refused_when_the_parent_is_unavailable(tmp_path, monkeypatch):
    from claude_fixtures import SESSION, World
    from t16 import RecordingT16Closer

    world = World(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    world.parent.unlink()
    mover, closer = FakeMover(), RecordingT16Closer()
    out = process_event("fechar_release", mover=mover, t16_closer=closer, client="claude", **t16_kwargs())
    assert out["result"] == "reject" and out["reason"] == "claude_evidence:parent_model" and "unobserved" in out["message"]
    assert mover.calls == [] and closer.calls == []


def test_fechar_release_in_claude_passes_the_parent_check_on_the_captured_pair(tmp_path, monkeypatch):
    from claude_fixtures import SESSION, World
    from t16 import RecordingT16Closer

    World(tmp_path)  # parent observed on claude-sonnet-5-5 / high = the machine's claude/execucao
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    mover, closer = FakeMover(), RecordingT16Closer()
    out = process_event("fechar_release", mover=mover, t16_closer=closer, client="claude", **t16_kwargs())
    assert out["result"] == "transition" and out["to"] == "Pronto" and mover.calls


def test_the_parent_check_of_t16_is_only_for_the_claude_client(tmp_path, monkeypatch):
    from t16 import RecordingT16Closer

    monkeypatch.delenv("CLAUDECODE", raising=False)
    mover, closer = FakeMover(), RecordingT16Closer()
    out = process_event("fechar_release", mover=mover, t16_closer=closer, client="cursor", **t16_kwargs())
    assert out["result"] == "transition" and out["to"] == "Pronto"


def test_an_explicit_birth_capture_is_the_pair_the_parent_is_compared_with(tmp_path, monkeypatch):
    from claude_fixtures import SESSION, World
    from model_selection import resolve
    from t16 import RecordingT16Closer

    World(tmp_path)
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", SESSION)
    capture = resolve("claude", "execucao", role="fecho-lote")
    seen = []

    def checker(**kw):
        seen.append(kw["capture"])
        return type("Check", (), {"ok": False, "message": "diverges"})()

    refusal = pe.claude_closeout_parent_refusal(tmp_path, capture, checker)
    assert seen == [capture]  # the birth capture given is the one compared, not a fresh read of the selection file
    assert refusal and "diverges" in refusal and "vs captured claude/execucao claude-sonnet-5-5/high" in refusal


# --- R28: T5 checks the gate tokens of design.md --------------------------------------------------------------------------------------


def design_change(tmp_path: Path, design: str) -> Path:
    change = tmp_path / "openspec" / "changes" / "card-1103-tokens"
    change.mkdir(parents=True)
    (change / "proposal.md").write_text("# p\n", encoding="utf-8")
    (change / "design.md").write_text(design, encoding="utf-8")
    (change / "tasks.md").write_text("# t\n", encoding="utf-8")
    spec = change / "specs" / "x"
    spec.mkdir(parents=True)
    (spec / "spec.md").write_text("# s\n", encoding="utf-8")
    return change


def submit(change: Path):
    mover = FakeMover()
    out = process_event("submeter_design", status="Design", q_git="card-1103-tokens", bound_card="1103", change_dir=change, mover=mover, dry_run=True)
    return out, mover


NO_SCREEN = "UI impact: none\nlive_route: N/A — harness de processo; sem tela\nsurface: none\n\nbody\n"


@pytest.mark.parametrize("missing,design", [
    ("live_route", "UI impact: none\nsurface: none\n\nbody\n"),
    ("UI impact", "live_route: N/A — harness\nsurface: none\n\nbody\n"),
    ("surface", "UI impact: none\nlive_route: N/A — harness\n\nbody\n"),
    ("UI impact", "# Design\n\nsome text without tokens\n"),
])
def test_t5_is_refused_naming_the_missing_gate_token(tmp_path, missing, design):
    out, mover = submit(design_change(tmp_path, design))
    assert out["result"] == "reject" and out["reason"] == "guard:design_tokens" and f"`{missing}`" in out["message"]
    assert out["state"] == "Design" and mover.calls == []


def test_t5_passes_the_token_check_for_a_no_screen_design_and_a_precommit_agrees(tmp_path):
    from design_clone_gate import design_token_gap
    from review_process_checklist import _check_design_tokens

    change = design_change(tmp_path, NO_SCREEN)
    out, _ = submit(change)
    assert out["result"] == "transition" and out["to"] == "Aprovação de Design"
    assert design_token_gap(NO_SCREEN) is None and _check_design_tokens(change) is None
    broken = design_change(tmp_path / "other", "UI impact: none\nsurface: none\n")
    assert design_token_gap((broken / "design.md").read_text()) == "live_route" and _check_design_tokens(broken) == "design.md tokens"


# --- R21: the nucleus installer in the consumer's review diff -----------------------------------------------------------------------------


def nucleus_with_two_tags(tmp_path: Path) -> Path:
    nucleus = init_git(tmp_path / "covenant-flow", "main")
    write(nucleus / "install.sh", "#!/usr/bin/env bash\necho v1\n")
    for args in (["add", "install.sh"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "v1"], ["tag", "v1.0.0"]):
        subprocess.run(["git", "-C", str(nucleus), *args], check=True, capture_output=True)
    write(nucleus / "install.sh", "#!/usr/bin/env bash\necho v2 --account --remove\n")
    for args in (["add", "install.sh"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "v2"]):
        subprocess.run(["git", "-C", str(nucleus), *args], check=True, capture_output=True)
    return nucleus


def test_the_review_diff_carries_the_nucleus_installer_diff_since_the_pinned_tag(tmp_path):
    nucleus = nucleus_with_two_tags(tmp_path)
    consumer = make_consumer(tmp_path / "consumer", pin="v1.0.0")
    subprocess.run(["git", "-C", str(consumer), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(consumer), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "pinned"], check=True, capture_output=True)
    write(consumer / "backend" / "x.py", "x = 1\n")
    plain = materialize(consumer, "pre-commit", "develop")
    assert "backend/x.py" in plain and "install.sh" not in plain
    joined = materialize(consumer, "pre-commit", "develop", nucleus=nucleus)  # base = the pin of the reviewed HEAD (v1.0.0)
    assert "backend/x.py" in joined
    assert "diff --git a/covenant-flow/install.sh b/covenant-flow/install.sh" in joined and "-echo v1" in joined and "+echo v2 --account --remove" in joined
    explicit = materialize(consumer, "pre-commit", "develop", nucleus=nucleus, nucleus_base="HEAD")
    assert "install.sh" not in explicit  # nothing changed since HEAD of the nucleus


def test_the_review_diff_command_line_writes_the_joined_patch_and_fails_visibly_without_a_base(tmp_path, capsys):
    from materialize_review_diff import main

    nucleus = nucleus_with_two_tags(tmp_path)
    consumer = make_consumer(tmp_path / "consumer", pin="v1.0.0")
    subprocess.run(["git", "-C", str(consumer), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(consumer), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", "pinned"], check=True, capture_output=True)
    assert main(["--root", str(consumer), "--nucleus", str(nucleus), "--out", ".cursor/tmp/review-diff.patch"]) == 0
    assert "covenant-flow/install.sh" in (consumer / ".cursor/tmp/review-diff.patch").read_text()
    assert main(["--root", str(consumer), "--nucleus", str(nucleus), "--nucleus-base", "v9.9.9", "--out", ".cursor/tmp/x.patch"]) == 2
    assert "cannot diff the nucleus install.sh" in capsys.readouterr().err
