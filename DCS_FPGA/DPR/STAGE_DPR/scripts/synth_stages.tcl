set root [file normalize [lindex $argv 0]]
set out $root/hw/vivado/build_dpr/dfx
file mkdir $out
foreach stage {viterbi rs} {
 create_project -in_memory -part xc7z010clg400-1
 read_verilog [glob $root/hw/shared/*.v]
 read_verilog $root/hw/rm/$stage/rp_decoder.v
 synth_design -mode out_of_context -top rp_decoder -part xc7z010clg400-1
 report_utilization -file $out/${stage}_ooc_utilization.rpt
 write_checkpoint -force $out/${stage}_synth.dcp
 close_project
}
puts STAGE_SYNTHESIS_PASS
exit
