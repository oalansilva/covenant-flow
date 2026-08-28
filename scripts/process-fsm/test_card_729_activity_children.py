"""#729: one chat per card; no D8 freeze; grill bind is Status+#id."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ALAN = REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md"
CRITIC = REPO / ".agents" / "skills" / "design-critic" / "SKILL.md"
GRILL = REPO / ".cursor" / "skills" / "grill-card" / "SKILL.md"
APPLY = REPO / ".cursor" / "skills" / "openspec-apply-change" / "SKILL.md"

FORBIDDEN = (
    "Um chat por coluna",
    "pedir chat novo com o título da coluna",
    "abra `#id Apply`",
    "outro chat `#<id> Apply`",
)


def test_runbooks_drop_d8_new_chat_freeze() -> None:
    for path in (ALAN, CRITIC):
        text = path.read_text(encoding="utf-8")
        for needle in FORBIDDEN:
            assert needle not in text, (path, needle)


def test_alan_workflow_names_activity_children() -> None:
    text = ALAN.read_text(encoding="utf-8")
    assert "## Um chat por card" in text
    assert "lista fechada isolada" in text
    assert "iniciar_apply" in text
    assert "T14" in text


def test_apply_skill_is_column_child() -> None:
    text = APPLY.read_text(encoding="utf-8")
    assert "MUST NOT call `process_event`" in text
    assert "MUST NOT spawn reviewers" in text or "MUST NOT spawn `diff-reviewer`" in text


def test_grill_bind_is_status_and_issue_id() -> None:
    text = GRILL.read_text(encoding="utf-8")
    assert "Não exige branch `card-<id>-*`" in text
    assert "Status=Em Refinamento" in text or "Em Refinamento" in text
