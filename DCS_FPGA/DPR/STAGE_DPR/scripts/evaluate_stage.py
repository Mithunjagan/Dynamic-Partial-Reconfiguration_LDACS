"""One full boot, cached partials, real stage swaps and exact DDR-buffer checks."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'host'))
import stage_client as client


def main():
    p=argparse.ArgumentParser();p.add_argument('--port',default='COM5');p.add_argument('--no-boot',action='store_true')
    p.add_argument('--output',type=Path);a=p.parse_args()
    images=ROOT/'hw/vivado/build_dpr/dfx/images.json';family=client.family(images)
    directory=a.output or ROOT/'results'/datetime.now(timezone.utc).strftime('onboard_%Y%m%dT%H%M%SZ')
    directory.mkdir(parents=True,exist_ok=False)
    (ROOT/'results/latest_path.txt').write_text(str(directory.resolve()))
    record=dict(measurement='physical_board_stage_multiplexed_ldacs_dpr',passed=False,
                started_utc=datetime.now(timezone.utc).isoformat(),family=family,batches=[],uploads=[],
                scope='Two genuine swaps per batch; all frames buffered in DDR; includes image CRC precheck in service time',
                cache_policy='Single Cortex-A9, I/D caches disabled',warmups=0,
                firmware=json.loads((ROOT/'sw/dpr/firmware_build.json').read_text()))
    start=time.perf_counter();board=None
    def save(): (directory/'evaluation.json').write_text(json.dumps(record,indent=2)+'\n')
    save()
    try:
        if not a.no_boot:
            client.debug_service();boot_start=time.perf_counter()
            with (directory/'boot.log').open('w') as log:
                boot=subprocess.run(['C:/Xilinx/Vitis/2022.2/bin/xsdb.bat',str(ROOT/'boot_firmware.tcl')],
                    stdout=log,stderr=subprocess.STDOUT,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            if boot.returncode or 'BOOT_OK:' not in (directory/'boot.log').read_text():raise RuntimeError('Stage boot failed')
            record['boot_seconds']=time.perf_counter()-boot_start;print('STAGE_BOOT_PASS',flush=True)
        board=client.Board(a.port,timeout=1);board.serial=client.ProgressSerial(board.serial)
        # XSDB con returns before C startup has finished clearing BSS/resetting UART.
        # Retry only the read-only identity handshake; never retry a partial load.
        deadline=time.monotonic()+10
        while True:
            try:
                record['initial_status']=board.status();break
            except TimeoutError:
                if time.monotonic()>deadline:raise
                time.sleep(.2)
        board.timeout=90
        if record['initial_status']['build_token']!=family['build_token']:raise RuntimeError('Wrong running family')
        for stage in ('viterbi','rs'):
            record['uploads'].append(board.upload(family,stage,images.parent));save()
        # Refuse RS work before a valid Viterbi batch exists.
        before=board.status();board.send(b'SBR1')
        if board.read(4)!=b'DPRE' or struct.unpack('<I',board.read(4))[0]!=23:raise RuntimeError('Stage-order rejection failed')
        after=board.status()
        if any(before[k]!=after[k] for k in ('module_id','generation','isolation_reset','build_token')):raise RuntimeError('Rejected request changed hardware state')
        record['safe_stage_order_rejection']=True;save()
        cases=[(mode,1) for mode in client.L.MODES]+[('qpsk_1_2',8),('qpsk_1_2',32)]
        for mode,count in cases:
            layout,frames=client.frames(mode,count)
            row=dict(mode=mode,count=count,layout=layout,seed=91,switches=[],traces=[])
            record['batches'].append(row);save()
            row['input_ack']=board.batch_load(layout,frames)
            execution_start=time.perf_counter()
            row['switches'].append(board.switch(family,'viterbi'));save()
            row['viterbi_ack']=board.viterbi(count);save()
            row['switches'].append(board.switch(family,'rs'));save()
            row['counters']=board.rs(count);save()
            row['execution_wall_seconds']=time.perf_counter()-execution_start
            for index,frame in enumerate(frames):
                trace=board.trace(index,frame)
                trace['input_payload_sha256']=hashlib.sha256(frame['payload']).hexdigest()
                row['traces'].append(trace)
                if not trace['valid']:raise RuntimeError(f'DDR buffer mismatch {mode} frame {index}')
            row['valid']=row['counters']['valid'] and all(t['valid'] for t in row['traces'])
            c=row['counters']
            row['compute_integrity_us']=c['compute_integrity_ticks']*1e6/c['timer_hz']
            row['service_batch_us']=row['compute_integrity_us']+sum(s['microseconds']['service_total'] for s in row['switches'])
            row['service_per_frame_ms']=row['service_batch_us']/count/1000
            row['payload_mbps']=layout['payload_bytes']*8*count/row['service_batch_us']
            row['wall_payload_mbps']=layout['payload_bytes']*8*count/row['execution_wall_seconds']/1e6
            print('STAGE_BATCH',mode,count,'PASS' if row['valid'] else 'FAIL','service_ms_per_frame',round(row['service_per_frame_ms'],3),flush=True)
            save()
            if not row['valid']:raise RuntimeError('Stage batch failed CRC/RS checks')
        record['final_status']=board.status();record['passed']=True
        record['timed_frames']=sum(r['count'] for r in record['batches'])
        record['partial_transfers']=sum(len(r['switches']) for r in record['batches'])
        print('STAGE_EVALUATION_PASS',record['timed_frames'],'frames',record['partial_transfers'],'swaps',flush=True)
    except Exception as error:
        record['error']=repr(error);print('STAGE_EVALUATION_FAILED',error,flush=True);raise
    finally:
        if board is not None:board.close()
        record['finished_utc']=datetime.now(timezone.utc).isoformat()
        record['wall_seconds']=time.perf_counter()-start;save();print('STAGE_EVIDENCE',directory.resolve(),flush=True)


if __name__=='__main__':main()
