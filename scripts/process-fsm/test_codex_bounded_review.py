"""Contract and controlled native-source fixtures; these are NOT live LM reviews."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sqlite3

import pytest
import codex_bounded_review as br
import codex_evidence as ce
import codex_review_session as cs
import codex_terminal as ct
from test_codex_review_session import dedicated
from model_selection_fixtures import machine_models


def command(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True).stdout


def prepare(root):
    if (root / 'scripts/process-fsm').is_dir():
        (root / 'scripts/process-fsm/codex_bounded_review.py').write_bytes(Path(br.__file__).read_bytes())
    command(root, 'config', 'user.name', 'Fixture')
    command(root, 'config', 'user.email', 'fixture@example.test')
    (root / '.gitignore').write_text('.cursor/tmp/\n')
    product = root / 'product'; product.mkdir(exist_ok=True)
    (product / 'producer.py').write_text('def produce():\n    return 1\n')
    command(root, 'add', '-A'); command(root, 'commit', '-m', 'base')
    (product / 'producer.py').write_text('def produce():\n    return 2\n')


def config(root, limit=500000):
    home = ce.Rollout().home
    p = home / 'sessions/window-fixture.jsonl'
    p.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        dict(type='session_meta', payload=dict(id='window-fixture', originator='codex_exec', cli_version='0.163.0', cwd=str(root), source='exec')),
        dict(type='turn_context', payload=dict(turn_id='window-turn', model='gpt-6-luna', effort='max', cwd=str(root), sandbox_policy={'type': 'read-only'}, multi_agent_version='v2')),
        dict(type='event_msg', payload=dict(type='token_count', info={'model_context_window': 500000}))]
    p.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    with sqlite3.connect(home / 'state_5.sqlite') as db:
        db.execute('CREATE TABLE IF NOT EXISTS threads (id TEXT, rollout_path TEXT, agent_path TEXT)')
        db.execute("DELETE FROM threads WHERE id='window-fixture'")
        db.execute('INSERT INTO threads VALUES (?,?,?)', ('window-fixture', str(p), '/root'))
    raw = ce.Rollout().session('window-fixture')[1][-1]
    return dict(limit=limit, limit_source=dict(path=str(p), session='window-fixture', ordinal=raw[0], raw_sha256=raw[2], model='gpt-6-luna', effort='max'),
                overhead={key: 4000 for key in br.COSTS}, uncertainty_percent=25)


def snapshot(root, *, name='case', mode='precommit', base='HEAD', target='HEAD'):
    return br.capture(root, root / '.cursor/tmp' / name, mode=mode, base=base, target=target)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / 'card-1130-fixture'; root.mkdir()
    command(root, 'init', '--initial-branch', root.name)
    prepare(root)
    return root


def planned(root, *, diagnostic=True, name='case'):
    cfg = config(root)
    snap = snapshot(root, name=name)
    return br.plan(snap, cfg, diagnostic=diagnostic)


def test_snapshot_includes_staged_working_untracked_and_global_staleness(repo):
    command(repo, 'add', 'product/producer.py')
    (repo / 'product/producer.py').write_text('def produce():\n    return 3\n')
    (repo / 'product/untracked.md').write_text('new contract\n')
    snap = snapshot(repo); s = br.check_snapshot(snap)
    assert {r['phase'] for r in s['inventory']} == {'index', 'working-tree'}
    assert any(r['status'] == 'A' and r['new'].endswith('untracked.md') for r in s['inventory'])
    (repo / 'product/untracked.md').write_text('changed contract\n')
    with pytest.raises(ce.EvidenceError, match='snapshot_stale'):
        br.check_snapshot(snap)


def test_rename_binary_delete_mode_and_closing_inventory(repo):
    (repo / 'product/delete.txt').write_text('delete me\n')
    (repo / 'product/rename.txt').write_text('unique rename contents\n' * 8)
    (repo / 'product/mode.sh').write_text('#!/bin/sh\ntrue\n')
    command(repo, 'add', '-A'); command(repo, 'commit', '-m', 'more base')
    before = command(repo, 'rev-parse', 'HEAD').decode().strip()
    (repo / 'product/rename.txt').rename(repo / 'product/renamed.txt')
    (repo / 'product/delete.txt').unlink()
    (repo / 'product/mode.sh').chmod(0o755)
    (repo / 'product/bytes.bin').write_bytes(bytes(range(256)))
    command(repo, 'add', '-A'); command(repo, 'commit', '-m', 'target')
    p = snapshot(repo, mode='closing', base=before)
    s = br.check_snapshot(p)
    assert {'R100', 'D', 'A', 'M'} <= {r['status'] for r in s['inventory']}
    assert any(r['old_mode'] == '100644' and r['new_mode'] == '100755' for r in s['inventory'])
    with pytest.raises(ce.EvidenceError, match='uninspectable'):
        br.plan(p, config(repo))


def test_dependency_graph_has_real_endpoints_and_reverse_test_context(repo):
    (repo / 'other').mkdir()
    (repo / 'other/consumer.py').write_text('from product.producer import produce\ndef consume():\n    return produce() + 1\n')
    p = br.check_plan(planned(repo))
    units = [i for i in p['items'] if i['kind'] == 'unit']
    integration = [i for i in p['items'] if i['kind'] == 'integration']
    assert len(units) == 2 and len(integration) == 1 and len(p['relations']) == 1
    body = json.loads(br.read(integration[0]['package']).decode()[len(br.PREFIX):])
    assert {'product/producer.py', 'other/consumer.py'} <= {r['path'] for r in body['contents']}
    matrix = body['relation_matrix']
    assert [matrix['endpoints'][i]['change'] for i in matrix['relations'][0]['endpoints']] == body['changes']
    assert 'return produce() + 1' in str(body['contents'])


@pytest.mark.parametrize('mutation', ['unit-gap', 'duplicate', 'empty-relations', 'relation-gap', 'sha', 'snapshot', 'context', 'budget-source'])
def test_manifest_cannot_omit_duplicate_or_substitute_coverage(repo, mutation):
    (repo / 'other').mkdir()
    (repo / 'other/consumer.py').write_text('from product.producer import produce\nVALUE = produce()\n')
    path = planned(repo); p = br.load(path); p.pop('integrity_sha256')
    if mutation == 'unit-gap': p['items'].pop(0)
    elif mutation == 'duplicate': p['items'].append(copy.deepcopy(p['items'][0]))
    elif mutation == 'empty-relations': p['relations'] = []
    elif mutation == 'relation-gap': p['items'] = [i for i in p['items'] if i['kind'] != 'integration']
    elif mutation == 'sha':
        package = Path(p['items'][0]['package']); package.chmod(0o600); package.write_text('stale')
    elif mutation == 'snapshot': p['snapshot_sha256'] = '0' * 64
    elif mutation == 'context': p['implementation']['codex_context.py'] = '0' * 64
    else: Path(p['config']['limit_source']['path']).write_text('changed')
    path.chmod(0o600); br.save(path, p)
    with pytest.raises(ce.EvidenceError): br.check_plan(path)


def test_unknown_dependency_and_indivisible_budget_block_before_births(repo):
    p = repo / 'product/producer.py'
    p.write_text('module = __import__(input())\n')
    snap = snapshot(repo)
    with pytest.raises(ce.EvidenceError, match='unknown_dependency'):
        br.plan(snap, config(repo))
    p.write_text('VALUE = 2\n')
    snap = snapshot(repo, name='new')
    with pytest.raises(ce.EvidenceError, match='budget_insufficient'):
        br.plan(snap, config(repo, limit=100))


def test_small_path_is_one_unit_and_no_synthetic_relations(repo):
    p = br.check_plan(planned(repo))
    assert len(p['items']) == 1 and p['items'][0]['kind'] == 'unit'
    assert p['relations'] == []
    assert p['items'][0]['budget']['estimated_total'] < 500000
    assert set(p['items'][0]['budget']['overhead']) == set(br.COSTS)
    with pytest.raises(ce.EvidenceError, match='inactive'):
        br.require_activation(None, repo)


def test_small_coherent_area_keeps_one_native_pair_for_multiple_files(repo):
    (repo / 'product/consumer.py').write_text('from product.producer import produce\nVALUE = produce()\n')
    p = br.check_plan(planned(repo))
    assert len(p['atoms']) == 2 and len(p['items']) == 1
    assert p['items'][0]['kind'] == 'unit' and len(p['items'][0]['relations']) == 1
    assert p['execution_estimate']['semantic_reviewers'] == 2


def test_independent_components_have_auditable_analysis_not_synthetic_pairs(repo):
    (repo / 'unrelated').mkdir()
    (repo / 'unrelated/note.txt').write_text('Independent publication wording.\n')
    path = planned(repo); p = br.check_plan(path)
    assert p['relations'] == [] and len(p['items']) == 2
    assert len(p['discovery']['facts']) == len(p['discovery']['isolated']) == 2
    assert all(f['source_sha256'] and f['path'] for f in p['discovery']['facts'])
    p.pop('integrity_sha256'); p['discovery']['facts'] = []
    path.chmod(0o600); br.save(path, p)
    with pytest.raises(ce.EvidenceError, match='relation_coverage'):
        br.check_plan(path)


def test_configuration_scope_links_components_without_imports(repo):
    (repo / 'package.json').write_text('{"type":"module"}\n')
    p = br.check_plan(planned(repo))
    assert any('configuration scope: package.json' in r['reason'] for r in p['relations'])


def bounded_payload(p, item, role, *, finding=False):
    return json.dumps(dict(schema=br.VERSION, item=item['id'], snapshot=p['snapshot_sha256'],
        role=role, changes=item['changes'], relations=item['relations'],
        verdict='FINDINGS' if finding else 'PASS', findings=['producer int incompatible with consumer str'] if finding else [], discovered_relations=[]))


def replace_payloads(d, package, p, item, *, finding=False):
    native = cs.read_package(package)
    for role_index, role in enumerate(cs.ROLES):
        child = native['phase'] + '-child-' + str(role_index)
        old = next(r['payload']['last_agent_message'] for r in d.rows[child] if r['type'] == 'event_msg' and r['payload'].get('type') == 'task_complete')
        new = bounded_payload(p, item, role, finding=finding)
        for session in (child, d.coordinator):
            for row in d.rows[session]:
                payload = row['payload']
                if row['type'] == 'event_msg' and payload.get('type') == 'task_complete' and payload.get('last_agent_message') == old:
                    payload['last_agent_message'] = new
                if row['type'] == 'response_item' and payload.get('type') == 'agent_message' and payload.get('author') == '/root/' + native['spawns'][role_index]['task_name']:
                    for block in payload.get('content', []):
                        if block.get('text', '').endswith('Payload:\n' + old):
                            block['text'] = block['text'][:-len(old)] + new
            d.flush(session)


def drive_fixture(d, plan_path, ledger, *, finding=False):
    """Drive real controller/helpers over controlled native records, no live LM."""
    p = br.load(plan_path); item = p['items'][0]
    action = br.advance(ledger, runtime=d.rt, activation=str(ledger.parent / 'activation.fixture'))
    cp_path = [e for e in br.load(ledger)['events'] if e['kind'] == 'attempt'][-1]['checkpoint']
    cp = ct.read_checkpoint(cp_path)
    bootstrap = Path([e['package'] for e in ct.events(cp, d.root) if e['kind'] == 'review_package'][-1])
    with d.monkeypatch.context() as setup:
        setup.setattr(cs, 'prepare', lambda **kwargs: {'package': str(bootstrap)})
        d.bootstrap()
    refusal = d.command_event(d.principal, 'principal-turn', cs.command(bootstrap, 'route-check'), {'result': 'blocked', 'code': 'review_route_unqualified'})
    refusal['payload']['item'].update(status='failed', exit_code=1); d.flush(d.principal)
    for phase in (('context', 'probe') if p['diagnostic'] else ('context', 'probe', 'review')):
        action = br.advance(ledger, runtime=d.rt, activation=str(ledger.parent / 'activation.fixture'))
        assert action['action'] == 'execute_exact_native_command'
        package = Path([e['package'] for e in ct.events(cp, d.root) if e['kind'] == 'review_package'][-1])
        assert cs.read_package(package)['phase'] == phase
        d.finish_children(package)
        if phase == ('probe' if p['diagnostic'] else 'review'):
            replace_payloads(d, package, p, item, finding=finding)
    return br.advance(ledger, runtime=d.rt, activation=str(ledger.parent / 'activation.fixture'))


@pytest.mark.parametrize('surface', ['codex-tui', 'codex_exec'])
def test_terminal_plan_native_collection_verify_resume_no_repeated_birth(dedicated, surface):
    d = dedicated; prepare(d.root)
    d.rows[d.principal][0]['payload']['originator'] = surface; d.flush(d.principal)
    plan = planned(d.root); ledger = plan.parent / 'ledger.json'
    br.new_ledger(plan, ledger)
    assert drive_fixture(d, plan, ledger)['result'] == 'item_verified'
    before = br.read(ledger)
    assert br.advance(ledger, runtime=d.rt)['result'] == 'diagnostic_verified'
    assert br.read(ledger) == before
    assert len([e for e in br.load(ledger)['events'] if e['kind'] == 'attempt']) == 1
    assert br.pending(ledger, runtime=d.rt)[1] == []
    # Historical completion does not confer product acceptance or activation.
    assert br.verify(ledger, runtime=d.rt)['result'] == 'diagnostic_verified'
    with pytest.raises(ce.EvidenceError, match='activation_scope'):
        fake = ledger.parent / 'fake.json'; br.save(fake, {'enabled': True})
        br.require_activation(fake, d.root, runtime=d.rt)


@pytest.mark.parametrize('fault', ['compaction', 'model', 'sandbox', 'incomplete', 'delivery', 'source-missing', 'source-changed'])
def test_completed_ledger_reopens_sources_and_preserves_failure(dedicated, fault):
    d = dedicated; prepare(d.root)
    plan = planned(d.root); ledger = plan.parent / 'ledger.json'; br.new_ledger(plan, ledger)
    drive_fixture(d, plan, ledger)
    child = 'probe-child-0'
    if fault == 'source-missing': d.paths[child].unlink()
    elif fault == 'source-changed': d.rows[child][0]['payload']['cwd'] = '/other'; d.flush(child)
    else:
        if fault == 'compaction': d.rows[child].append(d.row('compacted', {'type': 'context_compacted'}))
        elif fault == 'model': next(r['payload'] for r in d.rows[child] if r['type'] == 'turn_context')['model'] = 'wrong'
        elif fault == 'sandbox': next(r['payload'] for r in d.rows[child] if r['type'] == 'turn_context')['sandbox_policy'] = {'type': 'workspace-write'}
        elif fault == 'incomplete': d.rows[child] = [r for r in d.rows[child] if r['payload'].get('type') != 'task_complete']
        elif fault == 'delivery': d.rows[child] = [r for r in d.rows[child] if r['payload'].get('item', {}).get('type') != 'CommandExecution']
        d.flush(child)
    with pytest.raises((ce.EvidenceError, ValueError, OSError)):
        br.verify(ledger, runtime=d.rt)
    history = br.load(ledger)['events']
    assert any(e['kind'] == 'complete' for e in history)
    assert history[-1]['kind'] == 'failure'


def test_partial_ledger_global_invalidation_keeps_completed_history(repo):
    path = planned(repo); ledger = path.parent / 'ledger.json'; br.new_ledger(path, ledger)
    br.event(ledger, 'failure', code='interrupted')
    assert len(br.pending(ledger)[1]) == 1
    (repo / 'product/new.txt').write_text('new relevant artifact')
    with pytest.raises(ce.EvidenceError): br.pending(ledger)
    assert [e['code'] for e in br.load(ledger)['events']] == ['interrupted', 'global_invalidation']


@pytest.mark.parametrize('cause', ['bounded_findings', 'bounded_unknown_dependency'])
def test_semantic_failure_cannot_resample_verdict_on_same_snapshot(repo, cause, monkeypatch):
    path = planned(repo); p = br.load(path); ledger = path.parent / 'ledger.json'
    br.new_ledger(path, ledger)
    br.event(ledger, 'failure', item=p['items'][0]['id'], code=cause)
    monkeypatch.setattr(ct, 'start', lambda **kwargs: pytest.fail('semantic failure must not launch another attempt'))
    before = br.read(ledger)
    with pytest.raises(ce.EvidenceError, match='retry_requires_replan'):
        br.retry(ledger, p['items'][0]['id'])
    assert br.read(ledger) == before


def test_technical_retry_is_explicit_pending_only_and_once(repo, monkeypatch):
    path = planned(repo); p = br.load(path); ledger = path.parent / 'ledger.json'
    br.new_ledger(path, ledger); item = p['items'][0]['id']
    br.event(ledger, 'failure', item=item, code='native_process_interrupted')
    checkpoint = str(path.parent / 'new-attempt.json')
    launches = []
    def start(**kwargs):
        launches.append(kwargs)
        return {'checkpoint': checkpoint}
    monkeypatch.setattr(ct, 'start', start)
    assert br.retry(ledger, item)['checkpoint'] == checkpoint
    assert len(launches) == 1 and launches[0]['diff'] == p['items'][0]['package']
    assert [e['kind'] for e in br.load(ledger)['events']] == ['failure', 'retry', 'attempt']
    with pytest.raises(ce.EvidenceError, match='retry_ceiling'):
        br.retry(ledger, item)
    with pytest.raises(ce.EvidenceError, match='retry_not_pending'):
        br.retry(ledger, 'unplanned-item')
    assert len(launches) == 1


def test_group_consolidation_preserves_every_relation_once_with_budget(repo):
    for n in range(3):
        area = repo / ('area' + str(n)); area.mkdir()
        (area / 'consumer.py').write_text('from product.producer import produce\nVALUE = produce()\n')
    first = planned(repo)
    p = br.check_plan(first)
    groups = [i for i in p['items'] if i['kind'] == 'integration']
    assert len(p['relations']) == 3 and len(groups) == 1
    assert p['execution_estimate']['semantic_pairs'] == 5
    smaller = config(repo, limit=groups[0]['budget']['estimated_total'] - 1)
    second_snapshot = snapshot(repo, name='smaller')
    bounded = br.check_plan(br.plan(second_snapshot, smaller, diagnostic=True))
    groups = [i for i in bounded['items'] if i['kind'] == 'integration']
    assert 1 < len(groups) <= 3
    claimed = [r for i in groups for r in i['relations']]
    assert len(claimed) == len(set(claimed)) == 3
    assert all(i['budget']['estimated_total'] < smaller['limit'] for i in bounded['items'])


def test_unknown_dependency_can_be_replanned_with_real_bound_context(repo):
    path = repo / 'product/producer.py'
    path.write_text('module = __import__(input())\n')
    helper = repo / 'product/helper.py'
    helper.write_text('VALUE = 42\n')
    snap = snapshot(repo)
    with pytest.raises(ce.EvidenceError, match='unknown_dependency'):
        br.plan(snap, config(repo))
    resolution = dict(path='product/producer.py', sha256=ce.digest(path.read_bytes()),
                      line=1, call='__import__(input())', targets=['product/helper.py'],
                      reason='Fixture maps the external name contract to actual helper code; native reviewers still judge that claim.')
    p = br.check_plan(br.plan(snap, config(repo), diagnostic=True, resolutions=[resolution]))
    body = json.loads(br.read(p['items'][0]['package']).decode()[len(br.PREFIX):])
    assert body['dependency_resolutions'] == [resolution]
    assert any(r['path'] == 'product/helper.py' for r in body['contents'])


def test_added_nested_patch_atoms_reconstruct_all_bytes_and_reject_omission(repo):
    nested = ('diff --git a/code.py b/code.py\nnew file mode 100644\n--- /dev/null\n+++ b/code.py\n@@ -0,0 +1 @@\n+VALUE = 2\n'
              'diff --git a/test_code.py b/test_code.py\nnew file mode 100644\n--- /dev/null\n+++ b/test_code.py\n@@ -0,0 +1 @@\n+assert VALUE == 2\n')
    text = ('diff --git a/candidate.patch b/candidate.patch\nnew file mode 100644\n--- /dev/null\n+++ b/candidate.patch\n@@ -0,0 +1 @@\n' +
            ''.join('+' + line for line in nested.splitlines(keepends=True)) +
            'diff --git a/README b/README\nnew file mode 100644\n--- /dev/null\n+++ b/README\n@@ -0,0 +1 @@\n+contract\n')
    artifact = repo / 'product/retained.patch'; artifact.write_text(text)
    snap = snapshot(repo); s = br.check_snapshot(snap)
    atoms = br.review_atoms(s)
    pieces = [a for a in atoms if a.get('parent_change')]
    assert len(pieces) == 3 and max(a['nesting_depth'] for a in pieces) == 1
    assert b''.join(text.encode()[a['source_span']['start']:a['source_span']['end']] for a in pieces) == text.encode()
    whole = next(r for r in s['inventory'] if r['new'].endswith('retained.patch'))
    assert b''.join(br.atom_patches(repo, pieces).values()) == br.patch_bytes(repo, whole)
    p = br.check_plan(br.plan(snap, config(repo), diagnostic=True))
    assert len(p['atoms']) == 4  # producer + three coherent retained-patch units
    assert {a['logical_header'] for a in pieces} == {'diff --git a/code.py b/code.py', 'diff --git a/test_code.py b/test_code.py', 'diff --git a/README b/README'}


def test_retained_1586532_byte_case_plans_all_sections_with_bounded_groups(repo):
    import hashlib
    fixture = os.environ.get('BOUNDED_RETAINED_PATCH')
    if not fixture:
        pytest.skip('large retained artifact supplied explicitly by validation harness')
    pytest.importorskip('tiktoken', reason='optional versioned tokenizer required for this retained-case harness')
    body = Path(fixture).read_bytes()
    assert len(body) == 1586532 and hashlib.sha256(body).hexdigest() == '94512ff26dd0542e8519534a51d7aefb8e61fceabdd0971c361d7fefdc12adad'
    (repo / 'product/retained.patch').write_bytes(body)
    (repo / 'product/producer.py').write_text('def produce():\n    return 1\n')
    cfg = config(repo, limit=475000)
    cfg['overhead'] = dict(instructions=24000, tools=32000, calls=4000, outputs=16000,
                           framing=8000, analysis=48000, verdict=8000)
    cfg['tokenizer'] = {'method': 'dual-tiktoken-v1', 'version': '0.14.0'}
    snap = snapshot(repo)
    path = br.plan(snap, cfg, diagnostic=True)
    p = br.check_plan(path)
    pieces = [a for a in p['atoms'] if a.get('parent_change')]
    assert len(pieces) >= 129
    assert b''.join(body[a['source_span']['start']:a['source_span']['end']] for a in pieces) == body
    assert any(a['source_span']['start'] >= 1056482 for a in pieces)  # retain all 530,050 extra bytes
    assert sum(a['source_span']['end'] - a['source_span']['start'] for a in pieces) == 1586532
    claims = [r for i in p['items'] for r in i['relations']]
    assert len(claims) == len(set(claims)) == len(p['relations'])
    assert all(i['budget']['estimated_total'] < 475000 for i in p['items'])
    assert p['execution_estimate']['integration_groups'] < len(p['relations'])
    print('RETAINED_CASE_PLAN=' + json.dumps(dict(plan=str(path), **p['execution_estimate']), sort_keys=True))


def test_product_source_fixture_preserves_historical_ttl_but_new_launch_expires(dedicated):
    d = dedicated; prepare(d.root)
    # This fixture substitutes ONLY external activation and live GitHub Status,
    # never native chain/context/probe/model/payload/stage-source verification.
    d.monkeypatch.setattr(br, 'require_activation', lambda *args, **kwargs: {})
    d.monkeypatch.setattr(ct, 'state', lambda *args, **kwargs: {'q': 'Code Review'})
    path = planned(d.root, diagnostic=False); ledger = path.parent / 'ledger.json'
    br.new_ledger(path, ledger)
    assert drive_fixture(d, path, ledger)['result'] == 'item_verified'
    assert not (d.root / '.cursor/tmp/codex-child-proxies.jsonl').exists()
    assert list(path.parent.glob('*.native-proxies.jsonl'))
    d.now += cs.STAGE_MAX_AGE_MS + 1
    assert br.verify(ledger, runtime=d.rt, activation=str(ledger.parent / 'activation.fixture'))['result'] == 'verified'
    # Fresh product work must independently pass current native stage timing.
    p = br.load(path)
    cp = [e for e in br.load(ledger)['events'] if e['kind'] == 'attempt'][-1]['checkpoint']
    package = Path([e['package'] for e in ct.events(ct.read_checkpoint(cp), d.root) if e['kind'] == 'review_package'][-1])
    with pytest.raises(ce.EvidenceError, match='review_stage_status_expired'):
        cs.verify_stage_receipt(package, runtime=d.rt)


def test_integration_contract_fixture_detects_cross_unit_defect(dedicated):
    d = dedicated; prepare(d.root)
    (d.root / 'other').mkdir()
    (d.root / 'other/consumer.py').write_text('# Input contract: product/producer.py supplies value\ndef consume(value):\n    return value.upper()\n')
    # Both local contracts pass independently; real integration code fails.
    producer = {}; consumer = {}
    exec((d.root / 'product/producer.py').read_text(), producer)
    exec((d.root / 'other/consumer.py').read_text(), consumer)
    assert producer['produce']() == 2
    assert consumer['consume']('ok') == 'OK'
    with pytest.raises(AttributeError): consumer['consume'](producer['produce']())
    path = planned(d.root); p = br.load(path)
    integration = next(i for i in p['items'] if i['kind'] == 'integration')
    d.bootstrap(); d.context()
    refusal = d.command_event(d.principal, 'principal-turn', cs.command(d.bootstrap_path, 'route-check'),
                              {'result': 'blocked', 'code': 'review_route_unqualified'})
    refusal['payload']['item'].update(status='failed', exit_code=1); d.flush(d.principal)
    package = Path(cs.prepare(root=d.root, phase='probe', bootstrap=d.bootstrap_path,
                              diff=integration['package'], runtime=d.rt)['package'])
    d.finish_children(package)
    replace_payloads(d, package, p, integration, finding=True)
    # Both named native-source fixtures actually receive the integration bytes.
    import codex_review_probe as rp
    proofs = [ce.collect(b, runtime=d.rt, wait_seconds=0) for b in cs.read_package(package)['births']]
    rp.qualify([x['evidence_path'] for x in proofs], root=d.root, runtime=d.rt)
    cs.qualify_route(package, runtime=d.rt)
    # Contract result fixture is deliberately not an LM-understanding claim.
    for proof in proofs:
        with pytest.raises(ce.EvidenceError, match='bounded_findings'):
            br.native_result(proof, integration, p, runtime=d.rt)
    with pytest.raises(ce.EvidenceError, match='bounded_findings'):
        br.verify_item(p, integration, {'evidence': [x['evidence_path'] for x in proofs]}, runtime=d.rt)
