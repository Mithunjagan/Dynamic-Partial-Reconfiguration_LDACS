#!/usr/bin/env python3
"""Package only a successfully routed/pr_verify-checked DFX image family."""
import argparse
import sys
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from common.source_manifest import snapshot
MODULES = {'viterbi': 0, 'rs': 1}
def sha(data): return hashlib.sha256(data).hexdigest()
def pcap_words(data):
    if not data or len(data) % 4: raise ValueError('Raw Vivado .bin must contain complete 32-bit words')
    big = data.find(bytes.fromhex('aa995566'), 0, 1024)
    little = data.find(bytes.fromhex('665599aa'), 0, 1024)
    if big >= 0 and big % 4 == 0:
        offset, order = big, 'big'
        result = b''.join(data[i:i+4][::-1] for i in range(0, len(data), 4))
    elif little >= 0 and little % 4 == 0:
        offset, order, result = little, 'little', data
    else: raise ValueError('No aligned configuration sync word; use Vivado raw .bin, not a .bit header')
    allowed = {0xffffffff, 0, 0x000000bb, 0x11220044}
    if any(int.from_bytes(data[i:i+4], order) not in allowed for i in range(0, offset, 4)):
        raise ValueError('Unexpected preamble: container .bit headers must not be sent to PCAP')
    return result
def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',type=Path,default=ROOT/'hw/vivado/build_dpr/dfx');args=parser.parse_args()
    out=args.directory
    marker = json.loads((out / 'routed_manifest.json').read_text())
    if marker.get('critical_warnings_passed') is not True:
        raise RuntimeError('Rebuild with the current critical-warning validation gate')
    if marker.get('schema') == 'ldacs_hybrid_static_routed_v1':
        if marker.get('implementation_passed') is not True:
            raise RuntimeError('Static HYBRID implementation is incomplete')
        full = out / 'hybrid.bit'
        family = {'schema': 'ldacs_hybrid_static_image_v1', 'topology': 'static_hybrid',
                  'part': marker['part'], 'build_token': marker['build_token'],
                  'modules': {'hybrid': {'id': 0, 'full_file': full.name,
                    'full_sha256': sha(full.read_bytes()),
                    'routed_checkpoint_sha256': sha((out / 'hybrid_routed.dcp').read_bytes())}}}
        (out / 'images.json').write_text(json.dumps(family, indent=2) + '\n', encoding='utf-8')
        print('Packaged static HYBRID image:', out / 'images.json')
        return
    if marker.get('schema') != 'ldacs_dfx_routed_v1' or not marker.get('pr_verify_passed'):
        raise RuntimeError('No completed, verified DFX implementation')
    if marker.get('hardware_source_sha256')!=snapshot(ROOT)['hardware_source_sha256']:
        raise RuntimeError('Hardware sources changed since the verified implementation')
    static = (out / 'static_locked.dcp').read_bytes()
    family = {'schema': 'ldacs_stage_dpr_image_family_v1', 'build_token': marker['build_token'],
              'part': marker['part'], 'rp_cell': marker['rp_cell'], 'pr_verify_passed': True,
              'static_checkpoint_sha256': sha(static), 'static_monitor_version':marker.get('static_monitor_version',0),
              'hardware_source_sha256':marker.get('hardware_source_sha256'), 'modules': {}}
    for module, ident in MODULES.items():
        partial = out / f'{module}_partial.bin'
        data = pcap_words(partial.read_bytes())
        if len(data) > 8 * 1024 * 1024: raise ValueError('Image exceeds one firmware cache slot')
        packaged = out / f'{module}.pcap.bin'
        packaged.write_bytes(data)
        full = out / f'{module}.bit'
        family['modules'][module] = {'id': ident, 'partial_file': packaged.name,
            'partial_bytes': len(data), 'partial_sha256': sha(data),
            'full_file': full.name, 'full_sha256': sha(full.read_bytes()),
            'routed_checkpoint_sha256': sha((out / f'{module}_routed.dcp').read_bytes())}
    (out / 'images.json').write_text(json.dumps(family, indent=2) + '\n', encoding='utf-8')
    print('Packaged same-static image family:', out / 'images.json')
if __name__ == '__main__': main()
