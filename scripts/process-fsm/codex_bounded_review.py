"""Versioned, fail-closed composition over the existing native Review controller.

Identity/delivery are mechanical checks. Only the two native reviewers supply
semantic findings. No cache across snapshots; no FSM event or commit here.
"""
from __future__ import annotations
import argparse
import ast
import contextlib
import fcntl
import itertools
import json
import os
import re
from pathlib import Path
import secrets
import shlex
import subprocess
import stat
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import codex_evidence as ce
import codex_review as cr
import codex_review_session as cs
from codex_fs import atomic_write_bytes

VERSION = 'bounded-review-v1'
PREFIX = 'BOUNDED-REVIEW-V1\n'
COSTS = ('instructions', 'tools', 'calls', 'outputs', 'framing', 'analysis', 'verdict')


def fail(code, detail=''):
    raise ce.EvidenceError('bounded_' + code, detail)


def read(path):
    p = Path(path)
    if p.is_symlink() or not p.is_file():
        fail('source_unavailable', str(p))
    return p.read_bytes()


def load(path):
    return ce.check_seal(json.loads(read(path)))


def save(path, value, *, immutable=False):
    p = Path(path)
    body = (json.dumps(ce.sealed(value), sort_keys=True, ensure_ascii=True, indent=2) + '\n').encode()
    if immutable and p.exists():
        if read(p) != body:
            fail('immutable_changed', str(p))
        return
    atomic_write_bytes(p, body)
    p.chmod(0o400 if immutable else 0o600)
    fd = os.open(p.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def git(root, *args, index=None, input=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    if index:
        env['GIT_INDEX_FILE'] = str(index)
    result = subprocess.run(['git', '-C', str(root), *args], env=env, input=input, capture_output=True, timeout=60)
    if result.returncode:
        fail('git_failed', result.stderr.decode(errors='replace'))
    return result.stdout


def working_tree(root, index):
    """Hash every scoped path, never rely on copied index stat-cache entries."""
    names = set(git(root, 'ls-files', '-z', index=index).split(b'\0'))
    names.update(git(root, 'ls-files', '--others', '--exclude-standard', '-z').split(b'\0'))
    records = []
    for raw_name in sorted(names - {b''}):
        name = os.fsdecode(raw_name); path = Path(root) / name
        if any(p.is_symlink() for p in path.parents if p != Path(root) and Path(root) in p.parents):
            fail('path_outside_root', name)
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            records.append(b'0 ' + b'0' * 40 + b'\t' + raw_name + b'\0')
            continue
        if stat.S_ISLNK(mode):
            body, git_mode = os.fsencode(os.readlink(path)), '120000'
        elif stat.S_ISREG(mode):
            body, git_mode = read(path), '100755' if mode & 0o111 else '100644'
        else:
            fail('uninspectable', name)
        oid = git(root, 'hash-object', '-w', '--stdin', input=body).strip()
        records.append(git_mode.encode() + b' ' + oid + b'\t' + raw_name + b'\0')
    git(root, 'update-index', '-z', '--index-info', index=index, input=b''.join(records))
    return git(root, 'write-tree', index=index).decode().strip()


def inside(root, path):
    p = Path(path).absolute()
    if any(a.is_symlink() for a in [p, *p.parents]) or Path(root).resolve() not in p.resolve().parents:
        fail('path_outside_root', str(p))
    return p.resolve()


def tree_files(root, tree):
    entries = {}
    for row in git(root, 'ls-tree', '-rz', tree).split(b'\0'):
        if row:
            meta, name = row.split(b'\t', 1)
            mode, kind, oid = meta.decode().split()
            if kind != 'blob':
                fail('unknown_dependency', 'submodule: ' + os.fsdecode(name))
            entries[os.fsdecode(name)] = {'mode': mode, 'oid': oid}
    return entries


def changes(root, before, after, phase):
    raw = git(root, 'diff', '--raw', '-z', '--no-abbrev', '-M', before, after).split(b'\0')
    result = []
    pos = 0
    while pos < len(raw) and raw[pos]:
        meta = raw[pos].decode().split(); pos += 1
        old = os.fsdecode(raw[pos]); pos += 1
        status = meta[4]
        new = os.fsdecode(raw[pos]) if status[0] in 'RC' else old
        if status[0] in 'RC':
            pos += 1
        patch = git(root, 'diff', '--binary', '--full-index', '-M', before, after, '--', old, new)
        row = dict(phase=phase, before=before, after=after, old=old, new=new,
                   old_mode=meta[0][1:], new_mode=meta[1], old_oid=meta[2], new_oid=meta[3],
                   status=status, patch_sha256=ce.digest(patch))
        row['id'] = ce.digest(row)
        result.append(row)
    return result


def capture(root, out, *, mode='precommit', base='HEAD', target='HEAD'):
    root = Path(root).resolve(); out = inside(root, out)
    if Path(git(root, 'rev-parse', '--show-toplevel').decode().strip()).resolve() != root:
        fail('snapshot_root_mismatch')
    # Output must already be ignored: no output-dependent exclusion from inventory.
    if subprocess.run(['git', '-C', str(root), 'check-ignore', '-q', str(out)], capture_output=True).returncode:
        fail('output_not_ignored', str(out))
    out.mkdir(parents=True, exist_ok=False)
    base_oid = git(root, 'rev-parse', '--verify', base + '^{commit}').decode().strip()
    base_tree = git(root, 'rev-parse', base_oid + '^{tree}').decode().strip()
    index = out / 'index'
    if mode == 'precommit':
        real_index = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-path', 'index').decode().strip())
        atomic_write_bytes(index, read(real_index))
        index_tree = git(root, 'write-tree', index=index).decode().strip()
        target_tree = working_tree(root, index)
        target_oid = None
        inventory = changes(root, base_tree, index_tree, 'index') + changes(root, index_tree, target_tree, 'working-tree')
    elif mode == 'closing':
        target_oid = git(root, 'rev-parse', '--verify', target + '^{commit}').decode().strip()
        target_tree = git(root, 'rev-parse', target_oid + '^{tree}').decode().strip()
        index_tree = None
        inventory = changes(root, base_tree, target_tree, 'committed')
    else:
        fail('snapshot_mode')
    if not inventory:
        fail('empty_snapshot')
    exact = b''.join(git(root, 'diff', '--binary', '--full-index', '-M', a, b)
                     for a, b in ([(base_tree, index_tree), (index_tree, target_tree)] if index_tree else [(base_tree, target_tree)]))
    atomic_write_bytes(out / 'global.patch', exact)
    # Keep the otherwise unreachable index/working trees alive, without a nested repo.
    token = secrets.token_hex(16)
    retained = []
    for i, tree in enumerate(filter(None, [base_tree, index_tree, target_tree])):
        ref = 'refs/covenant-review/' + token + '/' + str(i)
        git(root, 'update-ref', ref, tree)
        retained.append(ref)
    snapshot = dict(version=VERSION, root=str(root), mode=mode, base=base_oid, target=target_oid,
                    base_tree=base_tree, index_tree=index_tree, target_tree=target_tree,
                    inventory=inventory, diff_sha256=ce.digest(exact), retained_refs=retained,
                    head=git(root, 'rev-parse', 'HEAD').decode().strip())
    save(out / 'snapshot.json', snapshot, immutable=True)
    return out / 'snapshot.json'


def check_snapshot(path, *, live=True):
    s = load(path); root = Path(s['root'])
    if s['version'] != VERSION:
        fail('version_changed')
    for ref, tree in zip(s['retained_refs'], filter(None, [s['base_tree'], s['index_tree'], s['target_tree']])):
        if git(root, 'rev-parse', '--verify', ref).decode().strip() != tree:
            fail('snapshot_reference_changed')
    inventory = changes(root, s['base_tree'], s['index_tree'], 'index') + changes(root, s['index_tree'], s['target_tree'], 'working-tree') if s['index_tree'] else changes(root, s['base_tree'], s['target_tree'], 'committed')
    if inventory != s['inventory'] or ce.digest(read(Path(path).parent / 'global.patch')) != s['diff_sha256']:
        fail('snapshot_coverage_changed')
    expected = b''.join(git(root, 'diff', '--binary', '--full-index', '-M', a, b) for a, b in
                        ([(s['base_tree'], s['index_tree']), (s['index_tree'], s['target_tree'])] if s['index_tree'] else [(s['base_tree'], s['target_tree'])]))
    if ce.digest(expected) != s['diff_sha256']:
        fail('snapshot_sha_changed')
    if live and s['mode'] == 'precommit':
        index = Path(path).parent / ('check-index-' + secrets.token_hex(8))
        try:
            original = Path(git(root, 'rev-parse', '--path-format=absolute', '--git-path', 'index').decode().strip())
            atomic_write_bytes(index, read(original))
            if git(root, 'write-tree', index=index).decode().strip() != s['index_tree']:
                fail('snapshot_stale', 'index changed')
            if working_tree(root, index) != s['target_tree'] or git(root, 'rev-parse', 'HEAD').decode().strip() != s['head']:
                fail('snapshot_stale', 'working tree/untracked/HEAD changed')
        finally:
            index.unlink(missing_ok=True)
    return s


def source(root, entries, name, cache=None):
    entry = entries.get(name)
    if not entry:
        return None
    cache = cache if cache is not None else {}
    if entry['oid'] not in cache:
        cache[entry['oid']] = git(root, 'cat-file', 'blob', entry['oid'])
    raw = cache[entry['oid']]
    try:
        text = raw.decode('utf-8')
    except UnicodeError:
        fail('uninspectable', name)
    if '\0' in text:
        fail('uninspectable', name)
    return dict(path=name, **entry, sha256=ce.digest(raw), text=text)


def patch_bytes(root, row):
    raw = git(root, 'diff', '--binary', '--full-index', '-M', row['before'], row['after'], '--', row['old'], row['new'])
    if row.get('fragment'):
        raw = raw[row['fragment']['start']:row['fragment']['end']]
        if ce.digest(raw) != row['fragment']['sha256']:
            fail('fragment_changed')
    return raw


def atom_patches(root, atoms):
    whole = {}; result = {}
    for row in atoms:
        parent = row.get('parent_change', row['id'])
        if parent not in whole:
            whole[parent] = patch_bytes(root, dict(row, fragment=None))
        raw = whole[parent]
        if row.get('fragment'):
            raw = raw[row['fragment']['start']:row['fragment']['end']]
            if ce.digest(raw) != row['fragment']['sha256']:
                fail('fragment_changed')
        result[row['id']] = raw
    return result


def review_atoms(snapshot):
    """Coherent inner-file boundaries for added patches, with exact byte spans.

    Outer headers/preamble belong to the first atom, not an unreviewed sidecar.
    Whole functions/files remain atomic elsewhere; no arbitrary token clipping.
    """
    atoms = []
    for row in snapshot['inventory']:
        raw = patch_bytes(snapshot['root'], row)
        data = git(snapshot['root'], 'cat-file', 'blob', row['new_oid']) if row['status'] == 'A' and row['new'].endswith('.patch') else b''
        def partition(start, end, depth):
            marks = list(re.finditer(rb'^' + re.escape(b'+' * depth) + rb'diff --git .+$', data[start:end], re.M))
            if not marks:
                return []
            leaves = []
            for n, mark in enumerate(marks):
                a = start if n == 0 else start + mark.start()
                b = start + marks[n + 1].start() if n + 1 < len(marks) else end
                header = mark.group().decode()[depth:]
                parts = shlex.split(header)
                nested = (len(parts) == 4 and parts[3].endswith('.patch') and
                          re.search(rb'^' + re.escape(b'+' * depth) + rb'new file mode ', data[start + mark.start():b], re.M))
                children = partition(a, b, depth + 1) if nested else []
                leaves.extend(children or [(a, b, header, depth)])
            return leaves
        leaves = partition(0, len(data), 0) if data else []
        if len(leaves) <= 1:
            atoms.append(row)
            continue
        offsets = {}; position = body_position = 0; in_hunk = False
        reconstructed = bytearray()
        for line in raw.splitlines(keepends=True):
            if line.startswith(b'@@ '):
                in_hunk = True
            elif in_hunk and line.startswith(b'+'):
                offsets[body_position] = position
                part = line[1:]
                reconstructed.extend(part); body_position += len(part)
            elif in_hunk and line.startswith(b'\\ No newline'):
                if reconstructed.endswith(b'\n'):
                    del reconstructed[-1:]; body_position -= 1
            position += len(line)
        if bytes(reconstructed) != data:
            fail('fragment_changed', 'addition cannot be reconstructed byte for byte')
        for n, (body_start, body_end, header, depth) in enumerate(leaves):
            start = 0 if n == 0 else offsets[body_start]
            end = offsets[leaves[n + 1][0]] if n + 1 < len(leaves) else len(raw)
            atom = dict(row, parent_change=row['id'], fragment=dict(start=start, end=end, sha256=ce.digest(raw[start:end])),
                        source_span=dict(start=body_start, end=body_end, sha256=ce.digest(data[body_start:body_end])),
                        logical_header=header, nesting_depth=depth)
            atom['id'] = ce.digest(atom)
            atoms.append(atom)
    return atoms


def context(root, trees, names, resolutions=(), slices=None, source_cache=None):
    """Conservative directory closure + import closure, both revisions.

    Relevant tests/configs, imports and explicit paths resolve against both
    trees. Dynamic Python imports are unknown and block without a bound map.
    """
    result = []; pending = set(names); seen = set()
    while pending:
        name = min(pending); pending.remove(name)
        if name in seen:
            continue
        seen.add(name)
        for tree, entries in trees.items():
            row = source(root, entries, name, source_cache)
            if row is None:
                continue
            scope = (slices or {}).get((tree, name))
            if scope:
                raw = row['text'].encode()
                segments = []
                for span in sorted(scope, key=lambda v: v['start']):
                    text = raw[span['start']:span['end']]
                    if ce.digest(text) != span['sha256']:
                        fail('fragment_changed')
                    segments.append(dict(span, text=text.decode()))
                row = dict(row, text='', segments=segments)
            dependency_text = row['text'] if not scope else '\n'.join(v['text'] for v in row['segments'])
            result.append(dict(tree=tree, **row))
            parent = str(Path(name).parent)
            # Relevant tests/configs, not the entire unrelated sibling directory.
            stem = Path(name).stem
            siblings = {'test_' + stem + '.py', stem + '_test.py', 'conftest.py', '.gitattributes',
                        'pyproject.toml', 'requirements.txt', 'package.json', 'tsconfig.json'}
            pending.update(p for p in entries if p not in seen and
                           (str(Path(p).parent) == parent and Path(p).name in siblings or
                            '/' not in p and p in siblings))
            # Full files preserve functions/contracts; no text summaries substitute.
            if name.endswith('.py'):
                try:
                    parsed = ast.parse(dependency_text)
                except SyntaxError:
                    fail('unknown_dependency', 'invalid Python: ' + name)
                for node in ast.walk(parsed):
                    modules = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ''] if isinstance(node, ast.ImportFrom) else []
                    if isinstance(node, ast.Call) and (isinstance(node.func, ast.Name) and node.func.id in {'eval', 'exec', '__import__'} or isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module'):
                        literal_import = ((isinstance(node.func, ast.Name) and node.func.id == '__import__') or
                                          (isinstance(node.func, ast.Attribute) and node.func.attr == 'import_module'))
                        if literal_import and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                            modules.append(node.args[0].value)
                        else:
                            site = dict(path=name, sha256=row['sha256'], line=node.lineno, call=ast.unparse(node))
                            mapped = [r for r in resolutions if all(r.get(k) == v for k, v in site.items())]
                            if (len(mapped) != 1 or not mapped[0].get('targets') or
                                    len(mapped[0].get('reason', '').strip()) < 20 or
                                    any(p not in entries for p in mapped[0]['targets'])):
                                fail('unknown_dependency', json.dumps(site, sort_keys=True))
                            pending.update(p for p in mapped[0]['targets'] if p not in seen)
                    for module in modules:
                        suffix = module.replace('.', '/') + '.py'
                        candidates = [p for p in entries if p == suffix or p.endswith('/' + suffix)]
                        pending.update(p for p in candidates if p not in seen)
            # Explicit references are supplementary, never the sole relation proof.
            pending.update(p for p in entries if p not in seen and p in dependency_text)
    return sorted(result, key=lambda x: (x['tree'], x['path']))


def atom_context(root, trees, changed, resolutions, source_cache=None):
    slices = {}
    names = {r[k] for r in changed for k in ('old', 'new')}
    for atom in changed:
        if atom.get('source_span'):
            slices.setdefault((atom['after'], atom['new']), []).append(atom['source_span'])
            # Include actual endpoint sources when this retained patch names
            # paths present in the frozen repository, never merely a summary.
            header = atom['logical_header']
            parts = shlex.split(header)
            if len(parts) == 4 and parts[2].startswith('a/') and parts[3].startswith('b/'):
                names.update(p[2:] for p in parts[2:] if any(p[2:] in entries for entries in trees.values()))
    return context(root, trees, names, resolutions, slices=slices, source_cache=source_cache)


def relation_matrix(relations, changed):
    """Compact labels bind to exact atoms once, without repeated 64-byte hashes.

    This removes only redundant metadata. All actual endpoint code, patch bytes
    and each distinct relation remain present and independently judged.
    """
    lookup = {row['id']: i for i, row in enumerate(changed)}
    return dict(discovery='paths/imports/references/exported contracts/tests/configuration + conservative same-component links; reconstructed from frozen sources',
                endpoints=[dict(index=i, change=row['id'], path=row.get('logical_header', row['new']),
                                source_span=row.get('source_span')) for i, row in enumerate(changed)],
                relations=[dict(id=row['id'], endpoints=[lookup[k] for k in row['endpoints']]) for row in relations])


def logical_path(row):
    if row.get('logical_header'):
        parts = shlex.split(row['logical_header'])
        if len(parts) == 4 and parts[3].startswith('b/'):
            return parts[3][2:]
    return row['new']


def references(text, value):
    """Exact Unicode word boundaries without rescanning all text via regex."""
    at = text.find(value)
    while at >= 0:
        end = at + len(value)
        if ((at == 0 or not (text[at - 1].isalnum() or text[at - 1] == '_')) and
                (end == len(text) or not (text[end].isalnum() or text[end] == '_'))):
            return True
        at = text.find(value, at + 1)
    return False


def discover(root, trees, atoms, patches, resolutions):
    """Conservative, reproducible dependency analysis, never an author assertion.

    Whole frozen source/closures are used when present; retained patch atoms
    also retain their actual diff code. Module/test families within a directory
    overapproximate implicit local contracts. Cross-component links require a
    path/module/reference, shared exported contract, test or configuration.
    This is a planner, not a claim of complete semantic understanding: native
    reviewers must block newly discovered dependencies and force replanning.
    """
    facts = []; contexts = {}; identifiers = {}; cache = {}
    for atom in atoms:
        path = logical_path(atom)
        material = atom_context(root, trees, [atom], resolutions, cache)
        # Physical wrapper files are not semantic dependencies between every
        # section of a retained patch. Their spans remain exact in each package.
        sources = {r['path'] for r in material if r['path'] != atom['new'] or not atom.get('source_span')}
        text = patches[atom['id']].decode() + '\n' + '\n'.join(r['text'] + '\n'.join(v['text'] for v in r.get('segments', [])) for r in material)
        # Strip diff '+' nesting only for declaration discovery, retaining raw
        # source hashes and complete real code for all actual review packages.
        owned = patches[atom['id']].decode() + '\n' + '\n'.join(r['text'] for r in material if r['path'] == path)
        code = re.sub(r'(?m)^\++', '', owned)
        exports = sorted(set(re.findall(r'\b(?:def|class|function|interface|type|const|enum)\s+([A-Za-z_]\w{3,})', code)) |
                         set(re.findall(r'\b([A-Z][A-Z0-9_]{5,})\s*=', code)))
        stem = re.sub(r'^test[_-]|[_-]test$', '', Path(path).stem)
        family = '_'.join(re.split('[_-]', stem)[:2])
        facts.append(dict(change=atom['id'], path=path, component=str(Path(path).parent) + ':' + family,
                          source_sha256=ce.digest(text.encode()), material_bytes=len(text.encode()), sources=sorted(sources), exports=exports))
        # A filename in a diff's own transport header is not an import/use of
        # every other file with that basename. Keep headers in the reviewed
        # bytes/hash, but exclude them from dependency reference discovery.
        transport = re.compile(r'^\+*(?:diff --git |--- |\+\+\+ |index |@@ |new file mode |deleted file mode |old mode |new mode |rename from |rename to |similarity index )')
        references_text = '\n'.join(line.lstrip('+') for line in text.splitlines() if not transport.match(line))
        contexts[atom['id']] = references_text
        identifiers[atom['id']] = set(re.findall(r'\b[A-Za-z_]\w*\b', references_text))
    # A generic name independently defined in several files is not evidence of
    # a cross-file contract. Imports/path/component closure still apply there.
    exporters = {}
    for fact in facts:
        for symbol in fact['exports']:
            exporters.setdefault(symbol, set()).add(fact['path'])
    relations = []
    global_names = {'pyproject.toml', 'requirements.txt', 'package.json', 'tsconfig.json', '.gitattributes', '.gitmodules'}
    for left, right in itertools.combinations(facts, 2):
        reasons = []
        if left['path'] == right['path']:
            reasons.append('same logical path across retained revisions/sections')
        if left['component'] == right['component']:
            reasons.append('conservative component: ' + left['component'])
        for a, b in ((left, right), (right, left)):
            path = a['path']; text = contexts[b['change']]
            stem = Path(path).stem
            aliases = {path, path.removesuffix('.py').replace('/', '.')}
            if len(stem) >= 6 and stem.lower() not in {'readme', 'manifest', 'package', 'design', 'tasks', 'proposal'}:
                aliases.add(stem)
            if path in b['sources'] or any(references(text, alias) for alias in aliases):
                reasons.append('source/import/path reference: ' + b['path'] + ' -> ' + path)
            # Exported names are candidate contracts, not arbitrary shared
            # words such as root/path. Unchanged linked sources are in closure.
            used = sorted(symbol for symbol in set(a['exports']) & identifiers[b['change']] if len(exporters[symbol]) == 1)
            if used:
                reasons.append('exported contract reference: ' + path + ':' + ','.join(used))
            directory = str(Path(path).parent)
            if Path(path).name in global_names and (directory == '.' or b['path'].startswith(directory + '/')):
                reasons.append('configuration scope: ' + path)
        if reasons:
            relations.append(dict(id='r:' + str(len(relations)), endpoints=[left['change'], right['change']], reason='; '.join(sorted(set(reasons)))))
    return dict(method='frozen-dependency-analysis-v1', facts=facts,
                isolated=[f['change'] for f in facts if not any(f['change'] in r['endpoints'] for r in relations)],
                limitations='Static conservative candidates; unknown dynamic calls block context closure; newly discovered semantic links block native acceptance.'), relations


def budget(raw, config):
    if (set(config) not in ({'limit', 'limit_source', 'overhead', 'uncertainty_percent'},
                            {'limit', 'limit_source', 'overhead', 'uncertainty_percent', 'tokenizer'}) or
            type(config['limit']) is not int or config['limit'] <= 0 or
            set(config['overhead']) != set(COSTS) or any(type(n) is not int or n <= 0 for n in config['overhead'].values()) or
            type(config['uncertainty_percent']) is not int or config['uncertainty_percent'] < 25):
        fail('budget_unknown', 'positive per-category reservations and >=25% uncertainty required')
    limit_source = config['limit_source']
    source_path, rows, _, turns = ce.Rollout().session(limit_source['session'])
    observed = [(r, sha) for i, r, sha in rows if i == limit_source['ordinal']]
    if (str(source_path) != limit_source['path'] or len(observed) != 1 or
            observed[0][1] != limit_source['raw_sha256'] or observed[0][0]['type'] != 'event_msg' or
            observed[0][0]['payload'].get('type') != 'token_count'):
        fail('budget_source_changed')
    info = observed[0][0]['payload'].get('info')
    window = info.get('model_context_window') if isinstance(info, dict) else None
    before = [r['payload'] for i, r, _ in rows if i < limit_source['ordinal'] and r['type'] == 'turn_context']
    if (type(window) is not int or config['limit'] > window or not before or
            (before[-1].get('model'), before[-1].get('effort')) != (limit_source['model'], limit_source['effort'])):
        fail('budget_unknown', 'window must come from native token_count for the requested model')
    # Byte fallback bound: count JSON-escaped full delivery twice (command and
    # delivered tool result); no invented tokenizer ratio. This is an estimate.
    escaped = json.dumps(raw.decode('utf-8'), ensure_ascii=True)
    delivery = len(escaped.encode()) * 2
    method = 'UTF8-byte-fallback/JSON-ascii/two-deliveries-v1; estimate, not native usage'
    if config.get('tokenizer'):
        wanted = config['tokenizer']
        if wanted != {'method': 'dual-tiktoken-v1', 'version': '0.14.0'}:
            fail('budget_unknown', 'unsupported tokenizer method/version')
        try:
            import tiktoken
        except ImportError:
            fail('budget_unknown', 'requested tokenizer unavailable; explicitly replan using byte fallback, never silently change method')
        if tiktoken.__version__ != wanted['version']:
            fail('budget_unknown', 'tokenizer version changed')
        delivery = 2 * max(len(tiktoken.get_encoding(enc).encode(escaped, disallowed_special=()))
                           for enc in ('o200k_base', 'cl100k_base'))
        method = 'tiktoken0.14.0 max(o200k_base,cl100k_base)/JSON-ascii/two-deliveries-v1; proxy estimate, not native usage'
    subtotal = delivery + sum(config['overhead'].values())
    total = (subtotal * (100 + config['uncertainty_percent']) + 99) // 100
    if total >= config['limit']:
        fail('budget_insufficient', f'estimated {total} >= limit {config["limit"]}; current coherent package requires replanning, not proof of semantic indivisibility')
    return dict(method=method,
                delivery_bound=delivery, overhead=config['overhead'], uncertainty_percent=config['uncertainty_percent'],
                estimated_total=total, limit=config['limit'], limit_source=limit_source)


def plan(snapshot_path, config, *, diagnostic=False, resolutions=(), authority_root=None):
    s = check_snapshot(snapshot_path); root = Path(s['root']); out = Path(snapshot_path).parent
    trees = {t: tree_files(root, t) for t in set(filter(None, [s['base_tree'], s['index_tree'], s['target_tree']]))}
    rows = review_atoms(s); items = []
    patches = atom_patches(root, rows)
    discovery, relations = discover(root, trees, rows, patches, resolutions)
    sizes = {f['change']: f['material_bytes'] for f in discovery['facts']}
    cached_context = {}; source_cache = {}
    def render(kind, changed, rels):
        names = sorted({r[k] for r in changed for k in ('old', 'new')})
        key = tuple(r['id'] for r in changed)
        if key not in cached_context:
            cached_context[key] = atom_context(root, trees, changed, resolutions, source_cache)
        contents = cached_context[key]
        patch = b''.join(patches[r['id']] for r in changed).decode('utf-8')
        payload = dict(version=VERSION, snapshot=s['integrity_sha256'], kind=kind, diagnostic=diagnostic,
                       changes=[r['id'] for r in changed], relations=[r['id'] for r in rels],
                       relation_matrix=relation_matrix(rels, changed), patch=patch, contents=contents, dependency_resolutions=list(resolutions))
        identifier = ce.digest(payload)
        raw = (PREFIX + json.dumps(dict(payload, id=identifier), ensure_ascii=True, sort_keys=True) + '\n').encode()
        cost = budget(raw, config)
        return identifier, raw, cost, payload

    def emit(rendered):
        identifier, raw, cost, payload = rendered
        package = out / (identifier + '.review.txt')
        if package.exists() and read(package) != raw:
            fail('immutable_changed', str(package))
        atomic_write_bytes(package, raw); package.chmod(0o400)
        items.append(dict(id=identifier, kind=payload['kind'], changes=payload['changes'], relations=payload['relations'],
                          package=str(package), sha256=ce.digest(raw), budget=cost))
    def area(row):
        return str(Path(logical_path(row)).parent)
    internal = set()
    # A small coherent area keeps the simple single-pair path. Whole functions
    # and inner-file atoms are packed without splitting their code contracts.
    for directory in dict.fromkeys(area(r) for r in rows):
        local = [r for r in rows if area(r) == directory]
        while local:
            selected = local[:1]
            def local_relations(values):
                ids = {r['id'] for r in values}
                return [r for r in relations if set(r['endpoints']) <= ids]
            rendered = render('unit', selected, local_relations(selected))
            low, high = 1, len(local)
            while low < high:
                count = (low + high + 1) // 2
                proposed = local[:count]
                try:
                    expanded = render('unit', proposed, local_relations(proposed))
                except ce.EvidenceError as exc:
                    if exc.code != 'bounded_budget_insufficient':
                        raise
                    high = count - 1
                else:
                    low = count
                    selected, rendered = proposed, expanded
            emit(rendered)
            internal.update(r['id'] for r in local_relations(selected))
            local = local[len(selected):]
    # Cover the conservative graph by budget-bounded overlapping groups rather
    # than spawning a wave for every edge. Each edge has exactly one owner.
    remaining = {r['id']: r for r in relations if r['id'] not in internal}
    by_id = {r['id']: r for r in rows}
    while remaining:
        first = next(iter(remaining.values()))
        members = set(first['endpoints'])
        def included(current):
            return [r for r in remaining.values() if set(r['endpoints']) <= current]
        def ordered(current):
            return [r for r in rows if r['id'] in current]
        rendered = render('integration', ordered(members), included(members))
        # Prefer same-directory neighbors for cohesive groups; never omit an
        # uncovered edge because unrelated endpoints did not fit this group.
        parents = {str(Path(by_id[i]['new']).parent) for i in members}
        edge_set = {frozenset(r['endpoints']) for r in remaining.values()}
        candidates = sorted((i for i in by_id if i not in members and any(frozenset((i, j)) in edge_set for j in members)),
                            key=lambda i: (-sum(frozenset((i, j)) in edge_set for j in members),
                                           sizes[i],
                                           str(Path(by_id[i]['new']).parent) not in parents, by_id[i]['new'], i))
        # Search conservative prefixes rather than re-tokenizing every failed
        # addition after a group fills. Final selected payload is always checked;
        # optimal packing/monotonic tokenizer counts are not assumed as proof.
        low, high = 0, len(candidates)
        seed = set(members)
        while low < high:
            count = (low + high + 1) // 2
            proposed = seed | set(candidates[:count])
            try:
                expanded = render('integration', ordered(proposed), included(proposed))
            except ce.EvidenceError as exc:
                if exc.code != 'bounded_budget_insufficient':
                    raise
                high = count - 1
            else:
                low = count
                members, rendered = proposed, expanded
        emit(rendered)
        for relationship in included(members):
            del remaining[relationship['id']]
    value = dict(version=VERSION, snapshot=str(Path(snapshot_path).resolve()), snapshot_sha256=s['integrity_sha256'],
                 root=str(root), diagnostic=diagnostic, discovery=discovery,
                 relations=relations, items=items, config=config, implementation=implementation(), resolutions=list(resolutions), atoms=rows)
    if authority_root:
        import process_authority as pa
        value['authority'] = pa.capture(authority_root, root.name.split('-')[1])
    count = len(items)
    units = sum(i['kind'] == 'unit' for i in items)
    value['execution_estimate'] = dict(atoms=len(rows), units=units, integration_groups=count - units,
        semantic_pairs=count, semantic_reviewers=2 * count, coordinators=count,
        context_diagnostic_children=count, probe_children=0 if diagnostic else 2 * count,
        total_native_child_births=(3 if diagnostic else 5) * count,
        coordinator_launches=(3 if diagnostic else 4) * count,
        note='fresh bootstrap/context/probe per item; estimates exclude bounded retries and extra polling')
    save(out / 'plan.json', value, immutable=True)
    return out / 'plan.json'


def implementation():
    return {name: ce.digest(Path(__file__).with_name(name).read_bytes()) for name in
            ('codex_bounded_review.py', 'codex_terminal.py', 'codex_terminal_review.py', 'codex_review.py',
             'codex_review_session.py', 'codex_review_probe.py', 'codex_evidence.py', 'codex_context.py',
             'codex_proxy.py', 'model_selection.py', 'review_process_checklist.py')}


def check_plan(path):
    p = load(path); s = check_snapshot(p['snapshot'])
    if p.get('authority'):
        import process_authority as pa
        pa.verify(p['authority'], Path(p['root']).name.split('-')[1])
    if p['version'] != VERSION or p['root'] != s['root'] or p['snapshot_sha256'] != s['integrity_sha256'] or p['implementation'] != implementation():
        fail('global_invalidation', 'snapshot/version/implementation changed')
    atoms = review_atoms(s)
    patches = atom_patches(s['root'], atoms); source_cache = {}
    if atoms != p['atoms']:
        fail('fragment_coverage_changed')
    expected = [r['id'] for r in atoms]
    units = [c for i in p['items'] if i['kind'] == 'unit' for c in i['changes']]
    if sorted(units) != sorted(expected) or len(units) != len(set(units)):
        fail('coverage_gap_or_duplicate')
    trees = {t: tree_files(s['root'], t) for t in set(filter(None, [s['base_tree'], s['index_tree'], s['target_tree']]))}
    discovery, relations = discover(s['root'], trees, atoms, patches, p['resolutions'])
    if discovery != p['discovery'] or relations != p['relations']:
        fail('relation_coverage')
    covered = [r for i in p['items'] for r in i['relations']]
    if sorted(covered) != sorted(r['id'] for r in relations) or len(covered) != len(set(covered)):
        fail('relation_coverage')
    for item in p['items']:
        raw = read(item['package'])
        if ce.digest(raw) != item['sha256'] or not raw.startswith(PREFIX.encode()):
            fail('package_sha_changed')
        body = json.loads(raw.decode()[len(PREFIX):]); identity = body.pop('id')
        if (identity != item['id'] or ce.digest(body) != identity or body['snapshot'] != s['integrity_sha256'] or
                body['version'] != VERSION or body['diagnostic'] != p['diagnostic'] or
                any(body[k] != item[k] for k in ('changes', 'relations', 'kind'))):
            fail('package_binding')
        obligations = [r for r in relations if r['id'] in item['relations']]
        changed = [r for r in atoms if r['id'] in item['changes']]
        if body['relation_matrix'] != relation_matrix(obligations, changed) or any(not set(r['endpoints']) <= set(item['changes']) for r in obligations):
            fail('relation_endpoints_missing')
        if budget(raw, p['config']) != item['budget']:
            fail('budget_changed')
        # Reconstruct actual context and patch; a self-sealed rewritten package
        # must not silently remove a dependency or substitute endpoint code.
        changed = [r for r in atoms if r['id'] in item['changes']]
        trees = {t: tree_files(s['root'], t) for t in set(filter(None, [s['base_tree'], s['index_tree'], s['target_tree']]))}
        names = {r[k] for r in changed for k in ('old', 'new')}
        if body['contents'] != atom_context(s['root'], trees, changed, p['resolutions'], source_cache) or body['dependency_resolutions'] != p['resolutions']:
            fail('context_changed')
        patch = b''.join(patches[r['id']] for r in changed).decode()
        if patch != body['patch']:
            fail('package_binding')
    return p


@contextlib.contextmanager
def ledger_lock(path):
    lock = Path(str(path) + '.lock')
    if lock.is_symlink():
        fail('ledger_invalid')
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def new_ledger(plan_path, path):
    p = check_plan(plan_path)
    path = inside(p['root'], path)
    with ledger_lock(path):
        if Path(path).exists():
            fail('ledger_exists')
        save(path, dict(version=VERSION, plan=str(Path(plan_path).resolve()), plan_sha256=p['integrity_sha256'],
                        root=p['root'], events=[]))
    return str(path)


def event(path, kind, **fields):
    with ledger_lock(path):
        ledger = load(path)
        ledger.pop('integrity_sha256')
        prior = ledger['events']
        row = ce.sealed(dict(kind=kind, sequence=len(prior), previous=prior[-1]['integrity_sha256'] if prior else ledger['plan_sha256'], **fields))
        prior.append(row); save(path, ledger)


def checked_ledger(path):
    ledger = load(path); previous = ledger['plan_sha256']
    inside(ledger['root'], path)
    for n, row in enumerate(ledger['events']):
        ce.check_seal(row)
        if row['sequence'] != n or row['previous'] != previous:
            fail('ledger_invalid')
        previous = row['integrity_sha256']
    try:
        p = check_plan(ledger['plan'])
        if p['integrity_sha256'] != ledger['plan_sha256'] or p['root'] != ledger['root']:
            fail('global_invalidation')
    except (ce.EvidenceError, OSError, ValueError) as exc:
        event(path, 'failure', code='global_invalidation', detail=str(exc))
        raise
    return ledger, p


def native_result(proof, item, p, *, runtime=None):
    rt = runtime or ce.Rollout()
    # Scan the entire child history, including compaction after full delivery.
    source_path, rows, _, _ = rt.session(proof['child_thread'])
    if any('compact' in row['type'].lower() or 'compact' in str(row.get('payload', {}).get('type', '')).lower() for _, row, _ in rows):
        fail('compaction', str(source_path))
    completed = [row['payload']['last_agent_message'] for _, row, _ in rows
                 if row['type'] == 'event_msg' and row['payload'].get('type') == 'task_complete']
    if len(completed) != 1:
        fail('payload_incomplete')
    try:
        result = json.loads(completed[0])
    except ValueError:
        fail('payload_incomplete', 'one complete JSON finding object required')
    expected = dict(schema=VERSION, item=item['id'], snapshot=p['snapshot_sha256'], role=proof['role'],
                    changes=item['changes'], relations=item['relations'])
    if any(result.get(k) != v for k, v in expected.items()):
        fail('coverage_or_payload_binding')
    if result.get('discovered_relations') != []:
        fail('unknown_dependency', 'new relation requires a new complete plan and births')
    if result.get('verdict') not in {'PASS', 'FINDINGS', 'BLOCKED'} or not isinstance(result.get('findings'), list):
        fail('payload_incomplete')
    if result['verdict'] == 'PASS' and result['findings']:
        fail('payload_incomplete', 'PASS contradicts findings')
    if result['verdict'] != 'PASS':
        fail('findings', json.dumps(result['findings']))
    return result


def reject_compacted_tasks(package, *, runtime):
    """Diagnose observed compaction before replay can look like sandbox drift.

    This only refuses. Native chain/permissions/probes are still verified by
    their original helpers; a marker can never establish a successful result.
    """
    candidates = []
    for birth_path in package.get('births', []):
        birth = load(birth_path)
        try:
            candidates.extend(runtime.locate(agent_path='/root/' + birth['task_name']))
        except ce.EvidenceError:
            pass  # normal provenance checker retains the missing-source cause
    try:
        for line in read(package['events']).splitlines():
            row = json.loads(line)
            if row.get('type') == 'thread.started' and isinstance(row.get('thread_id'), str):
                candidates.extend(runtime.locate(thread=row['thread_id']))
    except (ValueError, OSError, ce.EvidenceError):
        pass
    for thread, source_path in candidates:
        rows = runtime.read(Path(source_path))
        if any('compact' in r['type'].lower() or 'compact' in str(r['payload'].get('type', '')).lower() for _, r, _ in rows):
            fail('compaction', 'native compaction in ' + thread + '; no sandbox promotion or acceptance')


def verify_item(p, item, attempt, *, runtime=None):
    """Reopen original sources; never trust a ledger PASS or rewrite a receipt."""
    rt = runtime or ce.Rollout()
    for evidence in attempt['evidence']:
        envelope = load(evidence)
        if envelope.get('birth', {}).get('dedicated_package'):
            reject_compacted_tasks(cs.read_package(envelope['birth']['dedicated_package']), runtime=rt)
    proofs = [ce.verify_evidence(e, runtime=rt) for e in attempt['evidence']]
    if len(proofs) != 2 or {x['role'] for x in proofs} != set(cr.REVIEWERS) or len({x['child_thread'] for x in proofs}) != 2:
        fail('coverage_profiles')
    packages = {x['birth']['dedicated_package'] for x in proofs}
    if len(packages) != 1:
        fail('native_chain')
    path = next(iter(packages)); dedicated = cs.read_package(path)
    coordinator = cs.binding(path, runtime=rt, complete=True)['coordinator_thread']
    if any('compact' in row['type'].lower() or 'compact' in str(row['payload'].get('type', '')).lower()
           for _, row, _ in rt.session(coordinator)[1]):
        fail('compaction', 'dedicated coordinator compacted')
    if dedicated['diff'] != item['package'] or dedicated['diff_sha256'] != item['sha256']:
        fail('package_binding')
    if p['diagnostic']:
        if dedicated['phase'] != 'probe' or not all(x['qualification'] for x in proofs):
            fail('diagnostic_binding')
        cs.binding(path, runtime=rt, complete=True)
        from codex_review_probe import qualify
        qualify(attempt['evidence'], root=p['root'], runtime=rt)
    else:
        if dedicated['phase'] != 'review':
            fail('product_binding')
        expected_log = str(Path(item['package']).with_suffix('.native-proxies.jsonl'))
        if attempt.get('proxy_log') != expected_log:
            fail('proxy_scope')
        cr.verify_wave(root=p['root'], wave_id=dedicated['wave_id'], expected_sha256=item['sha256'], proxy_log=expected_log,
                       bound_card=dedicated['bound_card'])
    for proof in proofs:
        if p['diagnostic']:
            import codex_context as cc
            from codex_review_probe import observe
            cc.verify_qualification(root=p['root'], out=ce.destination(p['root']),
                                    session=proof['parent_thread'], runtime=rt)
            observe(proof['birth'], proof, runtime=rt)
            cs.verify_route(dedicated['bootstrap'], runtime=rt)
        else:
            ce.require_review_guarantees(proof)
        native_result(proof, item, p, runtime=rt)
    return proofs


def pending(path, *, runtime=None):
    ledger, p = checked_ledger(path); done = set()
    for row in ledger['events']:
        if row['kind'] == 'complete':
            item = next((i for i in p['items'] if i['id'] == row['item']), None)
            if item is None:
                fail('global_invalidation')
            try:
                verify_item(p, item, row, runtime=runtime)
            except (ce.EvidenceError, cr.ReviewDiffError, OSError, ValueError) as exc:
                event(path, 'failure', item=row['item'], code=getattr(exc, 'code', 'source_revalidation'), detail=str(exc))
                raise
            done.add(item['id'])
    return p, [i for i in p['items'] if i['id'] not in done]


def verify(path, *, runtime=None, activation=None):
    p, todo = pending(path, runtime=runtime)
    if todo:
        fail('coverage_incomplete', ','.join(i['id'] for i in todo))
    from model_selection import resolve
    pair = resolve('codex', 'execucao')['arguments']
    if (pair['model'], pair['reasoning_effort']) != (p['config']['limit_source']['model'], p['config']['limit_source']['effort']):
        fail('model_changed', 'replan/requalify for the newly selected model; no cross-model budget reuse')
    if not p['diagnostic']:
        require_activation(activation, p['root'], runtime=runtime)
        save(Path(p['root']) / '.cursor/tmp/bounded-review-current.json',
             dict(ledger=str(Path(path).resolve()), activation=str(Path(activation).resolve()), version=VERSION))
        from codex_terminal import state
        s = load(p['snapshot'])
        card = Path(p['root']).name.split('-')[1]
        if state(Path(p['root']), card, 'review', p.get('authority'))['q'] != 'Code Review':
            fail('status_changed')
    return dict(result='diagnostic_verified' if p['diagnostic'] else 'verified', protocol=VERSION,
                snapshot=p['snapshot_sha256'], diff_sha256=load(p['snapshot'])['diff_sha256'],
                wave_id=p['integrity_sha256'], items=len(p['items']), relations=len(p['relations']))


def native_success(runtime, spec):
    """Reopen one exact successful native command, including legacy text."""
    source, rows, _, _ = runtime.session(spec['session'])
    matches = []
    for i, row, sha in rows:
        value = row['payload']; item = value.get('item', {})
        if str(source) != spec['source']['source'] or i != spec['source']['ordinal'] or sha != spec['source']['raw_sha256']:
            continue
        if (row['type'] != 'event_msg' or value.get('type') != 'item_completed' or
                value.get('thread_id') != spec['session'] or item.get('type') != 'CommandExecution' or
                item.get('command') not in [['/bin/bash', '-lc', spec['command']], ['/bin/bash', '-c', spec['command']]] or
                cs._cwd(item.get('cwd', '')) != Path(spec['root']).resolve() or
                item.get('exit_code') != 0 or item.get('status') != 'completed' or
                item.get('source') not in {'unified_exec_startup', 'unified_exec_poll'}):
            fail('activation_source_changed')
        output = item.get('aggregated_output')
        if not isinstance(output, str) or ce.digest(output.encode()) != spec['output_sha256']:
            fail('activation_source_changed')
        matches.append(output)
    if len(matches) != 1:
        fail('activation_source_unavailable')
    return matches[0]


def require_activation(path, root, *, runtime=None):
    """Require source-bound trusted-base Review, installed trust and both routes."""
    if path is None:
        fail('inactive', 'legacy bootstrap Review, pin/trust and both live route diagnostics required')
    a = load(path); rt = runtime or ce.Rollout(); root = Path(root).resolve()
    if a.get('version') != VERSION or a.get('implementation') != implementation() or a.get('root') != str(root):
        fail('activation_scope')
    b = a['bootstrap']; base = Path(b['trusted_base']).resolve()
    commit = 'c8b794c76c1c69017f4bef84c220d7e42a15286a'
    expected = tree_files(b['git_root'], commit)
    for name, entry in expected.items():
        if name.startswith('scripts/process-fsm/'):
            if read(base / name) != git(b['git_root'], 'cat-file', 'blob', entry['oid']):
                fail('bootstrap_base_changed', name)
    patch = read(b['diff'])
    support = Path(b['support_root']).resolve()
    if ce.digest(patch) != b['diff_sha256'] or git(support, 'diff', '--binary', '--full-index', commit, b['target']) != patch:
        fail('bootstrap_diff_changed')
    for name, digest in implementation().items():
        reviewed = git(support, 'show', b['target'] + ':scripts/process-fsm/' + name)
        if ce.digest(read(root / 'scripts/process-fsm' / name)) != digest or ce.digest(reviewed) != digest:
            fail('pin_changed', name)
    review = a['legacy_review']; checklist = a['legacy_checklist']
    wanted = [sys.executable, str(base / 'scripts/process-fsm/codex_review.py'), 'verify-wave',
              '--root', str(support), '--wave-id', b['wave_id'], '--sha256', b['diff_sha256'], '--bound-card', b['card']]
    if shlex.split(review['command']) != wanted or review['root'] != str(support):
        fail('activation_contract', 'trusted-base exact-wave command required')
    output = native_success(rt, review)
    if ('review_diff_sha256: ' + b['diff_sha256']) not in output or ('review_wave_id: ' + b['wave_id']) not in output:
        fail('activation_contract')
    entries = cr._proxy_entries(support, b['proxy_log'], b['wave_id'])
    if {e['activity'] for e in entries} != set(cr.REVIEWERS):
        fail('activation_contract')
    for entry in entries:
        proof = ce.verify_proxy(entry)
        ce.require_review_guarantees(proof)
        if proof['qualification'] or proof['review_diff_sha256'] != b['diff_sha256']:
            fail('activation_contract')
    wanted = [sys.executable, '-I', str(base / 'scripts/process-fsm/review_process_checklist.py'),
              '--root', str(support), '--change-root', checklist['change_root'], '--phase', 'precommit', '--wave-same-turn', 'yes']
    if shlex.split(checklist['command']) != wanted or checklist['root'] != str(support):
        fail('activation_contract')
    native_success(rt, checklist)
    from account_registration import require_active
    if require_active(client='codex', workdir=root, session=os.environ.get('CODEX_THREAD_ID')) is None:
        fail('installation_trust', 'account pin/registration required')
    surfaces = set()
    for ledger_path in a['diagnostics']:
        l, p = checked_ledger(ledger_path)
        if not p['diagnostic'] or p['implementation'] != implementation() or p['root'] != str(root):
            fail('activation_scope')
        if verify(ledger_path, runtime=rt)['result'] != 'diagnostic_verified':
            fail('activation_contract')
        complete = next(e for e in l['events'] if e['kind'] == 'complete')
        proof = ce.verify_evidence(complete['evidence'][0], runtime=rt)
        surfaces.add(proof['dedicated_chain']['principal_host'])
    if surfaces != {'codex-tui', 'codex_exec'}:
        fail('activation_routes')
    return a


def advance(path, *, activation=None, runtime=None):
    with ledger_lock(Path(path).with_suffix('.advance')):
        return _advance(path, activation=activation, runtime=runtime)


def _advance(path, *, activation=None, runtime=None):
    """Drive the existing principal terminal controller once for the next item.

    Native commands are returned for the same principal's command tool. The
    controller handles fresh bootstrap/context/probes, captures and native pair.
    No child is launched by Python, no runtime receipt is fabricated here.
    """
    import codex_terminal as ct
    p, todo = pending(path, runtime=runtime)
    if not todo:
        return verify(path, activation=activation, runtime=runtime)
    from model_selection import resolve
    pair = resolve('codex', 'execucao')['arguments']
    if (pair['model'], pair['reasoning_effort']) != (p['config']['limit_source']['model'], p['config']['limit_source']['effort']):
        fail('model_changed', 'replan/requalify for the newly selected model')
    if not p['diagnostic']:
        require_activation(activation, p['root'], runtime=runtime)
        save(Path(p['root']) / '.cursor/tmp/bounded-review-current.json',
             dict(ledger=str(Path(path).resolve()), activation=str(Path(activation).resolve()), version=VERSION))
    item = todo[0]; ledger = load(path)
    attempts = [e for e in ledger['events'] if e['kind'] == 'attempt' and e['item'] == item['id']]
    if not attempts:
        cp = ct.start(root=p['root'], card=Path(p['root']).name.split('-')[1], operation='review',
                      diff=item['package'], diagnostics_authorized=True, runtime=runtime,
                      authority_root=(p.get('authority') or {}).get('root'))
        event(path, 'attempt', item=item['id'], checkpoint=cp['checkpoint'])
    else:
        cp = attempts[-1]
    try:
        # Diagnostics use the same native bootstrap/context/probe route, with the
        # bounded package at the final probe; they never call a product stage.
        checkpoint = ct.read_checkpoint(cp['checkpoint'])
        checkpoint = dict(checkpoint, bounded_proxy_log=str(Path(item['package']).with_suffix('.native-proxies.jsonl')))
        _, session, source_path, _, meta, turn = ct.active(runtime)
        if (session != checkpoint['session'] or str(source_path) != checkpoint['source'] or
                meta['originator'] != checkpoint['surface'] or Path(turn['cwd']).resolve() != Path(p['root']) or
                checkpoint['target_root'] != p['root'] or turn['sandbox_policy'].get('type') not in {'workspace-write', 'danger-full-access'}):
            fail('principal_binding_changed')
        if p['diagnostic']:
            checkpoint = dict(checkpoint, bounded_diagnostic=True)
        from codex_terminal_review import advance_review
        live = {'q': None} if p['diagnostic'] else ct.state(Path(p['root']), checkpoint['card'], 'review', checkpoint.get('authority'))
        result = advance_review(checkpoint, Path(p['root']), live, runtime=runtime or ce.Rollout())
        if result['result'] in {'review_wave_verified', 'bounded_diagnostic_collected'}:
            attempt = dict(item=item['id'], evidence=result['evidence'], proxy_log=checkpoint['bounded_proxy_log'])
            verify_item(p, item, attempt, runtime=runtime)
            event(path, 'complete', **attempt)
            return dict(result='item_verified', item=item['id'], remaining=len(todo) - 1)
        if result['result'] in {'blocked', 'recovery_required', 'interrupted'}:
            event(path, 'failure', item=item['id'], code=result.get('code', result['result']), detail=result)
        return dict(result, item=item['id'])
    except (ce.EvidenceError, cr.ReviewDiffError, OSError, ValueError) as exc:
        event(path, 'failure', item=item['id'], code=getattr(exc, 'code', 'native_verification'), detail=str(exc))
        raise


def retry(path, item_id):
    """Explicit fresh pending attempt; preserve every failed checkpoint/birth."""
    p, todo = pending(path)
    if item_id not in {i['id'] for i in todo}:
        fail('retry_not_pending')
    ledger = load(path)
    failures = [e for e in ledger['events'] if e['kind'] == 'failure' and e.get('item') == item_id]
    retries = [e for e in ledger['events'] if e['kind'] == 'retry' and e.get('item') == item_id]
    if any(e.get('code') in {'bounded_findings', 'bounded_unknown_dependency'} for e in failures):
        fail('retry_requires_replan', 'semantic findings/new dependencies require correction and a new snapshot/plan; never resample a verdict')
    if not failures or retries:
        fail('retry_ceiling', 'one explicit recovery; preserve residual/P0 policy')
    event(path, 'retry', item=item_id)
    item = next(i for i in p['items'] if i['id'] == item_id)
    import codex_terminal as ct
    cp = ct.start(root=p['root'], card=Path(p['root']).name.split('-')[1], operation='review',
                  diff=item['package'], diagnostics_authorized=True,
                  authority_root=(p.get('authority') or {}).get('root'))
    event(path, 'attempt', item=item_id, checkpoint=cp['checkpoint'])
    return cp


def prompt_contract(diff):
    raw = read(diff)
    if not raw.startswith(PREFIX.encode()):
        return ''
    p = json.loads(raw.decode()[len(PREFIX):])
    return ('\nThis is a bounded review package, not just a patch. Inspect ALL real base/target contents, patch and relation_matrix. '
            'Review every listed change/relation; report newly discovered dependencies, never silently discard them. '
            'Hashes/delivery do not establish semantic correctness. Return exactly ONE JSON object (no fence), with '
            'schema="' + VERSION + '", item="' + p['id'] + '", snapshot="' + p['snapshot'] + '", '
            'role equal to your named profile, changes=' + json.dumps(p['changes']) + ', relations=' + json.dumps(p['relations']) + ', '
            'verdict PASS|FINDINGS|BLOCKED, findings=[complete actionable findings], discovered_relations=[new required endpoints/contracts]. '
            'Only use PASS with no findings and no unknown dependencies. This is diagnostic only, no product/transition, '
            'when package diagnostic=true. Never infer PASS from another reviewer or byte delivery.\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    c = commands.add_parser('capture'); c.add_argument('--root', required=True); c.add_argument('--out', required=True)
    c.add_argument('--mode', choices=['precommit', 'closing'], default='precommit'); c.add_argument('--base', default='HEAD'); c.add_argument('--target', default='HEAD')
    q = commands.add_parser('plan'); q.add_argument('--snapshot', required=True); q.add_argument('--budget', required=True); q.add_argument('--diagnostic', action='store_true'); q.add_argument('--context-map'); q.add_argument('--authority-root')
    l = commands.add_parser('ledger'); l.add_argument('--plan', required=True); l.add_argument('--out', required=True)
    for name in ('pending', 'advance', 'verify'):
        q = commands.add_parser(name); q.add_argument('--ledger', required=True); q.add_argument('--activation')
    r = commands.add_parser('retry'); r.add_argument('--ledger', required=True); r.add_argument('--item', required=True)
    a = parser.parse_args()
    try:
        if a.action == 'capture':
            result = {'snapshot': str(capture(a.root, a.out, mode=a.mode, base=a.base, target=a.target))}
        elif a.action == 'plan':
            result = {'plan': str(plan(a.snapshot, json.loads(read(a.budget)), diagnostic=a.diagnostic,
                                       resolutions=json.loads(read(a.context_map)) if a.context_map else (),
                                       authority_root=a.authority_root))}
        elif a.action == 'ledger':
            result = {'ledger': new_ledger(a.plan, a.out)}
        elif a.action == 'pending':
            result = {'pending': [i['id'] for i in pending(a.ledger)[1]]}
        elif a.action == 'retry':
            result = retry(a.ledger, a.item)
        else:
            result = globals()[a.action](a.ledger, activation=a.activation)
        print(json.dumps(result, sort_keys=True))
    except (ce.EvidenceError, cr.ReviewDiffError, ValueError, OSError, KeyError) as exc:
        print(json.dumps(dict(result='blocked', code=getattr(exc, 'code', 'bounded_invalid'), detail=str(exc))))
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
