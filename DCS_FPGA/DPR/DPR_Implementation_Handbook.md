# Dynamic Partial Reconfiguration (DPR/DFX)

## Implementation Handbook

**Purpose:** A design-independent checklist for implementing Dynamic Partial Reconfiguration in an existing FPGA design.

**Methodology:** AMD/Xilinx **Dynamic Function eXchange (DFX)**, adapted to the actual FPGA family and Vivado version.

---

## 1. Objective

Implement Dynamic Partial Reconfiguration (DPR) so that selected hardware modules can be replaced **at runtime**, while the static portion of the FPGA continues operating.

## 2. Initial Design Analysis

- Identify the **FPGA family**, exact **part number**, **board**, and **Vivado version**.
- Inspect existing RTL, IP, constraints, clocks, resets, and design hierarchy.
- Confirm that the target device and toolchain support DFX.
- Identify logic that must remain **static** and logic that should be **reconfigurable**.
- Preserve existing functionality wherever possible.

## 3. Design Partitioning

- Divide the design into a **Static Region** and one or more **Reconfigurable Partitions (RPs)**.
- Identify all **Reconfigurable Modules (RMs)** associated with each RP.
- Ensure every RM for a given RP has the **same partition-level interface** (ports, widths, directions, and required interface behavior).
- Keep configuration control, essential clocks/resets, communication management, and critical system services in the static region.

## 4. Floorplanning and Pblock Creation

- Create a physical **Pblock** for each RP.
- Provide sufficient **LUT, flip-flop, BRAM, DSP, and routing resources** for every interchangeable RM.
- Follow device-specific Pblock alignment, configuration-frame, clock-region, and resource restrictions.
- Mark each RP with the appropriate **`HD.RECONFIGURABLE`** property.
- Consider **`RESET_AFTER_RECONFIG`** only where supported and suitable for the specific architecture.
- Verify Pblock legality, placement feasibility, and timing constraints.

## 5. Synthesis and Implementation

1. Synthesize the static logic and RMs according to the supported DFX flow.
2. Implement the **initial configuration**, containing the static logic and initial RMs.
3. Save the fully routed **design checkpoint (`.dcp`)**.
4. Produce the required **static-only checkpoint** and preserve static placement and routing.
5. Implement alternative RMs against the **same preserved static implementation**.
6. Save routed checkpoints for all implemented configurations.

> **Key rule:** Compatible configurations must use an identical static implementation; alternative RMs cannot arbitrarily alter static placement or routing.

## 6. Verification

Verify each configuration before deployment:

- Design Rule Checks (**DRC**)
- Resource utilization and Pblock fit
- Setup and hold timing
- Clock and reset compatibility
- Partition interface consistency
- Preservation of the static implementation
- DFX configuration compatibility using **`pr_verify`**
- Functional behavior using simulation and, later, hardware testing

**Do not treat `pr_verify` as a substitute for functional validation.** Resolve critical implementation or verification failures before hardware deployment.

## 7. Bitstream Generation

Generate and organize:

- A **full bitstream** for initial FPGA programming.
- **Partial bitstreams** for the implemented RM configurations.
- Required deployment metadata, software artifacts, and configuration files, as applicable.

**Compatibility rule:** Every partial bitstream must match the intended FPGA device, RP, and exact compatible static implementation/build. Never mix unrelated builds.

## 8. Runtime Reconfiguration

### 8.1 Select the Configuration Interface

- **ICAP (Internal Configuration Access Port):** Configuration controlled from the programmable logic (PL).
- **PCAP (Processor Configuration Access Port):** Configuration controlled by the processing system (PS) on supported Zynq devices.
- **Other configuration interfaces:** Use the device-family-specific mechanism where appropriate.

### 8.2 Safe Reconfiguration Sequence

1. Request a reconfiguration.
2. Stop new transactions; finish or safely terminate outstanding transactions.
3. **Decouple/isolate** the RP from the static logic.
4. Load the compatible partial bitstream through the selected configuration interface.
5. Check configuration completion and handle errors.
6. Reset/initialize the newly configured module as required.
7. Reconnect interfaces and resume operation.

Use **DFX Decoupler**, **DFX AXI Shutdown Manager**, or equivalent suitable isolation/control logic as needed.

## 9. Hardware Validation

- Verify correct behavior before and after DPR.
- Confirm that the **static region remains operational** throughout the reconfiguration.
- Test repeated swaps between compatible RMs.
- Check data integrity and interface behavior at reconfiguration boundaries.
- Measure and record **resource utilization**, **timing slack**, **bitstream size**, and **reconfiguration latency**.
- Test safe recovery from a failed or interrupted configuration, where practical.

## 10. Mandatory Design Rules

1. Preserve the **same static placement and routing** across compatible configurations.
2. Maintain an identical **partition interface contract** for all RMs of the same RP.
3. Ensure **every RM fits** within its assigned Pblock and permitted FPGA resources.
4. Follow **device-specific DFX rules** for clocks, resets, routing, primitives, and Pblock boundaries.
5. Ensure transient RP outputs cannot corrupt static logic while the RP is being reconfigured.
6. Never load **incompatible partial bitstreams** into a running design.
7. Use documentation corresponding to the project's **exact FPGA family and Vivado version**.

## 11. Required Deliverables

- [ ] Updated RTL and IP configurations
- [ ] XDC timing and floorplanning constraints
- [ ] Reproducible Vivado Tcl scripts or DFX project
- [ ] Routed design checkpoints and implementation reports
- [ ] Full and partial bitstreams (if successfully generated)
- [ ] Configuration controller/software (where required)
- [ ] Simulation and verification results
- [ ] Timing and resource utilization reports
- [ ] Hardware testing results (if actual hardware testing was completed)
- [ ] README with build, deployment, and reconfiguration instructions

## 12. Instructions to Codex

> First analyze the existing project and select the correct DFX workflow based on the **actual FPGA architecture**, design, and installed tools.
>
> Do **not** insert arbitrary example modules or replace working functionality unnecessarily.
>
> Implement incrementally, preserve successful checkpoints, validate each stage, and report blockers explicitly.
>
> **Never claim** successful synthesis, timing closure, bitstream generation, or hardware testing without real evidence from the tools or target hardware.

## 13. Reference

- [AMD Vivado Dynamic Function eXchange User Guide (UG909)](https://docs.amd.com/r/en-US/ug909-vivado-partial-reconfiguration) — use documentation matching the installed Vivado release.
- Consult the relevant **device technical reference manual** for supported configuration interfaces, device restrictions, and runtime loading procedures.
