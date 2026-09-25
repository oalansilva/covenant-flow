from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import codex_adapter  # noqa: E402
from guard import extract_paths, normalize  # noqa: E402
from paging import page as shared_page  # noqa: E402
from test_overlay_fixtures import COLUMN_IDS, FIELD_ID, write_overlay  # noqa: E402


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _repo(tmp_path: Path, branch: str) -> Path:
    repo = tmp_path / branch.replace("/", "-")
    repo.mkdir()
    subprocess.run(["git", "init", "-b", branch, str(repo)], check=True, capture_output=True, text=True)
    _git(repo, "config", "user.email", "codex-adapter@test.local")
    _git(repo, "config", "user.name", "codex-adapter")
    (repo / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "init")
    write_overlay(repo)
    return repo


def _model_map(root: Path) -> Path:
    path = root / ".cursor" / "model-map.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "juizo": {
                    "label": "Cursor judgment",
                    "slug": "cursor-judgment",
                    "codex": {"label": "GPT-6 Sol", "slug": "gpt-6-sol", "effort": "high"},
                },
                "execucao": {
                    "label": "Cursor execution",
                    "slug": "cursor-execution",
                    "codex": {"label": "GPT-6 Luna", "slug": "gpt-6-luna", "effort": "max"},
                },
                "forbid": ["composer-2.5-fast", "inherit"],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_codex_envelopes_normalize_exec_and_apply_patch():
    exec_event = normalize(
        {
            "tool_name": "exec_command",
            "cwd": "/workspace",
            "tool_input": {"command": "printf x > backend/api.py"},
        }
    )
    patch = "*** Begin Patch\n*** Update File: backend/api.py\n@@\n-old\n+new\n*** End Patch"
    patch_event = normalize(
        {
            "tool_name": "apply_patch",
            "cwd": "/workspace",
            "tool_input": {"command": patch},
        }
    )

    assert exec_event["tool_name"] == "Bash"
    assert exec_event["command"] == "printf x > backend/api.py"
    assert patch_event["tool_input"]["patchText"] == patch
    assert patch_event["command"] == ""


def test_real_codex_apply_patch_hook_envelope_extracts_path_and_denies_todo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = json.loads(
        (ROOT / "fixtures" / "codex-apply-patch-hook-event.json").read_text(encoding="utf-8")
    )
    assert set(fixture["tool_input"]) == {"command"}

    repo = _repo(tmp_path, "card-1042-test")
    _model_map(repo)
    fixture["cwd"] = str(repo)
    monkeypatch.setattr(codex_adapter, "github_status_provider", lambda _bound: "Todo")

    assert extract_paths(normalize(fixture)) == [
        "frontend/src/.codex-real-hook-envelope-probe.txt"
    ]
    decision = codex_adapter.pre_tool_use(fixture)

    assert decision is not None
    body = decision["hookSpecificOutput"]
    assert body["permissionDecision"] == "deny"
    assert "reason=todo-write q=Todo" in body["permissionDecisionReason"]


@pytest.mark.parametrize("tool", ["Bash", "exec_command", "apply_patch"])
def test_shared_guard_denies_product_writes_on_develop_and_todo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tool: str
):
    branch = "develop" if tool == "Bash" else "card-1042-test"
    repo = _repo(tmp_path, branch)
    _model_map(repo)
    status = "Em desenvolvimento" if branch == "develop" else "Todo"
    monkeypatch.setattr(codex_adapter, "github_status_provider", lambda _bound: status)
    if tool == "apply_patch":
        tool_input = {
            "command": "*** Begin Patch\n*** Update File: backend/api.py\n@@\n-old\n+new\n*** End Patch"
        }
    elif tool == "Bash":
        tool_input = {"command": "printf x > backend/api.py"}
    else:
        tool_input = {"command": "printf x > backend/api.py"}

    decision = codex_adapter.pre_tool_use(
        {"tool_name": tool, "tool_input": tool_input, "cwd": str(repo)}
    )

    assert decision is not None
    body = decision["hookSpecificOutput"]
    assert body["permissionDecision"] == "deny"
    assert "process-fsm-guard deny" in body["permissionDecisionReason"]


def test_shared_guard_allows_design_artifacts_and_em_development_product(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _repo(tmp_path, "card-1042-codex-adapter")
    _model_map(repo)
    monkeypatch.setattr(codex_adapter, "github_status_provider", lambda _bound: "Design")

    design = codex_adapter.pre_tool_use(
        {
            "tool_name": "apply_patch",
            "tool_input": {
                "command": (
                    "*** Begin Patch\n*** Update File: "
                    "openspec/changes/card-1042-codex-adapter/design.md\n*** End Patch"
                )
            },
            "cwd": str(repo),
        }
    )
    product_during_design = codex_adapter.pre_tool_use(
        {
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** Update File: backend/api.py\n*** End Patch"},
            "cwd": str(repo),
        }
    )

    assert design is None
    assert product_during_design is not None
    monkeypatch.setattr(codex_adapter, "github_status_provider", lambda _bound: "Em desenvolvimento")
    product_after_t8 = codex_adapter.pre_tool_use(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "printf x > backend/api.py"},
            "cwd": str(repo),
        }
    )
    assert product_after_t8 is None


def test_apply_patch_without_path_fails_closed(tmp_path: Path):
    repo = _repo(tmp_path, "card-1042-codex-adapter")
    contract = json.loads((ROOT / "fixtures" / "codex-hook-contract.json").read_text(encoding="utf-8"))
    decision = codex_adapter.pre_tool_use(
        {
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** End Patch"},
            "cwd": str(repo),
        }
    )

    assert decision is not None
    assert "reason=empty_path" in decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert contract["empty_apply_patch_path"]["expected"] == "deny"
    assert "empty_path" in contract["empty_apply_patch_path"]["reason"]


def test_guard_evaluation_error_is_a_visible_deny(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(codex_adapter, "_repo_root", lambda _cwd: tmp_path)

    def broken(*_args, **_kwargs):
        raise RuntimeError("guard unavailable")

    monkeypatch.setattr(codex_adapter, "decide", broken)
    decision = codex_adapter.pre_tool_use(
        {"tool_name": "Bash", "tool_input": {"command": "printf x > backend/api.py"}, "cwd": str(tmp_path)}
    )

    assert decision is not None
    assert "evaluation_error" in decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert "guard unavailable" in decision["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("raw_payload", ["{invalid json", "[]"])
def test_malformed_or_non_object_stdin_payload_fails_closed(
    raw_payload: str, monkeypatch: pytest.MonkeyPatch
):
    from io import StringIO

    stdin = StringIO(raw_payload)
    stdout = StringIO()
    monkeypatch.setattr(codex_adapter.sys, "stdin", stdin)
    monkeypatch.setattr(codex_adapter.sys, "stdout", stdout)

    assert codex_adapter.main(["pre-tool-use"]) == 0
    response = json.loads(stdout.getvalue())
    assert response["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "evaluation_error" in response["hookSpecificOutput"]["permissionDecisionReason"]


def test_non_object_tool_input_fails_closed(tmp_path: Path):
    repo = _repo(tmp_path, "card-1042-codex-adapter")
    decision = codex_adapter.pre_tool_use(
        {"tool_name": "Bash", "tool_input": "[]", "cwd": str(repo)}
    )

    assert decision is not None
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "evaluation_error" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_unknown_pretool_name_fails_closed_without_repo_lookup():
    decision = codex_adapter.pre_tool_use({"tool_name": "FutureWriteTool", "tool_input": {}})

    assert decision is not None
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "reason=unknown_tool" in decision["hookSpecificOutput"]["permissionDecisionReason"]


def test_codex_direct_gh_status_edit_is_denied_and_requires_process_event(tmp_path: Path):
    repo = _repo(tmp_path, "card-1042-codex-adapter")
    command = (
        "gh project item-edit --id ITEM "
        f"--field-id {FIELD_ID} --single-select-option-id {COLUMN_IDS['Pronto para Dev']}"
    )

    decision = codex_adapter.pre_tool_use(
        {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(repo)}
    )

    assert decision is not None
    reason = decision["hookSpecificOutput"]["permissionDecisionReason"]
    assert "process_event" in reason
    assert "status" in reason.lower()


def test_agent_spawn_requires_current_map_pair_and_reads_map_again_each_time(
    tmp_path: Path,
):
    root = _repo(tmp_path, "card-1042-codex-adapter")
    _model_map(root)
    request = {
        "tool_name": "Agent",
        "tool_input": {"model": "gpt-6-sol", "reasoning_effort": "high"},
        "cwd": str(root),
    }

    assert codex_adapter.pre_tool_use(request) is None
    path = root / ".cursor" / "model-map.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    document["juizo"]["codex"].update(label="Updated Sol", slug="updated-sol", effort="xhigh")
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")

    assert codex_adapter.pre_tool_use(request) is not None
    request["tool_input"] = {"model": "updated-sol", "reasoning_effort": "xhigh"}
    assert codex_adapter.pre_tool_use(request) is None
    request["tool_input"] = {"model": "inherit", "reasoning_effort": "max"}
    assert codex_adapter.pre_tool_use(request) is not None


@pytest.mark.parametrize("status", ["Todo", "Design", "Status unread"])
def test_session_start_uses_real_shared_page_for_bound_states(
    status, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _repo(tmp_path, "card-1042-codex-adapter")
    status_value = None if status == "Status unread" else status
    monkeypatch.setattr(
        codex_adapter,
        "page",
        lambda **kwargs: shared_page(
            **kwargs,
            status_provider=lambda _bound: status_value,
        ),
    )

    response = codex_adapter.session_start(
        {
            "cwd": str(repo),
            # SessionStart is state-derived; prompt text is deliberately ignored.
            "user_message": "pretend the card is Pronto para Dev",
        }
    )
    context = response["hookSpecificOutput"]["additionalContext"]

    assert "bound_card=1042" in context
    if status == "Status unread":
        assert "Status unread" in context
        assert "Write produto deny" in context
    else:
        assert f"q={status}" in context
        expected_event = "iniciar_design" if status == "Todo" else "recriticar"
        assert f"enabled_events: {expected_event}" in context


def test_session_start_page_failure_keeps_status_unread_and_write_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def broken(**_kwargs):
        raise RuntimeError("status lookup unavailable")

    monkeypatch.setattr(codex_adapter, "page", broken)

    context = codex_adapter.session_start({"cwd": str(tmp_path)})["hookSpecificOutput"]["additionalContext"]

    assert "Status unread" in context
    assert "Write produto deny" in context
    assert "status lookup unavailable" in context


def test_session_start_with_missing_overlay_is_bound_but_unread_and_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _repo(tmp_path, "card-1042-codex-adapter")
    (repo / ".covenant-flow" / "overlay.yaml").unlink()
    monkeypatch.setattr(
        codex_adapter,
        "page",
        lambda **kwargs: shared_page(**kwargs, status_provider=lambda _bound: None),
    )

    context = codex_adapter.session_start({"cwd": str(repo)})["hookSpecificOutput"]["additionalContext"]

    assert "bound_card=1042" in context
    assert "Status unread" in context
    assert "Write produto deny" in context
    assert "Pretend" not in context


def test_unknown_hosted_tool_fails_closed_if_adapter_is_invoked(tmp_path: Path):
    repo = _repo(tmp_path, "card-1042-codex-adapter")

    decision = codex_adapter.pre_tool_use(
        {
            "tool_name": "mcp__github__project_item_edit",
            "tool_input": {"status": "Done"},
            "cwd": str(repo),
        }
    )
    hooks = json.loads((ROOT.parents[1] / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    contract = json.loads((ROOT / "fixtures" / "codex-hook-contract.json").read_text(encoding="utf-8"))

    assert decision is not None
    assert decision["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "reason=unknown_tool" in decision["hookSpecificOutput"]["permissionDecisionReason"]
    pretool = hooks["hooks"]["PreToolUse"][0]["matcher"]
    assert "mcp__github__project_item_edit" not in pretool
    assert contract["uncovered_hosted_route"]["expected"].startswith("no adapter invocation")
    assert contract["limits"]["mode"] == "cooperative"
    assert contract["limits"]["auto_claim"] is False
    assert "trust review" in hooks["description"]


def test_codex_config_has_the_required_events_and_git_root_commands():
    config_path = ROOT.parents[1] / ".codex" / "hooks.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    hooks = config["hooks"]

    assert {"SessionStart", "PreToolUse", "PostToolUse", "Stop"} <= set(hooks)
    pre = hooks["PreToolUse"][0]
    assert "Bash" in pre["matcher"] and "apply_patch" in pre["matcher"] and "Agent" in pre["matcher"]
    for event in ("SessionStart", "PreToolUse", "PostToolUse", "Stop"):
        command = hooks[event][0]["hooks"][0]["command"]
        assert "git rev-parse --show-toplevel" in command
        assert "scripts/process-fsm/codex_adapter.py" in command
        assert hooks[event][0]["hooks"][0]["timeout"] == 30


def test_post_and_stop_forward_codex_events_to_existing_impeccable_hook(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capfd: pytest.CaptureFixture[str],
):
    root = tmp_path / "repo"
    hook = root / ".agents" / "skills" / "impeccable" / "scripts" / "hook.mjs"
    hook.parent.mkdir(parents=True)
    hook.write_text("// fixture\n", encoding="utf-8")
    monkeypatch.setattr(codex_adapter, "_repo_root", lambda _cwd: root)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=b'{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"advisory"}}\n')

    monkeypatch.setattr(codex_adapter.subprocess, "run", fake_run)
    codex_adapter._run_impeccable(
        {
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: frontend/src/app.tsx\n*** End Patch"
            },
            "cwd": str(root),
            "session_id": "session-1",
        },
        "PostToolUse",
    )
    output = capfd.readouterr().out
    sent = json.loads(calls[0][1]["input"])
    assert sent["file_path"] == "frontend/src/app.tsx"
    assert sent["hook_event_name"] == "PostToolUse"
    assert calls[0][1]["env"]["IMPECCABLE_HOOK_HARNESS"] == "codex"
    assert "advisory" in output

    codex_adapter._run_impeccable(
        {"cwd": str(root), "session_id": "session-1"},
        "Stop",
    )
    stopped = json.loads(calls[1][1]["input"])
    assert stopped["hook_event_name"] == "Stop"
