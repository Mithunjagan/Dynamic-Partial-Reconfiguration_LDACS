"""Distinct-frame UART-fed physical receiver bursts, with per-frame counters."""
import argparse
import json
import math
from pathlib import Path
import statistics
import time

import server as live
from measure_performance import RecordingSerial, stamp


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--frames', type=int, default=10)
    p.add_argument('--deadline-ms', type=float)
    p.add_argument('--modes', nargs='+', default=['PL', 'HYBRID', 'PS'])
    a = p.parse_args()
    if a.frames < 2 or any(mode not in live.MODES or mode == 'DPR' for mode in a.modes):
        p.error('Need at least two frames and static architectures')
    a.output.mkdir(parents=True, exist_ok=False)
    record = dict(schema='physical_uart_bursts_v1', started_utc=stamp(), complete=False,
        frames_per_profile=a.frames, deadline_ms=a.deadline_ms, architectures={},
        scope='Sequential distinct pre-encoded frames over real 115200-baud UART. One complete decode/request, no warmups. Host validation included. Modem excluded.',
        limitation='UART-paced short bursts, no simultaneous ingestion/decoding, RF, prescribed arrival schedule, or long-duration soak claim.')
    work = live.Workbench('COM5', r'C:\Xilinx\Vitis\2022.2\bin\xsdb.bat',
        r'C:\Xilinx\Vitis\2022.2\gnu\aarch32\nt\gcc-arm-none-eabi\bin\arm-none-eabi-gcc.exe')

    def save():
        temp = a.output / 'burst.tmp'
        temp.write_text(json.dumps(record, indent=2) + '\n')
        temp.replace(a.output / 'bursts.json')

    save()
    try:
        for mode in a.modes:
            directory = a.output / mode
            directory.mkdir()
            print(stamp(), 'BURST_BOOT', mode, flush=True)
            work.boot(mode)
            board = work.open_uart()
            board.timeout = 60
            board.serial = RecordingSerial(board.serial, directory)
            item = dict(boot=work.state['boot'], profiles=[], complete=False)
            record['architectures'][mode] = item
            for coding in live.client.L.MODES:
                frames = [live.client.prepare(coding, seed=2000+i) for i in range(a.frames)]
                row = dict(coding=coding, layout=frames[0][0], samples=[], complete=False)
                item['profiles'].append(row)
                start = time.perf_counter()
                for i, (layout, payload, tx) in enumerate(frames):
                    result = board.benchmark(layout, payload, tx, 1, 0, live.MODES[mode][1])
                    result['seed'] = 2000+i
                    row['samples'].append(result)
                    row['burst_wall_seconds'] = time.perf_counter()-start
                    save()
                    if not result['valid']:
                        raise RuntimeError('Distinct-frame CRC/payload/RS failure')
                elapsed = row['burst_wall_seconds']
                samples = [s['decoder_mean_us'] for s in row['samples']]
                row['summary'] = dict(frames=a.frames, decoder_mean_us=statistics.mean(samples),
                    decoder_median_us=statistics.median(samples),
                    decoder_stdev_us=statistics.stdev(samples), decoder_min_us=min(samples),
                    decoder_max_us=max(samples), decoder_p95_us=sorted(samples)[math.ceil(.95*len(samples))-1],
                    decoder_p95_method='Nearest rank, only this burst individual samples',
                    uart_fed_payload_mbps=sum(len(payload)*8 for _, payload, _ in frames)/elapsed/1e6,
                    uart_fed_frames_per_second=a.frames/elapsed,
                    crc_failed_frames=sum(s['crc_failed_frames'] for s in row['samples']),
                    deadline_misses=sum(v > a.deadline_ms*1000 for v in samples) if a.deadline_ms else None,
                    deadline_scope='Decoder interval only; no externally paced arrival schedule',
                    valid=all(s['valid'] for s in row['samples']))
                row['complete'] = True
                save()
                print(stamp(), 'BURST_PASS', mode, coding, a.frames, 'wall_s', round(elapsed,3), flush=True)
            item['complete'] = True
            work.close_uart()
            save()
        record['complete'] = True
    except BaseException as error:
        record['error'] = repr(error)
        raise
    finally:
        work.close_uart()
        work.executor.shutdown(wait=False)
        record['finished_utc'] = stamp()
        save()


if __name__ == '__main__':
    main()
