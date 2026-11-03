# Handbook implementation status - 3 November 2026

The newer [stage-sharing implementation](STAGE_DPR/README.md) is also complete:
Viterbi/packing and RS alternate in one RP, while block deinterleaving is static.
Both configurations passed timing/DRC and full pr_verify. The physical run passed
48 frames across eight modes, 20 transfers and 144 exact buffer comparisons.
Peak occupied LUTs are 8723, 24.02% below the 11480-LUT combined HYBRID baseline.
The Pblock geometry is unchanged; batching trades latency for occupied LUT area.
See [its report](STAGE_DPR/results/onboard_20261103T051524Z/REPORT.md). The table
below records the preserved whole-receiver implementation.

| Handbook stage | Evidence / status |
|---|---|
| Device/tool analysis | EDGE Z7-10, xc7z010clg400-1, Vivado/Vitis 2022.2; 50 MHz FCLK |
| Partition/interface | One receiver RP; four existing pin-compatible RMs; static proxy/isolation/heartbeat |
| Source preservation | Validated static products retained; new products use build_dpr and sw/dpr |
| RTL/control tests | Updated shell/isolation/heartbeat and decoder regression passed (18 quick XSim cases) |
| Runtime driver tests | Actual PCAP routine passes native register fixtures including continuity faults |
| Firmware | Monitored ARM HYBRID ELF built and load segments validated |
| Vivado project | Generated successfully from the validated integration template |
| Static synthesis | New static_synth.dcp generated with a preserved RP black box |
| RM synthesis / place / route | Completed for hybrid, full_pl, blank, and anchor; DRC and setup/hold gates passed |
| pr_verify / bitstreams | All three alternatives compatible with the same routed full_pl reference; full and partial images packaged under build_dpr/dfx/images.json (token 5330926) |
| New DPR board measurements | PASS: six genuine HYBRID/blank partial transfers; static continuity observed during all six; 800 timed frames, eight modes, 40/40 stage-buffer checks |

The installed Tcl framework initially failed during project creation. Project
variables are now scoped locally, and the validated integration is copied without
implementation results. Python hashing runs outside Vivado. The current build
attempt and exact logs are linked in `HYBRID/build/handbook_dpr/latest_build.json`.
That attempt stopped at an unsupported report-redirection command after routing.
The reporting-only fix and unchanged reference checkpoint hashes are audited in
`HYBRID/hw/vivado/build_dpr/source_snapshot.json`. The successful continuation log
is `HYBRID/build/handbook_dpr/resume_routed.log`.

The build keeps configuration-specific checkpoints, routed reports, and explicit
pr_verify logs. Runtime validation is provided by HYBRID/scripts/evaluate_dpr.py:
a pre-switch decode, safe invalid-request rejection, repeated genuine PCAP swaps,
static heartbeat/build-identity observations during loading, and post-switch
payload/CRC/stage checks.

Physical evaluation completed on 3 November 2026 at 01:28:12 IST. See
[the measured DPR report](HYBRID/results/dpr_20261102T195022Z/REPORT.md).
PCAP load: 18.196-18.212 ms; isolated/restart total: 18.384-18.400 ms.
The complete switch service takes 3.727 s because it includes a 3.709 s software
CRC precheck. Initial UART staging takes about 149.14 s per partial image and is
separate. All decoded payloads and static-continuity observations passed.
FULL_PL and anchor have routed/tool verification; this physical run covers
HYBRID and blank. The previously validated static evaluation remains separate.
