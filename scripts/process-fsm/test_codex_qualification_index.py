"""Controlled native-source fixtures; no invoking runtime is qualified."""
import json
from pathlib import Path

import pytest

import codex_evidence as ce
from codex_qualification_index import Index, verify_reference
from test_codex_evidence import Essay, essay
from model_selection_fixtures import machine_models


def qualify(e):
    with pytest.raises(ce.EvidenceError):
        e.collect()
    e.complete()
    proof = e.collect()
    ce.qualify(proof['evidence_path'], list(e.birth.parent.glob('*.failure-*.json')))
    return ce.qualification_path(e.birth.parent, e.host)


def test_private_atomic_index_reopens_original_and_preserves_provenance(essay):
    receipt = qualify(essay)
    index = Index()
    old = receipt.read_bytes()
    entry = index.register(receipt, essay.host)
    assert index.register(receipt, essay.host) == entry
    proof, found = index.discover(essay.host)
    assert found['discovery'] == 'index'
    assert proof['parent_thread'] == essay.parent_id
    assert receipt.read_bytes() == old
    assert index.path.stat().st_mode & 0o777 == 0o600
    assert index.path.parent.stat().st_mode & 0o777 == 0o700
    assert not list(index.path.parent.glob('.qualifications-*'))


def test_new_destination_reuses_capacity_without_transferring_context(essay):
    receipt = qualify(essay)
    Index().register(receipt, essay.host)
    other = essay.root.parent / 'card-1130-fresh'
    other.mkdir()
    essay.p.append(essay.row('turn_context', dict(turn_id='resumed-native-turn', model='parent-model',
        effort='medium', cwd=str(other), sandbox_policy={'type': 'workspace-write'})))
    essay.write(essay.parent, essay.p)
    result = ce.preflight(root=other)
    assert result['capability_reference']['discovery'] == 'index'
    assert result['capabilities']['context_isolation'] == 'unavailable'
    assert not ce.qualification_path(other / ce.DEFAULT_DEST, essay.host).exists()
    with pytest.raises(ce.EvidenceError, match='stage_capability_missing'):
        ce.preflight(root=other, stage='apply-coluna')


@pytest.mark.parametrize('problem', ['missing', 'corrupt', 'source-changed', 'receipt-changed', 'symlink', 'mode'])
def test_invalid_index_or_original_never_falls_back_to_success(essay, problem):
    receipt = qualify(essay)
    index = Index()
    index.register(receipt, essay.host)
    if problem == 'missing':
        receipt.unlink()
    elif problem == 'corrupt':
        index.path.write_text('{')
    elif problem == 'source-changed':
        essay.c[-1]['payload']['last_agent_message'] = 'altered'
        essay.write(essay.child, essay.c)
    elif problem == 'receipt-changed':
        value = json.loads(receipt.read_text())
        value['session'] = 'different'
        receipt.write_text(json.dumps(value))
    elif problem == 'symlink':
        saved = receipt.with_suffix('.saved')
        receipt.rename(saved)
        receipt.symlink_to(saved)
    else:
        index.path.chmod(0o644)
    with pytest.raises(ce.EvidenceError):
        index.discover(essay.host, legacy=[receipt])


def test_legacy_explicit_empty_index_and_surface_mismatch(essay):
    index = Index()
    with pytest.raises(ce.EvidenceError, match='qualification_reference_missing'):
        index.discover(essay.host)
    receipt = qualify(essay)
    proof, entry = index.discover(essay.host, legacy=[receipt])
    assert entry['discovery'] == 'legacy'
    assert not index.path.exists()
    assert index.discover(essay.host, explicit=receipt)[1]['discovery'] == 'explicit'
    with pytest.raises(ce.EvidenceError, match='qualification_surface_mismatch'):
        index.discover('codex-tui', explicit=receipt)


def test_conflicting_identities_do_not_select_by_timestamp(essay, tmp_path, monkeypatch, machine_models):
    first = qualify(essay)
    other_path = tmp_path / 'different'
    other_path.mkdir()
    other = Essay(other_path, monkeypatch, role='apply-coluna')
    second = qualify(other)
    with pytest.raises(ce.EvidenceError, match='qualification_conflict'):
        Index().discover('codex_exec', legacy=[first, second])
    assert Index().discover('codex_exec', explicit=second, legacy=[first])[0]['attempt_id'] == other.cap['attempt_id']


def test_preflight_preserves_public_failure_and_specific_discovery_cause(essay):
    with pytest.raises(ce.EvidenceError) as failure:
        ce.preflight(root=essay.root)
    assert failure.value.code == 'unverified'
    assert failure.value.observed == {'qualification_cause': 'qualification_reference_missing'}


def test_compatible_active_version_new_chat_keeps_capability_but_not_context(essay, tmp_path, monkeypatch, machine_models):
    receipt = qualify(essay)
    Index().register(receipt, essay.host)
    other_path = tmp_path / 'new-session'
    other_path.mkdir()
    new = Essay(other_path, monkeypatch, role='apply-coluna', skip_prepare=True)
    new.p[0]['payload']['cli_version'] = '99.1.0-compatible-schema'
    new.write(new.parent, new.p)
    result = ce.preflight(root=new.root)
    assert result['host_version'] == '99.1.0-compatible-schema'
    assert result['capability_reference']['identity']['session'] == essay.parent_id
    assert result['context_qualification']['result'] == 'unavailable'
    with pytest.raises(ce.EvidenceError, match='stage_capability_missing'):
        ce.preflight(root=new.root, stage='apply-coluna')


def test_symlink_in_index_parent_and_nonprivate_directory_are_refused(tmp_path):
    real = tmp_path / 'real'
    real.mkdir(mode=0o700)
    link = tmp_path / 'link'
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ce.EvidenceError, match='qualification_path_unsafe'):
        Index(link / 'refs.json').load()
    real.chmod(0o755)
    with pytest.raises(ce.EvidenceError, match='qualification_index_unsafe'):
        Index(real / 'refs.json').load()
