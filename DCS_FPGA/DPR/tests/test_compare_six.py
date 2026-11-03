"""Six-way comparison fixtures; no records are saved as real hardware data."""
import copy
import importlib.util
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'DPR'))
import compare_six
spec = importlib.util.spec_from_file_location('protocol_fixtures', ROOT / 'BENCHMARKS/test_protocol.py')
fixtures = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixtures)

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): fixtures.ProtocolTests.setUpClass()
    def documents(self):
        static = fixtures.ProtocolTests().fixtures()
        dynamic = copy.deepcopy(static)
        for arch, d in enumerate(dynamic):
            d['architecture'] = 'DPR_' + d['architecture']; d['schema'] = 'ldacs_dpr_benchmark_v1'
            d['image_family'] = {'build_token': 77, 'pr_verify_passed': True}
            alternate = 3 if arch == 2 else 2
            d['switches'] = [
                {'measurement': 'real_board_pcap_partial_switch', 'build_token': 77, 'from_id': arch,
                 'to_id': alternate, 'microseconds': {'total': 100, 'service_total': 120}},
                {'measurement': 'real_board_pcap_partial_switch', 'build_token': 77, 'from_id': alternate,
                 'to_id': arch, 'microseconds': {'total': 200, 'service_total': 230}, 'post_switch_decode': {'valid': True}}]
            for row in d['results']:
                for sample in row['samples']:
                    sample['execution_platform'] = d['architecture']
                    sample['raw_response_header_hex'] = '44444252' + sample['raw_response_header_hex'][8:]
            for index, switch in enumerate(d['switches']):
                total = switch['microseconds']['total']
                service = switch['microseconds']['service_total']
                switch.update(module={0:'hybrid',1:'full_pl',2:'blank',3:'anchor'}[switch['to_id']],
                              global_timer_hz=1000000, generation=index+2, devcfg_interrupts=0x3000)
                switch['ticks'] = {'isolation':10, 'pcap':total-30, 'restart':10, 'total':total,
                                   'unavailable':total-10, 'precheck':10, 'service_total':service}
                switch['microseconds'] = dict(switch['ticks'])
            d['switches'][1]['post_switch_decode'] = copy.deepcopy(d['results'][0]['samples'][0])
        return static + dynamic
    def test_complete_six_way_comparison(self):
        rows = compare_six.compare(self.documents())
        self.assertEqual(len(rows), 6)
        self.assertTrue(all(r['switch_roundtrip_mean_us'] == 350 for r in rows if r['architecture'].startswith('DPR_')))
    def test_static_response_cannot_be_relabelled(self):
        docs = self.documents(); docs[3]['results'][0]['samples'][0]['raw_response_header_hex'] = '4c444252'
        with self.assertRaises(ValueError): compare_six.compare(docs)
    def test_switch_correctness_required(self):
        docs = self.documents(); docs[3]['switches'][1]['post_switch_decode']['valid'] = False
        with self.assertRaises(ValueError): compare_six.compare(docs)
    def test_all_six_configurations_required(self):
        with self.assertRaises(ValueError): compare_six.compare(self.documents()[:-1])
    def test_invalid_transitions_rejected(self):
        docs = self.documents(); docs[3]['switches'][0].update(from_id=99, to_id=99)
        with self.assertRaises(ValueError): compare_six.compare(docs)
    def test_negative_nonfinite_and_inconsistent_times_rejected(self):
        for value in (-1, float('nan'), float('inf'), 123):
            docs = self.documents(); docs[3]['switches'][0]['microseconds']['total'] = value
            with self.assertRaises(ValueError): compare_six.compare(docs)
    def test_switch_generation_and_flags_checked(self):
        for change in ({'generation':44}, {'devcfg_interrupts':0x40}):
            docs = self.documents(); docs[3]['switches'][1].update(change)
            with self.assertRaises(ValueError): compare_six.compare(docs)
    def test_markdown_contains_every_csv_field(self):
        rows = compare_six.compare(self.documents())
        for row in rows: row['amortized_decoder_plus_switch_us'] = 12.5
        report = compare_six.markdown_report(rows)
        for key in rows[0]: self.assertIn(key, report)
if __name__ == '__main__': unittest.main()
