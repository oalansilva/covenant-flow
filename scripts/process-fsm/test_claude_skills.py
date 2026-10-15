from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

import claude_skills
import codex_skills
from codex_skills import BridgeError

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]


def frontmatter(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---\n", 2)[1])


def make_source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    for name in ("alpha", "covenant-flow"):
        path = root / ".cursor" / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(f'---\nname: {name}\ndescription: "{name} workflow"\n---\n\nCanonical body {name}.\n', encoding="utf-8")
    for name in claude_skills.VENDORED:
        path = root / ".agents" / "skills" / name / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text(f'---\nname: {name}\ndescription: "vendored {name}"\nallowed-tools: Bash(x:*)\n---\n\nVendored body.\n', encoding="utf-8")
    return root


def test_bridges_cover_the_codex_set_plus_the_two_vendored_skills():
    claude = claude_skills.expected_bridges(REPO)
    codex = codex_skills.expected_bridges(REPO)
    assert set(codex) < set(claude) and set(claude) - set(codex) == {"impeccable", "playwright-cli"}
    assert len(claude) == 20
    manifest = json.loads((REPO / ".claude/skills" / codex_skills.MANIFEST).read_text())
    assert set(manifest["files"]) == {f"{n}/SKILL.md" for n in claude}


def test_repository_bridges_match_manifest_frontmatter_and_carry_no_workflow():
    assert claude_skills.install_bridges(REPO, REPO, check_only=True) == []
    for name in claude_skills.expected_bridges(REPO):
        bridge = REPO / ".claude/skills" / name / "SKILL.md"
        vendored = name in claude_skills.VENDORED
        canonical = REPO / (".agents" if vendored else ".cursor") / "skills" / name / "SKILL.md"
        meta, source = frontmatter(bridge), frontmatter(canonical)
        assert meta == {"name": source["name"], "description": source["description"].strip()}
        body = bridge.read_text(encoding="utf-8").split("---\n", 2)[2]
        assert f"Read the complete `{canonical.relative_to(REPO).as_posix()}` file" in body
        assert len(body.strip().splitlines()) <= 4, f"{name} bridge has more than a pointer"
        assert not re.search(r"\b(Status|process_event|Pronto para Dev|T\d+)\b", body)


def test_generated_bridges_are_thin_and_do_not_grant_tools(tmp_path):
    source, target = make_source(tmp_path), tmp_path / "target"
    claude_skills.install_bridges(source, target)
    for name, content in claude_skills.expected_bridges(source).items():
        path = target / ".claude/skills" / name / "SKILL.md"
        assert path.read_text(encoding="utf-8") == content
        assert "Canonical body" not in content and "Vendored body" not in content and "allowed-tools" not in content
    assert claude_skills.install_bridges(source, target, check_only=True) == []


def test_divergent_local_bridge_is_refused_without_overwrite_or_partial_install(tmp_path):
    source, target = make_source(tmp_path), tmp_path / "target"
    conflict = target / ".claude/skills/alpha/SKILL.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("operator-authored skill\n", encoding="utf-8")
    with pytest.raises(BridgeError, match="no files changed"):
        claude_skills.install_bridges(source, target)
    assert conflict.read_text(encoding="utf-8") == "operator-authored skill\n"
    assert not (target / ".claude/skills/covenant-flow").exists()
    assert not (target / ".claude/skills" / codex_skills.MANIFEST).exists()


def test_drift_after_install_is_refused_on_update_and_flagged_by_check(tmp_path):
    source, target = make_source(tmp_path), tmp_path / "target"
    claude_skills.install_bridges(source, target)
    bridge = target / ".claude/skills/alpha/SKILL.md"
    bridge.write_text(bridge.read_text(encoding="utf-8") + "operator edit\n", encoding="utf-8")
    with pytest.raises(BridgeError):
        claude_skills.install_bridges(source, target, check_only=True)
    path = source / ".cursor/skills/alpha/SKILL.md"
    path.write_text(path.read_text().replace("alpha workflow", "alpha updated"), encoding="utf-8")
    with pytest.raises(BridgeError, match="no files changed"):
        claude_skills.install_bridges(source, target)
    assert "operator edit" in bridge.read_text(encoding="utf-8")


def test_vendored_skill_missing_or_colliding_is_refused(tmp_path):
    source = make_source(tmp_path)
    (source / ".agents/skills/impeccable/SKILL.md").unlink()
    with pytest.raises(BridgeError, match="vendored skill missing"):
        claude_skills.expected_bridges(source)


def test_codex_bridges_are_untouched_by_the_claude_generator(tmp_path):
    source = make_source(tmp_path)
    codex_skills.install_bridges(source, tmp_path / "t")
    assert (tmp_path / "t/.agents/skills/alpha/SKILL.md").is_file()
    assert not (tmp_path / "t/.claude").exists()
    assert codex_skills.install_bridges(REPO, REPO, check_only=True) == []


def test_cli_install_and_check(tmp_path, capsys):
    source = make_source(tmp_path)
    assert claude_skills.main(["install", "--source", str(source), "--target", str(tmp_path / "t")]) == 0
    assert claude_skills.main(["check", "--source", str(source), "--target", str(tmp_path / "t")]) == 0
    assert "Claude skill bridge coverage/drift: PASS" in capsys.readouterr().out
