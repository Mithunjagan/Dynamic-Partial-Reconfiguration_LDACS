"""Pin a project token to its hardware sources before a DFX family is built."""
import argparse
import hashlib
import json
from pathlib import Path


def snapshot(root):
    files = {}
    for folder in ('hw/static', 'hw/shared', 'hw/rm', 'hw/vivado', 'board_details'):
        for path in (root / folder).rglob('*'):
            relative = path.relative_to(root)
            if any(p.startswith('build') or p == 'hd_visual' for p in relative.parts[:-1]):
                continue
            if path.is_file() and path.suffix in ('.v', '.xdc', '.tcl', '.xml'):
                files[relative.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    return {'hardware_source_sha256': digest, 'files': files}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('operation', choices=('record', 'check'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--token', type=int)
    args = parser.parse_args()
    current = snapshot(args.root.resolve())
    if args.operation == 'record':
        if not args.token:
            parser.error('record requires a nonzero build token')
        current['build_token'] = args.token
        args.output.write_text(json.dumps(current, indent=2) + '\n')
        args.output.with_suffix('.sha256').write_text(current['hardware_source_sha256']+'\n')
    else:
        saved = json.loads(args.output.read_text())
        if saved['files'] != current['files']:
            raise RuntimeError('Hardware sources changed: recreate the project for a fresh build token')
    print(current['hardware_source_sha256'])


if __name__ == '__main__':
    main()
