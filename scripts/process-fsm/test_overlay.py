"""Overlay schema, pin, join, and packaged-source goldens."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from fsm import load_fsm, validate_fsm  # noqa: E402
from guard import decide  # noqa: E402
from overlay import (  # noqa: E402
    OverlayInvalid,
    OverlayMissing,
    dump_template,
    empty_required_keys,
    join_status_options,
    load_overlay,
    validate_overlay,
    write_init,
)
from paging import page  # noqa: E402
from test_overlay_fixtures import COLUMN_IDS, filled_overlay_dict, write_overlay  # noqa: E402

PACKAGED = (
    ROOT / "board_status.py",
    ROOT / "guard.py",
    ROOT / "process_event.py",
)
FORBIDDEN_FIELD = "PVTSSF_lAHOAAHtBM4BV8b2zhRUdMM"
SILENT = lambda bound: (_ for _ in ()).throw(AssertionError(f"github called bound={bound}"))  # noqa: E731


def test_packaged_yaml_has_no_globs():
    fsm = load_fsm()
    validate_fsm(fsm)
    assert "product_globs" not in fsm
    assert "design_globs" not in fsm


def test_packaged_python_has_no_cripto_field_id():
    for path in PACKAGED:
        text = path.read_text(encoding="utf-8")
        assert FORBIDDEN_FIELD not in text, path


def test_init_lists_empty_keys(tmp_path: Path):
    dest = write_init(tmp_path)
    data = yaml.safe_load(dest.read_text(encoding="utf-8"))
    validate_overlay(data, require_filled=False, raw_text=dest.read_text(encoding="utf-8"))
    empty = empty_required_keys(data)
    assert "board.owner" in empty
    assert "product_globs" in empty
    assert "board.status_options.Em Refinamento" in empty
    raw = dest.read_text(encoding="utf-8")
    assert "backend/**" not in raw
    assert FORBIDDEN_FIELD not in raw


def test_pin_refuses_empty_overlay(tmp_path: Path):
    write_init(tmp_path)
    with pytest.raises((OverlayInvalid, OverlayMissing)):
        load_overlay(tmp_path, require_filled=True)


def test_join_succeeds_when_twelve_names_match():
    data = filled_overlay_dict()
    joined = join_status_options(data)
    assert joined == COLUMN_IDS


def test_join_fails_on_name_drift():
    data = filled_overlay_dict()
    data["board"]["status_options"] = {"Nope": "fed46e78", **{
        k: v for k, v in list(COLUMN_IDS.items())[1:]
    }}
    with pytest.raises(OverlayInvalid):
        join_status_options(data)


def test_join_fails_on_missing_id():
    data = filled_overlay_dict()
    data["board"]["status_options"]["Todo"] = ""
    with pytest.raises(OverlayInvalid):
        join_status_options(data)


def test_overlay_law_table_rejected():
    data = filled_overlay_dict()
    with pytest.raises(OverlayInvalid):
        validate_overlay(data, require_filled=True, raw_text="fail_closed_asymmetric: true\n")


def test_missing_overlay_denies_product_write(tmp_path: Path):
    repo = tmp_path / "card"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "card-773-x", str(repo)], check=True, capture_output=True)
    payload = {
        "tool_name": "Write",
        "tool_input": {"path": "backend/app/main.py"},
        "cwd": str(repo),
        "status": "Em desenvolvimento",
    }
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"
    assert "overlay" in result["agent_message"]


def test_missing_overlay_allows_overlay_and_design_writes(tmp_path: Path):
    repo = tmp_path / "card"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "card-773-x", str(repo)], check=True, capture_output=True)
    for rel in (".covenant-flow/overlay.yaml", "openspec/changes/x/tasks.md"):
        result = decide(
            {
                "tool_name": "Write",
                "tool_input": {"path": rel},
                "cwd": str(repo),
                "status": "Em desenvolvimento",
            },
            status_provider=SILENT,
        )
        assert result["permission"] == "allow", rel


def test_page_unbound_without_overlay_does_not_dump(tmp_path: Path):
    result = page(
        cwd=tmp_path,
        resolve_fn=lambda *a, **k: {"q": None, "bound_card": "⊥", "q_git": "⊥"},
        status_provider=lambda bound: None,
    )
    ctx = result["additional_context"]
    assert "bound_card=⊥" in ctx
    assert "docs/crypto-overlay.md" not in ctx
    assert "overlay.yaml" not in ctx
    assert dump_template()[:20] not in ctx


def test_grok_opencode_have_no_law_table():
    for folder in (REPO / ".grok", REPO / ".opencode", REPO / ".dsh"):
        for path in folder.rglob("*"):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "| T0 |" not in text
            assert "### Requirement:" not in text
            assert "illegal_edges" not in text


def test_skill_stubs_body_budget():
    from dsh_stubs import stub_errors as dsh_errors
    from grok_stubs import stub_errors as grok_errors
    from opencode_stubs import stub_errors as oc_errors

    assert grok_errors() == []
    assert oc_errors() == []
    assert dsh_errors() == []
