"""Static HYBRID must never upload partials or claim a DPR capture."""
import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
import dpr_client as client


class Board:
    def status(self):
        return {'build_token':77, 'module_id':0, 'isolation_reset':0}
    def upload(self, *args):
        raise AssertionError('Static platform attempted an upload')
    def switch(self, *args):
        raise AssertionError('Static platform attempted PCAP switching')


class Tests(unittest.TestCase):
    def setUp(self):
        self.manifest = {'schema':'ldacs_hybrid_static_image_v1', 'build_token':77,
            'modules':{'hybrid':{'id':0, 'full_file':'hybrid.bit', 'full_sha256':'f'*64}}}
        self.capture = {'schema':'ldacs_partition_benchmark_v1', 'architecture':'HYBRID',
                        'artifacts':{}, 'results':[], 'valid':True}

    def test_static_capture_has_no_switches_or_dpr_label(self):
        with patch.object(client, 'family', return_value=self.manifest), \
             patch.object(client.base, 'collect', return_value=copy.deepcopy(self.capture)), \
             patch.object(client.base, 'provenance', return_value={'routed_build':{}}):
            result=client.collect(Board(),Path('images.json'),[],1,0,1,0,91)
        self.assertEqual(result['architecture'],'HYBRID')
        self.assertEqual(result['schema'],'ldacs_partition_benchmark_v1')
        self.assertEqual(result['implementation'],'static_hybrid')
        self.assertNotIn('switches',result)

    def test_static_capture_rejects_switch_requests(self):
        with patch.object(client, 'family', return_value=self.manifest):
            with self.assertRaises(ValueError):
                client.collect(Board(),Path('images.json'),[],1,0,1,3,91)

    def test_static_capture_checks_running_build_token(self):
        self.manifest['build_token']=88
        with patch.object(client, 'family', return_value=self.manifest):
            with self.assertRaises(RuntimeError):
                client.collect(Board(),Path('images.json'),[],1,0,1,0,91)


if __name__ == '__main__':
    unittest.main()
