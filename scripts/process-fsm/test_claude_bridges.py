"""CLAUDE.md bridge and the unofficial-adapter lock (design 12, tasks 1.1 and 6.4)."""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from overlay import render_agents
from test_overlay_fixtures import filled_overlay_dict

REPO = Path(__file__).resolve().parents[2]


def lines(path: Path) -> list[str]:
    return [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_claude_md_only_imports_agents_md_with_a_bridge_note():
    content = lines(REPO / "CLAUDE.md")
    assert content[0] == "@AGENTS.md" and len(content) <= 3
    text = "\n".join(content).lower()
    assert "bridge" in text
    assert not re.search(r"claude code is|cliente|client|\bT\d{1,2}\b|\|.*\|", text)  # no law, no client claim, no tables


def test_agents_md_and_active_client_text_do_not_name_claude_code():
    assert "claude" not in (REPO / "AGENTS.md").read_text(encoding="utf-8").lower()
    assert "claude" not in render_agents(filled_overlay_dict()).lower()
    skill = (REPO / ".cursor/skills/covenant-flow/SKILL.md").read_text(encoding="utf-8")
    active = next(line for line in skill.splitlines() if line.startswith("Cliente ativo:"))
    assert "Claude" not in active
    assert "Cliente ativo" not in (REPO / "CLAUDE.md").read_text(encoding="utf-8")


def test_the_claude_section_is_scoped_as_unofficial_and_cooperative():
    skill = (REPO / ".cursor/skills/covenant-flow/SKILL.md").read_text(encoding="utf-8")
    section = skill.split("## Claude Code (cooperativo; sem Auto)", 1)[1].split("\n## ", 1)[0]
    assert "não oficial" in section and "sem modo Auto" in section
    assert "não é cliente oficial" in section


PAGING = "scripts/process-fsm/test_paging.py"
# The one change the card makes in test_paging.py: the hooks-file test became the account-registration test (design 8),
# plus the imports that test needs. Anything else, or anything that names Claude Code, would be oficialização.
REGISTRATION_TESTS = {"test_hooks_json_session_start", "test_account_registration_session_start"}
REGISTRATION_IMPORTS = {"adapter_manifest", "shim_fixtures"}


def paging_without_registration_test(source: str) -> list[str]:
    tree = ast.parse(source)
    kept = [
        node for node in tree.body
        if not (isinstance(node, ast.FunctionDef) and node.name in REGISTRATION_TESTS)
        and not (isinstance(node, ast.ImportFrom) and node.module in REGISTRATION_IMPORTS)
    ]
    return [ast.dump(node) for node in kept]


def paging_registration_source(source: str) -> str:
    tree = ast.parse(source)
    parts = [
        ast.get_source_segment(source, node) or ""
        for node in tree.body
        if (isinstance(node, ast.FunctionDef) and node.name in REGISTRATION_TESTS)
        or (isinstance(node, ast.ImportFrom) and node.module in REGISTRATION_IMPORTS)
    ]
    return "\n".join(parts)


def test_the_card_diff_leaves_official_surfaces_alone():
    base = subprocess.run(["git", "-C", str(REPO), "merge-base", "HEAD", "origin/develop"], capture_output=True, text=True)
    if base.returncode != 0:
        pytest.skip("origin/develop unavailable")
    changed = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only", base.stdout.strip(), "--",
                              "AGENTS.md", "scripts/process-fsm/test_overlay.py"], capture_output=True, text=True).stdout.split()
    changed_overlay_render = subprocess.run(["git", "-C", str(REPO), "diff", base.stdout.strip(), "--", "scripts/process-fsm/overlay.py"], capture_output=True, text=True).stdout
    assert changed == [], "AGENTS.md and the official-client tests belong to the follow-up oficialização card"
    assert "render_agents" not in changed_overlay_render
    # test_paging.py may change only by swapping the hooks-file test for the account-registration one, without naming Claude Code.
    base_paging = subprocess.run(["git", "-C", str(REPO), "show", f"{base.stdout.strip()}:{PAGING}"], capture_output=True, text=True)
    if base_paging.returncode != 0:
        pytest.skip("test_paging.py unavailable at the merge-base")
    current_paging = (REPO / PAGING).read_text(encoding="utf-8")
    assert paging_without_registration_test(current_paging) == paging_without_registration_test(base_paging.stdout), \
        "AGENTS.md and the official-client tests belong to the follow-up oficialização card"
    assert "claude" not in paging_registration_source(current_paging).lower(), \
        "AGENTS.md and the official-client tests belong to the follow-up oficialização card"
