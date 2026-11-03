"""Independently audit the live campaign's raw physical response headers."""
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import struct
import urllib.request
import zlib

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--evidence',type=Path,help='Audit a saved physical campaign without accessing hardware')
args=parser.parse_args()
if args.evidence:
    data=json.loads(args.evidence.read_text(encoding='utf-8'))
else:
    with urllib.request.urlopen('http://127.0.0.1:8767/api/evidence',timeout=20) as response:
        data=json.load(response)
checks=[]
seen={}
for i,r in enumerate(data['results']):
    raw=struct.unpack('<4sBBHHHIIIII9Q',bytes.fromhex(r['raw_benchmark']['raw_response_header_hex']))
    magic,arch,rate,reps,length,warm,hz,pl,corrected,failed,bad,*counts=raw
    mean=counts[5]*1e6/hz/reps
    output=bytes.fromhex(r['stages'][-1]['output_hex'])
    input_key=(r['input_sha256'],r['encoded_sha256'])
    same_input=r['coding'] not in seen or seen[r['coding']]==input_key
    seen[r['coding']]=input_key
    verdict=dict(
        identity=magic==(b'DDBR' if r['mode']=='DPR' else b'LDBR') and arch=={'PS':2,'PL':1,'HYBRID':0,'DPR':1}[r['mode']],
        repetition_count=reps==3 and warm==1,
        raw_latency=abs(mean-r['latency_us'])<1e-5,
        raw_extrema=abs(counts[6]*1e6/hz-r['min_us'])<1e-5 and abs(counts[7]*1e6/hz-r['max_us'])<1e-5,
        throughput=abs(length*8/mean-r['payload_mbps'])<1e-8,
        no_crc_rs_failure=bad==failed==0,
        exact_final_payload=hashlib.sha256(output).hexdigest()==r['input_sha256'] and len(output)==length,
        crc32=f'0x{zlib.crc32(output):08X}'==r['crc32'],
        all_buffers=all(hashlib.sha256(bytes.fromhex(st['output_hex'])).hexdigest()==st['sha256'] and st['matches_model'] for st in r['stages']),
        fresh=datetime.fromisoformat(r['recorded_utc'])>=datetime.fromisoformat(r['request_started_utc'])>=datetime.fromisoformat(data['started_utc']),
        identical_cross_architecture_input=same_input,
        physical_modem=r['modem']['bit_errors']==0 and r['modem']['bitstream_sha256']==r['encoded_sha256'],
        stored_build_reports_excluded='resources' not in r,
    )
    checks.append(dict(index=i,mode=r['mode'],coding=r['coding'],checks=verdict,passed=all(verdict.values())))
summary=dict(run_id=data['run_id'],verified_entries=len({(r['mode'],r['coding']) for r in data['results']}),
    expected_entries=data['expected'],transactions=len(checks),timed_frames=sum(r['raw_benchmark']['iterations'] for r in data['results']),
    complete=len({(r['mode'],r['coding']) for r in data['results']})==data['expected'],
    all_record_audits_passed=all(c['passed'] for c in checks),records=checks)
out=ROOT/'dev/analytics/measurement_audit.json'
out.write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in summary.items() if k!='records'},indent=2))
if not summary['all_record_audits_passed']:raise SystemExit(1)
