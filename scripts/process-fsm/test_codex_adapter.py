from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from adapter_manifest import ENTRYPOINTS
from model_selection_fixtures import machine_models
from model_selection import resolve, save_capture

ROOT = next(ancestor / "scripts/process-fsm" for ancestor in Path(__file__).resolve().parents
            if (ancestor / ".cursor/process-fsm.yaml").is_file())
sys.path.insert(0, str(ROOT))

import codex_adapter  # noqa: E402
from guard import extract_paths, normalize  # noqa: E402
from paging import page as shared_page  # noqa: E402
from shim_fixtures import registered_account, registered_document, shim_call  # noqa: E402
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


def test_agent_spawn_requires_local_pair_role_and_birth_capture(tmp_path: Path, machine_models):
    root = _repo(tmp_path, "card-1042-codex-adapter")
    _model_map(root)  # Legacy cannot override the account's selection.
    cap_path = tmp_path / "birth.json"
    save_capture(cap_path, resolve("codex", "juizo", role="design-autor"))
    request = {"tool_name": "Agent", "tool_input": {
        "description": "design-autor 1042", "prompt": f"model_selection_capture: {cap_path}",
        "model": "gpt-6-sol", "reasoning_effort": "high"}, "cwd": str(root)}
    assert "birth_receipt_missing" in codex_adapter.pre_tool_use(request)["hookSpecificOutput"]["permissionDecisionReason"]
    document = yaml.safe_load(machine_models.read_text())
    document["clients"]["codex"]["juizo"].update(label="Updated Sol", model="updated-sol", effort="xhigh")
    machine_models.write_text(yaml.safe_dump(document))
    assert codex_adapter.pre_tool_use(request) is not None
    fresh = tmp_path / "fresh.json"
    save_capture(fresh, resolve("codex", "juizo", role="design-autor"))
    request["tool_input"].update(model="updated-sol", reasoning_effort="xhigh", prompt=f"model_selection_capture: {fresh}")
    assert "birth_receipt_missing" in codex_adapter.pre_tool_use(request)["hookSpecificOutput"]["permissionDecisionReason"]
    request["tool_input"].update(model="inherit")
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


def test_codex_code_review_session_does_not_route_reviewers_through_cursor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = _repo(tmp_path, "card-1042-codex-review-routing")
    _model_map(repo)
    monkeypatch.setattr(
        codex_adapter,
        "page",
        lambda **kwargs: shared_page(**kwargs, status_provider=lambda _bound: "Code Review"),
    )

    context = codex_adapter.session_start({"cwd": str(repo)})["hookSpecificOutput"]["additionalContext"]

    assert "q=Code Review" in context
    assert "Cliente ativo: Codex CLI" in context
    assert "`diff-reviewer` e `code-reviewer`" in context
    assert "Agents nativos do Codex" in context
    assert "read-only desde o nascimento" in context
    assert "recuse visivelmente antes de qualquer spawn" in context
    assert "não prova nem altera o sandbox do turno pai" in context
    assert "sem alternância manual de permissões" in context
    assert "`/permissions`" not in context
    assert "cadeia principal/coordenador/filhos" in context
    assert "Coordenador novo qualifica contexto opção 2" in context
    assert "`codex exec --sandbox read-only`" in context
    assert "registra proxies via `codex_proxy.py`" in context
    assert "metadados observados de runtime/trace e retorno, nunca inferidos" in context
    assert "scripts/process-fsm/review_process_checklist.py" in context
    assert "`codex/execucao` da escolha local" in context
    assert "Não encaminhe os reviewers para Cursor Task, `cursor-agent` ou Composer." in context
    order = [
        context.index("o pai/orquestrador gravável primeiro materializa"),
        context.index("Depois inicia uma sessão Codex CLI dedicada"),
        context.index("Nessa sessão, no mesmo turno"),
        context.index("Mantenha essa sessão `read-only`"),
        context.index("Após os dois retornos, o pai/orquestrador gravável registra proxies"),
        context.index("Então executa `verify-wave`"),
        context.index("Faça commit apenas depois de `verify-wave`"),
    ]
    assert order == sorted(order)


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


def test_unknown_hosted_tool_fails_closed_if_adapter_is_invoked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    registered_account(monkeypatch, tmp_path / "operator", ["codex"])
    repo = _repo(tmp_path, "card-1042-codex-adapter")

    decision = codex_adapter.pre_tool_use(
        {
            "tool_name": "mcp__github__project_item_edit",
            "tool_input": {"status": "Done"},
            "cwd": str(repo),
        }
    )
    hooks = registered_document("codex")
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


def test_account_registration_has_the_required_events_and_resolves_the_repo_through_the_shim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # The pin writes no `.codex/hooks.json` in the consumer: `install.sh --account` registers one shim entry per
    # event in the operator's `~/.codex/hooks.json`, and the shim (not a `git rev-parse` in the command) finds the repo.
    registered_account(monkeypatch, tmp_path / "operator", ["codex"])
    hooks = registered_document("codex")["hooks"]

    assert {"SessionStart", "PreToolUse", "PostToolUse", "Stop"} == set(hooks)
    pre = hooks["PreToolUse"][0]
    assert "Bash" in pre["matcher"] and "apply_patch" in pre["matcher"] and "Agent" in pre["matcher"]
    for event, shim_event in (("SessionStart", "session-start"), ("PreToolUse", "pre-tool-use"), ("PostToolUse", "post-tool-use"), ("Stop", "stop")):
        handler = hooks[event][0]["hooks"][0]
        assert shim_call(handler["command"]) == ("codex", shim_event)
        assert "git rev-parse" not in handler["command"] and "codex_adapter.py" not in handler["command"]
        assert ENTRYPOINTS["codex"][shim_event] == ["python3", "scripts/process-fsm/codex_adapter.py", shim_event]
        assert handler["timeout"] == 30
    assert (ROOT.parents[1] / ENTRYPOINTS["codex"]["pre-tool-use"][1]).is_file()


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


def _reason(decision):
    assert decision is not None
    return decision["hookSpecificOutput"]["permissionDecisionReason"]


@pytest.mark.parametrize("field", ["cmd", "command"])
def test_native_command_variants_with_subdirectory_workdir_use_bound_card(tmp_path, monkeypatch, field):
    repo = _repo(tmp_path, "card-1098-adapter")
    (repo / "backend").mkdir()
    target = repo / "backend" / "probe.txt"
    target.write_text("before")
    event = {"tool_name": "exec_command", "cwd": str(repo), "tool_input": {field: "printf after > probe.txt", "workdir": str(repo / "backend")}}
    monkeypatch.setattr(codex_adapter, "github_status_provider", lambda card: "Em desenvolvimento" if card == "1098" else None)
    assert codex_adapter.pre_tool_use(event) is None
    subprocess.run(["bash", "-c", event["tool_input"][field]], cwd=event["tool_input"]["workdir"], check=True)
    assert target.read_text() == "after"


@pytest.mark.parametrize("status", ["Todo", "Design", "Pronto para Dev"])
def test_all_shell_targets_are_guarded_before_fixture_mutation(tmp_path, monkeypatch, status):
    repo = _repo(tmp_path, "card-1098-adapter")
    design = repo / "openspec/changes/card-1098-adapter/design.md"
    product = repo / "backend/probe.txt"
    design.parent.mkdir(parents=True)
    product.parent.mkdir()
    design.write_text("design before")
    product.write_text("product before")
    monkeypatch.setattr(codex_adapter, "github_status_provider", lambda card: status)
    event = {"tool_name": "exec_command", "cwd": str(repo), "status": "Em desenvolvimento", "tool_input": {"cmd": "printf changed > openspec/changes/card-1098-adapter/design.md; printf changed > backend/probe.txt"}}
    decision = codex_adapter.pre_tool_use(event)
    assert "deny" in _reason(decision)
    # The fixture executes the command only on an allow, just like PreToolUse.
    if decision is None:
        subprocess.run(["bash", "-c", event["tool_input"]["cmd"]], cwd=repo, check=True)
    assert design.read_text() == "design before"
    assert product.read_text() == "product before"


@pytest.mark.parametrize("route", ["workdir", "patch", "redirect", "symlink", "copy_option", "change_card"])
def test_tool_input_cannot_grant_another_card_or_escape_binding(tmp_path, monkeypatch, route):
    repo = _repo(tmp_path, "card-1098-adapter")
    other = _repo(tmp_path, "card-9999-other")
    target = other / "backend/probe.txt"
    target.parent.mkdir()
    target.write_text("unchanged")
    (repo / "escape").symlink_to(other / "backend", target_is_directory=True)
    monkeypatch.setattr(codex_adapter, "github_status_provider", lambda card: "Em desenvolvimento")
    tool, data = "exec_command", {"cmd": f"printf changed > {target}"}
    if route == "workdir":
        data = {"cmd": "printf changed > backend/probe.txt", "workdir": str(other)}
    elif route == "patch":
        tool, data = "apply_patch", {"command": f"*** Begin Patch\n*** Update File: openspec/changes/card-1098-adapter/design.md\n*** Update File: {target}\n*** End Patch"}
    elif route == "symlink":
        data = {"cmd": "printf changed > escape/probe.txt"}
    elif route == "copy_option":
        data = {"cmd": f"cp --target-directory={target.parent} tracked.txt"}
    elif route == "change_card":
        tool, data = "apply_patch", {"command": "*** Begin Patch\n*** Add File: openspec/changes/card-9999-other/design.md\n*** End Patch"}
    decision = codex_adapter.pre_tool_use({"tool_name": tool, "cwd": str(repo), "tool_input": data})
    assert any(reason in _reason(decision) for reason in ("worktree_mismatch", "target_outside_binding", "target_card_mismatch"))
    assert target.read_text() == "unchanged"


def test_source_identity_cannot_be_replaced_by_workdir_and_missing_cwd_is_denied(tmp_path, monkeypatch):
    source = _repo(tmp_path, "develop")
    card = _repo(tmp_path, "card-1098-adapter")
    monkeypatch.setattr(codex_adapter, "github_status_provider", lambda card: "Em desenvolvimento")
    event = {"tool_name": "exec_command", "cwd": str(source), "tool_input": {"cmd": "printf x > backend/probe.txt", "workdir": str(card)}}
    assert "worktree_mismatch" in _reason(codex_adapter.pre_tool_use(event))
    event.pop("cwd")
    monkeypatch.chdir(card)
    assert "binding_unavailable" in _reason(codex_adapter.pre_tool_use(event))


@pytest.mark.parametrize("command", ["cd backend; printf x > probe.txt", "printf x > $TARGET", "printf x > `pwd`/backend/probe.txt"])
def test_dynamic_shell_mutation_refuses_unsupported_target_coverage(tmp_path, command):
    repo = _repo(tmp_path, "card-1098-adapter")
    event = {"tool_name": "exec_command", "cwd": str(repo), "tool_input": {"cmd": command}}
    assert "unsupported_targets" in _reason(codex_adapter.pre_tool_use(event))


def test_conflicting_native_command_fields_are_not_silently_selected(tmp_path):
    repo = _repo(tmp_path, "card-1098-adapter")
    event = {"tool_name": "exec_command", "cwd": str(repo), "tool_input": {"cmd": "true", "command": "false"}}
    assert "ambiguous_command" in _reason(codex_adapter.pre_tool_use(event))


def test_normalization_preserves_original_native_event_and_ignores_injected_status(tmp_path, monkeypatch):
    repo = _repo(tmp_path, "card-1098-adapter")
    event = {"tool_name": "exec_command", "cwd": str(repo), "status": "Em desenvolvimento", "tool_input": {"cmd": "printf x > backend/probe.txt", "workdir": str(repo)}}
    original = json.loads(json.dumps(event))
    monkeypatch.setattr(codex_adapter, "github_status_provider", lambda card: "Todo")
    assert "todo-write" in _reason(codex_adapter.pre_tool_use(event))
    assert event == original


def test_hook_context_must_match_authoritative_current_turn(tmp_path, monkeypatch):
    import codex_evidence
    repo = _repo(tmp_path, "card-1098-adapter")
    event = {"tool_name": "exec_command", "cwd": str(repo), "session_id": "same-chat", "tool_input": {"cmd": "printf x > backend/probe.txt"}}
    monkeypatch.setenv("CODEX_THREAD_ID", "same-chat")
    monkeypatch.setattr(codex_evidence.Rollout, "session", lambda self, tid: (None, [], {}, [{"cwd": "/historical-source"}]))
    assert "binding_mismatch" in _reason(codex_adapter.pre_tool_use(event))
    event["session_id"] = "other-chat"
    assert "hook session differs" in _reason(codex_adapter.pre_tool_use(event))
