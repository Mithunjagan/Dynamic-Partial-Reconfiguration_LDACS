# Benchmarks for the four selected designs

Reused existing physical EDGE Z7-10 / XC7Z010 board measurements. No hardware benchmarks were rerun for this consolidation.

| Design | Profiles | Timed frames | Source |
|---|---:|---:|---|
| Full PS | 8 | 24 (3/profile) | Physical API verification, 30 October 2026 |
| Full PL decoder | 8 | 800 (100/profile) | Completed architecture section, 3 November 2026 |
| Hybrid | 8 | 800 (100/profile) | Completed architecture section, 3 November 2026 |
| Latest stage-sharing DPR | 8 | 48 | Passed onboard run, 3 November 2026 |

The PL/Hybrid sections are complete and individually checked, although their enclosing campaign stopped on a later PS UART timeout. The failed PS attempt supplies no benchmark data here. PS results come from the earlier successful capture; its firmware and fabric-image hashes match current files.

## Static decoder measurements

All five decoder stages are included. DMA/control is included for accelerated designs. UART, modem, CRC verification and trace replay are excluded. Throughput is payload bits divided by board-measured decode time; it is not uninterrupted input-stream throughput.

| Profile | Full PS mean ms | Full PL mean ms | Hybrid mean ms |
|---|---:|---:|---:|
| qpsk_1_2 | 748.026331 | 1.421683 | 10.503020 |
| qpsk_2_3 | 1006.974605 | 1.566790 | 10.763155 |
| qpsk_3_4 | 1138.869246 | 1.639861 | 10.892935 |
| 16qam_1_2 | 1495.180252 | 2.129952 | 20.222662 |
| 16qam_2_3 | 2013.235720 | 2.418093 | 20.737755 |
| 64qam_1_2 | 2242.877041 | 2.836829 | 30.202875 |
| 64qam_2_3 | 3020.049457 | 3.268733 | 30.975587 |
| 64qam_3_4 | 3419.463116 | 3.486940 | 31.362241 |

Different profiles have different payload lengths. Compare architectures within the same profile. PS used saved text payloads; PL/Hybrid used RNG seed 91. Payload sizes and coding profiles agree, but PS-versus-accelerator speedups are descriptive comparisons across sessions, not an identical-input paired experiment. All selected timed cases passed CRC and final-output checks, with all five trace buffers matching the reference. PS sample count is smaller; per-frame percentiles are unavailable. Batch-mean standard deviation for PL/Hybrid is not per-frame jitter.

## Latest stage-sharing DPR

Viterbi/packing and RS alternate in one reconfigurable partition; block deinterleaving is static. Exact current image-family, firmware and full/partial image hashes were checked. The preserved run passed 48 frames, 20 genuine PCAP transfers, 144 intermediate/final buffer checks, and static continuity during every transfer.

| Profile | Batch | Compute/integrity ms per batch | PCAP ms per batch | CRC precheck ms per batch | Service ms/frame |
|---|---:|---:|---:|---:|---:|
| qpsk_1_2 | 1 | 24.190 | 36.487 | 1420.625 | 1481.725 |
| qpsk_2_3 | 1 | 11.547 | 36.491 | 1420.617 | 1469.077 |
| qpsk_3_4 | 1 | 11.849 | 36.488 | 1420.615 | 1469.375 |
| 16qam_1_2 | 1 | 20.553 | 36.491 | 1420.616 | 1478.083 |
| 16qam_2_3 | 1 | 21.762 | 36.494 | 1420.620 | 1479.299 |
| 64qam_1_2 | 1 | 30.117 | 36.493 | 1420.613 | 1487.646 |
| 64qam_2_3 | 1 | 31.899 | 36.497 | 1420.624 | 1489.442 |
| 64qam_3_4 | 1 | 32.749 | 36.497 | 1420.621 | 1490.290 |
| qpsk_1_2 | 8 | 87.520 | 36.494 | 1420.617 | 193.132 |
| qpsk_1_2 | 32 | 350.077 | 36.499 | 1420.629 | 56.488 |

DPR service includes both partial loads, CRC prechecks, DMA, copies and payload integrity. It excludes UART image/input staging and host gaps. Execution wall time has a separate field. Do not treat these values as the same interval as static decoder-only latency. Batch sizes 8/32 were measured only for QPSK 1/2; other combinations remain unmeasured.

Stage DPR uses approximately 50 MHz PL; static PL/Hybrid clocks come from their raw firmware replies (approximately 71.43 MHz). Stage DPR peak occupied LUTs are 8723. The reported 24.02% reduction refers to the preserved 11480-LUT whole-receiver DPR baseline, which is excluded from this selected-design performance comparison. The Pblock reservation did not shrink.

## Files and limits

- decoder.csv: means, min/max, sample counts, payload throughput, clocks, errors and speedup relative to PS.
- decoder_stages.csv: all five measured stage latencies.
- stage_sharing_dpr.csv / stage_sharing_swaps.csv: service, compute, CRC, PCAP, upload-independent switching and continuity.
- resources.csv: routed LUT/FF/BRAM/DSP and timing slack; implementation metadata rather than live activity.
- modem.csv: saved physical ARM digital-loopback modulation/demodulation measurements for all 24 static cases.
- end_to_end.csv: saved PL/Hybrid single-message wall measurements, three/profile, including host encode, physical UART modem/decode and verification. Equivalent full-wall PS measurements are unavailable.
- manifest.json: source hashes, selected scope and 80 binary UART response audits.

Power/energy is excluded at user request. RF/SNR equipment is unavailable. No RF reception, BER-vs-SNR, sustained continuous-stream rate, CPU utilization or real-time deadline compliance is claimed. These saved results share SPEC-CHECK constants and do not establish independent LDACS conformance.

This is a reproducible project benchmark using saved board evidence, not an externally certified standard benchmark. Existing sample counts, seeds and timing boundaries are preserved; results from different sessions are not pooled into invented per-frame distributions.
