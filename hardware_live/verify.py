"""Cross-check the live HTTP -> UART -> actual board -> HTTP message path.

Requires server.py and a connected XC7Z010. No fake transport or model fallback.
"""
import argparse
import json
from pathlib import Path
import time
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8765')
    parser.add_argument('--mode', choices=['all', 'PS', 'PL', 'HYBRID'], default='all')
    parser.add_argument('--coding', default='all')
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'captures/api_verification.json')
    parser.add_argument('--resume', action='store_true', help='Retain completed real cases from the same firmware images')
    args = parser.parse_args()
    def status():
        with urllib.request.urlopen(args.url + '/api/status', timeout=10) as response:
            return json.load(response)
    initial = status()
    if initial['busy']: raise SystemExit('Board is busy; wait for the current operation')
    profiles = list(initial['coding_modes']) if args.coding == 'all' else [args.coding]
    if any(coding not in initial['coding_modes'] for coding in profiles): raise SystemExit('Unknown coding profile')
    modes = ['PS', 'PL', 'HYBRID'] if args.mode == 'all' else [args.mode]
    capture = {'measurement': 'physical_board_api_integration_verification', 'results': [], 'complete': False}
    if args.resume and args.output.exists():
        import hashlib
        capture = json.loads(args.output.read_text(encoding='utf-8'))
        if capture.get('measurement') != 'physical_board_api_integration_verification': raise RuntimeError('Wrong capture schema')
        for row in capture['results']:
            image = Path(__file__).parent / 'build' / row['mode'] / 'uart_bridge.elf'
            if row.get('firmware_sha256') != hashlib.sha256(image.read_bytes()).hexdigest():
                raise RuntimeError('Cannot combine verification across different firmware images')
        capture['complete'] = False
    completed = {(r['mode'], r['coding']) for r in capture['results']}
    for mode in modes:
        for coding in profiles:
            if (mode, coding) in completed: continue
            message = f'Cross-check {mode} {coding}: Hello from real hardware!'
            data = json.dumps({'action': 'send', 'mode': mode, 'coding': coding, 'message': message}).encode()
            request = urllib.request.Request(args.url + '/api/action', data=data,
                       headers={'Content-Type': 'application/json', 'X-Axiom-Token': initial['token']})
            with urllib.request.urlopen(request, timeout=10) as response: job = json.load(response)['job']
            deadline = time.monotonic() + 180
            while True:
                s = status()
                if s['job'] != job: raise RuntimeError('Another client replaced the verification job')
                if not s['busy']: break
                if time.monotonic() > deadline: raise TimeoutError('Hardware job exceeded 180 seconds')
                time.sleep(.8)
            if s['error']: raise RuntimeError(s['error'])
            result = s['last']
            assert result['measurement'] == 'real_board_uart_response'
            assert result['mode'] == mode and result['coding'] == coding
            assert result['sent'] == result['received'] == message
            assert result['valid'] and result['raw_benchmark']['crc_failed_frames'] == 0
            assert result['modem']['measurement'] == 'physical_cortex_a9_gray_qam_digital_loopback'
            assert result['modem']['bit_errors'] == 0
            assert result['modem']['symbols'] * result['modem']['bits_per_symbol'] == result['encoded_bytes']
            assert all(stage['matches_model'] for stage in result['stages'])
            assert all(stage['domain'] == ('PS' if mode == 'PS' or mode == 'HYBRID' and i in (0, 4) else 'PL')
                       for i, stage in enumerate(result['stages']))
            capture['results'].append(result)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(capture, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            print(f"PASS {mode:6} {coding:12} exact message; 0 modem errors; 5/5 stage matches; {result['latency_us']:.3f} us", flush=True)
    capture['complete'] = all((mode, coding) in {(r['mode'], r['coding']) for r in capture['results']} for mode in modes for coding in profiles)
    args.output.write_text(json.dumps(capture, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"PASS {len(capture['results'])} physical modem/decoder combinations. Evidence: {args.output}")


if __name__ == '__main__': main()
