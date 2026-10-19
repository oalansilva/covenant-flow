"""Automatic preparation over controlled native chains; not a live Review."""
import json
from pathlib import Path

import pytest

import codex_evidence as ce
import codex_terminal as ct
import codex_terminal_review as tr
import codex_review_session as cs
from test_codex_review_session import dedicated
from model_selection_fixtures import machine_models


def start(d):
    diff = d.root / 'product.patch'
    diff.write_text('diff --git a/example b/example\n--- a/example\n+++ b/example\n@@ -1 +1 @@\n-old\n+new\n')
    path = Path(ct.start(root=d.root, card='1098', operation='review', diff=diff,
                        diagnostics_authorized=True, runtime=d.rt)['checkpoint'])
    return ct.read_checkpoint(path), path


@pytest.mark.parametrize('surface', ['codex-tui', 'codex_exec'])
def test_automatic_principal_preparation_preserves_all_native_phase_gates(dedicated, surface):
    d = dedicated
    d.rows[d.principal][0]['payload']['originator'] = surface
    d.flush(d.principal)
    bootstrap = d.bootstrap()
    cp, path = start(d)
    ct.append(cp, d.root, 'review_package', package=str(bootstrap), phase='bootstrap')
    negative = d.command_event(d.principal, 'principal-turn', cs.command(bootstrap, 'route-check'),
                               {'result': 'blocked', 'code': 'review_route_unqualified'})
    negative['payload']['item'].update(status='failed', exit_code=1)
    d.flush(d.principal)
    for phase in ('context', 'probe', 'review'):
        action = tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)
        latest = [e for e in ct.events(cp, d.root) if e['kind'] == 'review_package'][-1]
        package = Path(latest['package'])
        assert cs.read_package(package)['phase'] == phase
        assert action['action'] == 'execute_exact_native_command'
        d.finish_children(package)
    final = tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)
    assert final['result'] == 'review_wave_verified'
    assert len(final['evidence']) == 2
    assert '--phase precommit' in final['checklist_command']
    assert ct.events(cp, d.root)[-1]['kind'] == 'review_wave_verified'
    assert not any(e['kind'] == 'committed' for e in ct.events(cp, d.root))


@pytest.mark.parametrize('surface', ['codex-tui', 'codex_exec'])
def test_empty_checkpoint_launches_before_real_route_refusal_then_qualifies(dedicated, surface):
    """Use actual binding/route helpers over controlled native-source records.

    Unlike the already-bootstrapped fixture above, start with no coordinator or
    refusal. The returned refusal is obtained from verify_route, not invented.
    This remains a source fixture, never a live runtime qualification.
    """
    d = dedicated
    d.rows[d.principal][0]['payload']['originator'] = surface
    d.flush(d.principal)
    cp, path = start(d)
    launch = tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)
    bootstrap = Path([e['package'] for e in ct.events(cp, d.root) if e['kind'] == 'review_package'][-1])
    assert launch['phase'] == 'bootstrap'
    assert launch['expected_exit'] == 0
    assert launch['command'] == cs.command(bootstrap)
    assert not Path(cs.read_package(bootstrap)['events']).exists()
    with pytest.raises(ce.EvidenceError, match='review_launch_source_unavailable'):
        cs.verify_route(bootstrap, runtime=d.rt)

    # Reuse the native bootstrap fixture to complete the package that the
    # controller already prepared, without creating another package/attempt.
    with d.monkeypatch.context() as setup:
        setup.setattr(cs, 'prepare', lambda **kwargs: {'package': str(bootstrap)})
        assert d.bootstrap() == bootstrap
    assert cs.binding(bootstrap, runtime=d.rt, complete=True)['coordinator_thread'] == d.coordinator
    refusal = tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)
    assert refusal['phase'] == 'bootstrap-refusal'
    assert refusal['expected_exit'] == 1
    assert refusal['command'] == cs.command(bootstrap, 'route-check')
    with pytest.raises(ce.EvidenceError) as rejected:
        cs.verify_route(bootstrap, runtime=d.rt)
    assert rejected.value.code == 'review_route_unqualified'
    observed = {'result': cs.outcome(rejected.value.code), 'code': rejected.value.code,
                'detail': str(rejected.value)}
    assert observed['result'] == 'blocked'
    event = d.command_event(d.principal, 'principal-turn', refusal['command'], observed)
    event['payload']['item'].update(status='failed', exit_code=1)
    d.flush(d.principal)

    for phase in ('context', 'probe', 'review'):
        action = tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)
        latest = [e for e in ct.events(cp, d.root) if e['kind'] == 'review_package'][-1]
        package = Path(latest['package'])
        assert cs.read_package(package)['phase'] == phase
        assert action['action'] == 'execute_exact_native_command'
        d.finish_children(package)
    assert tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)['result'] == 'review_wave_verified'
    assert cs.verify_route(bootstrap, runtime=d.rt)['coordinator_thread'] == d.coordinator
    assert [e['phase'] for e in ct.events(cp, d.root) if e['kind'] == 'native_command_requested'][:2] == [
        'bootstrap', 'bootstrap-refusal']


def test_changed_diff_and_missing_diagnostic_authorization_cannot_launch(dedicated):
    d = dedicated
    cp, path = start(d)
    Path(cp['diff']).write_text('changed')
    with pytest.raises(ce.EvidenceError, match='review_diff_changed'):
        tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)
    assert not ct.events(cp, d.root)
    cp['diff_sha256'] = ce.digest(Path(cp['diff']).read_bytes())
    cp['diagnostics_authorized'] = False
    with pytest.raises(ce.EvidenceError, match='review_diagnostic_authorization_missing'):
        tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)


def test_partial_native_launch_output_never_relaunches_or_becomes_a_verdict(dedicated):
    d = dedicated
    cp, path = start(d)
    first = tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)
    assert first['expected_exit'] == 0
    package_path = [event['package'] for event in ct.events(cp, d.root) if event['kind'] == 'review_package'][-1]
    package = cs.read_package(package_path)
    Path(package['events']).write_text('{partial')
    result = tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)
    assert result['result'] == 'recovery_required'
    assert 'command' not in result
    assert tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)['result'] == 'blocked'


def test_requested_native_command_is_not_issued_twice_before_source_flush(dedicated):
    d = dedicated
    cp, path = start(d)
    first = tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)
    assert first['action'] == 'execute_exact_native_command'
    second = tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)
    assert second['code'] == 'review_native_command_pending'
    assert 'command' not in second
    assert tr.advance_review(cp, d.root, {'q': 'Code Review'}, runtime=d.rt)['result'] == 'blocked'
