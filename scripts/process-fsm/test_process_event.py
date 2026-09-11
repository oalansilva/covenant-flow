from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from test_overlay_fixtures import FIELD_ID, filled_overlay_dict, write_overlay  # noqa: E402
import design_clone_gate  # noqa: E402
from fsm import load_fsm  # noqa: E402
from guard import decide  # noqa: E402
from process_event import (  # noqa: E402
    HUMAN_EVENTS,
    FakeMover,
    files_g_design,
    process_event,
    sidecar_path,
)
from t14 import RecordingT14Runner, T14Error  # noqa: E402
from resolve import UNBOUND  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")
SILENT = lambda bound: (_ for _ in ()).throw(AssertionError(f"github called bound={bound}"))  # noqa: E731


def _change_tree(tmp_path: Path) -> Path:
    change = tmp_path / "openspec" / "changes" / "card-612-process-event"
    change.mkdir(parents=True)
    (change / "proposal.md").write_text("# p\n", encoding="utf-8")
    (change / "design.md").write_text("# d\n", encoding="utf-8")
    (change / "tasks.md").write_text("# t\n", encoding="utf-8")
    specs = change / "specs" / "x"
    specs.mkdir(parents=True)
    (specs / "spec.md").write_text("# s\n", encoding="utf-8")
    return change


def test_criar_card_not_implemented():
    mover = FakeMover()
    out = process_event("criar_card", card="612", mover=mover, status=None)
    assert out["result"] == "reject"
    assert out["reason"] == "not_implemented"
    assert mover.calls == []
    assert "actor" not in inspect.signature(process_event).parameters


def test_aprovar_design_rejected():
    mover = FakeMover()
    out = process_event(
        "aprovar_design",
        status="Aprovação de Design",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=False,
        g_design=True,
    )
    assert out["result"] == "reject"
    assert mover.calls == []
    assert out["state"] == "Aprovação de Design"


@pytest.mark.parametrize("event", ["priorizar", "homologar", "nao_homologar", "fechar_release"])
def test_human_gates_rejected(event: str):
    state = {
        "priorizar": "Em Refinamento",
        "homologar": "Done",
        "nao_homologar": "Done",
        "fechar_release": "Homologado",
    }[event]
    mover = FakeMover()
    out = process_event(
        event,
        status=state,
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        m_lote=False,
        status_provider=SILENT,
    )
    assert out["result"] == "reject"
    assert mover.calls == []
    if event == "fechar_release":
        assert "covenant-flow-environments" in (out.get("message") or "")
        assert "release-guard" in (out.get("message") or "")


def test_request_implement_lists_enabled_events():
    mover = FakeMover()
    out = process_event(
        "request_implement",
        status="Todo",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
    )
    assert out["result"] == "reject"
    assert mover.calls == []
    assert "iniciar_design" in out["enabled_events"]


def test_iniciar_apply_does_not_grant_write():
    mover = FakeMover()
    out = process_event(
        "iniciar_apply",
        status="Pronto para Dev",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=False,
        g_design=True,
    )
    assert out["result"] == "transition"
    assert out["to"] == "Em desenvolvimento"
    assert "write" not in out
    payload = {
        "tool_name": "Write",
        "tool_input": {"path": "backend/app/main.py"},
        "cwd": "/",
        "status": "Pronto para Dev",
    }
    # Guard still sees injected Pronto para Dev even after mover recorded the transition.
    result = decide(
        payload,
        status_provider=SILENT,
        resolve_fn=lambda *a, **k: {"q": "Pronto para Dev", "q_git": "card-612-process-event", "bound_card": "612"},
        overlay=filled_overlay_dict(),
    )
    assert result["permission"] == "deny"
    assert "I3" in result["agent_message"]


def test_iniciar_apply_digest_changed_moves_design_not_dev():
    mover = FakeMover()
    out = process_event(
        "iniciar_apply",
        status="Pronto para Dev",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=True,
    )
    assert out["result"] == "transition"
    assert out["to"] == "Design"
    assert out["reason"] == "I4"
    assert mover.calls == [(612, "Design")]


def test_pedir_review_digest_changed_moves_design():
    mover = FakeMover()
    out = process_event(
        "pedir_review",
        status="Em desenvolvimento",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=True,
    )
    assert out["to"] == "Design"
    assert mover.calls == [(612, "Design")]
    assert out["reason"] == "I4"


def test_invalidar_aprovacao_without_digest_change_rejects():
    mover = FakeMover()
    out = process_event(
        "invalidar_aprovacao",
        status="Pronto para Dev",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=False,
    )
    assert out["result"] == "reject"
    assert mover.calls == []


def test_invalidar_aprovacao_with_digest_change_still_rejects_agent():
    mover = FakeMover()
    out = process_event(
        "invalidar_aprovacao",
        status="Pronto para Dev",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=True,
    )
    assert out["result"] == "reject"
    assert mover.calls == []


def test_pedir_review_wrong_state_does_not_compile_t17():
    mover = FakeMover()
    out = process_event(
        "pedir_review",
        status="Pronto para Dev",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=True,
        g_design=True,
    )
    assert out["result"] == "reject"
    assert out["to"] is None
    assert mover.calls == []


def test_change_dotdot_rejected():
    mover = FakeMover()
    out = process_event(
        "iniciar_apply",
        change="../other",
        status="Pronto para Dev",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=False,
        g_design=True,
    )
    assert out["result"] == "reject"
    assert out["reason"] == "invalid_change"
    assert mover.calls == []


def test_unbound_rejects():
    mover = FakeMover()
    out = process_event(
        "iniciar_apply",
        status="Pronto para Dev",
        q_git="develop",
        bound_card=UNBOUND,
        mover=mover,
        digest_changed=False,
    )
    assert out["result"] == "reject"
    assert out["reason"] == "unbound"
    assert mover.calls == []


def test_card_mismatch_rejects():
    mover = FakeMover()
    out = process_event(
        "iniciar_apply",
        card="605",
        status="Pronto para Dev",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=False,
    )
    assert out["result"] == "reject"
    assert out["reason"] == "card_mismatch"


R1_GALLERY = ROOT / "fixtures" / "792-r1-gallery.html"


def test_t5_default_g_design_refuses_r1_gallery_monitor(tmp_path: Path):
    change = _change_tree(tmp_path)
    (change / "design.md").write_text(
        "UI impact: affected\nlive_route: /monitor\n",
        encoding="utf-8",
    )
    proto = tmp_path / "proto"
    proto.mkdir()
    (proto / "index.html").write_bytes(R1_GALLERY.read_bytes())
    mover = FakeMover()
    out = process_event(
        "submeter_design",
        status="Design",
        q_git="card-799-prototype-clone-rota",
        bound_card="799",
        mover=mover,
        change_dir=change,
        prototype_dir=proto,
        digest_changed=False,
    )
    assert out["result"] == "reject"
    assert str(out["reason"]).startswith("guard:")
    assert mover.calls == []


def test_t5_default_g_design_ui_none_transitions(tmp_path: Path):
    change = _change_tree(tmp_path)
    (change / "design.md").write_text(
        "UI impact: none\nlive_route: N/A harness-only; no product route\nsurface: new\n",
        encoding="utf-8",
    )
    mover = FakeMover()
    out = process_event(
        "submeter_design",
        status="Design",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        change_dir=change,
        digest_changed=False,
    )
    assert out["result"] == "transition"
    assert out["to"] == "Aprovação de Design"
    assert mover.calls == [(612, "Aprovação de Design")]


def _seeded_head_catalog(_repo: Path) -> dict:
    return design_clone_gate.parse_catalog(
        design_clone_gate.default_catalog_path().read_text(encoding="utf-8")
    )


def test_t5_refuses_panel_plus_sibling_landing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(design_clone_gate, "load_head_catalog", _seeded_head_catalog)
    change = _change_tree(tmp_path)
    (change / "design.md").write_text(
        "UI impact: affected\nlive_route: landing\nsurface: existing\n",
        encoding="utf-8",
    )
    proto = tmp_path / "proto"
    proto.mkdir()
    (proto / "index.html").write_text(
        (ROOT / "fixtures" / "790-panel-index.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (proto / "landing.html").write_text(
        (ROOT / "fixtures" / "790-sibling-landing-clone.html").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    mover = FakeMover()
    out = process_event(
        "submeter_design",
        status="Design",
        q_git="card-819-clone-pagina-viva",
        bound_card="819",
        mover=mover,
        change_dir=change,
        prototype_dir=proto,
        digest_changed=False,
    )
    assert out["result"] == "reject"
    assert str(out["reason"]).startswith("guard:")
    assert mover.calls == []


def test_t5_refuses_existing_without_proto(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(design_clone_gate, "load_head_catalog", _seeded_head_catalog)
    change = _change_tree(tmp_path)
    (change / "design.md").write_text(
        "UI impact: none\nlive_route: landing\nsurface: existing\n",
        encoding="utf-8",
    )
    mover = FakeMover()
    out = process_event(
        "submeter_design",
        status="Design",
        q_git="card-819-clone-pagina-viva",
        bound_card="819",
        mover=mover,
        change_dir=change,
        digest_changed=False,
    )
    assert out["result"] == "reject"
    assert str(out["reason"]).startswith("guard:")
    assert mover.calls == []


def test_t5_writes_sidecar_dry_run_does_not(tmp_path: Path):
    change = _change_tree(tmp_path)
    assert files_g_design(change)
    mover = FakeMover()
    dry = process_event(
        "submeter_design",
        status="Design",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        dry_run=True,
        change_dir=change,
        g_design=True,
        digest_changed=False,
    )
    assert dry["result"] == "transition"
    assert not sidecar_path(change).is_file()
    assert mover.calls == []
    live = process_event(
        "submeter_design",
        status="Design",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        dry_run=False,
        change_dir=change,
        g_design=True,
        digest_changed=False,
    )
    assert live["to"] == "Aprovação de Design"
    assert sidecar_path(change).is_file()
    assert mover.calls == [(612, "Aprovação de Design")]


def test_aceitar_sha_moves_qa():
    mover = FakeMover()
    out = process_event(
        "aceitar_sha",
        status="Code Review",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=False,
        pr_lister=lambda q_git: [{"number": 99, "headRefOid": "abc"}],
    )
    assert out["to"] == "QA"
    assert mover.calls == [(612, "QA")]


def test_aceitar_sha_without_pr_is_no_pr():
    """#792: push sem PR MUST reject no_pr; Status stays Code Review; no PR created."""
    mover = FakeMover()
    created: list[str] = []

    def empty_lister(q_git):
        assert q_git == "card-792-x"
        return []

    out = process_event(
        "aceitar_sha",
        status="Code Review",
        q_git="card-792-x",
        bound_card="792",
        mover=mover,
        digest_changed=False,
        pr_lister=empty_lister,
    )
    assert out["result"] == "reject"
    assert out["reason"] == "no_pr"
    assert out["state"] == "Code Review"
    assert mover.calls == []
    assert created == []


def test_aceitar_sha_omitted_lister_is_no_pr():
    mover = FakeMover()
    out = process_event(
        "aceitar_sha",
        status="Code Review",
        q_git="card-792-x",
        bound_card="792",
        mover=mover,
        digest_changed=False,
    )
    assert out["result"] == "reject"
    assert out["reason"] == "no_pr"
    assert mover.calls == []


def test_integrar_develop_rejects_without_checks_green():
    mover = FakeMover()
    runner = RecordingT14Runner()
    out = process_event(
        "integrar_develop",
        status="QA",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=False,
        checks_green=None,
        t14_runner=runner,
    )
    assert out["result"] == "reject"
    assert mover.calls == []
    assert runner.calls == []


def test_m_lote_false_message():
    out = process_event(
        "fechar_release",
        status="Homologado",
        q_git="card-612-process-event",
        bound_card="612",
        mover=FakeMover(),
        m_lote=False,
    )
    assert out["result"] == "reject"
    assert "covenant-flow-environments" in (out.get("message") or "")
    assert "release-guard" in (out.get("message") or "")


def test_dry_run_does_not_call_mover():
    mover = FakeMover()
    out = process_event(
        "iniciar_apply",
        status="Pronto para Dev",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        dry_run=True,
        digest_changed=False,
    )
    assert out["result"] == "transition"
    assert mover.calls == []


def test_item_edit_status_denied():
    payload = {
        "command": f"gh project item-edit --id X --field-id {FIELD_ID} --single-select-option-id bd47fbe8",
        "cwd": "/",
        "status": "Design",
    }
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"
    assert "process_event" in result["agent_message"]


def test_chained_process_event_and_item_edit_denied():
    payload = {
        "command": (
            "python scripts/process-fsm/process_event.py iniciar_apply && "
            f"gh project item-edit --field-id {FIELD_ID}"
        ),
        "cwd": "/",
    }
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"


def test_pure_process_event_cli_allowed():
    payload = {
        "command": "backend/.venv/bin/python scripts/process-fsm/process_event.py iniciar_apply --card 612",
        "cwd": "/",
        "status": "Pronto para Dev",
    }
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "allow"


def test_gh_issue_view_allowed():
    payload = {"command": "gh issue view 612", "cwd": "/"}
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "allow"


def test_process_fsm_move_env_does_not_allow_item_edit():
    payload = {
        "command": f"PROCESS_FSM_MOVE=1 gh project item-edit --field-id {FIELD_ID}",
        "cwd": "/",
    }
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"


def test_sidecar_write_denied_in_design(tmp_path: Path):
    repo = tmp_path / "card"
    repo.mkdir()
    rel = "openspec/changes/card-612-process-event/.design-digest"
    (repo / rel).parent.mkdir(parents=True)
    (repo / rel).write_text("old\n", encoding="utf-8")
    for tool in ("Write", "StrReplace", "Delete"):
        payload = {
            "tool_name": tool,
            "tool_input": {"path": rel},
            "cwd": str(repo),
            "status": "Design",
        }
        result = decide(
            payload,
            status_provider=SILENT,
            resolve_fn=lambda *a, **k: {
                "q": "Design",
                "q_git": "card-612-process-event",
                "bound_card": "612",
            },
        )
        assert result["permission"] == "deny", tool
        assert "sidecar" in result["agent_message"]


def test_python_c_sidecar_command_denied():
    payload = {
        "command": "python -c \"open('openspec/changes/card-612-process-event/.design-digest','w').write('x')\"",
        "cwd": "/",
        "status": "Design",
    }
    result = decide(payload, status_provider=SILENT)
    assert result["permission"] == "deny"
    assert "sidecar" in result["agent_message"]


def test_card_hash_prefix_matches_branch():
    mover = FakeMover()
    out = process_event(
        "iniciar_apply",
        card="#612",
        status="Pronto para Dev",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        digest_changed=False,
        g_design=True,
    )
    assert out["result"] == "transition"
    assert out["to"] == "Em desenvolvimento"


def test_mover_failure_returns_json_reject():
    class Boom(FakeMover):
        def set_status(self, issue_number: int, to: str) -> None:
            raise RuntimeError("item-edit failed")

    out = process_event(
        "iniciar_apply",
        status="Pronto para Dev",
        q_git="card-612-process-event",
        bound_card="612",
        mover=Boom(),
        digest_changed=False,
        g_design=True,
    )
    assert out["result"] == "reject"
    assert out["reason"] == "move_failed"


def test_load_fsm_still_valid():
    assert load_fsm()["fail_closed_asymmetric"] is True


def _t14_kwargs(**extra):
    payload = {
        "status": "QA",
        "q_git": "card-612-process-event",
        "bound_card": "612",
        "digest_changed": False,
        "checks_green": True,
    }
    payload.update(extra)
    return payload


def test_integrar_develop_measurer_false_skips_runner():
    mover = FakeMover()
    runner = RecordingT14Runner()
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        checks_green=None,
        checks_green_measurer=lambda *a, **k: False,
        **{k: v for k, v in _t14_kwargs().items() if k != "checks_green"},
    )
    assert out["result"] == "reject"
    assert mover.calls == []
    assert runner.calls == []


def test_integrar_develop_runner_ok_moves_done():
    mover = FakeMover()
    runner = RecordingT14Runner()
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        **_t14_kwargs(),
    )
    assert out["result"] == "transition"
    assert out["to"] == "Done"
    assert runner.calls == ["squash", "sync_dev_source", "restart", "comment_done"]
    assert mover.calls == [(612, "Done")]


def test_integrar_develop_sync_failure_is_i8():
    mover = FakeMover()
    runner = RecordingT14Runner(fail_at="sync_dev_source")
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        **_t14_kwargs(),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "I8"
    assert out.get("message")
    assert mover.calls == []
    assert runner.calls == ["squash", "sync_dev_source"]


def test_integrar_develop_restart_failure_is_i8():
    mover = FakeMover()
    runner = RecordingT14Runner(fail_at="restart")
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        **_t14_kwargs(),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "I8"
    assert out.get("message")
    assert mover.calls == []
    assert runner.calls == ["squash", "sync_dev_source", "restart"]


def test_integrar_develop_comment_done_failure_is_i8():
    mover = FakeMover()
    runner = RecordingT14Runner(fail_at="comment_done")
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        **_t14_kwargs(),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "I8"
    assert out.get("message")
    assert mover.calls == []
    assert "comment_done" in runner.calls
    assert mover.calls == []


def test_integrar_develop_classifier_no_pr():
    mover = FakeMover()
    runner = RecordingT14Runner()
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        checks_green=None,
        checks_green_classifier=lambda *a, **k: {"ok": False, "reason": "no_pr"},
        **{k: v for k, v in _t14_kwargs().items() if k != "checks_green"},
    )
    assert out["result"] == "reject"
    assert out["reason"] == "no_pr"
    assert mover.calls == []
    assert runner.calls == []


def test_integrar_develop_classifier_pending():
    mover = FakeMover()
    runner = RecordingT14Runner()
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        checks_green=None,
        checks_green_classifier=lambda *a, **k: {"ok": False, "reason": "qa-gate pending"},
        **{k: v for k, v in _t14_kwargs().items() if k != "checks_green"},
    )
    assert out["reason"] == "qa-gate pending"
    assert mover.calls == []
    assert runner.calls == []


def test_integrar_develop_classifier_failed():
    mover = FakeMover()
    runner = RecordingT14Runner()
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        checks_green=None,
        checks_green_classifier=lambda *a, **k: {"ok": False, "reason": "qa-gate failed"},
        **{k: v for k, v in _t14_kwargs().items() if k != "checks_green"},
    )
    assert out["reason"] == "qa-gate failed"
    assert mover.calls == []
    assert runner.calls == []


def test_integrar_develop_classifier_ok_moves_done():
    mover = FakeMover()
    runner = RecordingT14Runner()
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        checks_green=None,
        checks_green_classifier=lambda *a, **k: {"ok": True, "reason": None},
        **{k: v for k, v in _t14_kwargs().items() if k != "checks_green"},
    )
    assert out["result"] == "transition"
    assert out["to"] == "Done"
    assert runner.calls == ["squash", "sync_dev_source", "restart", "comment_done"]
    assert mover.calls == [(612, "Done")]


def test_integrar_develop_dirty_is_visible():
    """#798: dirty ⇒ reason=sync: dirty + path + porcelain; no move."""
    class Dirty(RecordingT14Runner):
        def sync_dev_source(self) -> None:
            self.calls.append("sync_dev_source")
            raise T14Error("sync: dirty /tmp/canonical-dev\n?? dirt.txt")

    mover = FakeMover()
    runner = Dirty()
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        **_t14_kwargs(),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "sync: dirty"
    assert "/tmp/canonical-dev" in (out.get("message") or "")
    assert "dirt.txt" in (out.get("message") or "")
    assert mover.calls == []
    assert runner.calls == ["squash", "sync_dev_source"]


def test_integrar_develop_missing_runner_never_moves():
    mover = FakeMover()
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=None,
        **_t14_kwargs(),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "I8"
    assert mover.calls == []


def test_integrar_develop_dry_run_skips_runner_and_mover():
    mover = FakeMover()
    runner = RecordingT14Runner()
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        dry_run=True,
        **_t14_kwargs(),
    )
    assert out["result"] == "transition"
    assert out["to"] == "Done"
    assert runner.calls == []
    assert mover.calls == []


def test_integrar_develop_oserror_is_i8():
    class Boom(RecordingT14Runner):
        def squash(self, *, q_git: str, bound_card: str) -> None:
            raise OSError("gh missing")

    mover = FakeMover()
    out = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=Boom(),
        **_t14_kwargs(),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "I8"
    assert out.get("message")
    assert mover.calls == []


def test_cli_has_no_checks_green_flag():
    from process_event import main

    with pytest.raises(SystemExit) as exc:
        main(["integrar_develop", "--checks-green"])
    assert exc.value.code != 0


def _status_of(mapping: dict[str, str | None]):
    def inner(bound: str | None) -> str | None:
        return mapping.get(str(bound) if bound is not None else "")

    return inner


def _t16_kwargs(**extra):
    payload = {
        "status": "Homologado",
        "q_git": "develop",
        "bound_card": UNBOUND,
        "package_cards": [617, 618],
        "m_lote": True,
        "status_provider": _status_of({"617": "Homologado", "618": "Homologado"}),
    }
    payload.update(extra)
    return payload


def test_fechar_release_rejects_without_m_lote():
    from t16 import RecordingT16Closer

    mover = FakeMover()
    closer = RecordingT16Closer()
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=closer,
        m_lote=None,
        m_lote_measurer=lambda: False,
        **{k: v for k, v in _t16_kwargs().items() if k != "m_lote"},
    )
    assert out["result"] == "reject"
    assert str(out["reason"] or "").startswith("guard:")
    assert "covenant-flow-environments" in (out.get("message") or "")
    assert "release-guard" in (out.get("message") or "")
    assert mover.calls == []
    assert closer.calls == []


def test_fechar_release_measurer_absent_is_guard():
    from t16 import RecordingT16Closer

    mover = FakeMover()
    closer = RecordingT16Closer()
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=closer,
        m_lote=None,
        m_lote_measurer=None,
        **{k: v for k, v in _t16_kwargs().items() if k != "m_lote"},
    )
    assert out["result"] == "reject"
    assert str(out["reason"] or "").startswith("guard:")
    assert mover.calls == []
    assert closer.calls == []


def test_fechar_release_post_pass_closes_package():
    from t16 import RecordingT16Closer

    mover = FakeMover()
    closer = RecordingT16Closer()
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=closer,
        **_t16_kwargs(),
    )
    assert out["result"] == "transition"
    assert out["to"] == "Pronto"
    assert closer.calls == ["comment_pronto", "comment_pronto"]
    assert closer.cards == ["617", "618"]
    assert mover.calls == [(617, "Pronto"), (618, "Pronto")]


def test_fechar_release_member_done_is_i9():
    from t16 import RecordingT16Closer

    mover = FakeMover()
    closer = RecordingT16Closer()
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=closer,
        **_t16_kwargs(status_provider=_status_of({"617": "Homologado", "618": "Done"})),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "I9"
    assert mover.calls == []
    assert closer.calls == []


def test_fechar_release_skips_already_pronto():
    from t16 import RecordingT16Closer

    mover = FakeMover()
    closer = RecordingT16Closer()
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=closer,
        **_t16_kwargs(status_provider=_status_of({"617": "Homologado", "618": "Pronto"})),
    )
    assert out["result"] == "transition"
    assert out["to"] == "Pronto"
    assert closer.cards == ["617"]
    assert mover.calls == [(617, "Pronto")]


def test_fechar_release_missing_closer_is_i9():
    mover = FakeMover()
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=None,
        **_t16_kwargs(),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "I9"
    assert mover.calls == []


def test_fechar_release_comment_failure_is_i9():
    from t16 import RecordingT16Closer

    mover = FakeMover()
    closer = RecordingT16Closer(fail_at="comment_pronto")
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=closer,
        **_t16_kwargs(),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "I9"
    assert mover.calls == []


def test_fechar_release_unbound_develop_evaluates():
    from t16 import RecordingT16Closer

    mover = FakeMover()
    closer = RecordingT16Closer()
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=closer,
        **_t16_kwargs(),
    )
    assert out["result"] == "transition"
    assert mover.calls[0][0] == 617


def test_fechar_release_unbound_non_lote_git_rejected():
    mover = FakeMover()
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=None,
        **_t16_kwargs(q_git="main"),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "unbound"
    assert mover.calls == []


def test_iniciar_apply_unbound_still_rejected():
    mover = FakeMover()
    out = process_event(
        "iniciar_apply",
        status="Pronto para Dev",
        q_git="develop",
        bound_card=UNBOUND,
        mover=mover,
        digest_changed=False,
        g_design=True,
    )
    assert out["result"] == "reject"
    assert out["reason"] == "unbound"
    assert mover.calls == []


def test_fechar_release_dry_run_skips_closer_and_mover():
    from t16 import RecordingT16Closer

    mover = FakeMover()
    closer = RecordingT16Closer()
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=closer,
        dry_run=True,
        **_t16_kwargs(),
    )
    assert out["result"] == "transition"
    assert out["to"] == "Pronto"
    assert closer.calls == []
    assert mover.calls == []


def test_homologar_still_rejected():
    mover = FakeMover()
    out = process_event(
        "homologar",
        status="Done",
        q_git="card-612-process-event",
        bound_card="612",
        mover=mover,
        status_provider=SILENT,
    )
    assert out["result"] == "reject"
    assert mover.calls == []


def test_nao_homologar_rejected_mover_empty():
    assert "nao_homologar" in HUMAN_EVENTS
    mover = FakeMover()
    out = process_event(
        "nao_homologar",
        status="Done",
        q_git="card-859-devolver-homologacao",
        bound_card="859",
        mover=mover,
        status_provider=SILENT,
    )
    assert out["result"] == "reject"
    assert out["state"] == "Done"
    assert out.get("to") is None
    assert mover.calls == []


def test_fechar_release_invalid_release_cards_is_i9(monkeypatch):
    from t16 import RecordingT16Closer

    monkeypatch.setenv("RELEASE_CARDS", "617,61O")
    mover = FakeMover()
    closer = RecordingT16Closer()
    out = process_event(
        "fechar_release",
        status="Homologado",
        q_git="card-652-t16-live-fechar-release",
        bound_card="652",
        package_cards=None,
        m_lote=True,
        mover=mover,
        t16_closer=closer,
        status_provider=_status_of({"652": "Homologado"}),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "I9"
    assert mover.calls == []
    assert closer.calls == []


def test_cli_has_no_m_lote_flag():
    from process_event import main

    with pytest.raises(SystemExit) as exc:
        main(["fechar_release", "--m-lote"])
    assert exc.value.code != 0


G1_INCLUDE = """HTTP/2 200
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 2026-09-03T02:55:52Z
X-RateLimit-Resource: graphql

{"data":null,"errors":[{"type":"RATE_LIMIT","message":"API rate limit exceeded"}]}
"""


def test_g11_item_id_rate_limit_is_not_not_on_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess as sp

    from graphql_quota import GraphQLQuotaError
    from process_event import _item_id_for_issue

    cache = tmp_path / "quota.json"
    monkeypatch.setenv("PROCESS_FSM_GRAPHQL_QUOTA_CACHE", str(cache))
    monkeypatch.setattr("process_event.load_overlay", lambda *a, **k: {"ok": True})
    monkeypatch.setattr("process_event.repo_owner_name", lambda o: ("oalansilva", "crypto"))
    monkeypatch.setattr("process_event.board_owner_number", lambda o: ("oalansilva", 1))

    def fake_run(argv, **kwargs):
        return sp.CompletedProcess(argv, 0, stdout=G1_INCLUDE, stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)
    with pytest.raises(GraphQLQuotaError) as excinfo:
        _item_id_for_issue(820)
    assert excinfo.value.remaining == 0
    assert "not on Project" not in str(excinfo.value)


def test_g11_process_event_quota_is_not_unbound(tmp_path: Path) -> None:
    from graphql_quota import GraphQLQuotaError

    mover = FakeMover()

    def quota(_bound: str | None) -> str | None:
        raise GraphQLQuotaError(0, "2026-09-03T02:55:52Z")

    out = process_event(
        "aceitar_sha",
        card="820",
        q_git="card-820-graphql-quota-rest",
        bound_card="820",
        mover=mover,
        status_provider=quota,
        pr_lister=lambda q_git: [{"number": 1, "headRefOid": "abc"}],
    )
    assert out["result"] == "reject"
    assert out["reason"] == "graphql_quota"
    assert out["reason"] != "unbound"
    assert "not on Project" not in (out.get("message") or "")
    assert "2026-09-03T02:55:52Z" in (out.get("message") or "")
    assert mover.calls == []


def test_g12_aceitar_sha_second_invocation_skips_graphql(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from graphql_quota import parse_include_output, write_cache

    import subprocess as sp

    cache = tmp_path / "quota.json"
    monkeypatch.setenv("PROCESS_FSM_GRAPHQL_QUOTA_CACHE", str(cache))
    write_cache(parse_include_output(G1_INCLUDE))
    monkeypatch.setenv("PROCESS_FSM_GRAPHQL_QUOTA_NOW", "2026-09-03T01:00:00Z")
    real_run = sp.run

    def wrapped(argv, *args, **kwargs):
        cmd0 = str(argv[0]) if argv else ""
        if cmd0 == "gh" or cmd0.endswith("/gh"):
            raise AssertionError(f"graphql called: {argv}")
        return real_run(argv, *args, **kwargs)

    monkeypatch.setattr("subprocess.run", wrapped)
    mover = FakeMover()
    first = process_event(
        "aceitar_sha",
        card="820",
        q_git="card-820-graphql-quota-rest",
        bound_card="820",
        mover=mover,
        pr_lister=lambda q_git: [{"number": 1, "headRefOid": "abc"}],
    )
    second = process_event(
        "aceitar_sha",
        card="820",
        q_git="card-820-graphql-quota-rest",
        bound_card="820",
        mover=mover,
        pr_lister=lambda q_git: [{"number": 1, "headRefOid": "abc"}],
    )
    assert first["reason"] == "graphql_quota"
    assert second["reason"] == "graphql_quota"
    assert mover.calls == []


def test_item_edit_rate_limit_updates_cache_not_move_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import subprocess as sp

    from graphql_quota import GraphQLQuotaError, load_cache
    from process_event import GhBoardMover

    cache = tmp_path / "quota.json"
    monkeypatch.setenv("PROCESS_FSM_GRAPHQL_QUOTA_CACHE", str(cache))
    monkeypatch.setattr("process_event.load_overlay", lambda *a, **k: {"ok": True})
    monkeypatch.setattr("process_event.repo_owner_name", lambda o: ("oalansilva", "crypto"))
    monkeypatch.setattr("process_event.board_owner_number", lambda o: ("oalansilva", 1))
    monkeypatch.setattr("process_event.status_options", lambda o: {"QA": "opt"})
    monkeypatch.setattr("process_event.status_field_id", lambda o: "field")
    monkeypatch.setattr("process_event.board_project_id", lambda o: "proj")
    monkeypatch.setattr("process_event._item_id_for_issue", lambda n: "ITEM")

    debug = (
        "* Response from https://api.github.com/graphql\n"
        "< HTTP/2.0 200 OK\n"
        "< X-RateLimit-Remaining: 0\n"
        "< X-RateLimit-Reset: 2026-09-03T02:55:52Z\n"
        "< X-RateLimit-Resource: graphql\n"
    )

    def fake_run(argv, **kwargs):
        return sp.CompletedProcess(argv, 1, stdout="", stderr=debug)

    monkeypatch.setattr("subprocess.run", fake_run)
    mover = GhBoardMover()
    with pytest.raises(GraphQLQuotaError) as excinfo:
        mover.set_status(820, "QA")
    assert excinfo.value.remaining == 0
    stored = load_cache()
    assert stored is not None
    assert stored["remaining"] == 0
    assert stored["source"] == "graphql-headers"
