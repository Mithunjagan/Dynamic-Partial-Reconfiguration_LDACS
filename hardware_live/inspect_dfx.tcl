set project [file normalize [file dirname [info script]]/../DCS_FPGA/DPR/FULL_PL/hw/vivado/build/ldacs_zed/ldacs_zed.xpr]
open_project $project
open_run synth_1
foreach cell [get_cells -hier -filter {IS_BLACKBOX == 1}] {puts "BLACKBOX: $cell / [get_property REF_NAME $cell]"}
foreach cell [get_cells -hier -filter {NAME =~ */rp}] {puts "RP: $cell / [get_property REF_NAME $cell]"}
exit
