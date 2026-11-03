# HYBRID dynamic partial reconfiguration

Default: a genuine receiver RP on EDGE Z7-10, XC7Z010CLG400-1, Vivado 2022.2.
ARM keeps helical deinterleaving and derandomization. The `hybrid` RM contains
Viterbi, bit packing, block deinterleaving and RS. Existing `full_pl`, `blank`
and `anchor` RMs keep the same partition ports. Static logic contains PS/DDR,
UART, DMA, clocks/resets, the AXI proxy/isolation and a 64-bit heartbeat.

## Build

Run from `DCS_FPGA`:

```powershell
python DPR/HYBRID/scripts/build_dpr.py
python DPR/HYBRID/build_firmware.py
```

The build runner pins hardware sources to a fresh build token, keeps Python
hashing outside Vivado's embedded environment, and uses a short Windows workspace
alias when available. It records the alias and logs in `build/handbook_dpr`.
Project-generation variables are scoped locally to avoid Vivado Tcl state collisions.
The validated board/AXI project is copied as an integration template when present;
implementation results are excluded, and the RP configurations are built anew.

New products are isolated in `hw/vivado/build_dpr/dfx` and `sw/dpr`.
The previously validated static bitstream, checkpoints, ELF and capture remain
in `hw/vivado/build`, `sw/uart_bridge.elf` and `results/onboard_*`.
`--static-hybrid` is an explicit baseline build option, not the default DPR path.
A source change requires project recreation and a fresh token. A successfully
verified family is immutable; the build refuses to reroute it in place.

The flow implements FULL_PL first, blanks the RP, locks static routing, and
implements all other RMs against that checkpoint. Every configuration must pass
DRC, setup/hold timing and `pr_verify`. Critical warnings are failures. Packaging
checks source consistency, image hashes and partial-word format. See
[implementation status](../IMPLEMENTATION_STATUS.md) for actual completed stages.

## Boot and actual board evaluation

After a complete verified build, with COM5 free and the board powered:

```powershell
python DPR/HYBRID/scripts/evaluate_dpr.py --switches 3 --iterations 20 --warmups 2 --batches 5
```

The script programs the full image once, confirms a pre-DPR decode, checks safe
rejection of invalid requests, stages compatible partials, and performs three
`hybrid -> blank -> hybrid` PCAP round trips. Each restoration requires a payload
check. It then benchmarks all eight modes and compares all five stage buffers
per mode against the model. Raw boot, switch, continuity, benchmark and trace
responses are retained under `results/dpr_*`.

The completed [3 November board evaluation](results/dpr_20261102T195022Z/REPORT.md)
passed six genuine swaps, 800 timed frames across eight modes, and 40/40 stage
checks. PCAP loading took 18.196-18.212 ms; complete service including CRC took
about 3.727 s. FULL_PL and anchor were tool-verified; physical swaps covered
HYBRID and blank. To summarize a saved successful evaluation:

```powershell
python DPR/HYBRID/scripts/report_dpr.py DPR/HYBRID/results/dpr_20261102T195022Z
```

The static heartbeat and build identity are sampled during every PCAP polling
iteration. Frozen/reset counters or changed identities fault the load and leave
the RP isolated. New firmware blocks cache overwrites after a PCAP fault. The
`DSC1` command exposes actual continuity observations; it is not a simulated test.
UART staging, CRC precheck, PCAP loading, restart and overall service time remain
separate measurements. PCAP latency includes continuity-monitor polling overhead.

Manual commands:

```powershell
xsdb.bat DPR/HYBRID/boot_firmware.tcl
python DPR/HYBRID/host/dpr_client.py --switches 3 --mode all --output DPR/HYBRID/results/dpr_capture.json
```

Boot verifies hashes, family token, firmware layout and monitor compatibility
before JTAG access. The optional first boot argument selects a shared image family;
the optional second selects an ELF. Never mix partials from independent builds.

The historical static partition analysis is retained in
`partition_policy_static_baseline.json`. The current coarse receiver RP is
selected to implement runtime replacement using existing compatible modules;
no per-frame area/performance advantage or release of the reserved Pblock is claimed.
