from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from guard import (  # noqa: E402
    WRITE_TOOLS,
    _command,
    decide,
    extract_paths,
    is_dsh_editor_mutate,
    normalize,
)
from overlay import CLIENT_KEYS, SCHEMA_MAJOR, empty_template, validate_overlay  # noqa: E402
from test_overlay_fixtures import filled_overlay_dict, write_overlay  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

SILENT = lambda bound: (_ for _ in ()).throw(  # noqa: E731
    AssertionError(f"github called bound={bound}")
)
FIELD_ID = "PVTSSF_lAHOAAHtBM4BV8b2zhRUdMM"
PRODUCT = "backend/app/tasks/discovery_tasks.py"
FRONTEND = "frontend/src/x.tsx"
MAIN_PY = "backend/app/main.py"
DESIGN_MD = "openspec/changes/card-782-dsh-adapter/design.md"


def _run_git(repo: Path, *args: str) -> None:
    import subprocess

    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(path: Path, branch: str, filename: str) -> None:
    import subprocess

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


def _dsh(cwd: Path, tool: str, args: dict, status: str | None = None) -> dict:
    payload: dict = {"tool": tool, "args": args, "cwd": str(cwd)}
    if status is not None:
        payload["status"] = status
    return payload


def _assert_dual_deny(result: dict) -> None:
    assert result["permission"] == "deny"
    assert result["decision"] == "deny"
    assert result.get("reason")


def _assert_dual_allow(result: dict) -> None:
    assert result["permission"] == "allow"
    assert result["decision"] == "allow"


def test_d1_dsh_write_product_on_develop_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", PRODUCT)
    result = decide(
        _dsh(repo, "write", {"file_path": PRODUCT}, status="Em desenvolvimento"),
        status_provider=SILENT,
    )
    _assert_dual_deny(result)


def test_d2_dsh_edit_frontend_on_develop_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", FRONTEND)
    result = decide(
        _dsh(repo, "edit", {"file_path": FRONTEND}, status="Todo"),
        status_provider=SILENT,
    )
    _assert_dual_deny(result)


def test_d3_write_empty_file_path_denied():
    payload = {"tool": "write", "args": {"file_path": ""}, "cwd": "/"}
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)
    assert "empty_path" in result["reason"]
    assert "OpenCode write/edit/apply_patch" not in result["reason"]
    assert "file_path" in result["reason"]


def test_d4_edit_empty_file_path_denied():
    payload = {"tool": "edit", "args": {"file_path": ""}, "cwd": "/"}
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)
    assert "empty_path" in result["reason"]
    assert "file_path" in result["reason"]


def test_d5_bash_tee_denied(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", MAIN_PY)
    result = decide(
        _dsh(repo, "bash", {"command": "echo x | tee backend/app/main.py"}, status="Todo"),
        status_provider=SILENT,
    )
    _assert_dual_deny(result)


def test_d6_bash_status_item_edit_denied(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-782-dsh-adapter", MAIN_PY)
    command = (
        "gh project item-edit --id X "
        f"--field-id {FIELD_ID} --single-select-option-id bd47fbe8"
    )
    result = decide(_dsh(repo, "bash", {"command": command}, status="Design"), status_provider=SILENT)
    _assert_dual_deny(result)
    assert "process_event" in result["reason"]


def test_d7_edit_openspec_design_allowed(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-782-dsh-adapter", DESIGN_MD)
    calls: list = []

    def wrapped(fsm, ctx):
        calls.append(ctx)
        raise AssertionError("evaluate must not run for design_globs")

    result = decide(
        _dsh(repo, "edit", {"file_path": DESIGN_MD}, status="Design"),
        status_provider=SILENT,
        evaluate_fn=wrapped,
    )
    _assert_dual_allow(result)
    assert calls == []


def test_d8_unknown_grep_allowed():
    result = decide({"tool": "grep", "args": {}, "cwd": "/"}, status_provider=SILENT)
    _assert_dual_allow(result)


def test_d9_four_dialects_same_deny(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", PRODUCT)
    envelopes = [
        {"tool_name": "Write", "tool_input": {"path": PRODUCT}, "cwd": str(repo), "status": "Todo"},
        {
            "toolName": "write",
            "toolInput": {"file_path": PRODUCT},
            "cwd": str(repo),
            "status": "Todo",
        },
        {"tool": "edit", "args": {"filePath": PRODUCT}, "cwd": str(repo), "status": "Todo"},
        {"tool": "write", "args": {"file_path": PRODUCT}, "cwd": str(repo), "status": "Todo"},
    ]
    results = [decide(item, status_provider=SILENT) for item in envelopes]
    for item in results:
        _assert_dual_deny(item)
    assert {item["permission"] for item in results} == {"deny"}
    assert {item["decision"] for item in results} == {"deny"}


def test_d10_str_replace_editor_mutate_extract_paths_and_deny(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", MAIN_PY)
    payload = _dsh(
        repo,
        "str_replace_editor",
        {"command": "str_replace", "path": MAIN_PY, "old_str": "a", "new_str": "b"},
        status="Todo",
    )
    assert extract_paths(payload) == [MAIN_PY]
    assert _command(payload) == ""
    assert is_dsh_editor_mutate(payload)
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)
    assert "empty_path" not in result["reason"]


def test_d10b_str_replace_editor_insert_extract_paths_and_deny(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", MAIN_PY)
    payload = _dsh(
        repo,
        "str_replace_editor",
        {"command": "insert", "path": MAIN_PY, "insert_line": 1, "new_str": "x"},
        status="Todo",
    )
    assert extract_paths(payload) == [MAIN_PY]
    result = decide(payload, status_provider=SILENT)
    _assert_dual_deny(result)
    assert "empty_path" not in result["reason"]


def test_d10c_str_replace_editor_openspec_design_allowed(tmp_path: Path):
    repo = tmp_path / "card"
    _init_repo(repo, "card-782-dsh-adapter", DESIGN_MD)
    calls: list = []

    def wrapped(fsm, ctx):
        calls.append(ctx)
        raise AssertionError("evaluate must not run for design_globs")

    payload = _dsh(
        repo,
        "str_replace_editor",
        {"command": "str_replace", "path": DESIGN_MD, "old_str": "a", "new_str": "b"},
        status="Design",
    )
    assert extract_paths(payload) == [DESIGN_MD]
    result = decide(payload, status_provider=SILENT, evaluate_fn=wrapped)
    _assert_dual_allow(result)
    assert calls == []


def test_d11_str_replace_editor_view_not_write_produto(tmp_path: Path):
    repo = tmp_path / "develop"
    _init_repo(repo, "develop", MAIN_PY)
    calls: list = []

    def wrapped(fsm, ctx):
        calls.append(ctx)
        raise AssertionError("view must not evaluate write_produto")

    payload = _dsh(repo, "str_replace_editor", {"command": "view", "path": MAIN_PY}, status="Todo")
    assert extract_paths(payload) == []
    assert not is_dsh_editor_mutate(payload)
    result = decide(payload, status_provider=SILENT, evaluate_fn=wrapped)
    _assert_dual_allow(result)
    assert calls == []


def test_d12_str_replace_editor_empty_path_denied():
    for command in ("create", "str_replace", "insert"):
        args = {"command": command, "path": ""}
        if command == "create":
            args["file_text"] = "x"
        elif command == "insert":
            args["insert_line"] = 1
            args["new_str"] = "x"
        else:
            args["old_str"] = "a"
            args["new_str"] = "b"
        payload = {"tool": "str_replace_editor", "args": args, "cwd": "/"}
        assert extract_paths(payload) == []
        assert _command(payload) == ""
        result = decide(payload, status_provider=SILENT)
        _assert_dual_deny(result)
        assert "empty_path" in result["reason"]
        assert "str_replace_editor" in result["reason"]


def test_d14_workflow_allowed():
    result = decide(
        {
            "tool": "workflow",
            "args": {"script": "return 1", "meta": {"name": "x", "description": "y"}},
            "cwd": "/",
        },
        status_provider=SILENT,
    )
    _assert_dual_allow(result)


def test_d19_overlay_omits_clients_dsh():
    data = filled_overlay_dict()
    assert "dsh" not in data["clients"]
    validate_overlay(data, require_filled=True)
    template = empty_template()
    assert "dsh" not in template["clients"]
    assert tuple(template["clients"]) == CLIENT_KEYS
    assert CLIENT_KEYS == ("cursor", "grok", "opencode")
    assert SCHEMA_MAJOR == 1


def test_d19b_overlay_extra_clients_dsh_auto_false():
    data = filled_overlay_dict()
    data["clients"]["dsh"] = {"auto": False}
    data["clients"]["unknown_extra"] = {"auto": False}
    validate_overlay(data, require_filled=True)
    assert SCHEMA_MAJOR == 1
    assert CLIENT_KEYS == ("cursor", "grok", "opencode")


def test_normalize_does_not_promote_editor_command_to_shell():
    native = normalize(
        {
            "tool": "str_replace_editor",
            "args": {"command": "str_replace", "path": MAIN_PY},
            "directory": "/tmp/ws",
        }
    )
    assert native["tool_name"] == "str_replace_editor"
    assert native["command"] == ""
    assert native["tool_input"]["command"] == "str_replace"
    assert native["cwd"] == "/tmp/ws"
    assert "str_replace_editor" not in WRITE_TOOLS
