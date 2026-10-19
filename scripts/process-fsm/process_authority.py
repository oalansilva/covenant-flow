"""Explicit data-only consumer authority; never changes the native/product root.

Only local adapter code parses the overlay and invokes fixed read-only Git
queries. No helper, plugin, hook or Python from the authority is imported.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess

import yaml

from overlay import OVERLAY_REL, validate_overlay
from resolve import _git_env

SCHEMA = 'process-authority-v1'


class AuthorityError(ValueError):
    code = 'authority_invalid'


def checked(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise AuthorityError('authority_symlink: ' + str(path))
    return path.resolve(strict=True)


def _git(root, *args):
    try:
        env = _git_env()
        for key in tuple(env):
            if key.startswith('GIT_CONFIG_') or key == 'GIT_NAMESPACE':
                env.pop(key, None)
        result = subprocess.run(['git', '-C', str(root), *args], env=env,
            capture_output=True, text=True, check=False, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AuthorityError('authority_git_unavailable') from exc
    if result.returncode:
        raise AuthorityError('authority_git_unavailable: ' + ' '.join(args))
    return result.stdout.strip()


def _repository(remote):
    match = re.fullmatch(r'(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?', remote)
    if not match:
        raise AuthorityError('authority_repository_unqualified')
    return match[1]


def capture(root, card):
    """Pin exact authority path, overlay bytes and repository/board/card identity."""
    try:
        root = checked(root)
        if not root.is_dir() or checked(_git(root, 'rev-parse', '--show-toplevel')) != root:
            raise AuthorityError('authority_worktree_mismatch')
        branch = _git(root, 'rev-parse', '--abbrev-ref', 'HEAD')
        match = re.fullmatch(r'card-(\d+)-.+', branch)
        if not match or match[1] != str(card) or branch != root.name:
            raise AuthorityError('authority_card_mismatch')
        path = checked(root / OVERLAY_REL)
        if not path.is_relative_to(root):
            raise AuthorityError('authority_overlay_escape')
        raw = path.read_bytes()
        data = yaml.safe_load(raw)
        validate_overlay(data, require_filled=True, raw_text=raw.decode())
        repository = _repository(_git(root, 'config', '--local', '--no-includes', '--get', 'remote.origin.url'))
        if repository != data['repo']:
            raise AuthorityError('authority_repository_mismatch')
        git_dir = checked(_git(root, 'rev-parse', '--absolute-git-dir'))
        common = Path(_git(root, 'rev-parse', '--git-common-dir'))
        common_dir = checked(common if common.is_absolute() else root / common)
        board = data['board']
        return {'schema': SCHEMA, 'root': str(root), 'overlay': str(path),
            'overlay_sha256': hashlib.sha256(raw).hexdigest(), 'repo': repository,
            'board_owner': board['owner'], 'board_number': board['number'],
            'board_project_id': board['project_id'], 'status_field_id': board['status_field_id'],
            'bound_card': str(card), 'q_git': branch,
            'git_dir': str(git_dir), 'git_common_dir': str(common_dir)}
    except AuthorityError:
        raise
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError) as exc:
        raise AuthorityError('authority_source_unavailable: ' + str(exc)) from exc


def verify(binding, card):
    if not isinstance(binding, dict) or binding.get('schema') != SCHEMA or binding.get('bound_card') != str(card):
        raise AuthorityError('authority_binding_mismatch')
    current = capture(binding['root'], card)
    if current != binding:
        raise AuthorityError('authority_source_changed')
    return current


def overlay(binding, card):
    """Return only data after rereading the pinned source, with no ancestor search."""
    verify(binding, card)
    raw = checked(binding['overlay']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != binding['overlay_sha256']:
        raise AuthorityError('authority_source_changed')
    return yaml.safe_load(raw)


def digest(binding):
    return hashlib.sha256(json.dumps(binding, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
