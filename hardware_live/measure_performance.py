"""Physical UART/board performance sweep. No simulated measurement fallback.

Uses existing firmware and clocks. Binary RX/TX recordings accompany decoded
counter replies. Reference encoding/checking is outside decoder timing.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import time

import server as live


def stamp():
    return datetime.now(timezone.utc).isoformat()


class RecordingSerial:
    def __init__(self, serial, directory):
        self.serial = serial
        self.rx = (directory / 'uart_rx.bin').open('ab', buffering=0)
        self.tx = (directory / 'uart_tx.bin').open('ab', buffering=0)

    def __getattr__(self, name):
        return getattr(self.serial, name)

    def read(self, count):
        data = self.serial.read(count)
        self.rx.write(data)
        return data

    def write(self, data):
        count = self.serial.write(data)
        self.tx.write(data[:count])
        return count

    def close(self):
        self.serial.close()
        self.rx.close()
        self.tx.close()


def summarize(row):
    samples = row['samples']
    if not samples:
        return None
    reps = sum(s['iterations'] for s in samples)
    elapsed = sum(s['decoder_ticks_sum'] / s['global_timer_hz'] for s in samples)
    means = [s['decoder_mean_us'] for s in samples]
    e2e = [s['host_wall_ms'] for s in row['end_to_end']]
    return dict(timed_frames=reps, mean_us=elapsed * 1e6 / reps,
                min_us=min(s['decoder_min_us'] for s in samples),
                max_us=max(s['decoder_max_us'] for s in samples),
                batch_mean_stdev_us=statistics.stdev(means) if len(means) > 1 else None,
                payload_mbps=row['layout']['payload_bytes'] * 8 * reps / elapsed / 1e6,
                frames_per_second=reps / elapsed,
                crc_failed_frames=sum(s['crc_failed_frames'] for s in samples),
                rs_failures=sum(s['rs_failures'] for s in samples),
                rs_corrections=sum(s['rs_corrections'] for s in samples),
                end_to_end_mean_ms=statistics.mean(e2e) if e2e else None,
                valid=all(s['valid'] for s in samples) and
                      all(s['benchmark']['valid'] for s in row['end_to_end']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--modes', nargs='+', choices=['PS', 'PL', 'HYBRID', 'DPR'], default=['PL', 'HYBRID', 'PS'])
    parser.add_argument('--batches', type=int, default=5)
    parser.add_argument('--iterations', type=int, default=20)
    parser.add_argument('--warmups', type=int, default=2)
    parser.add_argument('--end-to-end', type=int, default=3)
    parser.add_argument('--port', default='COM5')
    args = parser.parse_args()
    if args.batches < 1 or not 1 <= args.iterations <= 1000 or not 0 <= args.warmups <= 100:
        parser.error('Invalid repetition counts')
    args.output.mkdir(parents=True, exist_ok=False)
    work = live.Workbench(args.port, r'C:\Xilinx\Vitis\2022.2\bin\xsdb.bat',
                          r'C:\Xilinx\Vitis\2022.2\gnu\aarch32\nt\gcc-arm-none-eabi\bin\arm-none-eabi-gcc.exe')
    record = dict(schema='physical_board_performance_v1', started_utc=stamp(), complete=False,
                  port=args.port, settings=vars(args) | {'output': str(args.output)}, architectures={},
                  scope=dict(decoder='Five stages, DMA/control included; UART, CRC, modem, output copy excluded',
                             batch='Repeated decode of one resident frame; CRC checked each timed iteration',
                             end_to_end='Host encode + physical UART modem loopback + physical UART single decode + host verification; trace excluded',
                             percentiles='Unavailable: firmware returns aggregate/min/max, not individual samples',
                             sustained_streaming='Not measured: resident-buffer repetition is not continuous frame ingestion',
                             power='Excluded by user', rf_snr='Unavailable: no RF/channel equipment',
                             cpu_load='Not measured; elapsed clock cycles do not indicate CPU utilization',
                             timing_reference='SLCR-derived clock rate with nominal board reference; not external oscillator calibration'))

    def save():
        temporary = args.output / 'measurement.tmp'
        temporary.write_text(json.dumps(record, indent=2) + '\n')
        temporary.replace(args.output / 'measurement.json')

    def log(message):
        print(stamp(), message, flush=True)

    save()
    try:
        for mode in args.modes:
            log('BOOT ' + mode)
            directory = args.output / mode
            directory.mkdir()
            start = time.perf_counter()
            work.boot(mode)
            (directory / 'boot_log.json').write_text(json.dumps(work.logs, indent=2) + '\n')
            item = dict(boot=work.state['boot'], boot_wall_seconds=time.perf_counter() - start,
                        routed_metadata=live.resources(mode), profiles=[], complete=False)
            if mode == 'DPR':
                item['pcap_roundtrip'] = work.dpr_verified
            record['architectures'][mode] = item
            board = work.open_uart()
            board.timeout = 600
            board.serial = RecordingSerial(board.serial, directory)
            work.inspect_registers(mode)
            item['registers'] = work.state['registers']
            save()
            for coding in live.client.L.MODES:
                layout, payload, tx = live.client.prepare(coding, seed=91)
                row = dict(coding=coding, layout=layout, payload_sha256=live.sha_bytes(payload) if hasattr(live, 'sha_bytes') else hashlib.sha256(payload).hexdigest(),
                           encoded_sha256=hashlib.sha256(tx).hexdigest(), samples=[], end_to_end=[])
                item['profiles'].append(row)
                for batch in range(args.batches):
                    offsets = dict(rx=board.serial.rx.tell(), tx=board.serial.tx.tell())
                    result = board.benchmark(layout, payload, tx, args.iterations, args.warmups, live.MODES[mode][1])
                    result.update(recorded_utc=stamp(), wire_start_offsets=offsets,
                                  wire_end_offsets=dict(rx=board.serial.rx.tell(), tx=board.serial.tx.tell()))
                    row['samples'].append(result)
                    row['summary'] = summarize(row)
                    save()
                    log(f"BATCH {mode} {coding} {batch+1}/{args.batches} frames={result['iterations']} mean_us={result['decoder_mean_us']:.3f} crc_bad={result['crc_failed_frames']}")
                    if not result['valid']:
                        raise RuntimeError(f'Board CRC/payload/RS failure {mode} {coding}')
                row['trace'] = board.trace(layout, payload, tx, live.MODES[mode][1])
                save()
                if not row['trace']['payload_matches_input'] or row['trace']['rs_failures'] or not all(s['matches_model'] for s in row['trace']['stages'].values()):
                    raise RuntimeError('Board stage trace mismatch')
                for repeat in range(args.end_to_end):
                    started = time.perf_counter()
                    current_layout, current_payload, current_tx = live.client.prepare(coding, seed=1000+repeat)
                    encoded = time.perf_counter()
                    modem = work.modem(board, coding, current_tx)
                    recovered = modem.pop('_recovered')
                    result = board.benchmark(current_layout, current_payload, recovered, 1, 0, live.MODES[mode][1])
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    modem.pop('iq')  # Entire actual binary response remains in uart_rx.bin.
                    row['end_to_end'].append(dict(recorded_utc=stamp(), seed=1000+repeat,
                        host_wall_ms=elapsed_ms, host_encoding_ms=(encoded-started)*1000,
                        modem=modem, benchmark=result))
                    row['summary'] = summarize(row)
                    save()
                    if not result['valid']:
                        raise RuntimeError('End-to-end physical decode failed')
                log('PROFILE_PASS ' + mode + ' ' + coding)
            item['complete'] = True
            work.close_uart()
            save()
        record['complete'] = True
        log('SWEEP_PASS')
    except BaseException as error:
        record['error'] = repr(error)
        log('SWEEP_FAILED ' + repr(error))
        raise
    finally:
        work.close_uart()
        record['finished_utc'] = stamp()
        save()
        work.executor.shutdown(wait=False)


if __name__ == '__main__':
    main()
