#!/usr/bin/env python3
"""Compare three static and three DPR board captures without inventing missing data."""
import argparse
import copy
import csv
import importlib.util
import json
import math
from common.continuity import valid_continuity
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('static_compare', ROOT / 'BENCHMARKS/compare.py')
static_compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(static_compare)

def validate_switches(document):
    switches = document['switches']
    target = {'DPR_HYBRID': 0, 'DPR_FULL_PL': 1, 'DPR_FULL_PS': 2}[document['architecture']]
    alternate = 3 if target == 2 else 2
    if not switches or len(switches) % 2:
        raise ValueError('Incomplete switch round trip')
    previous_generation = None
    for index, switch in enumerate(switches):
        expected = (target, alternate) if index % 2 == 0 else (alternate, target)
        if (switch.get('from_id'), switch.get('to_id')) != expected:
            raise ValueError('Incorrect switch transition sequence')
        if switch.get('module') != {0:'hybrid', 1:'full_pl', 2:'blank', 3:'anchor'}[expected[1]]:
            raise ValueError('Switch module name and identity differ')
        hz = switch.get('global_timer_hz')
        generation = switch.get('generation')
        if type(hz) is not int or not 0 < hz <= 0xffffffff or type(generation) is not int or not 0 <= generation <= 0xffffffff:
            raise ValueError('Missing switch clock or generation')
        if previous_generation is not None and generation != ((previous_generation + 1) & 0xffffffff):
            raise ValueError('Nonconsecutive switch generations')
        previous_generation = generation
        ticks, micros = switch.get('ticks', {}), switch.get('microseconds', {})
        for key in ('isolation','pcap','restart','total','unavailable','precheck','service_total'):
            count, value = ticks.get(key), micros.get(key)
            if type(count) is not int or not 0 < count <= 0xffffffffffffffff or type(value) not in (float, int) or not math.isfinite(value) or value <= 0:
                raise ValueError('Invalid switch duration')
            if not math.isclose(value, count * 1e6 / hz, rel_tol=1e-9, abs_tol=1e-6):
                raise ValueError('Switch ticks and microseconds disagree')
        if (ticks['total'] < ticks['isolation'] + ticks['pcap'] + ticks['restart'] or
            ticks['unavailable'] != ticks['total'] - ticks['isolation'] or
            ticks['service_total'] < ticks['total'] + ticks['precheck']):
            raise ValueError('Inconsistent switch timing boundaries')
        flags = switch.get('devcfg_interrupts', 0)
        if type(flags) is not int or not 0 <= flags <= 0xffffffff or flags & 0x3000 != 0x3000 or flags & 0x00f4c840:
            raise ValueError('PCAP did not complete without errors')
        if document['image_family'].get('static_monitor_version')==1:
            continuity=switch.get('static_continuity',{})
            if continuity.get('measurement')!='real_board_static_continuity_during_pcap' or not valid_continuity(continuity,document['image_family']['build_token']):
                raise ValueError('Static continuity was not verified during PCAP')
        if index % 2:
            check = switch.get('post_switch_decode', {})
            if (not check.get('valid') or check.get('measurement') != 'real_board_uart_response' or
                check.get('architecture') != document['architecture'][4:] or
                not check.get('last_output_matches') or check.get('crc_failed_frames') != 0 or
                check.get('rs_failures') != 0 or
                not check.get('raw_response_header_hex', '').startswith('44444252')):
                raise ValueError('Post-switch decoding was not verified')


def compare(documents):
    names = {'HYBRID', 'FULL_PL', 'FULL_PS', 'DPR_HYBRID', 'DPR_FULL_PL', 'DPR_FULL_PS'}
    if len(documents) != 6 or {d['architecture'] for d in documents} != names:
        raise ValueError('Supply exactly one successful capture for each of the six configurations')
    static = [d for d in documents if not d['architecture'].startswith('DPR_')]
    dynamic = [d for d in documents if d['architecture'].startswith('DPR_')]
    for d in dynamic:
        if d.get('schema') != 'ldacs_dpr_benchmark_v1' or not d.get('switches'):
            raise ValueError('DPR capture must contain actual partial-switch measurements')
        if not d['image_family'].get('pr_verify_passed'): raise ValueError('Unverified image family')
        validate_switches(d)
        for t in d['switches']:
            if t.get('measurement') != 'real_board_pcap_partial_switch' or t['build_token'] != d['image_family']['build_token']:
                raise ValueError('Invalid partial-switch provenance')
        for r in d['results']:
            for s in r['samples']:
                if s.get('execution_platform') != d['architecture'] or not s['raw_response_header_hex'].startswith('44444252'):
                    raise ValueError('Static response cannot be labeled as a DPR decoder measurement')
        for t in d['switches'][1::2]:
            if not t.get('post_switch_decode', {}).get('valid'): raise ValueError('Post-switch decoding was not verified')
    # Validate each triple with the existing shared frame/clock/compiler checks.
    normalized = copy.deepcopy(dynamic)
    for d in normalized:
        d['architecture'] = d['architecture'][4:]
        d['schema'] = 'ldacs_partition_benchmark_v1'
    rows = static_compare.compare(static)
    drows = static_compare.compare(normalized)
    # Also validate every static/DPR pair against the same reference triple.
    for d in normalized:
        triple = [d if s['architecture'] == d['architecture'] else s for s in static]
        static_compare.compare(triple)
    for r in drows: r['architecture'] = 'DPR_' + r['architecture']
    rows += drows
    for row in rows:
        ps = next(r for r in rows if r['mode'] == row['mode'] and r['architecture'] == 'FULL_PS')
        row['speedup_vs_static_full_ps'] = ps['decoder_mean_us'] / row['decoder_mean_us']
        row['switch_mean_us'] = None
        row['switch_roundtrip_mean_us'] = None
        row['switch_service_mean_us'] = None
        row['static_pair_decoder_overhead_pct'] = None
        if row['architecture'].startswith('DPR_'):
            d = next(d for d in dynamic if d['architecture'] == row['architecture'])
            switches = d['switches']
            if len(switches) % 2: raise ValueError('Incomplete switch round trip')
            total = sum(t['microseconds']['total'] for t in switches)
            row['switch_mean_us'] = total / len(switches)
            row['switch_service_mean_us'] = sum(t['microseconds']['service_total'] for t in switches) / len(switches)
            row['switch_roundtrip_mean_us'] = sum(t['microseconds']['service_total'] for t in switches) / (len(switches) // 2)
            pair = next(r for r in rows if r['mode'] == row['mode'] and r['architecture'] == row['architecture'][4:])
            row['static_pair_decoder_overhead_pct'] = (row['decoder_mean_us'] / pair['decoder_mean_us'] - 1) * 100
    return rows

def markdown_report(rows):
    columns = list(rows[0])
    report = '| ' + ' | '.join(columns) + ' |\n'
    report += '|' + '|'.join('---' for _ in columns) + '|\n'
    for row in rows:
        values = ['' if row[key] is None else format(row[key], '.6f') if isinstance(row[key], float)
                  else str(row[key]).replace('|', '\\|') for key in columns]
        report += '| ' + ' | '.join(values) + ' |\n'
    return report + '\nSwitching is measured separately. Amortization is a derived workload scenario.\n'


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('captures', nargs=6, type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--frames-per-switch-roundtrip', type=int)
    a = p.parse_args()
    rows = compare([json.loads(p.read_text(encoding='utf-8')) for p in a.captures])
    if a.frames_per_switch_roundtrip is not None:
        if a.frames_per_switch_roundtrip <= 0: p.error('Frame count must be positive')
        for row in rows:
            row['amortized_decoder_plus_switch_us'] = row['decoder_mean_us'] + (row['switch_roundtrip_mean_us'] or 0) / a.frames_per_switch_roundtrip
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    report = markdown_report(rows)
    a.output.with_suffix('.md').write_text(report, encoding='utf-8')
    print('Saved six-way comparison:', a.output)
if __name__ == '__main__': main()
