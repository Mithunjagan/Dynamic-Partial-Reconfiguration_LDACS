"""Validate an image package before programming the FPGA or opening UART."""
import argparse
import hashlib
import json
from pathlib import Path
from .elf_validation import validate_elf

MODULES = {'hybrid': 0, 'full_pl': 1, 'blank': 2, 'anchor': 3}


def checked_file(directory, name, expected):
    path = (directory / name).resolve()
    if path.parent != directory.resolve():
        raise ValueError('Image must be beside its manifest')
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('Image hash mismatch: ' + name)
    return path


def family(path):
    path = Path(path)
    value = json.loads(path.read_text(encoding='utf-8'))
    static = value.get('schema') == 'ldacs_hybrid_static_image_v1'
    if not static and (value.get('schema') != 'ldacs_dpr_image_family_v1' or
                       value.get('pr_verify_passed') is not True):
        raise ValueError('Unverified or unsupported image family')
    if value.get('part') != 'xc7z010clg400-1':
        raise ValueError('Wrong FPGA part')
    token = value.get('build_token')
    if type(token) is not int or not 0 < token <= 0xffffffff:
        raise ValueError('Invalid build token')
    marker_path = path.parent / 'routed_manifest.json'
    if marker_path.exists():
        current = json.loads(marker_path.read_text(encoding='utf-8'))
        if current.get('build_token') != token or (not static and
                                                 current.get('pr_verify_passed') is not True):
            raise ValueError('Image package is stale or implementation failed')
        if static and (current.get('schema') != 'ldacs_hybrid_static_routed_v1' or
                       current.get('implementation_passed') is not True):
            raise ValueError('Static implementation is incomplete')
    expected_modules = {'hybrid'} if static else set(MODULES)
    if set(value['modules']) != expected_modules:
        raise ValueError('Incomplete image package')
    for name, module in value['modules'].items():
        if module['id'] != MODULES[name]:
            raise ValueError('Incorrect module identity mapping')
        checked_file(path.parent, module['full_file'], module['full_sha256'])
        if not static:
            partial = checked_file(path.parent, module['partial_file'], module['partial_sha256'])
            size = partial.stat().st_size
            if size != module['partial_bytes'] or not 0 < size <= 8 * 1024 * 1024 or size % 4:
                raise ValueError('Partial image size/alignment mismatch')
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--family', type=Path, required=True)
    parser.add_argument('--module', choices=MODULES, required=True)
    parser.add_argument('--elf', type=Path, required=True)
    args = parser.parse_args()
    package = family(args.family / 'images.json')
    marker_path = args.family / 'routed_manifest.json'
    if not marker_path.exists():
        raise ValueError('Boot requires a routed implementation manifest')
    marker = json.loads(marker_path.read_text())
    if marker.get('critical_warnings_passed') is not True:
        raise ValueError('Rebuild with the current critical-warning validation gate')
    validate_elf(args.elf)
    metadata = json.loads(args.elf.with_name('firmware_build.json').read_text())
    if hashlib.sha256(args.elf.read_bytes()).hexdigest() != metadata['elf_sha256']:
        raise ValueError('Firmware ELF does not match its build metadata')
    if metadata['architecture'] != MODULES[args.module]:
        # CPU-only firmware uses blank ID 2.
        raise ValueError('Firmware architecture does not match boot module')
    static = package['schema'] == 'ldacs_hybrid_static_image_v1'
    required=metadata.get('required_static_monitor_version',0)
    if not static and required and package.get('static_monitor_version')!=required:
        raise ValueError('Firmware requires a different static continuity monitor version')
    if args.module == 'hybrid' and static != (metadata.get('platform') == 'static_hybrid'):
        raise ValueError('HYBRID firmware and bitstream topologies differ')
    entry = package['modules'][args.module]
    print(checked_file(args.family, entry['full_file'], entry['full_sha256']))


if __name__ == '__main__':
    main()
