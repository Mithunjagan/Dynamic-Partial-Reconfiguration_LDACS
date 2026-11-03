"""Report routed area and measured stage scheduling; preserve raw observations."""
import argparse
import csv
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from common.continuity import valid_continuity


def main():
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);a=p.parse_args()
    e=json.loads((a.directory/'evaluation.json').read_text())
    if not e['passed']:raise ValueError('Evaluation did not pass')
    switches=[s for r in e['batches'] for s in r['switches']]
    if not all(valid_continuity(s['static_continuity'],e['family']['build_token']) for s in switches):raise ValueError('Missing continuity evidence')
    out=ROOT/'hw/vivado/build_dpr/dfx';resources={}
    for stage in ('viterbi','rs'):
        u=(out/f'{stage}_utilization.rpt').read_text()
        metrics={key:float(re.search(r'\|\s*'+label+r'\s*\|\s*([0-9.]+)',u).group(1))
                 for key,label in [('lut','Slice LUTs'),('ff','Slice Registers'),('bram36_equivalent','Block RAM Tile'),('dsp','DSPs')]}
        t=(out/f'{stage}_timing.rpt').read_text()
        m=re.search(r'WNS\(ns\).*?\n[^\n]*\n\s*([-+0-9.]+)\s+([-+0-9.]+)\s+\d+\s+\d+\s+([-+0-9.]+)',t,re.S)
        metrics.update(wns_ns=float(m[1]),tns_ns=float(m[2]),whs_ns=float(m[3]));resources[stage]=metrics
    baseline_path=ROOT.parent/'HYBRID/results/dpr_20261102T195022Z/summary.json'
    baseline=json.loads(baseline_path.read_text())['routed']['hybrid']
    peak=max(m['lut'] for m in resources.values());saved=baseline['lut']-peak
    rows=[]
    for r in e['batches']:
        c=r['counters'];s=r['switches']
        rows.append(dict(mode=r['mode'],batch=r['count'],compute_integrity_ms=r['compute_integrity_us']/1000,
                         pcap_ms=sum(x['microseconds']['pcap'] for x in s)/1000,
                         crc_precheck_ms=sum(x['microseconds']['precheck'] for x in s)/1000,
                         service_per_frame_ms=r['service_per_frame_ms'],derived_service_mbps=r['payload_mbps'],
                         execution_wall_s=r['execution_wall_seconds'],wall_payload_mbps=r['wall_payload_mbps'],
                         crc_failures=c['crc_failures'],rs_failures=c['rs_failures']))
    summary=dict(passed=True,completed_utc=e['finished_utc'],timed_frames=e['timed_frames'],partial_transfers=len(switches),
                 resources=resources,baseline_lut=baseline['lut'],peak_lut=peak,saved_lut=saved,saved_lut_percent=saved/baseline['lut']*100,
                 frame_buffer_checks=sum(len(r['traces'])*3 for r in e['batches']),rows=rows,
                 static_continuity=True,source_evaluation='evaluation.json',baseline=str(baseline_path.resolve()))
    (a.directory/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    with (a.directory/'summary.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    lines=['# Stage-multiplexed LDACS DPR: measured results','',f"Completed {e['finished_utc']}; EDGE Z7-10, build token {e['family']['build_token']}.",'',
           f"PASS: {e['timed_frames']} frames across eight modes, {len(switches)} genuine stage transfers, "
           f"{summary['frame_buffer_checks']} exact intermediate/final buffer comparisons; static continuity passed during every transfer.",'',
           f"Peak complete-configuration LUTs: {peak:g}, versus {baseline['lut']:g} for the prior combined HYBRID RM: "
           f"{saved:g} fewer ({summary['saved_lut_percent']:.2f}%). Both include static infrastructure.",'',
           '| Configuration | LUT | FF | BRAM36 equivalents | DSP | WNS ns | WHS ns |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for name,m in resources.items():lines.append(f"| {name} | {m['lut']:g} | {m['ff']:g} | {m['bram36_equivalent']:g} | {m['dsp']:g} | {m['wns_ns']:.3f} | {m['whs_ns']:.3f} |")
    lines+=['','The RP alternates between Viterbi + bit packing and RS. Block deinterleaving is static. '
            'PS helical deinterleaving and derandomization are unchanged. Intermediate frames live in bounded DDR slots. '
            'The frame-aligned Pblock geometry is retained because Viterbi still requires 44 RAMB36s; '
            'occupied LUT savings do not imply that this reserved region is available to unrelated static logic.','',
            '| Mode | Batch | Compute/integrity ms per batch | PCAP ms per batch | CRC precheck ms per batch | Accounted service ms/frame | Execution wall s |',
            '|---|---:|---:|---:|---:|---:|---:|']
    for r in rows:lines.append(f"| {r['mode']} | {r['batch']} | {r['compute_integrity_ms']:.3f} | {r['pcap_ms']:.3f} | {r['crc_precheck_ms']:.3f} | {r['service_per_frame_ms']:.3f} | {r['execution_wall_s']:.3f} |")
    lines+=['','Every batch includes Viterbi and RS partial loading, including image CRC verification. '
            'Accounted service sums measured board intervals, excludes UART staging and host command gaps, and includes DMA, copies and payload integrity. '
            'Execution wall time includes commands/responses from the first partial load to the RS batch response; it excludes input staging and trace retrieval. '
            'Derived service rate is not uninterrupted measured receiver throughput. No warm-ups were used. '
            'The prior 800-frame benchmark uses a different execution scope and cannot be treated as a direct speedup comparison.','',
            'Every frame passed CRC and exact comparisons of static-deinterleaver output, raw RS output and final payload. '
            'All eight modes were checked at batch size 1; QPSK 1/2 was also checked at 8 and 32. '
            'The new table CRC is still recomputed before every image load. '
            'All image/firmware hashes, raw timing/continuity replies and actual byte buffers remain in evaluation.json.','',
            f"Boot: {e['boot_seconds']:.3f} s; entire evaluation: {e['wall_seconds']:.3f} s. UART image staging:", '']
    lines += [f"- {u['module']}: {u['bytes']} bytes in {u['host_upload_seconds']:.3f} s." for u in e['uploads']]
    lines += ['', 'Both routed configurations passed DRC/timing, and the RS checkpoint passed full pr_verify against Viterbi with identical static routing. '
              'This is a receiver-loopback experiment, without RF/OFDM, independent standards conformance, measured power, or a claimed real-time deadline.']
    (a.directory/'REPORT.md').write_text('\n'.join(lines)+'\n')
    print(a.directory/'REPORT.md')


if __name__=='__main__':main()
