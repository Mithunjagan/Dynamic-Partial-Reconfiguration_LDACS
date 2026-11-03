# Physical-board validation

Final firmware evidence: `captures/api_verification_final.json`

Capture SHA256: `33a8417ca2ac83eb537fdbf158995dd23bcd1b89a06ba3140b4a8efffe466385`

24/24 physical modem/decoder cases passed. Completed cases were retained only when their firmware SHA256 matched the current image. All payload, Gray-QAM I/Q, recovered-bit, CRC32 and five stage-buffer checks passed. This is digital baseband loopback, not RF/OFDM or independent standards-conformance evidence.

| Architecture | Coding | Decoder mean (us) | Payload MB/s | Modem errors | Stages |
|---|---|---:|---:|---:|---:|
| PS | qpsk_1_2 | 748026.331 | 0.000730 | 0 | 5/5 |
| PS | qpsk_2_3 | 1006974.605 | 0.000723 | 0 | 5/5 |
| PS | qpsk_3_4 | 1138869.246 | 0.000719 | 0 | 5/5 |
| PS | 16qam_1_2 | 1495180.252 | 0.000730 | 0 | 5/5 |
| PS | 16qam_2_3 | 2013235.720 | 0.000723 | 0 | 5/5 |
| PS | 64qam_1_2 | 2242877.041 | 0.000730 | 0 | 5/5 |
| PS | 64qam_2_3 | 3020049.457 | 0.000723 | 0 | 5/5 |
| PS | 64qam_3_4 | 3419463.116 | 0.000719 | 0 | 5/5 |
| PL | qpsk_1_2 | 1421.582 | 0.384079 | 0 | 5/5 |
| PL | qpsk_2_3 | 1567.044 | 0.464569 | 0 | 5/5 |
| PL | qpsk_3_4 | 1639.782 | 0.499457 | 0 | 5/5 |
| PL | 16qam_1_2 | 2129.827 | 0.512718 | 0 | 5/5 |
| PL | 16qam_2_3 | 2418.048 | 0.602139 | 0 | 5/5 |
| PL | 64qam_1_2 | 2836.852 | 0.577401 | 0 | 5/5 |
| PL | 64qam_2_3 | 3269.321 | 0.668029 | 0 | 5/5 |
| PL | 64qam_3_4 | 3487.111 | 0.704595 | 0 | 5/5 |
| HYBRID | qpsk_1_2 | 10519.472 | 0.051904 | 0 | 5/5 |
| HYBRID | qpsk_2_3 | 10777.555 | 0.067548 | 0 | 5/5 |
| HYBRID | qpsk_3_4 | 10907.693 | 0.075085 | 0 | 5/5 |
| HYBRID | 16qam_1_2 | 20253.976 | 0.053915 | 0 | 5/5 |
| HYBRID | 16qam_2_3 | 20769.627 | 0.070102 | 0 | 5/5 |
| HYBRID | 64qam_1_2 | 30266.141 | 0.054120 | 0 | 5/5 |
| HYBRID | 64qam_2_3 | 31039.646 | 0.070362 | 0 | 5/5 |
| HYBRID | 64qam_3_4 | 31431.435 | 0.078170 | 0 | 5/5 |

Three measured repetitions follow one warm-up. Decoder time excludes UART, modem and trace replay. CPU cycles are elapsed clock cycles. Streaming stage times overlap. Each result retains raw headers, stage bytes, symbols, counters and image hashes. Earlier failed/incomplete attempts remain separate files and do not count as passed sweeps.

The final UART register snapshot was also physically checked (Hybrid VERSION 0x4C444333), followed by a successful message test; see `captures/post_register_smoke.json`. Seven-segment/buzzer is not integrated in these images. DPR is a separate validation.
