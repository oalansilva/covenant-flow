"""Pin installer integration for the (unofficial, cooperative) Claude Code adapter."""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from model_selection_fixtures import document
from test_codex_installer import INSTALL, ROOT, _pin, _target

pytestmark = pytest.mark.skipif(
    not INSTALL.is_file(), reason="installer integration tests require the product install.sh"
)

MANAGED = "scripts/process-fsm/claude_adapter.py"


def _home(tmp_path: Path) -> Path:
    return tmp_path / "operator-home"


def _git(target: Path) -> None:
    subprocess.run(["git", "init", "-q", str(target)], check=True)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def _env(tmp_path: Path) -> dict[str, str]:
    env = {**os.environ, "HOME": str(_home(tmp_path)), "AI_AGENT": "claude-code_2.1.296_agent"}
    for name in ("CLAUDECODE", "CODEX_THREAD_ID", "COVENANT_CLIENT", "CLAUDE_CODE_SUBAGENT_MODEL",
                 "CLAUDE_CODE_SUBAGENT_MODEL_FORCE", "CLAUDE_CODE_EFFORT_LEVEL"):
        env.pop(name, None)
    return env


def _assert_untouched(target: Path, original_map: bytes) -> None:
    assert (target / ".cursor" / "model-map.yaml").read_bytes() == original_map
    assert not (target / ".cursor" / "process-fsm.yaml").exists()
    assert not (target / ".codex" / "agents").exists()


def test_pin_installs_claude_adapter_and_resolves_the_fixture_selection_without_trust(tmp_path: Path):
    selection = _home(tmp_path) / ".config" / "covenant-flow" / "model-selection.yaml"
    selection.parent.mkdir(parents=True)
    selection.write_text(yaml.safe_dump(document()))
    before = selection.read_bytes()
    target, original_map = _target(tmp_path / "consumer")
    _git(target)

    result = _pin(target)

    assert result.returncode == 0, result.stderr
    assert "Claude Code project hooks require operator trust review" in result.stdout
    # CLAUDE.md is the one-line bridge copied from the product source.
    assert (target / "CLAUDE.md").read_bytes() == (ROOT / "CLAUDE.md").read_bytes()
    assert (target / "CLAUDE.md").read_text(encoding="utf-8").startswith("@AGENTS.md")
    skills = sorted(path.parent.name for path in (target / ".claude" / "skills").glob("*/SKILL.md"))
    assert len(skills) == 20 and {"covenant-flow", "impeccable", "playwright-cli"} <= set(skills)
    manifest = json.loads((target / ".claude" / "skills" / ".covenant-flow-bridges.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 1 and len(manifest["files"]) == 20
    for role in ("diff-reviewer", "code-reviewer"):
        agent = (target / ".claude" / "agents" / f"{role}.md").read_text(encoding="utf-8")
        assert "tools: Read, Grep, Glob" in agent and "model:" not in agent and "effort:" not in agent
    hooks = json.loads((target / ".claude" / "settings.json").read_text(encoding="utf-8"))["hooks"]
    assert {"SessionStart", "PreToolUse", "PostToolUse", "SubagentStop", "Stop"} <= set(hooks)
    for name in ("claude_adapter.py", "claude_evidence.py", "claude_proxy.py", "claude_review.py", "claude_trust.py"):
        assert filecmp.cmp(ROOT / "scripts/process-fsm" / name, target / "scripts/process-fsm" / name, shallow=False)
    policy = yaml.safe_load((target / ".cursor" / "model-policy.yaml").read_text(encoding="utf-8"))
    assert policy["clients"]["claude"]["contract"] == "claude-agent-pair-v1"

    # The pinned consumer resolves a Claude Code pair from the (fixture) account selection.
    capture = tmp_path / "birth.json"
    resolved = subprocess.run(
        [sys.executable, str(target / "scripts/process-fsm/model_selection.py"), "resolve", "--client", "claude",
         "--band", "execucao", "--role", "same-card-search", "--capture", str(capture)],
        env=_env(tmp_path), capture_output=True, text=True,
    )
    assert resolved.returncode == 0, resolved.stderr
    birth = json.loads(resolved.stdout)
    assert birth["source_path"] == str(selection)
    assert birth["arguments"] == {"model": "sonnet", "effort": "high"}

    # Pinning never reads or writes the account: selection untouched, no trust record, hooks unreviewed.
    assert selection.read_bytes() == before
    assert sorted(p.name for p in selection.parent.iterdir()) == ["model-selection.yaml"]
    assert not (_home(tmp_path) / ".config" / "covenant-flow" / "claude-hook-trust.json").exists()
    status = subprocess.run(
        [sys.executable, str(target / "scripts/process-fsm/claude_adapter.py"), "trust", "--status"],
        env=_env(tmp_path), cwd=target, capture_output=True, text=True,
    )
    assert status.returncode == 1 and json.loads(status.stdout)["reviewed"] is False

    # A second pin is a no-op for the Claude Code tree.
    tree = _snapshot(target / ".claude"), (target / "CLAUDE.md").read_bytes()
    second = _pin(target)
    assert second.returncode == 0, second.stderr
    assert (_snapshot(target / ".claude"), (target / "CLAUDE.md").read_bytes()) == tree
    assert selection.read_bytes() == before


def test_pin_preserves_consumer_claude_files_hooks_and_own_skills(tmp_path: Path):
    target, _original_map = _target(tmp_path / "consumer")
    own_claude_md = "# Consumer memory\n\nWe import the law below.\n\n@AGENTS.md\n\nOur own team notes stay.\n"
    (target / "CLAUDE.md").write_text(own_claude_md, encoding="utf-8")
    claude = target / ".claude"
    (claude / "skills" / "team-skill").mkdir(parents=True)
    (claude / "skills" / "team-skill" / "SKILL.md").write_bytes(b"---\nname: team-skill\ndescription: team\n---\nown\n")
    (claude / "agents").mkdir()
    (claude / "agents" / "team-agent.md").write_bytes(b"---\nname: team-agent\ndescription: team\n---\nown\n")
    (claude / "settings.local.json").write_bytes(b'{"local": true}\n')
    settings = {
        "model": "operator-default",
        "permissions": {"allow": ["Bash(ls:*)"]},
        "hooks": {
            "Notification": [{"hooks": [{"type": "command", "command": "python operator-notify.py"}]}],
            "PreToolUse": [
                {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "python operator-bash.py"},
                    # A stale handler owned by this adapter is replaced, never duplicated.
                    {"type": "command", "command": f'python3 "$CLAUDE_PROJECT_DIR/{MANAGED}" pre-tool-use', "timeout": 1},
                ]},
            ],
        },
    }
    (claude / "settings.json").write_text(json.dumps(settings), encoding="utf-8")

    result = _pin(target)

    assert result.returncode == 0, result.stderr
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == own_claude_md
    assert (claude / "skills" / "team-skill" / "SKILL.md").read_bytes().endswith(b"own\n")
    assert (claude / "agents" / "team-agent.md").read_bytes().endswith(b"own\n")
    assert (claude / "settings.local.json").read_bytes() == b'{"local": true}\n'
    merged = json.loads((claude / "settings.json").read_text(encoding="utf-8"))
    assert merged["model"] == "operator-default" and merged["permissions"] == {"allow": ["Bash(ls:*)"]}
    assert merged["hooks"]["Notification"][0]["hooks"][0]["command"] == "python operator-notify.py"
    commands = [h["command"] for g in merged["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert commands.count("python operator-bash.py") == 1
    assert sum(MANAGED in command for command in commands) == 1
    assert all("timeout" not in h or h["timeout"] != 1 for g in merged["hooks"]["PreToolUse"] for h in g["hooks"] if MANAGED in h["command"])
    assert {"SessionStart", "PostToolUse", "SubagentStop", "Stop"} <= set(merged["hooks"])


def test_existing_adapters_are_installed_byte_for_byte_and_claude_never_touches_their_hooks(tmp_path: Path):
    target, original_map = _target(tmp_path / "consumer")
    codex_hooks = target / ".codex" / "hooks.json"
    codex_hooks.parent.mkdir()
    codex_hooks.write_text(json.dumps({"hooks": {"Notification": [{"hooks": [{"type": "command", "command": "x"}]}]}}), encoding="utf-8")

    result = _pin(target)

    assert result.returncode == 0, result.stderr
    assert (target / ".cursor" / "model-map.yaml").read_bytes() == original_map
    for tree in (".cursor/hooks", ".cursor/rules", ".cursor/commands", ".cursor/agents", ".cursor/skills", ".grok",
                 ".opencode/plugin", ".opencode/skills", ".dsh", ".codex/agents"):
        comparison = filecmp.dircmp(ROOT / tree, target / tree)
        assert not comparison.left_only and not comparison.diff_files, tree
    codex = json.loads(codex_hooks.read_text(encoding="utf-8"))
    assert "claude_adapter.py" not in json.dumps(codex)
    assert "codex_adapter.py" in json.dumps(codex) and "Notification" in codex["hooks"]
    assert len(list((target / ".agents" / "skills").glob("*/SKILL.md"))) == 20
    # Separate manifests: the Claude bridges also cover the vendored skills.
    assert (target / ".claude" / "skills" / ".covenant-flow-bridges.json").read_bytes() != (
        target / ".agents" / "skills" / ".covenant-flow-bridges.json"
    ).read_bytes()


@pytest.mark.parametrize(
    "content",
    [
        "# Own memory without the law\n",
        "# Own memory\n\n```\n@AGENTS.md\n```\n\nand `@AGENTS.md` as code only\n",
        "see mail@AGENTS.md.example\n",
    ],
)
def test_own_claude_md_without_the_agents_import_aborts_visibly_before_any_write(tmp_path: Path, content: str):
    target, original_map = _target(tmp_path / "consumer")
    (target / "CLAUDE.md").write_text(content, encoding="utf-8")

    result = _pin(target)

    assert result.returncode != 0
    assert "CLAUDE.md conflict" in result.stderr and "@AGENTS.md" in result.stderr
    assert (target / "CLAUDE.md").read_text(encoding="utf-8") == content
    _assert_untouched(target, original_map)
    assert not (target / ".claude").exists()


def test_claude_collisions_abort_the_pin_before_any_tree_is_written(tmp_path: Path):
    cases = {
        "edited bridge": (".claude/skills/implantar/SKILL.md", b"operator-authored skill\n", "skill bridge conflict"),
        "edited reviewer agent": (".claude/agents/diff-reviewer.md", b"operator-authored agent\n", "Claude agent conflict"),
        "malformed settings": (".claude/settings.json", b"{not json", "claude hook merge error"),
        "non-object hooks": (".claude/settings.json", b'{"hooks": []}', "claude hook merge error"),
    }
    for name, (relative, content, message) in cases.items():
        target, original_map = _target(tmp_path / name.replace(" ", "-"))
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

        result = _pin(target)

        assert result.returncode != 0, name
        assert message in result.stderr, (name, result.stderr)
        assert path.read_bytes() == content, name
        _assert_untouched(target, original_map)
        assert not (target / "CLAUDE.md").exists(), name
        assert not (target / "scripts").exists(), name


def test_claude_symlinked_claude_md_is_refused(tmp_path: Path):
    target, original_map = _target(tmp_path / "consumer")
    (target / "elsewhere.md").write_text("@AGENTS.md\n", encoding="utf-8")
    (target / "CLAUDE.md").symlink_to(target / "elsewhere.md")

    result = _pin(target)

    assert result.returncode != 0 and "CLAUDE.md conflict" in result.stderr
    _assert_untouched(target, original_map)


def _source_copy(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    shutil.copytree(ROOT, source, ignore=shutil.ignore_patterns(".git", "__pycache__", ".pytest_cache"))
    return source


@pytest.mark.parametrize(
    "missing",
    [
        "scripts/process-fsm/claude_adapter.py",
        "scripts/process-fsm/claude_evidence.py",
        "scripts/process-fsm/codex_evidence.py",
        ".claude/settings.json",
        ".claude/agents/code-reviewer.md",
        "CLAUDE.md",
    ],
)
def test_missing_claude_mechanism_aborts_before_pin_writes(tmp_path: Path, missing: str):
    source = _source_copy(tmp_path)
    (source / missing).unlink()
    target, original_map = _target(tmp_path / "consumer")

    result = subprocess.run(
        [str(INSTALL), "--pin", "v1.2.0", "--source", str(source), "--target", str(target)],
        capture_output=True, text=True, env={**os.environ, "HOME": str(_home(tmp_path))},
    )

    assert result.returncode != 0
    assert "selection mechanism missing" in result.stderr or "hooks JSON missing" in result.stderr or "claude" in result.stderr.lower()
    _assert_untouched(target, original_map)
    assert not (target / ".claude").exists() and not (target / "CLAUDE.md").exists()


def test_policy_without_the_claude_contract_aborts_before_pin_writes(tmp_path: Path):
    source = _source_copy(tmp_path)
    policy_path = source / ".cursor" / "model-policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    del policy["clients"]["claude"]
    policy_path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    target, original_map = _target(tmp_path / "consumer")

    result = subprocess.run(
        [str(INSTALL), "--pin", "v1.2.0", "--source", str(source), "--target", str(target)],
        capture_output=True, text=True, env={**os.environ, "HOME": str(_home(tmp_path))},
    )

    assert result.returncode != 0
    _assert_untouched(target, original_map)
    assert not (target / ".claude").exists() and not (target / "CLAUDE.md").exists()
