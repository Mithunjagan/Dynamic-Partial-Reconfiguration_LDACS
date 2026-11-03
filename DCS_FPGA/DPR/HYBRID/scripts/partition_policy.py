"""Reproduce the HYBRID partition decision from saved routed/board evidence.

Resource counts come from the routed DPR HYBRID configuration at 50 MHz.
Latencies come from the static HYBRID board sweep at 71.428570 MHz; they are
reported as observed, without rescaling or treating the two builds as identical.
PCAP timings describe the measured whole-slot FULL_PL/blank images, not an
unbuilt per-stage partial image. No per-stage reconfiguration speedup is claimed.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT.parents[1]


def analyze():
    hierarchy = ROOT / 'FULL_PL/hw/vivado/build/dfx/hybrid_hierarchy.rpt'
    sweep = WORKSPACE / 'hardware_live/captures/api_verification_final.json'
    dpr = WORKSPACE / 'hardware_live/captures/dpr_final_evidence.json'
    rows = {}
    instances = {'u_vit':'viterbi', 'u_b2b':'bit_packing', 'u_deint':'block_deinterleaver',
                 'u_rs':'reed_solomon', 'dma':'axi_dma', 'rst_ps7_71M':'clock_reset',
                 'axi_mem_intercon':'axi_memory_interconnect', 'ps7_axi_periph':'axi_control_interconnect'}
    for line in hierarchy.read_text().splitlines():
        cells = [s.strip() for s in line.split('|')[1:-1]]
        if cells and cells[0] == '(inst)' and cells[1].endswith('dpr_shell'):
            cells[0] = 'control_shell'; instances['control_shell'] = 'control_shell'
        if cells and cells[0] == '(core)' and cells[1] == 'hybrid_core':
            cells[0] = 'decoder_control'; instances['decoder_control'] = 'decoder_control'
        if cells and cells[0] in instances:
            rows[instances[cells[0]]] = {'placement':'Static', 'lut':int(cells[4]),
                'ff':int(cells[8]), 'ramb36':int(cells[9]), 'ramb18':int(cells[10]), 'dsp':int(cells[11])}
    observations = [r for r in json.loads(sweep.read_text())['results'] if r['architecture']=='HYBRID']
    if len(observations) != 8 or not all(r['valid'] for r in observations):
        raise ValueError('Expected eight successful HYBRID mode observations')
    for stage in ('viterbi','block_deinterleaver','reed_solomon','helical','derandomizer'):
        samples = [r['raw_benchmark']['stage_measurements'][stage]['mean_us'] for r in observations]
        rows.setdefault(stage, {'placement':'Static', 'domain':'PS', 'lut':0, 'ff':0,
                               'ramb36':0, 'ramb18':0, 'dsp':0})
        rows[stage]['observed_min_us'] = min(samples)
        rows[stage]['observed_max_us'] = max(samples)
    transitions = json.loads(dpr.read_text())['switches']
    return {'schema':'ldacs_hybrid_partition_policy_v1', 'default_topology':'static_hybrid',
        'eligible_rms':[], 'blocks':rows,
        'decision':'All decoder stages are needed by every frame and use a streaming pipeline. No alternate time-multiplexed workload or measured per-stage partial images demonstrate an area/latency benefit. High resource use alone does not qualify a stage as an RM.',
        'resource_clock_hz':50000000, 'latency_clock_hz':71428570,
        'observed_whole_slot_pcap_us':[s['microseconds']['pcap'] for s in transitions],
        'observed_whole_slot_service_us':[s['microseconds']['service_total'] for s in transitions],
        'sources':{str(p.relative_to(WORKSPACE)):hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in (hierarchy,sweep,dpr)}}


def main():
    policy = analyze()
    path = ROOT / 'HYBRID/partition_policy_static_baseline.json'
    path.write_text(json.dumps(policy, indent=2)+'\n')
    print(path)


if __name__ == '__main__':
    main()
