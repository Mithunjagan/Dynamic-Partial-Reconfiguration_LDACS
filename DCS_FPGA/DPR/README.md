# LDACS DPR implementation

The area-saving [STAGE_DPR variant](STAGE_DPR/README.md) now shares one partition
between Viterbi/packing and RS, with static block deinterleaving and DDR batch
buffers. Its [measured report](STAGE_DPR/results/onboard_20261103T051524Z/REPORT.md)
records 24.02% fewer peak occupied LUTs, 20 genuine swaps and 48 correct frames.
Switching adds latency; the original whole-receiver HYBRID build described below
is preserved as the comparison baseline. These variants use separate firmware
and incompatible partial-image families.

The current implementation follows [DPR_Implementation_Handbook.md](DPR_Implementation_Handbook.md).
The default HYBRID path is now a real reconfigurable receiver, with separate
build products from the validated static baseline. See
[HYBRID/README.md](HYBRID/README.md) for build, boot and measurement commands, and
[IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) for tool-backed progress.

| Region / module | Placement / role |
|---|---|
| PS, DDR, UART, AXI DMA/interconnect, FCLK/reset | Static |
| AXI proxy, isolation, identity/generation, heartbeat | Static |
| `hybrid`, ID 0 | RM: Viterbi, bit packing, block deinterleaving, RS |
| `full_pl`, ID 1 | RM: complete receiver chain |
| `blank`, ID 2 | Existing idle RM |
| `anchor`, ID 3 | Existing diagnostic RM |

There is one RP, with identical ports for all four RMs. All compatible partials
must come from the same locked static implementation and pass `pr_verify`.
FULL_PS still runs its decoder on ARM; it never reconfigures the processor.

The old static HYBRID board evaluation is real evidence for that static build,
not evidence of a new partial switch. New DPR evidence is recorded separately
under `HYBRID/results/dpr_*` only after actual PCAP transfers and post-switch checks.
Runtime safe-rejection tests do not intentionally load incompatible bitstreams.
The [completed DPR evaluation](HYBRID/results/dpr_20261102T195022Z/REPORT.md)
records six physical HYBRID/blank swaps, continuity during every PCAP transfer,
800 timed frames across eight modes and 40/40 stage-buffer matches. PCAP took
about 18.2 ms; complete service including the software CRC precheck took 3.727 s.
Mocked fault tests cover queue/init errors, interrupts, timeout, frozen heartbeat,
changed identity and fault latching. Physical interrupted-transfer recovery is
not claimed unless explicitly recorded.

Source baseline history is preserved: `preserved_sources_20261029.json` contains
the original hashes and `baseline_history.json` records the November 2 baseline
reconciliation. Run `python DPR/verify_preserved.py` from `DCS_FPGA`.

Clock and reset constraints follow the installed Vivado release and 7-series
architecture. Source references:
[UG909 2022.2: 7-series Pblocks](https://docs.amd.com/r/2022.2-English/ug909-vivado-partial-reconfiguration/Creating-Pblocks-for-7-Series-Devices),
[Xilinx 2022.2 DevCfg registers](https://github.com/Xilinx/embeddedsw/blob/xilinx_v2022.2/XilinxProcessorIPLib/drivers/devcfg/src/xdevcfg_hw.h).

CRC precheck and UART image staging are separate from PCAP transfer timing.
Traffic is serialized; concurrent frame queues/fallback scheduling are not implemented.
Vivado power is estimated, and RF/OFDM and independent LDACS standards conformance
remain outside this receiver-loopback evaluation.
