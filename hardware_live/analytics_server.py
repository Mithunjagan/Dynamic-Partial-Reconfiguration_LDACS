"""Fresh-only analytics over the existing physical bridge. Never opens COM5.

python hardware_live/analytics_server.py --start
The running bridge on 127.0.0.1:8765 retains sole ownership of the board.
No prior capture, simulation, report, or fixture is loaded as a measurement.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.request
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BRIDGE = 'http://127.0.0.1:8765'
MODES = ['PS', 'PL', 'HYBRID', 'DPR']
STAGES = ['helical', 'viterbi', 'block_deinterleaver', 'reed_solomon', 'derandomizer']

def now(): return datetime.now(timezone.utc).isoformat()
def read_bridge():
    with urllib.request.urlopen(BRIDGE + '/api/status?after=2147483647', timeout=12) as response:
        s = json.load(response)
    if s.get('source') != 'physical_hardware_only':
        raise RuntimeError('The bridge does not identify physical hardware; refusing measurements')
    return s

def verified(r, mode, coding, message, started):
    """Check identity, time, payload, raw counters and all returned stage buffers."""
    if r.get('measurement') != 'real_board_uart_response' or r.get('mode') != mode or r.get('coding') != coding:
        raise RuntimeError('Unexpected board measurement identity')
    if datetime.fromisoformat(r['recorded_utc']) < datetime.fromisoformat(started):
        raise RuntimeError('Stale measurement rejected')
    if r.get('sent') != message or r.get('received') != message or r.get('valid') is not True:
        raise RuntimeError('Exact physical payload recovery failed')
    b, modem = r['raw_benchmark'], r['modem']
    if not b['valid'] or b['crc_failed_frames'] or b['rs_failures'] or not b['last_output_matches']:
        raise RuntimeError('Raw decoder validation failed')
    calculated = b['decoder_ticks_sum'] / b['iterations'] / b['global_timer_hz'] * 1e6
    if abs(calculated - r['latency_us']) > max(1e-7, calculated * 1e-10):
        raise RuntimeError('Counter-derived latency does not reconcile')
    if modem.get('measurement') != 'physical_cortex_a9_gray_qam_digital_loopback' or modem['bit_errors']:
        raise RuntimeError('Physical modem verification failed')
    if len(r['stages']) != 5 or [s['name'] for s in r['stages']] != STAGES:
        raise RuntimeError('Incomplete decoder trace')
    for s in r['stages']:
        if not s.get('matches_model') or hashlib.sha256(bytes.fromhex(s['output_hex'])).hexdigest() != s['sha256']:
            raise RuntimeError('Stage-buffer integrity failed: ' + s['name'])
    if hashlib.sha256(bytes.fromhex(r['stages'][-1]['output_hex'])).hexdigest() != r['input_sha256']:
        raise RuntimeError('Final physical output hash differs from input frame')
    if not r.get('firmware_sha256') or not r.get('bitstream_sha256'):
        raise RuntimeError('Running-image provenance is absent')

class Analytics:
    def __init__(self):
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)
        self.stop = threading.Event()
        self.state = dict(schema='fresh_physical_analytics_v1', source='physical_hardware_only',
            service_started_utc=now(), run_id=None, started_utc=None, finished_utc=None,
            running=False, live=False, phase='Ready to collect fresh board measurements',
            error=None, failures=[], modes=[], profiles=[], results=[], boots=[], dpr=None,
            completed=0, expected=0, excluded='No prior captures, stored benchmark values, simulated data or stored utilization/power reports are used.',
            limits=dict(scope='Physical digital baseband loopback, not an RF link or independent LDACS conformance test',
                decoder='Three resident-frame decodes after one warm-up; DMA/control included; modem, UART, CRC, output copy and trace excluded',
                stages='Stage durations overlap. Do not add them.',
                throughput='Padded frame payload bytes × 8 / decoder elapsed time; decimal Mbit/s. Not sustained UART/RF rate.',
                host='HTTP-observed send wall time includes modem, UART, decode, verification, trace and polling; excludes architecture boot.',
                statistics='Min/max are observed firmware extrema over three decodes. Individual samples and p95/p99 are unavailable.',
                clocks='Firmware-reported SLCR clock divisors with nominal board reference; not externally calibrated.',
                unavailable=['Measured power / energy', 'CPU utilization / retired instructions', 'RF BER versus SNR', 'Continuous-ingestion throughput', 'Fresh implementation LUT/FF/BRAM/DSP allocation', 'Independent LDACS conformance']))
        self.directory = None

    def update(self, **kwargs):
        with self.lock: self.state.update(kwargs)

    def save(self):
        with self.lock:
            if self.directory:
                path = self.directory / 'evidence.json'
                temp = self.directory / 'evidence.tmp'
                temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
                temp.replace(path)

    def snapshot(self, full=False):
        with self.lock:
            s = dict(self.state)
            if not full:
                rows = []
                for r in s['results']:
                    row = {k:v for k,v in r.items() if k not in ('raw_benchmark','raw_trace','modem','stages')}
                    row['stages'] = [{k:v for k,v in st.items() if k != 'output_hex'} for st in r['stages']]
                    row['modem'] = {k:v for k,v in r['modem'].items() if k != 'iq'}
                    b = r['raw_benchmark']
                    row['checks'] = {k:b[k] for k in ('iterations','warmups','crc_failed_frames','rs_failures','rs_corrections')}
                    rows.append(row)
                s['results'] = rows
                s['boots'] = [{k:v for k,v in b.items() if k != 'evidence'} for b in s['boots']]
                if s['dpr']:
                    s['dpr'] = {k:s['dpr'].get(k) for k in ('measurement','recorded_utc','switches','uploads')}
            s['token'] = self.token
        try:
            b = read_bridge()
            s['bridge'] = {k:b.get(k) for k in ('busy','ready','mode','requested_mode','status','error','transport')}
            s['available_profiles'] = b['coding_modes']
            s['dpr_available'] = b['dpr']['available']
        except Exception as e:
            s['bridge'] = {'error':str(e), 'ready':False, 'transport':{'present':False}}
        return s

    def action(self, action, mode, coding, message):
        s = read_bridge()
        if s['busy']: raise RuntimeError('Board is busy with another client; no operation was interrupted')
        body = json.dumps(dict(action=action,mode=mode,coding=coding,message=message)).encode()
        req = urllib.request.Request(BRIDGE+'/api/action', data=body,
            headers={'Content-Type':'application/json','X-Axiom-Token':s['token']})
        with urllib.request.urlopen(req, timeout=12) as response: job = json.load(response)['job']
        deadline = time.monotonic() + (1200 if mode == 'DPR' and action == 'boot' else 240)
        while True:
            s = read_bridge()
            if s['job'] != job: raise RuntimeError('Another controller replaced the active hardware job')
            if not s['busy']: break
            self.update(phase=s['status'])
            if time.monotonic() > deadline: raise TimeoutError('Physical bridge job exceeded its deadline')
            time.sleep(.4)
        if s['error']: raise RuntimeError(s['error'])
        return s

    def start(self, live=False, include_dpr=True, repeat_all=False):
        with self.lock:
            if self.state['running']: raise BlockingIOError('A fresh campaign is already running')
            b = read_bridge()
            if b['busy']: raise BlockingIOError('Physical board is already busy')
            if not b['transport']['present']: raise ValueError('Physical UART is absent')
            run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S_%fZ')
            self.directory = ROOT / 'benchmarks' / 'live_analytics' / run_id
            self.directory.mkdir(parents=True, exist_ok=False)
            modes = MODES if include_dpr and b['dpr']['available'] else MODES[:3]
            self.state.update(run_id=run_id, started_utc=now(), finished_utc=None, running=True,
                live=bool(live), repeat_all=bool(repeat_all), cycle=1, phase='Starting fresh physical campaign', error=None,
                modes=list(modes), profiles=list(b['coding_modes']), results=[], boots=[], dpr=None, failures=[],
                completed=0, expected=len(modes)*len(b['coding_modes']),
                evidence_path=str(self.directory/'evidence.json'))
            self.stop.clear()
        self.save()
        threading.Thread(target=self.run, name='fresh-physical-analytics',daemon=True).start()
        return run_id

    def measure(self, mode, coding, message):
        started = now()
        t = time.perf_counter()
        s = self.action('send',mode,coding,message)
        wall = (time.perf_counter()-t)*1000
        r = s['last']
        verified(r,mode,coding,message,started)
        # Stored implementation reports are deliberately excluded from this dataset.
        r.pop('resources',None)
        r.update(request_started_utc=started, host_observed_ms=wall,
            message_bytes=len(message.encode('utf-8')), payload_mbps=r['throughput_MBps']*8,
            frames_per_second=1e6/r['latency_us'])
        with self.lock:
            peers = [p for p in self.state['results'] if p['coding']==coding]
            if any(p['input_sha256']!=r['input_sha256'] or p['encoded_sha256']!=r['encoded_sha256'] for p in peers):
                raise RuntimeError('Cross-architecture input frames are not identical')
            self.state['results'].append(r)
            self.state['completed'] = len({(p['mode'],p['coding']) for p in self.state['results']})
        self.save()
        print(f"FRESH_PASS {mode} {coding} {r['latency_us']:.3f} us",flush=True)

    def resume_campaign(self, run_id, live=False, repeat_all=False):
        """Continue only an explicitly selected campaign, retaining its original dates."""
        if not re.fullmatch(r'\d{8}T\d{6}_\d{6}Z',run_id):
            raise ValueError('Invalid campaign identity')
        directory=ROOT/'benchmarks/live_analytics'/run_id
        state=json.loads((directory/'evidence.json').read_text(encoding='utf-8'))
        if state.get('schema')!='fresh_physical_analytics_v1' or state.get('run_id')!=run_id:
            raise ValueError('Wrong campaign evidence')
        for r in state['results']:
            if datetime.fromisoformat(r['request_started_utc'])<datetime.fromisoformat(state['started_utc']):
                raise ValueError('Pre-campaign measurement rejected')
            verified(r,r['mode'],r['coding'],r['sent'],r['request_started_utc'])
        if read_bridge()['busy']:raise BlockingIOError('Board is busy')
        self.state=state;self.directory=directory
        self.state.update(running=True,live=live,repeat_all=repeat_all,error=None,finished_utc=None,resumed_utc=now(),phase='Continuing missing entries in the same campaign')
        self.stop.clear();self.save()
        threading.Thread(target=self.run,name='fresh-physical-analytics',daemon=True).start()

    def sweep(self, message, force=False):
        for mode in self.state['modes']:
            if self.stop.is_set(): break
            done={(r['mode'],r['coding']) for r in self.state['results']}
            missing=[c for c in self.state['profiles'] if force or (mode,c) not in done]
            if not missing:continue
            try:
                self.update(phase='Loading and verifying '+mode)
                start = time.perf_counter()
                for attempt in range(3):
                    try:
                        s = self.action('boot',mode,self.state['profiles'][0],message)
                        break
                    except RuntimeError as error:
                        if str(error) != 'Board short read: 0/4 bytes' or attempt == 2:raise
                        with self.lock:
                            self.state['failures'].append(dict(mode=mode,recorded_utc=now(),error=str(error),boot_attempt=attempt+1))
                        self.save()
                        self.update(phase='Retrying physical '+mode+' startup after an empty UART boot response')
                with self.lock:
                    self.state['boots'].append(dict(mode=mode,recorded_utc=now(),
                        host_observed_seconds=time.perf_counter()-start,evidence=s['boot']))
                    if mode=='DPR': self.state['dpr']=s['dpr'].get('evidence')
                self.save()
                for coding in missing:
                    if self.stop.is_set(): break
                    self.update(phase='Measuring '+mode+' / '+coding)
                    self.measure(mode,coding,message)
                with self.lock:
                    covered={r['coding'] for r in self.state['results'] if r['mode']==mode}
                    if all(c in covered for c in self.state['profiles']):
                        for failure in self.state['failures']:
                            if failure['mode']==mode:failure['resolved_utc']=now()
            except Exception as e:
                with self.lock:
                    self.state['failures'].append(dict(mode=mode,recorded_utc=now(),error=str(e)))
                self.save()
                print('ARCHITECTURE_FAILED '+mode+' '+repr(e),flush=True)

    def run(self):
        try:
            message = 'LDACS faculty benchmark / ' + self.state['run_id']
            self.sweep(message)
            # Continuous mode samples the currently loaded entry; never fabricates a time series.
            while self.state['live'] and not self.stop.is_set() and (self.state.get('repeat_all') or read_bridge()['ready']):
                if self.state.get('repeat_all'):
                    self.update(cycle=self.state.get('cycle',1)+1,phase='Repeating the full physical comparison sequentially')
                    if self.stop.wait(5):break
                    self.sweep(message,force=True)
                    continue
                mode=read_bridge()['mode']
                if mode not in self.state['modes']:raise RuntimeError('Unexpected live architecture')
                self.update(phase='Live sampling '+mode+' / '+self.state['profiles'][0],
                    live_entry=dict(mode=mode,coding=self.state['profiles'][0]))
                if self.stop.wait(5): break
                self.measure(mode,self.state['profiles'][0],message)
            self.update(phase='Stopped after current hardware job' if self.stop.is_set() else
                'Fresh campaign complete'+(' with unavailable entries' if any(not f.get('resolved_utc') for f in self.state['failures']) else ''))
        except Exception as e:
            self.update(error=str(e),phase='Hardware campaign stopped: '+str(e))
            print('CAMPAIGN_FAILED '+repr(e),flush=True)
        finally:
            self.update(running=False,finished_utc=now())
            self.save()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def allowed(self):
        hosts={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        return self.headers.get('Host') in hosts and self.headers.get('Origin') in {None,*('http://'+h for h in hosts)}
    def reply(self,code,value,mime='application/json'):
        body = json.dumps(value,ensure_ascii=False).encode() if mime=='application/json' else value
        self.send_response(code)
        for k,v in [('Content-Type',mime+'; charset=utf-8'),('Content-Length',str(len(body))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]:self.send_header(k,v)
        self.end_headers()
        try:self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError):pass
    def do_GET(self):
        if not self.allowed():return self.reply(403,{'error':'Local origin required'})
        path=urlparse(self.path).path
        if path=='/':return self.reply(200,(ROOT/'hardware_live/analytics.html').read_bytes(),'text/html')
        if path=='/api/analytics':return self.reply(200,self.server.analytics.snapshot())
        if path=='/api/evidence':
            value=self.server.analytics.snapshot(full=True);value.pop('token',None)
            return self.reply(200,value)
        return self.reply(404,{'error':'Not found'})
    def do_POST(self):
        if not self.allowed():return self.reply(403,{'error':'Local origin required'})
        if not secrets.compare_digest(self.headers.get('X-Analytics-Token',''),self.server.analytics.token):
            return self.reply(403,{'error':'Reload analytics to obtain a control token'})
        try:
            n=int(self.headers.get('Content-Length','0'))
            if not 0<n<=2048:raise ValueError('Invalid request size')
            data=json.loads(self.rfile.read(n))
            if self.path=='/api/start':return self.reply(202,{'run_id':self.server.analytics.start(bool(data.get('live')),bool(data.get('include_dpr',True)),bool(data.get('repeat_all')))})
            if self.path=='/api/stop':
                self.server.analytics.stop.set()
                return self.reply(202,{'status':'Stopping after the active physical job finishes'})
            return self.reply(404,{'error':'Unknown action'})
        except BlockingIOError as e:return self.reply(409,{'error':str(e)})
        except (ValueError,TypeError) as e:return self.reply(400,{'error':str(e)})
        except Exception as e:return self.reply(503,{'error':str(e)})

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--http-port',type=int,default=8767)
    p.add_argument('--start',action='store_true')
    p.add_argument('--live',action='store_true')
    p.add_argument('--no-dpr',action='store_true')
    p.add_argument('--repeat-all',action='store_true',help='Continuously repeat all architectures/profiles instead of sampling only the current entry')
    p.add_argument('--resume',help='Explicit campaign ID to continue missing entries; preserves original measurement dates')
    args=p.parse_args()
    a=Analytics()
    server=ThreadingHTTPServer(('127.0.0.1',args.http_port),Handler)
    server.daemon_threads=True;server.analytics=a
    print(f'Fresh physical analytics http://127.0.0.1:{args.http_port}',flush=True)
    if args.resume:a.resume_campaign(args.resume,args.live,args.repeat_all)
    elif args.start:a.start(args.live,not args.no_dpr,args.repeat_all)
    try:server.serve_forever()
    except KeyboardInterrupt:a.stop.set()
    finally:server.server_close()

if __name__=='__main__':main()
