"""Build one source-pinned DFX family while preserving the static baseline.

Python hashing runs outside Vivado's embedded Tcl/Python environment. On Windows
a short workspace alias avoids long generated IP paths. It is retained for
subsequent Vivado runs and recorded alongside the build logs.
"""
import argparse
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
from common.source_manifest import snapshot


def short_root():
    if os.name != 'nt':
        return ROOT
    workspace = ROOT.parents[2]
    for letter in ('Q','R','S','T'):
        candidate = Path(letter+':/DCS_FPGA/DPR/HYBRID')
        if candidate.exists() and candidate.resolve() == ROOT:
            return candidate
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for letter in ('Q','R','S','T'):
        if not mask & (1 << (ord(letter)-ord('A'))):
            subprocess.run(['subst',letter+':',str(workspace)],check=True)
            return Path(letter+':/DCS_FPGA/DPR/HYBRID')
    return ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--vivado', default='C:/Xilinx/Vivado/2022.2/bin/vivado.bat')
    parser.add_argument('--resume-static', action='store_true')
    parser.add_argument('--resume-rms', action='store_true')
    args = parser.parse_args()
    logs = ROOT/'build/handbook_dpr'/datetime.now(timezone.utc).strftime('run_%Y%m%dT%H%M%SZ')
    logs.mkdir(parents=True)
    tool_root = short_root()
    build = ROOT/'hw/vivado/build_dpr'
    before = snapshot(ROOT)
    record = {'schema':'ldacs_dfx_build_attempt_v1','started_utc':datetime.now(timezone.utc).isoformat(),
              'tool_root':str(tool_root),'logs':str(logs),'passed':False,'stages':[]}
    (ROOT/'build/handbook_dpr/latest_build.json').write_text(json.dumps(record,indent=2)+'\n')
    def run(name, options=()):
        print('DFX_STAGE_START',name,flush=True)
        command=[args.vivado,'-mode','batch','-nojournal','-nolog','-source',str(tool_root/'hw/vivado'/name)]
        if options:command+=['-tclargs',*options]
        with (logs/(name+'.log')).open('w') as output:
            result=subprocess.run(command,cwd=logs,stdout=output,stderr=subprocess.STDOUT,timeout=7200)
        record['stages'].append({'name':name,'exit_code':result.returncode})
        (logs/'attempt.json').write_text(json.dumps(record,indent=2)+'\n')
        if result.returncode:
            raise RuntimeError(name+' failed; see '+str(logs/(name+'.log')))
        if snapshot(ROOT)['files'] != before['files']:
            raise RuntimeError('Hardware changed during the build; recreate for a new token')
        print('DFX_STAGE_PASS',name,flush=True)
    try:
        if not (args.resume_static or args.resume_rms):
            run('create_project.tcl')
            before['build_token']=int((build/'build_token.txt').read_text().strip())
            (build/'source_snapshot.json').write_text(json.dumps(before,indent=2)+'\n')
            (build/'source_snapshot.sha256').write_text(before['hardware_source_sha256']+'\n')
        else:
            saved=json.loads((build/'source_snapshot.json').read_text())
            if saved['files']!=before['files']:raise RuntimeError('Changed sources require project recreation')
        options=[]
        if args.resume_static:options.append('--resume-static')
        if args.resume_rms:options.append('--resume-rms')
        run('build.tcl',options)
        subprocess.run([sys.executable,'-B',str(ROOT/'scripts/package_images.py')],check=True)
        record['passed']=True
        print('DFX_FAMILY_PACKAGED',build/'dfx/images.json',flush=True)
    except Exception as error:
        record['error']=str(error)
        print('DFX_BUILD_ERROR',error,flush=True)
        raise
    finally:
        record['finished_utc']=datetime.now(timezone.utc).isoformat()
        (logs/'attempt.json').write_text(json.dumps(record,indent=2)+'\n')
        (ROOT/'build/handbook_dpr/latest_build.json').write_text(json.dumps(record,indent=2)+'\n')


if __name__ == '__main__':
    main()
