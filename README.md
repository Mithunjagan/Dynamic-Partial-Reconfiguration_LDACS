# LDACS receiver architectures and stage-sharing DPR

Source, programming images, and physical-board benchmark evidence for an
AllAboutFPGA EDGE Z7-10 / XC7Z010CLG400-1, using Vivado/Vitis 2022.2.

## Live message console and benchmark analytics

The redesigned message send/receive console and the benchmark dashboard are separate local pages with navigation between them. With the physical board and installed Xilinx tools available, run these in separate terminals:

```powershell
python hardware_live/server.py
python hardware_live/analytics_server.py
```

- Message send/receive console: `http://127.0.0.1:8765/`
- Benchmark dashboard: `http://127.0.0.1:8767/`

Use the dashboard to start a fresh comparison. Its live mode can repeat all eight coding profiles across PS, PL, Hybrid and full-PL DPR sequentially. Stop the campaign after its active operation before using the board for interactive messages. No historical values fill missing live measurements.

[Analytics instructions](hardware_live/ANALYTICS.md) explain timing boundaries, exports and additional unmeasured candidates. The GitHub evidence below is a saved record, not a live board feed:

- [Fresh physical campaign](benchmarks/live_analytics/20261103T074936_573297Z/evidence.json)
- [Independent raw-counter and payload audit](benchmarks/live_analytics/20261103T074936_573297Z/measurement_audit.json)
- [Browser verification](benchmarks/live_analytics/20261103T074936_573297Z/browser_verification.json)

The complete campaign covers 32 architecture/profile entries. Startup failures and their resolution times remain in the evidence. Stored implementation reports, simulated timing, RF performance and estimated power are excluded from this live dataset. The earlier benchmark sections below retain their original, separate provenance.

## Selected benchmark designs

| Design | Decoder placement | Existing physical benchmark |
|---|---|---|
| Full PS | All five stages on one Cortex-A9 | Eight profiles, 3 timed frames/profile |
| Full PL decoder | All five stages in FPGA logic; ARM handles I/O/control | Eight profiles, 100 timed frames/profile |
| Hybrid | Helical/PRBS on ARM; Viterbi/block deinterleaver/RS in FPGA | Eight profiles, 100 timed frames/profile |
| Latest stage-sharing DPR | Viterbi/packing and RS alternate in one RP; block deinterleaver static | 48 frames, eight profiles, 20 PCAP transfers, 144 buffer checks |

The supported profiles cover QPSK, 16-QAM and 64-QAM. Existing measurements
were reused; publishing this snapshot did not rerun any board benchmarks.

- [Selected-design benchmark report](benchmarks/selected_designs_20261103/REPORT.md)
- [Decoder results](benchmarks/selected_designs_20261103/decoder.csv)
- [FPGA resources and timing slack](benchmarks/selected_designs_20261103/resources.csv)
- [Stage-sharing DPR service measurements](benchmarks/selected_designs_20261103/stage_sharing_dpr.csv)
- [PCAP switching measurements](benchmarks/selected_designs_20261103/stage_sharing_swaps.csv)
- [Evidence manifest](benchmarks/selected_designs_20261103/manifest.json)

## Resources

| Configuration | LUT | FF | BRAM36 equivalents | DSP |
|---|---:|---:|---:|---:|
| Full PS fabric | 0 | 0 | 0 | 0 |
| Full PL decoder | 11700 | 6234 | 51.5 | 1 |
| Hybrid | 11270 | 5990 | 50.5 | 1 |
| Stage DPR: Viterbi | 8723 | 5417 | 50 | 0 |
| Stage DPR: RS | 6198 | 5046 | 6.5 | 1 |

These are routed implementation results. Full PS still uses ARM and DDR.
Stage DPR peak occupied LUTs are 22.60% below static Hybrid and 25.44% below
Full PL. The reconfigurable Pblock reservation is unchanged. DPR uses about
50 MHz PL; the static accelerated designs use about 71.43 MHz.

## Layout

- `DCS_FPGA/`: source/build scripts, including separate Full PS/Full PL trees,
  the original Hybrid, and `DPR/STAGE_DPR/` for the latest stage-sharing variant.
  Older DPR source is retained where shared tooling depends on it; its benchmark
  results are outside the selected four-design comparison.
- `hardware_live/`: physical UART message workbench and capture tooling.
- `board_details/`: EDGE Z7-10 board definitions.
- `benchmarks/selected_designs_20261103/`: consolidated CSVs and report.
- `benchmarks/physical_20261103/static/`: raw PL/Hybrid timing and binary UART
  recordings. Those architecture sections completed; the enclosing campaign
  later failed on a PS UART boot probe. The failed attempt contributes no PS
  performance data. PS results use the earlier successful physical capture.
- `DCS_FPGA/DPR/STAGE_DPR/results/onboard_20261103T051524Z/`: successful latest
  stage-sharing evaluation, including raw replies and returned buffers.

Selected full/partial bitstreams, firmware, PS initialization scripts and
routed reports are included at their expected paths. Large Vivado project
caches and intermediate checkpoints are omitted. `SNAPSHOT_MANIFEST.json`
records the copied file hashes. Line endings are preserved for source/image
integrity checks.

## Inspect saved results without using the board

```powershell
python benchmarks/selected_designs_20261103/collect_existing.py
```

This validates and consolidates existing files only. It does not open COM5,
program the FPGA, run simulations, or start a hardware benchmark.

For building and physical operation, see [project instructions](DCS_FPGA/README.md),
[stage-sharing DPR](DCS_FPGA/DPR/STAGE_DPR/README.md) and
[the physical workbench](hardware_live/README.md). The workbench expects the
board on COM5 at 115200 baud and the installed Xilinx 2022.2 tools.

## Measurement boundaries

Decoder timings exclude UART, modem, CRC verification and trace replay.
DPR service includes image CRC prechecks and partial loading; UART staging is
recorded separately. These intervals must not be compared as equivalent.
Sample counts and payload patterns differ across preserved sessions.

The modem is ideal digital baseband loopback on ARM. There is no measured RF
channel, BER-versus-SNR, physical power/energy, or certified real-time deadline.
Shared `SPEC-CHECK` constants remain unverified against independent LDACS
specification vectors. Hardware integration is validated; independent LDACS
standards conformance is not established.
