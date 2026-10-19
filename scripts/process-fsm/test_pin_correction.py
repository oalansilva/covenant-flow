"""Regression fixtures for the v1.1.23 correction; never live qualification."""
import copy
import json
from pathlib import Path

import pytest

import codex_binding as cb
import codex_evidence as ce
import codex_review_probe as rp
import codex_review_session as cs
from model_selection_fixtures import machine_models
from test_codex_review_probe import chunked_diagnostic
from test_codex_review_session import dedicated, qualified_route


@pytest.mark.parametrize("command", [
    'rg "cp.*" scripts',
    "rg 'cp .* $TARGET' scripts",
    'printf "%s" "cp source destination; mkdir x; rm y"',
    "printf '%s' 'echo x > backend/example.py'",
    "cat <<'TEXT'\ncp $SOURCE $TARGET\nTEXT",
    'rg "install|cp|mv" scripts && rg "mkdir.*" docs',
    'bash -n install.sh',
])
def test_quoted_searches_and_stored_examples_are_not_executable_mutations(command):
    assert cb.mutation_paths({"tool_name": "Bash", "tool_input": {"command": command}}) == []


@pytest.mark.parametrize("command,paths", [
    ('cp source.txt backend/target.py', ['source.txt', 'backend/target.py']),
    ('rg "cp.*" scripts; touch backend/actual.py', ['backend/actual.py']),
    ('printf "%s" "cp x y" > backend/actual.py', ['backend/actual.py']),
    ('touch backend/one.py\nrm backend/two.py', ['backend/one.py', 'backend/two.py']),
    ('"cp" source.txt backend/target.py', ['source.txt', 'backend/target.py']),
    ('sed -i "s/old/new/" backend/target.py', ['backend/target.py']),
    ('cp --target-directory=backend source.txt', ['backend', 'source.txt']),
])
def test_static_real_segments_keep_all_mutation_targets(command, paths):
    assert cb.mutation_paths({"tool_name": "Bash", "tool_input": {"command": command}}) == paths


@pytest.mark.parametrize("command", [
    'rg "cp.*" scripts; cp $SOURCE backend/target.py',
    'cd backend; touch target.py',
    'git -C other status; touch backend/target.py',
    'bash -c "cp source backend/target.py"',
    'env MODE=x cp source backend/target.py',
    'rg "$(cp source backend/target.py)" scripts',
    'touch backend/*.py',
    'printf x > $TARGET',
    'bash -c "printf x > /outside"',
    'eval "printf x > /outside"',
    'bash -n +n -c "touch /outside"',
])
def test_dynamic_real_mutations_still_refuse(command):
    with pytest.raises(cb.BindingError, match='unsupported_targets'):
        cb.mutation_paths({"tool_name": "Bash", "tool_input": {"command": command}})


@pytest.mark.parametrize('phase', ['context', 'probe', 'review'])
@pytest.mark.parametrize('fault', ['late', 'missing', 'failed', 'wrong-turn', 'wrong-release'])
def test_complete_binding_requires_preflight_before_births_for_every_phase(dedicated, phase, fault):
    d = dedicated
    if phase == 'context':
        d.bootstrap()
        path = Path(cs.prepare(root=d.root, phase=phase, bootstrap=d.bootstrap_path, runtime=d.rt)['package'])
        d.finish_children(path)
    elif phase == 'probe':
        d.bootstrap(); d.context()
        path = d.probe()
    else:
        qualified_route(d)
        diff = d.root / 'review.patch'; diff.write_text('diff --git a/x b/x\n-old\n+new\n')
        path = Path(cs.prepare(root=d.root, phase=phase, bootstrap=d.bootstrap_path, diff=diff, runtime=d.rt)['package'])
        d.finish_children(path)
    chain = cs.binding(path, runtime=d.rt, complete=True)
    rows = d.rows[d.coordinator]
    event = next(row for row in rows if row['payload'].get('item', {}).get('command', [None])[-1] == cs.command(path, 'preflight'))
    item = event['payload']['item']
    assert any(ref.get('command_id') == item['id'] for ref in chain['sources'])
    if fault == 'missing': rows.remove(event)
    elif fault == 'late':
        rows.remove(event)
        rows.insert(len(rows) - 1, event)
    elif fault == 'failed': item.update(status='failed', exit_code=1)
    elif fault == 'wrong-turn': event['payload']['turn_id'] = 'other-turn'
    else:
        output = json.loads(item['aggregated_output']); output['work_release'] = 'unapproved'
        item['aggregated_output'] = json.dumps(output)
    d.flush(d.coordinator)
    with pytest.raises(ce.EvidenceError): cs.binding(path, runtime=d.rt, complete=True)


@pytest.mark.parametrize('size', [900641, 940641])
def test_large_diff_is_delivered_by_literal_next_commands(tmp_path, monkeypatch, machine_models, size):
    text = None
    if size == 900641:
        text = ('diff --git a/x b/x\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n'
                + ('+' + 'x' * 194 + '"' * 6 + '\n') * 5000)[:size]
    e, path, probe, manifest, chunks = chunked_diagnostic(tmp_path, monkeypatch, chars=size, diff_text=text)
    plan = rp.read_plan(path)
    assert manifest['diff_bytes'] > 900000 and manifest['chunk_count'] >= 67
    if size == 900641:
        assert manifest['chunk_count'] == 67
    expected = manifest['next_read_command']
    for index, chunk in enumerate(chunks):
        item = chunk['payload']['item']
        assert item['command'][-1] == expected
        assert str(e.root) not in expected and '../' not in expected
        body = json.loads(item['aggregated_output'])
        assert body['chunk_index'] == index
        expected = body['next_read_command']
    assert expected is None
    proof = e.collect()
    assert proof['review_observation']['delivered_bytes'] == size
    ce.verify_evidence(proof['evidence_path'])


@pytest.mark.parametrize('fault', ['equivalent-path', 'cwd', 'reordered', 'truncated', 'next-command'])
def test_next_command_contract_never_relaxes_native_delivery(tmp_path, monkeypatch, machine_models, fault):
    e, path, probe, manifest, chunks = chunked_diagnostic(tmp_path, monkeypatch, chars=48000)
    item = chunks[1]['payload']['item']
    if fault == 'equivalent-path':
        item['command'][-1] = item['command'][-1].replace(' --plan ', ' --plan ./')
    elif fault == 'cwd': item['cwd'] = (e.root / 'wrong-directory').as_uri()
    elif fault == 'reordered':
        a, b = e.c.index(chunks[0]), e.c.index(chunks[1])
        e.c[a], e.c[b] = e.c[b], e.c[a]
    elif fault == 'truncated': item['aggregated_output'] = item['aggregated_output'][:200]
    else:
        result = json.loads(item['aggregated_output']); result['next_read_command'] = 'echo substitute'
        item['aggregated_output'] = json.dumps(result)
    e.write(e.child, e.c)
    with pytest.raises(ce.EvidenceError): e.collect()
