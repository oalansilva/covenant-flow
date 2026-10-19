"""Private capability locators. Never transfer context or manufacture receipts.

The account index pins immutable local artifacts. Append-only native sources are
reopened through the evidence verifier, which checks accepted record digests.
The ordinary worktree-contained evidence destination is deliberately unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import stat
import tempfile

import codex_evidence as ce

SCHEMA = 'codex-qualification-index-v1'
DRIVER_SCHEMA = 'rollout-v1'
SURFACES = frozenset({'codex-tui', 'codex_exec'})


def fail(code, detail=''):
    raise ce.EvidenceError(code, detail, recovery='preserve original sources; restore the intact reference or run the authorized native diagnostic for this surface')


def checked_path(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        fail('qualification_path_unsafe', str(path))
    return path.resolve()


def read_object(path):
    try:
        value = json.loads(checked_path(path).read_text())
        if not isinstance(value, dict):
            fail('qualification_source_invalid', str(path))
        return ce.check_seal(value)
    except ce.EvidenceError:
        raise
    except (OSError, ValueError, TypeError) as exc:
        fail('qualification_source_unavailable', f'{path}: {type(exc).__name__}')


def verify_reference(path, surface, *, runtime=None):
    """Reopen original receipt, envelope and authoritative native sources."""
    if not isinstance(surface, str) or not surface:
        fail('qualification_surface_unverified', str(surface))
    receipt = read_object(path)
    try:
        evidence = checked_path(receipt['evidence'])
        envelope = read_object(evidence)
        for ref in envelope['sources']:
            checked_path(ref['source'])
        # The envelope embeds the original birth. Check the original capture
        # and birth paths too; hashes are not permission to follow symlinks.
        birth = envelope['birth']
        for key in ('capture_path',):
            if birth.get(key):
                checked_path(birth[key])
        proof = ce.verify_evidence(evidence, runtime=runtime)
        rt = runtime or ce.Rollout()
        parent_host = rt.session(proof['parent_thread'])[2]['originator']
        if parent_host != surface:
            fail('qualification_surface_mismatch', f'qualification belongs to another host surface; expected={surface}; observed={parent_host}')
        if (proof['schema'] != ce.SCHEMA or proof['driver'] not in ce.ACCEPTED_DRIVERS
                or not proof['qualification'] or receipt.get('driver') != proof['driver']
                or receipt.get('session') != proof['parent_thread']):
            fail('qualification_source_invalid', 'schema, driver or original session mismatch')
        if proof['driver'] != ce.NATIVE_DRIVER and surface != 'codex_exec':
            fail('qualification_surface_mismatch', 'legacy exec driver cannot qualify TUI')
        refusals = [read_object(p) for p in receipt['refusals']]
        if (not refusals or [r.get('code') for r in refusals] != receipt['refusal_codes']
                or any(r.get('schema') != ce.SCHEMA or r.get('attempt_id') != proof['attempt_id']
                       or r.get('result') != 'blocked' for r in refusals)):
            fail('qualification_source_invalid', 'positive proof and bound refusal required')
        paths = [checked_path(path), evidence, *[checked_path(p) for p in receipt['refusals']]]
        artifacts = {str(p): ce.digest(p.read_bytes()) for p in paths}
        identity = {'surface': surface, 'driver_schema': DRIVER_SCHEMA,
                    'attempt_id': proof['attempt_id'], 'session': proof['parent_thread'],
                    'child': proof['child_thread'], 'evidence_sha256': proof['integrity_sha256']}
        return proof, {'receipt': str(checked_path(path)), 'identity': identity, 'artifacts': artifacts}
    except ce.EvidenceError:
        raise
    except (OSError, KeyError, TypeError, ValueError) as exc:
        fail('qualification_source_invalid', f'{path}: {type(exc).__name__}')


class Index:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else Path.home() / '.config/covenant-flow/codex/qualifications-v1.json'

    def directory(self, *, create=False):
        path = checked_path(self.path)
        if not path.is_absolute():
            fail('qualification_index_unsafe')
        parent = path.parent
        account = Path.home() / '.config/covenant-flow'
        if account != parent and account not in parent.parents:
            fail('qualification_index_unsafe', 'index must remain in this account covenant-flow configuration directory')
        if create:
            parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not parent.exists():
            return False
        info = parent.stat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
            fail('qualification_index_unsafe', 'account index directory must be owned by this uid and mode 0700')
        if path.exists():
            info = path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
                fail('qualification_index_unsafe', 'index must be a private regular file (0600)')
        return True

    def load(self):
        if not self.directory() or not self.path.exists():
            return {'schema': SCHEMA, 'entries': {}}
        try:
            data = json.loads(self.path.read_text())
            if (not isinstance(data, dict) or data.get('schema') != SCHEMA
                    or not isinstance(data.get('entries'), dict)):
                fail('qualification_index_corrupt')
            for key, entries in data['entries'].items():
                if key not in {self.key(s) for s in SURFACES} or not isinstance(entries, list):
                    fail('qualification_index_corrupt')
                for entry in entries:
                    if (not isinstance(entry, dict) or set(entry) != {'receipt', 'identity', 'artifacts'}
                            or not isinstance(entry['receipt'], str) or not isinstance(entry['identity'], dict)
                            or not isinstance(entry['artifacts'], dict)):
                        fail('qualification_index_corrupt')
            return data
        except (OSError, ValueError, TypeError) as exc:
            if isinstance(exc, ce.EvidenceError):
                raise
            fail('qualification_index_corrupt', type(exc).__name__)

    @staticmethod
    def key(surface):
        return surface + '/' + DRIVER_SCHEMA

    @contextmanager
    def lock(self):
        self.directory(create=True)
        path = checked_path(self.path.with_suffix('.lock'))
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600:
                fail('qualification_index_unsafe', 'invalid lock')
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def register(self, receipt, surface, *, runtime=None):
        if surface not in SURFACES:
            fail('qualification_surface_unverified', 'shared terminal index supports only TUI and exec; local legacy verifier remains independent')
        proof, entry = verify_reference(receipt, surface, runtime=runtime)
        with self.lock():
            data = self.load()
            entries = data['entries'].setdefault(self.key(surface), [])
            for old in entries:
                if old['receipt'] == entry['receipt']:
                    if old != entry:
                        fail('qualification_reference_changed', entry['receipt'])
                    return entry
                if old['identity'] != entry['identity']:
                    fail('qualification_conflict', 'another capability identity is already indexed; select an explicit verified reference')
            entries.append(entry)
            raw = json.dumps(data, sort_keys=True, indent=2).encode() + b'\n'
            fd, name = tempfile.mkstemp(dir=self.path.parent, prefix='.qualifications-')
            try:
                with os.fdopen(fd, 'wb') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(name, self.path)
                directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                Path(name).unlink(missing_ok=True)
        return entry

    def discover(self, surface, *, explicit=None, legacy=(), runtime=None):
        """Explicit selection wins; otherwise every exact candidate must agree.

        A corrupt index never silently falls back. Nonexistent legacy paths are
        absent, but a dangling symlink or an indexed missing source is invalid.
        No timestamps or recursive transcript/worktree scans are used.
        """
        if explicit is not None:
            proof, entry = verify_reference(explicit, surface, runtime=runtime)
            return proof, dict(entry, discovery='explicit')
        # Preserve other hosts' existing local verifier without granting them
        # terminal discovery, account registration or product qualification.
        indexed = self.load()['entries'].get(self.key(surface), []) if surface in SURFACES else []
        candidates = {}
        for entry in indexed:
            for path, expected in entry['artifacts'].items():
                try:
                    actual = ce.digest(checked_path(path).read_bytes())
                except OSError as exc:
                    fail('qualification_source_unavailable', str(path))
                if actual != expected:
                    fail('qualification_reference_changed', path)
            proof, actual = verify_reference(entry['receipt'], surface, runtime=runtime)
            if actual != entry:
                fail('qualification_reference_changed', entry['receipt'])
            candidates[entry['receipt']] = (proof, actual, 'index')
        for path in legacy:
            path = checked_path(path)
            if path.exists() and str(path) not in candidates:
                proof, entry = verify_reference(path, surface, runtime=runtime)
                candidates[str(path)] = (proof, entry, 'legacy')
        if not candidates:
            fail('qualification_reference_missing', f'{surface}/{DRIVER_SCHEMA}')
        identities = {ce.digest(value[1]['identity']) for value in candidates.values()}
        if len(identities) != 1:
            fail('qualification_conflict', 'conflicting original identities; supply an explicit reference')
        proof, entry, origin = candidates[sorted(candidates)[0]]
        return proof, dict(entry, discovery=origin)
