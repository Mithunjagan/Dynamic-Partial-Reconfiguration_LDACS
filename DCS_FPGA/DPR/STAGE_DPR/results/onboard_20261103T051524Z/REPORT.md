# Stage-multiplexed LDACS DPR: measured results

Completed 2026-11-03T05:21:56.397029+00:00; EDGE Z7-10, build token 411869786.

PASS: 48 frames across eight modes, 20 genuine stage transfers, 144 exact intermediate/final buffer comparisons; static continuity passed during every transfer.

Peak complete-configuration LUTs: 8723, versus 11480 for the prior combined HYBRID RM: 2757 fewer (24.02%). Both include static infrastructure.

| Configuration | LUT | FF | BRAM36 equivalents | DSP | WNS ns | WHS ns |
|---|---:|---:|---:|---:|---:|---:|
| viterbi | 8723 | 5417 | 50 | 0 | 4.451 | 0.019 |
| rs | 6198 | 5046 | 6.5 | 1 | 3.442 | 0.019 |

The RP alternates between Viterbi + bit packing and RS. Block deinterleaving is static. PS helical deinterleaving and derandomization are unchanged. Intermediate frames live in bounded DDR slots. The frame-aligned Pblock geometry is retained because Viterbi still requires 44 RAMB36s; occupied LUT savings do not imply that this reserved region is available to unrelated static logic.

| Mode | Batch | Compute/integrity ms per batch | PCAP ms per batch | CRC precheck ms per batch | Accounted service ms/frame | Execution wall s |
|---|---:|---:|---:|---:|---:|---:|
| qpsk_1_2 | 1 | 24.190 | 36.487 | 1420.625 | 1481.725 | 1.713 |
| qpsk_2_3 | 1 | 11.547 | 36.491 | 1420.617 | 1469.077 | 1.713 |
| qpsk_3_4 | 1 | 11.849 | 36.488 | 1420.615 | 1469.375 | 1.698 |
| 16qam_1_2 | 1 | 20.553 | 36.491 | 1420.616 | 1478.083 | 1.693 |
| 16qam_2_3 | 1 | 21.762 | 36.494 | 1420.620 | 1479.299 | 1.721 |
| 64qam_1_2 | 1 | 30.117 | 36.493 | 1420.613 | 1487.646 | 1.721 |
| 64qam_2_3 | 1 | 31.899 | 36.497 | 1420.624 | 1489.442 | 1.735 |
| 64qam_3_4 | 1 | 32.749 | 36.497 | 1420.621 | 1490.290 | 1.747 |
| qpsk_1_2 | 8 | 87.520 | 36.494 | 1420.617 | 193.132 | 1.770 |
| qpsk_1_2 | 32 | 350.077 | 36.499 | 1420.629 | 56.488 | 1.940 |

Every batch includes Viterbi and RS partial loading, including image CRC verification. Accounted service sums measured board intervals, excludes UART staging and host command gaps, and includes DMA, copies and payload integrity. Execution wall time includes commands/responses from the first partial load to the RS batch response; it excludes input staging and trace retrieval. Derived service rate is not uninterrupted measured receiver throughput. No warm-ups were used. The prior 800-frame benchmark uses a different execution scope and cannot be treated as a direct speedup comparison.

Every frame passed CRC and exact comparisons of static-deinterleaver output, raw RS output and final payload. All eight modes were checked at batch size 1; QPSK 1/2 was also checked at 8 and 32. The new table CRC is still recomputed before every image load. All image/firmware hashes, raw timing/continuity replies and actual byte buffers remain in evaluation.json.

Boot: 19.741 s; entire evaluation: 391.457 s. UART image staging:

- viterbi: 1683900 bytes in 146.998 s.
- rs: 1683900 bytes in 146.998 s.

Both routed configurations passed DRC/timing, and the RS checkpoint passed full pr_verify against Viterbi with identical static routing. This is a receiver-loopback experiment, without RF/OFDM, independent standards conformance, measured power, or a claimed real-time deadline.
