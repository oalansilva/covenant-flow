"""Principal-side automatic Review preparation, driven by native tool receipts.

Returned commands are executed by the principal agent's native command tool,
so their launch/return chain remains observable. No operator permission switch,
subprocess masquerading as a tool receipt, or coordinator write is introduced.
"""
from pathlib import Path
import json
import shlex
import sys

import codex_evidence as ce
import codex_review_session as cs
import codex_context as cc


def command_action(command, *, phase, expected_exit=0):
    return {'result': 'native_action_required', 'action': 'execute_exact_native_command',
            'command': command, 'expected_exit': expected_exit, 'phase': phase,
            'then': 'poll the same process to completion, preserve full result/exit_code, then advance checkpoint; no human confirmation'}


def advance_review(checkpoint, root, live, *, runtime):
    from codex_terminal import append, events, failure, fail
    authority_root = (checkpoint.get("authority") or {}).get("root")
    event_command = {}
    if authority_root is not None:
        event_command['event_command'] = shlex.join([sys.executable,
            str(Path(root) / 'scripts/process-fsm/process_event.py'), 'pedir_review',
            '--card', checkpoint['card'], '--client', 'codex', '--authority-root', authority_root])
    def issue(command, *, phase, expected_exit=0):
        digest = ce.digest(command.encode())
        issued = [e for e in events(checkpoint, root) if e['kind'] == 'native_command_requested'
                  and e['command_sha256'] == digest]
        if issued:
            return failure(checkpoint, root, ce.EvidenceError('review_native_command_pending',
                'command already issued; await the same native process/flush, never rerun it'),
                sources={'command_sha256': digest})
        append(checkpoint, root, 'native_command_requested', command_sha256=digest, phase=phase)
        return command_action(command, phase=phase, expected_exit=expected_exit)
    if not checkpoint.get('diff'):
        fail('review_diff_missing', 'principal must materialize exact precommit or closing diff before starting')
    diff = cs.inside(root, checkpoint['diff'])
    if ce.digest(diff.read_bytes()) != checkpoint['diff_sha256']:
        fail('review_diff_changed', 'preserve original attempt; start a new checkpoint for a new diff/SHA')
    history = events(checkpoint, root)
    prepared = [e for e in history if e['kind'] == 'review_package']
    if not prepared:
        if not checkpoint['diagnostics_authorized']:
            fail('review_diagnostic_authorization_missing', 'route bootstrap/context/probes are diagnostic work, never stage acceptance')
        package = cs.prepare(root=root, phase='bootstrap', authority_root=authority_root, runtime=runtime)
        append(checkpoint, root, 'review_package', package=package['package'], phase='bootstrap')
        return issue(package['command'], phase='bootstrap')
    path = Path(prepared[-1]['package'])
    package = cs.read_package(path)
    phase = package['phase']
    bootstrap = path if phase == 'bootstrap' else Path(package['bootstrap'])
    if not Path(package['events']).exists():
        if phase == 'review':
            if live['q'] != 'Code Review':
                return {'result': 'awaiting_event', 'event': 'pedir_review', 'actor': 'parent', **event_command,
                        'note': 'use existing FSM event; checkpoint does not move Status'}
            try:
                cs._stage_observation(path, runtime=runtime, at_ms=cs._clock_ms())
            except ce.EvidenceError as exc:
                if exc.code == 'review_launch_source_unavailable':
                    return issue(cs.command(path, 'stage-check'), phase='review-stage-check')
                if exc.code == 'review_stage_status_expired':
                    retry = failure(checkpoint, root, exc, sources={
                        'bootstrap': str(bootstrap), 'diff_sha256': checkpoint['diff_sha256'], 'q': live['q']})
                    if retry['result'] == 'blocked':
                        return retry
                    fresh = cs.prepare(root=root, phase='review', bootstrap=bootstrap, diff=diff, authority_root=authority_root, runtime=runtime)
                    append(checkpoint, root, 'review_package', package=fresh['package'], phase='review',
                           supersedes=str(path), original_failure=exc.code)
                    return issue(fresh['stage_check_command'], phase='review-stage-check')
                raise
        return issue(cs.command(path), phase=phase)
    # Once a native process has started, a partial/error output must never
    # trigger relaunch of the same immutable attempt or counterfeit a return.
    try:
        if phase == 'review' and live['q'] != 'Code Review':
            fail('review_stage_binding_mismatch', 'Status changed after launch; current product Review is not accepted')
        cs.binding(path, runtime=runtime, complete=True)
        if phase == 'bootstrap':
            # Route qualification itself requires a completed native launch.
            # Record the expected unqualified-route refusal only after binding
            # that launch; an absent/partial launch is never that refusal.
            try:
                observed, ref = cs.native_command(runtime, package['principal_thread'], cs.command(path, 'route-check'),
                            root, after=package['before_record'], required_exit=1)
            except ce.EvidenceError as exc:
                if exc.code != 'review_launch_source_unavailable':
                    raise
                return issue(cs.command(path, 'route-check'), phase='bootstrap-refusal', expected_exit=1)
            if observed.get('code') != 'review_route_unqualified' or observed.get('result') != 'blocked':
                fail('review_route_refusal_invalid')
        proofs = [ce.collect(birth, runtime=runtime, wait_seconds=1) for birth in package.get('births', [])]
        if phase == 'context':
            cc.qualify(cc.plan_path(package['births'][0]), runtime=runtime)
        if phase == 'probe':
            from codex_review_probe import qualify
            qualify([p['evidence_path'] for p in proofs], root=root, runtime=runtime)
            cs.qualify_route(path, runtime=runtime)
    except ce.EvidenceError as exc:
        return failure(checkpoint, root, exc, sources={'package': package['integrity_sha256'],
                    'events': ce.digest(Path(package['events']).read_bytes())})
    if phase == 'review':
        from codex_proxy import record
        from codex_review import verify_wave
        for proof in proofs:
            cap = proof['birth']['capture']
            record(repo_root=root, activity=proof['role'], band=proof['band'],
                   requested_model=proof['requested']['model'], requested_effort=proof['requested']['reasoning_effort'],
                   observed_model=proof['turns'][-1]['observed']['model'],
                   observed_effort=proof['turns'][-1]['observed']['reasoning_effort'],
                   host=proof['host'], host_version=proof['host_version'], status=proof['status'],
                   payload_returned=proof['payload_returned'], child_id=proof['child_thread'],
                   wave_id=proof['wave_id'], sandbox_mode=proof['parent_sandbox'], bound_card=checkpoint['card'],
                   review_diff_sha256=checkpoint['diff_sha256'], capture=cap, runtime_evidence=proof['evidence_path'])
        verified = verify_wave(root=root, wave_id=package['wave_id'],
                              expected_sha256=checkpoint['diff_sha256'], bound_card=checkpoint['card'])
        append(checkpoint, root, 'review_wave_verified', package=str(path), diff_sha256=checkpoint['diff_sha256'],
               wave_id=package['wave_id'], children=[p['child_thread'] for p in proofs])
        return {'result': 'review_wave_verified', 'wave': package['wave_id'], 'verification': verified,
                'action': 'principal_reads_both_findings_then_canonical_ceiling_and_checklist',
                'evidence': [p['evidence_path'] for p in proofs],
                'checklist_command': shlex.join([sys.executable, str(Path(__file__).with_name('review_process_checklist.py')),
                                                '--phase', 'precommit', '--wave-same-turn', 'yes']),
                'requirements': ['P0 stops; one correction and one wave; residual after ceiling',
                                 'verify-wave and checklist must pass before commit; closing is a distinct checkpoint']}
    next_phase = {'bootstrap': 'context', 'context': 'probe', 'probe': 'review'}[phase]
    next_diff = diff
    if next_phase == 'probe':
        next_diff = ce.destination(root) / ('terminal-diagnostic-' + checkpoint['checkpoint_id'] + '.diff')
        if not next_diff.exists():
            # A fixed non-product input, never a live Review result.
            next_diff.write_text('diff --git a/diagnostic b/diagnostic\n--- a/diagnostic\n+++ b/diagnostic\n@@ -1 +1 @@\n-before\n+after\n')
            next_diff.chmod(0o600)
    next_package = cs.prepare(root=root, phase=next_phase, bootstrap=bootstrap,
                              diff=next_diff if next_phase in {'probe', 'review'} else None, authority_root=authority_root, runtime=runtime)
    append(checkpoint, root, 'review_package', package=next_package['package'], phase=next_phase)
    if next_phase == 'review':
        if live['q'] != 'Code Review':
            return {'result': 'awaiting_event', 'event': 'pedir_review', 'actor': 'parent', **event_command,
                    'package': next_package['package'], 'note': 'route qualified; no product review before T9'}
        return issue(next_package['stage_check_command'], phase='review-stage-check')
    return issue(next_package['command'], phase=next_phase)
