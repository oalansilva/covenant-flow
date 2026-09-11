"""#879: subagentStop destape + Code Review review-diff contract. No GitHub."""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from subagent_stop import (  # noqa: E402
    FOLLOWUP_APPLY,
    FOLLOWUP_DESIGN_AUTOR,
    FOLLOWUP_DESIGN_CRITIC,
    FOLLOWUP_GRILL,
    FOLLOWUP_QA,
    FOLLOWUP_REVIEW,
    classify_etapa,
    decide,
    handle,
    sidecar_path,
)

SKILL = REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md"
HOOKS = REPO / ".cursor" / "hooks.json"
STOP_SH = REPO / ".cursor" / "hooks" / "process-fsm-subagent-stop.sh"
DIFF_AGENT = REPO / ".cursor" / "agents" / "diff-reviewer.md"
CODE_AGENT = REPO / ".cursor" / "agents" / "code-reviewer.md"

FORBIDDEN_Q = ("concluiu?", "já acabou?", "verifique se nao concluiu")

ETAPA_CASES = (
    ("grill-card 879", FOLLOWUP_GRILL),
    ("grelha issue 879", FOLLOWUP_GRILL),
    ("apply-coluna 879", FOLLOWUP_APPLY),
    ("diff-reviewer 879", FOLLOWUP_REVIEW),
    ("code-reviewer 879", FOLLOWUP_REVIEW),
    ("qa-gate 879", FOLLOWUP_QA),
    ("Design-autor 879", FOLLOWUP_DESIGN_AUTOR),
    ("design-autor sem-tela", FOLLOWUP_DESIGN_AUTOR),
    ("design-critic sem-tela", FOLLOWUP_DESIGN_CRITIC),
    ("Assessment A 879", FOLLOWUP_DESIGN_CRITIC),
    ("Assessment B 879", FOLLOWUP_DESIGN_CRITIC),
)


def _write_sidecar(root: Path, task: str, description: str) -> Path:
    path = sidecar_path({}, root=root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"task": task, "description": description}, ensure_ascii=True),
        encoding="utf-8",
    )
    return path


def _payload(
    *,
    description: str,
    status: str = "completed",
    loop_count: int = 0,
    task: str = "generalPurpose",
    extra: dict | None = None,
) -> dict:
    body = {
        "status": status,
        "loop_count": loop_count,
        "task": task,
        "description": description,
    }
    if extra:
        body.update(extra)
    return body


def _cli(raw: str, *, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / "subagent_stop.py")],
        input=raw,
        capture_output=True,
        text=True,
        cwd=str(REPO),
        env=env,
        check=False,
    )


@pytest.mark.parametrize("description,expected", ETAPA_CASES)
def test_completed_sidecar_emits_exact_order(tmp_path: Path, description: str, expected: str) -> None:
    task = "generalPurpose"
    _write_sidecar(tmp_path, task, description)
    out = decide(_payload(description=description, task=task), root=tmp_path)
    assert out == {"followup_message": expected}
    assert expected not in FORBIDDEN_Q
    for bad in FORBIDDEN_Q:
        assert bad not in expected
    assert not sidecar_path({}, root=tmp_path).exists()


def test_design_autor_is_not_empty() -> None:
    assert classify_etapa("Design-autor 879") == "design_autor"
    assert classify_etapa("Design-autor 879") != None  # noqa: E711
    assert FOLLOWUP_DESIGN_AUTOR != "{}"
    assert FOLLOWUP_DESIGN_AUTOR.startswith("O filho Design-autor já devolveu.")


def test_bare_design_does_not_classify() -> None:
    assert classify_etapa("Design") is None
    assert classify_etapa("Design session") is None


def test_design_autor_matches_before_critic() -> None:
    assert classify_etapa("Design-autor then design-critic") == "design_autor"


def test_no_sidecar_is_empty(tmp_path: Path) -> None:
    out = decide(_payload(description="grill-card 879"), root=tmp_path)
    assert out == {}


def test_sidecar_mismatch_is_empty(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, "generalPurpose", "grill-card 879")
    out = decide(_payload(description="qa-gate 879"), root=tmp_path)
    assert out == {}
    assert sidecar_path({}, root=tmp_path).exists()


LONG_PROMPT = "<long prompt>"


def test_cursor_shaped_stop_task_is_title_not_type(tmp_path: Path) -> None:
    sidecar_description = "diff-reviewer card 879"
    _write_sidecar(tmp_path, "generalPurpose", sidecar_description)
    out = decide(
        {
            "status": "completed",
            "loop_count": 0,
            "task": "diff-reviewer card 879",
            "subagent_type": "generalPurpose",
            "description": LONG_PROMPT,
        },
        root=tmp_path,
    )
    assert out == {"followup_message": FOLLOWUP_REVIEW}
    assert not sidecar_path({}, root=tmp_path).exists()


def test_cursor_shaped_named_subagent_type(tmp_path: Path) -> None:
    sidecar_description = "diff-reviewer card 879"
    _write_sidecar(tmp_path, "diff-reviewer", sidecar_description)
    out = decide(
        {
            "status": "completed",
            "loop_count": 0,
            "task": "diff-reviewer card 879",
            "subagent_type": "diff-reviewer",
            "description": LONG_PROMPT,
        },
        root=tmp_path,
    )
    assert out == {"followup_message": FOLLOWUP_REVIEW}
    assert not sidecar_path({}, root=tmp_path).exists()


def test_unrelated_generalpurpose_does_not_widen(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, "generalPurpose", "grill-card 879")
    out = decide(
        {
            "status": "completed",
            "loop_count": 0,
            "task": "Search files",
            "subagent_type": "generalPurpose",
        },
        root=tmp_path,
    )
    assert out == {}
    assert sidecar_path({}, root=tmp_path).exists()


@pytest.mark.parametrize(
    "sidecar_description,expected",
    (
        ("apply-coluna 879", FOLLOWUP_APPLY),
        ("diff-reviewer 879", FOLLOWUP_REVIEW),
    ),
)
def test_stop_task_equals_sidecar_description_despite_long_prompt(
    tmp_path: Path,
    sidecar_description: str,
    expected: str,
) -> None:
    _write_sidecar(tmp_path, "generalPurpose", sidecar_description)
    out = decide(
        {
            "status": "completed",
            "loop_count": 0,
            "task": sidecar_description,
            "subagent_type": "generalPurpose",
            "description": LONG_PROMPT,
        },
        root=tmp_path,
    )
    assert out == {"followup_message": expected}
    assert not sidecar_path({}, root=tmp_path).exists()


def test_short_unrelated_stop_description_does_not_widen(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, "generalPurpose", "apply-coluna 879")
    out = decide(
        _payload(description="Apply OpenSpec change", task="generalPurpose"),
        root=tmp_path,
    )
    assert out == {}
    assert sidecar_path({}, root=tmp_path).exists()


def test_fuzzy_title_does_not_match(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, "generalPurpose", "grill-card 879")
    out = decide(
        _payload(description="Grill card", task="Grill card"),
        root=tmp_path,
    )
    assert out == {}
    assert sidecar_path({}, root=tmp_path).exists()


@pytest.mark.parametrize(
    "sidecar",
    (
        {},
        {"task": "generalPurpose"},
        {"task": "generalPurpose", "description": ""},
        {"task": "generalPurpose", "description": "   "},
    ),
)
def test_empty_partial_sidecar_is_empty(tmp_path: Path, sidecar: dict) -> None:
    path = sidecar_path({}, root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sidecar, ensure_ascii=True), encoding="utf-8")
    out = decide(_payload(description="grill-card 879"), root=tmp_path)
    assert out == {}
    assert path.exists()


def test_sidecar_description_only_matches(tmp_path: Path) -> None:
    path = sidecar_path({}, root=tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"description": "grill-card 879"}, ensure_ascii=True),
        encoding="utf-8",
    )
    out = decide(_payload(description="grill-card 879"), root=tmp_path)
    assert out == {"followup_message": FOLLOWUP_GRILL}
    assert not path.exists()


def test_nested_tool_input_title_matches(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, "generalPurpose", "grill-card 879")
    out = decide(
        {
            "status": "completed",
            "loop_count": 0,
            "subagent_type": "generalPurpose",
            "tool_input": {"task": "grill-card 879", "description": LONG_PROMPT},
        },
        root=tmp_path,
    )
    assert out == {"followup_message": FOLLOWUP_GRILL}
    assert not sidecar_path({}, root=tmp_path).exists()


@pytest.mark.parametrize("status", ("error", "aborted", "running", "in_progress"))
def test_non_completed_is_empty(tmp_path: Path, status: str) -> None:
    _write_sidecar(tmp_path, "generalPurpose", "grill-card 879")
    out = decide(_payload(description="grill-card 879", status=status), root=tmp_path)
    assert out == {}
    assert sidecar_path({}, root=tmp_path).exists()


def test_still_working_is_absence_of_completed() -> None:
    """P3: ainda a trabalhar = ausência de subagentStop completed, não stdin inventado."""
    assert decide({"description": "grill-card 879"}, root=Path("/no/sidecar")) == {}


def test_loop_count_positive_is_empty(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, "generalPurpose", "grill-card 879")
    out = decide(_payload(description="grill-card 879", loop_count=1), root=tmp_path)
    assert out == {}


def test_missing_loop_count_destapes_when_other_guards_hold(tmp_path: Path) -> None:
    task = "generalPurpose"
    description = "grill-card 879"
    _write_sidecar(tmp_path, task, description)
    body = _payload(description=description, task=task)
    del body["loop_count"]
    assert "loop_count" not in body
    assert "loopCount" not in body
    out = decide(body, root=tmp_path)
    assert out == {"followup_message": FOLLOWUP_GRILL}


def test_parallel_worker_is_empty(tmp_path: Path) -> None:
    _write_sidecar(tmp_path, "generalPurpose", "grill-card 879")
    out = decide(
        _payload(description="grill-card 879", extra={"is_parallel_worker": True}),
        root=tmp_path,
    )
    assert out == {}


@pytest.mark.parametrize("kind", ("explore", "shell"))
def test_explore_shell_is_empty(tmp_path: Path, kind: str) -> None:
    _write_sidecar(tmp_path, kind, "grill-card 879")
    out = decide(_payload(description="grill-card 879", task=kind), root=tmp_path)
    assert out == {}


def test_invalid_json_fail_open() -> None:
    assert handle("not-json") == {}
    assert handle("") == {}
    assert handle("[]") == {}


def test_crash_fail_open(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr("subagent_stop.decide", boom)
    assert handle('{"status":"completed","loop_count":0}', root=tmp_path) == {}


def test_cli_prints_one_json_object(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    description = "grill-card 879"
    _write_sidecar(tmp_path, "generalPurpose", description)
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PROCESS_FSM_ROOT"] = str(tmp_path)
    proc = _cli(
        json.dumps(_payload(description=description)),
        env=env,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert data == {"followup_message": FOLLOWUP_GRILL}


def test_cli_invalid_json_is_empty_object() -> None:
    proc = _cli("{{{")
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {}


def test_hook_script_locator_and_fail_open() -> None:
    text = STOP_SH.read_text(encoding="utf-8")
    assert 'ROOT="$(cd "$(dirname "$0")/../.." && pwd)"' in text
    assert "ROOT/backend/.venv/bin/python" in text
    assert "command -v python3" in text
    assert "subagent_stop.py" in text
    assert "failClosed" not in text
    assert STOP_SH.stat().st_mode & stat.S_IXUSR


def test_hook_script_always_emits_json(tmp_path: Path) -> None:
    hooks = tmp_path / ".cursor" / "hooks"
    hooks.mkdir(parents=True)
    script = hooks / "process-fsm-subagent-stop.sh"
    script.write_text(STOP_SH.read_text(encoding="utf-8"), encoding="utf-8")
    script.chmod(0o755)
    proc = subprocess.run(
        [str(script)],
        input="{}",
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
        check=False,
    )
    assert proc.returncode == 0
    assert json.loads(proc.stdout) == {}


def test_agents_require_review_diff_and_forbid_git_transcripts() -> None:
    for path in (DIFF_AGENT, CODE_AGENT):
        text = path.read_text(encoding="utf-8")
        assert "readonly: true" in text
        assert "model: inherit" in text
        assert "ERROR: review-diff missing" in text
        assert "MUST NOT git" in text
        assert "MUST NOT transcripts" in text
        assert "agent-transcripts" in text
        assert "review_diff_path:" in text
        assert "## Diff" in text


def test_skill_s1_parent_materializes_diff() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert "## Modos Cursor (terminal vs Desktop+SSH)" in text
    assert "### Pasta (Q2)" in text
    assert "review_diff_path:" in text
    assert "MAY spawnar" in text
    assert "subagent_type` nomeado" in text
    assert ".cursor/tmp/review-diff.patch" in text
    assert "git diff HEAD" in text
    assert "git ls-files --others --exclude-standard" in text
    assert "git diff origin/develop...HEAD" in text
    assert "MUST NOT pedir git ao filho" in text
    assert "v1.1.14" in text


def test_skill_s2_sidecar_and_order() -> None:
    text = SKILL.read_text(encoding="utf-8")
    assert ".cursor/tmp/awaiting-task.json" in text
    assert "concluiu?" in text
    assert "já acabou?" in text
    assert "Design-autor" in text
    assert "Assessment A/B" in text
    assert "MUST NOT re-prompt" in text
    assert "background" in text
    assert "aborted" in text
    assert "hang do host" in text
    assert "clients.*.auto" in text
    assert "No `description` do Task" in text
    assert "MUST constar um needle do classificador" in text
    assert "MUST NOT classificar" in text
    assert "prompt longo" in text
    assert "MUST NOT destapar" in text
    assert "string exacta" in text
    assert "subagent_type" in text
    assert "não o título" in text
    for needle in (
        "grill-card",
        "apply-coluna",
        "diff-reviewer",
        "code-reviewer",
        "qa-gate",
        "design-autor",
        "design-critic",
        "Assessment A",
        "Assessment B",
    ):
        assert needle in text
    assert "Sidecar **por** Task" in text
    assert "MUST NOT ser skip" in text
    assert "commit só depois dos dois" in text


def test_hooks_matcher_covers_named_reviewers() -> None:
    hooks = json.loads(HOOKS.read_text(encoding="utf-8"))
    destape = hooks["hooks"]["subagentStop"]
    matcher = destape[0]["matcher"]
    assert "generalPurpose" in matcher
    assert "diff-reviewer" in matcher
    assert "code-reviewer" in matcher
    assert destape[0]["loop_limit"] == 32
    assert destape[0].get("failClosed") is not True
    assert "subagentStart" not in hooks["hooks"]


PASTED_SKILL_PROMPT = (
    "# Covenant Flow\n"
    "lista fechada: grill-card, Design-autor, Apply-coluna, QA, "
    "Assessment A/B, `diff-reviewer`, `code-reviewer`.\n"
    "Needles colados do SKILL.md: design-autor, design-critic, "
    "diff-reviewer, code-reviewer, apply-coluna, qa-gate.\n"
)


def test_pasted_skill_prompt_does_not_reclassify_grill(tmp_path: Path) -> None:
    sidecar_description = "grill-card 879"
    _write_sidecar(tmp_path, "generalPurpose", sidecar_description)
    assert "design-autor" in PASTED_SKILL_PROMPT
    assert "diff-reviewer" in PASTED_SKILL_PROMPT
    assert classify_etapa(PASTED_SKILL_PROMPT) == "design_autor"
    out = decide(
        {
            "status": "completed",
            "loop_count": 0,
            "task": "grill-card 879",
            "subagent_type": "generalPurpose",
            "description": PASTED_SKILL_PROMPT,
        },
        root=tmp_path,
    )
    assert out == {"followup_message": FOLLOWUP_GRILL}
    assert out != {"followup_message": FOLLOWUP_DESIGN_AUTOR}
    assert not sidecar_path({}, root=tmp_path).exists()


def test_followups_never_ask_if_done() -> None:
    for msg in (
        FOLLOWUP_GRILL,
        FOLLOWUP_APPLY,
        FOLLOWUP_REVIEW,
        FOLLOWUP_QA,
        FOLLOWUP_DESIGN_AUTOR,
        FOLLOWUP_DESIGN_CRITIC,
    ):
        for bad in FORBIDDEN_Q:
            assert bad not in msg
