# Stage DPR status

This variant is separate from the validated whole-receiver HYBRID implementation.

- Implemented: Viterbi/packing and RS RMs with a common partition interface.
- Implemented: static block deinterleaving and stage-dependent stream routing.
- Implemented: bounded DDR batch scheduler with per-frame UART flow control.
- Implemented: verified table CRC; image integrity remains checked before every load.
- Passed: 21 native PCAP/CRC/scheduler tests and four XSim datapath tests covering noisy QPSK and largest 64-QAM.
- Built: Cortex-A9 stage firmware, with validated ELF layout.
- Passed: early OOC synthesis (Viterbi 5553 LUT, RS 2945 LUT).
- Passed: both complete configurations routed; timing/DRC and full pr_verify passed. Peak LUT count is 8723 versus 11480 for the combined HYBRID family (24.0% lower).
- Passed on board: 48 frames, eight modes, 20 actual PCAP stage swaps, 144 exact intermediate/final buffer comparisons; continuity preserved during all swaps.
- Measured QPSK accounted service: batch 1 = 1481.725 ms/frame; batch 8 = 193.132 ms/frame; batch 32 = 56.488 ms/frame.
- Results: results/onboard_20261103T051524Z/REPORT.md, evaluation.json, summary.json and summary.csv.
- Limitations: unchanged Pblock geometry; higher scheduling latency; no uninterrupted real-time receiver throughput claim.

Source tests are recorded in build/source_validation.json. The current build log
is linked by build/handbook_dpr/latest_build.json. Firmware and full/partial images
are not compatible with the older HYBRID family.
