from __future__ import annotations

import sys
from pathlib import Path
import tomllib

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import codex_agents  # noqa: E402
from codex_agents import AgentConfigError, install, plan  # noqa: E402


def _source(root: Path) -> Path:
    roles = root / ".codex" / "agents"
    roles.mkdir(parents=True)
    (roles / "diff-reviewer.toml").write_text(
        'name = "diff-reviewer"\n'
        'description = "Read-only exact-diff defect review."\n'
        'sandbox_mode = "read-only"\n'
        'developer_instructions = "Do not use git or write files."\n',
        encoding="utf-8",
    )
    (roles / "code-reviewer.toml").write_text(
        'name = "code-reviewer"\n'
        'description = "Read-only exact-diff process review."\n'
        'sandbox_mode = "read-only"\n'
        'developer_instructions = "Do not use git or write files."\n',
        encoding="utf-8",
    )
    return root


def test_installs_readonly_roles_without_model_defaults_and_preserves_other_agents(tmp_path: Path):
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    other = target / ".codex" / "agents" / "operator.toml"
    other.parent.mkdir(parents=True)
    other.write_text('name = "operator"\n', encoding="utf-8")

    changed = install(source, target)
    parsed = [
        (target / ".codex" / "agents" / name).read_text(encoding="utf-8")
        for name in ("diff-reviewer.toml", "code-reviewer.toml")
    ]

    assert len(changed) == 2
    assert all('sandbox_mode = "read-only"' in text for text in parsed)
    assert all("model =" not in text and "model_reasoning_effort" not in text for text in parsed)
    assert other.read_text(encoding="utf-8") == 'name = "operator"\n'
    assert codex_agents.install(source, target, check_only=True) == []


def test_install_does_not_follow_preexisting_predictable_temp_symlink(tmp_path: Path):
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    role_dir = target / ".codex" / "agents"
    role_dir.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"protected bytes\n")
    temp_link = role_dir / ".diff-reviewer.toml.covenant-flow-tmp"
    temp_link.symlink_to(victim)

    installed = install(source, target)

    assert len(installed) == 2
    assert (role_dir / "diff-reviewer.toml").is_file()
    assert victim.read_bytes() == b"protected bytes\n"
    assert temp_link.is_symlink()


def test_conflicting_role_refuses_all_before_writing_other_role(tmp_path: Path):
    source = _source(tmp_path / "source")
    target = tmp_path / "target"
    role_dir = target / ".codex" / "agents"
    role_dir.mkdir(parents=True)
    conflict = role_dir / "diff-reviewer.toml"
    conflict.write_text('name = "diff-reviewer"\nmodel = "operator-choice"\n', encoding="utf-8")

    with pytest.raises(AgentConfigError, match="operator review required"):
        install(source, target)

    assert conflict.read_text(encoding="utf-8") == 'name = "diff-reviewer"\nmodel = "operator-choice"\n'
    assert not (role_dir / "code-reviewer.toml").exists()


def test_preflight_detects_static_model_routing_in_source_role(tmp_path: Path):
    source = _source(tmp_path / "source")
    path = source / ".codex" / "agents" / "diff-reviewer.toml"
    path.write_text(
        path.read_text(encoding="utf-8") + 'model = "gpt-6-sol"\n',
        encoding="utf-8",
    )

    with pytest.raises(AgentConfigError, match="must not set model"):
        plan(source, tmp_path / "target")


def test_product_reviewer_roles_are_distinct_readonly_and_do_not_pin_models():
    repo = ROOT.parents[1]
    roles = repo / ".codex" / "agents"
    diff = tomllib.loads((roles / "diff-reviewer.toml").read_text(encoding="utf-8"))
    process = tomllib.loads((roles / "code-reviewer.toml").read_text(encoding="utf-8"))

    assert diff["name"] == "diff-reviewer" and process["name"] == "code-reviewer"
    assert diff["description"] != process["description"]
    assert diff["sandbox_mode"] == process["sandbox_mode"] == "read-only"
    for role in (diff, process):
        assert "model" not in role and "model_reasoning_effort" not in role
        assert "review_diff_path" in role["developer_instructions"]
        assert "git" in role["developer_instructions"]
        assert "write" in role["developer_instructions"]
    assert "defect review" in diff["description"]
    assert "process/contract" in process["developer_instructions"]
