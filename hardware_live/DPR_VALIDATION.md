# Physical DPR validation

Actual PCAP full_pl -> blank -> full_pl round trip passed. All five post-switch stage buffers and exact payload matched. Digital baseband modem runs on ARM; decoder runs in the reconfigurable FPGA module. No RF/OFDM or seven-segment/buzzer is claimed.

| Target | PCAP us | Total switch us | Service total us |
|---|---:|---:|---:|
| blank | 18088.770 | 18298.389 | 3623470.551 |
| full_pl | 18089.799 | 18299.406 | 3623474.481 |

UART partial-image uploads are excluded from switch timing and retained separately in raw evidence. DPR PL clock is 50 MHz; static-mode clocks are separate.

A subsequent custom 64-QAM message also passed in the active DPR platform with zero modem bit errors and 5/5 stage matches. See captures/final_live_state.json.
