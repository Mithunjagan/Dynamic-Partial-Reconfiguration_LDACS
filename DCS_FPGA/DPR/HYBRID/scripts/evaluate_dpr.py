"""Boot and evaluate actual PCAP partial swaps on the EDGE Z7-10.

The FPGA is programmed once at boot. Subsequent swaps use the ARM PCAP loader.
Raw responses, continuity observations and failures are retained as evidence.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'host'))
import dpr_client as client


def debug_service():
    try:
        with socket.create_connection(('127.0.0.1',3121),timeout=1):
            return
    except OSError:
        executable=Path('C:/Xilinx/Vitis/2022.2/bin/unwrapped/win64.o/hw_server.exe')
        subprocess.Popen([str(executable),'-s','tcp:127.0.0.1:3121'],
                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                         creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            try:
                with socket.create_connection(('127.0.0.1',3121),timeout=.3):return
            except OSError:time.sleep(.2)
        raise RuntimeError('Xilinx hardware service did not start')


class ProgressSerial:
    def __init__(self, port):
        self.port=port;self.upload=None;self.bytes=0;self.quarter=1
    def __getattr__(self,name):return getattr(self.port,name)
    def write(self,data):
        result=self.port.write(data)
        if self.upload and len(data)>32:
            self.bytes+=result
            if self.bytes*4>=self.upload[1]*self.quarter:
                print('UPLOAD_PROGRESS',self.upload[0],min(100,int(self.bytes*100/self.upload[1])),flush=True)
                self.quarter+=1
        return result


class Board(client.DPRBoard):
    def upload(self,manifest,module,directory):
        print('UPLOAD_START',module,manifest['modules'][module]['partial_bytes'],flush=True)
        self.serial.upload=(module,manifest['modules'][module]['partial_bytes'])
        self.serial.bytes=0;self.serial.quarter=1
        result=super().upload(manifest,module,directory)
        self.serial.upload=None
        print('UPLOAD_PASS',module,round(result['host_upload_seconds'],3),flush=True)
        return result
    def switch(self,manifest,module):
        print('PCAP_START',module,flush=True)
        result=super().switch(manifest,module)
        print('PCAP_PASS',module,'pcap_us',round(result['microseconds']['pcap'],3),
              'static_samples',result['static_continuity']['samples'],flush=True)
        return result
    def benchmark(self,layout,payload,tx,iterations=20,warmups=2,architecture=0):
        result=super().benchmark(layout,payload,tx,iterations,warmups,architecture)
        mode=next(name for name in client.base.L.MODES if client.base.L.frame_layout(name)==layout)
        print('DECODE',mode,iterations,'PASS' if result['valid'] else 'FAIL',
              'mean_us',round(result['decoder_mean_us'],3),flush=True)
        if not result['valid']:raise RuntimeError('Decode failed: '+mode)
        return result


def reject_safely(board,packet,error_code):
    before=board.status()
    board.send(packet)
    if board.read(4)!=b'DPRE' or struct.unpack('<I',board.read(4))[0]!=error_code:
        raise RuntimeError('Invalid request was not rejected safely')
    after=board.status()
    fields=('build_token','module_id','isolation_reset','generation')
    if any(before[k]!=after[k] for k in fields) or after['isolation_reset']:
        raise RuntimeError('Rejected request changed the running configuration')
    return {'expected_error':error_code,'before':before,'after':after,'passed':True}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--images',type=Path,default=ROOT/'hw/vivado/build_dpr/dfx/images.json')
    parser.add_argument('--port',default='COM5')
    parser.add_argument('--switches',type=int,default=3)
    parser.add_argument('--iterations',type=int,default=20)
    parser.add_argument('--warmups',type=int,default=2)
    parser.add_argument('--batches',type=int,default=5)
    parser.add_argument('--no-boot',action='store_true')
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if not 1<=args.switches<=100 or not 1<=args.iterations<=1000 or not 0<=args.warmups<=100 or args.batches<1:
        parser.error('Invalid switch count or benchmark repetitions')
    manifest=client.family(args.images)
    if manifest['schema']!='ldacs_dpr_image_family_v1' or manifest.get('static_monitor_version')!=1:
        raise RuntimeError('This evaluation requires the new verified DPR family with continuity monitor v1')
    output=args.output or ROOT/'results'/datetime.now(timezone.utc).strftime('dpr_%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True,exist_ok=False)
    (ROOT/'results/latest_dpr_evaluation_path.txt').write_text(str(output.resolve()))
    record={'measurement':'physical_board_hybrid_dpr_evaluation','started_utc':datetime.now(timezone.utc).isoformat(),
            'passed':False,'image_family':manifest,'port':args.port}
    start=time.perf_counter();board=None
    def save():
        (output/'evaluation.json').write_text(json.dumps(record,indent=2)+'\n')
    save()
    try:
        if not args.no_boot:
            debug_service();boot_start=time.perf_counter()
            with (output/'boot.log').open('w') as log:
                boot=subprocess.run(['C:/Xilinx/Vitis/2022.2/bin/xsdb.bat',str(ROOT/'boot_firmware.tcl'),
                                     str(args.images.parent)],stdout=log,stderr=subprocess.STDOUT,timeout=180,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            record['boot_seconds']=time.perf_counter()-boot_start
            if boot.returncode or 'BOOT_OK:' not in (output/'boot.log').read_text():
                raise RuntimeError('DPR boot failed; see boot.log')
            print('DPR_BOOT_PASS',round(record['boot_seconds'],3),flush=True)
        board=Board(args.port,timeout=60);board.serial=ProgressSerial(board.serial)
        record['initial_status']=board.status()
        layout,payload,tx=client.base.prepare('qpsk_1_2',91)
        record['before_dpr_decode']=board.benchmark(layout,payload,tx,1,0,0)
        record['safe_rejections']=[
            reject_safely(board,b'DPR1'+bytes([99]),4),
            reject_safely(board,b'DPU1'+struct.pack('<BIII',0,manifest['build_token']^1,4,0),1)]
        save()
        capture=client.collect(board,args.images,list(client.base.L.MODES),args.iterations,
                               args.warmups,args.batches,args.switches,91)
        capture['board_label']='EDGE Z7-10 / XC7Z010CLG400-1'
        if capture['architecture']!='DPR_HYBRID' or not capture['valid']:
            raise RuntimeError('No valid DPR_HYBRID capture')
        (output/'benchmark.json').write_text(json.dumps(capture,indent=2)+'\n')
        traces={}
        for mode in client.base.L.MODES:
            layout,payload,tx=client.base.prepare(mode,91)
            trace=board.trace(layout,payload,tx,0)
            trace['valid']=trace['payload_matches_input'] and not trace['rs_failures'] and all(s['matches_model'] for s in trace['stages'].values())
            traces[mode]=trace
            (output/'traces.json').write_text(json.dumps(traces,indent=2)+'\n')
            print('POST_DPR_TRACE',mode,'PASS' if trace['valid'] else 'FAIL',flush=True)
            if not trace['valid']:raise RuntimeError('Post-DPR stage mismatch: '+mode)
        record['final_status']=board.status()
        record['switches']=capture['switches']
        record['post_dpr_modes']=len(capture['results'])
        record['post_dpr_timed_frames']=sum(s['iterations'] for r in capture['results'] for s in r['samples'])
        record['stage_buffer_checks']=sum(len(t['stages']) for t in traces.values())
        record['passed']=True
        print('REAL_DPR_EVALUATION_PASS',record['post_dpr_timed_frames'],'frames',
              len(record['switches']),'partial_transfers',record['stage_buffer_checks'],'stage_checks',flush=True)
    except Exception as error:
        record['error']=repr(error)
        print('DPR_EVALUATION_FAILED',error,flush=True)
        raise
    finally:
        if board is not None:board.close()
        record['finished_utc']=datetime.now(timezone.utc).isoformat()
        record['wall_seconds']=time.perf_counter()-start;save()
        print('DPR_EVIDENCE',output.resolve(),flush=True)


if __name__=='__main__':
    main()
