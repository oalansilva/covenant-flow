"""Register or inspect original Codex capability references, without trust."""
import argparse
import json
from pathlib import Path

import codex_evidence as ce
from codex_qualification_index import Index, SURFACES


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('register', 'discover'):
        command = sub.add_parser(name)
        command.add_argument('--surface', choices=sorted(SURFACES), required=True)
        command.add_argument('--reference', type=Path, required=name == 'register')
        if name == 'discover':
            command.add_argument('--legacy', action='append', type=Path, default=[])
    args = parser.parse_args(argv)
    try:
        index = Index()
        if args.action == 'register':
            result = index.register(args.reference, args.surface)
        else:
            proof, result = index.discover(args.surface, explicit=args.reference, legacy=args.legacy)
        print(json.dumps({'result': 'verified_reference', 'reference': result}, sort_keys=True))
        return 0
    except (ce.EvidenceError, OSError, ValueError) as exc:
        print(json.dumps({'result': 'blocked', 'code': getattr(exc, 'code', 'invalid_input'),
                          'detail': str(exc)}, sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
