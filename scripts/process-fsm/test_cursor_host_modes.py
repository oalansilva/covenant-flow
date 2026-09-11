"""#880: Cursor host modes (terminal vs Desktop+SSH). Needles + interrupt helper.

Sem GitHub. C1–C8 = design.md Golden cases.
P3 URI exacta (`cursor --folder-uri` vs equivalente que não dispose
InstantiationService) fica residual no runbook: MUST = janela nova / MUST NOT MCP.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md"
AGENTS = REPO / "AGENTS.md"

SUCCESS = "success"
HOST_KILL = "host_kill"
ABORT = "abort"
FAIL = "fail"
REFUSE = "refuse"

INTERRUPTED_BY_USER = "Task was interrupted by the user"


def classify_cursor_stage_child(
    *,
    host_status: str | None,
    return_payload: object | None = None,
    interrupt_message: str | None = None,
    operator_stop_visible: bool = False,
) -> str:
    """Classify a Cursor grill/Design/Apply/review/QA child host outcome.

    Success only when the host reports ``completed`` and a return payload is
    present. ``Task was interrupted by the user`` without a visible operator
    Stop in that turn is a host kill (this card's fail). Explicit Stop is an
    abort: not success; restage = new spawn, not resume of the corpse.
    Destape after completed and hang S2 stay #879 (not classified here).
    """
    status = (host_status or "").strip().lower()
    message = interrupt_message or ""
    interrupted = INTERRUPTED_BY_USER in message
    if status == "completed" and return_payload is not None:
        return SUCCESS
    if interrupted:
        if operator_stop_visible:
            return ABORT
        return HOST_KILL
    return FAIL


def parent_desktop_substitute_outcome() -> str:
    """Pai MUST NOT executar a etapa no Desktop em substituição do filho."""
    return REFUSE


def resume_corpse_outcome() -> str:
    """Operador MUST NOT retomar cadáver como filho aceite."""
    return REFUSE


def _near(text: str, left: str, right: str, window: int = 220) -> bool:
    start = 0
    while True:
        pos = text.find(left, start)
        if pos < 0:
            return False
        lo = max(0, pos - window)
        hi = min(len(text), pos + len(left) + window)
        if right in text[lo:hi]:
            return True
        start = pos + 1


def _heading_section(text: str, heading: str) -> str:
    start = text.find(heading)
    assert start >= 0, heading
    hashes = len(heading) - len(heading.lstrip("#"))
    rest = text[start + len(heading) :]
    nxt = re.search(rf"\n#{{1,{hashes}}} ", rest)
    return heading + (rest if nxt is None else rest[: nxt.start()])


def _skill() -> str:
    return SKILL.read_text(encoding="utf-8")


def test_c1_both_host_modes_named() -> None:
    text = _skill()
    section = _heading_section(text, "## Modos Cursor (terminal vs Desktop+SSH)")
    assert "modo terminal" in section
    assert "modo Desktop+SSH" in section
    assert "não abandonar um modo" in section
    assert "grelha" in section and "Design" in section
    assert "Apply" in section and "review" in section
    assert "QA" in section and "Done técnico" in section
    assert "só modo terminal" not in section
    assert "abandonar o modo terminal" not in section
    assert "abandonar o modo Desktop" not in section


def test_c2_desktop_ssh_must_not_move_agent_to_root() -> None:
    text = _skill()
    pasta = _heading_section(text, "### Pasta (Q2)")
    assert "MUST NOT" in pasta
    assert "`move_agent_to_root`" in pasta
    assert _near(pasta, "Desktop+SSH Windows desta VM", "MUST NOT")
    assert _near(pasta, "MUST NOT", "move_agent_to_root")
    assert "filho MUST NOT `move_agent_to_root`" in _skill()


def test_c3_visible_bind_new_remote_ssh_window() -> None:
    text = _skill()
    pasta = _heading_section(text, "### Pasta (Q2)")
    assert "janela Remote-SSH nova" in pasta
    assert "vscode-remote://ssh-remote+" in pasta
    assert "MUST NOT File > Open" in pasta
    assert "`working_directory` sozinho" in pasta
    assert "não satisfaz Q2" in pasta
    assert "#<id> Apply" in text


def test_c4_flow_shell_all_first_attempt() -> None:
    text = _skill()
    comando = _heading_section(text, "### Comando (Q3)")
    assert "required_permissions" in comando
    assert '["all"]' in comando
    assert "primeiro" in comando
    assert "MUST NOT `workspace_readwrite`" in comando
    assert "uid_map" in comando
    assert "Landlock" in comando
    assert "visível" in comando
    assert "não afirmar que o host nunca pinta cartão" in comando


def test_c5_completed_with_payload_is_success() -> None:
    assert (
        classify_cursor_stage_child(
            host_status="completed",
            return_payload={"tasks": "1.1–5.2"},
        )
        == SUCCESS
    )
    assert (
        classify_cursor_stage_child(host_status="completed", return_payload=None)
        == FAIL
    )


def test_c6_interrupt_without_stop_is_host_kill() -> None:
    kill = classify_cursor_stage_child(
        host_status="interrupted",
        interrupt_message="Task was interrupted by the user after 163713ms",
        operator_stop_visible=False,
    )
    assert kill == HOST_KILL
    assert kill != SUCCESS
    abort = classify_cursor_stage_child(
        host_status="interrupted",
        interrupt_message="Task was interrupted by the user after 12ms",
        operator_stop_visible=True,
    )
    assert abort == ABORT
    assert abort != SUCCESS
    assert abort != HOST_KILL


def test_c7_refuse_parent_substitute_and_resume_corpse() -> None:
    text = _skill()
    filho = _heading_section(text, "### Filho (Q4)")
    assert "MUST NOT executar a etapa no Desktop" in filho
    assert "MUST NOT retomar cadáver" in filho
    assert "spawn **novo**" in filho
    assert "não resume" in filho
    assert parent_desktop_substitute_outcome() == REFUSE
    assert resume_corpse_outcome() == REFUSE


def test_c8_no_dual_write_other_client_skins() -> None:
    text = _skill()
    assert "MUST NOT dual-write lei" in text
    assert ".dsh/" in text
    assert ".grok/" in text
    assert ".opencode/" in text
    for rel in (
        (".dsh", "skills", "covenant-flow", "SKILL.md"),
        (".grok", "skills", "covenant-flow", "SKILL.md"),
        (".opencode", "skills", "covenant-flow", "SKILL.md"),
    ):
        stub = REPO.joinpath(*rel).read_text(encoding="utf-8")
        assert ".cursor/skills/covenant-flow/SKILL.md" in stub
        assert "move_agent_to_root" not in stub
        assert "required_permissions" not in stub


def test_spawn_prompts_name_closed_list_and_cwd() -> None:
    text = _skill()
    prompts = _heading_section(
        text, "### Prompts autocontidos (grill / Design-autor / Apply / review / QA)"
    )
    for name in ("grill", "Design-autor", "Apply", "review", "QA"):
        assert name in prompts
    assert "MUST NOT `move_agent_to_root`" in prompts
    assert "`working_directory` = worktree" in prompts
    assert '["all"]' in prompts


def test_live_proof_rubric_and_out_of_scope_cards() -> None:
    text = _skill()
    ensaio = _heading_section(text, "### Ensaio e prova viva (Q5–Q6)")
    assert "Rubrica prova viva (1.5)" in ensaio
    assert "Windows + SSH a esta VM" in ensaio
    assert "#879" in ensaio
    modos = _heading_section(text, "## Modos Cursor (terminal vs Desktop+SSH)")
    assert "Grok / OpenCode / dsh fora" in modos
    assert "não é deny de T5" in modos
    assert "G_design" in modos
    agents = AGENTS.read_text(encoding="utf-8")
    nonempty = [ln for ln in agents.splitlines() if ln.strip()]
    assert len(nonempty) <= 40
    assert "move_agent_to_root" not in agents


def test_modos_cursor_dsh_fora_is_not_t5_deny() -> None:
    section = _heading_section(_skill(), "## Modos Cursor (terminal vs Desktop+SSH)")
    assert "Grok / OpenCode / dsh fora" in section
    assert "não é deny de T5" in section
    assert "G_design" in section
