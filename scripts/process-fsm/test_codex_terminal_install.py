"""Disposable installer targets and controlled source proofs; no actual pin/trust."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from test_codex_installer import _target, _pin, ROOT
from test_codex_evidence import essay
from test_codex_qualification_index import qualify
from model_selection_fixtures import machine_models


def test_clean_pin_delivers_terminal_modules_docs_and_manifest_without_trust(tmp_path, essay):
    target, selection = _target(tmp_path / 'clean-consumer')
    result = _pin(target)
    assert result.returncode == 0, result.stderr
    files = json.loads((target / '.covenant-flow/adapters.json').read_text())['clients']['codex']['files']
    for name in ('codex_qualification_index', 'codex_qualification', 'codex_terminal', 'codex_terminal_review'):
        path = 'scripts/process-fsm/' + name + '.py'
        assert (target / path).read_bytes() == (ROOT / path).read_bytes()
        assert files[path] == hashlib.sha256((target / path).read_bytes()).hexdigest()
    assert (target / 'docs/codex-terminal-flow.md').read_bytes() == (ROOT / 'docs/codex-terminal-flow.md').read_bytes()
    assert (target / 'docs/claude-runtime-evidence.md').read_bytes() == (ROOT / 'docs/claude-runtime-evidence.md').read_bytes()
    for name in ('cf_shim', 'claude_evidence', 'codex_review_probe', 'codex_binding'):
        relative = 'scripts/process-fsm/' + name + '.py'
        assert (target / relative).read_bytes() == (ROOT / relative).read_bytes()
    assert (target / 'scripts/process-fsm/test_claude_desktop_surface.py').is_file()
    assert (target / 'scripts/process-fsm/test_residual_1101.py').is_file()
    assert (target / 'scripts/process-fsm/test_pin_correction.py').is_file()
    operator_home = tmp_path / 'operator-home'
    assert not list(operator_home.glob('**/*trust*.json'))
    # The installed verifier really reopens the original controlled rollout.
    # This remains a fixture, not qualification of the invoking native host.
    receipt = qualify(essay)
    command = [sys.executable, str(target / 'scripts/process-fsm/codex_qualification.py'), 'register',
               '--surface', essay.host, '--reference', str(receipt)]
    registered = subprocess.run(command, capture_output=True, text=True, check=False)
    assert registered.returncode == 0, registered.stdout + registered.stderr
    discovered = subprocess.run([sys.executable, str(target / 'scripts/process-fsm/codex_qualification.py'),
        'discover', '--surface', essay.host], capture_output=True, text=True, check=False)
    assert discovered.returncode == 0, discovered.stdout + discovered.stderr
    assert json.loads(discovered.stdout)['reference']['discovery'] == 'index'
    pf = subprocess.run([sys.executable, str(target / 'scripts/process-fsm/codex_evidence.py'),
        'preflight', '--root', str(essay.root), '--dest', '.cursor/tmp/fresh-installed', '--stage', 'apply-coluna'],
        capture_output=True, text=True, check=False)
    assert pf.returncode != 0
    assert json.loads(pf.stdout)['code'] == 'stage_capability_missing'
    assert not list((essay.root / '.cursor/tmp/fresh-installed').glob('*qualification*.json'))
