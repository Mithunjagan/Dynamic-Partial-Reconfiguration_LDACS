"""Stage batch transport; reuses the verified UART/PCAP client, not its scheduler."""
import json
from pathlib import Path
import random
import struct
import sys
import zlib

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'HYBRID/scripts'))
sys.path.insert(0,str(ROOT.parent/'HYBRID/host'))
from evaluate_dpr import Board as Transport, ProgressSerial, debug_service
from board_client import header
sys.path.insert(0,str(ROOT/'scripts'))
from preflight import family
sys.path.insert(0,str(ROOT))
from model import ldacs_ref as L


def frames(mode,count,seed=91):
    layout=L.frame_layout(mode);result=[]
    for i in range(count):
        rng=random.Random(seed+i)
        payload=bytes(rng.randrange(256) for _ in range(layout['payload_bytes']))
        encoded=L.encode_frame(payload,layout)
        result.append(dict(payload=payload,tx=bytes(encoded['tx']),
                           bdi=b''.join(L.block_deinterleave(encoded['rs_in'],layout['num_cw'])),
                           rs=bytes(encoded['randomized'])))
    return layout,result


class Board(Transport):
    def magic(self,expected):
        value=self.read(4)
        if value==b'DPRE':raise RuntimeError('Stage firmware error '+str(struct.unpack('<I',self.read(4))[0]))
        if value!=expected:raise RuntimeError(f'Protocol mismatch {value!r}, expected {expected!r}')

    def batch_load(self,layout,frames):
        if not 1<=len(frames)<=64:raise ValueError('Batch must contain 1..64 frames')
        self.send(header(b'SBL1',layout)+struct.pack('<H',len(frames)))
        self.magic(b'RDY1')
        for i,frame in enumerate(frames):
            data=struct.pack('<I',zlib.crc32(frame['payload']))+frame['tx']
            for start in range(0,len(data),4096):
                chunk=data[start:start+4096]
                if self.serial.write(chunk)!=len(chunk):raise IOError('Short batch upload')
            self.serial.flush();self.magic(b'SBF1')
            if struct.unpack('<I',self.read(4))[0]!=i:raise RuntimeError('Wrong input frame acknowledgement')
        self.magic(b'SBLA');raw=self.read(16)
        count,hz,ticks=struct.unpack('<IIQ',raw)
        if count!=len(frames) or not hz:raise RuntimeError('Invalid batch acknowledgement')
        return {'raw_hex':(b'SBLA'+raw).hex(),'count':count,'timer_hz':hz,'helical_ticks':ticks}

    def viterbi(self,count):
        self.send(b'SBV1');self.magic(b'SBVA');raw=self.read(12)
        n,ticks=struct.unpack('<IQ',raw)
        if n!=count or not ticks:raise RuntimeError('Invalid Viterbi acknowledgement')
        return {'raw_hex':(b'SBVA'+raw).hex(),'count':n,'ticks':ticks}

    def rs(self,count):
        self.send(b'SBR1');self.magic(b'SBRR');raw=self.read(80)
        values=struct.unpack('<10I5Q',raw)
        names=['count','coded_bytes','nrs','payload_bytes','timer_hz','pl_hz','corrections','rs_failures','crc_failures','phase',
               'helical_ticks','viterbi_bdi_ticks','rs_ticks','derand_ticks','compute_integrity_ticks']
        r=dict(zip(names,values));r['raw_hex']=(b'SBRR'+raw).hex()
        if r['count']!=count or r['phase']!=3 or not r['timer_hz'] or not r['pl_hz']:raise RuntimeError('Invalid RS batch counters')
        r['valid']=not r['rs_failures'] and not r['crc_failures']
        return r

    def trace(self,index,expected):
        self.send(b'SBT1'+struct.pack('<H',index));self.magic(b'SBTR')
        nrs,payload=struct.unpack('<II',self.read(8))
        if (nrs,payload)!=(len(expected['bdi']),len(expected['payload'])):raise RuntimeError('Wrong trace lengths')
        raw=[self.read(nrs),self.read(payload),self.read(payload)]
        r={name:{'matches':data==expected[name],'actual_hex':data.hex()}
           for name,data in zip(('bdi','rs','payload'),raw)}
        r['valid']=all(r[k]['matches'] for k in ('bdi','rs','payload'))
        return r
