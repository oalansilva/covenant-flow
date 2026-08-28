"""Generate and check Grok skill stubs that point at canonical skills (not a second runbook)."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parents[1]
CURSOR_SKILLS = REPO_ROOT / ".cursor" / "skills"
GROK_SKILLS = REPO_ROOT / ".grok" / "skills"

# Extra Grok stubs whose canonical file lives under .agents/skills (card #673).
AGENTS_EXTRA_SKILLS: tuple[tuple[str, str], ...] = (
    ("design-critic", ".agents/skills/design-critic"),
    ("impeccable", ".agents/skills/impeccable"),
)

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def _description_raw(text: str) -> str:
    match = FRONTMATTER_RE.match(text)
    if not match:
        return '"Delegate to the canonical SKILL.md"'
    block = match.group(1)
    found = re.search(r"^description:\s*(.*)$", block, re.MULTILINE)
    if not found:
        return '"Delegate to the canonical SKILL.md"'
    return found.group(1).strip()


def stub_body(name: str, canonical_dir: str) -> str:
    return (
        f"# {name}\n"
        "\n"
        f"Cliente: Grok Build. MUST Read `{canonical_dir}/SKILL.md` and follow it as the runbook.\n"
        "Map Cursor Task `inherit` to `spawn_subagent` inherit. Do not copy the runbook here.\n"
    )


def render_stub(name: str, description_raw: str, canonical_dir: str) -> str:
    return (
        f"---\nname: {name}\ndescription: {description_raw}\n---\n\n"
        f"{stub_body(name, canonical_dir)}"
    )


def canonical_skills() -> list[Path]:
    return sorted(path for path in CURSOR_SKILLS.glob("*/SKILL.md") if path.is_file())


def stub_sources() -> dict[str, tuple[Path, str]]:
    """name -> (canonical SKILL.md, repo-relative directory of that skill)."""
    out: dict[str, tuple[Path, str]] = {}
    for skill_md in canonical_skills():
        name = skill_md.parent.name
        out[name] = (skill_md, f".cursor/skills/{name}")
    for name, rel in AGENTS_EXTRA_SKILLS:
        out[name] = (REPO_ROOT / rel / "SKILL.md", rel)
    return out


def expected_stubs() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, (skill_md, canonical_dir) in stub_sources().items():
        text = skill_md.read_text(encoding="utf-8") if skill_md.is_file() else ""
        out[name] = render_stub(name, _description_raw(text), canonical_dir)
    return out


def write_stubs() -> None:
    for name, content in expected_stubs().items():
        dest = GROK_SKILLS / name / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def stub_errors() -> list[str]:
    errors: list[str] = []
    sources = stub_sources()
    expected = expected_stubs()
    for name, content in expected.items():
        dest = GROK_SKILLS / name / "SKILL.md"
        _skill_md, canonical_dir = sources[name]
        pointer = f"{canonical_dir}/SKILL.md"
        if not dest.is_file():
            errors.append(f"missing {dest.relative_to(REPO_ROOT)}")
            continue
        actual = dest.read_text(encoding="utf-8")
        if actual != content:
            errors.append(f"stale {dest.relative_to(REPO_ROOT)}")
        nonempty = [ln for ln in actual.splitlines() if ln.strip()]
        try:
            body = actual.split("---", 2)[2]
        except IndexError:
            body = actual
        body_lines = [ln for ln in body.splitlines() if ln.strip()]
        if len(body_lines) > 8:
            errors.append(f"body too long {dest.relative_to(REPO_ROOT)}")
        if pointer not in actual:
            errors.append(f"missing pointer {dest.relative_to(REPO_ROOT)}")
        if "Em Refinamento → Todo → Design" in actual:
            errors.append(f"runbook copy {dest.relative_to(REPO_ROOT)}")
        del nonempty
    return errors


if __name__ == "__main__":
    write_stubs()
    problems = stub_errors()
    if problems:
        raise SystemExit("\n".join(problems))
