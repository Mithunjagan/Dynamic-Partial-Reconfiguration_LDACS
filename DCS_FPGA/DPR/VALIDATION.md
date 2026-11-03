# DPR validation - 3 November 2026

The separate stage-sharing implementation is now [validated](STAGE_DPR/results/onboard_20261103T051524Z/REPORT.md).
It passed 21 native tests, four noisy-input/backpressure XSim cases, both routed
timing/DRC gates, full pr_verify, and a physical 48-frame / 20-swap evaluation
with 144 exact buffer checks. Peak occupied LUT count is 8723 (24.02% below the
combined HYBRID baseline). Test sizes are deliberately bounded; the unchanged
BRAM-constrained Pblock and increased scheduling latency remain documented.
The results below belong to the preserved whole-receiver HYBRID build.

The handbook DPR implementation passed tool verification and a physical EDGE Z7-10 evaluation. The default HYBRID now has one receiver RP. PS/DDR/UART/DMA, clocks, AXI isolation and heartbeat remain static.

| Check | Result |
|---|---|
| Source tests | 92 unit tests passed; host protocol, actual PCAP routine fixtures, preflight, comparison and source pinning |
| Updated RTL | 18 quick XSim cases passed: 14 pipeline/trace cases and four shell/control cases |
| Firmware | ARM HYBRID DPR ELF built with static monitor enabled; load layout validated |
| Implementations | HYBRID, FULL_PL, blank and anchor fully routed against one locked static implementation |
| DRC | No errors or critical warnings; ordinary warnings remain in the reports |
| Timing | All four meet setup/hold; HYBRID WNS +2.869 ns, WHS +0.024 ns, TNS 0.000 ns |
| pr_verify | All three alternate checkpoints compatible with the full_pl reference |
| Image family | Token 5330926; four full images and four 1,683,900-byte partial images with hashes |
| Physical DPR | Six genuine PCAP partial transfers: three HYBRID -> blank -> HYBRID round trips |
| Static continuity | Heartbeat, shell identity and token sampled during all six transfers; all passed |
| Post-switch correctness | Correct payload after every restored HYBRID; 800 timed frames plus 80 warm-ups across eight modes; zero CRC/RS failures |
| Stage buffers | 40/40 comparisons matched the reference model |
| Safe request rejection | Invalid module and wrong-family requests rejected without changing live configuration |
| Preserved sources | 159 files match the selected November 2 baseline; common RTL/models match |

Measured PCAP load is 18.196-18.212 ms. Isolated/restart total is 18.384-18.400 ms. Complete switch service is about 3.727 s, including a 3.709 s software image CRC precheck. UART staging is separate: approximately 149.14 s per partial. Boot took 19.661 s; the entire evaluation took 470.342 s.

See [the measured report](HYBRID/results/dpr_20261102T195022Z/REPORT.md) for all modes, transfer counters, utilization and timings. Raw UART/continuity responses, build identity and firmware hashes are retained alongside it. The image manifest is `HYBRID/hw/vivado/build_dpr/dfx/images.json`. `validation_summary.json` records exact values and scope.

FULL_PL and anchor passed routed/tool verification; physical swaps in this evaluation cover HYBRID and blank. Physical interrupted-transfer recovery, RF/OFDM, independent standards conformance and measured power were not tested. No DPR throughput or area advantage is claimed.

The validated static products and their 800-frame evaluation remain intact. Previous static validation is retained as `VALIDATION_20261102_static.md` and `validation_summary_20261102_static.json`; those results are not DPR measurements. October 29 records and the baseline reconciliation history are also retained.

The initial build stopped at a report-redirection command after successful FULL_PL/HYBRID routing. Only that reporting command changed before resuming preserved checkpoints. The snapshot records the exact edit and unchanged checkpoint hashes; `HYBRID/build/handbook_dpr/resume_routed.log` records successful completion.
