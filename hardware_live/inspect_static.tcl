set root [file normalize [file dirname [info script]]]
open_checkpoint $root/../DCS_FPGA/DPR/FULL_PL/hw/vivado/build/dfx/static_synth.dcp
report_utilization -file $root/build/static_utilization.rpt
exit
