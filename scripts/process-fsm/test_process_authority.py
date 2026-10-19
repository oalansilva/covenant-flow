"""Data-only external authority contracts; fixtures are not runtime qualification."""
import json
from pathlib import Path
import subprocess

import pytest

import process_authority as pa
from test_overlay_fixtures import write_overlay


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True)


def authority_tree(root):
    root.mkdir(parents=True)
    git(root, 'init', '--initial-branch', root.name)
    git(root, '-c', 'user.name=Fixture', '-c', 'user.email=f@example.test',
        'commit', '--allow-empty', '-m', 'fixture')
    git(root, 'remote', 'add', 'origin', 'https://github.com/oalansilva/crypto.git')
    write_overlay(root)
    return root


@pytest.fixture
def authority(tmp_path):
    return authority_tree(tmp_path / 'consumer' / 'card-1098-fixture')


def test_snapshot_binds_exact_consumer_repo_board_card_without_loading_external_code(authority):
    trap = authority / 'scripts/process-fsm'
    trap.mkdir(parents=True)
    (trap / 'guard.py').write_text('raise AssertionError("external code executed")')
    pinned = pa.capture(authority, '1098')
    assert pinned['root'] == str(authority)
    assert pinned['repo'] == 'oalansilva/crypto'
    assert (pinned['board_owner'], pinned['board_number'], pinned['bound_card']) == ('oalansilva', 1, '1098')
    assert pa.verify(pinned, '1098') == pinned
    assert pa.overlay(pinned, '1098')['repo'] == pinned['repo']


@pytest.mark.parametrize('fault', ['missing', 'different-card', 'branch', 'origin', 'unqualified', 'overlay', 'board', 'symlink-overlay', 'symlink-root', 'ancestor-only', 'non-root'])
def test_authority_rejects_missing_changed_ineligible_or_escaping_sources(authority, tmp_path, fault):
    pinned = pa.capture(authority, '1098')
    path = authority / '.covenant-flow/overlay.yaml'
    if fault == 'missing': path.unlink()
    elif fault == 'different-card': pinned['bound_card'] = '9000'
    elif fault == 'branch': git(authority, 'checkout', '-b', 'card-9000-other')
    elif fault == 'origin': git(authority, 'remote', 'set-url', 'origin', 'https://github.com/other/repo.git')
    elif fault == 'unqualified': git(authority, 'remote', 'set-url', 'origin', '/tmp/crypto')
    elif fault == 'overlay': path.write_text(path.read_text() + '\n# changed bytes\n')
    elif fault == 'board': path.write_text(path.read_text().replace('number: 1', 'number: 2'))
    elif fault == 'symlink-overlay':
        escaped = tmp_path / 'overlay.yaml'; path.rename(escaped); path.symlink_to(escaped)
    elif fault == 'symlink-root':
        link = tmp_path / 'linked'; link.symlink_to(authority, target_is_directory=True); pinned['root'] = str(link)
    elif fault == 'ancestor-only': path.rename(authority.parent / 'overlay.yaml')
    elif fault == 'non-root':
        nested = authority / 'card-1098-fixture'; nested.mkdir(); pinned['root'] = str(nested)
    with pytest.raises(pa.AuthorityError): pa.verify(pinned, '1098')


def test_absent_overlay_is_not_discovered_in_parent_or_other_tree(authority):
    (authority / '.covenant-flow/overlay.yaml').unlink()
    write_overlay(authority.parent)
    with pytest.raises(pa.AuthorityError, match='source_unavailable'):
        pa.capture(authority, '1098')


@pytest.mark.parametrize('remote', ['https://github.com/oalansilva/crypto.git', 'git@github.com:oalansilva/crypto.git', 'ssh://git@github.com/oalansilva/crypto'])
def test_canonical_repository_identity(remote):
    assert pa._repository(remote) == 'oalansilva/crypto'


def test_guard_queries_explicit_authority_without_using_cwd_or_its_overlay(authority, monkeypatch):
    import guard
    from types import SimpleNamespace
    expected = pa.capture(authority, '1098')
    called = []
    real_run = pa.subprocess.run
    def run(argv, **kwargs):
        if argv[0] == 'git': return real_run(argv, **kwargs)
        called.append(argv)
        return SimpleNamespace(stdout=json.dumps({'data': {'repository': {'issue': {'projectItems': {'nodes': [
            {'project': {'number': 1, 'owner': {'login': 'oalansilva'}}, 'fieldValueByName': {'name': 'Code Review'}}]}}}}}), stderr='', returncode=0)
    monkeypatch.setattr(guard, 'try_load_overlay', lambda *args: pytest.fail('implicit cwd overlay'))
    monkeypatch.setattr(guard.subprocess, 'run', run)
    monkeypatch.setattr(guard, 'raise_if_cached_exhausted', lambda: None)
    monkeypatch.setattr(guard, 'write_cache', lambda *args: None)
    assert guard.github_status_provider('1098', authority=expected) == 'Code Review'
    assert 'repository(owner:"oalansilva",name:"crypto")' in called[0][5]


@pytest.mark.parametrize('fault', ['ambiguous', 'wrong-board', 'unknown-owner', 'no-status'])
def test_explicit_query_rejects_ambiguous_or_incomplete_board_membership(authority, monkeypatch, fault):
    import guard
    from types import SimpleNamespace
    expected = pa.capture(authority, '1098')
    node = {'project': {'number': 1, 'owner': {'login': 'oalansilva'}}, 'fieldValueByName': {'name': 'Code Review'}}
    nodes = [node, node] if fault == 'ambiguous' else [node]
    if fault == 'wrong-board': node['project']['number'] = 2
    if fault == 'unknown-owner': node['project']['owner'] = {}
    if fault == 'no-status': node['fieldValueByName'] = {}
    real_run = pa.subprocess.run
    def run(argv, **kwargs):
        if argv[0] == 'git': return real_run(argv, **kwargs)
        return SimpleNamespace(stdout=json.dumps({'data': {'repository': {'issue': {'projectItems': {'nodes': nodes}}}}}), stderr='', returncode=0)
    monkeypatch.setattr(guard.subprocess, 'run', run)
    monkeypatch.setattr(guard, 'raise_if_cached_exhausted', lambda: None)
    monkeypatch.setattr(guard, 'write_cache', lambda *args: None)
    assert guard.github_status_provider('1098', authority=expected) is None


def test_terminal_passes_and_pins_authority_without_rebinding_native_root(dedicated, authority, monkeypatch):
    import codex_terminal as ct
    import codex_terminal_review as tr
    import codex_review_session as cs
    diff = dedicated.root / 'product.patch'; diff.write_text('review diff')
    checkpoint_path = ct.start(root=dedicated.root, card='1098', operation='review', diff=diff,
        authority_root=authority, diagnostics_authorized=True, runtime=dedicated.rt)['checkpoint']
    checkpoint = ct.read_checkpoint(checkpoint_path)
    assert checkpoint['target_root'] == checkpoint['birth_root'] == str(dedicated.root)
    assert checkpoint['authority'] == pa.capture(authority, '1098')
    action = tr.advance_review(checkpoint, dedicated.root, {'q': 'Em desenvolvimento'}, runtime=dedicated.rt)
    package_path = [e['package'] for e in ct.events(checkpoint, dedicated.root) if e['kind'] == 'review_package'][-1]
    assert cs.read_package(package_path)['authority'] == checkpoint['authority']
    assert action['command'] == cs.command(package_path)
    (authority / '.covenant-flow/overlay.yaml').write_text('changed')
    with pytest.raises(ct.ce.EvidenceError, match='terminal_authority_invalid'):
        ct.advance(checkpoint_path, runtime=dedicated.rt)


# Reuse the native source fixture; it is explicitly controlled evidence.
from test_codex_review_session import dedicated
from model_selection_fixtures import machine_models


@pytest.mark.parametrize('fault', [None, 'ambiguous', 'changed-before-edit', 'wrong-card'])
def test_live_mover_uses_only_pinned_board_and_rechecks_before_edit(authority, monkeypatch, fault):
    import process_event as pe
    from types import SimpleNamespace
    pinned = pa.capture(authority, '1098')
    node = {'id': 'pinned-item', 'project': {'number': 1, 'owner': {'login': 'oalansilva'}}}
    nodes = [node, node] if fault == 'ambiguous' else [node]
    calls = []
    real_run = pa.subprocess.run
    def run(argv, **kwargs):
        if argv[0] == 'git': return real_run(argv, **kwargs)
        calls.append(argv)
        if argv[:3] == ['gh', 'api', 'graphql']:
            if fault == 'changed-before-edit':
                path = authority / '.covenant-flow/overlay.yaml'
                path.write_text(path.read_text() + '\n# changed before board edit\n')
            return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps({
                'data': {'repository': {'issue': {'projectItems': {'nodes': nodes}}}}}))
        return SimpleNamespace(returncode=0, stderr='', stdout='')
    monkeypatch.setattr(pe.subprocess if hasattr(pe, 'subprocess') else pa.subprocess, 'run', run)
    monkeypatch.setattr(pe, 'raise_if_cached_exhausted', lambda: None)
    monkeypatch.setattr(pe, 'write_cache', lambda *args: None)
    mover = pe.GhBoardMover(authority=pinned)
    if fault:
        with pytest.raises((pa.AuthorityError, RuntimeError)):
            mover.set_status(9000 if fault == 'wrong-card' else 1098, 'Code Review')
        assert not any(call[:3] == ['gh', 'project', 'item-edit'] for call in calls)
    else:
        mover.set_status(1098, 'Code Review')
        assert len(calls) == 2
        edit = calls[1]
        data = pa.overlay(pinned, '1098')
        assert edit[edit.index('--project-id') + 1] == data['board']['project_id']
        assert edit[edit.index('--field-id') + 1] == data['board']['status_field_id']
        assert edit[edit.index('--id') + 1] == 'pinned-item'
