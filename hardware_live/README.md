# AXIOM physical-board message workbench

Run from `Aero_proj`:

```powershell
python hardware_live/server.py
```

Open http://127.0.0.1:8765. Keep the EDGE Z7-10 powered and its USB-JTAG/UART
connected. The configured serial port is COM5, 115200 8N1. Close other COM5
clients. The server owns the port across messages and releases it before a
JTAG architecture reload. Use `--port COMx` or `--http-port N` if required.
Vivado/Vitis 2022.2 and the ARM compiler are taken from the installed
`C:/Xilinx` tree; explicit `--xsdb` and `--gcc` overrides are supported.

## What really executes

1. The PC encodes the entered UTF-8 text using the existing LDACS reference
   encoder, padded to the selected coding profile's frame capacity.
2. Real Cortex-A9 firmware receives those coded bits using `LDM1`, produces
   integer Gray-QPSK, 16-QAM, or 64-QAM I/Q symbols, and demaps those symbols.
   It returns **all** symbols and recovered bits through the physical UART.
3. The host independently checks every returned symbol against the documented
   Gray mapping and compares every recovered bit to the encoded input.
4. The **actual board-returned demapped bits** become the input to the
   architecture-specific board decoder through `LDB1` and `LDAC`.
5. The board returns an architecture ID, global-timer and PL counters, payload,
   CRC status, and all five stage buffers. The host checks the final payload
   byte-for-byte and the intermediate buffers against the reference model.

The modem is an ideal **digital baseband loopback on ARM**. There is no RF
transceiver, DAC/ADC acquisition, physical channel, OFDM, synchronization,
channel estimation, or received-noise model in this workbench. The symbol
sequence plot shows returned I/Q symbol levels; it is not an RF waveform or
an interpolated sample stream. An ideal zero-error loopback is not evidence of
RF reception or noise tolerance. The existing SPEC-CHECK parameters have not
been independently established as LDACS-compliant.

| Receiver mode | Five decoder algorithms | Supporting work |
| --- | --- | --- |
| PS | All five on Cortex-A9 | ARM modem, UART and control; no decoder/DMA in PL |
| PL Compute | All five in FPGA logic | ARM modem, UART, control and AXI DMA |
| Hybrid | ARM: helical and PRBS; FPGA: Viterbi, block deinterleaver and RS | ARM modem/UART/control and AXI DMA |

“PL Compute” is **not** autonomous PL-only I/O with ARM in WFI. The label refers
to decoder placement. The hardware address is the actual project address
`0x40000000`, not the hypothetical `0x43C00000` used in the earlier demo page.
DMA remains at `0x40400000`. Measured clocks come from firmware-reported SLCR
configuration; the workbench does not force fictional 150/200 MHz frequencies.

The paper's Figure 4 partition is adapted to the project's Cortex-A9/XC7Z010.
The paper's evaluation platform is an UltraScale+ MPSoC with Cortex-A53; those
paper performance numbers must not be attributed to this board.

## Boot and firmware integrity

`boot.tcl` performs volatile JTAG reset, board-generated PS initialization,
architecture bitstream programming, and firmware download/start. Only a
successful physical UART architecture-ID and payload/CRC probe marks a boot
verified. It is **not** a flash writer, an observed BootROM/FSBL boot sequence,
or proof of physical POR_B assertion.

Firmware is built into `hardware_live/build/<mode>`, leaving original ELF
files and source files intact. The read-only LDR1 command returns ten actual decoder/DMA MMIO registers through UART, outside timed decoding. The generated `uart_bridge_modem.c` copies the
existing UART bridge with the added `LDM1` command and `modem.inc` handler.
The source hashes, compiler arguments, generated image hash, entry point and
load regions are retained in each `firmware_build.json`.

The shared linker script places explicit, non-overlapping code/data segments
in DDR above the DMA buffers. Build-ID notes are disabled and discarded.
`-mno-unaligned-access` avoids Cortex-A9 data aborts from compiler-generated
unaligned stores with the experiment's uncached memory policy. The assembly
entry has an explicit nearby literal pool. ELF validation rejects wrong
machine type, overlapping segments, invalid entry points, and DMA-memory
overlap before downloading anything.

Changing static architecture reloads its complete bitstream. That operation
is never mislabeled as dynamic partial reconfiguration. PS-only loads a blank
fabric image to remove any previously programmed accelerator.

## Timing boundaries

- Decoder latency: physical board global-timer elapsed time for one complete
  five-stage decode, including DMA/control overhead in accelerated variants.
  Three repetitions follow one warm-up. UART transfer, CRC verification,
  final output copying, modem and trace replays are outside this timer.
- CPU cycles: twice the global-timer tick count. These are **elapsed clock
  cycles**, not retired instructions or CPU-load measurements.
- PL stage counts: actual accelerator counters at the firmware-reported PL
  clock. Streaming stage times overlap and must not be added.
- Throughput: frame payload bytes / decoder latency, reported in decimal
  **MB/s**. The original client uses Mbit/s; the bridge explicitly divides by 8.
- UART benchmark wall time: includes encoded-input transfer, warm-up, three
  repetitions, CRC checking and output transfer. Modem and trace UART wall
  times are separate fields in the exported evidence.
- Resource allocation: each image's existing routed Vivado utilization report.
  It is not live resource switching activity or device attestation.
- CPU load, actual watts, energy efficiency and an LDACS RF deadline are not
  measured. The page deliberately does not invent these quantities.

## Independent cross-check

With the server running and no other client controlling the board:

```powershell
python hardware_live/verify.py
```

This exercises all three receiver architectures and all eight coding profiles
through the actual HTTP/UART/board path. Every completed case must pass exact
message, architecture ID, modem bit recovery, independent I/Q mapping, CRC and
all five stage checks. The default output is
`hardware_live/captures/api_verification.json`. `complete: true` means the
entire requested sweep completed; a partial file is never a completed sweep.
Raw intermediate buffers, response-header hex, timer counters, waveform
symbols and hashes remain inspectable. Individual message and same-message
sweep captures have timestamped filenames in `captures`.

Optional focused checks:

```powershell
python hardware_live/verify.py --mode HYBRID --coding qpsk_1_2
python hardware_live/server.py --build-only
```

The second command only builds and validates firmware. It does not execute
hardware tests. A missing board, wrong image, CRC mismatch, partial response,
DMA error or JTAG error produces a failure; no software result is substituted.

## Dynamic reconfiguration gate

The physical Full-PL -> blank -> Full-PL PCAP test passed; see DPR_VALIDATION.md and captures/dpr_final_evidence.json. The fourth mode remains active for real message sending after the switch. Its modem runs on ARM and all five decoder stages run in PL. This family uses a real 50 MHz PL preset and is not a clock-matched static speedup comparison.

The fourth UI mode is available only when the existing DPR project produces
a routed image family, passing timing/DRC and `pr_verify`, and packages matching
full/partial hashes and a build token. The bridge then stages partial images
over UART into board DDR, performs real `full_pl -> blank -> full_pl` PCAP
switches, validates generation/module identity and isolation status, and checks
a message plus all five stage buffers after switching. Upload time is recorded
separately from cached-PCAP switch time. Full raw evidence is exported.

Until those checks actually pass, the UI must say **not hardware-verified**.
See `DCS_FPGA/DPR/FULL_PL/hw/vivado/build_live.log` for the real implementation
attempt. No DPR success can be inferred from the presence of RTL, synthesis
checkpoints, a successful static reload, or an available UI button.

## Seven-segment timer and buzzer

The board files contain the four-digit display pins. The requested timing
display/buzzer add-on has **not been integrated into the running bitstreams**.
A future implementation should latch the existing measured interval, refresh
the display with independent logic, and issue nonblocking start/end tones
outside the timed software interval. For DPR, that controller belongs in the
static partition. It consumes real fabric resources and power and therefore
requires new reports, timing closure and an on/off benchmark comparison. A
PS-only decoder can still use PL for display support, but must be labeled that
way rather than claiming the entire PL is disabled.

The service binds only to loopback and validates Host, Origin and a per-session
control token. It does not expose arbitrary shell commands or file paths.
