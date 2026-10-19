"""Explicit source-card binding tests over controlled sources only."""
import json
from pathlib import Path

import pytest

import codex_evidence as ce
import codex_context as cc
from model_selection import resolve, save_capture
from test_codex_context import diagnostic, lifecycle
from model_selection_fixtures import machine_models


def test_source_binding_uses_live_card_state_without_authorizing_product(tmp_path, monkeypatch):
    import resolve as binding
    import guard
    monkeypatch.setattr(binding, 'resolve', lambda *args: {'bound_card': '⊥', 'q_git': 'develop'})
    live = {'q': 'Em Refinamento'}
    monkeypatch.setattr(guard, 'github_status_provider', lambda card: live['q'])
    assert ce.refinement_binding(tmp_path, '1117') == {'card': '1117', 'status': 'Em Refinamento', 'q_git': 'develop'}
    live['q'] = 'Todo'
    with pytest.raises(ce.EvidenceError, match='refinement_status_mismatch'):
        ce.refinement_binding(tmp_path, '1117')
    monkeypatch.setattr(binding, 'resolve', lambda *args: {'bound_card': '1130', 'q_git': 'card-1130-other'})
    with pytest.raises(ce.EvidenceError, match='refinement_card_mismatch'):
        ce.refinement_binding(tmp_path, '1117')


def test_refinement_card_is_sealed_and_rechecked_before_native_spawn(diagnostic, monkeypatch):
    e = diagnostic
    lifecycle(e)
    cc.qualify(e.plan)
    live = {'q': 'Em Refinamento'}
    def bound(root, card):
        if live['q'] != 'Em Refinamento':
            raise ce.EvidenceError('refinement_status_mismatch')
        return {'card': card, 'status': live['q'], 'q_git': 'develop'}
    monkeypatch.setattr(ce, 'refinement_binding', bound)
    cap = resolve('codex', 'juizo', role='grill-card')
    capture = e.root / 'grill.capture.json'
    save_capture(capture, cap)
    prepared = ce.prepare(root=e.root, capture=capture, task_name='grill_card_1095', card='1095')
    birth = ce.check_seal(json.loads(Path(prepared['birth']).read_text()))
    assert birth['bound_card'] == '1095' and birth['stage_status'] == 'Em Refinamento'
    assert birth['capability_identity']['session'] == e.parent_id
    args = dict(cap['arguments'], task_name='grill_card_1095', fork_turns='none',
                message='#1095 grill-card\nmodel_selection_capture: ' + str(capture)
                        + '\nruntime_evidence_birth: ' + prepared['birth'])
    assert ce.check_prepared_spawn(args, e.root)['result'] == 'ready'
    live['q'] = 'Todo'
    with pytest.raises(ce.EvidenceError, match='refinement_status_mismatch'):
        ce.check_prepared_spawn(args, e.root)
    live['q'] = 'Em Refinamento'
    receipt = Path(birth['capability_reference'])
    original = receipt.read_bytes()
    receipt.write_text('{}')
    with pytest.raises(ce.EvidenceError, match='unverified'):
        ce.check_prepared_spawn(args, e.root)
    receipt.write_bytes(original)
    with pytest.raises(ce.EvidenceError, match='refinement_card_invalid'):
        ce.prepare(root=e.root, capture=e.capture, task_name='qa_cannot_adopt_card', card='1117')
    assert Path(prepared['birth']).read_text() == json.dumps(birth, sort_keys=True, ensure_ascii=False, indent=2) + '\n'
