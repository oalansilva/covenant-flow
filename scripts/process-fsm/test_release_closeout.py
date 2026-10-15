"""Card #1059 release-closeout table, runbook needles, and harness regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from model_selection_fixtures import machine_models
from model_selection import resolve, save_capture

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
sys.path.insert(0, str(ROOT))

from release_closeout import (  # noqa: E402
    CLIENT_CODEX,
    CLIENT_CURSOR,
    CODEX_QUESTION_SCHEMA,
    CURSOR_QUESTION_SCHEMA,
    ContextIdentity,
    Manifest,
    PreflightItem,
    QuestionItem,
    archive_write_plan,
    card_outside_package_is_left_alone,
    check_runtime_model,
    classify_tool_error,
    completed_homologado_change_blocks,
    decision_table_for_client,
    diagnose_guard_decision,
    documental_checks_proposal,
    encode_question,
    evaluate_decision,
    format_operation_deny,
    gh_supports_flag,
    is_placeholder_text,
    manifesto_path,
    pronto_body_is_complete,
    pronto_evidence_args,
    reconcile_field,
    resume_manifest,
    run_preflight,
    save_manifest,
    should_post_homologado,
    simulate_merge_against_target,
    validate_question_payload,
)
from t16 import LiveT16Closer, T16Error  # noqa: E402

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")

SKILL = REPO / ".cursor" / "skills" / "covenant-flow" / "SKILL.md"
OVERLAY = REPO / "docs" / "crypto-overlay.md"
AGENTS = REPO / "AGENTS.md"
HELPER = REPO / "scripts" / "post-card-evidence-comment.sh"
RELEASE_GUARD = REPO / "scripts" / "release-guard"


def _release_section() -> str:
    text = SKILL.read_text(encoding="utf-8")
    return text.split("## Release", 1)[1]


def test_release_section_drops_t18_label_and_uses_birth_capture():
    release = _release_section()
    assert "Pré-requisito (T18)" not in release
    assert "juizo" in release.lower() or "juízo" in release
    assert "check_runtime_model(..., capture=...)" in release
    assert "Nenhum modelo de outro cliente é obrigatório" in release
    assert "nao_homologar" in SKILL.read_text(encoding="utf-8")
    assert "Pré-requisito (T18)" not in AGENTS.read_text(encoding="utf-8")


def _overlay_text() -> str:
    # The overlay doc is consumer-owned product data: absent in the nucleus checkout.
    return OVERLAY.read_text(encoding="utf-8") if OVERLAY.is_file() else ""


def test_release_section_and_overlay_archive_use_1022_decide():
    release = _release_section()
    overlay = _overlay_text()
    for text in (release, overlay) if overlay else (release,):
        assert "decide()" in text
        assert "#1022" in text
        assert "worktree" in text.lower()
        assert "cherry-pick" in text
        assert "segunda allow-list" in text or "second allow-list" in text
    assert "Sync now / Archive without syncing" in release
    assert "após os cards do pacote moverem para `Pronto`" not in overlay
    assert "Limpar branches após publicação/Pronto" not in overlay


def test_release_branch_deletion_before_post_and_pronto():
    release = _release_section()
    overlay = _overlay_text()
    for text in (release, overlay) if overlay else (release,):
        assert "antes" in text and "post" in text and "Pronto" in text
        assert "PRESERVED_BRANCHES" in text
        assert "qa-gate" in text
        assert "MUST NOT desligar `qa-gate`" in text or "MUST NOT desligar `qa-gate`" in overlay


def test_decision_table_proceeds_without_reconfirming_authorized_work():
    decision = evaluate_decision(authorized=True, data_available=True)
    assert decision.action == "proceed"
    cursor = decision_table_for_client(CLIENT_CURSOR)
    codex = decision_table_for_client(CLIENT_CODEX)
    assert cursor["table"] == codex["table"]
    assert cursor["map_key"] == "execucao"
    assert codex["map_key"] == "execucao.codex"
    assert cursor["encoding"] != codex["encoding"]


def test_decision_table_asks_real_gaps_once_and_stops_on_external_block():
    gaps = (
        {"card": "1017", "field": "responsavel", "prompt": "Responsável"},
        {"card": "1042", "field": "classificacao", "prompt": "Classificação"},
    )
    first = evaluate_decision(authorized=True, data_available=True, gaps=gaps)
    assert first.action == "ask_once"
    assert {item["card"] for item in first.gaps} == {"1017", "1042"}
    second = evaluate_decision(
        authorized=True,
        data_available=True,
        gaps=gaps,
        already_asked=("1017:responsavel", "1042:classificacao"),
    )
    assert second.action == "stop"
    assert second.reason == "real_gap"
    assert second.reason != "authorized"
    assert {item["card"] for item in second.gaps} == {"1017", "1042"}
    independent = evaluate_decision(authorized=True, data_available=True)
    assert independent.action == "proceed"
    blocked = evaluate_decision(
        authorized=True,
        data_available=True,
        external_blocker="archive deny points at #1022",
    )
    assert blocked.action == "stop"
    assert "#1022" in blocked.blocker
    silent = evaluate_decision(
        authorized=True,
        data_available=True,
        gaps=gaps,
        already_asked=(),
    )
    assert silent.action == "ask_once"


def test_reconcile_human_per_card_beats_inference_and_undistributed_stays_gap():
    human = reconcile_field(
        card="1017",
        field="classificacao",
        sources=(
            {"kind": "human", "card": "1017", "value": "harness", "origin": "alan-comment"},
            {"kind": "inference", "card": "1017", "value": "produto"},
        ),
    )
    assert human.value == "harness"
    assert human.attributed_to_alan is True
    undistributed = reconcile_field(
        card="1017",
        field="classificacao",
        sources=({"kind": "human", "card": "", "value": "harness", "origin": "chat"},),
    )
    assert undistributed.gap is True
    assert undistributed.attributed_to_alan is False
    assert undistributed.origin == "undistributed_human_reply"


def test_question_schema_rejects_incompatible_and_duplicate_fields():
    ok, _ = validate_question_payload(
        CURSOR_QUESTION_SCHEMA,
        {"title": "x", "questions": [{"id": "a", "prompt": "p", "options": [{"id": "1", "label": "1"}]}]},
    )
    assert ok is True
    bad, err = validate_question_payload(
        CURSOR_QUESTION_SCHEMA,
        {"title": "x", "questions": [], "unexpected": 1},
    )
    assert bad is False
    assert "incompatible field" in err
    items = (
        QuestionItem(
            card="1017",
            field="responsavel",
            prompt="Quem responde?",
            options=("Clara", "Alan"),
            recommended="Clara",
        ),
    )
    encoded = encode_question(CLIENT_CURSOR, items, tool_available=False)
    assert encoded["sent"] is False
    assert encoded["accepted_recommendation"] is False
    assert "Clara" in encoded["text"] and "Alan" in encoded["text"]
    extra = validate_question_payload(CODEX_QUESTION_SCHEMA, {"question": "q", "choices": ["a"], "foo": 1})
    assert extra[0] is False
    dup_ids, dup_err = validate_question_payload(
        CURSOR_QUESTION_SCHEMA,
        {
            "title": "x",
            "questions": [
                {"id": "a", "prompt": "p", "options": [{"id": "1", "label": "1"}]},
                {"id": "a", "prompt": "q", "options": [{"id": "1", "label": "1"}]},
            ],
        },
    )
    assert dup_ids is False
    assert "duplicate field" in dup_err


def test_manifest_resumes_without_secrets_or_transcript(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    manifest = Manifest(
        package="2026-09-27",
        decisions={"1017:classificacao": "harness"},
        origins={"1017:classificacao": "alan-comment"},
        evidence_refs=["origin/main=abc1234"],
        completed_steps=["comments", "fields"],
        context={"package": "2026-09-27", "cwd": str(tmp_path), "head": "aaa", "refs": []},
        asked_gaps=["1017:classificacao"],
    )
    path = save_manifest(
        Manifest(
            **{
                **manifest.as_dict(),
                "decisions": {**manifest.decisions, "token": "ghp_secret", "transcript": "private"},
            }
        )
    )
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert "token" not in json.dumps(stored)
    assert "transcript" not in stored
    assert "ghp_secret" not in path.read_text(encoding="utf-8")
    current = ContextIdentity(
        package="2026-09-27",
        cwd=str(tmp_path / "other"),
        head="bbb",
        refs=(),
    )
    updated, step, note = resume_manifest("2026-09-27", current_context=current)
    assert "cwd" in note
    assert step == "documentation"
    assert str(manifesto_path("2026-09-27")).startswith(str(tmp_path / "state"))
    assert updated.package == "2026-09-27"


def test_operation_deny_does_not_generalize_to_archive():
    message = format_operation_deny(
        operation="write_produto",
        path="backend/app/main.py",
        q="Homologado",
        q_git="release-2026-09-27",
        bound_card="⊥",
        rule="I1",
        cause="product write on integration branch",
        corrective="do not treat this as a deny of archive",
    )
    assert "operation=write_produto" in message
    assert "q_git=release-2026-09-27" in message
    diagnosed = diagnose_guard_decision(
        operation="write_produto",
        path="backend/app/main.py",
        decision={"decision": "deny", "reason": "process-fsm-guard deny reason=I1 q=Homologado"},
        q="Homologado",
        q_git="release-2026-09-27",
        bound_card="⊥",
    )
    assert diagnosed["generalizes"] is False
    assert "archive" not in diagnosed["message"] or "another operation" in diagnosed["message"]


def test_archive_plan_points_unresolved_and_fail_closed_at_1022():
    unresolved = archive_write_plan(
        decide_result={"decision": "deny", "reason": "fail_closed"},
        package_resolved=False,
        card_resolved=False,
        q_git="release-2026-09-27",
        bound_card="⊥",
    )
    assert unresolved.proceed is False
    assert unresolved.points_at_1022 is True
    assert unresolved.worktree_cherry_pick is False
    fail_closed = archive_write_plan(
        decide_result={"decision": "deny", "reason": "fail_closed"},
        package_resolved=True,
        card_resolved=True,
        q_git="release-2026-09-27",
        bound_card="⊥",
    )
    assert fail_closed.proceed is False
    assert fail_closed.points_at_1022 is True
    conflict = archive_write_plan(
        decide_result={"decision": "allow"},
        package_resolved=True,
        card_resolved=True,
        q_git="release-2026-09-27",
        bound_card="⊥",
        conflict="both modified spec.md",
    )
    assert conflict.ask is True
    allowed = archive_write_plan(
        decide_result={"decision": "allow"},
        package_resolved=True,
        card_resolved=True,
        q_git="release-2026-09-27",
        bound_card="⊥",
    )
    assert allowed.proceed is True
    assert allowed.use_generic_menu is False


def test_pronto_helper_args_refuse_placeholders():
    args, error = pronto_evidence_args(
        package="release-guard post",
        branches="card-1017-x",
        deploy="abc services=app url=https://example.com",
        cards="1017",
        commit="abc1234",
    )
    assert args == []
    assert "package" in error
    args, error = pronto_evidence_args(
        package="2026-09-27",
        branches="<lista ou pendência>",
        deploy="abc services=app url=https://example.com",
        cards="1017",
        commit="abc1234",
    )
    assert args == []
    assert "branches" in error
    ok, error = pronto_evidence_args(
        package="2026-09-27",
        branches="card-1017-x",
        deploy="abc1234 services=app url=https://example.com",
        cards="1017",
        commit="abc1234",
    )
    assert error == ""
    assert "--package" in ok and "2026-09-27" in ok
    assert "--branches" in ok
    assert not pronto_body_is_complete("Branches limpas: <lista ou pendência>")
    assert is_placeholder_text("<deploy PROD pendente>")


def test_live_t16_closer_sends_real_package_and_branches(monkeypatch, tmp_path: Path):
    calls: list[list[str]] = []

    def runner(args, **kwargs):  # noqa: ANN001
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "Posted\n", "")

    monkeypatch.setenv("RELEASE_PACKAGE", "2026-09-27")
    monkeypatch.setenv("RELEASE_BRANCHES", "card-1017-x,card-1055-y")
    monkeypatch.setenv("PROD_DEPLOY_EVIDENCE", "abc1234 services=app url=https://example.com")
    closer = LiveT16Closer(cwd=tmp_path, comment_script=HELPER, runner=runner)
    closer.commit = "abc1234def"
    closer.comment_pronto(card="1017", package=[1017, 1055])
    posted = calls[-1]
    assert "release-guard post" not in posted
    assert "2026-09-27" in posted
    assert "card-1017-x,card-1055-y" in posted
    assert "abc1234 services=app url=https://example.com" in posted

    monkeypatch.setenv("RELEASE_PACKAGE", "release-guard post")
    with pytest.raises(T16Error):
        LiveT16Closer(cwd=tmp_path, comment_script=HELPER, runner=runner).comment_pronto(
            card="1017", package=[1017]
        )


def test_homologado_comment_requires_human_decision_and_is_not_t7():
    refused = should_post_homologado(human_proven=False, already_has_comment=False)
    assert refused["post"] is False
    assert refused["called_t7"] is False
    assert refused["ask_alan_to_write"] is False
    allowed = should_post_homologado(human_proven=True, already_has_comment=False)
    assert allowed["post"] is True
    assert allowed["called_t7"] is False


def test_preflight_lists_pendencies_without_announcing_t16():
    report = run_preflight(
        (
            PreflightItem("comments", True, "missing homologado comment on #1017"),
            PreflightItem("archive", True, "card-1017 still active"),
            PreflightItem("deploy", False, "not started"),
            PreflightItem("t16", False, "not started"),
        )
    )
    kinds = {item["kind"] for item in report["pending"]}
    assert "comments" in kinds
    assert "archive" in kinds
    assert report["announces_deploy"] is False
    assert report["announces_t16"] is False
    assert "deploy" not in kinds
    assert "t16" not in kinds


def test_documental_proposal_keeps_qa_gate():
    proposal = documental_checks_proposal(["docs/release-2026-09-27.md", "openspec/specs/covenant-flow/spec.md"])
    assert proposal["disable_qa_gate"] is False
    assert proposal["qa_gate"] == "required"


def test_gh_flag_and_permission_denied_stay_on_that_call():
    def runner(args, **kwargs):  # noqa: ANN001
        if "--help" in args:
            return subprocess.CompletedProcess(args, 0, "Usage: gh pr create [--title]\n", "")
        return subprocess.CompletedProcess(args, 1, "", "Permission denied")

    supported = gh_supports_flag("gh", ["pr", "create"], "--title", runner=runner)
    assert supported["supported"] is True
    denied = gh_supports_flag(
        "gh",
        ["api"],
        "--paginate",
        runner=lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "", "Permission denied"),
    )
    assert denied["error_class"] == "permission_denied"
    assert denied["generalizes"] is False
    graphql = classify_tool_error("GraphQL: Resource not accessible by integration")
    assert graphql["generalizes"] is False
    assert graphql["operation"] == "this_call_only"


def test_runtime_model_check_has_no_fallback_or_auto(tmp_path: Path):
    (tmp_path / ".cursor").mkdir()
    (tmp_path / ".cursor" / "model-map.yaml").write_text(
        "juizo:\n  slug: cursor-grok-4.6-high\n  codex:\n    label: Sol\n    slug: gpt-6-sol\n    effort: high\n"
        "execucao:\n  label: Composer 2.5\n  slug: composer-2.5\n"
        "  codex:\n    label: Luna\n    slug: gpt-6-luna\n    effort: max\n",
        encoding="utf-8",
    )
    match = check_runtime_model(
        root=tmp_path, client=CLIENT_CODEX, runtime_slug="gpt-6-luna", runtime_effort="max", capture=resolve("codex", "execucao", role="fecho-lote")
    )
    assert match.ok is True
    diverge = check_runtime_model(
        root=tmp_path,
        client=CLIENT_CODEX,
        runtime_slug="gpt-6-sol",
        client_can_route=False,
        capture=resolve("codex", "execucao", role="fecho-lote"),
    )
    assert diverge.ok is False
    assert diverge.routed is False
    assert "do not claim routing occurred" in diverge.message
    auto = check_runtime_model(
        root=tmp_path, client=CLIENT_CURSOR, runtime_slug="cursor-execucao", auto_claimed=True, capture=resolve("cursor", "execucao", role="fecho-lote")
    )
    assert auto.auto_claimed is True
    assert auto.ok is False


def test_release_entry_point_keeps_provider_and_variant_observations(tmp_path: Path):
    capture = resolve("opencode", "execucao", role="fecho-lote")
    facts = dict(root=tmp_path, client="opencode", capture=capture,
                 runtime_slug="test-model", runtime_provider="test-provider",
                 runtime_variant="high")
    assert check_runtime_model(**facts).ok
    assert not check_runtime_model(**dict(facts, runtime_provider="other-provider")).ok
    assert not check_runtime_model(**dict(facts, runtime_variant="")).ok


def test_replay_package_membership_and_duplicate_policy():
    assert card_outside_package_is_left_alone("1042", ["1017", "1055"]) is True
    assert completed_homologado_change_blocks(
        card="1017", status="Homologado", progress="complete", package_cards=["1017"]
    )
    assert not completed_homologado_change_blocks(
        card="1042", status="Homologado", progress="complete", package_cards=["1017"]
    )
    assert not completed_homologado_change_blocks(
        card="1017", status="Homologado", progress="in-progress", package_cards=["1017"]
    )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True, text=True)
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")
    return repo


def _make_change(repo: Path, name: str, *, complete: bool = True) -> None:
    base = repo / "openspec" / "changes" / name
    (base / "specs" / "alpha").mkdir(parents=True)
    (base / "proposal.md").write_text(f"# {name}\n", encoding="utf-8")
    (base / "design.md").write_text("# d\n", encoding="utf-8")
    if complete:
        (base / "tasks.md").write_text("- [x] 1.1 done\n", encoding="utf-8")
    else:
        (base / "tasks.md").write_text("- [ ] 1.1 open\n", encoding="utf-8")
    (base / "specs" / "alpha" / "spec.md").write_text("# s\n", encoding="utf-8")


def _fake_gh(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "gh"
    script.write_text(
        """#!/usr/bin/env bash
set -u
case "${1:-} ${2:-}" in
  "auth status") exit 0 ;;
  "project item-list") printf '%s\\n' "${FAKE_BOARD_JSON:?}"; exit 0 ;;
  "pr list") printf '%s\\n' "${FAKE_PR_JSON:-[]}" ;;
  "api repos/"*) printf '%s\\n' "${FAKE_COMMENTS:-[]}" ;;
  *) printf 'unexpected: %s\\n' "$*" >&2; exit 1 ;;
esac
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _board(*cards: tuple) -> str:
    items = []
    for card in cards:
        number, status = card[0], card[1]
        title = card[2] if len(card) > 2 else f"Card {number}"
        items.append(
            f'{{"content":{{"number":{number},"repository":"oalansilva/crypto","title":"{title}"}},'
            f'"status":"{status}","responsavel":"Alan","prioridade":"P1","tipo":"Operacao"}}'
        )
    return f'{{"items":[{",".join(items)}],"totalCount":{len(cards)}}}'


def test_release_guard_blocks_completed_homologado_package_change(tmp_path: Path, monkeypatch):
    repo = _init_repo(tmp_path)
    _make_change(repo, "card-1017-codex-closeout", complete=True)
    _make_change(repo, "card-1042-codex-adapter", complete=True)
    archive = repo / "openspec" / "changes" / "archive" / "2026-09-01-card-1017-codex-closeout"
    archive.mkdir(parents=True)
    (archive / "tasks.md").write_text("- [x] 1.1 done\n", encoding="utf-8")
    (repo / "local-unrelated.txt").write_text("keep me\n", encoding="utf-8")
    fake_gh = _fake_gh(tmp_path)
    monkeypatch.setenv(
        "FAKE_BOARD_JSON",
        _board(
            (1017, "Homologado", "Codex closeout"),
            (1042, "Homologado", "Codex adapter"),
        ),
    )
    env = dict(os.environ)
    env["PATH"] = f"{fake_gh.parent}:{env['PATH']}"
    env["RELEASE_CARDS"] = "1017"
    result = subprocess.run(
        [str(RELEASE_GUARD), "audit"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0
    assert "card-1017-codex-closeout" in result.stdout
    assert "Homologado package card is still active" in result.stdout
    assert "BOTH active and archived" in result.stdout
    assert "card-1042-codex-adapter" not in result.stdout or "card #1042" not in result.stdout
    assert (repo / "local-unrelated.txt").read_text(encoding="utf-8") == "keep me\n"


def _comment_fake_gh(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    script = bin_dir / "gh"
    script.write_text(
        """#!/usr/bin/env bash
set -u
if [[ "${1:-}" == "api" && "${2:-}" == "-X" && "${3:-}" == "PATCH" ]]; then
  printf '%s\\n' "$*" >> "${FAKE_PATCH_LOG:?}"
  touch "${FAKE_PATCH_MARKER:?}"
  exit 0
fi
if [[ "${1:-}" == "api" ]]; then
  printf '%s\\n' "${FAKE_COMMENTS_JSON:?}"
  exit 0
fi
if [[ "${1:-} ${2:-}" == "issue comment" ]]; then
  touch "${FAKE_POST_MARKER:?}"
  exit 0
fi
printf 'unexpected gh call: %s\\n' "$*" >&2
exit 1
""",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return script


def _run_pronto(tmp_path: Path, comments_json: str, *extra: str) -> subprocess.CompletedProcess[str]:
    fake_gh = _comment_fake_gh(tmp_path)
    env = dict(os.environ)
    env["PATH"] = f"{fake_gh.parent}:{env['PATH']}"
    env["FAKE_COMMENTS_JSON"] = comments_json
    env["FAKE_POST_MARKER"] = str(tmp_path / "posted")
    env["FAKE_PATCH_MARKER"] = str(tmp_path / "patched")
    env["FAKE_PATCH_LOG"] = str(tmp_path / "patch.log")
    return subprocess.run(
        [
            str(HELPER),
            "--transition",
            "pronto",
            "--card",
            "1017",
            "--commit",
            "abc1234def",
            *extra,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_pronto_helper_refuses_placeholder_and_updates_incomplete(tmp_path: Path):
    refused = _run_pronto(tmp_path, "[]", "--package", "<pacote>", "--branches", "card-x", "--deploy", "sha url")
    assert refused.returncode != 0
    assert "placeholder" in refused.stderr
    assert not (tmp_path / "posted").exists()

    incomplete = (
        '[{"id":42,"body":"Publicado em main.\\nPacote/release: <pacote>\\n'
        "Commit/merge: abc1234def\\nDeploy PROD: <deploy PROD pendente>\\n"
        'Branches limpas: <lista ou pendência>\\n","url":"https://example.test/comment/42"}]'
    )
    updated = _run_pronto(
        tmp_path,
        incomplete,
        "--package",
        "2026-09-27",
        "--branches",
        "card-1017-x",
        "--deploy",
        "abc1234 services=app url=https://example.com",
        "--cards",
        "1017",
    )
    assert updated.returncode == 0
    assert (tmp_path / "patched").exists()
    assert not (tmp_path / "posted").exists()

    complete = (
        '[{"id":42,"body":"Publicado em main.\\nPacote/release: 2026-09-27\\n'
        "Commit/merge: abc1234def\\nDeploy PROD: abc1234 services=app url=https://example.com\\n"
        'Branches limpas: card-1017-x\\n","url":"https://example.test/comment/42"}]'
    )
    (tmp_path / "posted").unlink(missing_ok=True)
    (tmp_path / "patched").unlink(missing_ok=True)
    deduped = _run_pronto(
        tmp_path,
        complete,
        "--package",
        "2026-09-27",
        "--branches",
        "card-1017-x",
        "--deploy",
        "abc1234 services=app url=https://example.com",
    )
    assert deduped.returncode == 0
    assert "DEDUPE:" in deduped.stdout
    assert not (tmp_path / "posted").exists()
    assert not (tmp_path / "patched").exists()


def test_simulate_merge_reports_conflict_before_pr(tmp_path: Path):
    repo = _init_repo(tmp_path)
    clean = simulate_merge_against_target(repo, head="HEAD", target="HEAD")
    assert clean.ok is True
    assert clean.open_pr is True

    def conflict_runner(args, **kwargs):  # noqa: ANN001
        return subprocess.CompletedProcess(args, 1, "CONFLICT (content): merge conflict in README.md\n", "")

    conflicted = simulate_merge_against_target(
        repo, head="HEAD", target="origin/main", runner=conflict_runner
    )
    assert conflicted.ok is False
    assert conflicted.conflict is True
    assert conflicted.open_pr is False


def test_claude_parent_must_be_observed_on_the_captured_execution_pair(tmp_path: Path, monkeypatch):
    import claude_evidence as ev
    from claude_fixtures import SESSION, World, assistant
    from release_model_selection import check_claude_parent

    world = World(tmp_path)
    capture = resolve("claude", "execucao", role="fecho-lote")
    facts = dict(root=world.repo, capture=capture, session=SESSION, runtime=world.runtime, environ=world.env)
    # the parent is observed on Sonnet 5.5 / high = the captured claude/execucao pair
    assert check_claude_parent(**facts).ok
    # a later edit of the local selection does not change the obligation of a living parent
    import yaml
    path = Path.home() / ".config/covenant-flow/model-selection.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["clients"]["claude"]["execucao"].update(model="claude-haiku-5-5", effort="medium")
    path.write_text(yaml.safe_dump(doc))
    assert check_claude_parent(**facts).ok
    # wrong model, wrong effort, unobserved / unreadable parent: T16 and fecho-lote refused
    for model, effort in (("claude-opus-5-5", "high"), ("claude-sonnet-5-5", "medium")):
        world.rows.append(assistant(world.repo, model=model, effort=effort, content=[], msg_id=f"m-{model}-{effort}"))
        world.flush()
        refused = check_claude_parent(**facts)
        assert refused.ok is False and refused.divergence and "new Claude Code session" in refused.message
        world.rows.pop()
        world.flush()
    world.flush(truncate=True)
    unobserved = check_claude_parent(**facts)
    assert unobserved.ok is False and unobserved.runtime_slug == "unavailable" and "source_truncated" in unobserved.message
    world.parent.unlink()
    assert check_claude_parent(**facts).ok is False
    assert check_claude_parent(**dict(facts, capture=None)).ok is False
