"""Regression tests for unsafe downloads, stale images and baseline scope."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.elf_validation import validate_elf
from common.image_validation import family


def elf_bytes(overlap=False):
    data = bytearray(272)
    ident = b'\x7fELF\x01\x01\x01' + b'\0' * 9
    struct.pack_into('<16sHHIIIIIHHHHHH', data, 0, ident, 2, 40, 1,
                     0x01000000, 52, 0, 0, 52, 32, 2, 0, 0, 0)
    struct.pack_into('<8I', data, 52, 1, 256, 0x01000000, 0x01000000, 8, 8, 5, 4)
    address = 0x01000000 if overlap else 0x01001000
    struct.pack_into('<8I', data, 84, 1, 264, address, address, 8, 16, 6, 4)
    return data


class Tests(unittest.TestCase):
    def fixture(self, directory):
        modules = {}
        for ident, name in enumerate(('hybrid','full_pl','blank','anchor')):
            full, partial = directory / (name+'.bit'), directory / (name+'.pcap.bin')
            full.write_bytes(b'full-image-fixture')
            partial.write_bytes(bytes.fromhex('ffffffff665599aa00000020'))
            modules[name] = {'id':ident, 'full_file':full.name, 'full_sha256':hashlib.sha256(full.read_bytes()).hexdigest(),
                             'partial_file':partial.name, 'partial_sha256':hashlib.sha256(partial.read_bytes()).hexdigest(),
                             'partial_bytes':partial.stat().st_size}
        manifest = {'schema':'ldacs_dpr_image_family_v1', 'part':'xc7z010clg400-1',
                    'build_token':77, 'pr_verify_passed':True, 'modules':modules}
        (directory/'images.json').write_text(json.dumps(manifest))
        (directory/'routed_manifest.json').write_text(json.dumps({'schema':'ldacs_dfx_routed_v1',
            'pr_verify_passed':True, 'critical_warnings_passed':True, 'build_token':77}))
        elf = directory/'uart_bridge.elf'; elf.write_bytes(elf_bytes())
        (directory/'firmware_build.json').write_text(json.dumps({'architecture':1,
            'elf_sha256':hashlib.sha256(elf.read_bytes()).hexdigest()}))
        return elf

    def preflight(self, directory, elf):
        return subprocess.run([sys.executable, '-B', str(ROOT/'validate_boot.py'), '--family', str(directory),
            '--module','full_pl','--elf',str(elf)], capture_output=True, text=True)

    def test_overlapping_elf_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'image.elf'; p.write_bytes(elf_bytes(True))
            with self.assertRaisesRegex(ValueError, 'Overlapping'): validate_elf(p)

    def test_boot_preflight_accepts_verified_nonoverlapping_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp); elf=self.fixture(directory)
            result=self.preflight(directory,elf)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(Path(result.stdout.strip()),(directory/'full_pl.bit').resolve())

    def test_boot_preflight_rejects_replaced_full_bitstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp); elf=self.fixture(directory)
            (directory/'full_pl.bit').write_bytes(b'replaced')
            self.assertNotEqual(self.preflight(directory,elf).returncode,0)

    def test_boot_preflight_rejects_stale_token_and_critical_warnings(self):
        for change in ({'build_token':88},{'critical_warnings_passed':False}):
            with tempfile.TemporaryDirectory() as tmp:
                directory=Path(tmp); elf=self.fixture(directory)
                path=directory/'routed_manifest.json'; marker=json.loads(path.read_text()); marker.update(change)
                path.write_text(json.dumps(marker))
                self.assertNotEqual(self.preflight(directory,elf).returncode,0)

    def test_boot_preflight_rejects_changed_firmware(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp); elf=self.fixture(directory); elf.write_bytes(elf.read_bytes()+b'changed')
            self.assertNotEqual(self.preflight(directory,elf).returncode,0)

    def test_generated_verilog_is_not_a_preserved_source(self):
        build=ROOT/'FULL_PL/hw/vivado/build'; build.mkdir(parents=True,exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=build,suffix='.v'):
            result=subprocess.run([sys.executable,'-B',str(ROOT/'verify_preserved.py')],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr+result.stdout)

    def test_static_hybrid_package_contains_no_partial_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp);self.fixture(directory)
            path=directory/'images.json';package=json.loads(path.read_text())
            package.update(schema='ldacs_hybrid_static_image_v1',modules={'hybrid':package['modules']['hybrid']})
            package['modules']['hybrid']={k:v for k,v in package['modules']['hybrid'].items() if not k.startswith('partial_')}
            path.write_text(json.dumps(package))
            (directory/'routed_manifest.json').write_text(json.dumps({'schema':'ldacs_hybrid_static_routed_v1',
                'build_token':77,'implementation_passed':True,'critical_warnings_passed':True}))
            self.assertEqual(family(path)['schema'],'ldacs_hybrid_static_image_v1')


if __name__ == '__main__':
    unittest.main()
