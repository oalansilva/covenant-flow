"""Checkpoint lifecycle over controlled rollout sources, never live acceptance."""
import json
from pathlib import Path

import pytest

import codex_evidence as ce
import codex_terminal as ct
from test_codex_evidence import essay
from model_selection_fixtures import machine_models
from test_codex_context import diagnostic, lifecycle


def checkpoint(e, **kwargs):
    return Path(ct.start(root=e.root, card='1095', operation='apply', **kwargs)['checkpoint'])


def test_exec_resume_contains_exact_native_identity_and_does_not_fake_rebind(essay, monkeypatch):
    target = essay.root.parent / 'card-1130-target'
    target.mkdir()
    path = checkpoint(essay, target_root=target)
    result = ct.advance(path)
    assert result['code'] == 'worktree_mismatch'
    assert result['automatic_rebind'] == 'unavailable'
    assert result['command'] == f'codex --cd {target} exec resume {essay.parent_id} --json -'
    assert not ct.events(ct.read_checkpoint(path), target)


def test_tui_resume_uses_same_session_without_shell_rebind_claim(essay):
    cp = ct.read_checkpoint(checkpoint(essay))
    cp['surface'] = 'codex-tui'
    assert ct.resume_action(cp)['command'] == f'codex --cd {essay.root} resume {essay.parent_id}'


def test_new_chat_cannot_resume_the_checkpoint(essay, monkeypatch):
    path = checkpoint(essay)
    essay.p[0]['payload']['id'] = 'other-session'
    essay.write(essay.parent, essay.p)
    # A supplied identity is not a substitute for authoritative session lookup.
    monkeypatch.setenv('CODEX_THREAD_ID', 'absent-session')
    with pytest.raises(ce.EvidenceError, match='source_unavailable'):
        ct.advance(path)


def test_question_requires_explicit_native_user_answer_and_rechecks_live_state(essay, monkeypatch):
    path = checkpoint(essay, question='Which scope?')
    cp = ct.read_checkpoint(path)
    queries = []
    monkeypatch.setattr(ct, 'state', lambda *args: queries.append(args) or {'q': 'Em desenvolvimento'})
    assert ct.advance(path)['code'] == 'human_answer_missing'
    text = 'checkpoint: ' + cp['checkpoint_id'] + '\nanswer: option A'
    for role in ('assistant', 'user'):
        essay.p.append(essay.row('response_item', {'type': 'message', 'role': role,
            'content': [{'type': 'input_text', 'text': text}]}))
        essay.write(essay.parent, essay.p)
        if role == 'assistant':
            assert ct.advance(path)['code'] == 'human_answer_missing'
    monkeypatch.setattr(ce, 'preflight', lambda **kwargs: {'result': 'ready'})
    assert ct.advance(path)['result'] == 'ready'
    assert len(queries) == 3
    assert ct.human_answer(cp, ce.Rollout().session(essay.parent_id)[1])['answer'] == 'option A'


def test_recovery_ceiling_preserves_original_failure_and_resets_only_changed_sources(essay):
    path = checkpoint(essay)
    cp = ct.read_checkpoint(path)
    error = ce.EvidenceError('source_unavailable', 'missing original')
    first = ct.failure(cp, essay.root, error, sources={'origin': 'a'})
    second = ct.failure(cp, essay.root, error, sources={'origin': 'a'})
    assert first['result'] == 'recovery_required'
    assert second['result'] == 'blocked'
    assert second['original_failure'] == first['original_failure']
    recovered_source = ct.failure(cp, essay.root, error, sources={'origin': 'b'})
    assert recovered_source['result'] == 'recovery_required'
    assert len(ct.events(cp, essay.root)) == 3


def test_missing_diagnostics_authorization_does_not_spawn_or_mutate_state(essay, monkeypatch):
    path = checkpoint(essay)
    monkeypatch.setattr(ct, 'state', lambda *args: {'q': 'Em desenvolvimento'})
    result = ct.advance(path)
    assert result['result'] == 'recovery_required'
    assert 'arguments' not in result
    assert not any(e['kind'] == 'diagnostic_prepared' for e in ct.events(ct.read_checkpoint(path), essay.root))


def test_changed_status_blocks_even_with_valid_answer(essay, monkeypatch):
    path = checkpoint(essay)
    def changed(*args):
        ct.fail('terminal_status_mismatch', 'q=Todo')
    monkeypatch.setattr(ct, 'state', changed)
    with pytest.raises(ce.EvidenceError, match='terminal_status_mismatch'):
        ct.advance(path)


def test_release_is_not_authorized_by_apply_or_technical_done(essay):
    with pytest.raises(ce.EvidenceError, match='release_request_missing'):
        ct.start(root=essay.root, card='1095', operation='release')


@pytest.mark.parametrize('matching', [False, True])
def test_explicit_release_still_requires_observed_execution_selection(essay, monkeypatch, matching):
    if matching:
        essay.p[1]['payload'].update(model='gpt-6-luna', effort='max')
        essay.write(essay.parent, essay.p)
    path = Path(ct.start(root=essay.root, card='1095', operation='release', release_requested=True)['checkpoint'])
    monkeypatch.setattr(ct, 'state', lambda *args: {'q': 'Homologado'})
    monkeypatch.setattr(ce, 'preflight', lambda **kwargs: {'result': 'ready'})
    result = ct.advance(path)
    if not matching:
        assert result['code'] == 'release_parent_selection_mismatch'
        assert 'action' not in result
        return
    assert result['action'] == 'canonical_release_closeout'
    assert result['authorization'] == 'explicit operation only; no trust inferred'
    essay.p[1]['payload']['effort'] = 'high'
    essay.write(essay.parent, essay.p)
    assert ct.advance(path)['code'] == 'release_parent_selection_changed'


def test_post_T18_uses_existing_development_stage_without_T8(essay, monkeypatch):
    path = checkpoint(essay)
    monkeypatch.setattr(ct, 'state', lambda *args: {'q': 'Em desenvolvimento', 'post_T18': True})
    monkeypatch.setattr(ce, 'preflight', lambda **kwargs: {'result': 'ready'})
    result = ct.advance(path)
    assert result['role'] == 'apply-coluna'
    assert 'iniciar_apply' not in json.dumps(result)


@pytest.mark.parametrize('operation,state,event', [('design', 'Todo', 'iniciar_design'),
    ('apply', 'Pronto para Dev', 'iniciar_apply'), ('qa', 'Code Review', 'aceitar_sha')])
def test_pretransition_preparation_retries_existing_event_without_releasing_child(essay, monkeypatch, operation, state, event):
    path = Path(ct.start(root=essay.root, card='1095', operation=operation)['checkpoint'])
    monkeypatch.setattr(ct, 'state', lambda *args: {'q': state})
    monkeypatch.setattr(ce, 'preflight', lambda **kwargs: {'result': 'ready'})
    result = ct.advance(path)
    assert result['result'] == 'awaiting_event' and result['event'] == event
    assert 'arguments' not in result
    assert result['action'] == 'parent_existing_FSM_event'


def test_late_native_flush_recollects_same_birth_without_erasing_original_failure(diagnostic, monkeypatch):
    e = diagnostic
    lifecycle(e)
    path = checkpoint(e)
    cp = ct.read_checkpoint(path)
    ct.append(cp, e.root, 'diagnostic_prepared', birth=str(e.birth), plan=str(e.plan),
              refusals=[str(p) for p in e.birth.parent.glob('*.failure-*.json')])
    monkeypatch.setattr(ct, 'state', lambda *args: {'q': 'Em desenvolvimento'})
    original = e.child.read_bytes()
    e.write(e.child, [row for row in e.c if row['payload'].get('type') != 'task_complete'])
    first = ct.advance(path)
    second = ct.advance(path)
    third = ct.advance(path)
    assert first['result'] == 'recovery_required'
    assert second['result'] == third['result'] == 'blocked'
    assert third['original_failure'] == first['original_failure']
    count = len(ct.events(cp, e.root))
    e.child.write_bytes(original)
    success = ct.advance(path)
    assert success['result'] == 'ready'
    history = ct.events(cp, e.root)
    assert any(item.get('kind') == 'failure' and item['integrity_sha256'] == first['original_failure'] for item in history)
    assert len(history) > count
    assert any(item['kind'] == 'diagnostic_qualified' and item['birth'] == str(e.birth) for item in history)


def test_source_creation_and_unbound_release_use_existing_FSM_contracts(essay, monkeypatch):
    from resolve import UNBOUND
    import resolve
    import guard
    import overlay
    monkeypatch.setattr(resolve, 'resolve', lambda *args: {'bound_card': UNBOUND, 'q_git': 'develop'})
    monkeypatch.setattr(guard, 'github_status_provider', lambda card: 'Homologado')
    monkeypatch.setattr(overlay, 'load_overlay', lambda *args, **kwargs: {'integration_branch': 'develop'})
    assert ct.state(essay.root, None, 'create')['q'] is None
    assert ct.state(essay.root, '1095', 'release')['q'] == 'Homologado'
