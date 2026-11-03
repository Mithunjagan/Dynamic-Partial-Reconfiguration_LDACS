# Keep project variables local; avoid collisions with Vivado Tcl framework state.
proc ldacs_create_dpr_project {} {
    global argv
# ============================================================================
# create_project.tcl - builds the EDGE Z7-10 (Zynq-7010) Vivado project
#
#   cd hw/vivado
#   vivado -mode batch -source create_project.tcl          (project + block design)
#   vivado -mode batch -source build.tcl                   (synth, impl, bitstream, .xsa)
#
# Block design (Fig. 4 of the paper, adapted to Zynq-7000):
#   PS7 (2x Cortex-A9) --GP0--> AXI interconnect --> AXI DMA (control)
#                                                --> ldacs_decoder_top (control)
#   AXI DMA M_AXIS_MM2S --> ldacs_decoder_top --> AXI DMA S_AXIS_S2MM
#   AXI DMA M_AXI_MM2S/S2MM --HP0--> DDR
# Written for Vivado 2020.2+ (tested flow names). If a step fails in your
# version, follow docs/VIVADO_GUI.md to make the same design by hand.
# ============================================================================
set enable_dpr [expr {[lsearch -exact $argv --static-hybrid] < 0}]
set proj_name ldacs_zed
set origin    [file normalize [file dirname [info script]]]
set build_root [file normalize $origin/build_dpr]
if {!$enable_dpr} {set build_root [file normalize $origin/build_static]}
set rtl_dir   [file normalize $origin/../static]
set board_repo [file normalize $origin/../../board_details]
set board_part allaboutfpga.com:edgez7_10:part0:1.0

# Board definition source: the checked-in copy of the official AllAboutFPGA
# EDGE board repository.  Set this before creating/selecting the board part so
# the batch build does not depend on a machine-wide Vivado catalog install.
# https://github.com/AllAboutFPGA/EDGE-FPGA-Kit-Board-Files
if {![file exists [file join $board_repo edgeZ7_10 A.0 board.xml]]} {
    error "EDGE Z7-10 board definition not found under: $board_repo"
}
set_param board.repoPaths [list $board_repo]

# Vivado 2022.2 embeds Tcl without the zlib command. The token is a build-family
# identity, not a security credential; keep it unsigned and nonzero.
set token [expr {(([clock clicks] ^ [pid]) & 0x7fffffff) + 1}]
file mkdir $build_root
set tokfile [open $build_root/build_token.txt w];puts $tokfile $token;close $tokfile
set modefile [open $build_root/topology.txt w]
puts $modefile [expr {$enable_dpr ? "receiver_dpr" : "static_hybrid"}]
close $modefile
file delete -force $build_root/source_snapshot.sha256
set marker [open $build_root/dfx_pending.txt w];puts $marker $token;close $marker
file mkdir $build_root/dfx
set marker [open $build_root/dfx/routed_manifest.json w];puts $marker { {"pr_verify_passed":false} };close $marker
# Reuse the validated static board/AXI integration when available. The copy
# excludes implementation results; all new DPR checkpoints are built separately.
set baseline [file normalize $origin/build/ldacs_zed/ldacs_zed.xpr]
if {$enable_dpr && [file exists $baseline]} {
    open_project $baseline
    save_project_as $proj_name $build_root/$proj_name -force -exclude_run_results
    open_bd_design [get_files system.bd]
    update_compile_order -fileset sources_1
    # Ports/parameters are unchanged; regenerate the copied BD after parameter edits.
    set_property CONFIG.BUILD_TOKEN $token [get_bd_cells dec]
    set_property CONFIG.STATIC_HYBRID 0 [get_bd_cells dec]
    validate_bd_design
    save_bd_design
    generate_target all [get_files system.bd]
    make_wrapper -files [get_files system.bd] -top
    set_property top system_wrapper [current_fileset]
    set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY none [get_runs synth_1]
    puts "DFX_PROJECT_FROM_VALIDATED_PLATFORM: $build_root/$proj_name/$proj_name.xpr"
    exit
}
create_project $proj_name $build_root/$proj_name -part xc7z010clg400-1 -force
if {[lsearch -exact [get_board_parts -quiet] $board_part] < 0} {
    error "Required EDGE board part was not found in board repository: $board_part"
}
set_property board_part $board_part [current_project]

puts "INFO: Target part set to xc7z010clg400-1 (EDGE Z7-10)"
puts "INFO: Board repository: $board_repo"
puts "INFO: Applying verified EDGE board preset: $board_part"


add_files -norecurse [glob $rtl_dir/*.v]
# Module-reference analysis must know both generate-branch implementations.
add_files -norecurse [glob $origin/../shared/*.v]
add_files -norecurse [list [file normalize $origin/../rm/hybrid/core.v]]
update_compile_order -fileset sources_1

create_bd_design system

# --- Zynq processing system ---
set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7 ps7]
# Apply the installed EDGE Z7-10 preset.  This supplies board-specific PS,
# DDR, UART, MIO, and fabric-clock settings; do not duplicate them here.
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
    -config {apply_board_preset "1"} $ps
# All configurations share the same 50 MHz static clock tree.
set_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {50} $ps
make_bd_intf_pins_external [get_bd_intf_pins ps7/DDR]
make_bd_intf_pins_external [get_bd_intf_pins ps7/FIXED_IO]


set_property -dict [list \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_USE_FABRIC_INTERRUPT {1} \
    CONFIG.PCW_IRQ_F2P_INTR {1}] $ps

# --- AXI DMA (direct register mode, 26-bit length for 29 kB frames) ---
set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma dma]
set_property -dict [list \
    CONFIG.c_include_sg {0} \
    CONFIG.c_sg_length_width {26} \
    CONFIG.c_sg_include_stscntrl_strm {0} \
    CONFIG.c_mm2s_burst_size {256} \
    CONFIG.c_s2mm_burst_size {256}] $dma
if {[catch {set_property CONFIG.c_m_axis_mm2s_tdata_width {8} $dma} err]} {
    puts "WARNING: could not set MM2S stream width to 8: $err"
}

# --- LDACS decoder (RTL module reference) ---
set dec [create_bd_cell -type module -reference dpr_shell dec]
set_property CONFIG.BUILD_TOKEN $token $dec
set_property CONFIG.STATIC_HYBRID [expr {!$enable_dpr}] $dec

connect_bd_intf_net [get_bd_intf_pins dma/M_AXIS_MM2S] [get_bd_intf_pins dec/s_axis]
connect_bd_intf_net [get_bd_intf_pins dec/m_axis]     [get_bd_intf_pins dma/S_AXIS_S2MM]

# --- AXI connections (automation adds interconnects, clocks, resets) ---
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} Master {/ps7/M_AXI_GP0} Slave {/dma/S_AXI_LITE} intc_ip {New AXI Interconnect} master_apm {0}} \
    [get_bd_intf_pins dma/S_AXI_LITE]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} Master {/ps7/M_AXI_GP0} Slave {/dec/s_axi_ctrl} intc_ip {Auto} master_apm {0}} \
    [get_bd_intf_pins dec/s_axi_ctrl]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} Master {/dma/M_AXI_MM2S} Slave {/ps7/S_AXI_HP0} intc_ip {New AXI Interconnect} master_apm {0}} \
    [get_bd_intf_pins ps7/S_AXI_HP0]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 \
    -config {Clk_master {Auto} Clk_slave {Auto} Clk_xbar {Auto} Master {/dma/M_AXI_S2MM} Slave {/ps7/S_AXI_HP0} intc_ip {Auto} master_apm {0}} \
    [get_bd_intf_pins dma/M_AXI_S2MM]

# decoder clock / reset (if automation did not already connect them)
if {[llength [get_bd_nets -quiet -of_objects [get_bd_pins dec/aclk]]] == 0} {
    connect_bd_net [get_bd_pins ps7/FCLK_CLK0] [get_bd_pins dec/aclk]
}
if {[llength [get_bd_nets -quiet -of_objects [get_bd_pins dec/aresetn]]] == 0} {
    set rst [lindex [get_bd_cells -quiet -filter {VLNV =~ "*proc_sys_reset*"}] 0]
    connect_bd_net [get_bd_pins $rst/peripheral_aresetn] [get_bd_pins dec/aresetn]
}
if {[llength [get_bd_nets -quiet -of_objects [get_bd_pins dma/axi_resetn]]] == 0} {
    set rst [lindex [get_bd_cells -quiet -filter {VLNV =~ "*proc_sys_reset*"}] 0]
    connect_bd_net [get_bd_pins $rst/peripheral_aresetn] [get_bd_pins dma/axi_resetn]
}

# interrupts (not used by the polling driver, but available for later)
set cc [create_bd_cell -type ip -vlnv xilinx.com:ip:xlconcat irq_concat]
set_property CONFIG.NUM_PORTS {2} $cc
connect_bd_net [get_bd_pins dma/mm2s_introut] [get_bd_pins irq_concat/In0]
connect_bd_net [get_bd_pins dma/s2mm_introut] [get_bd_pins irq_concat/In1]
connect_bd_net [get_bd_pins irq_concat/dout]  [get_bd_pins ps7/IRQ_F2P]

assign_bd_address
set_property offset 0x40400000 [get_bd_addr_segs ps7/Data/SEG_dma_Reg]
set_property offset 0x40000000 [get_bd_addr_segs ps7/Data/SEG_dec_reg0]
puts "==== Address map (put these into sw/src/main.c or pass --dma/--dec) ===="
foreach seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces ps7/Data]] {
    puts [format "  %-40s 0x%08X" [get_property NAME $seg] [get_property OFFSET $seg]]
}

validate_bd_design
save_bd_design

# Generate block-design IP checkpoints before top-level synthesis. This avoids
# relying on asynchronous out-of-context run scheduling in batch mode.
generate_target all [get_files system.bd]

make_wrapper -files [get_files system.bd] -top
add_files -norecurse [glob -nocomplain $build_root/$proj_name/$proj_name.gen/sources_1/bd/system/hdl/system_wrapper.v \
                           $build_root/$proj_name/$proj_name.srcs/sources_1/bd/system/hdl/system_wrapper.v]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1
puts "INFO: project created: $build_root/$proj_name/$proj_name.xpr"

set_property STEPS.SYNTH_DESIGN.ARGS.FLATTEN_HIERARCHY none [get_runs synth_1]

}
ldacs_create_dpr_project
