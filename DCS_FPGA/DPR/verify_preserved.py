#!/usr/bin/env python3
"""Verify all pre-existing source files and common DPR shell/module copies."""
import hashlib
import json
import argparse
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--historical', action='store_true', help='Audit the archived 2026-10-29 baseline')
    args = parser.parse_args()
    name = 'preserved_sources_20261029.json' if args.historical else 'preserved_sources.json'
    manifest = json.loads((ROOT / 'DPR' / name).read_text())
    mismatches = []
    for name, expected in manifest.items():
        path = ROOT / name
        if not path.is_file() or digest(path) != expected:
            mismatches.append(name)
    if mismatches:
        raise SystemExit('Baseline mismatches (' + str(len(mismatches)) + '):\n' + '\n'.join(mismatches))
    common = ROOT / 'DPR/FULL_PL'
    for variant in ('HYBRID', 'FULL_PS'):
        other = ROOT / 'DPR' / variant
        for folder in ('static', 'shared', 'rm'):
            for source in (common / 'hw' / folder).rglob('*.v'):
                relative = source.relative_to(common)
                target = other / relative
                if not target.is_file() or digest(source) != digest(target):
                    raise SystemExit('Common DPR hardware differs: ' + str(relative))
    for variant in ('HYBRID', 'FULL_PL', 'FULL_PS'):
        if digest(ROOT / 'DPR' / variant / 'model/ldacs_ref.py') != digest(ROOT / 'model/ldacs_ref.py'):
            raise SystemExit('Reference model differs: ' + variant)
    print(f'PASS: {len(manifest)} files match the selected baseline; DPR shell/modules and reference models match')
if __name__ == '__main__': main()
