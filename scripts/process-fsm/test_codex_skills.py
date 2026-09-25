from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

import codex_skills  # noqa: E402
from codex_skills import BridgeError, expected_bridges, install_bridges  # noqa: E402


def _write_skill(root: Path, name: str, description: str) -> Path:
    path = root / ".cursor" / "skills" / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'---\nname: {name}\ndescription: "{description}"\n---\n\nCanonical.\n',
        encoding="utf-8",
    )
    return path


def _source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    _write_skill(root, "alpha", "Alpha workflow")
    _write_skill(root, "design-critic", "Design critic workflow")
    return root


def test_generates_thin_bridges_and_preserves_vendor_and_existing_skills(tmp_path: Path):
    source = _source(tmp_path)
    target = tmp_path / "target"
    vendor = target / ".agents" / "skills" / "impeccable" / "SKILL.md"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("provider-owned bytes\n", encoding="utf-8")
    existing = target / ".agents" / "skills" / "playwright-cli" / "SKILL.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("local skill bytes\n", encoding="utf-8")

    changed = install_bridges(source, target)

    expected = expected_bridges(source)
    for name, content in expected.items():
        path = target / ".agents" / "skills" / name / "SKILL.md"
        assert path.read_text(encoding="utf-8") == content
        assert f".cursor/skills/{name}/SKILL.md" in content
        assert "Canonical." not in content
    assert vendor.read_text(encoding="utf-8") == "provider-owned bytes\n"
    assert existing.read_text(encoding="utf-8") == "local skill bytes\n"
    assert any(codex_skills.MANIFEST in item for item in changed)
    assert install_bridges(source, target, check_only=True) == []


def test_install_does_not_follow_preexisting_predictable_temp_symlink(tmp_path: Path):
    source = _source(tmp_path)
    target = tmp_path / "target"
    alpha = target / ".agents" / "skills" / "alpha"
    alpha.mkdir(parents=True)
    victim = tmp_path / "victim.txt"
    victim.write_bytes(b"protected bytes\n")
    temp_link = alpha / ".SKILL.md.covenant-flow-tmp"
    temp_link.symlink_to(victim)

    install_bridges(source, target)

    assert (alpha / "SKILL.md").is_file()
    assert victim.read_bytes() == b"protected bytes\n"
    assert temp_link.is_symlink()


def test_conflict_refuses_before_changing_other_bridges(tmp_path: Path):
    source = _source(tmp_path)
    target = tmp_path / "target"
    skills_root = target / ".agents" / "skills"
    conflict = skills_root / "alpha" / "SKILL.md"
    conflict.parent.mkdir(parents=True)
    conflict.write_text("operator-authored skill\n", encoding="utf-8")

    with pytest.raises(BridgeError, match="no files changed"):
        install_bridges(source, target)

    assert conflict.read_text(encoding="utf-8") == "operator-authored skill\n"
    assert not (skills_root / "design-critic" / "SKILL.md").exists()
    assert not (skills_root / codex_skills.MANIFEST).exists()


def test_preflight_allows_missing_bridges_without_writing_them(tmp_path: Path):
    source = _source(tmp_path)
    target = tmp_path / "target"

    result = install_bridges(source, target, preflight_only=True)

    assert result == ["preflight: 2 bridge(s) will be installed or updated"]
    assert not (target / ".agents" / "skills").exists()


def test_legacy_design_critic_is_reconciled_with_its_other_files_kept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = _source(tmp_path)
    target = tmp_path / "target"
    legacy = "legacy canonical copy\n"
    legacy_file = target / ".agents" / "skills" / "design-critic" / "SKILL.md"
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_text(legacy, encoding="utf-8")
    unrelated = legacy_file.parent / "agents" / "openai.yaml"
    unrelated.parent.mkdir(parents=True)
    unrelated.write_text("name: preserved\n", encoding="utf-8")
    monkeypatch.setattr(
        codex_skills,
        "LEGACY_DESIGN_CRITIC_SHA256",
        hashlib.sha256(legacy.encode()).hexdigest(),
    )

    changed = install_bridges(source, target)

    assert "reconcile legacy copy: .agents/skills/design-critic/SKILL.md" in changed
    assert legacy_file.read_text(encoding="utf-8").startswith("---\nname: design-critic\n")
    assert unrelated.read_text(encoding="utf-8") == "name: preserved\n"


def test_generated_bridges_stay_current_and_modified_bridges_refuse_update(tmp_path: Path):
    source = _source(tmp_path)
    target = tmp_path / "target"
    install_bridges(source, target)

    _write_skill(source, "alpha", "Updated alpha workflow")
    bridge = target / ".agents" / "skills" / "alpha" / "SKILL.md"
    bridge.write_text(bridge.read_text(encoding="utf-8") + "operator edit\n", encoding="utf-8")

    with pytest.raises(BridgeError, match="no files changed"):
        install_bridges(source, target)
    assert "operator edit" in bridge.read_text(encoding="utf-8")


def test_repository_skill_bridges_cover_all_canonical_names():
    expected = expected_bridges(REPO)

    assert len(expected) == 18
    assert install_bridges(REPO, REPO, check_only=True) == []
    manifest = json.loads(
        (REPO / ".agents" / "skills" / codex_skills.MANIFEST).read_text(encoding="utf-8")
    )
    assert set(manifest["files"]) == {f"{name}/SKILL.md" for name in expected}
