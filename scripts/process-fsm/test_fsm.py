from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from fsm import (  # noqa: E402
    YAML_PATH,
    EvalContext,
    ValidationError,
    evaluate,
    load_fsm,
    validate_fsm,
)

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


@pytest.fixture()
def fsm():
    data = load_fsm()
    validate_fsm(data)
    return data


def test_canonical_yaml_validates(fsm):
    assert fsm["fail_closed_asymmetric"] is True
    assert "write_produto" not in fsm["illegal_events"]
    assert "request_implement" in fsm["illegal_events"]


def _legal_ctx(state, event, actor) -> EvalContext:
    kwargs: dict = {"state": state, "event": event, "actor": actor}
    if event == "iniciar_apply":
        kwargs.update(q_git="card-612-process-event", digest_changed=False)
    elif event == "pedir_review":
        kwargs.update(digest_changed=False)
    elif event == "submeter_design":
        kwargs.update(g_design=True)
    elif event == "achar_bloqueante":
        kwargs.update(open_p0_p1=True)
    elif event == "aceitar_sha":
        kwargs.update(reviewers_ok=True)
    elif event == "rerun_infra":
        kwargs.update(flaky_infra=True)
    elif event == "falha_codigo":
        kwargs.update(source_failure=True)
    elif event == "integrar_develop":
        kwargs.update(checks_green=True)
    elif event == "fechar_release":
        kwargs.update(m_lote=True)
    elif event == "invalidar_aprovacao":
        kwargs.update(digest_changed=True)
    return EvalContext(**kwargs)


@pytest.mark.parametrize(
    "tid,state,event,actor,dest",
    [
        ("T0", None, "criar_card", "Agent", "Em Refinamento"),
        ("T1", "Em Refinamento", "priorizar", "Alan", "Todo"),
        ("T2", "Todo", "cancelar", "Alan", "Cancelado"),
        ("T3", "Todo", "iniciar_design", "Agent", "Design"),
        ("T4", "Design", "recriticar", "Agent", "Design"),
        ("T5", "Design", "submeter_design", "Agent", "Aprovação de Design"),
        ("T6", "Aprovação de Design", "devolver_design", "Alan", "Design"),
        ("T7", "Aprovação de Design", "aprovar_design", "Alan", "Pronto para Dev"),
        ("T8", "Pronto para Dev", "iniciar_apply", "Agent", "Em desenvolvimento"),
        ("T9", "Em desenvolvimento", "pedir_review", "Agent", "Code Review"),
        ("T10", "Code Review", "achar_bloqueante", "Agent", "Em desenvolvimento"),
        ("T11", "Code Review", "aceitar_sha", "Agent", "QA"),
        ("T12", "QA", "rerun_infra", "Agent", "QA"),
        ("T13", "QA", "falha_codigo", "CI", "Em desenvolvimento"),
        ("T14", "QA", "integrar_develop", "Agent", "Done"),
        ("T15", "Done", "homologar", "Alan", "Homologado"),
        ("T16", "Homologado", "fechar_release", "Agent", "Pronto"),
        ("T17a", "Pronto para Dev", "invalidar_aprovacao", "Guard", "Design"),
        ("T17b", "Em desenvolvimento", "invalidar_aprovacao", "Guard", "Design"),
    ],
)
def test_legal_transitions(fsm, tid, state, event, actor, dest):
    result = evaluate(fsm, _legal_ctx(state, event, actor))
    assert result.result == "transition"
    assert result.to == dest
    assert result.reason == tid
    assert result.state == state


def test_i1_write_allowed(fsm):
    result = evaluate(
        fsm,
        EvalContext(
            state="Em desenvolvimento",
            event="write_produto",
            actor="Agent",
            q_git="card-609-process-fsm-yaml",
            bound_card="609",
            path="backend/app/main.py",
        ),
    )
    assert result.result == "allow"
    assert result.state == "Em desenvolvimento"


def test_todo_write_reject(fsm):
    result = evaluate(
        fsm,
        EvalContext(state="Todo", event="write_produto", actor="Agent", q_git="card-609-x", bound_card="609"),
    )
    assert result.result == "reject"
    assert result.state == "Todo"
    assert result.to is None


def test_develop_write_reject(fsm):
    result = evaluate(
        fsm,
        EvalContext(
            state="Em desenvolvimento",
            event="write_produto",
            q_git="develop",
            bound_card="609",
        ),
    )
    assert result.result == "reject"


def test_done_write_reject(fsm):
    result = evaluate(fsm, EvalContext(state="Done", event="write_produto", bound_card="609", q_git="card-609-x"))
    assert result.result == "reject"
    assert result.state == "Done"


def test_human_gate_rejects_missing_actor(fsm):
    result = evaluate(fsm, EvalContext(state="Aprovação de Design", event="aprovar_design", actor=None))
    assert result.result == "reject"
    result = evaluate(
        fsm,
        EvalContext(state="Aprovação de Design", event="aprovar_design", actor="Agent"),
    )
    assert result.result == "reject"
    assert result.state == "Aprovação de Design"


def test_unbound_write_reject(fsm):
    result = evaluate(
        fsm,
        EvalContext(state="Em desenvolvimento", event="write_produto", q_git="card-609-x", bound_card=None),
    )
    assert result.result == "reject"


def test_request_implement_not_a_transition(fsm):
    assert all(row["event"] != "request_implement" for row in fsm["transitions"])
    result = evaluate(fsm, EvalContext(state="Todo", event="request_implement", actor="Alan"))
    assert result.result == "reject"


def _dump(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "process-fsm.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_missing_t7_alan_fails(tmp_path, fsm):
    data = copy.deepcopy(fsm)
    for row in data["transitions"]:
        if row["id"] == "T7":
            row["actor"] = "Agent"
    path = _dump(tmp_path, data)
    with pytest.raises(ValidationError, match="T7"):
        validate_fsm(load_fsm(path))


@pytest.mark.parametrize("tid", ["T1", "T15"])
def test_missing_alan_on_human_gates_fails(tmp_path, fsm, tid):
    data = copy.deepcopy(fsm)
    for row in data["transitions"]:
        if row["id"] == tid:
            row["actor"] = "Agent"
    path = _dump(tmp_path, data)
    with pytest.raises(ValidationError, match=tid):
        validate_fsm(load_fsm(path))


def test_t16_alan_only_fails(tmp_path, fsm):
    data = copy.deepcopy(fsm)
    for row in data["transitions"]:
        if row["id"] == "T16":
            row["actor"] = "Alan"
    path = _dump(tmp_path, data)
    with pytest.raises(ValidationError, match="T16"):
        validate_fsm(load_fsm(path))


def test_t16_missing_agent_fails(tmp_path, fsm):
    data = copy.deepcopy(fsm)
    for row in data["transitions"]:
        if row["id"] == "T16":
            row["actor"] = "Guard"
    path = _dump(tmp_path, data)
    with pytest.raises(ValidationError, match="T16"):
        validate_fsm(load_fsm(path))


def test_overlapping_qa_same_event_fails(tmp_path, fsm):
    data = copy.deepcopy(fsm)
    extra = copy.deepcopy(next(row for row in data["transitions"] if row["id"] == "T14"))
    extra["id"] = "T14-dup"
    extra["exclusive_group"] = None
    extra["guard"] = None
    data["transitions"].append(extra)
    path = _dump(tmp_path, data)
    with pytest.raises(ValidationError, match="overlapping"):
        validate_fsm(load_fsm(path))


def test_write_produto_in_illegal_events_fails(tmp_path, fsm):
    data = copy.deepcopy(fsm)
    data["illegal_events"] = list(data["illegal_events"]) + ["write_produto"]
    path = _dump(tmp_path, data)
    with pytest.raises(ValidationError, match="write_produto"):
        validate_fsm(load_fsm(path))


def test_sigma_drift_fails(tmp_path, fsm):
    data = copy.deepcopy(fsm)
    data["transitions"] = [row for row in data["transitions"] if row["id"] != "T3"]
    path = _dump(tmp_path, data)
    with pytest.raises(ValidationError):
        validate_fsm(load_fsm(path))


def test_yaml_path_is_repo_cursor_file():
    assert YAML_PATH.name == "process-fsm.yaml"
    assert YAML_PATH.is_file()


def test_t8_develop_git_rejected(fsm):
    result = evaluate(
        fsm,
        EvalContext(
            state="Pronto para Dev",
            event="iniciar_apply",
            actor="Agent",
            q_git="develop",
            digest_changed=False,
        ),
    )
    assert result.result == "reject"
    assert result.to is None
    assert result.reason == "guard:q_git_card"


def test_t8_digest_changed_is_i4_not_t8(fsm):
    result = evaluate(
        fsm,
        EvalContext(
            state="Pronto para Dev",
            event="iniciar_apply",
            actor="Agent",
            q_git="card-612-x",
            digest_changed=True,
        ),
    )
    assert result.result == "reject"
    assert result.reason == "I4"
    assert result.to is None


def test_t9_digest_missing_is_i4(fsm):
    result = evaluate(
        fsm,
        EvalContext(state="Em desenvolvimento", event="pedir_review", actor="Agent", digest_changed=None),
    )
    assert result.result == "reject"
    assert result.reason == "I4"


def test_t16_without_m_lote_rejected(fsm):
    result = evaluate(
        fsm,
        EvalContext(state="Homologado", event="fechar_release", actor="Agent", m_lote=False),
    )
    assert result.result == "reject"
    assert result.reason == "guard:M_lote"


def test_t17_agent_rejected_guard_transitions(fsm):
    agent = evaluate(
        fsm,
        EvalContext(
            state="Pronto para Dev",
            event="invalidar_aprovacao",
            actor="Agent",
            digest_changed=True,
        ),
    )
    assert agent.result == "reject"
    assert agent.reason == "actor"
    guard = evaluate(
        fsm,
        EvalContext(
            state="Pronto para Dev",
            event="invalidar_aprovacao",
            actor="Guard",
            digest_changed=True,
        ),
    )
    assert guard.result == "transition"
    assert guard.to == "Design"
    assert guard.reason == "T17a"


def test_t17b_from_em_desenvolvimento(fsm):
    result = evaluate(
        fsm,
        EvalContext(
            state="Em desenvolvimento",
            event="invalidar_aprovacao",
            actor="Guard",
            digest_changed=True,
        ),
    )
    assert result.result == "transition"
    assert result.to == "Design"
    assert result.reason == "T17b"
