import argparse,json,random,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));from model import ldacs_ref as L
sys.path.insert(0,str(ROOT.parent/'tests'));from run_rtl import simulate
p=argparse.ArgumentParser();p.add_argument('--quick',action='store_true');a=p.parse_args()
results=[]
for mode in (['qpsk_1_2','64qam_3_4'] if a.quick else list(L.MODES)):
 layout=L.frame_layout(mode);payload=bytes((i*37+len(mode))&255 for i in range(layout['payload_bytes']))
 tx=L.add_errors(L.encode_frame(payload,layout)['tx'],random.Random(27),ber=.01)
 d=L.decode_frame(tx,layout)
 for stage,vin,expected in [('viterbi',bytes(L.helical_deinterleave(tx)),d['block_deinterleaved']),('rs',d['block_deinterleaved'],d['hw_out'])]:
  work=ROOT/'build/rtl'/f'{mode}_{stage}';work.mkdir(parents=True,exist_ok=True)
  for name,data in [('vit_in.mem',vin),('hw_expected.mem',expected)]: (work/name).write_text(''.join(f'{b:02x}\n' for b in data))
  cfg=dict(CFG_RATE=L.RATE_CODE[layout['rate']],CFG_N_STEPS=layout['n_steps'],CFG_NUM_CW=layout['num_cw'],CFG_RS_N=layout['rs_n'],CFG_TRACE=0,N_IN=len(vin),N_OUT=len(expected),EXP_CORR=d['n_corr'] if stage=='rs' else 0,EXP_FAIL=d['n_fail'] if stage=='rs' else 0)
  (work/'tb_cfg.vh').write_text(''.join(f'localparam {k}={v};\n' for k,v in cfg.items()))
  files=[ROOT/'tests/tb_stage.v',*sorted((ROOT/'hw/static').glob('dpr_shell.v')),*sorted((ROOT/'hw/shared').glob('*.v')),ROOT/f'hw/rm/{stage}/rp_decoder.v']
  simulate(Path('C:/Xilinx/Vivado/2022.2/bin'),work,'tb_decoder_top',files)
  results.append(dict(mode=mode,stage=stage,ber=.01,passed=True))
(ROOT/'build/rtl/results.json').write_text(json.dumps(results,indent=2)+'\n')
