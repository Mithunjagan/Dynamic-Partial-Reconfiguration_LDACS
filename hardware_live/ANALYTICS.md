# Fresh physical benchmark analytics

The dashboard is at http://127.0.0.1:8767. The physical bridge at :8765 must remain running. A link is also in the board console's top bar.

Start the physical bridge if necessary:

```powershell
python hardware_live/server.py
```

In a second terminal, start analytics and a new physical campaign:

```powershell
python hardware_live/analytics_server.py --start --live --repeat-all
```

`--start` measures all eight coding profiles for PS, PL, Hybrid and, when the bridge reports its verified image family available, DPR. Every architecture is booted and physically verified. `--no-dpr` selects the three static architectures. Without `--start`, use the dashboard's start button. The start button also exposes the DPR and continuing-sampling choices.

`--live --repeat-all` repeats every architecture/profile sequentially on the single board. Each entry retains its last actual sample timestamp; a complete cycle takes several minutes, especially the UART staging of DPR images. With `--live` alone, the service continues sampling DPR / QPSK 1/2 after the complete four-mode sweep (Hybrid / QPSK 1/2 when DPR is excluded), waiting five seconds between transactions. Other matrix cells retain their original measurement timestamps. Page updates occur every second; a new observation appears only after the actual hardware transaction completes. Stop waits for the active physical job to finish. It never interrupts a JTAG transfer or decode.

No prior capture or stored benchmark is read. Each campaign creates `benchmarks/live_analytics/<UTC timestamp>/evidence.json`. Failed campaigns remain in their own directories. Individual bridge transactions are also retained by the original bridge. Only responses after the current request start are eligible. Successful measurements must pass exact recovered-message, CRC/RS, all five stage-buffer hashes, counter arithmetic, input-frame equality and image-provenance checks. Inputs for a profile are identical across architectures. Stored implementation resource/power reports are removed from the analytics data.

Charts compare latency (observed mean/min/max), decoder payload throughput, every profile/architecture, stage duration, host-observed wall time, actual sample history, modem timings and DPR switches. The faculty section identifies implementation and instrumentation additions separately from observed measurements. CSV exports the latest entry per architecture/profile. JSON exports raw counters, trace buffers, I/Q values, image hashes, failures and measurement timestamps.

Important boundaries: decoder throughput uses padded frame payload and resident-frame timing, not useful text rate or continuous UART/RF throughput. Host timing includes diagnostics and HTTP polling. Stage timings overlap. Min/max over three decodes cannot establish p95/p99. CPU clock cycles are elapsed time, not CPU utilization. DPR has a different PL clock. Power, RF performance, independent LDACS conformance and fresh resource allocation are not measured.

The companion only accesses the fixed loopback bridge and never opens COM5. It has loopback binding, Host/Origin checks and a per-service control token. Keep other console clients idle during a campaign. Firmware and decoding algorithms are unchanged. The bridge now pauses one second after firmware start before its identity probe, and retries only a boot probe that returned zero bytes once. This addresses the observed C-startup/UART-reset race; no failed decode is accepted or replaced.

Read-only verification of the real page:

```powershell
python hardware_live/verify_analytics.py
```

The browser check uses the actual local service, with no test transport or dummy observations. Results and screenshots are written to `dev/analytics/`.

To continue missing entries in this same campaign after a service restart, use `--resume <run_id> --live --repeat-all`. This validates the existing campaign evidence, preserves its original acquisition times, and does not import measurements from before that campaign. Failed boot attempts remain in raw evidence and receive a resolution time once fresh entries succeed.
