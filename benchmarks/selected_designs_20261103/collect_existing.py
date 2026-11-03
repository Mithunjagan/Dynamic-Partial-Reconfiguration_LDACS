"""Consolidate existing physical evidence for exactly four selected designs.

Offline only: no board, serial, JTAG, simulation, or benchmark execution.
"""
import csv
import hashlib
import json
from pathlib import Path
import re
import statistics
import struct

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD = ROOT/'hardware_live/captures/api_verification_final.json'
NEW = ROOT/'benchmarks/physical_20261103/static/measurement.json'
STAGE = ROOT/'DCS_FPGA/DPR/STAGE_DPR/results/onboard_20261103T051524Z'
RESPONSE = struct.Struct('<4sBBHHHIIIII9Q')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def csv_file(name, rows):
    with (OUT/name).open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    old = json.loads(OLD.read_text())
    new = json.loads(NEW.read_text())
    stage = json.loads((STAGE/'evaluation.json').read_text())
    stage_summary = json.loads((STAGE/'summary.json').read_text())
    family_path = ROOT/'DCS_FPGA/DPR/STAGE_DPR/hw/vivado/build_dpr/dfx/images.json'
    family = json.loads(family_path.read_text())
    require(old['complete'] and stage['passed'], 'Incomplete selected source')
    require(stage['family'] == family, 'Stage family differs from current packaged family')
    require(sha(ROOT/'DCS_FPGA/DPR/STAGE_DPR/sw/dpr/uart_bridge.elf') == stage['firmware']['elf_sha256'], 'Stage firmware changed')
    for entry in family['modules'].values():
        require(sha(family_path.parent/entry['partial_file']) == entry['partial_sha256'], 'Stage partial image changed')
        require(sha(family_path.parent/entry['full_file']) == entry['full_sha256'], 'Stage full image changed')
    decoder, stages, resources, e2e, modem, audits = [], [], [], [], [], []
    sources = [OLD,NEW,STAGE/'evaluation.json',STAGE/'summary.json',family_path]
    for mode, arch_id in (('PS',2),('PL',1),('HYBRID',0)):
        archived = [r for r in old['results'] if r['mode']==mode]
        require(len(archived)==8, 'Missing coding profile')
        elf = ROOT/'hardware_live/build'/mode/'uart_bridge.elf'
        firmware_hash = sha(elf)
        sources += [elf.with_name('firmware_build.json')]
        require(all(r['firmware_sha256']==firmware_hash for r in archived), 'Saved firmware identity mismatch')
        if mode=='PS':
            profiles = [(r['coding'],r['payload_bytes'],[r['raw_benchmark']],r['raw_trace'],str(OLD.relative_to(ROOT)),r) for r in archived]
            bit = ROOT/'DCS_FPGA/FULL_PS/hw/vivado/build/ldacs_zed/ldacs_zed.runs/impl_1/system_wrapper.bit'
            require(all(r['bitstream_sha256']==sha(bit) for r in archived), 'PS fabric image changed')
            metadata = archived[0]['resources']
        else:
            item = new['architectures'][mode]
            require(item['complete'] and len(item['profiles'])==8, 'Architecture section incomplete')
            require(item['boot']['firmware_sha256']==firmware_hash, 'New firmware mismatch')
            design = ROOT/'DCS_FPGA/FULL_PL' if mode=='PL' else ROOT/'DCS_FPGA'
            bit = design/'hw/vivado/build/ldacs_zed/ldacs_zed.runs/impl_1/system_wrapper.bit'
            require(item['boot']['bitstream_sha256']==sha(bit), 'Accelerator image changed')
            profiles = [(r['coding'],r['layout']['payload_bytes'],r['samples'],r['trace'],str(NEW.relative_to(ROOT)),r) for r in item['profiles']]
            metadata = item['routed_metadata']
            wire = (NEW.parent/mode/'uart_rx.bin').read_bytes()
            for row in item['profiles']:
                require(len(row['samples'])==5 and sum(s['iterations'] for s in row['samples'])==100, 'Short batch sweep')
                for s in row['samples']:
                    response = wire[s['wire_start_offsets']['rx']:s['wire_end_offsets']['rx']]
                    header = bytes.fromhex(s['raw_response_header_hex'])
                    require(response[:len(header)]==header and len(response)==len(header)+row['layout']['payload_bytes'], 'Raw UART response mismatch')
                    require(hashlib.sha256(response[len(header):]).hexdigest()==s['last_output_sha256'], 'UART output hash mismatch')
                    audits.append(dict(design=mode,profile=row['coding'],check='binary UART response',passed=True))
                for trial in row['end_to_end']:
                    require(trial['benchmark']['valid'] and trial['modem']['bit_errors']==0, 'End-to-end failure')
                    e2e.append(dict(design=mode,profile=row['coding'],seed=trial['seed'],
                        host_wall_ms=trial['host_wall_ms'],host_encoding_ms=trial['host_encoding_ms'],
                        board_mapping_us=trial['modem']['mapping_us'],board_demapping_us=trial['modem']['demapping_us'],
                        decoder_us=trial['benchmark']['decoder_mean_us'],
                        scope='Host encode + UART modem + UART single decode + host validation; no trace'))
        report = ROOT/metadata['source']
        require(sha(report)==metadata['report_sha256'], 'Utilization source changed')
        ff = None
        for line in report.read_text(errors='replace').splitlines():
            match = re.search(r'\|\s*Slice Registers\s*\|\s*([\d.]+)',line)
            if match:
                ff=float(match[1]);break
        resources.append(dict(design=mode,configuration='static',lut=metadata['lut']['used'],ff=ff,
            bram36_equivalent=metadata['bram']['used'],dsp=metadata['dsp']['used'],
            wns_ns=metadata.get('wns_ns'),whs_ns=metadata.get('whs_ns'),source=str(report.relative_to(ROOT)),
            scope='Routed implementation metadata, not measured live activity'))
        for coding, payload, samples, trace, source, full in profiles:
            require(trace['payload_matches_input'] and not trace['rs_failures'] and all(t['matches_model'] for t in trace['stages'].values()), 'Stage verification failed')
            for t in trace['stages'].values():
                actual=bytes.fromhex(t['output_hex'])
                require(len(actual)==t['length'] and hashlib.sha256(actual).hexdigest()==t['sha256'],'Trace byte/hash mismatch')
            require(trace['stages']['derandomizer']['sha256']==samples[-1]['last_output_sha256'],'Trace and timed output differ')
            for s in samples:
                raw=RESPONSE.unpack(bytes.fromhex(s['raw_response_header_hex']))
                require(raw[0]==b'LDBR' and raw[1]==arch_id and raw[3]==s['iterations'] and raw[4]==payload,'Counter identity mismatch')
                require(raw[6]==s['global_timer_hz'] and raw[7]==s['pl_clock_hz'] and raw[16]==s['decoder_ticks_sum'],'Counter data mismatch')
                require(s['valid'] and s['last_output_matches'] and not s['crc_failed_frames'] and not s['rs_failures'],'Failed physical frame')
            count=sum(s['iterations'] for s in samples)
            seconds=sum(s['decoder_ticks_sum']/s['global_timer_hz'] for s in samples)
            decoder.append(dict(design=mode,profile=coding,payload_bytes=payload,timed_frames=count,
                batches=len(samples),warmups_per_batch=samples[0]['warmups'],
                mean_ms=seconds*1000/count,min_ms=min(s['decoder_min_us'] for s in samples)/1000,
                max_ms=max(s['decoder_max_us'] for s in samples)/1000,
                batch_mean_stdev_us=statistics.stdev(s['decoder_mean_us'] for s in samples) if len(samples)>1 else None,
                payload_mbps=payload*8*count/seconds/1e6,frames_per_second=count/seconds,
                crc_failures=sum(s['crc_failed_frames'] for s in samples),rs_failures=sum(s['rs_failures'] for s in samples),
                gt_hz=samples[0]['global_timer_hz'],pl_hz=samples[0]['pl_clock_hz'] if mode!='PS' else None,
                speedup_vs_ps=None,source=source))
            for name in samples[0]['stage_measurements']:
                total=sum(s['stage_measurements'][name]['ticks_sum']/s['stage_measurements'][name]['clock_hz'] for s in samples)
                stages.append(dict(design=mode,profile=coding,stage=name,mean_us=total*1e6/count,timed_frames=count,source=source))
        for row in archived:
            m=row['modem']
            require(row['valid'] and m['bit_errors']==0,'Archived modem failure')
            modem.append(dict(design=mode,profile=row['coding'],symbols=m['symbols'],bit_errors=m['bit_errors'],
                mapping_us=m['mapping_us'],demapping_us=m['demapping_us'],uart_wall_ms=m['uart_wall_ms'],
                trials=1,source=str(OLD.relative_to(ROOT)),scope='Physical ARM ideal digital QAM loopback; no RF/noise'))
    for row in decoder:
        baseline=next(r for r in decoder if r['design']=='PS' and r['profile']==row['profile'])
        row['speedup_vs_ps']=baseline['mean_ms']/row['mean_ms']
    transfers=[]
    checks=0
    for batch in stage['batches']:
        require(batch['valid'] and batch['counters']['valid'],'Stage batch failed')
        c=batch['counters']
        raw=struct.unpack('<4s10I5Q',bytes.fromhex(c['raw_hex']))
        require(raw[0]==b'SBRR' and raw[1]==batch['count'] and raw[5]==c['timer_hz'] and raw[-1]==c['compute_integrity_ticks'],'Stage raw counters differ')
        compute_us=c['compute_integrity_ticks']*1e6/c['timer_hz']
        service_us=compute_us+sum(s['microseconds']['service_total'] for s in batch['switches'])
        require(abs(service_us/batch['count']/1000-batch['service_per_frame_ms'])<1e-6,'DPR service calculation differs')
        for trace in batch['traces']:
            require(trace['valid'] and all(trace[n]['matches'] for n in ('bdi','rs','payload')),'Stage output mismatch')
            checks+=3
        for switch in batch['switches']:
            require(switch['static_continuity']['valid'],'Static continuity failed')
            transfers.append(dict(profile=batch['mode'],batch_size=batch['count'],module=switch['module'],
                partial_bytes=switch['partial_bytes'],**{k+'_us':v for k,v in switch['microseconds'].items()},
                static_continuity=True))
    require(checks==144 and len(transfers)==20 and sum(b['count'] for b in stage['batches'])==48,'Stage totals mismatch')
    for name,r in stage_summary['resources'].items():
        resources.append(dict(design='STAGE_DPR',configuration=name,lut=r['lut'],ff=r['ff'],bram36_equivalent=r['bram36_equivalent'],
            dsp=r['dsp'],wns_ns=r['wns_ns'],whs_ns=r['whs_ns'],source=str((STAGE/'summary.json').relative_to(ROOT)),
            scope='Routed implementation metadata, not measured live activity'))
    csv_file('decoder.csv',decoder);csv_file('decoder_stages.csv',stages)
    csv_file('stage_sharing_dpr.csv',stage_summary['rows']);csv_file('stage_sharing_swaps.csv',transfers)
    csv_file('resources.csv',resources);csv_file('modem.csv',modem);csv_file('end_to_end.csv',e2e)
    manifest=dict(designs=['FULL_PS','FULL_PL_DECODER','HYBRID','LATEST_STAGE_SHARING_DPR'],hardware_reruns=0,
        static_profiles=24,static_timed_frames=sum(r['timed_frames'] for r in decoder),stage_dpr_frames=48,
        stage_dpr_swaps=20,stage_dpr_buffer_checks=checks,all_selected_evidence_valid=True,
        evidence=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in sources],wire_audits=audits,
        excluded=['whole-receiver DPR','DPR full PL','DPR hybrid','host-only benchmarks','simulations','power estimates'],
        sample_count_note='PS 3 timed frames/profile; PL/Hybrid 100/profile; stage DPR all profiles at batch 1 and QPSK 1/2 also batches 8/32')
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    lines=['# Benchmarks for the four selected designs','',
        'Reused existing physical EDGE Z7-10 / XC7Z010 board measurements. No hardware benchmarks were rerun for this consolidation.', '',
        '| Design | Profiles | Timed frames | Source |','|---|---:|---:|---|',
        '| Full PS | 8 | 24 (3/profile) | Physical API verification, 30 October 2026 |',
        '| Full PL decoder | 8 | 800 (100/profile) | Completed architecture section, 3 November 2026 |',
        '| Hybrid | 8 | 800 (100/profile) | Completed architecture section, 3 November 2026 |',
        '| Latest stage-sharing DPR | 8 | 48 | Passed onboard run, 3 November 2026 |','',
        'The PL/Hybrid sections are complete and individually checked, although their enclosing campaign stopped on a later PS UART timeout. The failed PS attempt supplies no benchmark data here. PS results come from the earlier successful capture; its firmware and fabric-image hashes match current files.', '',
        '## Static decoder measurements','',
        'All five decoder stages are included. DMA/control is included for accelerated designs. UART, modem, CRC verification and trace replay are excluded. Throughput is payload bits divided by board-measured decode time; it is not uninterrupted input-stream throughput.', '',
        '| Profile | Full PS mean ms | Full PL mean ms | Hybrid mean ms |', '|---|---:|---:|---:|']
    for row in [r for r in decoder if r['design']=='PS']:
        values=[next(r['mean_ms'] for r in decoder if r['design']==m and r['profile']==row['profile']) for m in ('PS','PL','HYBRID')]
        lines.append('| '+row['profile']+' | '+' | '.join(f'{v:.6f}' for v in values)+' |')
    lines += ['', 'Different profiles have different payload lengths. Compare architectures within the same profile. PS used saved text payloads; PL/Hybrid used RNG seed 91. Payload sizes and coding profiles agree, but PS-versus-accelerator speedups are descriptive comparisons across sessions, not an identical-input paired experiment. All selected timed cases passed CRC and final-output checks, with all five trace buffers matching the reference. PS sample count is smaller; per-frame percentiles are unavailable. Batch-mean standard deviation for PL/Hybrid is not per-frame jitter.', '',
        '## Latest stage-sharing DPR','',
        'Viterbi/packing and RS alternate in one reconfigurable partition; block deinterleaving is static. Exact current image-family, firmware and full/partial image hashes were checked. The preserved run passed 48 frames, 20 genuine PCAP transfers, 144 intermediate/final buffer checks, and static continuity during every transfer.', '',
        '| Profile | Batch | Compute/integrity ms per batch | PCAP ms per batch | CRC precheck ms per batch | Service ms/frame |',
        '|---|---:|---:|---:|---:|---:|']
    for row in stage_summary['rows']:
        lines.append(f"| {row['mode']} | {row['batch']} | {row['compute_integrity_ms']:.3f} | {row['pcap_ms']:.3f} | {row['crc_precheck_ms']:.3f} | {row['service_per_frame_ms']:.3f} |")
    lines += ['', 'DPR service includes both partial loads, CRC prechecks, DMA, copies and payload integrity. It excludes UART image/input staging and host gaps. Execution wall time has a separate field. Do not treat these values as the same interval as static decoder-only latency. Batch sizes 8/32 were measured only for QPSK 1/2; other combinations remain unmeasured.', '',
        'Stage DPR uses approximately 50 MHz PL; static PL/Hybrid clocks come from their raw firmware replies (approximately 71.43 MHz). Stage DPR peak occupied LUTs are 8723. The reported 24.02% reduction refers to the preserved 11480-LUT whole-receiver DPR baseline, which is excluded from this selected-design performance comparison. The Pblock reservation did not shrink.', '',
        '## Files and limits','',
        '- decoder.csv: means, min/max, sample counts, payload throughput, clocks, errors and speedup relative to PS.',
        '- decoder_stages.csv: all five measured stage latencies.',
        '- stage_sharing_dpr.csv / stage_sharing_swaps.csv: service, compute, CRC, PCAP, upload-independent switching and continuity.',
        '- resources.csv: routed LUT/FF/BRAM/DSP and timing slack; implementation metadata rather than live activity.',
        '- modem.csv: saved physical ARM digital-loopback modulation/demodulation measurements for all 24 static cases.',
        '- end_to_end.csv: saved PL/Hybrid single-message wall measurements, three/profile, including host encode, physical UART modem/decode and verification. Equivalent full-wall PS measurements are unavailable.',
        '- manifest.json: source hashes, selected scope and 80 binary UART response audits.', '',
        'Power/energy is excluded at user request. RF/SNR equipment is unavailable. No RF reception, BER-vs-SNR, sustained continuous-stream rate, CPU utilization or real-time deadline compliance is claimed. These saved results share SPEC-CHECK constants and do not establish independent LDACS conformance.', '',
        'This is a reproducible project benchmark using saved board evidence, not an externally certified standard benchmark. Existing sample counts, seeds and timing boundaries are preserved; results from different sessions are not pooled into invented per-frame distributions.', '']
    (OUT/'REPORT.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:v for k,v in manifest.items() if k not in ('evidence','wire_audits')},indent=2))


if __name__=='__main__':
    main()
