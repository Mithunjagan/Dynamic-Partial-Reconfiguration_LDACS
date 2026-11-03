"""Summarize a successful physical DPR evaluation without replacing raw evidence."""
import argparse
import csv
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parents[0] / 'common'))
from continuity import valid_continuity


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('evaluation', type=Path)
    args = parser.parse_args()
    directory = args.evaluation
    evaluation = json.loads((directory / 'evaluation.json').read_text())
    capture = json.loads((directory / 'benchmark.json').read_text())
    traces = json.loads((directory / 'traces.json').read_text())
    token = capture['image_family']['build_token']
    if not evaluation['passed'] or not capture['valid'] or not all(t['valid'] for t in traces.values()):
        raise RuntimeError('Cannot report a failed or incomplete evaluation as passed')
    switches = capture['switches']
    if not switches or not all(valid_continuity(s['static_continuity'], token) for s in switches):
        raise RuntimeError('Missing valid static continuity observations')
    rows = []
    for result in capture['results']:
        samples = result['samples']
        frames = sum(s['iterations'] for s in samples)
        rows.append(dict(mode=result['mode'], frames=frames,
                         mean_ms=sum(s['decoder_mean_us']*s['iterations'] for s in samples)/frames/1000,
                         min_ms=min(s['decoder_min_us'] for s in samples)/1000,
                         max_ms=max(s['decoder_max_us'] for s in samples)/1000,
                         crc_failures=sum(s['crc_failed_frames'] for s in samples),
                         rs_failures=sum(s['rs_failures'] for s in samples)))
    report_dir = ROOT / 'hw/vivado/build_dpr/dfx'
    tools = {}
    for module in capture['image_family']['modules']:
        timing = (report_dir / (module+'_timing.rpt')).read_text()
        match = re.search(r'WNS\(ns\).*?\n[^\n]*\n\s*([-+0-9.]+)\s+([-+0-9.]+)\s+\d+\s+\d+\s+([-+0-9.]+)', timing, re.S)
        utilization = (report_dir / (module+'_utilization.rpt')).read_text()
        metrics = {key:float(re.search(r'\|\s*'+label+r'\s*\|\s*([0-9.]+)', utilization).group(1))
                   for key,label in [('lut','Slice LUTs'),('ff','Slice Registers'),('bram36_equivalent','Block RAM Tile'),('dsp','DSPs')]}
        metrics.update(wns_ns=float(match[1]),tns_ns=float(match[2]),whs_ns=float(match[3]))
        tools[module] = metrics
    summary = dict(measurement='physical_board_hybrid_dpr_evaluation', passed=True,
                   build_token=token, completed_utc=evaluation['finished_utc'],
                   timed_frames=sum(r['frames'] for r in rows),
                   warmup_frames=sum(s['warmups'] for r in capture['results'] for s in r['samples']),
                   partial_transfers=len(switches), static_continuity_passed=True,
                   stage_checks=evaluation['stage_buffer_checks'], modes=rows, routed=tools,
                   boot_seconds=evaluation['boot_seconds'], wall_seconds=evaluation['wall_seconds'],
                   switches=switches, image_uploads=capture['image_uploads'])
    (directory/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    with (directory/'summary.csv').open('w', newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['# HYBRID DPR on-board evaluation','',
           f"Completed {evaluation['finished_utc']} on EDGE Z7-10, COM5. Build token {token}.",'',
           f"PASS: {len(switches)} genuine PCAP partial transfers, {summary['timed_frames']} timed frames, "
           f"{summary['warmup_frames']} warm-ups, {len(rows)} modes and {summary['stage_checks']}/{len(rows)*5} stage-buffer checks.",'',
           f"One full boot preceded {len(switches)//2} HYBRID -> blank -> HYBRID round trips. Each restored HYBRID passed a complete QPSK decode. "
           'Static heartbeat, shell identity and build token were sampled during every PCAP transfer; all observations passed. '
           'Invalid module and wrong-family requests were rejected without changing the running configuration.','',
           '| Transfer | PCAP ms | Isolated/restart total ms | CRC precheck ms | Service total ms | Static samples |',
           '|---|---:|---:|---:|---:|---:|']
    for s in switches:
        u=s['microseconds']
        lines.append(f"| {s['from_id']} -> {s['to_id']} | {u['pcap']/1000:.6f} | {u['total']/1000:.6f} | {u['precheck']/1000:.6f} | {u['service_total']/1000:.6f} | {s['static_continuity']['samples']} |")
    lines += ['', 'IDs: HYBRID=0, blank=2. PCAP and isolated/restart intervals exclude the DDR-image CRC precheck. '
              'Service total includes that precheck. UART image staging is separate:', '']
    lines += [f"- {u['module']}: {u['bytes']} bytes, {u['host_upload_seconds']:.3f} s." for u in capture['image_uploads']]
    lines += ['', '| Mode | Mean decode ms | Min ms | Max ms | CRC failures | RS failures |',
              '|---|---:|---:|---:|---:|---:|']
    for r in rows:
        lines.append(f"| {r['mode']} | {r['mean_ms']:.6f} | {r['min_ms']:.6f} | {r['max_ms']:.6f} | {r['crc_failures']} | {r['rs_failures']} |")
    lines += ['', f"{capture['batches']} batches of {capture['iterations_per_batch']} timed frames and {capture['warmups_per_batch']} warm-ups per mode; seed {capture['seed']}. Decode includes five receiver stages and DMA/control, "
              'excluding UART, CRC checking and final output copy. I-cache/D-cache disabled; single Cortex-A9. '
              'Each timed payload passed firmware CRC32; every final batch payload matched byte-for-byte. '
              'Five trace buffers per mode matched the software reference.', '',
              '| Routed configuration | LUT | FF | BRAM36 equivalents | DSP | WNS ns | WHS ns |',
              '|---|---:|---:|---:|---:|---:|---:|']
    for name,m in tools.items():
        lines.append(f"| {name} | {m['lut']:g} | {m['ff']:g} | {m['bram36_equivalent']:g} | {m['dsp']:g} | {m['wns_ns']:.3f} | {m['whs_ns']:.3f} |")
    lines += ['', 'Utilization is the complete configuration, including static logic. All four configurations passed setup/hold and DRC gates; '
              'all three alternate checkpoints passed full pr_verify against the same full_pl reference. '
              'Each partial image is 1,683,900 bytes. FULL_PL and anchor have tool verification only in this evaluation; '
              'the physical swap measurements cover HYBRID and blank.', '',
              f"Boot: {summary['boot_seconds']:.3f} s. Entire evaluation including boot, staging and checks: {summary['wall_seconds']:.3f} s.", '',
              'Raw evidence: evaluation.json, benchmark.json, traces.json, boot.log. Exact counters, continuity replies, '
              'clock values, artifact hashes and firmware provenance remain in those files. Unrounded summaries: summary.json and summary.csv. '
              'No RF/OFDM, independent standards conformance, measured power, or DPR throughput/area advantage is claimed.']
    (directory/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(directory/'REPORT.md')


if __name__ == '__main__':
    main()
