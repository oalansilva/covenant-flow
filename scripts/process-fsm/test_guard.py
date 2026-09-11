from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from fsm import load_fsm  # noqa: E402
from guard import decide, emit, extract_path, extract_paths, normalize  # noqa: E402
from resolve import UNBOUND  # noqa: E402
from test_overlay_fixtures import FIELD_ID, filled_overlay_dict, write_overlay  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

DENY_STATES = (
    "Todo",
    "Design",
    "Aprovação de Design",
    "Pronto para Dev",
    "QA",
    "Done",
    "Homologado",
    "Pronto",
    "Cancelado",
)
ALLOW_STATES = ("Em desenvolvimento", "Code Review")
SILENT = lambda bound: (_ for _ in ()).throw(
    AssertionError(f"github called bound={bound}")
)  # noqa: E731


def _no_github(_bound: str | None) -> str | None:
    return None


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(path: Path, branch: str, filename: str) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "-b", branch, str(path)], check=True, capture_output=True, text=True
    )
    _run_git(path, "config", "user.email", "process-fsm@test.local")
    _run_git(path, "config", "user.name", "process-fsm")
    tracked = path / filename
    tracked.parent.mkdir(parents=True, exist_ok=True)
    tracked.write_text("fixture\n", encoding="utf-8")
    _run_git(path, "add", filename)
    _run_git(path, "commit", "-m", "init")
    write_overlay(path)
    return tracked


def _write_payload(cwd: Path, rel: str, status: str | None = None, tool: str = "Write") -> dict:
    tool_input = {"target_notebook": rel} if tool == "EditNotebook" else {"path": rel}
    payload: dict = {"tool_name": tool, "tool_input": tool_input, "cwd": str(cwd)}
    if status is not None:
        payload["status"] = status
    return payload


def _shell_payload(cwd: Path, command: str, status: str | None = None) -> dict:
    payload: dict = {"command": command, "cwd": str(cwd)}
    if status is not None:
        payload["status"] = status
    return payload


def test_extract_path_from_cursor_envelope():
    assert (
        extract_path({"tool_name": "Write", "tool_input": {"path": "backend/a.py"}})
        == "backend/a.py"
    )
    assert (
        extract_path({"tool_name": "StrReplace", "tool_input": {"file_path": "backend/a.py"}})
        == "backend/a.py"
    )
    assert extract_path(
        {"tool_name": "EditNotebook", "tool_input": {"target_notebook": "backend/n.ipynb"}}
    ) == ("backend/n.ipynb")
    assert (
        extract_path({"command": "cat >backend/app/main.py", "cwd": "/"}) == "backend/app/main.py"
    )
    # Card #625: tee under /tmp outside the worktree is an allowlisted sink.
    assert (
        extract_path({"command": "tee /tmp/repo/backend/app/main.py", "cwd": "/home/user/card"})
        is None
    )
    assert extract_path({"command": "pytest backend/ -q", "cwd": "/"}) is None


def test_shell_null_redirect_with_product_cite_allowed(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-625-guard-null-redirect", "backend/app/main.py")
    payload = _shell_payload(
        repo,
        "ls backend/app/main.py >/dev/null 2>/dev/null",
        status="Todo",
    )
    assert decide(payload, status_provider=SILENT)["permission"] == "allow"


def test_shell_tmp_redirect_with_product_cite_allowed(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-625-guard-null-redirect", "backend/app/main.py")
    payload = _shell_payload(
        repo,
        "cat backend/app/main.py > /tmp/cf-625-out.txt",
        status="Todo",
    )
    assert decide(payload, status_provider=SILENT)["permission"] == "allow"


def test_shell_fd_redirect_with_product_cite_allowed(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-625-guard-null-redirect", "backend/app/main.py")
    payload = _shell_payload(
        repo,
        "/tmp/pyvenv-cf/bin/python -m pytest backend/tests -q 2>&1",
        status="Todo",
    )
    assert decide(payload, status_provider=SILENT)["permission"] == "allow"


@pytest.mark.parametrize("state", DENY_STATES)
def test_product_write_denied_in_column(tmp_path: Path, state: str):
    repo = tmp_path / "card"
    _init_repo(repo, "card-611-process-fsm-guard", "backend/app/main.py")
    payload = _write_payload(repo, "backend/app/main.py", status=state)
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"
    assert "reason=" in result["agent_message"]
    if state == "Pronto para Dev":
        assert "I3" in result["agent_message"]


@pytest.mark.parametrize("state", ALLOW_STATES)
@pytest.mark.parametrize("tool", ["Write", "StrReplace", "Delete", "EditNotebook"])
def test_product_write_allowed_under_i1(tmp_path: Path, state: str, tool: str):
    repo = tmp_path / "card"
    rel = "backend/app/main.py" if tool != "EditNotebook" else "backend/notebook.ipynb"
    _init_repo(repo, "card-611-process-fsm-guard", rel)
    payload = _write_payload(repo, rel, status=state, tool=tool)
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "allow"


def test_injected_status_does_not_call_provider(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-611-process-fsm-guard", "backend/app/main.py")
    payload = _write_payload(repo, "backend/app/main.py", status="Em desenvolvimento")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "allow"


def test_develop_write_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    payload = _write_payload(repo, "backend/app/main.py", status="Em desenvolvimento")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"
    assert "develop-write" in result["agent_message"] or "I1" in result["agent_message"]


def test_main_write_denied(tmp_path: Path):
    repo = tmp_path / "main"
    _init_repo(repo, "main", "backend/app/main.py")
    payload = _write_payload(repo, "backend/app/main.py", status="Em desenvolvimento")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"


def test_unbound_write_denied(tmp_path: Path):
    repo = tmp_path / "change"
    _init_repo(repo, "change-608-process-fsm", "backend/app/main.py")
    payload = _write_payload(repo, "backend/app/main.py", status="Em desenvolvimento")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"
    assert "unbound" in result["agent_message"] or "unbound-write" in result["agent_message"]


def test_bound_mismatch_denied(tmp_path: Path):
    cwd_repo = tmp_path / "card-605"
    path_repo = tmp_path / "card-611"
    _init_repo(cwd_repo, "card-605-other", "tracked.txt")
    tracked = _init_repo(path_repo, "card-611-process-fsm-guard", "backend/app/main.py")
    payload = {
        "tool_name": "Write",
        "tool_input": {"path": str(tracked)},
        "cwd": str(cwd_repo),
        "status": "Em desenvolvimento",
    }
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"


def test_replay_b6a71170(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/tasks/discovery_tasks.py")
    payload = _write_payload(repo, "backend/app/tasks/discovery_tasks.py", status="Todo")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"


def test_design_openspec_write_skips_evaluate(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-611-process-fsm-guard", "openspec/changes/card-611-x/proposal.md")
    calls: list = []

    def wrapped(fsm, ctx):
        calls.append(ctx)
        raise AssertionError("evaluate must not run for design_globs")

    payload = _write_payload(repo, "openspec/changes/card-611-x/proposal.md", status="Design")
    result = decide(payload, status_provider=SILENT, evaluate_fn=wrapped)
    assert result["permission"] == "allow"
    assert calls == []


def test_prototype_write_allowed_in_design(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-611-process-fsm-guard", "frontend/public/prototypes/x/index.html")
    payload = _write_payload(repo, "frontend/public/prototypes/x/index.html", status="Design")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "allow"


def test_fail_closed_product_denied(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-611-process-fsm-guard", "backend/app/main.py")
    payload = _write_payload(repo, "backend/app/main.py")
    result = decide(payload, status_provider=_no_github)
    assert result["permission"] == "deny"
    assert "fail_closed" in result["agent_message"]


def test_fail_closed_design_allowed_on_card_branch(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-611-process-fsm-guard", "openspec/changes/card-611-x/design.md")
    payload = _write_payload(repo, "openspec/changes/card-611-x/design.md")
    result = decide(payload, status_provider=_no_github)
    assert result["permission"] == "allow"


def test_shell_redirect_denied(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-611-process-fsm-guard", "backend/app/main.py")
    payload = _shell_payload(repo, "cat extra >> backend/app/main.py", status="Todo")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"


def test_shell_tee_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    payload = _shell_payload(repo, "echo x | tee backend/app/main.py", status="Em desenvolvimento")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"


def test_write_into_missing_product_dir_still_binds(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-611-process-fsm-guard", "backend/app/main.py")
    payload = _write_payload(repo, "backend/newpkg/mod.py", status="Em desenvolvimento")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "allow"


def test_shell_absolute_and_glued_redirect_denied(tmp_path: Path):
    repo = tmp_path / "card"
    tracked = _init_repo(repo, "card-611-process-fsm-guard", "backend/app/main.py")
    abs_path = str(tracked)
    glued = _shell_payload(repo, "cat >backend/app/main.py", status="Todo")
    absolute = _shell_payload(repo, f"tee {abs_path}", status="Todo")
    assert decide(glued, status_provider=SILENT)["permission"] == "deny"
    assert decide(absolute, status_provider=SILENT)["permission"] == "deny"


def test_pytest_backend_allowed(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-611-process-fsm-guard", "backend/app/main.py")
    payload = _shell_payload(repo, "pytest backend/ -q", status="Todo")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "allow"


def test_git_commit_not_gated(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-611-process-fsm-guard", "backend/app/main.py")
    payload = _shell_payload(repo, "git commit -m 'feat: backend'", status="Todo")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "allow"


def test_hooks_json_composes_impeccable():
    hooks = json.loads((REPO / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    pre = hooks["hooks"]["preToolUse"]
    assert pre[0]["command"] == ".cursor/hooks/process-fsm-guard.sh"
    assert pre[0]["failClosed"] is True
    assert "Write" in pre[0]["matcher"]
    shell = hooks["hooks"]["beforeShellExecution"]
    assert shell[0]["command"] == ".cursor/hooks/process-fsm-guard.sh"
    assert shell[0].get("failClosed") is not True
    after = hooks["hooks"]["afterFileEdit"][0]["command"]
    stop = hooks["hooks"]["stop"][0]["command"]
    assert ".cursor/hooks/impeccable.sh" in after and "afterFileEdit" in after
    assert ".cursor/hooks/impeccable.sh" in stop and " stop" in f" {stop}"
    for command in (after, stop):
        assert "test -f .cursor/hooks/impeccable.sh" in command
        assert "./hooks/impeccable.sh" in command
        assert "./impeccable.sh" in command
        assert "git rev-parse --show-toplevel" in command
        assert "exit 127" in command
    assert (REPO / ".cursor" / "hooks" / "impeccable.sh").is_file()
    destape = hooks["hooks"]["subagentStop"]
    assert destape[0]["command"] == ".cursor/hooks/process-fsm-subagent-stop.sh"
    matcher = destape[0]["matcher"]
    assert "generalPurpose" in matcher
    assert "diff-reviewer" in matcher
    assert "code-reviewer" in matcher
    assert destape[0]["loop_limit"] == 32
    assert destape[0].get("failClosed") is not True
    assert "subagentStart" not in hooks["hooks"]


def test_fsm_still_loads():
    validate = load_fsm()
    assert validate["fail_closed_asymmetric"] is True


def test_git_cite_sidecar_allowed(tmp_path: Path):
    """Card #631: git add/commit/status that only cite the sidecar must not sidecar-deny."""
    repo = tmp_path / "card"
    _init_repo(repo, "card-631-guard-sidecar-git-cite", "backend/app/main.py")
    digest = "openspec/changes/card-631-guard-sidecar-git-cite/" + ".design" + "-digest"
    for command in (
        f"git add {digest}",
        f"git commit -m 'chore: archive {digest}'",
        f"git status -- {digest}",
        f"git reset HEAD -- {digest}",
    ):
        payload = _shell_payload(repo, command, status="Design")
        result = decide(payload, status_provider=SILENT)
        assert result["permission"] == "allow", command


def test_shell_redirect_sidecar_denied(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-631-guard-sidecar-git-cite", "backend/app/main.py")
    digest = "openspec/changes/card-631-x/" + ".design" + "-digest"
    payload = _shell_payload(repo, f"echo x > {digest}", status="Design")
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"
    assert "sidecar" in result["agent_message"]


def _assert_dual_deny(result: dict) -> None:
    assert result["permission"] == "deny"
    assert result["decision"] == "deny"
    assert result.get("agent_message")
    assert result.get("reason")


def _assert_dual_allow(result: dict) -> None:
    assert result["permission"] == "allow"
    assert result["decision"] == "allow"


def test_normalize_grok_and_cursor_keys():
    grok = normalize(
        {
            "toolName": "write",
            "toolInput": {"file_path": "backend/a.py"},
            "workspaceRoot": "/tmp/ws",
        }
    )
    assert grok["tool_name"] == "write"
    assert grok["tool_input"]["file_path"] == "backend/a.py"
    assert grok["cwd"] == "/tmp/ws"
    cursor = normalize({"tool_name": "Write", "tool_input": {"path": "backend/a.py"}, "cwd": "/x"})
    assert cursor["tool_name"] == "Write"
    assert extract_path({"toolName": "search_replace", "toolInput": {"file_path": "backend/a.py"}}) == (
        "backend/a.py"
    )
    assert extract_path({"toolName": "write", "toolInput": {"target_file": "backend/a.py"}}) == (
        "backend/a.py"
    )


def test_emit_dual_keys():
    denied = emit("deny", "nope")
    _assert_dual_deny(denied)
    allowed = emit("allow")
    _assert_dual_allow(allowed)


def test_grok_write_product_on_develop_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    for tool in ("write", "search_replace"):
        payload = {
            "toolName": tool,
            "toolInput": {"file_path": "backend/app/main.py"},
            "cwd": str(repo),
            "status": "Todo",
        }
        result = decide(payload, status_provider=SILENT)
        _assert_dual_deny(result)


def test_grok_tee_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    payload = {
        "toolName": "run_terminal_command",
        "toolInput": {"command": "echo x | tee backend/app/main.py"},
        "cwd": str(repo),
        "status": "Em desenvolvimento",
    }
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)


def test_grok_openspec_write_allowed_in_design(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-668-multi-harness-adapters", "openspec/changes/card-668-x/proposal.md")
    calls: list = []

    def wrapped(fsm, ctx):
        calls.append(ctx)
        raise AssertionError("evaluate must not run for design_globs")

    payload = {
        "toolName": "search_replace",
        "toolInput": {"file_path": "openspec/changes/card-668-x/proposal.md"},
        "cwd": str(repo),
        "status": "Design",
    }
    result = decide(payload, status_provider=SILENT, evaluate_fn=wrapped)
    _assert_dual_allow(result)
    assert calls == []


def test_grok_status_item_edit_denied(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-668-multi-harness-adapters", "backend/app/main.py")
    payload = {
        "toolName": "run_terminal_command",
        "toolInput": {
            "command": f"gh project item-edit --field-id {FIELD_ID} --id x",
        },
        "cwd": str(repo),
        "status": "Design",
    }
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)
    assert "process_event" in result["reason"]


def test_bash_fallback_parses_grok_write(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    hooks = repo / ".cursor" / "hooks"
    hooks.mkdir(parents=True)
    src = (REPO / ".cursor" / "hooks" / "process-fsm-guard.sh").read_text(encoding="utf-8")
    script = hooks / "process-fsm-guard.sh"
    script.write_text(src, encoding="utf-8")
    script.chmod(0o755)
    payload = {
        "toolName": "write",
        "toolInput": {"file_path": "backend/app/main.py"},
        "cwd": str(repo),
        "status": "Todo",
    }
    proc = subprocess.run(
        [str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    _assert_dual_deny(data)


def test_grok_hooks_json_registers_guard():
    hooks = json.loads((REPO / ".grok" / "hooks" / "process-fsm.json").read_text(encoding="utf-8"))
    pre = hooks["hooks"]["PreToolUse"]
    matchers = " ".join(item.get("matcher") or "" for item in pre)
    assert "write" in matchers and "search_replace" in matchers
    assert "Write" in matchers and "Edit" in matchers
    assert "run_terminal_command" in matchers and "run_terminal_cmd" in matchers
    raw = (REPO / ".grok" / "hooks" / "process-fsm.json").read_text(encoding="utf-8")
    assert "| T0" not in raw
    assert "T0–T17" not in raw and "T0-T17" not in raw
    for item in pre:
        handler = item["hooks"][0]
        assert handler["timeout"] >= 30
        assert ".grok/hooks/process-fsm-guard.sh" in handler["command"]
        assert "test -f .grok/hooks/process-fsm-guard.sh" in handler["command"]
        assert "./process-fsm-guard.sh" in handler["command"]
        assert "git rev-parse --show-toplevel" in handler["command"]
        assert "exit 127" in handler["command"]
    start = hooks["hooks"]["SessionStart"][0]["hooks"][0]
    assert "process-fsm-session-start.sh" in start["command"]
    assert "test -f .grok/hooks/process-fsm-session-start.sh" in start["command"]
    assert "./process-fsm-session-start.sh" in start["command"]
    assert "git rev-parse --show-toplevel" in start["command"]
    post = hooks["hooks"]["PostToolUse"][0]["hooks"][0]
    assert ".grok/hooks/impeccable.sh" in post["command"]
    assert "PostToolUse" in post["command"]
    assert "test -f .grok/hooks/impeccable.sh" in post["command"]
    assert "./impeccable.sh" in post["command"]
    assert "git rev-parse --show-toplevel" in post["command"]
    assert post["timeout"] >= 30
    stop = hooks["hooks"]["Stop"][0]["hooks"][0]
    assert ".grok/hooks/impeccable.sh" in stop["command"]
    assert "Stop" in stop["command"]
    assert "test -f .grok/hooks/impeccable.sh" in stop["command"]
    assert "./impeccable.sh" in stop["command"]
    assert "git rev-parse --show-toplevel" in stop["command"]
    assert stop["timeout"] >= 30
    assert (REPO / ".grok" / "hooks" / "impeccable.sh").is_file()


def _sh_hook(command: str, cwd: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["sh", "-c", command],
        cwd=str(cwd),
        input=b"{}",
        capture_output=True,
        timeout=30,
        check=False,
    )


def test_grok_impeccable_command_resolves_from_workspace_and_hooks_dir():
    hooks = json.loads((REPO / ".grok" / "hooks" / "process-fsm.json").read_text(encoding="utf-8"))
    commands = [
        hooks["hooks"]["PostToolUse"][0]["hooks"][0]["command"],
        hooks["hooks"]["Stop"][0]["hooks"][0]["command"],
        hooks["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
        hooks["hooks"]["PreToolUse"][1]["hooks"][0]["command"],
        hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"],
    ]
    cwds = [
        path
        for path in (REPO, REPO / ".grok" / "hooks", REPO / "frontend")
        if path.is_dir()
    ]
    for command in commands:
        for cwd in cwds:
            proc = _sh_hook(command, cwd)
            assert proc.returncode == 0, (cwd, command[:120], proc.stderr)


def test_cursor_impeccable_command_resolves_from_workspace_and_cursor_dir():
    hooks = json.loads((REPO / ".cursor" / "hooks.json").read_text(encoding="utf-8"))
    commands = [
        hooks["hooks"]["afterFileEdit"][0]["command"],
        hooks["hooks"]["stop"][0]["command"],
    ]
    cwds = [REPO, REPO / ".cursor", REPO / ".cursor" / "hooks"]
    for command in commands:
        for cwd in cwds:
            proc = _sh_hook(command, cwd)
            assert proc.returncode == 0, (cwd, command[:120], proc.stderr)


def test_impeccable_wrappers_stay_fail_open():
    grok = (REPO / ".grok" / "hooks" / "impeccable.sh").read_text(encoding="utf-8")
    cursor = (REPO / ".cursor" / "hooks" / "impeccable.sh").read_text(encoding="utf-8")
    for text in (grok, cursor):
        assert "sys.exit(0)" in text
        assert "except Exception" in text
    dsh = (REPO / ".dsh" / "plugin" / "impeccable-hook.js").read_text(encoding="utf-8")
    oc = (REPO / ".opencode" / "plugin" / "impeccable-hook.js").read_text(encoding="utf-8")
    assert "return next()" in dsh
    assert "fail-open" in dsh
    assert "never throw" in oc
    assert "kind: 'block'" not in dsh and 'kind: "block"' not in dsh


def _oc_payload(cwd: Path, tool: str, args: dict, status: str | None = None) -> dict:
    payload: dict = {"tool": tool, "args": args, "cwd": str(cwd)}
    if status is not None:
        payload["status"] = status
    return payload


def test_g1_opencode_edit_product_on_develop_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/tasks/discovery_tasks.py")
    payload = _oc_payload(
        repo,
        "edit",
        {"filePath": "backend/app/tasks/discovery_tasks.py"},
        status="Em desenvolvimento",
    )
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)


def test_g2_opencode_write_frontend_on_develop_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "frontend/src/x.tsx")
    payload = _oc_payload(repo, "write", {"filePath": "frontend/src/x.tsx"}, status="Todo")
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)


def test_g3_apply_patch_update_file_extract_paths_and_deny(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    payload = _oc_payload(
        repo,
        "apply_patch",
        {"patchText": "*** Begin Patch\n*** Update File: backend/app/main.py\n*** End Patch"},
        status="Todo",
    )
    assert extract_paths(payload) == ["backend/app/main.py"]
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)
    assert "empty_path" not in result["reason"]


def test_g4_apply_patch_empty_patchtext_denied():
    payload = {"tool": "apply_patch", "args": {"patchText": ""}, "cwd": "/"}
    assert extract_paths(payload) == []
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)
    assert "empty_path" in result["reason"]


def test_g5_apply_patch_unparseable_patchtext_denied():
    payload = {
        "tool": "apply_patch",
        "args": {"patchText": "*** Begin Patch\n*** End Patch"},
        "cwd": "/",
    }
    assert extract_paths(payload) == []
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)
    assert "empty_path" in result["reason"]


def test_g6_edit_empty_filepath_denied():
    payload = {"tool": "edit", "args": {"filePath": ""}, "cwd": "/"}
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)
    assert "empty_path" in result["reason"]


def test_g7_opencode_bash_tee_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    payload = _oc_payload(
        repo,
        "bash",
        {"command": "echo x | tee backend/app/main.py"},
        status="Em desenvolvimento",
    )
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)


def test_g8_opencode_bash_status_item_edit_denied(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-720-opencode-three-adapters", "backend/app/main.py")
    command = (
        "gh project item-edit --id X "
        f"--field-id {FIELD_ID} --single-select-option-id bd47fbe8"
    )
    payload = _oc_payload(repo, "bash", {"command": command}, status="Design")
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)
    assert "process_event" in result["reason"]


def test_g9_opencode_edit_openspec_design_allowed(tmp_path: Path):
    repo = tmp_path / "card"
    rel = "openspec/changes/card-720-opencode-three-adapters/design.md"
    _init_repo(repo, "card-720-opencode-three-adapters", rel)
    calls: list = []

    def wrapped(fsm, ctx):
        calls.append(ctx)
        raise AssertionError("evaluate must not run for design_globs")

    payload = _oc_payload(repo, "edit", {"filePath": rel}, status="Design")
    result = decide(payload, status_provider=SILENT, evaluate_fn=wrapped)
    _assert_dual_allow(result)
    assert calls == []


def test_g10_unknown_opencode_tool_allowed():
    result = decide({"tool": "grep", "args": {}, "cwd": "/"}, status_provider=SILENT)
    _assert_dual_allow(result)


def test_g11_three_dialects_same_deny(tmp_path: Path):
    repo = tmp_path / "develop"
    rel = "backend/app/tasks/discovery_tasks.py"
    _init_repo(repo, "develop", rel)
    envelopes = [
        {"tool_name": "Write", "tool_input": {"path": rel}, "cwd": str(repo), "status": "Todo"},
        {"toolName": "write", "toolInput": {"file_path": rel}, "cwd": str(repo), "status": "Todo"},
        {"tool": "edit", "args": {"filePath": rel}, "cwd": str(repo), "status": "Todo"},
    ]
    results = [decide(item, status_provider=SILENT) for item in envelopes]
    for item in results:
        _assert_dual_deny(item)
    assert {item["permission"] for item in results} == {"deny"}
    assert {item["decision"] for item in results} == {"deny"}


def test_g12_bash_fallback_parses_opencode_edit(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "backend/app/main.py")
    hooks = repo / ".cursor" / "hooks"
    hooks.mkdir(parents=True)
    src = (REPO / ".cursor" / "hooks" / "process-fsm-guard.sh").read_text(encoding="utf-8")
    script = hooks / "process-fsm-guard.sh"
    script.write_text(src, encoding="utf-8")
    script.chmod(0o755)
    payload = {
        "tool": "edit",
        "args": {"filePath": "backend/app/main.py"},
        "cwd": str(repo),
        "status": "Todo",
    }
    proc = subprocess.run(
        [str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    _assert_dual_deny(data)


def test_g17_apply_patch_add_file_openspec_allowed(tmp_path: Path):
    repo = tmp_path / "card"
    rel = "openspec/changes/card-720-opencode-three-adapters/design.md"
    _init_repo(repo, "card-720-opencode-three-adapters", rel)
    calls: list = []

    def wrapped(fsm, ctx):
        calls.append(ctx)
        raise AssertionError("evaluate must not run for design_globs")

    payload = _oc_payload(
        repo,
        "apply_patch",
        {"patchText": f"*** Begin Patch\n*** Add File: {rel}\n*** End Patch"},
        status="Design",
    )
    assert extract_paths(payload) == [rel]
    result = decide(payload, status_provider=SILENT, evaluate_fn=wrapped)
    _assert_dual_allow(result)
    assert calls == []


def test_g18_apply_patch_move_to_product_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", "docs/note.md")
    payload = _oc_payload(
        repo,
        "apply_patch",
        {
            "patchText": (
                "*** Begin Patch\n*** Update File: docs/note.md\n"
                "*** Move to: backend/app/moved.py\n*** End Patch"
            )
        },
        status="Todo",
    )
    paths = extract_paths(payload)
    assert "backend/app/moved.py" in paths
    assert "docs/note.md" in paths
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)


def test_normalize_opencode_native_keys():
    native = normalize(
        {
            "tool": "edit",
            "args": {"filePath": "backend/a.py"},
            "directory": "/tmp/ws",
        }
    )
    assert native["tool_name"] == "edit"
    assert native["tool_input"]["filePath"] == "backend/a.py"
    assert native["cwd"] == "/tmp/ws"
    assert extract_path({"tool": "write", "args": {"filePath": "backend/a.py"}}) == "backend/a.py"


def _canonical_overlay() -> dict:
    return filled_overlay_dict()


def test_checkout_b_card_on_canonical_denied():
    overlay = _canonical_overlay()
    source = overlay["environments"]["dev"]["source"]
    result = decide(
        {"command": "git checkout -b card-801-t14-qa-closeout", "cwd": source},
        overlay=overlay,
        status_provider=SILENT,
    )
    _assert_dual_deny(result)
    assert "canonical_card_branch" in result["agent_message"]


def test_switch_c_card_on_canonical_denied():
    overlay = _canonical_overlay()
    source = overlay["environments"]["dev"]["source"]
    result = decide(
        {"command": "git switch -c card-792-x", "cwd": source},
        overlay=overlay,
        status_provider=SILENT,
    )
    _assert_dual_deny(result)
    assert "canonical_card_branch" in result["agent_message"]


def test_checkout_track_b_card_on_canonical_denied():
    overlay = _canonical_overlay()
    source = overlay["environments"]["dev"]["source"]
    result = decide(
        {"command": "git checkout --track -b card-801-x", "cwd": source},
        overlay=overlay,
        status_provider=SILENT,
    )
    _assert_dual_deny(result)
    assert "canonical_card_branch" in result["agent_message"]


def test_git_c_canonical_from_other_cwd_denied():
    """Assessment B: git -C <canonical> checkout -b card-* from another cwd MUST deny."""
    overlay = _canonical_overlay()
    source = overlay["environments"]["dev"]["source"]
    result = decide(
        {
            "command": f"git -C {source} checkout -b card-801-t14-qa-closeout",
            "cwd": "/tmp/card-801-worktree",
        },
        overlay=overlay,
        status_provider=SILENT,
    )
    _assert_dual_deny(result)
    assert "canonical_card_branch" in result["agent_message"]


def test_checkout_b_card_in_worktree_allowed():
    overlay = _canonical_overlay()
    result = decide(
        {
            "command": "git checkout -b card-801-t14-qa-closeout",
            "cwd": "/tmp/card-801-worktree",
        },
        overlay=overlay,
        status_provider=SILENT,
    )
    _assert_dual_allow(result)


def test_git_c_worktree_from_canonical_cwd_allowed():
    overlay = _canonical_overlay()
    source = overlay["environments"]["dev"]["source"]
    result = decide(
        {
            "command": "git -C /tmp/card-801-worktree checkout -b card-801-t14-qa-closeout",
            "cwd": source,
        },
        overlay=overlay,
        status_provider=SILENT,
    )
    _assert_dual_allow(result)


def test_checkout_existing_branch_on_canonical_allowed():
    overlay = _canonical_overlay()
    source = overlay["environments"]["dev"]["source"]
    result = decide(
        {"command": "git checkout develop", "cwd": source},
        overlay=overlay,
        status_provider=SILENT,
    )
    _assert_dual_allow(result)


def test_worktree_add_on_canonical_allowed():
    overlay = _canonical_overlay()
    source = overlay["environments"]["dev"]["source"]
    result = decide(
        {"command": "git worktree add /tmp/wt card-801-x", "cwd": source},
        overlay=overlay,
        status_provider=SILENT,
    )
    _assert_dual_allow(result)


def test_decide_does_not_deny_qa_task_spawn():
    result = decide(
        {"tool": "Task", "args": {"prompt": "QA child read checks; T14 integrar_develop"}},
        status_provider=SILENT,
        overlay=_canonical_overlay(),
    )
    _assert_dual_allow(result)
    result2 = decide(
        {"tool": "task", "args": {"prompt": "QA T14"}},
        status_provider=SILENT,
        overlay=_canonical_overlay(),
    )
    _assert_dual_allow(result2)


def _run_guard_fallback(repo: Path, payload: dict) -> dict:
    hooks = repo / ".cursor" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    src = (REPO / ".cursor" / "hooks" / "process-fsm-guard.sh").read_text(encoding="utf-8")
    script = hooks / "process-fsm-guard.sh"
    script.write_text(src, encoding="utf-8")
    script.chmod(0o755)
    proc = subprocess.run(
        [str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(repo),
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_bash_fallback_denies_canonical_card_branch(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-801-t14-qa-closeout", "backend/app/main.py")
    overlay = filled_overlay_dict()
    source = overlay["environments"]["dev"]["source"]
    data = _run_guard_fallback(
        repo,
        {"command": "git checkout -b card-801-t14-qa-closeout", "cwd": source},
    )
    _assert_dual_deny(data)
    assert "canonical_card_branch" in data["agent_message"]


def test_bash_fallback_denies_git_c_canonical_from_other_cwd(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-801-t14-qa-closeout", "backend/app/main.py")
    overlay = filled_overlay_dict()
    source = overlay["environments"]["dev"]["source"]
    data = _run_guard_fallback(
        repo,
        {
            "command": f"git -C {source} checkout -b card-801-t14-qa-closeout",
            "cwd": str(repo),
        },
    )
    _assert_dual_deny(data)
    assert "canonical_card_branch" in data["agent_message"]


def test_bash_fallback_allows_checkout_b_in_worktree(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-801-t14-qa-closeout", "backend/app/main.py")
    data = _run_guard_fallback(
        repo,
        {"command": "git checkout -b card-801-t14-qa-closeout", "cwd": str(repo)},
    )
    _assert_dual_allow(data)


def test_bash_fallback_allows_existing_checkout_on_canonical(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-801-t14-qa-closeout", "backend/app/main.py")
    overlay = filled_overlay_dict()
    source = overlay["environments"]["dev"]["source"]
    data = _run_guard_fallback(
        repo,
        {"command": "git checkout develop", "cwd": source},
    )
    _assert_dual_allow(data)


G1_INCLUDE = """HTTP/2 200
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 2026-09-03T02:55:52Z
X-RateLimit-Resource: graphql

{"data":null,"errors":[{"type":"RATE_LIMIT","message":"API rate limit exceeded"}]}
"""


def test_g5_github_status_provider_rate_limit_is_not_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from graphql_quota import GraphQLQuotaError
    from guard import github_status_provider

    cache = tmp_path / "quota.json"
    monkeypatch.setenv("PROCESS_FSM_GRAPHQL_QUOTA_CACHE", str(cache))
    monkeypatch.setattr("guard.try_load_overlay", lambda *a, **k: {"ok": True})
    monkeypatch.setattr("guard.repo_owner_name", lambda o: ("oalansilva", "crypto"))
    monkeypatch.setattr("guard.board_owner_number", lambda o: ("oalansilva", 1))
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, stdout=G1_INCLUDE, stderr="")

    monkeypatch.setattr("guard.subprocess.run", fake_run)
    with pytest.raises(GraphQLQuotaError) as excinfo:
        github_status_provider("820")
    assert excinfo.value.remaining == 0
    assert excinfo.value.reset_at == "2026-09-03T02:55:52Z"
    assert calls
    assert "item-list" not in " ".join(calls[0])
    assert "graphql" in calls[0]
    assert "--include" in calls[0]

    calls.clear()

    def fake_run_nonzero(argv, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 1, stdout=G1_INCLUDE, stderr="graphql error")

    monkeypatch.setattr("guard.subprocess.run", fake_run_nonzero)
    with pytest.raises(GraphQLQuotaError) as excinfo:
        github_status_provider("820")
    assert excinfo.value.remaining == 0


def test_g9_g10_status_provider_cache_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from graphql_quota import GraphQLQuotaError, parse_include_output, write_cache
    from guard import github_status_provider

    cache = tmp_path / "quota.json"
    monkeypatch.setenv("PROCESS_FSM_GRAPHQL_QUOTA_CACHE", str(cache))
    write_cache(parse_include_output(G1_INCLUDE))
    monkeypatch.setenv("PROCESS_FSM_GRAPHQL_QUOTA_NOW", "2026-09-03T01:00:00Z")

    def boom(*a, **k):
        raise AssertionError("graphql called")

    monkeypatch.setattr("guard.subprocess.run", boom)
    with pytest.raises(GraphQLQuotaError):
        github_status_provider("820")

    monkeypatch.setenv("PROCESS_FSM_GRAPHQL_QUOTA_NOW", "2026-09-03T03:00:00Z")
    monkeypatch.setattr("guard.try_load_overlay", lambda *a, **k: {"ok": True})
    monkeypatch.setattr("guard.repo_owner_name", lambda o: ("oalansilva", "crypto"))
    monkeypatch.setattr("guard.board_owner_number", lambda o: ("oalansilva", 1))
    called: list[int] = []

    def once(argv, **kwargs):
        called.append(1)
        return subprocess.CompletedProcess(argv, 0, stdout=G1_INCLUDE, stderr="")

    monkeypatch.setattr("guard.subprocess.run", once)
    with pytest.raises(GraphQLQuotaError):
        github_status_provider("820")
    assert called == [1]


def test_decide_quota_error_includes_reset(tmp_path: Path) -> None:
    from graphql_quota import GraphQLQuotaError

    repo = tmp_path / "card"
    _init_repo(repo, "card-820-graphql-quota-rest", "backend/app/main.py")
    payload = _write_payload(repo, "backend/app/main.py")

    def quota(_bound: str | None) -> str | None:
        raise GraphQLQuotaError(0, "2026-09-03T02:55:52Z")

    result = decide(payload, status_provider=quota)
    assert result["permission"] == "deny"
    assert "fail_closed" in result["agent_message"]
    assert "2026-09-03T02:55:52Z" in result["agent_message"]
    assert "remaining=0" in result["agent_message"]
