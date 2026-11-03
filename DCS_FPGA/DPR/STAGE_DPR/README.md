# LDACS stage-multiplexed DPR

Implemented and [validated on board](results/onboard_20261103T051524Z/REPORT.md):
peak complete-configuration LUT usage is 8723 versus 11480 for the combined
HYBRID receiver (24.02% lower). Both RMs passed timing/DRC and full pr_verify.
The physical run passed 48 frames, 20 stage transfers and 144 exact buffer checks.
QPSK batch size 32 accounts for 56.488 ms of service per frame, versus 1481.725 ms
for the first single-frame batch. This is an area/latency tradeoff; the reserved
Pblock is unchanged and no uninterrupted real-time throughput is established.

This separate experiment shares one RP between Viterbi + bit packing (ID 0)
and Reed–Solomon (ID 1). The block deinterleaver, AXI routing/isolation, DMA,
clocks/reset and heartbeat are static. ARM handles helical deinterleaving,
derandomization and batch scheduling. The working whole-receiver HYBRID family
and all its measurements remain under `../HYBRID`.

Frames flow through Viterbi and the static deinterleaver into DDR. Once every
frame in the batch is buffered, RS replaces Viterbi and consumes those buffers.
All RMs use the same ports. Static configuration mirrors keep the deinterleaver
configured across stage changes; it is reset and drained before replacement.

Build from the repository root:

```powershell
python DCS_FPGA/DPR/STAGE_DPR/scripts/test_rtl.py --quick
python -m unittest discover -s DCS_FPGA/DPR/STAGE_DPR/tests
python DCS_FPGA/DPR/STAGE_DPR/scripts/build_dpr.py
python DCS_FPGA/DPR/STAGE_DPR/build_firmware.py
python DCS_FPGA/DPR/STAGE_DPR/scripts/evaluate_stage.py
```

Early OOC area estimates can be generated with `scripts/synth_stages.tcl`.
The current implementation run reuses those checkpoints, guarded by the source
and checkpoint hashes in `build/early_synth.json`, to avoid repeating synthesis.
`--reuse-stage-synth` requires that audited cache. Source pins and fresh tokens
prevent mixing this family with the older HYBRID partials.

The initial floorplan retains the proven frame-aligned clock-region geometry:
Viterbi still needs 44 RAMB36s, so a smaller LUT count does not establish a smaller
reserved physical footprint. New reports determine actual occupied LUTs, FFs,
BRAM and DSP; no physical reclamation claim is made from OOC counts.

The new stage firmware retains CRC validation at upload and before every PCAP
load. A tested table-based CRC reduces computation without caching acceptance.
Any PCAP failure latches a fault and requires full reinitialization. Static
heartbeat and identity are sampled during each load. No DMA runs concurrently
with reconfiguration; static deinterleaver output must drain first.

Batch memory is bounded to 64 disjoint 64-KiB slots beginning at 0x06000000.
Each slot stores coded input at +0, deinterleaved RS codewords at +0x8000,
raw RS output at +0x9000, and final payload at +0xa000. These addresses do not
overlap firmware, DMA scratch buffers or the PCAP image cache. Each UART input
frame is acknowledged after helical deinterleaving to prevent FIFO overflow.

The bounded evaluation checks all eight modes with batch size 1 and QPSK 1/2
with sizes 8 and 32: 48 frames and 20 real partial transfers. Every frame gets
CRC and exact intermediate/final buffer checks. The run uses no warm-ups, and
keeps UART image staging and frame staging outside its board-service accounting.
That accounting sums measured PS/DMA/integrity and switch-service intervals;
it excludes host command gaps. Execution wall time is also recorded separately,
including commands and responses but excluding initial input staging and traces.
The derived service rate is not a measured uninterrupted receiver throughput.

Raw results and failures are retained in `results/onboard_*`. A successful family
must pass DRC, timing and full `pr_verify` before the evaluation will boot it.
