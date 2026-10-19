"""Terminal principal checkpoints and bounded diagnostic recovery.

This controller runs in the card's principal. Native spawn/relay actions are
returned to that same agent, never replaced with a Python-created observation.
It does not execute FSM events, record trust, author delegated work or deploy.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_evidence as ce
import codex_context as cc
from codex_qualification_index import Index, SURFACES, checked_path
from model_selection import resolve, save_capture

SCHEMA = 'codex-terminal-checkpoint-v1'
OPERATIONS = {
    'create': (None, {None}),
    'refine': ('grill-card', {'Em Refinamento'}),
    'design': ('design-autor', {'Todo', 'Design'}),
    'critique': ('design-critic', {'Design'}),
    'apply': ('apply-coluna', {'Pronto para Dev', 'Em desenvolvimento'}),
    'review': ('pedir_review', {'Em desenvolvimento', 'Code Review'}),
    'qa': ('qa-gate', {'Code Review', 'QA'}),
    'integrate': ('qa-gate', {'QA'}),
    'homologation': (None, {'Done'}),
    'release': ('fecho-lote', {'Homologado'}),
}
PREPARATION_EVENTS = {
    'design': ('Todo', 'iniciar_design'),
    'apply': ('Pronto para Dev', 'iniciar_apply'),
    'qa': ('Code Review', 'aceitar_sha'),
}


def fail(code, detail=''):
    raise ce.EvidenceError(code, detail, recovery='preserve checkpoint and artifacts; resolve this concrete cause before retrying')


def active(runtime=None):
    rt = runtime or ce.Rollout()
    session = os.environ.get('CODEX_THREAD_ID')
    if not session:
        fail('session_unavailable')
    source, rows, meta, turns = rt.session(session)
    if meta['originator'] not in SURFACES:
        fail('terminal_surface_unverified', meta['originator'])
    if any(row['type'] == 'event_msg' and row['payload'].get('type') == 'task_complete'
           and row['payload'].get('turn_id') == turns[-1]['turn_id'] for _, row, _ in rows):
        fail('session_inactive')
    return rt, session, source, rows, meta, turns[-1]


def state(root, card, operation, authority=None):
    from resolve import resolve as binding
    from guard import github_status_provider
    bound = binding(root, root)
    if operation == 'create':
        if str(bound['bound_card']) != '⊥':
            fail('terminal_card_mismatch', 'create a new card from the unbound workspace')
        return dict(bound, q=None)
    if operation == 'release' and str(bound['bound_card']) == '⊥':
        from overlay import load_overlay
        overlay = load_overlay(root, require_filled=True)
        branch = bound['q_git']
        if branch != overlay['integration_branch'] and not branch.startswith('release-'):
            fail('terminal_card_mismatch', 'unbound release requires integration or release branch')
        status = github_status_provider(str(card))
        if status != 'Homologado':
            fail('terminal_status_mismatch', f'release card Status={status}')
        return dict(bound, q=status)
    if operation != 'refine' and str(bound['bound_card']) != str(card):
        fail('terminal_card_mismatch', f'expected={card}; observed={bound["bound_card"]}')
    if operation == 'refine' and str(bound['bound_card']) not in {'⊥', str(card)}:
        fail('terminal_card_mismatch', 'refinement cannot use another card worktree')
    if authority is not None:
        import process_authority as pa
        pa.verify(authority, card)
        status = github_status_provider(str(card), authority=authority)
    else:
        status = github_status_provider(str(card))
    if status not in OPERATIONS[operation][1]:
        fail('terminal_status_mismatch', f'operation={operation}; Status={status}')
    return dict(bound, q=status)


def read_checkpoint(path):
    path = checked_path(path)
    value = ce.check_seal(json.loads(path.read_text()))
    if value.get('schema') != SCHEMA or value.get('operation') not in OPERATIONS:
        fail('checkpoint_invalid')
    if path.name != value['checkpoint_id'] + '.checkpoint.json':
        fail('checkpoint_invalid', 'checkpoint id/path mismatch')
    return value


def event_directory(checkpoint, root):
    return ce.destination(root, Path('.cursor/tmp/codex-terminal') / checkpoint['checkpoint_id'])


def events(checkpoint, root):
    directory = event_directory(checkpoint, root)
    result = []
    for path in sorted(directory.glob('event-*.json')):
        checked_path(path)
        item = ce.check_seal(json.loads(path.read_text()))
        if item.get('checkpoint_id') != checkpoint['checkpoint_id'] or item.get('sequence') != len(result):
            fail('checkpoint_history_invalid')
        if item.get('previous_sha256') != (result[-1]['integrity_sha256'] if result else checkpoint['integrity_sha256']):
            fail('checkpoint_history_invalid')
        result.append(item)
    return result


def append(checkpoint, root, kind, **fields):
    prior = events(checkpoint, root)
    event = ce.sealed(dict(fields, schema=SCHEMA, checkpoint_id=checkpoint['checkpoint_id'],
                           sequence=len(prior), kind=kind,
                           previous_sha256=prior[-1]['integrity_sha256'] if prior else checkpoint['integrity_sha256']))
    ce.private_write(event_directory(checkpoint, root) / f'event-{len(prior):06d}.json', event)
    return event


def start(*, root, card, operation, target_root=None, diagnostics_authorized=False,
          release_requested=False, question=None, diff=None, authority_root=None, runtime=None):
    rt, session, source, rows, meta, turn = active(runtime)
    root = Path(root).resolve()
    if Path(turn['cwd']).resolve() != root:
        fail('worktree_mismatch', 'checkpoint must be born in the active native cwd')
    if operation not in OPERATIONS or (operation != 'create' and not str(card).isdigit()):
        fail('checkpoint_invalid')
    if operation == 'release' and not release_requested:
        fail('release_request_missing', 'Apply/homologation never authorizes release')
    authority = None
    if authority_root is not None:
        if operation != "review" or Path(target_root or root).resolve() != root:
            fail("terminal_authority_scope", "external authority supports Review in the same native root only")
        import process_authority as pa
        try:
            authority = pa.capture(authority_root, card)
        except pa.AuthorityError as exc:
            fail("terminal_authority_invalid", str(exc))
    token = secrets.token_hex(16)
    checkpoint = ce.sealed({'schema': SCHEMA, 'checkpoint_id': token, 'session': session,
        'surface': meta['originator'], 'host_version': meta['cli_version'], 'source': str(source),
        'before_record': len(rows), 'birth_root': str(root), 'target_root': str(Path(target_root or root).resolve()),
        'card': str(card), 'operation': operation, 'diagnostics_authorized': diagnostics_authorized,
        'release_requested': release_requested, 'question': question, 'authority': authority,
        'principal_model': turn.get('model', ce.UNAVAILABLE),
        'principal_effort': turn.get('effort', ce.UNAVAILABLE),
        'diff': str(checked_path(diff)) if diff is not None else None,
        'diff_sha256': ce.digest(checked_path(diff).read_bytes()) if diff is not None else None})
    path = ce.destination(root, '.cursor/tmp/codex-terminal') / (token + '.checkpoint.json')
    ce.private_write(path, checkpoint)
    return {'result': 'checkpoint_created', 'checkpoint': str(path), 'checkpoint_id': token}


def resume_action(checkpoint):
    base = ['codex', '--cd', checkpoint['target_root']]
    if checkpoint['surface'] == 'codex_exec':
        base += ['exec', 'resume', checkpoint['session'], '--json', '-']
    else:
        base += ['resume', checkpoint['session']]
    return {'action': 'operator_native_resume', 'command': shlex.join(base),
            'stdin_contract': f'checkpoint: {checkpoint["checkpoint_id"]}\nanswer: <explicit human answer>'
            if checkpoint['question'] else 'Resume this checkpoint and revalidate native cwd/state.',
            'question': checkpoint['question'], 'automatic_rebind': 'unavailable',
            'required_observation': 'same session UUID; new active turn_context at target_root; explicit native user answer when requested'}


def human_answer(checkpoint, rows):
    marker = 'checkpoint: ' + checkpoint['checkpoint_id']
    answers = []
    for ordinal, row, raw_sha in rows:
        payload = row['payload']
        if ordinal < checkpoint['before_record'] or row['type'] != 'response_item':
            continue
        if payload.get('type') != 'message' or payload.get('role') != 'user':
            continue
        message = cc.text(payload)
        lines = message.splitlines()
        if marker in lines:
            values = [line.removeprefix('answer: ').strip() for line in lines if line.startswith('answer: ')]
            if len(values) == 1 and values[0] and values[0] != '<explicit human answer>':
                answers.append({'source': checkpoint['source'], 'ordinal': ordinal,
                                'raw_sha256': raw_sha, 'answer': values[0]})
    if len(answers) > 1:
        fail('human_answer_ambiguous', 'multiple answers for this checkpoint; ask an explicit new question')
    return answers[0] if answers else None


def failure(checkpoint, root, error, *, sources=None):
    code = getattr(error, 'code', 'invalid_input')
    observed = getattr(error, 'observed', ce.UNAVAILABLE)
    cause = observed.get('qualification_cause', code) if isinstance(observed, dict) else code
    # Source fingerprints are decisive artifacts, never rollout mtimes or an
    # unrelated tool call's growing transcript length.
    fingerprint = ce.digest(sources or {})
    history = events(checkpoint, root)
    identical = [e for e in history if e['kind'] == 'failure' and e['cause'] == cause and e['sources_sha256'] == fingerprint]
    item = append(checkpoint, root, 'failure', code=code, cause=cause, sources_sha256=fingerprint,
                  detail=str(error), scope={'session': checkpoint['session'], 'root': str(root)},
                  retry=len(identical))
    return {'result': 'blocked' if identical else 'recovery_required', 'code': code, 'cause': cause,
            'same_cause_retry_remaining': max(0, 1 - len(identical)),
            'original_failure': identical[0]['integrity_sha256'] if identical else item['integrity_sha256'],
            'detail': str(error)}


def _diagnostic(checkpoint, root, runtime):
    inspected = cc.inspect(root=root, qualification=True, sentinel=True, runtime=runtime)
    capture = event_directory(checkpoint, root) / ('diagnostic-' + secrets.token_hex(12) + '.capture.json')
    save_capture(capture, resolve('codex', 'execucao', role='same-card-search'))
    result = cc.prepare(root=root, capture=capture, task_name='same_card_search_' + checkpoint['checkpoint_id'],
                        sentinel_record=inspected['sentinel_record'], qualification=True, runtime=runtime)
    # Capture an actual pre-birth refusal, without changing a card or product.
    try:
        ce.collect(result['birth'], runtime=runtime, wait_seconds=0)
        fail('diagnostic_birth_already_completed')
    except ce.EvidenceError as exc:
        if exc.code not in {'birth_mismatch', 'spawn_return_unavailable'}:
            raise
    birth = ce.check_seal(json.loads(Path(result['birth']).read_text()))
    refusals = sorted(str(p) for p in Path(result['birth']).parent.glob(birth['attempt_id'] + '.failure-*.json'))
    append(checkpoint, root, 'diagnostic_prepared', birth=result['birth'], plan=result['context_plan'], refusals=refusals)
    return {'result': 'native_action_required', 'action': 'spawn_diagnostic_in_same_principal',
            'arguments': dict(birth['capture']['arguments'], fork_turns='none', task_name=birth['task_name'], message=result['message']),
            'capture': str(capture), 'birth': result['birth'], 'qualification': 'diagnostic_only',
            'then': 'wait for completed payload and call advance again; never count this as stage work'}


def diagnostic_sources(attempt, runtime):
    """Fingerprint only decisive native sources; unrelated parent tools do not
    buy additional automatic retries. A delayed child/source flush does.
    """
    birth = ce.check_seal(json.loads(Path(attempt['birth']).read_text()))
    source, rows, meta, turns = runtime.session(birth['parent_thread'])
    calls, used = set(), []
    for ordinal, row, raw_sha in rows:
        if ordinal < birth['before_record']:
            continue
        payload = row['payload']
        if row['type'] == 'response_item' and payload.get('type') == 'function_call' and payload.get('name') == 'spawn_agent':
            try:
                arguments = json.loads(payload['arguments'])
            except (ValueError, KeyError):
                continue
            if arguments.get('task_name') == birth['task_name']:
                calls.add(payload.get('call_id'))
                used.append((ordinal, raw_sha))
        elif payload.get('call_id') in calls or (payload.get('author', '').endswith('/' + birth['task_name'])):
            used.append((ordinal, raw_sha))
    children = []
    try:
        for identity, path in runtime.locate(agent_path='/root/' + birth['task_name']):
            children.append({'identity': identity, 'rows': [(i, sha) for i, row, sha in runtime.read(path)]})
    except ce.EvidenceError as exc:
        children.append({'code': exc.code})
    return {'birth_sha256': birth['integrity_sha256'], 'native_parent_records': used, 'children': children}


def stage_actions(checkpoint, root, pf, *, runtime):
    operation = checkpoint['operation']
    if operation == 'create':
        return {'result': 'ready', 'action': 'parent_canonical_criar_card', 'event': 'criar_card',
                'entry_status': 'Em Refinamento', 'then': 'bind returned issue and start refinement checkpoint; T1 remains Alan only'}
    if operation == 'review':
        return {'result': 'ready', 'action': 'prepare_and_launch_dedicated_review',
                'workflow': ['bootstrap', 'context', 'probe', 'review'],
                'helper': str(Path(__file__).with_name('codex_review_session.py')),
                'requirements': ['automatically launch exec read-only; persist in principal',
                    'two named native reviewers in same coordinator turn',
                    'exact diff/SHA; full chunks; deny/readback; both completed payloads',
                    'collect/proxies/verify-wave and precommit checklist before commit'], 'preflight': pf}
    if operation == 'homologation':
        return {'result': 'awaiting_human', 'action': 'wait_for_Alan_T15_or_T18',
                'T18': 'reason visible; reopen same card branch from current develop; no iniciar_apply/T8'}
    if operation == 'release':
        from release_model_selection import check_runtime_model
        rt, session, source, rows, meta, turn = active(runtime)
        if (turn.get('model'), turn.get('effort')) != (checkpoint['principal_model'], checkpoint['principal_effort']):
            fail('release_parent_selection_changed', 'do not retune the living parent; start a new execution session and operation checkpoint')
        capture_path = event_directory(checkpoint, root) / 'release.capture.json'
        if not capture_path.exists():
            save_capture(capture_path, resolve('codex', 'execucao', role='fecho-lote'))
        from model_selection import load_capture
        selection = load_capture(capture_path)
        checked = check_runtime_model(root=root, client='codex', runtime_slug=turn.get('model', ce.UNAVAILABLE),
                    runtime_effort=turn.get('effort', ce.UNAVAILABLE), capture=selection)
        if not checked.ok:
            fail('release_parent_selection_mismatch', checked.message)
        return {'result': 'ready', 'action': 'canonical_release_closeout',
                'requirements': ['execution capture and observed principal model/effort', 'native isolated fecho-lote/Kaizen',
                    'overlay and environments; guards pre/post', 'archive/sync by shared decide()',
                    'PR/merge; deploy hooks; public health; hygiene; main to develop sync; T16'],
                'capture': str(capture_path), 'preflight': pf,
                'authorization': 'explicit operation only; no trust inferred'}
    return {'result': 'ready', 'action': 'continue_canonical_stage', 'operation': operation,
            'role': OPERATIONS[operation][0], 'preflight': pf,
            'prepare_card': checkpoint['card'] if operation == 'refine' else None,
            'requirements': ['fresh per-birth selection; isolated native child; completed payload',
                             'parent events/Git only; child never substitutes for human gate']}


def advance(path, *, runtime=None):
    checkpoint = read_checkpoint(path)
    rt, session, source, rows, meta, turn = active(runtime)
    if session != checkpoint['session'] or meta['originator'] != checkpoint['surface'] or str(source) != checkpoint['source']:
        fail('checkpoint_session_mismatch', 'a new chat cannot continue the old checkpoint')
    root = Path(checkpoint['target_root'])
    if Path(turn['cwd']).resolve() != root:
        return dict(result='awaiting_human', code='worktree_mismatch', **resume_action(checkpoint))
    if checkpoint.get('authority') is not None:
        import process_authority as pa
        try:
            pa.verify(checkpoint['authority'], checkpoint['card'])
        except pa.AuthorityError as exc:
            fail('terminal_authority_invalid', str(exc))
        live = state(root, checkpoint['card'], checkpoint['operation'], checkpoint['authority'])
    else:
        live = state(root, checkpoint['card'], checkpoint['operation'])
    if checkpoint['question'] and not human_answer(checkpoint, rows):
        return dict(result='awaiting_human', code='human_answer_missing', **resume_action(checkpoint))
    role = OPERATIONS[checkpoint['operation']][0]
    if role is None:
        return stage_actions(checkpoint, root, None, runtime=rt)
    if checkpoint['operation'] == 'review':
        from codex_terminal_review import advance_review
        return advance_review(checkpoint, root, live, runtime=rt)
    history = events(checkpoint, root)
    pending = [e for e in history if e['kind'] == 'diagnostic_prepared']
    completed = {e['birth'] for e in history if e['kind'] == 'diagnostic_qualified'}
    if pending and pending[-1]['birth'] not in completed:
        attempt = pending[-1]
        sources = diagnostic_sources(attempt, rt)
        same_source_failures = [e for e in history if e['kind'] == 'failure'
                                and e['sources_sha256'] == ce.digest(sources)]
        if len(same_source_failures) >= 2:
            return {'result': 'blocked', 'code': same_source_failures[-1]['code'],
                    'cause': same_source_failures[-1]['cause'], 'same_cause_retry_remaining': 0,
                    'original_failure': same_source_failures[0]['integrity_sha256'],
                    'detail': 'automatic retry budget exhausted for unchanged decisive native sources'}
        try:
            proof = ce.collect(attempt['birth'], wait_seconds=1, runtime=rt)
            context = cc.qualify(attempt['plan'], runtime=rt)
            # A contextual diagnostic does not replace an already verified
            # surface capability identity. Keep its original provenance.
            try:
                capability, entry = Index().discover(meta['originator'],
                    explicit=os.environ.get('COVENANT_CODEX_QUALIFICATION'),
                    legacy=[ce.qualification_path(Path(proof['evidence_path']).parent, meta['originator'])], runtime=rt)
                reference = Path(entry['receipt'])
            except ce.EvidenceError as exc:
                if exc.code != 'qualification_reference_missing':
                    raise
                ce.qualify(proof['evidence_path'], attempt['refusals'], runtime=rt)
                reference = ce.qualification_path(Path(proof['evidence_path']).parent, meta['originator'])
            Index().register(reference, meta['originator'], runtime=rt)
            append(checkpoint, root, 'diagnostic_qualified', birth=attempt['birth'], reference=str(reference),
                   context=context['qualification_path'])
        except (ce.EvidenceError, OSError, ValueError) as exc:
            return failure(checkpoint, root, exc, sources=sources)
    try:
        pf = ce.preflight(root=root, stage=role, runtime=rt)
        append(checkpoint, root, 'preflight_ready', live=live, operation=checkpoint['operation'])
        prerequisite = PREPARATION_EVENTS.get(checkpoint['operation'])
        if prerequisite is not None and live['q'] == prerequisite[0]:
            return {'result': 'awaiting_event', 'action': 'parent_existing_FSM_event', 'event': prerequisite[1],
                    'state': live['q'], 'preflight': pf,
                    'note': 'preparation only; no stage child or product work before the existing event succeeds'}
        return stage_actions(checkpoint, root, pf, runtime=rt)
    except ce.EvidenceError as exc:
        sentinel_refs = []
        for ordinal, row, raw_sha in rows:
            try:
                cc.read_sentinel(rows, ordinal)
                sentinel_refs.append((ordinal, raw_sha))
            except ce.EvidenceError:
                pass
        result = failure(checkpoint, root, exc, sources={'parent_only_sentinel_refs': sentinel_refs})
        if result['result'] == 'blocked' or not checkpoint['diagnostics_authorized']:
            return result
        if result['cause'] in {'qualification_reference_missing', 'stage_capability_missing'}:
            try:
                return dict(_diagnostic(checkpoint, root, rt), original_failure=result['original_failure'])
            except ce.EvidenceError as diagnostic_error:
                if diagnostic_error.code == 'context_sentinel_source_unavailable':
                    return dict(result, action='emit_parent_only_context_sentinel_then_advance',
                                detail='principal emits one fresh nonsecret context_sentinel directly in chat; do not put its value in tools/files/env/child prompts')
                return failure(checkpoint, root, diagnostic_error)
        return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    new = sub.add_parser('start')
    new.add_argument('--root', type=Path, default=Path.cwd())
    new.add_argument('--target-root', type=Path)
    new.add_argument('--authority-root', type=Path, help='explicit consumer authority for Review; never rebinds native cwd')
    new.add_argument('--card', help='bound existing issue; omitted only for create')
    new.add_argument('--operation', required=True, choices=sorted(OPERATIONS))
    new.add_argument('--diagnostics-authorized', action='store_true')
    new.add_argument('--release-requested', action='store_true')
    new.add_argument('--question')
    new.add_argument('--diff', type=Path, help='already materialized exact Review diff; pinned by digest')
    step = sub.add_parser('advance')
    step.add_argument('--checkpoint', required=True, type=Path)
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    try:
        result = start(**args) if command == 'start' else advance(args['checkpoint'])
        print(json.dumps(result, sort_keys=True))
        return 1 if result['result'] in {'blocked', 'recovery_required'} else 0
    except (ce.EvidenceError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({'result': 'blocked', 'code': getattr(exc, 'code', 'invalid_input'), 'detail': str(exc)}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
