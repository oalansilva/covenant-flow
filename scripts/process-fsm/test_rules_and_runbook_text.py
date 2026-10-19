"""The rules and the runbook describe the account registration and the desktop-app way of working (#1103, R25 R29-R31)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
HARNESS = REPO / ".cursor" / "rules" / "harness.mdc"
SKILL = REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md"
RULES = REPO / "rules.md"
DOC = REPO / "docs" / "claude-runtime-evidence.md"
ACCOUNT_CHAIN = "registro na conta (`install.sh --account`) → shim → adapter pinado"
# A project hook file of the three hosts, not the account one (`~/.codex/hooks.json`) and not another file that merely ends alike.
PROJECT_HOOK_FILE = re.compile(r"(?<![~\w/])(\.cursor/hooks\.json|\.codex/hooks\.json)")


def project_hook_mentions(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if PROJECT_HOOK_FILE.search(line)]


def test_harness_rule_names_the_account_registration_not_a_project_hook_file():
    text = HARNESS.read_text(encoding="utf-8")
    assert "registro na conta (`install.sh --account`) → shim → adapter pinado" in text
    assert project_hook_mentions(text) == []


def test_the_codex_paragraph_of_the_skill_describes_the_account_registration():
    skill = SKILL.read_text(encoding="utf-8")
    assert "Os hooks chegam pelo registro na conta (`install.sh --account`) → shim → adapter pinado (`scripts/process-fsm/codex_*.py`)" in skill
    assert "O adapter usa `.codex/hooks.json`" not in skill
    # the only project hook file still named is the old pin's, said as such
    for line in project_hook_mentions(skill):
        assert "Pins anteriores ao registro na conta" in line or "implantar" in line or "fornecedor" in line, line


def test_rules_md_of_the_consumer_names_the_account_registration():
    if not RULES.is_file():
        pytest.skip("rules.md is the consumer's own file; the nucleus has none")
    text = RULES.read_text(encoding="utf-8")
    assert ACCOUNT_CHAIN in text and project_hook_mentions(text) == []


def test_the_skill_explains_how_to_work_through_the_desktop_app():
    skill = SKILL.read_text(encoding="utf-8")
    section = skill.split("### Claude Code pelo app desktop", 1)[1].split("\n## ", 1)[0]
    for needle in (
        "`/source`", "*worktree*", "desligada", "`#<id>`", "`EnterWorktree`", "pasta do app (sem card)", "`.claude/worktrees/`",
        "`mcp__ccd_*`", "Agent", "`<papel> <id> <único>`", "--handoff", "`auto`", "não autoriza processo",
    ):
        assert needle in section, needle
    # R29: operator commands pasted in plain bash, without `!` and without `cd … &&`
    assert "sem `!` na frente e sem `cd … &&`" in section and "bash comum" in section
    # R30: after the account review a new session is needed
    assert "sessão nova" in section and "`hooks_inactive`" in section
    # the claude paragraph names both surfaces and both floors
    assert "`claude-desktop`" in skill and "2.1.292" in skill and "2.1.295" in skill


def test_the_runtime_doc_has_the_desktop_row_the_session_version_and_the_floors():
    text = DOC.read_text(encoding="utf-8")
    row = next(line for line in text.splitlines() if line.startswith("| App desktop do Claude no Windows por SSH"))
    for needle in ("claude-desktop", "2.1.295", "2.37337.1", "2.1.292", "APP_SESSION_2_1_295", "pasta do app (sem card)"):
        assert needle in row, needle
    assert "`QUALIFIED_ENTRYPOINTS = (\"cli\", \"claude-desktop\")`" in text
    assert "`AI_AGENT`" in text and "só vale fora de sessão" in text
    assert "retorno em segundo plano" in text.lower() and "`<task-notification>`" in text
    assert "recusa dentro de sessão de agente" in text


def test_the_skill_documents_the_nucleus_installer_diff_in_the_review_wave():
    skill = SKILL.read_text(encoding="utf-8")
    assert "--nucleus <checkout do covenant-flow>" in skill and "diff do `install.sh` do nucleus" in skill


def test_the_consumer_ignores_the_folders_the_app_creates():
    gitignore = REPO / ".gitignore"
    if not (REPO / "docs" / "crypto-overlay.md").is_file():
        pytest.skip("the app folders are ignored by the consumer's .gitignore (task 4.6); this tree is not the Cripto consumer")
    assert ".claude/worktrees/" in gitignore.read_text(encoding="utf-8").splitlines()
