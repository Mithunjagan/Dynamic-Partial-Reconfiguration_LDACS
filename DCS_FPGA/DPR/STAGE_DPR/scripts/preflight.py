import argparse,hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from common.image_validation import checked_file
from common.elf_validation import validate_elf
from common.source_manifest import snapshot

def family(path):
 path=Path(path);f=json.loads(path.read_text());m=json.loads(path.with_name('routed_manifest.json').read_text())
 if f.get('schema')!='ldacs_stage_dpr_image_family_v1' or f.get('part')!='xc7z010clg400-1':raise ValueError('Wrong stage family')
 if not f.get('pr_verify_passed') or not m.get('pr_verify_passed') or not m.get('critical_warnings_passed'):raise ValueError('Unverified stage family')
 if type(f.get('build_token')) is not int or not 0<f['build_token']<=0xffffffff or f['build_token']!=m['build_token']:raise ValueError('Invalid build identity')
 if f.get('static_monitor_version')!=1 or f.get('hardware_source_sha256')!=snapshot(ROOT)['hardware_source_sha256']:raise ValueError('Sources or monitor changed')
 if set(f['modules'])!={'viterbi','rs'}:raise ValueError('Incomplete stage family')
 for name,ident in [('viterbi',0),('rs',1)]:
  e=f['modules'][name]
  if e['id']!=ident:raise ValueError('Wrong module ID')
  checked_file(path.parent,e['full_file'],e['full_sha256'])
  p=checked_file(path.parent,e['partial_file'],e['partial_sha256'])
  if p.stat().st_size!=e['partial_bytes'] or not 0<e['partial_bytes']<=8*1024*1024 or e['partial_bytes']%4:raise ValueError('Invalid partial size')
 return f

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--family',type=Path,required=True);p.add_argument('--module',choices=['viterbi','rs'],required=True);p.add_argument('--elf',type=Path,required=True);a=p.parse_args()
 f=family(a.family/'images.json');validate_elf(a.elf);meta=json.loads(a.elf.with_name('firmware_build.json').read_text())
 if meta['platform']!='stage_dpr' or meta['required_static_monitor_version']!=1 or hashlib.sha256(a.elf.read_bytes()).hexdigest()!=meta['elf_sha256']:raise ValueError('Wrong stage firmware')
 print(checked_file(a.family,f['modules'][a.module]['full_file'],f['modules'][a.module]['full_sha256']))
