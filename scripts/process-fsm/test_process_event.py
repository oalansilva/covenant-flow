from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from test_overlay_fixtures import FIELD_ID, filled_overlay_dict, write_overlay  # noqa: E402
import design_clone_gate  # noqa: E402
from model_selection_fixtures import machine_models  # noqa: E402, F401
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


def test_criar_card_not_implemented_without_executor():
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
        def move(self, issue_number, evento, de, para, ator, extras=None) -> None:
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


def test_integrar_develop_retry_after_squash_only_moves():
    """D9: first T14 squashes and closes out but the executor refuses; the retry only asks the move."""
    from process_event import MoveRefused

    class FlakyMover(FakeMover):
        def __init__(self) -> None:
            super().__init__()
            self.refuse = True

        def move(self, issue_number, evento, de, para, ator, extras=None):  # noqa: ANN001
            if self.refuse:
                self.refuse = False
                self.requests.append({"issue": issue_number, "evento": evento, "de": de, "para": para, "refused": True})
                raise MoveRefused("indisponivel", "executor indisponível")
            super().move(issue_number, evento, de, para, ator, extras)

    mover = FlakyMover()
    runner = RecordingT14Runner()
    first = process_event("integrar_develop", mover=mover, t14_runner=runner, **_t14_kwargs())
    assert first["result"] == "reject"
    assert first["reason"] == "executor:indisponivel"
    assert runner.calls == ["squash", "sync_dev_source", "restart", "comment_done"]
    assert mover.calls == []

    classified: list[str] = []

    def no_pr(*_a, **_k):  # noqa: ANN002, ANN003
        classified.append("no_pr")
        return {"ok": False, "reason": "no_pr"}

    second = process_event(
        "integrar_develop",
        mover=mover,
        t14_runner=runner,
        checks_green=None,
        checks_green_classifier=no_pr,
        **{k: v for k, v in _t14_kwargs().items() if k != "checks_green"},
    )
    assert second["result"] == "transition"
    assert second["to"] == "Done"
    assert runner.calls == ["squash", "sync_dev_source", "restart", "comment_done"]
    assert classified == []
    assert mover.calls == [(612, "Done")]
    assert mover.requests[-1]["evento"] == "integrar_develop" and mover.requests[-1]["de"] == "QA"


def test_integrar_develop_retry_after_partial_closeout_reruns_it():
    """A sync failure after the squash is not a closed T14: the retry runs the closeout again."""
    mover = FakeMover()
    runner = RecordingT14Runner(fail_at="sync_dev_source")
    first = process_event("integrar_develop", mover=mover, t14_runner=runner, **_t14_kwargs())
    assert first["reason"] == "I8"
    runner.fail_at = None
    second = process_event("integrar_develop", mover=mover, t14_runner=runner, **_t14_kwargs())
    assert second["result"] == "transition"
    assert runner.calls == ["squash", "sync_dev_source", "squash", "sync_dev_source", "restart", "comment_done"]
    assert mover.calls == [(612, "Done")]


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
        m_lote_measurer=lambda **_k: False,
        **{k: v for k, v in _t16_kwargs().items() if k != "m_lote"},
    )
    assert out["result"] == "reject"
    assert str(out["reason"] or "").startswith("guard:")
    assert "covenant-flow-environments" in (out.get("message") or "")
    assert "release-guard" in (out.get("message") or "")
    assert mover.calls == []
    assert closer.calls == []


def test_fechar_release_message_includes_post_blockers():
    from t16 import LoteMeasurement, RecordingT16Closer

    mover = FakeMover()
    closer = RecordingT16Closer()
    measurement = LoteMeasurement(
        ok=False,
        blockers=("OpenSpec completed change of Homologado package card is still active",),
        fail_class="post_failed",
    )
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=closer,
        m_lote=None,
        m_lote_measurer=lambda **_k: measurement,
        **{k: v for k, v in _t16_kwargs().items() if k != "m_lote"},
    )
    assert out["result"] == "reject"
    assert out["reason"] == "guard:M_lote"
    assert "OpenSpec completed change of Homologado package card is still active" in (
        out.get("message") or ""
    )
    assert "fail_class=post_failed" in (out.get("message") or "")
    assert mover.calls == []
    assert closer.calls == []


def test_fechar_release_raw_env_same_context_post_pass_is_accepted(monkeypatch):
    import os
    import subprocess

    from t16 import RecordingT16Closer, measure_m_lote

    monkeypatch.setenv("RELEASE_CARDS", " 0617, 618 ")
    workdir = ROOT.parents[1]
    seen: dict[str, object] = {}

    def measurer(*, cwd=None, package=None, **_k):
        seen["cwd"] = cwd
        seen["package"] = package
        return measure_m_lote(
            cwd=cwd,
            package=package,
            runner=lambda *a, **k: subprocess.CompletedProcess(
                ["scripts/release-guard", "post"], 0, "", ""
            ),
        )

    mover = FakeMover()
    closer = RecordingT16Closer()
    extra = {k: v for k, v in _t16_kwargs().items() if k not in {"m_lote", "package_cards"}}
    out = process_event(
        "fechar_release",
        cwd=workdir,
        mover=mover,
        t16_closer=closer,
        m_lote=None,
        m_lote_measurer=measurer,
        package_cards=None,
        **extra,
    )
    assert seen["package"] == "617,618"
    assert Path(seen["cwd"]).resolve() == workdir.resolve()
    assert os.environ["RELEASE_CARDS"] == " 0617, 618 "
    assert out["result"] == "transition"
    assert out["to"] == "Pronto"
    assert mover.calls == [(617, "Pronto"), (618, "Pronto")]
    assert closer.cards == ["617", "618"]


def test_fechar_release_card_without_env_same_context_post_pass_is_accepted(monkeypatch):
    import subprocess

    from t16 import RecordingT16Closer, measure_m_lote

    monkeypatch.delenv("RELEASE_CARDS", raising=False)
    workdir = ROOT.parents[1]
    seen: dict[str, object] = {}

    def measurer(*, cwd=None, package=None, **_k):
        seen["cwd"] = cwd
        seen["package"] = package
        return measure_m_lote(
            cwd=cwd,
            package=package,
            runner=lambda *a, **k: subprocess.CompletedProcess(
                ["scripts/release-guard", "post"], 0, "", ""
            ),
        )

    mover = FakeMover()
    closer = RecordingT16Closer()
    out = process_event(
        "fechar_release",
        cwd=workdir,
        card="617",
        mover=mover,
        t16_closer=closer,
        m_lote=None,
        m_lote_measurer=measurer,
        status="Homologado",
        q_git="develop",
        bound_card=UNBOUND,
        package_cards=None,
        status_provider=_status_of({"617": "Homologado"}),
    )
    assert seen["package"] == "617"
    assert Path(seen["cwd"]).resolve() == workdir.resolve()
    assert out["result"] == "transition"
    assert out["to"] == "Pronto"
    assert mover.calls == [(617, "Pronto")]
    assert closer.cards == ["617"]


def test_fechar_release_refuses_pass_from_other_context():
    from release_closeout import ContextIdentity
    from t16 import RecordingT16Closer

    mover = FakeMover()
    closer = RecordingT16Closer()
    other = ContextIdentity(
        package="617,618",
        cwd="/tmp/other-worktree",
        head="deadbeef",
        refs=("origin/develop=aaaa",),
        branch="release-2026-09-27",
    )
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=closer,
        lote_pass_context=other,
        **_t16_kwargs(),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "guard:M_lote"
    assert "context divergence" in (out.get("message") or "")
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
    assert out["reason"] == "guard:lote_git"
    assert "develop" in out.get("message", "")
    assert "release-*" in out.get("message", "")
    assert mover.calls == []


@pytest.mark.parametrize("q_git", ["docs-release-2026-07-01", "sync-main-develop"])
def test_fechar_release_wrong_lote_git_docs_or_sync_rejected(q_git: str):
    mover = FakeMover()
    out = process_event(
        "fechar_release",
        mover=mover,
        t16_closer=None,
        **_t16_kwargs(q_git=q_git),
    )
    assert out["result"] == "reject"
    assert out["reason"] == "guard:lote_git"
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

import process_event as pe


@pytest.fixture
def unavailable_codex_stage(monkeypatch):
    import account_registration
    import codex_evidence

    monkeypatch.setenv("CODEX_THREAD_ID", "codex-i4-fixture")
    calls = {"registration": [], "stage": []}
    monkeypatch.setattr(
        account_registration, "require_active",
        lambda client, root: calls["registration"].append((client, root)),
    )

    def unavailable(**kwargs):
        calls["stage"].append(kwargs)
        raise codex_evidence.EvidenceError("stage_capability_missing", "fixture: missing context isolation")

    monkeypatch.setattr(codex_evidence, "preflight", unavailable)
    return calls


def approved_i4_change(tmp_path, *, changed=True):
    change = tmp_path / "openspec" / "changes" / "card-612-process-event"
    change.mkdir(parents=True)
    (change / "design.md").write_text("# approved design\n")
    sidecar_path(change).write_text(pe.compute_digest(change, None) + "\n")
    if changed:
        (change / "design.md").write_text("# revised design\n")
    return change


@pytest.mark.parametrize("event,state", [
    ("iniciar_apply", "Pronto para Dev"),
    ("pedir_review", "Em desenvolvimento"),
])
@pytest.mark.parametrize("dry_run", [False, True])
def test_codex_measured_i4_precedes_stage_capability_without_starting_stage(
    tmp_path, unavailable_codex_stage, event, state, dry_run,
):
    change = approved_i4_change(tmp_path)
    original_sidecar = sidecar_path(change).read_bytes()
    mover = FakeMover()
    out = process_event(
        event, card="612", change="card-612-process-event",
        resolve_fn=lambda *args, **kwargs: {"q": None, "q_git": "card-612-process-event", "bound_card": "612"},
        status_provider=lambda bound: state if bound == "612" else None,
        change_dir=change, mover=mover, dry_run=dry_run, client="codex",
    )
    assert out == {"result": "transition", "state": state, "to": "Design", "reason": "I4"}
    assert mover.calls == ([] if dry_run else [(612, "Design")])
    assert len(unavailable_codex_stage["registration"]) == 1
    assert unavailable_codex_stage["stage"] == []
    assert sidecar_path(change).read_bytes() == original_sidecar


@pytest.mark.parametrize("event,state", [
    ("iniciar_apply", "Pronto para Dev"),
    ("pedir_review", "Em desenvolvimento"),
])
def test_codex_unchanged_digest_still_requires_stage_capability(
    tmp_path, unavailable_codex_stage, event, state,
):
    change = approved_i4_change(tmp_path, changed=False)
    mover = FakeMover()
    out = process_event(
        event, card="612", status=state, q_git="card-612-process-event",
        bound_card="612", change_dir=change, mover=mover, client="codex",
    )
    assert out["reason"] == "codex_evidence:stage_capability_missing"
    assert out["result"] == "reject" and out["to"] is None and mover.calls == []
    assert unavailable_codex_stage["stage"][0]["stage"] == event


@pytest.mark.parametrize("event,state", [
    ("pedir_review", "Pronto para Dev"),
    ("iniciar_apply", "Em desenvolvimento"),
    ("pedir_review", "Done"),
    ("iniciar_apply", None),
])
def test_codex_changed_digest_wrong_state_does_not_compile_t17(
    tmp_path, unavailable_codex_stage, event, state,
):
    mover = FakeMover()
    out = process_event(
        event, card="612", status=state, q_git="card-612-process-event",
        bound_card="612", change_dir=approved_i4_change(tmp_path), mover=mover,
        status_provider=lambda bound: state, client="codex",
    )
    assert out["result"] == "reject" and out["to"] is None and mover.calls == []


@pytest.mark.parametrize("overrides,reason", [
    ({"card": "999"}, "card_mismatch"),
    ({"change": "card-999-other"}, "change_mismatch"),
    ({"q_git": "develop"}, "guard:q_git_card"),
    ({"q_git": "main"}, "guard:q_git_card"),
    ({"bound_card": "999"}, "card_mismatch"),
    ({"bound_card": None}, "unbound"),
    ({"client": "cursor"}, "codex_evidence:ambiguous_client"),
])
def test_codex_i4_preserves_identity_card_branch_and_client_checks(
    tmp_path, unavailable_codex_stage, overrides, reason,
):
    mover = FakeMover()
    kwargs = dict(
        card="612", change="card-612-process-event", status="Em desenvolvimento",
        q_git="card-612-process-event", bound_card="612",
        change_dir=approved_i4_change(tmp_path), mover=mover, client="codex",
        resolve_fn=lambda *args, **kwargs: {"q": None, "q_git": None, "bound_card": None},
    )
    kwargs.update(overrides)
    # A branch outside card-* is tested without a contradictory explicit slug.
    if overrides.get("q_git") in {"develop", "main"}:
        kwargs["change"] = None
    out = process_event("pedir_review", **kwargs)
    assert out["result"] == "reject" and out["reason"] == reason
    assert out["to"] is None and mover.calls == []
    assert unavailable_codex_stage["stage"] == []


@pytest.mark.parametrize("code", [
    "hooks_inactive", "hooks_unreviewed", "hooks_changed", "adapter_divergent",
])
def test_codex_i4_never_bypasses_hook_registration_or_trust(
    tmp_path, monkeypatch, unavailable_codex_stage, code,
):
    import account_registration

    def refused(*args, **kwargs):
        raise account_registration.RegistrationRefusal(code, "fixture registration refusal")

    monkeypatch.setattr(account_registration, "require_active", refused)
    mover = FakeMover()
    out = process_event(
        "pedir_review", card="612", status="Em desenvolvimento",
        q_git="card-612-process-event", bound_card="612",
        change_dir=approved_i4_change(tmp_path), mover=mover, client="codex",
    )
    assert out["reason"] == "codex_evidence:" + code
    assert out["result"] == "reject" and out["to"] is None and mover.calls == []
    assert unavailable_codex_stage["stage"] == []


def test_codex_i4_requires_the_existing_engine_to_authorize_guard_actor(
    tmp_path, unavailable_codex_stage,
):
    table = load_fsm()
    for transition in table["transitions"]:
        if transition["id"] == "T17b":
            transition["actor"] = "Alan"
    mover = FakeMover()
    out = process_event(
        "pedir_review", card="612", status="Em desenvolvimento",
        q_git="card-612-process-event", bound_card="612", fsm=table,
        change_dir=approved_i4_change(tmp_path), mover=mover, client="codex",
    )
    assert out["reason"] == "actor" and out["result"] == "reject"
    assert out["to"] is None and mover.calls == []
    assert unavailable_codex_stage["stage"] == []


def test_codex_cannot_call_guard_invalidation_directly(
    tmp_path, unavailable_codex_stage,
):
    mover = FakeMover()
    out = process_event(
        "invalidar_aprovacao", card="612", status="Em desenvolvimento",
        q_git="card-612-process-event", bound_card="612",
        change_dir=approved_i4_change(tmp_path), mover=mover, client="codex",
    )
    assert out["reason"] == "actor" and out["result"] == "reject"
    assert mover.calls == []

@pytest.fixture
def t5_basic_runtime(monkeypatch):
    import account_registration
    import codex_evidence

    monkeypatch.setenv("CODEX_THREAD_ID", "codex-t5-fixture")
    calls = {"registration": [], "preflight": []}
    monkeypatch.setattr(
        account_registration, "require_active",
        lambda client, root: calls["registration"].append((client, root)),
    )

    def preflight(**kwargs):
        calls["preflight"].append(kwargs)
        if kwargs.get("stage") is not None:
            raise codex_evidence.EvidenceError("stage_capability_missing", "fixture: no spawn capacity")
        return {"result": "ready", "capabilities": {"context_isolation": "unavailable"}}

    monkeypatch.setattr(codex_evidence, "preflight", preflight)
    return calls


def t5_artifacts(tmp_path):
    change = tmp_path / "openspec" / "changes" / "card-612-process-event"
    change.mkdir(parents=True)
    for name in ("proposal.md", "tasks.md"):
        (change / name).write_text("# artifact\n")
    (change / "design.md").write_text("UI impact: none\nlive_route: N/A harness-only\nsurface: new\n")
    spec = change / "specs" / "harness" / "spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("# contract\n")
    return change


def t5_request(artifact_dir, mover, **overrides):
    kwargs = dict(
        card="612", change="card-612-process-event", status="Design",
        q_git="card-612-process-event", bound_card="612",
        change_dir=artifact_dir, mover=mover, client="codex",
        resolve_fn=lambda *a, **kw: {"q": None, "q_git": None, "bound_card": None},
    )
    kwargs.update(overrides)
    return process_event("submeter_design", **kwargs)


@pytest.mark.parametrize("signal,client", [("CURSOR_AGENT", "cursor"), ("CURSOR_VERSION", "cursor"), ("CURSOR_PROJECT_DIR", "cursor"), ("OPENCODE", "opencode")])
@pytest.mark.parametrize("event", ["iniciar_design", "recriticar", "submeter_design", "iniciar_apply", "pedir_review", "aceitar_sha", "integrar_develop"])
def test_implicit_cursor_opencode_identity_cannot_bypass_account_registration(tmp_path, monkeypatch, signal, client, event):
    import account_registration
    monkeypatch.setenv(signal, "observed-host")
    seen = []
    def denied(active, root):
        seen.append((active, root))
        raise account_registration.RegistrationRefusal("hooks_unreviewed", "fixture: registration untrusted")
    monkeypatch.setattr(account_registration, "require_active", denied)
    mover = FakeMover()
    out = process_event(event, cwd=tmp_path, status="Todo", q_git="card-612-process-event", bound_card="612", mover=mover)
    assert out["result"] == "reject" and out["reason"] == client + "_registration:hooks_unreviewed"
    assert seen == [(client, tmp_path)] and mover.calls == []


def test_host_detection_keeps_explicit_client_and_innermost_precedence(tmp_path, monkeypatch):
    import process_event as pe
    import account_registration
    seen = []
    monkeypatch.setenv("CURSOR_AGENT", "1")
    monkeypatch.setenv("OPENCODE", "1")
    monkeypatch.setattr(pe, "nearest_agent_client", lambda **kw: "opencode")
    monkeypatch.setattr(account_registration, "require_active", lambda client, root: seen.append(client))
    assert pe.host_client() == "opencode"
    for explicit, expected in ((None, "opencode"), ("cursor", "cursor")):
        out = process_event("iniciar_design", cwd=tmp_path, status="Todo", q_git="card-612-process-event", bound_card="612", mover=FakeMover(), client=explicit)
        assert out["result"] == "transition" and seen[-1] == expected
    monkeypatch.setenv("COVENANT_CLIENT", "grok")
    assert process_event("iniciar_design", cwd=tmp_path, status="Todo", q_git="card-612-process-event", bound_card="612", mover=FakeMover())["result"] == "transition"
    assert seen == ["opencode", "cursor"]


@pytest.mark.parametrize("observed", [None, ("claude-opus-5-5", "high"), ("claude-sonnet-5-5", "low"), ("claude-sonnet-5-5", "high")])
def test_claude_t16_requires_observed_parent_matching_captured_execution(tmp_path, monkeypatch, machine_models, observed):
    import claude_evidence
    from model_selection import resolve as resolve_selection
    from release_model_selection import check_claude_parent
    monkeypatch.setenv("CLAUDECODE", "1")
    capture = resolve_selection("claude", "execucao", role="fecho-lote")
    def observe(**kwargs):
        if observed is None:
            raise claude_evidence.EvidenceError("runtime_unavailable", "fixture: no observed parent")
        return {"model": observed[0], "effort": observed[1]}
    monkeypatch.setattr(claude_evidence, "observe_parent", observe)
    mover = FakeMover()
    out = process_event("fechar_release", cwd=tmp_path, status="Homologado", q_git="develop", bound_card=UNBOUND,
        package_cards=[612], m_lote=False, mover=mover, parent_capture=capture, parent_checker=check_claude_parent)
    if observed == ("claude-sonnet-5-5", "high"):
        assert out["reason"] != "claude_evidence:parent_model"
    else:
        assert out["result"] == "reject" and out["reason"] == "claude_evidence:parent_model"
        assert "observed parent" in out["message"] and "captured claude/execucao" in out["message"]
    assert mover.calls == [] and out["state"] == "Homologado"


@pytest.mark.parametrize("missing", ["UI impact", "live_route", "surface"])
def test_t5_rejects_missing_parseable_contract_tokens_before_move(tmp_path, monkeypatch, missing):
    import process_event as pe
    monkeypatch.setattr(pe, "native_client", lambda: None)
    change = t5_artifacts(tmp_path)
    lines = ["UI impact: none", "live_route: N/A harness-only", "surface: new"]
    (change / "design.md").write_text("\n".join(line for line in lines if not line.startswith(missing + ":")) + "\n")
    mover = FakeMover()
    out = process_event("submeter_design", cwd=tmp_path, status="Design", q_git="card-612-process-event", bound_card="612", change_dir=change, mover=mover)
    assert out["reason"] == "guard:design_tokens" and out["result"] == "reject"
    assert missing in out["message"] and mover.calls == []
    assert not sidecar_path(change).exists()


@pytest.mark.parametrize("dry_run", [False, True])
def test_codex_t5_keeps_basic_preflight_and_only_submits_artifacts(
    tmp_path, t5_basic_runtime, dry_run,
):
    change = t5_artifacts(tmp_path)
    mover = FakeMover()
    out = t5_request(change, mover, dry_run=dry_run)
    assert out == {"result": "transition", "state": "Design", "to": "Aprovação de Design", "reason": "T5"}
    assert len(t5_basic_runtime["registration"]) == 1
    assert len(t5_basic_runtime["preflight"]) == 1
    assert t5_basic_runtime["preflight"][0]["stage"] is None
    if dry_run:
        assert mover.calls == [] and not sidecar_path(change).exists()
    else:
        assert mover.calls == [(612, "Aprovação de Design")]
        assert sidecar_path(change).read_text().strip() == pe.compute_digest(change, None)


@pytest.mark.parametrize("code", [
    "source_unavailable", "session_unavailable", "session_inactive",
    "unverified", "worktree_mismatch", "observation_unavailable", "unsupported_schema",
])
def test_codex_t5_basic_runtime_failures_still_block_submission(
    tmp_path, monkeypatch, t5_basic_runtime, code,
):
    import codex_evidence

    def refused(**kwargs):
        assert kwargs["stage"] is None
        raise codex_evidence.EvidenceError(code, "fixture basic runtime refusal")

    monkeypatch.setattr(codex_evidence, "preflight", refused)
    change = t5_artifacts(tmp_path)
    mover = FakeMover()
    out = t5_request(change, mover)
    assert out["result"] == "reject" and out["reason"] == "codex_evidence:" + code
    assert out["to"] is None and mover.calls == []
    assert not sidecar_path(change).exists()


@pytest.mark.parametrize("code", [
    "hooks_inactive", "hooks_unreviewed", "hooks_changed", "adapter_divergent",
])
def test_codex_t5_keeps_account_registration_and_operator_trust(
    tmp_path, monkeypatch, t5_basic_runtime, code,
):
    import account_registration

    def refused(*args, **kwargs):
        raise account_registration.RegistrationRefusal(code, "fixture registration refusal")

    monkeypatch.setattr(account_registration, "require_active", refused)
    change = t5_artifacts(tmp_path)
    mover = FakeMover()
    out = t5_request(change, mover)
    assert out["reason"] == "codex_evidence:" + code and out["result"] == "reject"
    assert mover.calls == [] and t5_basic_runtime["preflight"] == []
    assert not sidecar_path(change).exists()


@pytest.mark.parametrize("overrides,reason", [
    ({"card": "999"}, "card_mismatch"),
    ({"change": "card-999-other"}, "change_mismatch"),
    ({"q_git": "develop", "bound_card": None, "change": None}, "unbound"),
    ({"q_git": "main", "bound_card": None, "change": None}, "unbound"),
    ({"bound_card": None}, "unbound"),
    ({"client": "cursor"}, "codex_evidence:ambiguous_client"),
])
def test_codex_t5_rejects_invalid_identity_card_and_branch(
    tmp_path, t5_basic_runtime, overrides, reason,
):
    change = t5_artifacts(tmp_path)
    mover = FakeMover()
    out = t5_request(change, mover, **overrides)
    assert out["reason"] == reason and out["result"] == "reject"
    assert mover.calls == [] and not sidecar_path(change).exists()


@pytest.mark.parametrize("state", ["Todo", "Aprovação de Design", "Pronto para Dev", "Em desenvolvimento", "Done"])
def test_codex_t5_wrong_state_is_not_submission(tmp_path, t5_basic_runtime, state):
    change = t5_artifacts(tmp_path)
    mover = FakeMover()
    out = t5_request(change, mover, status=state)
    assert out["result"] == "reject" and out["to"] is None
    assert mover.calls == [] and not sidecar_path(change).exists()


@pytest.mark.parametrize("missing", ["proposal.md", "design.md", "tasks.md", "specs/harness/spec.md"])
def test_codex_t5_still_requires_design_artifacts(tmp_path, t5_basic_runtime, missing):
    change = t5_artifacts(tmp_path)
    (change / missing).unlink()
    mover = FakeMover()
    out = t5_request(change, mover)
    assert out["result"] == "reject" and out["reason"] == "guard:G_design"
    assert mover.calls == [] and not sidecar_path(change).exists()


def test_codex_t5_keeps_actor_gate(tmp_path, t5_basic_runtime):
    table = load_fsm()
    for transition in table["transitions"]:
        if transition["id"] == "T5":
            transition["actor"] = "Alan"
    change = t5_artifacts(tmp_path)
    mover = FakeMover()
    out = t5_request(change, mover, fsm=table)
    assert out["result"] == "reject" and out["reason"] == "actor"
    assert mover.calls == [] and not sidecar_path(change).exists()


@pytest.mark.parametrize("event,state", [
    ("iniciar_design", "Todo"),
    ("recriticar", "Design"),
    ("iniciar_apply", "Pronto para Dev"),
    ("pedir_review", "Em desenvolvimento"),
])
def test_t5_scope_does_not_relax_future_native_stage_gates(
    tmp_path, t5_basic_runtime, event, state,
):
    change = t5_artifacts(tmp_path)
    # Real fixture digest unchanged: do not take the distinct I4 invalidation route.
    sidecar_path(change).write_text(pe.compute_digest(change, None) + "\n")
    before = sidecar_path(change).read_bytes()
    mover = FakeMover()
    out = process_event(
        event, card="612", status=state, q_git="card-612-process-event",
        bound_card="612", change_dir=change, mover=mover, client="codex",
    )
    assert out["result"] == "reject" and out["reason"] == "codex_evidence:stage_capability_missing"
    assert t5_basic_runtime["preflight"][0]["stage"] == event
    assert mover.calls == [] and sidecar_path(change).read_bytes() == before
