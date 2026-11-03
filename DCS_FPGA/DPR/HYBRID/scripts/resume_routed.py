"""Finish an interrupted family without rerouting its preserved static checkpoint.

The sole allowed source-pin migration is the recorded Vivado reporting API fix.
Other hardware changes always require a fresh project/token.
"""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent))
from common.source_manifest import snapshot

OLD='redirect -tee -file $out/${rm}_pr_verify.rpt {pr_verify -full_check $out/full_pl_routed.dcp $out/${rm}_routed.dcp}'
NEW='pr_verify -full_check -file $out/${rm}_pr_verify.rpt $out/full_pl_routed.dcp $out/${rm}_routed.dcp'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    build=ROOT/'hw/vivado/build_dpr';out=build/'dfx'
    saved=json.loads((build/'source_snapshot.json').read_text())
    current=snapshot(ROOT)
    if saved['files']!=current['files']:
        raise RuntimeError('Source changes require a new build; refusing checkpoint reuse')
    script=ROOT/'hw/vivado/build.tcl';text=script.read_text()
    checkpoints={name:sha(out/name) for name in ('full_pl_routed.dcp','hybrid_routed.dcp','static_locked.dcp')}
    if OLD in text:
        if text.count(OLD)!=1:raise RuntimeError('Reporting fix is not unique')
        (build/'source_snapshot_before_reporting_fix.json').write_text(json.dumps(saved,indent=2)+'\n')
        (build/'build_before_reporting_fix.tcl').write_text(text)
        script.write_text(text.replace(OLD,NEW))
        updated=snapshot(ROOT)
        changed=[key for key in set(saved['files'])|set(updated['files']) if saved['files'].get(key)!=updated['files'].get(key)]
        if changed!=['hw/vivado/build.tcl']:raise RuntimeError('Unexpected hardware change')
        updated['build_token']=saved['build_token']
        updated['reporting_only_resume']={'old_source_sha256':saved['hardware_source_sha256'],
            'old_command':OLD,'new_command':NEW,'preserved_checkpoints':checkpoints}
        (build/'source_snapshot.json').write_text(json.dumps(updated,indent=2)+'\n')
        (build/'source_snapshot.sha256').write_text(updated['hardware_source_sha256']+'\n')
    log=ROOT/'build/handbook_dpr/resume_routed.log'
    print('RESUMING_PRESERVED_ROUTED_CHECKPOINTS',flush=True)
    with log.open('w') as stream:
        result=subprocess.run(['C:/Xilinx/Vivado/2022.2/bin/vivado.bat','-mode','batch','-nolog','-nojournal',
            '-source',str(ROOT/'scripts/finish_family.tcl'),'-tclargs',str(ROOT)],
            cwd=log.parent,stdout=stream,stderr=subprocess.STDOUT,timeout=7200)
    if result.returncode:raise RuntimeError('Verification/implementation failed: '+str(log))
    if any(sha(out/name)!=digest for name,digest in checkpoints.items()):
        raise RuntimeError('Preserved reference checkpoints changed')
    if snapshot(ROOT)['files']!=json.loads((build/'source_snapshot.json').read_text())['files']:
        raise RuntimeError('Hardware sources changed during resume')
    subprocess.run([sys.executable,'-B',str(ROOT/'scripts/package_images.py')],check=True)
    print('DPR_FAMILY_VERIFIED_AND_PACKAGED',flush=True)


if __name__=='__main__':main()
