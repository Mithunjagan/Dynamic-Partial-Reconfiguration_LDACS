"""Three real LDACS architectures, one local message workbench. No simulation fallback."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import queue
import re
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse, parse_qs
import zlib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PROJECT = ROOT / 'DCS_FPGA'
MODES = {'PS': ('FULL_PS', 2), 'PL': ('FULL_PL', 1), 'HYBRID': ('BENCHMARKS/hybrid', 0), 'DPR': ('DPR/FULL_PL', 1)}
STAGES = ['helical', 'viterbi', 'block_deinterleaver', 'reed_solomon', 'derandomizer']
sys.path.insert(0, str(PROJECT / 'FULL_PS'))
spec = importlib.util.spec_from_file_location('axiom_board_client', PROJECT / 'FULL_PS/host/board_client.py')
client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(client)


def now(): return datetime.now(timezone.utc).isoformat()
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def validate_elf(path):
    data = Path(path).read_bytes()
    if data[:7] != b'\x7fELF\x01\x01\x01': raise RuntimeError('Expected ELF32 little-endian firmware')
    header = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
    if header[2] != 40: raise RuntimeError('Firmware is not ARM machine code')
    segments = []
    for i in range(header[10]):
        kind, offset, address, physical, filesz, memsz, flags, align = struct.unpack_from('<IIIIIIII', data, header[5] + i * header[9])
        if kind == 1 and memsz:
            if not 0x01000000 <= address < address + memsz <= 0x02000000:
                raise RuntimeError('Firmware load region overlaps reserved DMA memory or exceeds DDR image range')
            segments.append((address, address + memsz, flags))
    segments.sort()
    if any(a[1] > b[0] for a, b in zip(segments, segments[1:])):
        raise RuntimeError('Overlapping ELF load segments; refusing unsafe download')
    if not any(lo <= header[4] < hi and flags & 1 for lo, hi, flags in segments):
        raise RuntimeError('ELF entry is outside executable load regions')
    return {'entry': f'0x{header[4]:08X}', 'load_regions': [[hex(a), hex(b), f] for a, b, f in segments]}


def design_root(mode): return PROJECT if mode == 'HYBRID' else PROJECT / MODES[mode][0]


def resources(mode):
    directory = design_root(mode) / 'hw/vivado/build'
    report = directory / 'utilization.rpt'
    timing = directory / 'timing.rpt'
    if mode == 'DPR':
        report = directory / 'dfx/full_pl_utilization.rpt'
        timing = directory / 'dfx/full_pl_timing.rpt'
    values = {'source': str(report.relative_to(ROOT)), 'lut': None, 'bram': None, 'dsp': None}
    if report.exists():
        text = report.read_text(errors='replace')
        for key, label, capacity in [('lut', 'Slice LUTs', 17600), ('bram', 'Block RAM Tile', 60), ('dsp', 'DSPs', 80)]:
            match = re.search(r'\|\s*' + re.escape(label) + r'\s*\|\s*([\d.]+)', text)
            if match:
                used = float(match[1]); values[key] = {'used': used, 'capacity': capacity, 'percent': used / capacity * 100}
        values['report_sha256'] = sha(report)
    if timing.exists():
        text = timing.read_text(errors='replace')
        match = re.search(r'WNS\(ns\)[^\n]*\n[^\n]*\n\s*([-+\d.]+)\s+([-+\d.]+)\s+(\d+)\s+\d+\s+([-+\d.]+)', text)
        if match: values.update(wns_ns=float(match[1]), whs_ns=float(match[4]))
    return values


class Workbench:
    def __init__(self, port, xsdb, gcc):
        self.port, self.xsdb, self.gcc = port, Path(xsdb), Path(gcc)
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='physical-board')
        self.logs = []; self.log_sequence = 0
        self.state = {'busy': False, 'job': None, 'mode': None, 'requested_mode': 'HYBRID', 'ready': False,
                      'stage': 0, 'status': 'Connect and boot a hardware architecture', 'last': None,
                      'comparison': {}, 'error': None, 'port': port, 'source': 'physical_hardware_only',
                      'boot': None, 'registers': None, 'session_started': now()}
        self.token = secrets.token_urlsafe(32)
        self.dpr_verified = None
        self.board = None

    def close_uart(self):
        if self.board is not None:
            try: self.board.close()
            except Exception: pass
            self.board = None

    def ensure_debug_service(self):
        try:
            with socket.create_connection(('127.0.0.1', 3121), timeout=.5): return
        except OSError: pass
        executable = self.xsdb.parent / 'unwrapped/win64.o/hw_server.exe'
        if not executable.is_file(): raise RuntimeError('Xilinx hardware server executable is missing')
        # XSDB's implicit server has an idle-exit policy. Keep one debug service
        # available across long serial experiments rather than repeatedly
        # opening/closing the shared USB-JTAG adapter between transactions.
        process = subprocess.Popen([str(executable), '-s', 'tcp:127.0.0.1:3121'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is not None: raise RuntimeError('Persistent Xilinx hardware server could not start')
            try:
                with socket.create_connection(('127.0.0.1', 3121), timeout=.3):
                    self.log('Persistent Xilinx debug service started; PID ' + str(process.pid), 'HOST')
                    return
            except OSError: time.sleep(.2)
        raise TimeoutError('Xilinx debug service did not open its local port')

    def open_uart(self):
        if self.board is None:
            import serial
            transport = serial.Serial(port=None, baudrate=115200, timeout=.2, write_timeout=30)
            # Use the board's established FTDI line state and keep the port open
            # across frames. Release it before JTAG uses the shared USB adapter.
            transport.port = self.port
            transport.open()
            self.board = client.Board(self.port, timeout=25, serial_port=transport)
        return self.board

    def transport_status(self):
        """Report physical USB-UART enumeration without opening or disturbing COM5."""
        try:
            from serial.tools import list_ports
            ports = {item.device: item for item in list_ports.comports()}
            item = ports.get(self.port)
            return {
                'present': item is not None,
                'port': self.port,
                'description': item.description if item else None,
                'hwid': item.hwid if item else None,
                'claimed_by_bridge': self.board is not None,
                'sampled_utc': now(),
            }
        except Exception as error:
            return {'present': False, 'port': self.port, 'error': str(error), 'sampled_utc': now()}

    def dpr_info(self):
        folder = PROJECT / 'DPR/FULL_PL/hw/vivado/build/dfx'
        marker, images = folder / 'routed_manifest.json', folder / 'images.json'
        status = {'available': False, 'hardware_verified': self.dpr_verified is not None,
                  'status': 'BUILD / VALIDATION REQUIRED', 'detail': 'No verified partial-image family is available.'}
        if marker.exists():
            try:
                routed = json.loads(marker.read_text())
                if routed.get('pr_verify_passed') and images.exists():
                    family = json.loads(images.read_text())
                    if family.get('pr_verify_passed') and family.get('build_token') == routed.get('build_token'):
                        status.update(available=True, status='IMAGE FAMILY AVAILABLE', detail='Routed, pr_verify-checked image family exists. A physical PCAP round trip and post-switch decoder check are required.')
            except (ValueError, OSError): pass
        log_path = PROJECT / 'DPR/FULL_PL/hw/vivado/build_live.log'
        if not status['available'] and log_path.exists():
            tail = log_path.read_text(errors='replace')[-6000:]
            failures = re.findall(r'^(?:ERROR:.*|Timing failed.*|Expected one.*|DFX DRC failed.*)', tail, re.M)
            if failures: status.update(status='BUILD FAILED / NOT VERIFIED', detail=failures[-1][:500])
            elif 'Exiting Vivado' not in tail: status.update(status='BUILD IN PROGRESS / NOT VERIFIED', detail='Vivado is building the real DFX image family. Hardware mode remains unavailable until routing, timing, compatibility and board tests pass.')
        if self.dpr_verified:
            status.update(status='PCAP HARDWARE VERIFIED', detail='Real partial switch and post-switch payload checks passed. See exported raw switch counters.', evidence=self.dpr_verified)
        return status

    def log(self, message, source='HOST', level='info'):
        with self.lock:
            self.log_sequence += 1
            self.logs.append({'id': self.log_sequence, 'time': now(), 'source': source, 'level': level, 'text': str(message)})
            self.logs = self.logs[-600:]

    def update(self, **values):
        with self.lock: self.state.update(values)

    def snapshot(self, after=0):
        with self.lock:
            value = dict(self.state)
            value['logs'] = [entry for entry in self.logs if entry['id'] > after]
            value['cursor'] = self.log_sequence
            value['token'] = self.token
            value['transport'] = self.transport_status()
            value['dpr'] = self.dpr_info()
            value['profiles'] = {mode: resources(mode) for mode in MODES}
            value['coding_modes'] = {name: {'payload_bytes': client.L.frame_layout(name)['payload_bytes']} for name in client.L.MODES}
            return value

    def submit(self, action, data):
        if action not in ('boot', 'send', 'sweep', 'registers', 'dpr'): raise ValueError('Unknown action')
        if action == 'dpr' and not self.dpr_info()['available']:
            raise ValueError(self.dpr_info()['detail'])
        mode = data.get('mode', 'HYBRID')
        if mode not in MODES: raise ValueError('Architecture must be PS, PL, or HYBRID')
        coding = data.get('coding', 'qpsk_1_2')
        if coding not in client.L.MODES: raise ValueError('Unknown LDACS coding profile')
        message = data.get('message', '')
        if not isinstance(message, str) or not message or '\0' in message:
            if action in ('send', 'sweep'): raise ValueError('Enter a nonempty message without NUL characters')
        if len(message.encode('utf-8')) > client.L.frame_layout(coding)['payload_bytes']:
            raise ValueError('UTF-8 message exceeds the selected frame payload capacity')
        if action == 'registers' and mode == 'PS': raise ValueError('PS-only has no accelerator registers')
        with self.lock:
            if self.state['busy']: raise BlockingIOError('A hardware operation is already running')
            job = secrets.token_hex(6)
            self.state.update(busy=True, job=job, error=None, requested_mode=mode, status='Queued / ' + action)
        self.executor.submit(self.run_job, action, data, job)
        return job

    def run_job(self, action, data, job):
        mode, coding = data.get('mode', 'HYBRID'), data.get('coding', 'qpsk_1_2')
        try:
            if action == 'boot': self.boot(mode)
            elif action == 'send':
                if self.state['mode'] != mode or not self.state['ready']: self.boot(mode)
                self.message(mode, coding, data['message'], save=True)
            elif action == 'registers': self.inspect_registers(mode)
            elif action == 'dpr': self.dpr_roundtrip(coding, data.get('message') or 'AXIOM REAL PCAP VERIFIED')
            else:
                self.update(comparison={})
                # Each architecture sees the exact same encoded frame and input text.
                prepared = client.prepare(coding, seed=91, text=data['message'])
                for selected in ('PS', 'PL', 'HYBRID'):
                    self.update(requested_mode=selected)
                    self.boot(selected)
                    result = self.message(selected, coding, data['message'], prepared=prepared, save=True)
                    with self.lock:
                        comparison = dict(self.state['comparison']); comparison[selected] = result
                    self.update(comparison=comparison)
                self.update(status='Three-mode sweep complete / exact payload matches')
                self.save_capture('sweep', {'measurement': 'real_board_three_mode_message_sweep', 'recorded_utc': now(),
                                          'coding': coding, 'message': data['message'], 'results': self.state['comparison']})
        except Exception as error:
            self.close_uart()
            self.update(error=str(error), ready=False, status='Hardware operation failed; no software fallback')
            self.log(str(error), 'ERROR', 'error')
        finally: self.update(busy=False)

    def build_firmware(self, mode):
        source_root = PROJECT / MODES[mode][0]
        sw = source_root / 'sw'
        output = HERE / 'build' / mode
        output.mkdir(parents=True, exist_ok=True)
        elf = output / 'uart_bridge.elf'
        files = ['src/uart_bridge.c', 'src/runtime.c']
        arch = MODES[mode][1]
        if arch in (0, 2): files += ['src/helical.c', 'src/derand.c']
        if arch == 2: files += ['src/receiver.c']
        inputs = {name: sha(sw / name) for name in files}
        inputs.update({'linker': sha(HERE / 'firmware.ld'), 'compiler': str(self.gcc), 'arch': arch,
                       'modem': sha(HERE / 'modem.inc'), 'build_policy': 'aligned-access-modem-pool-registers-v5'})
        manifest = output / 'firmware_build.json'
        if elf.exists() and manifest.exists():
            old = json.loads(manifest.read_text())
            if old.get('inputs') == inputs and old.get('elf_sha256') == sha(elf): validate_elf(elf); return elf
        if not self.gcc.is_file(): raise RuntimeError('ARM compiler not found: ' + str(self.gcc))
        relative = lambda path: os.path.relpath(path, sw).replace('\\', '/')
        # Keep all original firmware sources intact. The generated translation unit
        # has only two explicit additions: the modem handler and its UART command.
        original = (sw / 'src/uart_bridge.c').read_text()
        hook = 'void bridge_main(void) {\n'
        sync = 'do{magic=(magic<<8)|uart_getc();}while(magic!=0x4c444143u&&magic!=0x4c444231u);'
        if original.count(hook) != 1 or original.count(sync) != 1:
            raise RuntimeError('Upstream UART bridge changed; review modem integration before building')
        generated = original.replace(hook, '#include "modem.inc"\n' + hook)
        generated = generated.replace(r'b bridge_main\n', r'b bridge_main\n.ltorg\n')
        generated = generated.replace(sync, sync.replace('magic!=0x4c444231u', 'magic!=0x4c444231u&&magic!=0x4c444d31u&&magic!=0x4c445231u') + '\n        if(magic==0x4c444d31u){axiom_modem();continue;}\n        if(magic==0x4c445231u){axiom_registers();continue;}')
        translation = output / 'uart_bridge_modem.c'
        translation.write_text(generated)
        files[0] = relative(translation)
        command = [str(self.gcc), '-std=c11', '-mcpu=cortex-a9', '-mfpu=vfpv3', '-mfloat-abi=hard', '-marm',
                   '-O2', '-mno-unaligned-access', '-Wall', '-Wextra', '-Wno-unused-function', '-Wno-unused-variable', '-Wno-unused-parameter',
                   '-Iinclude', '-I' + relative(HERE), '-nostdlib', '-nostartfiles', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
                   f'-DARCH={arch}', '-Wl,--build-id=none', '-T', relative(HERE / 'firmware.ld'),
                   '-o', relative(elf), *files, '-lgcc', '-e', '_start']
        self.log('Building isolated ' + mode + ' firmware with non-overlapping DDR segments', 'BUILD')
        result = subprocess.run(command, cwd=sw, capture_output=True, text=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode: raise RuntimeError('Firmware build failed: ' + result.stderr[-4000:])
        memory = validate_elf(elf)
        manifest.write_text(json.dumps({'inputs': inputs, 'elf_sha256': sha(elf), 'memory': memory,
                                        'built_utc': now(), 'flags': command[1:]}, indent=2) + '\n')
        return elf

    def xsdb_lines(self, script, arguments, timeout=100):
        if not self.xsdb.is_file(): raise RuntimeError('XSDB not found: ' + str(self.xsdb))
        process = subprocess.Popen([str(self.xsdb), str(script), *map(str, arguments)], cwd=HERE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace',
                                   creationflags=subprocess.CREATE_NO_WINDOW)
        lines = queue.Queue()
        def reader():
            try:
                for line in process.stdout: lines.put(line.rstrip())
            finally: lines.put(None)
        threading.Thread(target=reader, daemon=True).start()
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0: raise TimeoutError('XSDB operation timed out')
                try: line = lines.get(timeout=min(remaining, .5))
                except queue.Empty: continue
                if line is None: break
                if line: yield line
            result = process.wait(timeout=max(.1, deadline - time.monotonic()))
            if result: raise RuntimeError('XSDB failed; inspect JTAG log above')
        finally:
            if process.poll() is None:
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            process.stdout.close()

    def boot(self, mode):
        if mode == 'DPR': return self.dpr_roundtrip()
        self.update(ready=False, requested_mode=mode, stage=0, boot=None, last=None, registers=None, status='Preparing real ' + mode + ' hardware image')
        elf = self.build_firmware(mode)
        self.close_uart()
        self.ensure_debug_service()
        reports = resources(mode)
        if mode != 'PS' and (reports.get('wns_ns') is None or reports.get('whs_ns') is None or reports['wns_ns'] < 0 or reports['whs_ns'] < 0):
            raise RuntimeError('Accelerator routed timing report is missing or fails setup/hold')
        self.log('JTAG boot ' + mode + ' / target XC7Z010 / firmware ' + sha(elf)[:16], 'JTAG')
        loaded = False
        for line in self.xsdb_lines(HERE / 'boot.tcl', [mode, PROJECT, elf]):
            self.log(line, 'JTAG')
            match = re.search(r'AXIOM_STAGE:(\d):(.+)', line)
            if match: self.update(stage=int(match[1]), status=match[2])
            if line == 'AXIOM_LOAD_OK': loaded = True
        if not loaded: raise RuntimeError('JTAG loader did not confirm firmware start')
        # Starting the CPU is not sufficient evidence: verify the binary UART architecture ID and payload.
        self.update(mode=mode, status='Verifying board-returned architecture ID and known message')
        probe = self.transact(mode, 'qpsk_1_2', 'AXIOM BOARD LINK VERIFIED', trace=False)
        if not probe['valid']: raise RuntimeError('Board boot probe returned a payload/CRC failure')
        bit = design_root(mode) / 'hw/vivado/build/ldacs_zed/ldacs_zed.runs/impl_1/system_wrapper.bit'
        evidence = {'mode': mode, 'verified_utc': now(), 'firmware_sha256': sha(elf), 'bitstream_sha256': sha(bit),
                    'entry': validate_elf(elf)['entry'], 'probe': probe}
        self.update(ready=True, mode=mode, stage=6, boot=evidence, status=mode + ' ready / verified physical UART response')
        self.log('BOOT VERIFIED: board architecture=' + probe['architecture'] + '; payload and CRC32 match', 'UART', 'success')

    def transact(self, mode, coding, message, prepared=None, trace=True):
        layout, payload, tx = prepared or client.prepare(coding, seed=91, text=message)
        board = self.open_uart()
        try:
            modem = self.modem(board, coding, tx) if trace else None
            # The decoder receives the actual demapper-returned bits, not an
            # independently re-created host frame or a substituted software result.
            decoder_input = modem.pop('_recovered') if modem else tx
            measured = board.benchmark(layout, payload, decoder_input, iterations=3, warmups=1, architecture=MODES[mode][1])
            if not measured['valid']: raise RuntimeError('Board decoder reported payload mismatch, RS failure, or CRC failure')
            traced = board.trace(layout, payload, decoder_input, architecture=MODES[mode][1]) if trace else None
        except Exception:
            self.close_uart()
            raise
        if traced and not (traced['payload_matches_input'] and all(s['matches_model'] for s in traced['stages'].values()) and traced['rs_failures'] == 0):
            raise RuntimeError('Actual board stage buffers or final payload failed verification')
        stages = []
        for i, name in enumerate(STAGES):
            scope = 'PS' if mode == 'PS' or mode == 'HYBRID' and i in (0, 4) else 'PL'
            record = {'name': name, 'domain': scope, **measured['stage_measurements'][name]}
            if traced: record.update(traced['stages'][name])
            stages.append(record)
        received_bytes = bytes.fromhex(traced['stages']['derandomizer']['output_hex']) if traced else None
        return {'measurement': 'real_board_uart_response', 'recorded_utc': now(), 'mode': mode,
                'architecture': measured['architecture'], 'coding': coding, 'sent': message,
                'received': received_bytes[:len(message.encode('utf-8'))].decode('utf-8') if received_bytes is not None else None,
                'valid': measured['valid'] and (traced is None or traced['payload_matches_input']),
                'payload_bytes': len(payload), 'encoded_bytes': len(tx), 'input_sha256': hashlib.sha256(payload).hexdigest(),
                'encoded_sha256': hashlib.sha256(tx).hexdigest(), 'crc32': f'0x{zlib.crc32(payload):08X}',
                'latency_us': measured['decoder_mean_us'], 'min_us': measured['decoder_min_us'], 'max_us': measured['decoder_max_us'],
                'throughput_MBps': measured['decoder_payload_mbps'] / 8,
                'timer_ticks': measured['decoder_ticks_sum'] / measured['iterations'],
                'cpu_cycles': measured['decoder_ticks_sum'] * 2 / measured['iterations'],
                'global_timer_hz': measured['global_timer_hz'], 'pl_clock_hz': measured['pl_clock_hz'] if mode != 'PS' else None,
                'pipeline_us': measured['pl_pipeline_mean_us'], 'uart_ms': measured['uart_batch_wall_ms'],
                'trace_uart_ms': traced['uart_trace_wall_ms'] if traced else None,
                'modem': modem, 'stages': stages, 'raw_benchmark': measured, 'raw_trace': traced, 'resources': resources(mode),
                'firmware_sha256': (self.state.get('boot') or {}).get('firmware_sha256'),
                'bitstream_sha256': (self.state.get('boot') or {}).get('bitstream_sha256')}

    def modem(self, board, coding, tx):
        modulation = client.L.MODES[coding][0]
        bps = {'QPSK': 2, '16QAM': 4, '64QAM': 6}[modulation]
        started = time.perf_counter()
        board.send(b'LDM1' + struct.pack('<BH', bps, len(tx)) + tx)
        board.magic(b'LDMR')
        got_bps, length, symbols, hz, mapping, demapping = struct.unpack('<BHHIQQ', board.read(25))
        if (got_bps, length, symbols) != (bps, len(tx), len(tx) // bps) or not hz or not mapping or not demapping:
            raise RuntimeError('Invalid board modem metadata or timing counters')
        iq = board.read(symbols * 2)
        recovered = board.read(length)
        if recovered != tx: raise RuntimeError('On-board QAM demapper did not recover the transmitted coded bits')
        # Independently verify every returned hardware I/Q symbol against the
        # documented Gray mapping, rather than trusting only a round-trip check.
        expected = bytearray()
        half = bps // 2; levels = 1 << half
        for start in range(0, len(tx), bps):
            for axis in (0, half):
                gray = 0
                for bit in tx[start + axis:start + axis + half]: gray = gray * 2 + bit
                binary = gray; shifted = gray
                while shifted:
                    shifted >>= 1; binary ^= shifted
                expected.append((2 * binary - levels + 1) & 255)
        if iq != expected: raise RuntimeError('Board I/Q samples do not match the independent Gray-QAM mapping')
        signed = struct.unpack(f'<{symbols * 2}b', iq)
        points = [[signed[i], signed[i + 1]] for i in range(0, len(signed), 2)]
        self.log(f'{modulation}: {symbols} real ARM-mapped I/Q symbols; {length} demapped bits; bit errors=0', 'MODEM', 'success')
        return {'measurement': 'physical_cortex_a9_gray_qam_digital_loopback', 'domain': 'ARM PS in every receiver mode',
                'modulation': modulation, 'bits_per_symbol': bps, 'symbols': symbols, 'bit_errors': 0,
                'mapping_us': mapping * 1e6 / hz, 'demapping_us': demapping * 1e6 / hz,
                'mapping_ticks': mapping, 'demapping_ticks': demapping, 'global_timer_hz': hz,
                'uart_wall_ms': (time.perf_counter() - started) * 1000, 'iq_sha256': hashlib.sha256(iq).hexdigest(),
                'bitstream_sha256': hashlib.sha256(recovered).hexdigest(), 'iq': points,
                'scope': 'Integer baseband Gray QAM loopback; no RF/ADC/DAC/OFDM/channel model', '_recovered': recovered}

    def message(self, mode, coding, message, prepared=None, save=False):
        self.update(status='Encoding and sending actual LDACS frame over ' + self.port)
        self.log('TX ' + mode + ' / ' + coding + ' / UTF-8 ' + str(len(message.encode('utf-8'))) + ' B: ' + message, 'UART')
        result = self.transact(mode, coding, message, prepared)
        self.update(last=result, status='Message recovered and all five board stages verified')
        self.log('RX EXACT MATCH: ' + result['received'], 'UART', 'success')
        self.log('Decoder ' + f"{result['latency_us']:.3f}" + ' us; payload ' + f"{result['throughput_MBps']:.6f}" + ' MB/s; UART batch ' + f"{result['uart_ms']:.1f}" + ' ms', 'TIMER')
        for entry in result['stages']:
            self.log(entry['name'] + ' @' + entry['domain'] + ': ' + f"{entry['mean_us']:.3f}" + ' us; ' + str(entry.get('length', 0)) + ' board bytes; model match=' + str(entry.get('matches_model')), 'TRACE')
        if save: self.save_capture('message', result)
        return result

    def inspect_registers(self, mode):
        if not self.state['ready'] or self.state['mode'] != mode: raise ValueError('Boot this architecture first')
        if mode == 'DPR':
            values = self.board.status()
            registers = [{'address': f'0x{address:08X}', 'value': f'0x{values[name]:08X}'} for address, name in
                         [(0x40000094, 'build_token'), (0x40000088, 'module_id'), (0x40000080, 'isolation_reset'), (0x40000090, 'generation')]]
            self.update(registers={'recorded_utc': now(), 'mode': mode, 'values': registers}, status='Actual DPR shell registers returned over UART')
            return
        board = self.open_uart(); board.send(b'LDR1'); board.magic(b'LDRR')
        architecture, count = struct.unpack('<BB', board.read(2))
        if architecture != MODES[mode][1] or count != 10: raise RuntimeError('Register response architecture/count mismatch')
        values = struct.unpack('<20I', board.read(80))
        registers = [{'address': f'0x{values[i]:08X}', 'value': f'0x{values[i+1]:08X}'} for i in range(0, 20, 2)]
        for entry in registers: self.log(entry['address'] + ' = ' + entry['value'], 'MMIO')
        self.update(registers={'recorded_utc': now(), 'mode': mode, 'values': registers, 'transport': 'ARM MMIO snapshot returned over physical UART'}, status='Actual decoder and DMA registers returned over UART')

    def dpr_roundtrip(self, coding='qpsk_1_2', message='AXIOM REAL PCAP VERIFIED'):
        # Never substitute a static JTAG architecture reload for a partial switch.
        directory = PROJECT / 'DPR/FULL_PL'
        image_path = directory / 'hw/vivado/build/dfx/images.json'
        sys.path.insert(0, str(directory / 'host'))
        module_spec = importlib.util.spec_from_file_location('axiom_dpr_client', directory / 'host/dpr_client.py')
        dpr = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(dpr)
        manifest = dpr.family(image_path)
        self.close_uart()
        self.ensure_debug_service()
        self.update(ready=False, stage=0, boot=None, last=None, requested_mode='DPR', status='Booting verified DFX family before PCAP switching')
        # Build with the existing DPR source, PCAP loader and corrected linker;
        # keep original DPR firmware products unchanged.
        sw = directory / 'sw'; out = HERE / 'build/DPR'; out.mkdir(parents=True, exist_ok=True)
        elf = out / 'uart_bridge.elf'
        relative = lambda p: os.path.relpath(p, sw).replace('\\', '/')
        original = (sw / 'src/uart_bridge.c').read_text()
        hook = 'void bridge_main(void) {\n'
        dispatch = 'if(magic==0x44505331u){dpr_status();continue;}'
        if original.count(hook) != 1 or original.count(dispatch) != 1:
            raise RuntimeError('Review changed DPR firmware before integrating the real modem')
        generated = original.replace(hook, '#include "modem.inc"\n' + hook)
        generated = generated.replace(r'b bridge_main\n', r'b bridge_main\n.ltorg\n')
        generated = generated.replace('magic!=0x4c444231u', 'magic!=0x4c444231u&&magic!=0x4c444d31u&&magic!=0x4c445231u')
        generated = generated.replace(dispatch, 'if(magic==0x4c444d31u){axiom_modem();continue;}\n        if(magic==0x4c445231u){axiom_registers();continue;}\n        ' + dispatch)
        translation = out / 'uart_bridge_modem.c'; translation.write_text(generated)
        command = [str(self.gcc), '-std=c11', '-mcpu=cortex-a9', '-mfpu=vfpv3', '-mfloat-abi=hard', '-marm',
                   '-O2', '-mno-unaligned-access', '-Iinclude', '-Isrc', '-I' + relative(HERE), '-nostdlib', '-nostartfiles', '-ffreestanding',
                   '-fno-builtin', '-fno-stack-protector', '-DARCH=1', '-Wl,--build-id=none',
                   '-T', relative(HERE / 'firmware.ld'), '-o', relative(elf), relative(translation), 'src/runtime.c', '-lgcc', '-e', '_start']
        compiled = subprocess.run(command, cwd=sw, capture_output=True, text=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW)
        if compiled.returncode: raise RuntimeError('DPR firmware build failed: ' + compiled.stderr[-3000:])
        validate_elf(elf)
        loaded = False
        for line in self.xsdb_lines(HERE / 'boot_dpr.tcl', [directory, image_path.parent, elf]):
            self.log(line, 'JTAG')
            if line == 'AXIOM_DPR_LOAD_OK': loaded = True
        if not loaded: raise RuntimeError('DPR firmware start not confirmed')
        board = dpr.DPRBoard(self.port, timeout=600)
        self.board = board
        try:
            before = board.status()
            if before['build_token'] != manifest['build_token']: raise RuntimeError('Running shell has a different image-family token')
            uploads = []
            for name in ('blank', 'full_pl'):
                self.update(status='Uploading verified ' + name + ' partial image over UART (outside switch timing)')
                self.log('Staging ' + name + ' partial into board DDR', 'PCAP')
                uploads.append(board.upload(manifest, name, image_path.parent))
            self.update(status='Performing real PCAP full_pl → blank → full_pl round trip')
            transitions = [board.switch(manifest, 'blank'), board.switch(manifest, 'full_pl')]
            self.update(mode='DPR', boot={'mode': 'DPR', 'firmware_sha256': sha(elf),
                        'bitstream_sha256': manifest['modules']['full_pl']['full_sha256'], 'verified_utc': now()})
            result = self.message('DPR', coding, message, save=True)
            evidence = {'measurement': 'real_board_pcap_roundtrip', 'recorded_utc': now(), 'manifest': manifest,
                        'uploads': uploads, 'switches': transitions, 'post_switch_benchmark': result['raw_benchmark'],
                        'post_switch_trace': result['raw_trace'], 'message': result, 'firmware_sha256': sha(elf)}
        except Exception:
            self.close_uart()
            raise
        self.dpr_verified = evidence
        self.update(mode='DPR', requested_mode='DPR', ready=True, stage=6,
                    status='DPR PCAP round trip verified; ready for real message decoding')
        self.save_capture('dpr_verified', evidence)
        self.log('REAL PCAP VERIFIED; both partial transfers and post-switch decode passed', 'PCAP', 'success')

    def save_capture(self, kind, result):
        directory = HERE / 'captures'; directory.mkdir(exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
        path = directory / f'{kind}_{stamp}.json'
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
        self.log('Saved physical capture: ' + str(path.relative_to(ROOT)), 'HOST')


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def reply(self, status, value, mime='application/json'):
        body = json.dumps(value, ensure_ascii=False).encode('utf-8') if mime == 'application/json' else value
        self.send_response(status); self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(body))); self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff'); self.end_headers(); self.wfile.write(body)
    def allowed(self):
        # Loopback binding plus Host/Origin validation prevents LAN access and cross-origin hardware control.
        host = self.headers.get('Host', '')
        valid = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if host not in valid: return False
        origin = self.headers.get('Origin')
        return origin is None or origin in {'http://' + h for h in valid}
    def do_GET(self):
        if not self.allowed(): return self.reply(403, {'error': 'Local origin required'})
        url = urlparse(self.path)
        if url.path in ('/', '/index.html'): return self.reply(200, (ROOT / 'index.html').read_bytes(), 'text/html')
        if url.path == '/api/status':
            try: after = max(0, int(parse_qs(url.query).get('after', ['0'])[0]))
            except ValueError: return self.reply(400, {'error': 'Invalid cursor'})
            return self.reply(200, self.server.workbench.snapshot(after))
        return self.reply(404, {'error': 'Not found'})
    def do_POST(self):
        if not self.allowed(): return self.reply(403, {'error': 'Local origin required'})
        if not secrets.compare_digest(self.headers.get('X-Axiom-Token', ''), self.server.workbench.token):
            return self.reply(403, {'error': 'Reload the workbench to obtain the local control token'})
        if self.path != '/api/action': return self.reply(404, {'error': 'Not found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 16384: raise ValueError('Invalid request size')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict): raise ValueError('Expected an object')
            job = self.server.workbench.submit(body.get('action'), body)
            return self.reply(202, {'job': job})
        except BlockingIOError as error: return self.reply(409, {'error': str(error)})
        except (ValueError, TypeError) as error: return self.reply(400, {'error': str(error)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', default='COM5')
    parser.add_argument('--http-port', type=int, default=8765)
    parser.add_argument('--xsdb', default=r'C:\Xilinx\Vitis\2022.2\bin\xsdb.bat')
    parser.add_argument('--gcc', default=r'C:\Xilinx\Vitis\2022.2\gnu\aarch32\nt\gcc-arm-none-eabi\bin\arm-none-eabi-gcc.exe')
    parser.add_argument('--build-only', action='store_true')
    arguments = parser.parse_args()
    workbench = Workbench(arguments.port, arguments.xsdb, arguments.gcc)
    if arguments.build_only:
        for mode in ('PS', 'PL', 'HYBRID'): print(mode, workbench.build_firmware(mode), flush=True)
        return
    server = ThreadingHTTPServer(('127.0.0.1', arguments.http_port), Handler)
    server.daemon_threads = True; server.workbench = workbench
    workbench.log('Physical-board message bridge ready. No simulation fallback. Close other COM5 clients.')
    print(f'AXIOM hardware workbench: http://127.0.0.1:{arguments.http_port}', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); workbench.executor.shutdown(wait=True); workbench.close_uart()


if __name__ == '__main__': main()
