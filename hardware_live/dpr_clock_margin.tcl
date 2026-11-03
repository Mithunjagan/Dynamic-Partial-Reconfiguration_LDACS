# Reuse the generated project and functional RM checkpoints, while rebuilding
# the actual PS preset/static shell at 50 MHz. No fake XDC clock relaxation.
set root [file normalize [file dirname [info script]]/../DCS_FPGA/DPR/FULL_PL/hw/vivado]
open_project $root/build/ldacs_zed/ldacs_zed.xpr
open_bd_design [get_files system.bd]
set_property CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {50} [get_bd_cells ps7]
validate_bd_design
save_bd_design
generate_target all [get_files system.bd]
close_project
exit
