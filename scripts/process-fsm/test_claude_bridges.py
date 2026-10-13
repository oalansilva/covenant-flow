"""CLAUDE.md bridge and the unofficial-adapter lock (design 12, tasks 1.1 and 6.4)."""
from __future__ import annotations

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


def test_the_card_diff_leaves_official_surfaces_alone():
    base = subprocess.run(["git", "-C", str(REPO), "merge-base", "HEAD", "origin/develop"], capture_output=True, text=True)
    if base.returncode != 0:
        pytest.skip("origin/develop unavailable")
    changed = subprocess.run(["git", "-C", str(REPO), "diff", "--name-only", base.stdout.strip(), "--",
                              "AGENTS.md", "scripts/process-fsm/test_overlay.py", "scripts/process-fsm/test_paging.py"], capture_output=True, text=True).stdout.split()
    changed_overlay_render = subprocess.run(["git", "-C", str(REPO), "diff", base.stdout.strip(), "--", "scripts/process-fsm/overlay.py"], capture_output=True, text=True).stdout
    assert changed == [], "AGENTS.md and the official-client tests belong to the follow-up oficialização card"
    assert "render_agents" not in changed_overlay_render
