from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

import claude_agents
from claude_agents import AgentConfigError

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
FORBIDDEN = {"Bash", "Edit", "Write", "MultiEdit", "NotebookEdit", "Agent", "Task"}


def parse(path: Path):
    text = path.read_text(encoding="utf-8")
    return yaml.safe_load(text.split("---\n", 2)[1]), text.split("---\n", 2)[2]


@pytest.mark.parametrize("name", claude_agents.ROLES)
def test_repository_reviewer_is_read_only_pinless_and_hash_bound_to_the_canonical(name):
    meta, body = parse(REPO / ".claude/agents" / f"{name}.md")
    tools = {t.strip() for t in meta["tools"].split(",")}
    assert meta["name"] == name and tools == {"Read", "Grep", "Glob"} and not tools & FORBIDDEN
    assert "model" not in meta and "effort" not in meta  # the pair comes per spawn from the capture
    canonical = REPO / ".cursor/agents" / f"{name}.md"
    assert f"canonical_sha256: {hashlib.sha256(canonical.read_bytes()).hexdigest()}" in body
    assert f".cursor/agents/{name}.md" in body
    assert "review_diff_path:" in body and "ERROR: review-diff missing" in body
    assert "Do not run git" in body and "transcripts" in body
    claude_agents.validate(REPO / ".claude/agents" / f"{name}.md", REPO)
    assert claude_agents.install(REPO, REPO, check_only=True) == []


def test_description_matches_the_canonical_reviewer():
    for name in claude_agents.ROLES:
        meta, _ = parse(REPO / ".claude/agents" / f"{name}.md")
        canonical, _ = parse(REPO / ".cursor/agents" / f"{name}.md")
        assert meta["description"] == canonical["description"]


def make_source(tmp_path: Path) -> Path:
    root = tmp_path / "s"
    for name in claude_agents.ROLES:
        path = root / ".cursor/agents" / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\nname: {name}\ndescription: {name} role\nreadonly: true\n---\n\nContract of {name}.\n", encoding="utf-8")
    return root


def test_stale_hash_pinned_model_or_write_tool_is_refused(tmp_path):
    source = make_source(tmp_path)
    target = tmp_path / "t"
    claude_agents.install(source, target)
    agent = target / ".claude/agents/diff-reviewer.md"
    claude_agents.validate(agent, source)
    (source / ".cursor/agents/diff-reviewer.md").write_text("---\nname: diff-reviewer\ndescription: x\n---\nchanged\n", encoding="utf-8")
    with pytest.raises(AgentConfigError, match="stale"):
        claude_agents.validate(agent, source)
    for edit, needle in (("tools: Read, Grep, Glob\n", "tools: Read, Grep, Glob, Bash\n"), ("tools: Read, Grep, Glob\n", "tools: Read, Grep, Glob\nmodel: opus\n")):
        broken = tmp_path / "broken.md"
        broken.write_text(agent.read_text().replace(edit, needle), encoding="utf-8")
        with pytest.raises(AgentConfigError):
            claude_agents.validate(broken, make_source(tmp_path / "again"))


def test_install_never_overwrites_operator_content(tmp_path):
    source = make_source(tmp_path)
    target = tmp_path / "t"
    existing = target / ".claude/agents/code-reviewer.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("operator agent\n", encoding="utf-8")
    with pytest.raises(AgentConfigError, match="no files changed"):
        claude_agents.install(source, target)
    assert existing.read_text() == "operator agent\n"
    assert not (target / ".claude/agents/diff-reviewer.md").exists()
