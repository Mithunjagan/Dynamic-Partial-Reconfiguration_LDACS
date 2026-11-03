"""Run shell, byte-enable and pipeline regressions using installed Vivado XSim.

Generated simulator inputs/results stay under DPR/build/review_rtl.
"""
import argparse
import json
from pathlib import Path
import random
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'HYBRID'))
from model import ldacs_ref as L


def simulate(bin_dir, work, top, files):
    work.mkdir(parents=True, exist_ok=True)
    commands = [
        [str(bin_dir / 'xvlog.bat'), '--sv', '-i', str(work), *map(str, files)],
        [str(bin_dir / 'xelab.bat'), top, '-s', 'review_snapshot'],
        [str(bin_dir / 'xsim.bat'), 'review_snapshot', '--runall'],
    ]
    logs = []
    for index, command in enumerate(commands):
        run = subprocess.run(command, cwd=work, capture_output=True, text=True, timeout=240)
        output = run.stdout + run.stderr
        (work / f'{index}.log').write_text(output)
        logs.append(output)
        if run.returncode:
            raise RuntimeError(output[-5000:])
    if 'TEST PASSED' not in logs[-1] or 'TEST FAILED' in logs[-1]:
        raise RuntimeError(logs[-1][-5000:])
    print('PASS ' + work.name, flush=True)


def source_files(project, module, static=False):
    return [project / 'hw/static/dpr_shell.v', *sorted((project / 'hw/shared').glob('*.v')),
            *([project / 'hw/rm/hybrid/core.v'] if static else sorted((project / 'hw/rm' / module).glob('*.v')))]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--bin', type=Path, default=Path('C:/Xilinx/Vivado/2022.2/bin'))
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--error-campaign', action='store_true', help='Run residual-error RS cases only')
    args = parser.parse_args()
    out = ROOT / 'build/review_rtl'
    cases = [('hybrid', False), ('hybrid', True), ('full_pl', False)]
    if not args.error_campaign:
        project = ROOT / 'FULL_PL'
        simulate(args.bin, out / 'shell', 'tb_shell', [project / 'tests/tb_shell.v',
                 project / 'tests/mock_rp.v', project / 'hw/static/dpr_shell.v'])
        register_template = (project / 'tests/tb_shell.v').read_text()
        start = register_template.index('initial begin\n repeat(5)')
        end = register_template.index('initial begin #200000', start)
        for module, static in cases:
            label = module + ('_static' if static else '_rm')
            body = '''initial begin
     repeat(5)@(posedge aclk);@(negedge aclk);aresetn=1;
     write_split(8'h80,0,0,0);
     write_split(8'h0c,32'h1234,0,0);read_check(8'h0c,32'h1234,0);
     s_axi_ctrl_wstrb=0;write_split(8'h0c,0,1,0);read_check(8'h0c,32'h1234,0);
     s_axi_ctrl_wstrb=1;write_split(8'h0c,32'hcd,0,0);read_check(8'h0c,32'h12cd,0);
     s_axi_ctrl_wstrb=2;write_split(8'h0c,32'hab00,1,0);read_check(8'h0c,32'habcd,0);
     s_axi_ctrl_wstrb=4;write_split(8'h0c,0,0,0);read_check(8'h0c,32'habcd,0);
     s_axi_ctrl_wstrb=1;write_split(8'h08,2,1,0);
     s_axi_ctrl_wstrb=0;write_split(8'h08,0,0,0);read_check(8'h08,2,0);
     $display("REGISTER TEST PASSED");$finish;
    end
    '''
            bench = register_template[:start] + body + register_template[end:]
            if static:
                bench = bench.replace('dpr_shell dut(', 'dpr_shell #(.STATIC_HYBRID(1)) dut(')
            work = out / ('strobes_' + label)
            work.mkdir(parents=True, exist_ok=True)
            tb = work / 'tb_shell.v'; tb.write_text(bench)
            simulate(args.bin, work, 'tb_shell', [tb, *source_files(project, module, static)])
    results = []
    modes = ['qpsk_1_2'] if args.quick else list(L.MODES)
    for module, static in cases:
        project = ROOT / ('FULL_PL' if module == 'full_pl' else 'HYBRID')
        vectors = [(mode, 0.0, 0) for mode in modes]
        vectors += [('qpsk_1_2', 0.02, 0), ('qpsk_1_2', 0.01, 1), ('qpsk_1_2', 0.01, 2)]
        if module == 'full_pl': vectors += [('qpsk_1_2', 0.01, 3), ('qpsk_1_2', 0.01, 4)]
        if args.error_campaign: vectors = [('qpsk_3_4', 0.04, 0), ('qpsk_3_4', 0.08, 0)]
        for mode, ber, tap in vectors:
            layout = L.frame_layout(mode)
            payload = bytes((i * 37 + len(mode)) & 255 for i in range(layout['payload_bytes']))
            tx = L.add_errors(L.encode_frame(payload, layout)['tx'], random.Random(27), ber=ber)
            decoded = L.decode_frame(tx, layout)
            expected = {0: decoded['payload'] if module == 'full_pl' else decoded['hw_out'],
                        1: decoded['viterbi_bytes'], 2: decoded['block_deinterleaved'],
                        3: bytes(decoded['vit_in']), 4: decoded['hw_out']}[tap]
            work = out / f'{module}_{static}_{mode}_{ber}_{tap}'; work.mkdir(parents=True, exist_ok=True)
            data = tx if module == 'full_pl' else L.helical_deinterleave(tx)
            for name, values in [('vit_in.mem', data), ('hw_expected.mem', expected)]:
                (work / name).write_text(''.join(f'{b:02x}\n' for b in values))
            config = {'CFG_RATE': L.RATE_CODE[layout['rate']], 'CFG_N_STEPS': layout['n_steps'],
                      'CFG_NUM_CW': layout['num_cw'], 'CFG_RS_N': layout['rs_n'], 'CFG_TRACE': tap,
                      'N_IN': len(tx), 'N_OUT': len(expected),
                      'EXP_CORR': decoded['n_corr'] if tap in (0, 4) else 0,
                      'EXP_FAIL': decoded['n_fail'] if tap in (0, 4) else 0}
            (work / 'tb_cfg.vh').write_text(''.join(f'localparam {k}={v};\n' for k,v in config.items()))
            bench = (project / 'hw/tb/tb_decoder_top.v').read_text()
            if static: bench = bench.replace('dpr_shell dut (', 'dpr_shell #(.STATIC_HYBRID(1)) dut (')
            tb = work / 'tb_decoder_top.v'; tb.write_text(bench)
            simulate(args.bin, work, 'tb_decoder_top', [tb, *source_files(project, module, static)])
            results.append({'module':module, 'static':static, 'mode':mode, 'ber':ber, 'tap':tap, 'passed':True})
    (out / ('validation_errors.json' if args.error_campaign else 'validation.json')).write_text(json.dumps({'board_measurement':False, 'cases':results}, indent=2)+'\n')


if __name__ == '__main__':
    main()
