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
from test_overlay_fixtures import FIELD_ID, write_overlay  # noqa: E402

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
    assert hooks["hooks"]["afterFileEdit"][0]["command"].endswith("impeccable.sh afterFileEdit")
    assert hooks["hooks"]["stop"][0]["command"].endswith("impeccable.sh stop")
    assert (REPO / ".cursor" / "hooks" / "impeccable.sh").is_file()


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
    for item in pre:
        handler = item["hooks"][0]
        assert handler["timeout"] >= 30
        assert handler["command"] == "./process-fsm-guard.sh"
    start = hooks["hooks"]["SessionStart"][0]["hooks"][0]
    assert "process-fsm-session-start.sh" in start["command"]
    post = hooks["hooks"]["PostToolUse"][0]["hooks"][0]
    assert post["command"] == "./impeccable.sh PostToolUse"
    assert post["timeout"] >= 30
    stop = hooks["hooks"]["Stop"][0]["hooks"][0]
    assert stop["command"] == "./impeccable.sh Stop"
    assert stop["timeout"] >= 30
    assert (REPO / ".grok" / "hooks" / "impeccable.sh").is_file()


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
