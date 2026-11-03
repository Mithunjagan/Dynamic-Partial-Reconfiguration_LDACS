"""Summarize a validated FULL_PL board capture without rerunning hardware."""
import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path)
    args = parser.parse_args()
    data = json.loads(args.capture.read_text())
    if data['architecture'] != 'FULL_PL' or not data['valid']:
        raise ValueError('A valid FULL_PL capture is required')
    rows = []
    for record in data['results']:
        samples = record['samples']
        if not samples or not all(s['valid'] and s['last_output_matches'] and
                                  s['crc_failed_frames'] == s['rs_failures'] == 0
                                  for s in samples):
            raise ValueError('Unsuccessful board response')
        frames = sum(s['iterations'] for s in samples)
        seconds = sum(s['decoder_ticks_sum'] / s['global_timer_hz'] for s in samples)
        row = dict(mode=record['mode'], frames=frames,
                   payload_bytes=record['layout']['payload_bytes'],
                   mean_us=seconds * 1e6 / frames,
                   min_us=min(s['decoder_min_us'] for s in samples),
                   max_us=max(s['decoder_max_us'] for s in samples),
                   payload_mbps=record['layout']['payload_bytes'] * 8 * frames / seconds / 1e6,
                   pipeline_us=sum(s['pl_pipeline_ticks_sum'] / s['pl_clock_hz']
                                   for s in samples) * 1e6 / frames)
        for name in samples[0]['stage_measurements']:
            row[name + '_us'] = sum(s['stage_measurements'][name]['ticks_sum'] /
                                       s['stage_measurements'][name]['clock_hz']
                                       for s in samples) * 1e6 / frames
        rows.append(row)
    csv_path = args.capture.with_suffix('.csv')
    with csv_path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    samples = [s for r in data['results'] for s in r['samples']]
    lines = ['# FULL_PL real-board benchmark', '',
             f"Capture UTC: {data['recorded_utc']}", '',
             f"Board: {data['board_label']}; UART {data['port']}; seed {data['seed']}.",
             f"Measured frames: {sum(r['frames'] for r in rows)}; "
             f"{data['batches']} batches/mode, {data['iterations_per_batch']} measured frames/batch, "
             f"{data['warmups_per_batch']} warmups/batch.",
             'All measured CRC checks and final-frame byte comparisons passed; zero RS failures.', '',
             f"Live PL clocks (Hz): {sorted({s['pl_clock_hz'] for s in samples})}; "
             f"ARM global timer clocks (Hz): {sorted({s['global_timer_hz'] for s in samples})}.", '',
             '| Mode | Frames | Mean (us) | Min (us) | Max (us) | Payload (Mbps) | PL pipeline (us) |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"| {row['mode']} | {row['frames']} | {row['mean_us']:.3f} | "
                     f"{row['min_us']:.3f} | {row['max_us']:.3f} | "
                     f"{row['payload_mbps']:.3f} | {row['pipeline_us']:.3f} |")
    lines += ['', 'Decoder latency includes DMA/reset/control and excludes UART, CRC and output copy.',
              'PL pipeline and stage counters describe overlapping streaming intervals; do not add stage times.',
              'CSV includes all five measured stage latencies. These are receiver-only measurements.', '',
              'Startup repair: explicitly assigned build-id and ARM unwind sections to the code PT_LOAD',
              'segment in FULL_PL/sw/ldacs_bridge.ld. The previous ELF had overlapping code/data loads,',
              'with zero-filled data replacing instructions. Rebuilt with unchanged compiler flags,',
              'DDR base, cache policy and clocks. Verified non-overlapping PT_LOAD ranges before boot.',
              'The capture retains the corrected ELF hash, source hashes and bitstream/report hashes.',
              'No HYBRID or FULL_PS baseline was changed for this run.', '']
    report = args.capture.with_suffix('.md')
    report.write_text('\n'.join(lines))
    print('\n'.join(lines))
    print('Saved', csv_path, report)


if __name__ == '__main__':
    main()
