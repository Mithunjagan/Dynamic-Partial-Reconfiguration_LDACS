"""Finish the active real DFX build, package verified images, and run board PCAP checks.

This is a bounded one-shot build companion, not a simulated or scheduled mode.
"""
import json
from pathlib import Path
import subprocess
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
VIVADO = ROOT / 'DCS_FPGA/DPR/FULL_PL/hw/vivado'
MANIFEST = VIVADO / 'build/dfx/routed_manifest.json'
BASE = 'http://127.0.0.1:8765'


def status():
    with urllib.request.urlopen(BASE + '/api/status', timeout=15) as response:
        return json.load(response)


def main():
    deadline = time.monotonic() + 40 * 60
    print('Waiting for routed, timing/DRC/pr_verify-checked DFX family.', flush=True)
    while time.monotonic() < deadline:
        try: marker = json.loads(MANIFEST.read_text())
        except (OSError, ValueError): marker = {}
        if marker.get('pr_verify_passed'): break
        try: tail = (VIVADO / 'build_live.log').read_text(errors='replace')[-8000:]
        except OSError: tail = ''
        if 'Exiting Vivado' in tail and ('ERROR:' in tail or 'Timing failed' in tail or 'DFX DRC failed' in tail):
            raise RuntimeError('DPR build did not pass; inspect DCS_FPGA/DPR/FULL_PL/hw/vivado/build_live.log')
        time.sleep(10)
    else: raise TimeoutError('Bounded wait expired; no completed DFX family is claimed')
    subprocess.run([sys.executable, str(ROOT / 'DCS_FPGA/DPR/FULL_PL/scripts/package_images.py')], check=True)
    print('Image family packaged. Waiting for exclusive board access.', flush=True)
    while True:
        s = status()
        verification = ROOT / 'hardware_live/captures/api_verification_final.json'
        try: static_complete = json.loads(verification.read_text()).get('complete', False)
        except (OSError, ValueError): static_complete = False
        if not s['busy'] and static_complete:
            request = urllib.request.Request(BASE + '/api/action', data=b'{"action":"dpr","mode":"PL"}',
                      headers={'Content-Type': 'application/json', 'X-Axiom-Token': s['token']})
            try:
                with urllib.request.urlopen(request, timeout=20) as response: job = json.load(response)['job']
                break
            except urllib.error.HTTPError as error:
                if error.code != 409: raise
        if time.monotonic() > deadline: raise TimeoutError('No exclusive board slot before deadline')
        time.sleep(2)
    print('Actual board PCAP round trip started; UART image staging can take several minutes.', flush=True)
    last = None
    while True:
        s = status()
        if s['job'] != job: raise RuntimeError('DPR job was replaced by another client')
        if s['status'] != last: print(s['status'], flush=True); last = s['status']
        if not s['busy']: break
        if time.monotonic() > deadline: raise TimeoutError('DPR board operation exceeded the bounded wait')
        time.sleep(2)
    if s['error'] or not s['dpr']['hardware_verified']:
        raise RuntimeError(s['error'] or 'No verified physical PCAP evidence')
    print('PASS: real PCAP blank/full_pl round trip and post-switch message/stage checks.', flush=True)


if __name__ == '__main__': main()
