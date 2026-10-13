from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from review_process_checklist import _check_tasks, check  # noqa: E402


def _write_tasks(change_dir: Path, text: str) -> None:
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "tasks.md").write_text(text, encoding="utf-8")


@pytest.mark.parametrize(
    ("task", "due_phase", "barrier"),
    [
        ("4.2 Publish the pin <!-- covenant-flow:after-commit -->", "postcommit", "commit"),
        ("5.4 Run the pilot <!-- covenant-flow:after-pin -->", "postpin", "pin"),
        ("5.5 Update the board <!-- covenant-flow:after-qa -->", "postqa", "qa"),
    ],
)
def test_phase_annotation_only_defers_a_task_until_its_declared_barrier(
    tmp_path: Path, task: str, due_phase: str, barrier: str
):
    change = tmp_path / "change"
    _write_tasks(change, f"- [ ] {task}\n")

    assert _check_tasks(change, "precommit") is None
    if barrier == "pin":
        assert _check_tasks(change, "postcommit") is None
    if barrier == "qa":
        assert _check_tasks(change, "postcommit") is None
        assert _check_tasks(change, "postpin") is None
    assert _check_tasks(change, due_phase) == f"tasks.md task {task.split()[0]} pending at {due_phase}"
    assert _check_tasks(change) == "tasks.md pending"


@pytest.mark.parametrize(
    "task",
    [
        "1.4 Implement bridges",
        "1.4 Implement bridges <!-- covenant-flow:after-unknown -->",
        "1.4 Implement bridges <!-- covenant-flow:after-commit --> <!-- covenant-flow:after-pin -->",
    ],
)
def test_precommit_rejects_open_implementation_or_invalid_defer_annotation(
    tmp_path: Path, task: str
):
    change = tmp_path / "change"
    _write_tasks(change, f"- [ ] {task}\n")

    expected = "tasks.md phase annotation" if "covenant-flow:" in task else "tasks.md pending"
    assert _check_tasks(change, "precommit") == expected


def test_precommit_uses_open_spec_from_external_consumer_root(tmp_path: Path):
    repo = tmp_path / "product"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "card-1042-codex-adapter", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "checklist@test.local"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Checklist Test"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo), "add", "README.md"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-m", "baseline"],
        check=True,
        capture_output=True,
        text=True,
    )
    patch = repo / ".cursor" / "tmp" / "review-diff.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text("diff --git a/README.md b/README.md\n", encoding="utf-8")

    consumer = tmp_path / "consumer"
    change = consumer / "openspec" / "changes" / "card-1042-codex-adapter"
    _write_tasks(
        change,
        "\n".join(
            [
                "- [x] 1.1 Inventory installation paths",
                "- [ ] 4.2 Publish the pin <!-- covenant-flow:after-commit -->",
                "- [ ] 5.4 Run the pilot <!-- covenant-flow:after-pin -->",
                "- [ ] 5.5 Update the board <!-- covenant-flow:after-qa -->",
            ]
        )
        + "\n",
    )
    (change / "design.md").write_text(
        "UI impact: none\nlive_route: N/A harness-only; no product route\nsurface: none\n",
        encoding="utf-8",
    )

    assert check(
        repo,
        "yes",
        change_root=consumer,
        phase="precommit",
    ) is None
    assert check(repo, "yes", change_root=consumer) == "tasks.md pending"

    tasks = change / "tasks.md"
    tasks.write_text(
        tasks.read_text(encoding="utf-8") + "- [ ] 3.2 Run reviewers\n",
        encoding="utf-8",
    )
    assert check(
        repo,
        "yes",
        change_root=consumer,
        phase="precommit",
    ) == "tasks.md pending"


# --- pilot_evidence gate (card #1101, design 12) ------------------------------------------

import json  # noqa: E402

from review_process_checklist import PILOT_GATE_FILE, main as checklist_main  # noqa: E402

SHA_A, SHA_B = "a" * 40, "b" * 40


def _child(role, client="claude", **extra):
    return {"activity": role, "client": client, "child_id": f"{role}-id", "observed_model": "m", "observed_effort": "high", "status": "completed", **extra}


def _pilot():
    roles = ["grill-card", "design-autor", "design-critic", "apply-coluna", "diff-reviewer", "code-reviewer", "qa-gate"]
    return {"card": "1110", "sha": SHA_A, "children": [_child(r) for r in roles]}


def _switch():
    design = [_child("design-autor", "cursor"), _child("design-critic", "codex")]
    rest = [_child(r) for r in ("apply-coluna", "diff-reviewer", "code-reviewer", "qa-gate")]
    return {"card": "1111", "sha": SHA_B, "children": design + rest}


def _gated(tmp_path, *, declared=True, tasks="- [x] 1.1 done\n"):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "card-1101-claude-code-adapter", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "--allow-empty", "-m", "i"], check=True, capture_output=True)
    patch = repo / ".cursor/tmp/review-diff.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text("diff --git a/README.md b/README.md\n")
    change = repo / "openspec/changes/card-1101-claude-code-adapter"
    _write_tasks(change, tasks)
    (change / "design.md").write_text("UI impact: none\nlive_route: N/A harness-only\nsurface: none\n")
    if declared:
        (change / PILOT_GATE_FILE).write_text(json.dumps({"version": 1, "gate": "pilot_evidence", "card": "1101"}))
    return repo


def _evidence(tmp_path, pilot=None, switch=None, **top):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps({"version": 1, "pilot": pilot if pilot is not None else _pilot(), "switch": switch if switch is not None else _switch(), **top}))
    return path


GREEN = lambda sha: True  # noqa: E731


def test_gate_is_inactive_without_the_declaration_and_before_postqa(tmp_path):
    (tmp_path / "u").mkdir()
    undeclared = _gated(tmp_path / "u", declared=False)
    assert check(undeclared, "yes", phase="postqa") is None
    declared = _gated(tmp_path)
    for phase in ("precommit", "postcommit", "postpin"):
        assert check(declared, "yes", phase=phase) is None


def test_declared_gate_requires_evidence_at_postqa_and_strict(tmp_path):
    repo = _gated(tmp_path)
    assert check(repo, "yes", phase="postqa") == "pilot_evidence"
    assert check(repo, "yes") == "pilot_evidence"
    assert check(repo, "yes", phase="postqa", pilot_evidence=_evidence(tmp_path), qa_green=GREEN) is None
    assert check(repo, "yes", pilot_evidence=_evidence(tmp_path), qa_green=GREEN) is None


def test_cli_failure_message_and_success(tmp_path, capsys, monkeypatch):
    repo = _gated(tmp_path)
    assert checklist_main(["--root", str(repo), "--wave-same-turn", "yes", "--phase", "postqa"]) == 1
    assert capsys.readouterr().out.strip() == "ERROR: process-checklist failed: pilot_evidence"
    import review_process_checklist as rpc
    monkeypatch.setattr(rpc, "qa_gate_green_for_sha", lambda sha: True)
    assert checklist_main(["--root", str(repo), "--wave-same-turn", "yes", "--phase", "postqa", "--pilot-evidence", str(_evidence(tmp_path))]) == 0


def _mutated(**mut):
    pilot, switch = _pilot(), _switch()
    for key, fn in mut.items():
        fn(pilot if key == "pilot" else switch)
    return pilot, switch


@pytest.mark.parametrize("name,mutation", [
    ("pilot_card_is_the_gated_card", lambda p, s: p.update(card="1101")),
    ("same_card", lambda p, s: s.update(card=p["card"])),
    ("same_sha", lambda p, s: s.update(sha=p["sha"])),
    ("bad_sha", lambda p, s: p.update(sha="abc")),
    ("missing_children", lambda p, s: p.update(children=[])),
    ("missing_switch", lambda p, s: s.clear()),
    ("pilot_child_not_claude", lambda p, s: p["children"][1].update(client="cursor")),
    ("pilot_unobserved_model", lambda p, s: p["children"][3].update(observed_model="unavailable")),
    ("pilot_not_completed", lambda p, s: p["children"][3].update(status="failed")),
    ("pilot_missing_qa_proxy", lambda p, s: p["children"].pop()),
    ("pilot_missing_reviewer", lambda p, s: p["children"].pop(4)),
    ("switch_design_on_claude", lambda p, s: s["children"][0].update(client="claude")),
    ("switch_apply_on_cursor", lambda p, s: s["children"][2].update(client="cursor")),
    ("switch_review_on_codex", lambda p, s: s["children"][4].update(client="codex")),
    ("switch_missing_design_critic", lambda p, s: s["children"].pop(1)),
    ("child_without_id", lambda p, s: p["children"][0].pop("child_id")),
])
def test_missing_or_wrong_evidence_fails_the_gate(tmp_path, capsys, name, mutation):
    repo = _gated(tmp_path)
    pilot, switch = _pilot(), _switch()
    mutation(pilot, switch)
    assert check(repo, "yes", phase="postqa", pilot_evidence=_evidence(tmp_path, pilot, switch), qa_green=GREEN) == "pilot_evidence", name
    assert "pilot_evidence detail" in capsys.readouterr().err


def test_a_sha_without_qa_green_fails_and_the_verifier_sees_both_shas(tmp_path):
    repo = _gated(tmp_path)
    seen = []
    assert check(repo, "yes", phase="postqa", pilot_evidence=_evidence(tmp_path), qa_green=lambda sha: seen.append(sha) or sha == SHA_A) == "pilot_evidence"
    assert check(repo, "yes", phase="postqa", pilot_evidence=_evidence(tmp_path), qa_green=lambda sha: sha == SHA_B) == "pilot_evidence"
    assert SHA_A in seen


@pytest.mark.parametrize("content", ["{ not json", "[]", json.dumps({"version": 2}), ""])
def test_unreadable_evidence_fails_the_gate(tmp_path, content):
    repo = _gated(tmp_path)
    path = tmp_path / "bad.json"
    path.write_text(content)
    assert check(repo, "yes", phase="postqa", pilot_evidence=path, qa_green=GREEN) == "pilot_evidence"
    assert check(repo, "yes", phase="postqa", pilot_evidence=tmp_path / "nope.json", qa_green=GREEN) == "pilot_evidence"


def test_default_verifier_asks_the_checks_api_for_a_completed_successful_qa_gate(monkeypatch):
    import t14
    import review_process_checklist as rpc
    outputs = iter([
        '{"name":"lint","status":"completed","conclusion":"success"}\n{"name":"qa-gate","status":"completed","conclusion":"success"}\n',
        '{"name":"qa-gate","status":"completed","conclusion":"failure"}\n',
        '{"name":"qa-gate","status":"in_progress","conclusion":null}\n',
        '{"name":"lint","status":"completed","conclusion":"success"}\n',
    ])
    calls = []

    def fake_run(args, **kw):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, next(outputs), "")

    monkeypatch.setattr(t14, "_run", fake_run)
    monkeypatch.setattr(t14, "_overlay_repo", lambda: "owner/repo")
    assert [rpc.qa_gate_green_for_sha(SHA_A) for _ in range(4)] == [True, False, False, False]
    assert calls[0][:3] == ["gh", "api", f"repos/owner/repo/commits/{SHA_A}/check-runs"]
    monkeypatch.setattr(t14, "_run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "boom"))
    assert rpc.qa_gate_green_for_sha(SHA_A) is False
