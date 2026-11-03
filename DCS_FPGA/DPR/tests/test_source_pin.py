"""The build token must not silently cover a changed hardware source tree."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from common.source_manifest import snapshot


class Tests(unittest.TestCase):
    def test_rtl_and_constraint_changes_invalidate_source_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'hw/static').mkdir(parents=True)
            (root/'hw/vivado').mkdir(parents=True)
            rtl=root/'hw/static/shell.v';rtl.write_text('module shell; endmodule\n')
            xdc=root/'hw/vivado/floorplan_override.xdc';xdc.write_text('create_pblock receiver\n')
            before=snapshot(root)['hardware_source_sha256']
            rtl.write_text('module shell; wire identity; endmodule\n')
            self.assertNotEqual(before,snapshot(root)['hardware_source_sha256'])
            before=snapshot(root)['hardware_source_sha256'];xdc.write_text('create_pblock another_receiver\n')
            self.assertNotEqual(before,snapshot(root)['hardware_source_sha256'])

    def test_generated_build_files_do_not_change_source_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'hw/static').mkdir(parents=True)
            (root/'hw/static/shell.v').write_text('module shell; endmodule\n')
            before=snapshot(root)
            generated=root/'hw/vivado/build_dpr/project';generated.mkdir(parents=True)
            (generated/'generated.v').write_text('module generated; endmodule\n')
            self.assertEqual(before,snapshot(root))


if __name__=='__main__':
    unittest.main()
