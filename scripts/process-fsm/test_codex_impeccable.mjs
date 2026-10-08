import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import test, { afterEach } from 'node:test';
import { runHook, runStopHook } from '../../.agents/skills/impeccable/scripts/hook-lib.mjs';

const tempRoots = [];

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'codex-impeccable-'));
  tempRoots.push(root);
  fs.mkdirSync(path.join(root, '.impeccable'), { recursive: true });
  const uiFile = path.join(root, 'frontend', 'src', 'page.tsx');
  fs.mkdirSync(path.dirname(uiFile), { recursive: true });
  fs.writeFileSync(uiFile, 'export const Page = () => <main>Page</main>;\n');
  return { root, uiFile };
}

afterEach(() => {
  for (const root of tempRoots.splice(0)) fs.rmSync(root, { recursive: true, force: true });
});

function fakeDetector(antipattern) {
  return {
    async detectText(_content, file) {
      return [{
        antipattern,
        name: antipattern,
        description: 'fixture finding',
        severity: 'warning',
        category: 'fixture',
        file,
        line: 1,
        snippet: 'fixture',
      }];
    },
  };
}

function hookEvent(file, session = 'session-1') {
  return {
    hook_event_name: 'PostToolUse',
    tool_name: 'apply_patch',
    tool_input: { command: 'fixture patch' },
    cwd: path.dirname(path.dirname(path.dirname(file))),
    file_path: file,
    session_id: session,
  };
}

test('Codex UI edits trigger the shared detector with the same immediate finding class', async () => {
  const { root, uiFile } = fixture();
  const detector = fakeDetector('gradient-text');
  const event = hookEvent(uiFile);
  const results = await Promise.all(
    ['codex', 'cursor', 'grok', 'opencode', 'dsh'].map((harness) => runHook({
      stdinJson: JSON.stringify(event),
      env: { IMPECCABLE_HOOK_HARNESS: harness },
      cwd: root,
      detector,
    })),
  );

  const signatures = results.map((result) => ({
    kind: result.emission?.kind || null,
    findings: (result.emission?.findings || []).map((item) => [item.antipattern, item.severity]),
  }));
  assert.deepEqual(signatures[0], { kind: 'fresh', findings: [['gradient-text', 'warning']] });
  for (const signature of signatures.slice(1)) assert.deepEqual(signature, signatures[0]);
});

test('Codex non-UI edits stay outside the shared detector', async () => {
  const { root } = fixture();
  const event = {
    hook_event_name: 'PostToolUse',
    tool_name: 'apply_patch',
    tool_input: { command: 'fixture patch' },
    cwd: root,
    file_path: 'README.md',
    session_id: 'session-2',
  };
  const result = await runHook({
    stdinJson: JSON.stringify(event),
    env: { IMPECCABLE_HOOK_HARNESS: 'codex' },
    cwd: root,
    detector: fakeDetector('gradient-text'),
  });

  assert.equal(result.emission, undefined);
  assert.ok(result.audit.skipped);
});

test('Codex Stop uses the shared session-scoped deep pass', async () => {
  const { root, uiFile } = fixture();
  const event = hookEvent(uiFile, 'session-deep');
  const detector = fakeDetector('flat-type-hierarchy');
  const edited = await runHook({
    stdinJson: JSON.stringify(event),
    env: { IMPECCABLE_HOOK_HARNESS: 'codex' },
    cwd: root,
    detector,
  });
  const stopped = await runStopHook({
    stdinJson: JSON.stringify({
      hook_event_name: 'Stop',
      cwd: root,
      session_id: 'session-deep',
    }),
    env: { IMPECCABLE_HOOK_HARNESS: 'codex' },
    cwd: root,
    detector,
  });

  assert.equal(edited.emission?.kind, 'clean');
  assert.equal(edited.audit.deferred, 1);
  assert.equal(stopped.emission?.kind, 'stop-deep-pass');
  assert.equal(stopped.emission?.groups[0]?.findings[0]?.antipattern, 'flat-type-hierarchy');
  assert.match(stopped.stdout, /hookSpecificOutput/);
});
