# DPR validation - 2 November 2026

| Check | Current result |
|---|---|
| Host, PCAP fixtures, comparison and boot preflight | 69 unit tests passed |
| XSim 2022.2 | 45 RTL cases passed: shell, byte enables, all eight modes, trace taps, backpressure and residual-error cases |
| ARM firmware | HYBRID, FULL_PL and FULL_PS rebuilt; non-overlapping ELF segments validated |
| Default HYBRID implementation | Static pipeline synthesized, placed, routed and packaged successfully |
| HYBRID setup / hold slack | +4.223 ns / +0.025 ns; TNS 0.000 ns |
| HYBRID routed resources | 11402 LUT, 6107 FF, 49 RAMB36, 3 RAMB18, 1 DSP |
| HYBRID DRC / routing | Zero errors or critical warnings; zero routing errors |
| XSDB boot and board identity | Actual JTAG programming and UART build-token/architecture checks passed |
| DFX reset constraint | Saved FULL_PL routed checkpoint checked with RESET_AFTER_RECONFIG=TRUE: zero errors/critical warnings |
| Source baseline | 159 files match the explicitly reconciled November 2 baseline; common RTL/model copies match |

Default HYBRID has no RP or partial images. Its full-image package is
`HYBRID/hw/vivado/build/dfx/images.json`; the wrapper retains its AXI-Lite and
AXI-stream interfaces. `HYBRID/partition_policy.json` records the selection
and unrounded baseline measurements with source hashes. Existing resource
measurements are from the 50 MHz DPR HYBRID configuration; board stage latencies
are from the 71.428570 MHz static HYBRID sweep. Neither is presented as a new
board measurement of the edited design.

`validation_summary.json` records exact ELF hashes, layout, suite counts, image
hash and implementation metrics. Detailed generated results are under
`build/review_rtl`, `build/review_unit_tests.json`, `build/review_drc`, and
`HYBRID/build/review_implementation/final_rebuild.log`.

The new static HYBRID image passed a physical-board evaluation completed at 2026-11-02 23:58:52 IST: 800 timed frames across eight modes, zero CRC/RS failures and 40/40 stage-buffer comparisons. Measurement and stage checks took 128.889 s; boot took 26.876 s. Evidence: `HYBRID/results/onboard_20261102T182532Z/REPORT.md`. The saved October 30
FULL_PL/blank round trip is documented in `../../hardware_live/DPR_VALIDATION.md`
and used the separate live-workbench firmware. A new experimental four-RM
family was not built in this revision. Current boot/package gates require such
families to be rebuilt and validated; historical packages are not silently
approved by the updated scripts. The new static HYBRID capture is now available. Additional captures are still
needed for the other configurations and a matched-clock six-way comparison.

The original October 29 validation records are retained as
`VALIDATION_20261029.md` and `validation_summary_20261029.json`. Original baseline
hashes remain in `preserved_sources_20261029.json`; `baseline_history.json`
records the 121 historical byte mismatches and the explicit baseline reconciliation.
The current check does not claim those files were unchanged since October 29.

Shared LDACS SPEC-CHECK assumptions and the absence of RF/OFDM remain as documented.
